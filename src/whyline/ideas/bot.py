"""Telegram cards, buttons, and a retrying outbox.

``handle`` turns one inbound row into ledger changes and outbox rows.
``flush_outbox`` is the only sender. A failed send waits 1, 5, 15, then
60 minutes, and stops after 8 attempts with an events note.

Quick score inserts a ``jobs`` row for IDEA-13. It does not move the idea
to ``scoring``: ``analyse`` does that when the job runs, and it refuses a
second move into ``scoring``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from whyline.agents import capabilities, telegram
from whyline.ideas import assistant, documents, intent, store, xlsx

OUT_OF_DATE = "This card is out of date"
REFINE_QUESTION = "What should I add?"
MAX_ATTEMPTS = 8
# Index by the attempt that just failed. Attempt 5 and later stay at 60.
BACKOFF_MINUTES = (1, 5, 15, 60)
_MESSAGE_LIMIT = 4096
_AGENTS_KEY = "default_agents"
_CARD_KEY = "telegram_card"
_OPEN_KEY = "telegram_open"
_SETTINGS_KEY = "telegram_settings"
_DETECT_ORDER = ("claude", "codex", "grok")
_PLAN_KEYS = frozenset({
    "repo",
    "implementer",
    "tester",
    "reviewer",
    "release",
    "drafter",
    "plan_reviewer",
})
_LABEL_ACTION = {
    "Brainstorm": "brainstorm",
    "Quick score": "score",
    "Cancel": "cancel",
    "Full report": "report",
    "Refine": "refine",
    "Drop": "drop",
    "Excel": "excel",
    "Confirm": "confirm",
    "Edit": "edit",
}
_SCORE_FROM = frozenset({"captured", "scored"})
_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"

# IDEA-13 adds this table as schema 4. It is created on the first score tap
# so the row exists before that migration. The columns are the plan's.
_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  idea_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  state TEXT NOT NULL,
  lease_until TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  pid INTEGER
)
"""

HELP_TEXT = """\
Commands:
/new
/list
/status [id]
/excel
/brainstorm [id]
/plan [id]
/stop [id]
/drop <id>
/help

Settings:
models: claude, codex, grok
passes: 1
final: claude
backup: codex
timeout: 30
repo: name
implementer: grok
tester: codex
reviewer: claude
release: human
drafter: claude
plan_reviewer: codex"""

_SETTINGS_TEMPLATE = """\
Settings:
models: claude, codex, grok
passes: 1
final: claude
backup: codex
timeout: 30
repo: name
implementer: grok
tester: codex
reviewer: claude
release: human
drafter: claude
plan_reviewer: codex"""


def handle(conn: sqlite3.Connection, inbound, *, run_fn=None) -> None:
    """Route one inbound row and queue the reply.

    A row already marked handled is ignored. The callback is acknowledged
    even when the button is stale. Nothing is sent here; ``flush_outbox``
    does that.
    """
    if _truthy(_field(inbound, "handled")):
        return
    chat_id = _field(inbound, "chat_id")
    if chat_id is None:
        _mark_handled(conn, inbound)
        return
    text = _field(inbound, "text") or ""
    callback = _field(inbound, "callback_data")
    question = _open_for(conn, int(chat_id))
    routed = intent.route(text, callback, open_question=question)
    _ack(conn, inbound, routed)
    _dispatch(conn, inbound, routed, run_fn)
    _mark_handled(conn, inbound)


def flush_outbox(conn: sqlite3.Connection, *, http=None) -> int:
    """Send due outbox rows. Return how many were sent.

    A row with ``sent_at`` set is not sent again. A row whose
    ``next_try_at`` is still ahead is left for a later call. The 30-second
    pause inside ``telegram._call`` is not used; this backoff is the retry.
    """
    token = telegram.token_get()
    if not token:
        return 0
    moment = _now()
    due = conn.execute(
        """
        SELECT id FROM outbox
        WHERE sent_at IS NULL
          AND attempts < ?
          AND (next_try_at IS NULL OR next_try_at <= ?)
        ORDER BY id
        """,
        (MAX_ATTEMPTS, moment),
    ).fetchall()
    sent = 0
    for item in due:
        if _flush_one(conn, int(item["id"]), token, http, moment):
            sent += 1
    return sent


