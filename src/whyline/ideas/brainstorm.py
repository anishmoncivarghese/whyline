"""Brainstorm an idea in the inbox workspace, never in a user repository.

The settings card starts from every unattended agent that can run here.
``run`` calls the console brainstorm runner in ``paths.workspace()``. That
folder becomes a git repository the first time a brainstorm needs it. When
the final writer fails, the next backup writes the synthesis. The finished
document is copied under the inbox home and queued for Telegram.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from whyline.agents import capabilities
from whyline.ideas import documents, intent, paths, store

_ACTOR = "brainstorm"
_DETECT_ORDER = ("claude", "codex", "grok")
_AGENTS_KEY = "default_agents"
_UNATTENDED = "not cleared for unattended runs"
_PASSES = (1, 2, 3)
_TIMEOUTS = (15, 30, 45, 60, "none")
_MINUTE = 60.0
_GIT_EMAIL = "inbox@whyline.local"
_GIT_NAME = "Whyline Inbox"
_EMPTY_COMMIT = "inbox: create workspace"

# The example the card shows, so a reply can copy it.
TEMPLATE = "\n".join((
    "models: claude, codex, grok",
    "passes: 1",
    "final: claude",
    "backup: codex",
    "timeout: 30",
))
SETTINGS_BUTTONS = (
    ("Start brainstorm", "start_brainstorm"),
    ("Edit", "edit"),
    ("Cancel", "cancel"),
)
RESULT_BUTTONS = (
    ("Create spec and plan", "plan"),
    ("Brainstorm again", "brainstorm"),
    ("Drop", "drop"),
)
_BRAINSTORM_KEYS = frozenset({"models", "passes", "final", "backup", "timeout"})
_LIST_KEYS = frozenset({"models", "backup"})


class SettingsError(ValueError):
    """A settings line is not one this card accepts. The message names it."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = tuple(lines)
        super().__init__("\n".join(lines))


class BrainstormError(RuntimeError):
    """The run did not produce a synthesis. The idea is back at captured."""


class _Stopped(Exception):
    """The cancel event fired. Not a writer failure."""


class _WriterFailed(Exception):
    """The final writer did not leave a synthesis. Try the next backup."""


class _RunFailed(Exception):
    """The run cannot continue. Research failed, or the backups are exhausted."""


@dataclass(frozen=True)
class Request:
    """One filled brainstorm card.

    ``timeout`` is ``15``, ``30``, ``45``, ``60``, or ``"none"``. ``backup``
    is empty when the card says none.
    """

    models: tuple[str, ...]
    passes: int
    final: str
    backup: tuple[str, ...]
    timeout: int | str

    def as_fields(self) -> dict:
        return {
            "models": list(self.models),
            "passes": self.passes,
            "final": self.final,
            "backup": list(self.backup),
            "timeout": self.timeout,
        }


def defaults(conn: sqlite3.Connection) -> tuple[Request, tuple[str, ...]]:
    """Models, one pass, the first model as writer, timeout 15.

    Models are every unattended agent that is installed and logged in.
    ``default_agents``, when set, is that list instead. Backup is whatever
    remains of ``default_agents`` after those models, or none. An agent that
    cannot run unattended is left out, and the note says why.
    """
    stored = _stored_agents(conn)
    notes: list[str] = []
    if stored is None:
        models = _detected_agents()
        backup: list[str] = []
    else:
        models = []
        for name in stored:
            if name in models:
                continue
            if _block_reason(name):
                continue
            models.append(name)
        backup = []
        for name in stored:
            if name in models or name in backup:
                continue
            reason = _block_reason(name)
            if reason:
                notes.append(f"{name}: {reason}")
                continue
            backup.append(name)
    final = models[0] if models else ""
    return Request(tuple(models), 1, final, tuple(backup), 15), tuple(notes)