def send_score(conn: sqlite3.Connection, idea_id: int, *, chat_id: int | None = None) -> None:
    """Queue the summary card for a score that has landed.

    The chat is the one in ``source_ref`` (``<chat>:<message>``) unless
    ``chat_id`` is passed. Buttons are Brainstorm, Full report, Refine,
    Drop, and Excel, in that order.
    """
    idea = store.get(conn, idea_id)
    if idea is None:
        raise LookupError(f"no idea {idea_id}")
    if chat_id is None:
        chat_id = _chat_from_ref(idea.source_ref)
    if chat_id is None:
        return
    analysis = _latest_analysis(conn, idea.id)
    if analysis is None:
        _enqueue(conn, chat_id, "message", "No score yet.", idea_id=idea.id)
        return
    idea = store.get(conn, idea_id)
    keyboard = _keyboard(
        (
            ("Brainstorm", "brainstorm"),
            ("Full report", "report"),
            ("Refine", "refine"),
            ("Drop", "drop"),
            ("Excel", "excel"),
        ),
        idea.id,
        idea.revision,
        width=5,
    )
    _enqueue(
        conn,
        chat_id,
        "message",
        _summary(idea, analysis),
        buttons=keyboard,
        idea_id=idea.id,
    )
    _remember_card(conn, chat_id, "score", idea.id)


def enqueue_score(conn: sqlite3.Connection, idea_id: int) -> bool:
    """Queue one score job. False when a queued or running one already exists."""
    _ensure_jobs(conn)
    with store._txn(conn):
        row = conn.execute(
            """
            SELECT id FROM jobs
            WHERE idea_id = ? AND kind = 'score'
              AND state IN ('queued', 'running')
            """,
            (idea_id,),
        ).fetchone()
        if row is not None:
            return False
        conn.execute(
            """
            INSERT INTO jobs (idea_id, kind, state, attempts)
            VALUES (?, 'score', 'queued', 0)
            """,
            (idea_id,),
        )
        return True


def score_agents(conn: sqlite3.Connection) -> list[str]:
    """Agents a quick score will try, first one named in the progress reply.

    ``default_agents`` wins when it is set. Otherwise every unattended
    agent that is installed and logged in, in Claude, Codex, Grok order.
    """
    stored = _stored_agents(conn)
    names = stored if stored is not None else _detected_agents()
    chosen: list[str] = []
    for name in names:
        if name in chosen:
            continue
        if capabilities.can_run_unattended(name):
            chosen.append(name)
    return chosen


def _dispatch(conn, row, routed: intent.Intent, run_fn) -> None:
    kind = routed.kind
    if kind == "capture":
        _capture(conn, row, routed)
    elif kind == "action":
        _action(conn, row, routed)
    elif kind == "command":
        _command(conn, row, routed)
    elif kind == "settings":
        _settings(conn, row, routed)
    elif kind == "answer":
        _answer(conn, row, routed)
    elif kind == "free":
        if not routed.text.strip():
            _say(conn, row, "Send an idea, or /help.")
            return
        _free(conn, row, routed, run_fn)
    else:
        _say(conn, row, "Send an idea, or /help.")


def _capture(conn, row, routed: intent.Intent) -> None:
    chat_id = int(_field(row, "chat_id"))
    message_id = _message_id(row)
    source_ref = f"{chat_id}:{message_id}" if message_id is not None else None
    idea = store.add(
        conn, routed.text, source="telegram", source_ref=source_ref
    )
    line = _normalised_first_line(idea.original_text)
    keyboard = _keyboard(
        (
            ("Brainstorm", "brainstorm"),
            ("Quick score", "score"),
            ("Cancel", "cancel"),
        ),
        idea.id,
        idea.revision,
    )
    # The flag and the card share a transaction, so a retry of this row
    # does not send a second card.
    with store._txn(conn):
        if _kv(conn, f"capture_card:{idea.id}"):
            return
        _insert_outbox(conn, chat_id, "message", line, keyboard, None, idea.id)
        _kv_set(conn, f"capture_card:{idea.id}", "1")
        _remember_card_in(conn, chat_id, "capture", idea.id, None)


def _action(conn, row, routed: intent.Intent) -> None:
    if routed.idea_id == 0:
        _unbound(conn, row, routed)
        return
    idea = store.get(conn, routed.idea_id) if routed.idea_id is not None else None
    if idea is None or idea.revision != routed.revision:
        _say(
            conn,
            row,
            OUT_OF_DATE,
            idea_id=idea.id if idea is not None else None,
        )
        return
    name = routed.name
    if name == "score":
        _quick_score(conn, row, idea)
    elif name == "report":
        _full_report(conn, row, idea)
    elif name == "excel":
        _excel(conn, row, idea)
    elif name == "drop":
        _ask_drop(conn, row, idea)
    elif name == "drop_yes":
        _drop(conn, row, idea)
    elif name == "refine":
        _ask_refine(conn, row, idea)
    elif name == "cancel":
        _cancel(conn, row, idea)
    elif name == "confirm":
        _confirm(conn, row, idea)
    elif name == "edit":
        _edit(conn, row, idea)
    elif name == "brainstorm":
        # IDEA-12 fills in the settings card.
        return
    else:
        _say(conn, row, "Not available yet.", idea_id=idea.id)


def _unbound(conn, row, routed: intent.Intent) -> None:
    """Confirm / Edit / Cancel on a card that is not tied to an idea."""
    if routed.revision != 0:
        _say(conn, row, OUT_OF_DATE)
        return
    if routed.name == "cancel":
        _say(conn, row, "Cancelled.")
    elif routed.name == "confirm":
        _say(conn, row, "Confirmed.")
    elif routed.name == "edit":
        _say(conn, row, "Send a key: value message.\n\n" + _SETTINGS_TEMPLATE)
    else:
        _say(conn, row, "Not available yet.")


def _command(conn, row, routed: intent.Intent) -> None:
    name = routed.name
    if name == "list":
        _list(conn, row)
    elif name == "help":
        _say(conn, row, HELP_TEXT)
    elif name == "excel":
        _excel(conn, row, None)
    elif name == "drop":
        _command_drop(conn, row, routed)
    elif name == "new":
        _say(conn, row, "Send the idea as a message.")
    else:
        _say(conn, row, "Not available yet.")


def _settings(conn, row, routed: intent.Intent) -> None:
    plain, errors = _plain_fields(routed.fields)
    if errors:
        _say(conn, row, "\n".join(errors))
        return
    kind = "plan_setup" if _PLAN_KEYS.intersection(plain) else "brainstorm_settings"
    chat_id = int(_field(row, "chat_id"))
    idea = _latest_for_chat(conn, chat_id)
    summary = ", ".join(f"{key}: {_show(value)}" for key, value in plain.items())
    card = assistant.confirm_card(kind, summary=summary or "Settings", fields=plain, idea=idea)
    _send_named_card(conn, row, card, idea, kind=kind, fields=plain)


def _answer(conn, row, routed: intent.Intent) -> None:
    chat_id = int(_field(row, "chat_id"))
    question = _open_for(conn, chat_id)
    _clear_open(conn, chat_id)
    if not question or question.get("kind") != "refine":
        _say(conn, row, "Nothing is waiting for an answer.")
        return
    try:
        idea_id = int(question["idea_id"])
    except (KeyError, TypeError, ValueError):
        _say(conn, row, "Nothing is waiting for an answer.")
        return
    idea = store.get(conn, idea_id)
    if idea is None:
        _say(conn, row, "No idea is waiting for an answer.")
        return
    extra = routed.text.strip()
    if extra:
        _append_context(conn, idea, extra)
        idea = store.get(conn, idea.id)
    _quick_score(conn, row, idea)