def apply(
    base: Request, fields: Mapping
) -> tuple[Request, tuple[str, ...]]:
    """Merge ``fields`` onto ``base``.

    A passes value outside 1–3, an unknown agent, or a timeout outside
    ``15, 30, 45, 60, none`` raises ``SettingsError`` naming that line.
    Antigravity, and any other agent that cannot run unattended, is removed.
    The returned notes say why. An explicit ``final`` outside the models is
    added to them. Changing ``models`` so the current writer is left out
    makes the first of the new models the writer instead.
    """
    models = list(base.models)
    passes = base.passes
    final = base.final
    backup = list(base.backup)
    timeout: int | str = base.timeout
    notes: list[str] = []
    errors: list[str] = []
    final_set = False
    models_set = False

    for key, field in fields.items():
        if key not in _BRAINSTORM_KEYS:
            continue
        raw, parsed, unknown = _read(key, field)
        line = f"{key}: {raw}"
        if key == "passes":
            if isinstance(parsed, bool) or parsed not in _PASSES:
                errors.append(line)
            else:
                passes = int(parsed)
        elif key == "timeout":
            canonical = _canonical_timeout(parsed)
            if canonical not in _TIMEOUTS:
                errors.append(line)
            else:
                timeout = canonical
        elif key in _LIST_KEYS:
            if unknown:
                errors.append(line)
                continue
            kept, dropped = _split_unattended(parsed)
            notes.extend(dropped)
            if key == "models":
                models = kept
                models_set = True
            else:
                backup = kept
        elif key == "final":
            if unknown or not parsed:
                errors.append(line)
                continue
            kept, dropped = _split_unattended([parsed])
            notes.extend(dropped)
            final_set = True
            final = kept[0] if kept else ""
    if errors:
        raise SettingsError(errors)

    if final and _block_reason(final):
        notes.append(f"{final}: {_block_reason(final)}")
        final = ""
    if final and final not in models:
        if final_set:
            # Only an explicit final: may add an agent the models line omitted.
            models.append(final)
            notes.append(f"final: {final} (added; it is not one of the models)")
        elif models_set and models:
            previous = final
            final = models[0]
            notes.append(f"final: {final} ({previous} is no longer a model)")
        else:
            # The console runner replaces a writer that is not in the model list.
            models.append(final)
    if not final and models:
        final = models[0]
    if final_set and not final and not models:
        final = ""
    # A backup may also be one of the models. The template names codex as both.
    # Only the default list keeps the remainder that is not already a model.
    backup = [name for name in backup if not _block_reason(name)]
    unique_notes = list(dict.fromkeys(note for note in notes if note))
    return (
        Request(tuple(models), passes, final, tuple(backup), timeout),
        tuple(unique_notes),
    )


def request_from_fields(fields: Mapping) -> tuple[Request, tuple[str, ...]]:
    """Build a request from a card's stored fields."""
    return apply(Request((), 1, "", (), 15), fields)


def render(request: Request, notes: tuple[str, ...] = ()) -> str:
    """The settings card: the filled values, any removal notes, then the template."""
    parts = ["Brainstorm", "", _format(request)]
    if notes:
        parts.extend(["", *notes])
    parts.extend(["", TEMPLATE])
    return "\n".join(parts)


def ensure_workspace() -> Path:
    """``paths.workspace()``, created as a git repository on first use.

    One empty commit gives later brainstorm commits a parent. The identity
    is local to this repository, so a machine without a global git name can
    still commit here.
    """
    root = paths.workspace()
    if not (root / ".git").exists():
        _git_ok(root, "init", "-q", "-b", "main")
    if _git(root, "config", "user.email").returncode != 0:
        _git_ok(root, "config", "user.email", _GIT_EMAIL)
    if _git(root, "config", "user.name").returncode != 0:
        _git_ok(root, "config", "user.name", _GIT_NAME)
    if _git(root, "rev-parse", "--verify", "HEAD").returncode != 0:
        _git_ok(root, "commit", "-q", "--allow-empty", "-m", _EMPTY_COMMIT)
    return root