def _free(conn, row, routed: intent.Intent, run_fn) -> None:
    chat_id = int(_field(row, "chat_id"))
    idea = _latest_for_chat(conn, chat_id)
    proposal = assistant.propose(
        conn,
        routed.text,
        idea=idea,
        context=_card_context(conn, chat_id),
        run_fn=run_fn,
    )
    if proposal.card is not None:
        bound = idea
        if bound is None and proposal.card.idea_id is not None:
            bound = store.get(conn, proposal.card.idea_id)
        _send_named_card(
            conn,
            row,
            proposal.card,
            bound,
            kind=proposal.card.kind,
            fields=dict(proposal.fields),
        )
        return
    _say(conn, row, str(proposal), idea_id=idea.id if idea is not None else None)


def _quick_score(conn, row, idea: store.Idea) -> None:
    if idea.status not in _SCORE_FROM:
        _say(
            conn,
            row,
            f"This idea can't be scored from {idea.status}.",
            idea_id=idea.id,
        )
        return
    agents = score_agents(conn)
    if not agents:
        _say(conn, row, "No agent can score unattended.", idea_id=idea.id)
        return
    if not enqueue_score(conn, idea.id):
        return
    _say(conn, row, f"Scoring with {agents[0]}…", idea_id=idea.id)


def _full_report(conn, row, idea: store.Idea) -> None:
    analysis = _latest_analysis(conn, idea.id)
    if analysis is None:
        _say(conn, row, "No report yet.", idea_id=idea.id)
        return
    md = Path(analysis["report_path"])
    if not md.is_file():
        _say(conn, row, "No report yet.", idea_id=idea.id)
        return
    try:
        exported = documents.export(md)
    except (OSError, ValueError) as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return
    _send_documents(conn, row, idea, exported, md)


def _send_documents(conn, row, idea: store.Idea, exported, md: Path) -> None:
    """Word and PDF, or Word with the note, or the Markdown file."""
    note = " ".join(item for item in exported.notes if item)
    made = [path for path in (exported.docx, exported.pdf) if path is not None]
    if not made:
        _say(
            conn,
            row,
            note or "Report",
            document_path=str(md),
            idea_id=idea.id,
        )
        return
    for index, path in enumerate(made):
        caption = note if index == 0 and note else ""
        _say(conn, row, caption, document_path=str(path), idea_id=idea.id)


def _excel(conn, row, idea: store.Idea | None) -> None:
    try:
        path = xlsx.export(conn)
    except OSError as exc:
        _say(
            conn,
            row,
            f"Could not write the workbook: {exc}",
            idea_id=idea.id if idea is not None else None,
        )
        return
    _say(
        conn,
        row,
        "Ideas",
        document_path=str(path),
        idea_id=idea.id if idea is not None else None,
    )


def _ask_drop(conn, row, idea: store.Idea) -> None:
    chat_id = int(_field(row, "chat_id"))
    keyboard = _keyboard(
        (("Drop", "drop_yes"), ("Cancel", "cancel")),
        idea.id,
        idea.revision,
        width=2,
    )
    _say(conn, row, "Drop this idea?", keyboard, idea_id=idea.id)
    _remember_card(conn, chat_id, "drop_confirm", idea.id)


def _drop(conn, row, idea: store.Idea) -> None:
    try:
        store.transition(
            conn,
            idea.id,
            "dropped",
            expected_revision=idea.revision,
            actor="telegram",
            note="dropped",
        )
    except store.StaleRevision:
        _say(conn, row, OUT_OF_DATE, idea_id=idea.id)
        return
    except store.IllegalMove as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return
    _say(conn, row, "Dropped.", idea_id=idea.id)


def _ask_refine(conn, row, idea: store.Idea) -> None:
    _set_open(
        conn,
        int(_field(row, "chat_id")),
        {"idea_id": idea.id, "kind": "refine"},
    )
    _say(conn, row, REFINE_QUESTION, idea_id=idea.id)


def _cancel(conn, row, idea: store.Idea) -> None:
    """Cancel on the capture card drops the idea. On any other card it does not.

    Drop has its own confirm button. A confirm card's Cancel only dismisses
    that card, so a settings edit cannot throw the idea away.
    """
    card = _card_for(conn, _field(row, "chat_id"))
    kind = card.get("kind") if card else "capture"
    if kind == "capture" and idea.status == "captured":
        try:
            store.transition(
                conn,
                idea.id,
                "dropped",
                expected_revision=idea.revision,
                actor="telegram",
                note="cancelled",
            )
        except (store.IllegalMove, store.StaleRevision):
            pass
    _say(conn, row, "Cancelled.", idea_id=idea.id)
    _clear_card(conn, _field(row, "chat_id"))


def _confirm(conn, row, idea: store.Idea) -> None:
    card = _card_for(conn, _field(row, "chat_id"))
    fields = card.get("fields") if card else None
    if isinstance(fields, dict) and fields:
        _kv_set_txn(conn, f"{_SETTINGS_KEY}:{idea.id}", json.dumps(fields))
    _say(conn, row, "Confirmed.", idea_id=idea.id)


def _edit(conn, row, idea: store.Idea) -> None:
    _say(
        conn,
        row,
        "Send a key: value message.\n\n" + _SETTINGS_TEMPLATE,
        idea_id=idea.id,
    )


def _command_drop(conn, row, routed: intent.Intent) -> None:
    if not routed.args:
        _say(conn, row, "Drop needs an idea id.")
        return
    try:
        idea_id = int(routed.args[0])
    except ValueError:
        _say(conn, row, "Drop needs an idea id.")
        return
    idea = store.get(conn, idea_id)
    if idea is None:
        _say(conn, row, f"No idea {idea_id}.")
        return
    _ask_drop(conn, row, idea)


def _list(conn, row) -> None:
    newest = list(reversed(store.list_ideas(conn)))[:10]
    if not newest:
        _say(conn, row, "No ideas yet.")
        return
    lines = [f"{idea.id}  {idea.status}  {_label(idea)}" for idea in newest]
    _say(conn, row, "\n".join(lines))


def _send_named_card(conn, row, card: assistant.Card, idea, *, kind: str, fields) -> None:
    idea_id = idea.id if idea is not None else 0
    revision = idea.revision if idea is not None else 0
    pairs = []
    for label in card.buttons:
        action = _LABEL_ACTION.get(label)
        if action is not None:
            pairs.append((label, action))
    keyboard = _keyboard(pairs, idea_id, revision)
    text = f"{card.title}\n{card.body}"
    _say(
        conn,
        row,
        text,
        keyboard,
        idea_id=idea.id if idea is not None else None,
    )
    _remember_card(
        conn,
        int(_field(row, "chat_id")),
        kind,
        idea_id,
        fields if isinstance(fields, dict) else None,
    )


def _append_context(conn, idea: store.Idea, extra: str) -> None:
    """Keep refine text where the next score reads it, and in the history.

    The same shape as ``idea refine``: the scorer reads ``original_text``,
    and events are append-only, so the note is its own row.
    """
    base = idea.original_text.rstrip()
    text = f"{base}\n\n{extra}" if base else extra
    with store._txn(conn):
        conn.execute(
            "UPDATE ideas SET original_text = ? WHERE id = ?",
            (text, idea.id),
        )
        conn.execute(
            """
            INSERT INTO events (idea_id, at, from_status, to_status, actor, note)
            VALUES (?, ?, ?, ?, 'telegram', ?)
            """,
            (idea.id, _now(), idea.status, idea.status, extra),
        )


def _flush_one(conn, row_id: int, token: str, http, moment: str) -> bool:
    conn.execute("BEGIN IMMEDIATE")
    try:
        sent = _attempt(conn, row_id, token, http, moment)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return sent


def _attempt(conn, row_id: int, token: str, http, moment: str) -> bool:
    row = conn.execute("SELECT * FROM outbox WHERE id = ?", (row_id,)).fetchone()
    if row is None or row["sent_at"] is not None or int(row["attempts"]) >= MAX_ATTEMPTS:
        return False
    if not _due(row["next_try_at"], moment):
        return False
    try:
        _deliver(token, row, http)
    except telegram.TelegramError as exc:
        _mark_failed(conn, row, moment, str(exc))
        return False
    conn.execute(
        "UPDATE outbox SET sent_at = ? WHERE id = ?",
        (moment, row_id),
    )
    return True