def run(
    conn: sqlite3.Connection,
    idea_id: int,
    request: Request,
    *,
    run_fn=None,
    cancel_event=None,
) -> Path:
    """Run the brainstorm and queue the synthesis as documents.

    The topic is the idea's original text plus refine notes that are not
    already in it. ``timeout`` ``none`` is an unlimited runner budget.
    Phase lines edit one status message in the idea's chat.
    """
    root = ensure_workspace()
    idea = store.get(conn, idea_id)
    if idea is None:
        raise LookupError(f"no idea {idea_id}")
    if not request.models or not request.final:
        raise BrainstormError("No agent can brainstorm unattended.")
    idea = _begin(conn, idea)
    chat_id = _chat_id(idea.source_ref)
    progress = _progress(conn, chat_id, idea.id)
    topic = _topic(conn, idea)
    attachments = _report(conn, idea.id)
    try:
        _attempts(
            conn,
            idea,
            request,
            root=root,
            topic=topic,
            chat_id=chat_id,
            progress=progress,
            run_fn=run_fn,
            attachments=attachments,
            cancel_event=cancel_event,
        )
    except BrainstormError:
        raise
    except Exception as exc:
        _fail(conn, idea.id, str(exc), chat_id)
        raise BrainstormError(str(exc)) from exc
    shared = _shared(root, topic)
    dest = _archive(idea.id, shared.read_text(encoding="utf-8"))
    store.set_paths(conn, idea.id, brainstorm_path=str(dest))
    finished = store.get(conn, idea.id)
    finished = store.transition(
        conn,
        idea.id,
        "brainstormed",
        expected_revision=finished.revision,
        actor=_ACTOR,
    )
    _send(conn, chat_id, finished, dest)
    return dest


def _attempts(
    conn,
    idea: store.Idea,
    request: Request,
    *,
    root: Path,
    topic: str,
    chat_id: int | None,
    progress,
    run_fn,
    attachments,
    cancel_event,
) -> None:
    unlimited = request.timeout == "none"
    minutes = 15 if unlimited else int(request.timeout)
    agents = list(request.models)
    final = request.final
    tried: list[str] = []
    chain = list(request.backup)
    while True:
        try:
            _invoke(
                root,
                topic=topic,
                agents=agents,
                passes=request.passes,
                final=final,
                minutes=minutes,
                unlimited=unlimited,
                progress=progress,
                run_fn=run_fn,
                attachments=attachments,
                cancel_event=cancel_event,
            )
        except _Stopped:
            _fail(conn, idea.id, "Stopped.", chat_id)
            raise BrainstormError("Stopped.") from None
        except _RunFailed as exc:
            _fail(conn, idea.id, str(exc), chat_id)
            raise BrainstormError(str(exc)) from exc
        except _WriterFailed as exc:
            if final not in tried:
                tried.append(final)
            backup = _next_backup(chain, tried)
            if backup is None:
                reason = str(exc) or "The final writer did not write a synthesis."
                _fail(conn, idea.id, reason, chat_id)
                raise BrainstormError(reason) from exc
            reason = str(exc).split("—", 1)[0].strip() or "it failed"
            progress(f"{final} failed ({reason}); trying {backup}…")
            agents = _substitute(agents, final, backup)
            final = backup
            continue
        return


def _invoke(
    root: Path,
    *,
    topic: str,
    agents: list[str],
    passes: int,
    final: str,
    minutes: int,
    unlimited: bool,
    progress,
    run_fn,
    attachments,
    cancel_event,
) -> None:
    from whyline.console import adapters
    from whyline_relay import agents as relay_agents
    from whyline_relay import brainstorm as relay_brainstorm
    from whyline_relay import chat

    try:
        # Relay would otherwise walk every research model after the writer.
        # Auto keeps the roster to the writer and fails over its own chain.
        # The backup on the card is that chain.
        with _writer_only():
            result = adapters.run_brainstorm(
                root=root,
                topic=topic,
                agents=agents,
                passes=passes,
                final_agent=final,
                timeout_minutes=minutes,
                timeout_unlimited=unlimited,
                progress=progress,
                run_fn=run_fn,
                attachments=list(attachments),
                cancel_event=cancel_event,
            )
    except relay_agents.AgentCancelled:
        raise _Stopped() from None
    except (
        relay_agents.AgentTimeout,
        relay_agents.AgentMissing,
        chat.AgentUnavailable,
        relay_brainstorm.NothingToSynthesize,
    ) as exc:
        raise _WriterFailed(str(exc)) from exc
    text = getattr(result, "text", "") or ""
    if not isinstance(text, str):
        text = str(text)
    if getattr(result, "kind", None) == "error":
        if text.startswith("Stopped"):
            raise _Stopped()
        raise _RunFailed(text or "Brainstorm failed.")
    if not _has_final(root, topic):
        raise _WriterFailed(text or "The final writer did not write a synthesis.")