def _mark_failed(conn, row, moment: str, reason: str) -> None:
    attempts = int(row["attempts"]) + 1
    if attempts >= MAX_ATTEMPTS:
        _give_up(conn, row, moment, reason)
        conn.execute(
            "UPDATE outbox SET attempts = ?, next_try_at = NULL WHERE id = ?",
            (attempts, row["id"]),
        )
        return
    delay = BACKOFF_MINUTES[min(attempts, len(BACKOFF_MINUTES)) - 1]
    conn.execute(
        "UPDATE outbox SET attempts = ?, next_try_at = ? WHERE id = ?",
        (attempts, _add_minutes(moment, delay), row["id"]),
    )


def _give_up(conn, row, moment: str, reason: str) -> None:
    idea_id = row["idea_id"]
    if idea_id is None:
        return
    idea = conn.execute(
        "SELECT status FROM ideas WHERE id = ?", (idea_id,)
    ).fetchone()
    if idea is None:
        return
    detail = " ".join(str(reason).split())
    if len(detail) > 200:
        detail = detail[:200]
    note = f"gave up after {MAX_ATTEMPTS} attempts"
    if detail:
        note = f"{note}: {detail}"
    conn.execute(
        """
        INSERT INTO events (idea_id, at, from_status, to_status, actor, note)
        VALUES (?, ?, ?, ?, 'outbox', ?)
        """,
        (idea_id, moment, idea["status"], idea["status"], note),
    )


def _deliver(token: str, row, http) -> None:
    kind = row["kind"]
    if kind == "callback":
        callback_id = row["text"]
        if not callback_id:
            raise telegram.TelegramError("callback is missing an id")
        telegram._call(
            "answerCallbackQuery",
            token,
            {"callback_query_id": callback_id},
            None,
            http=http,
            sleep=_no_sleep,
        )
        return
    if kind == "document":
        path = row["document_path"]
        if not path:
            raise telegram.TelegramError("document is missing a path")
        fields: dict = {"chat_id": row["chat_id"]}
        caption = row["text"] or ""
        if caption:
            fields["caption"] = caption[: telegram.CAPTION_LIMIT]
        telegram._call(
            "sendDocument",
            token,
            fields,
            {"document": path},
            http=http,
            sleep=_no_sleep,
        )
        return
    text = (row["text"] or "").strip()
    if not text:
        raise telegram.TelegramError("message is empty")
    fields = {"chat_id": row["chat_id"], "text": text[:_MESSAGE_LIMIT]}
    keyboard = _load_keyboard(row["buttons_json"])
    if keyboard:
        fields["reply_markup"] = {"inline_keyboard": keyboard}
    telegram._call(
        "sendMessage",
        token,
        fields,
        None,
        http=http,
        sleep=_no_sleep,
    )


def _load_keyboard(raw):
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise telegram.TelegramError("buttons are not valid JSON") from exc
    if not isinstance(parsed, list) or not parsed:
        return None
    return parsed


def _ack(conn, row, routed: intent.Intent) -> None:
    callback_id = _field(row, "callback_id")
    if not callback_id:
        return
    idea_id = None
    if routed.kind == "action" and routed.idea_id:
        if store.get(conn, routed.idea_id) is not None:
            idea_id = routed.idea_id
    _enqueue_callback(conn, int(_field(row, "chat_id")), str(callback_id), idea_id)


def _enqueue_callback(conn, chat_id: int, callback_id: str, idea_id: int | None) -> None:
    with store._txn(conn):
        found = conn.execute(
            """
            SELECT id FROM outbox
            WHERE kind = 'callback' AND text = ?
            """,
            (callback_id,),
        ).fetchone()
        if found is not None:
            return
        _insert_outbox(conn, chat_id, "callback", callback_id, None, None, idea_id)


def _say(
    conn,
    row,
    text: str,
    keyboard=None,
    *,
    idea_id: int | None = None,
    document_path: str | None = None,
) -> None:
    chat_id = _field(row, "chat_id")
    if chat_id is None:
        return
    kind = "document" if document_path else "message"
    _enqueue(
        conn,
        int(chat_id),
        kind,
        text,
        buttons=keyboard,
        document_path=document_path,
        idea_id=idea_id,
    )


def _enqueue(
    conn,
    chat_id: int,
    kind: str,
    text: str,
    *,
    buttons=None,
    document_path: str | None = None,
    idea_id: int | None = None,
) -> None:
    with store._txn(conn):
        _insert_outbox(conn, chat_id, kind, text, buttons, document_path, idea_id)


def _insert_outbox(
    conn,
    chat_id: int,
    kind: str,
    text: str,
    buttons,
    document_path: str | None,
    idea_id: int | None,
) -> None:
    payload = json.dumps(buttons, ensure_ascii=False) if buttons else None
    conn.execute(
        """
        INSERT INTO outbox (
          chat_id, kind, text, buttons_json, document_path,
          attempts, next_try_at, sent_at, idea_id
        ) VALUES (?, ?, ?, ?, ?, 0, NULL, NULL, ?)
        """,
        (chat_id, kind, text, payload, document_path, idea_id),
    )


def _keyboard(buttons, idea_id: int, revision: int, width: int = 3) -> list:
    cells = [
        {
            "text": label,
            "callback_data": f"{action}:{idea_id}:{revision}",
        }
        for label, action in buttons
    ]
    return [cells[index:index + width] for index in range(0, len(cells), width)]


def _ensure_jobs(conn) -> None:
    conn.execute(_JOBS)


def _latest_analysis(conn, idea_id: int):
    return conn.execute(
        """
        SELECT * FROM analyses
        WHERE idea_id = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (idea_id,),
    ).fetchone()


def _latest_for_chat(conn, chat_id: int) -> store.Idea | None:
    row = conn.execute(
        """
        SELECT id FROM ideas
        WHERE source = 'telegram' AND source_ref LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"{int(chat_id)}:%",),
    ).fetchone()
    if row is None:
        return None
    return store.get(conn, int(row["id"]))


def _summary(idea: store.Idea, analysis) -> str:
    title = idea.title.strip() or _normalised_first_line(idea.original_text)
    names = _existing_names(analysis["report_path"])[:3]
    existing = "\n".join(f"- {name}" for name in names) if names else "- none"
    return (
        f"{title}\n"
        f"\n"
        f"Usefulness: {analysis['usefulness']}/9\n"
        f"MVP complexity: {analysis['complexity_mvp']}/9\n"
        f"Full complexity: {analysis['complexity_full']}/9\n"
        f"Verdict: {analysis['verdict']}\n"
        f"Confidence: {analysis['confidence']}\n"
        f"\n"
        f"Existing:\n"
        f"{existing}"
    )


def _existing_names(path: str) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    names: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            in_section = line.strip() == "## What already exists"
            continue
        if not in_section or not line.startswith("- **"):
            continue
        end = line.find("**", 4)
        if end > 4:
            names.append(line[4:end])
    return names


def _normalised_first_line(text: str) -> str:
    for line in text.splitlines():
        flat = " ".join(line.split())
        if flat:
            return flat
    return "(untitled)"


def _label(idea: store.Idea) -> str:
    title = idea.title.strip()
    if title:
        return _normalised_first_line(title)
    return _normalised_first_line(idea.original_text)


def _plain_fields(fields) -> tuple[dict, list[str]]:
    plain: dict = {}
    errors: list[str] = []
    for key, field in fields.items():
        value, error = _plain_value(key, field)
        if error:
            errors.append(error)
        else:
            plain[key] = value
    return plain, errors


def _plain_value(key: str, field: intent.Field):
    value = field.value
    if isinstance(value, intent.AgentWord):
        if value.name is None:
            return None, f"unknown agent {value.raw}"
        return value.name, None
    if isinstance(value, tuple):
        names: list[str] = []
        for item in value:
            if not isinstance(item, intent.AgentWord):
                return None, f"{key}: could not read {field.raw}"
            if item.name is None:
                return None, f"unknown agent {item.raw}"
            names.append(item.name)
        return names, None
    if value is None:
        return None, f"{key}: could not read {field.raw}"
    return value, None