def _writer_only():
    """Context manager: synthesis tries only the writer this call asked for."""
    from contextlib import contextmanager

    @contextmanager
    def _limit():
        from whyline_relay import brainstorm as relay_brainstorm

        original = relay_brainstorm.run_final_synthesis

        def wrapped(*args, **kwargs):
            limited_args, limited_kwargs = _limit_synthesis_models(args, kwargs)
            return original(*limited_args, **limited_kwargs)

        relay_brainstorm.run_final_synthesis = wrapped
        try:
            yield
        finally:
            relay_brainstorm.run_final_synthesis = original

    return _limit()


def _limit_synthesis_models(args, kwargs):
    writer = kwargs.get("final_agent")
    if not (isinstance(writer, str) and writer) and len(args) >= 2:
        if isinstance(args[1], str) and args[1]:
            writer = args[1]
    if len(args) >= 3 and "models" not in kwargs:
        limited = _only_writer(args[2], writer)
        if limited is args[2]:
            return args, kwargs
        updated = list(args)
        updated[2] = limited
        return tuple(updated), kwargs
    models = kwargs.get("models")
    limited = _only_writer(models, writer)
    if limited is models:
        return args, kwargs
    copied = dict(kwargs)
    copied["models"] = limited
    return args, copied


def _only_writer(models, writer: str | None):
    if not isinstance(models, (list, tuple)) or not writer:
        return models
    kept = []
    for item in models:
        key = item[0] if isinstance(item, (tuple, list)) and item else item
        if key == writer:
            kept.append(item)
    if isinstance(models, tuple):
        return tuple(kept)
    return kept


def _next_backup(chain: list[str], tried: list[str]) -> str | None:
    from whyline_relay import failover

    backup = failover.next_backup(list(chain), set(tried))
    if not isinstance(backup, str) or backup not in tuple(chain):
        return None
    return backup


def _substitute(agents: list[str], failed: str, backup: str) -> list[str]:
    replaced: list[str] = []
    for agent in agents:
        candidate = backup if agent == failed else agent
        if candidate not in replaced:
            replaced.append(candidate)
    if backup not in replaced:
        replaced.append(backup)
    return replaced


def _begin(conn: sqlite3.Connection, idea: store.Idea) -> store.Idea:
    if idea.status in {"captured", "scored", "brainstormed"}:
        idea = store.transition(
            conn,
            idea.id,
            "brainstorm_configuring",
            expected_revision=idea.revision,
            actor=_ACTOR,
            note=idea.status,
        )
    if idea.status != "brainstorm_configuring":
        raise BrainstormError(f"cannot brainstorm from {idea.status}")
    entered = store.transition(
        conn,
        idea.id,
        "brainstorming",
        expected_revision=idea.revision,
        actor=_ACTOR,
    )
    # Start wrote Cancel against the revision from before this move.
    from whyline.ideas import bot

    bot.refresh_running_card(conn, entered)
    return entered


def _fail(conn: sqlite3.Connection, idea_id: int, reason: str, chat_id: int | None) -> None:
    current = store.get(conn, idea_id)
    if current is not None and current.status == "brainstorming":
        note = " ".join(str(reason).split())
        if len(note) > 500:
            note = note[:500]
        try:
            returned = store.transition(
                conn,
                idea_id,
                "captured",
                expected_revision=current.revision,
                actor=_ACTOR,
                note=note,
            )
        except (store.IllegalMove, store.StaleRevision):
            pass
        else:
            from whyline.ideas import bot

            bot.refresh_running_card(conn, returned)
    if chat_id is None:
        return
    text = " ".join(str(reason).split()) or "Brainstorm failed."
    _enqueue(conn, chat_id, "message", text, None, None, idea_id)