def _show(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(_show(item) for item in value)
    return str(value)


def _stored_agents(conn) -> list[str] | None:
    raw = _kv(conn, _AGENTS_KEY)
    if raw is None:
        return None
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


def _message_id(row) -> int | None:
    mid = _field(row, "message_id")
    if mid is not None:
        return int(mid)
    update_id = _field(row, "update_id")
    if update_id is None:
        return None
    return int(update_id)


def _chat_from_ref(source_ref: str | None) -> int | None:
    if not source_ref or ":" not in source_ref:
        return None
    head, _sep, _tail = source_ref.partition(":")
    try:
        return int(head)
    except ValueError:
        return None


def _card_context(conn, chat_id: int):
    card = _card_for(conn, chat_id)
    if not card:
        return None
    return {"kind": card.get("kind"), "fields": card.get("fields") or {}}


def _card_for(conn, chat_id) -> dict | None:
    if chat_id is None:
        return None
    card = _map(conn, _CARD_KEY).get(str(int(chat_id)))
    return card if isinstance(card, dict) else None


def _remember_card(conn, chat_id: int, kind: str, idea_id: int, fields=None) -> None:
    with store._txn(conn):
        _remember_card_in(conn, chat_id, kind, idea_id, fields)


def _remember_card_in(conn, chat_id: int, kind: str, idea_id: int, fields) -> None:
    data = _map(conn, _CARD_KEY)
    data[str(int(chat_id))] = {
        "kind": kind,
        "idea_id": idea_id,
        "fields": fields or {},
    }
    _kv_set(conn, _CARD_KEY, json.dumps(data))


def _clear_card(conn, chat_id) -> None:
    if chat_id is None:
        return
    with store._txn(conn):
        data = _map(conn, _CARD_KEY)
        data.pop(str(int(chat_id)), None)
        _kv_set(conn, _CARD_KEY, json.dumps(data))


def _open_for(conn, chat_id: int):
    question = _map(conn, _OPEN_KEY).get(str(int(chat_id)))
    return question if isinstance(question, dict) else None


def _set_open(conn, chat_id: int, question: dict) -> None:
    with store._txn(conn):
        data = _map(conn, _OPEN_KEY)
        data[str(int(chat_id))] = question
        _kv_set(conn, _OPEN_KEY, json.dumps(data))


def _clear_open(conn, chat_id: int) -> None:
    with store._txn(conn):
        data = _map(conn, _OPEN_KEY)
        data.pop(str(int(chat_id)), None)
        _kv_set(conn, _OPEN_KEY, json.dumps(data))


def _map(conn, key: str) -> dict:
    raw = _kv(conn, key)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _kv(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _kv_set(conn, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _kv_set_txn(conn, key: str, value: str) -> None:
    with store._txn(conn):
        _kv_set(conn, key, value)


def _mark_handled(conn, row) -> None:
    update_id = _field(row, "update_id")
    if update_id is None:
        return
    conn.execute(
        "UPDATE inbound SET handled = 1 WHERE update_id = ?",
        (int(update_id),),
    )


def _field(row, name: str, default=None):
    if row is None:
        return default
    if isinstance(row, sqlite3.Row):
        if name not in row.keys():
            return default
        return row[name]
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return default


def _truthy(value) -> bool:
    return bool(value)


def _due(next_try_at, moment: str) -> bool:
    return next_try_at is None or next_try_at <= moment


def _now() -> str:
    return store._now()


def _add_minutes(stamp: str, minutes: int) -> str:
    parsed = datetime.strptime(stamp, _STAMP).replace(tzinfo=timezone.utc)
    parsed += timedelta(minutes=minutes)
    return (
        parsed.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{parsed.microsecond // 1000:03d}Z"
    )


def _no_sleep(_seconds: float) -> None:
    return None