def _topic(conn: sqlite3.Connection, idea: store.Idea) -> str:
    """Original text, plus refine notes stored only on the event row.

    Bot and CLI refine both append the note to ``original_text`` and copy
    it onto an event whose status does not change. A note already in the
    text is not repeated. Outbox give-up notes use another actor.
    """
    text = idea.original_text.strip()
    rows = conn.execute(
        """
        SELECT note FROM events
        WHERE idea_id = ? AND from_status = to_status
          AND actor IN ('telegram', 'cli') AND note != ''
        ORDER BY id
        """,
        (idea.id,),
    ).fetchall()
    extra: list[str] = []
    for row in rows:
        note = " ".join(str(row["note"]).split())
        if note and note not in text:
            extra.append(note)
    if extra:
        text = (text + "\n\n" + "\n\n".join(extra)).strip()
    return text or "idea"


def _report(conn: sqlite3.Connection, idea_id: int) -> list[Path]:
    row = conn.execute(
        """
        SELECT report_path FROM analyses
        WHERE idea_id = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (idea_id,),
    ).fetchone()
    if row is None:
        return []
    path = Path(row["report_path"])
    return [path] if path.is_file() else []


def _has_final(root: Path, topic: str) -> bool:
    path = _shared(root, topic)
    if not path.is_file():
        return False
    try:
        return "## Final Synthesis" in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _shared(root: Path, topic: str) -> Path:
    from whyline_relay import brainstorm as relay_brainstorm

    return relay_brainstorm.shared_path(root, topic)


def _archive(idea_id: int, text: str) -> Path:
    folder = paths.home() / "brainstorms"
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    dest = folder / f"{idea_id}.md"
    _write_private(dest, text)
    return dest


def _send(conn, chat_id: int | None, idea: store.Idea, md: Path) -> None:
    if chat_id is None:
        return
    from whyline.ideas import bot

    bot.edit_progress(conn, idea.id, "Synthesis written; sending it ↓", chat_id=chat_id)
    try:
        exported = documents.export(md)
    except (OSError, ValueError) as exc:
        bot.edit_progress(
            conn,
            idea.id,
            f"The synthesis is ready but sending it failed: {exc}; I'll retry",
            chat_id=chat_id,
        )
        _enqueue(conn, chat_id, "message", str(exc), None, None, idea.id)
        return
    keyboard = bot._keyboard(bot.buttons_for("brainstormed"), idea.id, idea.revision)
    note = " ".join(item for item in exported.notes if item)
    made = [path for path in (exported.docx, exported.pdf) if path is not None]
    queued: list[int] = []
    if not made:
        outbox_id = bot._enqueue(
            conn, chat_id, "document", note or "Brainstorm",
            buttons=keyboard, document_path=str(md), idea_id=idea.id,
        )
        bot.mark_delivery(conn, outbox_id, "synthesis")
        queued.append(outbox_id)
    else:
        for index, path in enumerate(made):
            caption = note if index == 0 and note else ""
            outbox_id = bot._enqueue(
                conn, chat_id, "document", caption,
                buttons=keyboard, document_path=str(path), idea_id=idea.id,
            )
            bot.mark_delivery(conn, outbox_id, "synthesis")
            queued.append(outbox_id)
    # Kind is brainstormed, not brainstorm. Again rewrites a brainstorm card
    # in place, which would revive the retired pre-run settings message and
    # leave this result keyboard live. The last queued row is the only one
    # that still has buttons.
    bot._remember_card(
        conn, chat_id, "brainstormed", idea.id, outbox_id=queued[-1]
    )


def _progress(conn, chat_id: int | None, idea_id: int):
    """Edit one status message at each phase. Never throttle those edits.

    A per-agent line updates the same board (who is done, who is current).
    It is not also sent on its own: the board already shows it, and a
    second copy would be the line the minute-throttle used to drop.
    """
    state: dict = {"order": [], "marks": {}, "phase": "", "review": ""}

    def emit(line="") -> None:
        text = line if isinstance(line, str) else str(line)
        text = " ".join(text.split())
        if not text or chat_id is None:
            return
        status = _phase_text(text, state)
        if status is None:
            return
        from whyline.ideas import bot

        bot.edit_progress(conn, idea_id, status[:4000], chat_id=chat_id)

    return emit


def _phase_text(line: str, state: dict) -> str | None:
    """The status sentence for this progress line, or None when it is chatter."""
    lower = line.lower()
    if lower.startswith("researching"):
        names = [
            _agent_key(part)
            for part in line.split(":", 1)[-1].split(",")
            if part.strip()
        ]
        state["phase"] = "research"
        state["order"] = names
        state["marks"] = {}
        if names:
            state["marks"][names[0]] = "…"
        return _board("Researching", state)
    if lower.startswith("review pass"):
        state["phase"] = "review"
        state["review"] = line.rstrip(".")
        state["marks"] = {}
        return f"{state['review']}: …"
    if lower.startswith("final synthesis by"):
        agent = _agent_key(line.split()[-1])
        state["phase"] = "write"
        return f"Writing the final synthesis with {agent}…"
    if "failed" in lower and "trying" in lower:
        return line if line.endswith("…") else f"{line}…"
    parsed = _AGENT_LINE.match(line)
    if parsed is None:
        return None
    label = _agent_key(parsed.group(3))
    status = parsed.group(4).lower()
    scope = parsed.group(5).lower()
    mark = {"succeeded": "✓", "starting": "…", "failed": "✗", "skipped": "✗"}.get(status, "")
    if "final synthesis" in scope:
        if status == "starting":
            return f"Writing the final synthesis with {label}…"
        if status == "succeeded":
            return "Synthesis written; sending it ↓"
        return None
    if "review" in scope:
        state["phase"] = "review"
        if label:
            state.setdefault("marks", {})[label] = mark
        heading = state.get("review") or "Review"
        if state.get("order"):
            return _board(heading, state)
        return f"{heading}: …"
    state["phase"] = "research"
    state.setdefault("marks", {})[label] = mark
    if status in {"succeeded", "failed", "skipped"}:
        _advance_current(state, label)
    return _board("Researching", state)


_AGENT_LINE = re.compile(
    r"^\[(\d+)/(\d+)\]\s+(\S+)\s+(starting|succeeded|failed|skipped)\s+(.+)$",
    re.IGNORECASE,
)


def _agent_key(label: str) -> str:
    return label.strip().lower().rstrip(".,")


def _board(heading: str, state: dict) -> str:
    order = list(state.get("order") or [])
    marks = state.get("marks") or {}
    if not order:
        parts = []
        for name, mark in marks.items():
            parts.append(f"{name} {mark}".strip() if mark else name)
        body = ", ".join(parts) if parts else "…"
        return f"{heading}: {body}"
    shown = []
    for name in order:
        mark = marks.get(name, "")
        if mark == "…":
            shown.append(f"{name} …")
        elif mark:
            shown.append(f"{name} {mark}")
        else:
            shown.append(name)
    return f"{heading}: {', '.join(shown)}"


def _advance_current(state: dict, finished: str) -> None:
    order = state.get("order") or []
    marks = state.setdefault("marks", {})
    found = False
    for name in order:
        if name == finished:
            found = True
            continue
        if found and marks.get(name) not in {"✓", "✗"}:
            marks[name] = "…"
            return


def _read(key: str, field) -> tuple[str, object, bool]:
    if isinstance(field, intent.Field):
        return _read_intent(key, field)
    raw = _show_raw(field)
    if key in _LIST_KEYS:
        names, unknown = _agent_names(field)
        return raw, names, unknown
    if key == "final":
        names, unknown = _agent_names(field)
        if len(names) != 1 or unknown:
            return raw, None, True
        return raw, names[0], False
    return raw, field, False


def _read_intent(key: str, field: intent.Field) -> tuple[str, object, bool]:
    raw = field.raw
    value = field.value
    if key in _LIST_KEYS:
        if not isinstance(value, tuple):
            return raw, [], True
        unknown = False
        names: list[str] = []
        for item in value:
            if not isinstance(item, intent.AgentWord) or item.name is None:
                unknown = True
                continue
            names.append(item.name)
        return raw, names, unknown
    if key == "final":
        if not isinstance(value, intent.AgentWord) or value.name is None:
            return raw, None, True
        return raw, value.name, False
    if key == "timeout":
        if value in {"15", "30", "45", "60"}:
            return raw, int(value), False
        return raw, value, False
    return raw, value, False


def _agent_names(value) -> tuple[list[str], bool]:
    if value is None:
        return [], False
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() == "none":
            return [], False
        words = [word for word in text.replace(",", " ").split() if word]
    elif isinstance(value, (list, tuple)):
        words = []
        for item in value:
            words.extend(_agent_names(item)[0] if not isinstance(item, str) else [item])
        # A list item that does not normalise is unknown. Re-check below.
        unknown = False
        names: list[str] = []
        for word in words:
            if word in names:
                continue
            canonical = word if word in intent.AGENTS else intent.normalise_agent(word)
            if canonical is None:
                unknown = True
                continue
            names.append(canonical)
        return names, unknown
    else:
        words = [str(value)]
    unknown = False
    names = []
    for word in words:
        canonical = word if word in intent.AGENTS else intent.normalise_agent(word)
        if canonical is None:
            unknown = True
            continue
        if canonical not in names:
            names.append(canonical)
    return names, unknown


def _split_unattended(names: list[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    notes: list[str] = []
    for name in names:
        if name in kept:
            continue
        reason = _block_reason(name)
        if reason:
            notes.append(f"{name}: {reason}")
            continue
        kept.append(name)
    return kept, notes


def _block_reason(name: str) -> str | None:
    if name == "human":
        return _UNATTENDED
    if not capabilities.can_run_unattended(name):
        return _UNATTENDED
    return None


def _canonical_timeout(value) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = "".join(value.split()).lower()
        if text.endswith("m") and text[:-1] in {"15", "30", "45", "60", "none"}:
            text = text[:-1]
        if text == "none":
            return "none"
        if text in {"15", "30", "45", "60"}:
            return int(text)
        return value.strip()
    return value


def _show_raw(value) -> str:
    if isinstance(value, (list, tuple)):
        shown = ", ".join(str(item) for item in value)
        return shown or "none"
    if value is None:
        return ""
    return str(value)


def _format(request: Request) -> str:
    backup = ", ".join(request.backup) if request.backup else "none"
    models = ", ".join(request.models) if request.models else "none"
    final = request.final or "none"
    return "\n".join((
        f"models: {models}",
        f"passes: {request.passes}",
        f"final: {final}",
        f"backup: {backup}",
        f"timeout: {request.timeout}",
    ))


def _stored_agents(conn: sqlite3.Connection) -> list[str] | None:
    row = conn.execute(
        "SELECT value FROM kv WHERE key = ?", (_AGENTS_KEY,)
    ).fetchone()
    if row is None:
        return None
    raw = row["value"]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw.split()
    if isinstance(parsed, str):
        parsed = parsed.split()
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _detected_agents() -> list[str]:
    from whyline import account

    try:
        detected = account.detect()
    except Exception:
        return []
    if not isinstance(detected, dict):
        return []
    names: list[str] = []
    for name in _DETECT_ORDER:
        if not capabilities.can_run_unattended(name):
            continue
        info = detected.get(name)
        if isinstance(info, dict) and info.get("available"):
            names.append(name)
    return names


def _chat_id(source_ref: str | None) -> int | None:
    if not source_ref or ":" not in source_ref:
        return None
    head, _sep, _tail = source_ref.partition(":")
    try:
        return int(head)
    except ValueError:
        return None


def _enqueue(conn, chat_id, kind, text, buttons, document_path, idea_id) -> None:
    payload = json.dumps(buttons, ensure_ascii=False) if buttons else None
    with store._txn(conn):
        conn.execute(
            """
            INSERT INTO outbox (
              chat_id, kind, text, buttons_json, document_path,
              attempts, next_try_at, sent_at, idea_id
            ) VALUES (?, ?, ?, ?, ?, 0, NULL, NULL, ?)
            """,
            (chat_id, kind, text, payload, document_path, idea_id),
        )


def _keyboard(buttons, idea_id: int, revision: int) -> list:
    cells = [
        {"text": label, "callback_data": f"{action}:{idea_id}:{revision}"}
        for label, action in buttons
    ]
    return [cells]


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    path.chmod(0o600)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


def _git_ok(root: Path, *args: str) -> None:
    result = _git(root, *args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise BrainstormError(detail or f"git {' '.join(args)} failed")
