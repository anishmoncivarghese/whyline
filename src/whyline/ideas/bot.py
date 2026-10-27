"""Telegram cards, buttons, and a retrying outbox.

``handle`` turns one inbound row into ledger changes and outbox rows.
``flush_outbox`` is the only sender. A failed send waits 1, 5, 15, then
60 minutes, and stops after 8 attempts with an events note. A tap is
answered in ``telegram_in.poll_once``, not from this outbox.

Quick score inserts a ``jobs`` row for IDEA-13. It does not move the idea
to ``scoring``: ``analyse`` does that when the job runs, and it refuses a
second move into ``scoring``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from whyline.agents import capabilities, deliveries, service, telegram
from whyline.ideas import (
    actions,
    assistant,
    brainstorm,
    confirm,
    documents,
    intent,
    memory,
    reminders,
    requests,
    setup,
    store,
    xlsx,
)

OUT_OF_DATE = "This card is out of date"
REQUEST_OUT_OF_DATE = "This card is out of date."
CALLBACK_DATA_LIMIT = 64
REFINE_QUESTION = "What should I add?"
MAX_ATTEMPTS = 8
# Index by the attempt that just failed. Attempt 5 and later stay at 60.
BACKOFF_MINUTES = (1, 5, 15, 60)
# A gap explanation. flush_outbox sends this kind before every other due row.
_NOTICE = "notice"
_MESSAGE_LIMIT = 4096
_AGENTS_KEY = "default_agents"
_CARD_KEY = "telegram_card"
_OPEN_KEY = "telegram_open"
_SETTINGS_KEY = "telegram_settings"
_PROGRESS_KEY = "telegram_progress"
_DELIVERY_KEY = "telegram_delivery"
_MOVED = "Moved to the newer card ↓"
_ECHO = {
    "report": "▶ Full report",
    "excel": "▶ Excel",
    "refine": "▶ Refine",
    "drop": "▶ Drop",
}
# Labels stay within 14 characters so a phone does not truncate them.
# "Start brainstorm", "Create spec and plan" and "Brainstorm again" do not fit.
_STATUS_BUTTONS = {
    "captured": (
        ("Brainstorm", "brainstorm"),
        ("Quick score", "score"),
        ("Cancel", "cancel"),
    ),
    "scoring": (
        ("Brainstorm", "brainstorm"),
        ("Cancel", "cancel"),
    ),
    "scored": (
        ("Brainstorm", "brainstorm"),
        ("Full report", "report"),
        ("Refine", "refine"),
        ("Excel", "excel"),
        ("Drop", "drop"),
    ),
    "brainstorm_configuring": (
        ("Start", "start_brainstorm"),
        ("Edit", "edit"),
        ("Cancel", "cancel"),
    ),
    "brainstorming": (("Cancel", "cancel"),),
    "brainstormed": (
        ("Spec and plan", "plan"),
        ("Again", "brainstorm"),
        ("Drop", "drop"),
    ),
    "setup_configuring": (
        ("Confirm", "confirm"),
        ("Edit", "edit"),
        ("Cancel", "cancel"),
    ),
    "plan_waiting": (("Cancel", "cancel"),),
    "planning": (("Cancel", "cancel"),),
    "plan_review": (
        ("Start", "start_plan"),
        ("Change", "change_plan"),
        ("Discard", "discard_plan"),
    ),
    "plan_discarded": (("Reopen", "reopen"),),
    "dropped": (("Reopen", "reopen"),),
    "running": (
        ("Status", "status"),
        ("Stop", "stop"),
    ),
    "paused": (
        ("Status", "status"),
        ("Stop", "stop"),
    ),
    "stopped": (
        ("Resume", "resume"),
    ),
}
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
    "Start": "start_plan",
    "Start now": "start_now",
    "Change": "change_plan",
    "Discard": "discard_plan",
    "Retry": "retry_plan",
    "Stop": "stop",
    "Stop now": "stop_yes",
    "Refresh": "refresh",
    "Resume": "resume",
    "Status": "status",
    "Show evidence": "evidence",
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
/run <saved-agent>
/ask <repo> <question>
/remind <when> <text>
/remember <fact>
/forget <n>
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


def handle(
    conn: sqlite3.Connection,
    inbound,
    *,
    run_fn=None,
    http=None,
    now: datetime | None = None,
) -> None:
    """Route one inbound row and queue the reply.

    A row already marked handled is ignored. The tap itself was answered
    when the poll stored it. Full report and Excel send their echo and
    status through ``flush_outbox`` before the export so Telegram can
    show them; everything else waits for the caller's flush.
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
    _dispatch(conn, inbound, routed, run_fn, http=http, now=now)
    _mark_handled(conn, inbound)


def buttons_for(status: str) -> tuple[tuple[str, str], ...]:
    """``(label, action)`` for a card in this status. Empty when none apply."""
    found = _STATUS_BUTTONS.get(status)
    if found is None:
        return ()
    return found


def away_text(start: datetime, end: datetime, caught_up: int) -> str:
    """What the chat hears when the previous tick is more than ten minutes old.

    ``caught_up`` is how many updates this tick stored. Zero omits the
    catching-up clause. A gap of more than 23 hours adds Telegram's
    one-day limit, because older messages are gone.
    """
    text = (
        f"I was offline from {start:%H:%M} to {end:%H:%M} "
        "(Mac asleep or off)."
    )
    if caught_up:
        noun = "message" if caught_up == 1 else "messages"
        text += f" Catching up on {caught_up} {noun}."
    if end - start > timedelta(hours=23):
        text += (
            " Telegram keeps undelivered messages for about a day, "
            "so anything older may be lost; please resend it."
        )
    return text


def tell_allowed(conn: sqlite3.Connection, text: str) -> int:
    """Queue one plain message to each allowed chat. Returns how many.

    The row kind is ``notice``. A reply queued before sleep has a smaller
    id, and id order alone would deliver it first. No buttons, so this
    does not retire the card those chats are using.
    """
    from whyline.ideas import telegram_in

    chats = telegram_in.allowed_chats(conn)
    for chat_id in chats:
        _enqueue(conn, int(chat_id), _NOTICE, text)
    return len(chats)


def flush_outbox(conn: sqlite3.Connection, *, http=None) -> int:
    """Send due outbox rows. Return how many were sent.

    A row with ``sent_at`` set is not sent again. A row whose
    ``next_try_at`` is still ahead is left for a later call. The 30-second
    pause inside ``telegram._call`` is not used; this backoff is the retry.
    A ``notice`` goes out before every other due row, whatever its id, so
    a gap explanation is not stuck behind a reply queued before sleep.
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
        ORDER BY CASE WHEN kind = ? THEN 0 ELSE 1 END, id
        """,
        (MAX_ATTEMPTS, moment, _NOTICE),
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
    keyboard = _keyboard(buttons_for("scored"), idea.id, idea.revision)
    outbox_id = _enqueue(
        conn,
        chat_id,
        "message",
        _summary(idea, analysis),
        buttons=keyboard,
        idea_id=idea.id,
    )
    _remember_card(conn, chat_id, "score", idea.id, outbox_id=outbox_id)


def request_text(request: requests.Request) -> str:
    """Action summary as the title, then each argument as ``key: value``."""
    spec = actions.REGISTRY.get(request.action)
    title = spec.summary if spec is not None else request.action
    try:
        args = json.loads(request.args_json or "{}")
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict) or not args:
        return title
    lines = [title]
    for key, value in args.items():
        lines.append(f"{key}: {_show(value)}")
    return "\n".join(lines)


def offer_request(conn: sqlite3.Connection, request: requests.Request) -> None:
    """Queue a Confirm/Cancel card for a ``waiting_tap`` Telegram request."""
    if request.state != "waiting_tap" or request.chat_id is None:
        return
    chat_id = int(request.chat_id)
    code = confirm.issue(
        conn,
        scope="request",
        subject=f"request:{request.id}",
        actor=str(chat_id),
    )
    keyboard = _request_keyboard(request.id, code)
    _enqueue(conn, chat_id, "message", request_text(request), buttons=keyboard)


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


def _enable_hint(name: str) -> str:
    return f"Enable {name} in Settings or choose another provider."


def _subscription_enabled(name: str) -> bool:
    from whyline.agents.runner import _cli_permitted

    return _cli_permitted(name)


def score_agents(conn: sqlite3.Connection) -> list[str]:
    """Agents a quick score will try, first one named in the progress reply.

    ``default_agents`` wins when it is set. Otherwise every unattended
    agent that is installed and logged in, in Claude, Codex, Grok order.
    A stored name that Settings has turned off is skipped so a configured
    enabled backup can run; it is not replaced by some other provider.
    """
    stored = _stored_agents(conn)
    names = stored if stored is not None else _detected_agents()
    chosen: list[str] = []
    for name in names:
        if name in chosen:
            continue
        if capabilities.can_run_unattended(name) and _subscription_enabled(name):
            chosen.append(name)
    return chosen


def score_unavailable_reason(conn: sqlite3.Connection) -> str:
    """Why ``score_agents`` is empty. Names a disabled saved agent when that is why."""
    stored = _stored_agents(conn)
    if stored:
        off = next((name for name in stored if not _subscription_enabled(name)), None)
        if off:
            return _enable_hint(off)
    return "No agent can score unattended."


def _dispatch(
    conn, row, routed: intent.Intent, run_fn, *, http=None, now: datetime | None = None
) -> None:
    kind = routed.kind
    if kind == "capture":
        _capture(conn, row, routed)
    elif kind == "action":
        _action(conn, row, routed, run_fn, http=http)
    elif kind == "request":
        _request_tap(conn, row, routed)
    elif kind == "command":
        _command(conn, row, routed, http=http, now=now)
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
    keyboard = _keyboard(buttons_for("captured"), idea.id, idea.revision)
    # The flag and the card share a transaction, so a retry of this row
    # does not send a second card.
    with store._txn(conn):
        if _kv(conn, f"capture_card:{idea.id}"):
            return
        outbox_id = _insert_outbox(conn, chat_id, "message", line, keyboard, None, idea.id)
        _kv_set(conn, f"capture_card:{idea.id}", "1")
        _remember_card_in(conn, chat_id, "capture", idea.id, None, outbox_id=outbox_id)


_BRAINSTORM_FROM = frozenset({
    "captured",
    "scored",
    "brainstormed",
    "brainstorm_configuring",
})


def _action(conn, row, routed: intent.Intent, run_fn, *, http=None) -> None:
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
        _full_report(conn, row, idea, http=http)
    elif name == "excel":
        _excel(conn, row, idea, http=http)
    elif name == "drop":
        _ask_drop(conn, row, idea)
    elif name == "drop_yes":
        _drop(conn, row, idea)
    elif name == "reopen":
        _reopen(conn, row, idea)
    elif name == "refine":
        _ask_refine(conn, row, idea)
    elif name == "cancel":
        _cancel(conn, row, idea)
    elif name == "confirm":
        _confirm(conn, row, idea)
    elif name == "edit":
        _edit(conn, row, idea)
    elif name == "brainstorm":
        _open_brainstorm(conn, row, idea)
    elif name == "start_brainstorm":
        _start_brainstorm(conn, row, idea, run_fn)
    elif name == "plan":
        _open_setup(conn, row, idea)
    elif name == "start_plan":
        _ask_start_plan(conn, row, idea)
    elif name == "start_now":
        _start_now(conn, row, idea)
    elif name == "retry_start":
        from whyline.ideas import run as ideas_run

        ideas_run.enqueue_start(conn, idea.id)
        _say(conn, row, "Retrying…", idea_id=idea.id)
    elif name == "change_plan":
        _ask_change_plan(conn, row, idea)
    elif name == "discard_plan":
        _ask_discard_plan(conn, row, idea)
    elif name == "discard_plan_yes":
        _discard_plan(conn, row, idea)
    elif name == "retry_plan":
        if idea.status == "ready":
            from whyline.ideas import run as ideas_run

            ideas_run.enqueue_start(conn, idea.id)
            _say(conn, row, "Retrying…", idea_id=idea.id)
        else:
            from whyline.ideas import planning

            planning.enqueue_plan(conn, idea.id, action="resume", answer=None)
            _say(conn, row, "Retrying…", idea_id=idea.id)
    elif name.startswith("repo_"):
        repo_name = name[len("repo_") :]
        _choose_repo(conn, row, idea, repo_name)
    elif name in ("status", "refresh"):
        _send_status(conn, row, idea)
    elif name == "stop":
        _ask_stop(conn, row, idea)
    elif name == "stop_yes":
        _stop(conn, row, idea)
    elif name == "resume":
        _resume_from_stopped(conn, row, idea)
    elif name == "evidence":
        _show_evidence(conn, row, idea)
    elif name.startswith("confirm_resolve_"):
        option_id = name[len("confirm_resolve_") :]
        _handle_resolve(conn, row, idea, option_id, confirmed=True)
    elif name.startswith("resolve_"):
        option_id = name[len("resolve_") :]
        _handle_resolve(conn, row, idea, option_id, confirmed=False)
    else:
        _say(conn, row, "Not available yet.", idea_id=idea.id)


def _request_tap(conn, row, routed: intent.Intent) -> None:
    """Confirm or cancel a waiting_tap request. Nothing runs yet."""
    request_id = routed.request_id
    code = routed.code
    chat_id = _field(row, "chat_id")
    actor = str(chat_id) if chat_id is not None else ""
    if request_id is None or not code:
        _say(conn, row, REQUEST_OUT_OF_DATE)
        return
    if routed.name == "ok":
        try:
            requests.confirm(conn, request_id, code, actor=actor)
        except (requests.ConfirmError, requests.IllegalMove, LookupError):
            _say(conn, row, REQUEST_OUT_OF_DATE)
        return
    if routed.name != "no":
        _say(conn, row, REQUEST_OUT_OF_DATE)
        return
    if not confirm.consume(
        conn,
        code,
        scope="request",
        subject=f"request:{request_id}",
        actor=actor,
    ):
        _say(conn, row, REQUEST_OUT_OF_DATE)
        return
    try:
        requests.cancel(conn, request_id)
    except (requests.IllegalMove, LookupError):
        _say(conn, row, REQUEST_OUT_OF_DATE)


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


def _command(
    conn, row, routed: intent.Intent, *, http=None, now: datetime | None = None
) -> None:
    name = routed.name
    if name == "list":
        _list(conn, row)
    elif name == "help":
        _say(conn, row, HELP_TEXT)
    elif name == "excel":
        _excel(conn, row, None, http=http)
    elif name == "drop":
        _command_drop(conn, row, routed)
    elif name == "status":
        _command_status(conn, row, routed)
    elif name == "run":
        _command_run(conn, row, routed)
    elif name == "ask":
        _command_ask(conn, row, routed)
    elif name == "remind":
        _command_remind(conn, row, routed, now=now)
    elif name == "remember":
        _command_remember(conn, row, routed)
    elif name == "forget":
        _command_forget(conn, row, routed)
    elif name == "stop":
        _command_stop(conn, row, routed)
    elif name == "new":
        _say(conn, row, "Send the idea as a message.")
    else:
        _say(conn, row, "Not available yet.")


def _command_remind(
    conn, row, routed: intent.Intent, *, now: datetime | None = None
) -> None:
    moment = now or datetime.now().astimezone().replace(tzinfo=None)
    try:
        reminder = reminders.add(
            conn,
            int(_field(row, "chat_id")),
            " ".join(routed.args),
            now=moment,
        )
    except reminders.TimeParseError:
        _say(conn, row, reminders.BAD_TIME)
        return
    due = datetime.fromisoformat(reminder.due_at)
    _say(conn, row, f"I'll remind you {reminders.due_in_words(due, moment)}.")


def _command_remember(conn, row, routed: intent.Intent) -> None:
    fact = " ".join(routed.args).strip()
    if not fact:
        _say(conn, row, "remember needs a fact.")
        return
    try:
        count = memory.add(fact)
    except memory.MemoryFullError:
        _say(conn, row, memory.MEMORY_FULL)
        return
    _say(conn, row, f"Remembered ({count}).")


def _command_forget(conn, row, routed: intent.Intent) -> None:
    if not routed.args:
        _say(conn, row, "forget needs a line number.")
        return
    try:
        n = int(routed.args[0])
    except ValueError:
        _say(conn, row, "forget needs a line number.")
        return
    try:
        count = memory.forget(n)
    except (IndexError, ValueError):
        _say(conn, row, f"No memory item {n}.")
        return
    _say(conn, row, f"Forgot ({count}).")


def create_run_request(
    conn: sqlite3.Connection,
    name: str,
    *,
    channel: str,
    actor: str,
    chat_id: int | None,
) -> tuple[requests.Request | None, str | None]:
    """Create a keyword run request for one exact saved-agent name."""
    found = next(
        (
            item
            for item in service.rows(None)
            if getattr(getattr(item, "defn", None), "name", None) == name
        ),
        None,
    )
    if found is None:
        return None, f"No saved agent named {name}."
    request = requests.create(
        conn,
        channel=channel,
        actor=actor,
        chat_id=chat_id,
        action="run_agent",
        args={"agent": name},
        proposed_by="keyword",
    )
    defn = found.defn
    delivery = deliveries.get(defn.agent_id)
    needs_tap = int(getattr(defn, "timeout_minutes", 15)) > 15 or bool(
        delivery is not None and str(getattr(delivery, "command", "")).strip()
    )
    if needs_tap and request.state == "queued":
        conn.execute(
            """
            UPDATE requests SET state = 'waiting_tap', approval = 'tap'
            WHERE id = ? AND state = 'queued'
            """,
            (request.id,),
        )
        request = requests._request(
            conn.execute(
                "SELECT * FROM requests WHERE id = ?", (request.id,)
            ).fetchone()
        )
    return request, None


def _command_run(conn, row, routed: intent.Intent) -> None:
    if len(routed.args) != 1 or str(_field(row, "kind", "")).endswith(
        "_attachment"
    ):
        _say(conn, row, "run takes only a saved agent's name.")
        return
    chat_id = int(_field(row, "chat_id"))
    request, error = create_run_request(
        conn,
        routed.args[0],
        channel="telegram",
        actor=str(chat_id),
        chat_id=chat_id,
    )
    if error:
        _say(conn, row, error)
        return
    if request is None:
        return
    if request.state == "waiting_tap":
        offer_request(conn, request)
    elif request.state == "refused":
        _say(conn, row, request.error or "Run is turned off in the console.")


def _command_ask(conn, row, routed: intent.Intent) -> None:
    repos = setup.list_repos(conn)
    args = list(routed.args)
    if not args:
        _say(conn, row, "ask needs a question.")
        return
    if len(repos) == 1:
        repo = next(iter(repos))
        question_parts = args[1:] if args[0] == repo else args
    else:
        repo = args[0]
        question_parts = args[1:]
        if repo not in repos:
            allowed = ", ".join(repos) if repos else "(none)"
            _say(conn, row, f"Unknown repo {repo}. Allowed repos: {allowed}.")
            return
    if repo not in repos:
        allowed = ", ".join(repos) if repos else "(none)"
        _say(conn, row, f"Unknown repo {repo}. Allowed repos: {allowed}.")
        return
    question = " ".join(question_parts).strip()
    if not question:
        _say(conn, row, "ask needs a question.")
        return
    chat_id = int(_field(row, "chat_id"))
    created = requests.create(
        conn,
        channel="telegram",
        actor=str(chat_id),
        chat_id=chat_id,
        action="ask_repo",
        args={"repo": repo, "question": question},
        proposed_by="keyword",
    )
    if created.state == "waiting_tap":
        offer_request(conn, created)
    elif created.state == "refused":
        _say(conn, row, created.error or "Ask is turned off in the console.")


def _settings(conn, row, routed: intent.Intent) -> None:
    card = _card_for(conn, _field(row, "chat_id"))
    if (
        card
        and card.get("kind") == "brainstorm"
        and not _PLAN_KEYS.intersection(routed.fields)
    ):
        _update_brainstorm_card(conn, row, routed, card)
        return
    if (
        card
        and card.get("kind") in {"setup", "plan_setup"}
    ):
        _update_setup_card(conn, row, routed, card)
        return
    plain, errors = _plain_fields(routed.fields)
    if errors:
        _say(conn, row, "\n".join(errors))
        return
    kind = "plan_setup" if _PLAN_KEYS.intersection(plain) else "brainstorm_settings"
    chat_id = int(_field(row, "chat_id"))
    idea = _latest_for_chat(conn, chat_id)
    if idea and idea.status == "setup_configuring":
        _update_setup_card(conn, row, routed, card or {"idea_id": idea.id, "fields": {}})
        return
    summary = ", ".join(f"{key}: {_show(value)}" for key, value in plain.items())
    card = assistant.confirm_card(kind, summary=summary or "Settings", fields=plain, idea=idea)
    _send_named_card(conn, row, card, idea, kind=kind, fields=plain)


def _answer(conn, row, routed: intent.Intent) -> None:
    chat_id = int(_field(row, "chat_id"))
    question = _open_for(conn, chat_id)
    _clear_open(conn, chat_id)
    if not question:
        _say(conn, row, "Nothing is waiting for an answer.")
        return
    q_kind = question.get("kind")
    if q_kind not in {"refine", "plan_question", "change_plan"}:
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

    if q_kind == "refine":
        extra = routed.text.strip()
        if extra:
            _append_context(conn, idea, extra)
            idea = store.get(conn, idea.id)
        _quick_score(conn, row, idea)
        return

    if q_kind == "plan_question":
        from whyline.ideas import planning

        reply = routed.text.strip()
        planning.enqueue_plan(conn, idea.id, action="resume", answer=reply)
        _say(conn, row, "Resuming plan with your answer…", idea_id=idea.id)
        return

    if q_kind == "change_plan":
        from whyline.ideas import planning

        reply = routed.text.strip()
        planning.enqueue_plan(conn, idea.id, action="redraft", feedback=reply)
        _say(conn, row, "Redrafting plan with your changes…", idea_id=idea.id)
        return


def _free(conn, row, routed: intent.Intent, run_fn) -> None:
    chat_id = int(_field(row, "chat_id"))
    idea = _latest_for_chat(conn, chat_id)
    kwargs = {}
    try:
        import inspect

        params = inspect.signature(assistant.propose).parameters
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if has_varkw or "chat_id" in params:
            kwargs = {
                "chat_id": chat_id,
                "channel": "telegram",
                "actor": str(chat_id),
            }
    except (ValueError, TypeError):
        pass
    try:
        proposal = assistant.propose(
            conn,
            routed.text,
            idea=idea,
            context=_card_context(conn, chat_id),
            run_fn=run_fn,
            **kwargs,
        )
    except TypeError as exc:
        if kwargs and ("unexpected keyword" in str(exc) or "chat_id" in str(exc)):
            proposal = assistant.propose(
                conn,
                routed.text,
                idea=idea,
                context=_card_context(conn, chat_id),
                run_fn=run_fn,
            )
        else:
            raise
    if proposal.request is not None:
        req = proposal.request
        if req.state == "waiting_tap":
            offer_request(conn, req)
            return
        if req.state == "refused":
            _say(
                conn,
                row,
                req.error or str(proposal),
                idea_id=idea.id if idea is not None else None,
            )
            return

    if proposal.kind == "status" and proposal.error is None:
        from whyline.ideas import watch

        bound = idea
        if bound is None and proposal.card and proposal.card.idea_id is not None:
            bound = store.get(conn, proposal.card.idea_id)
        if bound is None and isinstance(proposal.fields, dict) and proposal.fields.get("idea_id"):
            try:
                bound = store.get(conn, int(proposal.fields["idea_id"]))
            except (ValueError, TypeError):
                pass
        target = bound or watch.find_idea_for_status(conn, chat_id=chat_id)
        if target is not None:
            _send_status(conn, row, target)
            return

    if proposal.card is not None:
        bound = idea
        if bound is None and proposal.card.idea_id is not None:
            bound = store.get(conn, proposal.card.idea_id)
        if (
            proposal.kind == "brainstorm_settings"
            and proposal.error is None
            and _apply_brainstorm_proposal(conn, row, bound, proposal)
        ):
            return
        if (
            proposal.kind in {"plan_setup", "setup"}
            and proposal.error is None
            and _apply_setup_proposal(conn, row, bound, proposal)
        ):
            return
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
        _say(conn, row, score_unavailable_reason(conn), idea_id=idea.id)
        return
    if not enqueue_score(conn, idea.id):
        _say(conn, row, "Already scoring.", idea_id=idea.id)
        return
    chat_id = int(_field(row, "chat_id"))
    begin_progress(
        conn,
        chat_id,
        idea.id,
        (
            f"Quick score started with {agents[0]}. "
            "Usually 2-5 minutes; I'll message you when it's done."
        ),
    )
    _retarget_buttons(conn, idea, "scoring")


def _full_report(conn, row, idea: store.Idea, *, http=None) -> None:
    _echo(conn, row, "report", idea.id)
    analysis = _latest_analysis(conn, idea.id)
    if analysis is None or not Path(analysis["report_path"]).is_file():
        _say(conn, row, "No report yet.", idea_id=idea.id)
        return
    md = Path(analysis["report_path"])
    chat_id = int(_field(row, "chat_id"))
    begin_progress(conn, chat_id, idea.id, "Preparing your report as Word and PDF…")
    # Send now: edit_progress overwrites this row, and Telegram never
    # sees Preparing if the export finishes before the caller's flush.
    flush_outbox(conn, http=http)
    try:
        exported = documents.export(md)
    except (OSError, ValueError) as exc:
        edit_progress(
            conn, idea.id, f"Couldn't prepare the report: {exc}", chat_id=chat_id, http=http
        )
        return
    note = " ".join(item for item in exported.notes if item)
    made = [path for path in (exported.docx, exported.pdf) if path is not None]
    if not made:
        edit_progress(
            conn,
            idea.id,
            f"Couldn't prepare the report: {note or 'Word and PDF could not be written.'}",
            chat_id=chat_id,
            http=http,
        )
        _send_documents(conn, row, idea, exported, md)
        return
    if exported.docx is not None and exported.pdf is None:
        edit_progress(
            conn, idea.id, f"Sent Word only: {note}", chat_id=chat_id, http=http
        )
    elif exported.pdf is not None and exported.docx is None:
        edit_progress(
            conn, idea.id, f"Sent PDF only: {note}", chat_id=chat_id, http=http
        )
    else:
        edit_progress(conn, idea.id, "Report sent ↓", chat_id=chat_id, http=http)
    _send_documents(conn, row, idea, exported, md)


def _send_documents(conn, row, idea: store.Idea, exported, md: Path) -> None:
    """Word and PDF, or Word with the note, or the Markdown file."""
    note = " ".join(item for item in exported.notes if item)
    made = [path for path in (exported.docx, exported.pdf) if path is not None]
    if not made:
        outbox_id = _say(
            conn,
            row,
            note or "Report",
            document_path=str(md),
            idea_id=idea.id,
        )
        if outbox_id is not None:
            mark_delivery(conn, outbox_id, "report")
        return
    for index, path in enumerate(made):
        caption = note if index == 0 and note else ""
        outbox_id = _say(conn, row, caption, document_path=str(path), idea_id=idea.id)
        if outbox_id is not None:
            mark_delivery(conn, outbox_id, "report")


def _excel(conn, row, idea: store.Idea | None, *, http=None) -> None:
    if idea is not None:
        _echo(conn, row, "excel", idea.id)
    chat_id = _field(row, "chat_id")
    if idea is not None and chat_id is not None:
        begin_progress(conn, int(chat_id), idea.id, "Rebuilding your workbook…")
        flush_outbox(conn, http=http)
    try:
        path = xlsx.export(conn)
    except OSError as exc:
        if idea is not None:
            edit_progress(
                conn,
                idea.id,
                f"Couldn't rebuild the workbook: {exc}",
                chat_id=chat_id,
                http=http,
            )
        else:
            _say(conn, row, f"Could not write the workbook: {exc}")
        return
    if idea is not None:
        edit_progress(conn, idea.id, "Workbook sent ↓", chat_id=chat_id, http=http)
    outbox_id = _say(
        conn,
        row,
        "Ideas",
        document_path=str(path),
        idea_id=idea.id if idea is not None else None,
    )
    if outbox_id is not None and idea is not None:
        mark_delivery(conn, outbox_id, "excel")


def _ask_drop(conn, row, idea: store.Idea) -> None:
    _echo(conn, row, "drop", idea.id)
    chat_id = int(_field(row, "chat_id"))
    keyboard = _keyboard(
        (("Drop", "drop_yes"), ("Cancel", "cancel")),
        idea.id,
        idea.revision,
    )
    outbox_id = _say(conn, row, "Drop this idea?", keyboard, idea_id=idea.id)
    _remember_card(conn, chat_id, "drop_confirm", idea.id, outbox_id=outbox_id)


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
    fresh = store.get(conn, idea.id) or idea
    _say(
        conn,
        row,
        "Dropped. Reopen any time.",
        _keyboard(buttons_for("dropped"), fresh.id, fresh.revision),
        idea_id=fresh.id,
    )


def _reopen(conn, row, idea: store.Idea) -> None:
    try:
        fresh = store.transition(
            conn,
            idea.id,
            "captured",
            expected_revision=idea.revision,
            actor="telegram",
            note="reopened",
        )
    except store.StaleRevision:
        _say(conn, row, OUT_OF_DATE, idea_id=idea.id)
        return
    except store.IllegalMove as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return
    _say(conn, row, "Reopened.", idea_id=fresh.id)
    _retarget_buttons(conn, fresh, "captured")


def _ask_refine(conn, row, idea: store.Idea) -> None:
    _echo(conn, row, "refine", idea.id)
    _set_open(
        conn,
        int(_field(row, "chat_id")),
        {"idea_id": idea.id, "kind": "refine"},
    )
    _say(conn, row, REFINE_QUESTION, idea_id=idea.id)


def _cancel(conn, row, idea: store.Idea) -> None:
    """Stop a live job, or drop a captured idea that is sitting idle.

    Scoring's Cancel stops the job and restores the captured buttons even
    when analyse has not moved the idea yet. A brainstorm Cancel returns
    the idea to where it came from. A confirm card's Cancel does not drop.
    """
    score = _live_job(conn, idea.id, "score")
    if score is not None or idea.status == "scoring":
        if score is not None:
            _stop_job(conn, score)
        fresh = _move_or_keep(conn, idea, "captured", "cancelled")
        _say(conn, row, "Cancelled.", idea_id=idea.id)
        _retarget_buttons(conn, fresh, "captured")
        return
    brain = _live_job(conn, idea.id, "brainstorm")
    if brain is not None or idea.status in {"brainstorming", "brainstorm_configuring"}:
        if brain is not None:
            _stop_job(conn, brain)
        target = _brainstorm_return(
            conn, idea.id, allow_brainstormed=idea.status == "brainstorming"
        )
        fresh = _move_or_keep(conn, idea, target, "cancelled")
        _say(conn, row, "Cancelled.", idea_id=idea.id)
        _retarget_buttons(conn, fresh, fresh.status)
        _clear_card(conn, _field(row, "chat_id"))
        return
    if idea.status in {"setup_configuring", "plan_waiting", "planning"}:
        plan_job = _live_job(conn, idea.id, "plan")
        if plan_job is not None:
            _stop_job(conn, plan_job)
        _kv_set_txn(conn, f"plan_waiting_told:{idea.id}", "")
        fresh = _move_or_keep(conn, idea, "brainstormed", "cancelled")
        _say(conn, row, "Cancelled.", idea_id=idea.id)
        _retarget_buttons(conn, fresh, "brainstormed")
        _clear_card(conn, _field(row, "chat_id"))
        return
    if idea.status == "ready":
        start_job = _live_job(conn, idea.id, "start")
        if start_job is not None:
            _stop_job(conn, start_job)
        fresh = _move_or_keep(conn, idea, "plan_discarded", "cancelled")
        _say(conn, row, "Cancelled.", idea_id=idea.id)
        _retarget_buttons(conn, fresh, "plan_discarded")
        _clear_card(conn, _field(row, "chat_id"))
        return
    card = _card_for(conn, _field(row, "chat_id"))
    kind = card.get("kind") if card else "capture"
    fresh = idea
    if kind == "capture" and idea.status == "captured":
        fresh = _move_or_keep(conn, idea, "dropped", "cancelled")
    _say(conn, row, "Cancelled.", idea_id=idea.id)
    status = fresh.status if fresh.status in _STATUS_BUTTONS else "captured"
    _retarget_buttons(conn, fresh, status)
    _clear_card(conn, _field(row, "chat_id"))


def _confirm(conn, row, idea: store.Idea) -> None:
    card = _card_for(conn, _field(row, "chat_id"))
    fields = card.get("fields") if card else None
    if isinstance(fields, dict) and fields:
        _kv_set_txn(conn, f"{_SETTINGS_KEY}:{idea.id}", json.dumps(fields))
    if idea.status == "setup_configuring" or (
        card and card.get("kind") in {"setup", "plan_setup"}
    ):
        from whyline.ideas import planning

        planning.enqueue_plan(conn, idea.id)
    _say(conn, row, "Confirmed.", idea_id=idea.id)


def _ask_change_plan(conn, row, idea: store.Idea) -> None:
    chat_id = int(_field(row, "chat_id"))
    _set_open(conn, chat_id, {"kind": "change_plan", "idea_id": idea.id})
    _say(conn, row, "What should change?", idea_id=idea.id)


def _ask_start_plan(conn, row, idea: store.Idea) -> None:
    from whyline.ideas import planning, setup

    repo_name, root = planning._get_repo_root(conn, idea)
    plan_name = Path(idea.plan_path).name if idea.plan_path else (idea.title or "plan")

    raw = _kv(conn, f"telegram_settings:{idea.id}") or _kv(conn, "telegram_settings")
    fields = json.loads(raw) if raw else {}
    req_fields = setup.request_from_fields(fields)
    implementer = req_fields.implementer
    tester = req_fields.tester
    reviewer = req_fields.reviewer
    has_explicit_timeout = "timeout" in fields
    timeout = req_fields.timeout if has_explicit_timeout else None

    if not implementer or not tester or not reviewer or timeout is None:
        try:
            req_def, _ = setup.defaults(conn, idea.id, repo_name, root)
            implementer = implementer or req_def.implementer
            tester = tester or req_def.tester
            reviewer = reviewer or req_def.reviewer
            if timeout is None:
                timeout = req_def.timeout
        except Exception:
            pass

    if timeout is None:
        timeout = 30
    timeout_str = str(timeout)
    question = (
        f"Start {plan_name} in {repo_name} with "
        f"{implementer}, {tester}, {reviewer}, timeout {timeout_str}?"
    )

    keyboard = _keyboard(
        (("Start now", "start_now"), ("Cancel", "cancel")),
        idea.id,
        idea.revision,
    )
    chat_id = int(_field(row, "chat_id"))
    outbox_id = _say(conn, row, question, keyboard, idea_id=idea.id)
    _remember_card(
        conn, chat_id, "start_confirm", idea.id, outbox_id=outbox_id
    )


def _start_now(conn, row, idea: store.Idea) -> None:
    from whyline.ideas import run as ideas_run

    try:
        fresh = store.transition(
            conn,
            idea.id,
            "ready",
            expected_revision=idea.revision,
            actor="telegram",
            note="start",
        )
    except store.StaleRevision:
        _say(conn, row, OUT_OF_DATE, idea_id=idea.id)
        return
    except store.IllegalMove as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return

    ideas_run.enqueue_start(conn, fresh.id)
    _clear_card(conn, _field(row, "chat_id"))


def _ask_discard_plan(conn, row, idea: store.Idea) -> None:
    keyboard = _keyboard(
        (("Discard", "discard_plan_yes"), ("Cancel", "cancel")),
        idea.id,
        idea.revision,
    )
    chat_id = int(_field(row, "chat_id"))
    outbox_id = _say(conn, row, "Discard this plan?", keyboard, idea_id=idea.id)
    _remember_card(
        conn, chat_id, "discard_confirm", idea.id, outbox_id=outbox_id
    )


def _discard_plan(conn, row, idea: store.Idea) -> None:
    from whyline.console import auto_run
    from whyline.ideas import setup

    repos = setup.list_repos(conn)
    repo_name = idea.repo or ""
    path_str = repos.get(repo_name)
    if path_str:
        root = Path(path_str)
        try:
            auto_run.stop(root)
        except Exception:
            pass

    try:
        fresh = store.transition(
            conn,
            idea.id,
            "plan_discarded",
            expected_revision=idea.revision,
            actor="telegram",
            note="discarded",
        )
    except (store.IllegalMove, store.StaleRevision) as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return

    text = f"Plan discarded.\nSpec: {fresh.spec_path}\nPlan: {fresh.plan_path}"
    _say(conn, row, text, idea_id=fresh.id)
    _retarget_buttons(conn, fresh, "plan_discarded")
    _clear_card(conn, _field(row, "chat_id"))


def _send_status(
    conn: store.sqlite3.Connection,
    row,
    idea: store.Idea,
    preamble: str | None = None,
) -> None:
    from whyline.ideas import watch

    status_text, buttons = watch.build_status(conn, idea)
    keyboard = _keyboard(buttons, idea.id, idea.revision)
    full_text = f"{preamble}\n\n{status_text}" if preamble else status_text
    chat_id = _field(row, "chat_id")
    outbox_id = _say(conn, row, full_text, keyboard, idea_id=idea.id)
    if chat_id is not None and outbox_id is not None:
        _remember_card(conn, int(chat_id), "status", idea.id, outbox_id=outbox_id)


def _command_status(conn: store.sqlite3.Connection, row, routed: intent.Intent) -> None:
    target = routed.args[0] if routed.args else ""
    lookup = target.lower()
    _record_status_request(conn, row, target)
    if lookup == "agents":
        _say(conn, row, _agents_status())
        return
    if lookup == "relay":
        _say(conn, row, _relay_status(conn))
        return
    if target and not target.isdigit():
        _say(conn, row, _agent_status(lookup, shown_name=target))
        return

    from whyline.ideas import watch

    chat_id = _field(row, "chat_id")
    idea_id = int(target) if target else None
    idea = watch.find_idea_for_status(
        conn, chat_id=int(chat_id) if chat_id is not None else None, idea_id=idea_id
    )
    if idea is None:
        _say(conn, row, "No idea in progress.")
        return
    _send_status(conn, row, idea)


def _record_status_request(conn: sqlite3.Connection, row, target: str) -> None:
    """Record a synchronous keyword status request without queueing a worker."""
    moment = store._now()
    chat_id = _field(row, "chat_id")
    actor = None if chat_id is None else str(chat_id)
    args = {"target": target} if target else {}
    conn.execute(
        """
        INSERT INTO requests (
          created_at, channel, actor, chat_id, action, args_json,
          proposed_by, state, approval, started_at, finished_at
        ) VALUES (?, 'telegram', ?, ?, 'status', ?, 'keyword', 'done', 'none', ?, ?)
        """,
        (moment, actor, chat_id, json.dumps(args), moment, moment),
    )


def _agents_status() -> str:
    found = service.rows(None)
    lines = []
    for item in found:
        defn = item.defn
        name = getattr(defn, "name", None)
        if not name:
            name = getattr(getattr(defn, "path", None), "stem", "unknown")
        paused = "paused" if item.status == "paused" else "not paused"
        if item.last_outcome or item.last_run:
            outcome = item.last_outcome or "unknown outcome"
            when = item.last_run or "unknown time"
            lines.append(f"{name} — {outcome} — {when} — {paused}")
        else:
            lines.append(f"{name} — no runs — {paused}")
    return _limited_lines(lines, empty="No saved agents.")


def _agent_status(name: str, *, shown_name: str | None = None) -> str:
    shown_name = shown_name or name
    try:
        runs = service.history(name, None, 3)
    except service.AgentNotFound:
        return f"No saved agent named {shown_name}."
    except service.Ambiguous as error:
        return str(error)
    if not runs:
        return f"{shown_name} has not run yet."
    lines = []
    for run in runs:
        when = run.started[:16].replace("T", " ") if run.started else "unknown time"
        outcome = run.outcome or "unknown outcome"
        reason = (run.reason or "").splitlines()[0].strip() if run.reason else ""
        lines.append(f"{when} — {outcome} — {reason or 'no reason'}")
    return _limited_lines(lines)


def _relay_status(conn: sqlite3.Connection) -> str:
    from whyline_relay import state as relay_state

    lines = []
    for name, raw_root in setup.list_repos(conn).items():
        root = Path(raw_root)
        if not relay_state.path(root).is_file():
            continue
        saved = relay_state.load(root)
        if saved is None:
            lines.append(
                f"{name} — plan: —; task: —; stage: —; paused: unreadable state"
            )
            continue
        paused = saved.paused_reason or "not paused"
        lines.append(
            f"{name} — plan: {saved.plan or '—'}; task: {saved.task_id or '—'}; "
            f"stage: {saved.stage or '—'}; paused: {paused}"
        )
    return _limited_lines(lines, empty="No relay state found.")


def _limited_lines(lines: list[str], *, empty: str = "") -> str:
    """Fit whole logical rows in one Telegram message, naming omitted rows."""
    if not lines:
        return empty
    full = "\n".join(lines)
    if len(full) < _MESSAGE_LIMIT:
        return full
    for kept in range(len(lines) - 1, -1, -1):
        suffix = f"…and {len(lines) - kept} more"
        prefix = "\n".join(lines[:kept])
        candidate = f"{prefix}\n{suffix}" if prefix else suffix
        if len(candidate) < _MESSAGE_LIMIT:
            return candidate
    return f"…and {len(lines)} more"


def _command_stop(conn: store.sqlite3.Connection, row, routed: intent.Intent) -> None:
    from whyline.ideas import watch

    chat_id = _field(row, "chat_id")
    idea_id = int(routed.args[0]) if routed.args else None
    idea = watch.find_idea_for_status(
        conn, chat_id=int(chat_id) if chat_id is not None else None, idea_id=idea_id
    )
    if idea is None:
        _say(conn, row, "No idea in progress.")
        return
    _ask_stop(conn, row, idea)


def _ask_stop(conn: store.sqlite3.Connection, row, idea: store.Idea) -> None:
    chat_id = _field(row, "chat_id")
    keyboard = _keyboard(
        (("Stop now", "stop_yes"), ("Cancel", "cancel")),
        idea.id,
        idea.revision,
    )
    title = idea.title.strip() or f"idea {idea.id}"
    outbox_id = _say(conn, row, f"Stop {title}?", keyboard, idea_id=idea.id)
    if chat_id is not None and outbox_id is not None:
        _remember_card(conn, int(chat_id), "stop_confirm", idea.id, outbox_id=outbox_id)


def _stop(conn: store.sqlite3.Connection, row, idea: store.Idea) -> None:
    from whyline.ideas import run as ideas_run, watch

    repo_name, root = ideas_run._get_repo_root(conn, idea)
    if root is not None and root.exists():
        watch.stop_relay(root)
    fresh = idea
    if idea.status != "stopped":
        try:
            fresh = store.transition(
                conn,
                idea.id,
                "stopped",
                expected_revision=idea.revision,
                actor="stop",
                note="stopped",
            )
        except (store.IllegalMove, store.StaleRevision):
            fresh = store.get(conn, idea.id) or idea
    keyboard = _keyboard((("Resume", "resume"),), fresh.id, fresh.revision)
    _say(conn, row, "Stopped.", keyboard, idea_id=fresh.id)


def _resume_from_stopped(conn: store.sqlite3.Connection, row, idea: store.Idea) -> None:
    from whyline.ideas import run as ideas_run, watch

    repo_name, root = ideas_run._get_repo_root(conn, idea)
    if root is None or not root.exists():
        _say(conn, row, "Repository not found.", idea_id=idea.id)
        return
    result = watch.resume_relay(root, idea.id, conn)
    fresh = idea
    if idea.status == "stopped":
        try:
            fresh = store.transition(
                conn,
                idea.id,
                "running",
                expected_revision=idea.revision,
                actor="recovery",
                note="resumed",
            )
        except (store.IllegalMove, store.StaleRevision):
            fresh = store.get(conn, idea.id) or idea
    _send_status(conn, row, fresh, preamble=result)


def _handle_resolve(
    conn: store.sqlite3.Connection,
    row,
    idea: store.Idea,
    option_id: str,
    *,
    confirmed: bool = False,
) -> None:
    from whyline.ideas import watch

    reply_text, fresh, needs_confirm, confirm_label = watch.handle_resolve(
        conn, idea, option_id, confirmed=confirmed
    )
    if needs_confirm:
        keyboard = _keyboard(
            (("Confirm", f"confirm_resolve_{option_id}"), ("Cancel", "cancel")),
            fresh.id,
            fresh.revision,
        )
        _say(conn, row, reply_text, keyboard, idea_id=fresh.id)
        return

    keyboard = None
    if fresh.status == "running":
        keyboard = _keyboard(
            buttons_for("running"), fresh.id, fresh.revision
        )
    elif fresh.status == "stopped":
        keyboard = _keyboard((("Resume", "resume"),), fresh.id, fresh.revision)

    _say(conn, row, reply_text, keyboard, idea_id=fresh.id)


def _show_evidence(conn: store.sqlite3.Connection, row, idea: store.Idea) -> None:
    from whyline.console import recovery
    from whyline.ideas import run as ideas_run

    repo_name, root = ideas_run._get_repo_root(conn, idea)
    if root is None or not root.exists():
        _say(conn, row, "Repository not found.", idea_id=idea.id)
        return
    saved = None
    try:
        from whyline_relay import state as relay_state

        saved = relay_state.load(root)
    except Exception:
        pass
    paused_reason = saved.paused_reason if saved else ""
    problems = recovery.diagnose(root, [], paused_reason)
    if not problems:
        _say(conn, row, "No evidence available.", idea_id=idea.id)
        return
    problem = problems[0]
    lines = [problem.summary, *problem.evidence]
    _say(conn, row, "\n".join(lines), idea_id=idea.id)


def _edit(conn, row, idea: store.Idea) -> None:
    from whyline.ideas import setup

    card = _card_for(conn, _field(row, "chat_id"))
    template = (
        brainstorm.TEMPLATE
        if card and card.get("kind") == "brainstorm"
        else setup.TEMPLATE
        if card and card.get("kind") in {"setup", "plan_setup"}
        else _SETTINGS_TEMPLATE
    )
    _say(
        conn,
        row,
        "Send a key: value message.\n\n" + template,
        idea_id=idea.id,
    )


def _open_brainstorm(conn, row, idea: store.Idea) -> None:
    # The scoring card is required to offer Brainstorm. scoring cannot move
    # straight to brainstorm_configuring, so the score stops first.
    idea = _stop_score_for_brainstorm(conn, idea)
    if idea.status not in _BRAINSTORM_FROM:
        _say(
            conn,
            row,
            f"This idea can't be brainstormed from {idea.status}.",
            idea_id=idea.id,
        )
        return
    request, notes = brainstorm.defaults(conn)
    if not request.models:
        text = "No agent can brainstorm unattended."
        if notes:
            text = text + "\n" + "\n".join(notes)
        _say(conn, row, text, idea_id=idea.id)
        return
    if idea.status != "brainstorm_configuring":
        try:
            idea = store.transition(
                conn,
                idea.id,
                "brainstorm_configuring",
                expected_revision=idea.revision,
                actor="telegram",
                note=idea.status,
            )
        except store.StaleRevision:
            _say(conn, row, OUT_OF_DATE, idea_id=idea.id)
            return
        except store.IllegalMove as exc:
            _say(conn, row, str(exc), idea_id=idea.id)
            return
    _show_brainstorm(conn, row, idea, request, notes)


def _update_brainstorm_card(conn, row, routed: intent.Intent, card: dict) -> None:
    idea_id = card.get("idea_id")
    idea = store.get(conn, int(idea_id)) if idea_id else None
    if idea is None:
        _say(conn, row, "No idea is waiting for settings.")
        return
    try:
        base, _stored_notes = brainstorm.request_from_fields(card.get("fields") or {})
        request, notes = brainstorm.apply(base, routed.fields)
    except brainstorm.SettingsError as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return
    _show_brainstorm(conn, row, idea, request, notes)


def _apply_brainstorm_proposal(conn, row, idea, proposal) -> bool:
    """Update the Start card from an assistant proposal. False leaves the confirm card."""
    if idea is None or idea.status not in _BRAINSTORM_FROM:
        return False
    card = _card_for(conn, _field(row, "chat_id"))
    on_card = bool(
        card and card.get("kind") == "brainstorm" and card.get("idea_id") == idea.id
    )
    try:
        if on_card:
            base, _stored_notes = brainstorm.request_from_fields(card.get("fields") or {})
        else:
            base, _stored_notes = brainstorm.defaults(conn)
        request, notes = brainstorm.apply(base, proposal.fields)
    except brainstorm.SettingsError as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return True
    if idea.status != "brainstorm_configuring":
        try:
            idea = store.transition(
                conn,
                idea.id,
                "brainstorm_configuring",
                expected_revision=idea.revision,
                actor="telegram",
                note=idea.status,
            )
        except (store.IllegalMove, store.StaleRevision) as exc:
            _say(conn, row, str(exc), idea_id=idea.id)
            return True
    _show_brainstorm(conn, row, idea, request, notes)
    return True


def _start_brainstorm(conn, row, idea: store.Idea, _run_fn) -> None:
    if idea.status != "brainstorm_configuring":
        _say(
            conn,
            row,
            f"This idea can't be brainstormed from {idea.status}.",
            idea_id=idea.id,
        )
        return
    card = _card_for(conn, _field(row, "chat_id"))
    fields = {}
    if card and card.get("kind") == "brainstorm":
        fields = card.get("fields") or {}
    try:
        if fields:
            request, _notes = brainstorm.request_from_fields(fields)
        else:
            request, _notes = brainstorm.defaults(conn)
    except brainstorm.SettingsError as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return
    disabled = brainstorm.disabled_provider(request)
    if disabled is None and isinstance(fields, dict):
        disabled = brainstorm.disabled_in_fields(fields)
    if disabled:
        _say(conn, row, _enable_hint(disabled), idea_id=idea.id)
        return
    if not request.models or not request.final:
        text = "No agent can brainstorm unattended."
        if _notes:
            text = text + "\n" + "\n".join(_notes)
        _say(conn, row, text, idea_id=idea.id)
        return
    # The tick handles this row. Running the brainstorm here would hold the
    # scheduler for the whole timeout. The detached job runs it instead.
    from whyline.ideas import worker

    if not worker.enqueue_brainstorm(conn, idea.id, request):
        _say(conn, row, "Already brainstorming.", idea_id=idea.id)
        return
    names = ", ".join(request.models)
    passes = "1 pass" if request.passes == 1 else f"{request.passes} passes"
    chat_id = int(_field(row, "chat_id"))
    begin_progress(
        conn,
        chat_id,
        idea.id,
        (
            f"Brainstorm started with {names}, {passes}. "
            "Usually 15-40 minutes; I'll message you when it's done."
        ),
    )
    _retarget_buttons(conn, idea, "brainstorming")


def _show_brainstorm(conn, row, idea: store.Idea, request, notes) -> None:
    chat_id = int(_field(row, "chat_id"))
    keyboard = _keyboard(buttons_for("brainstorm_configuring"), idea.id, idea.revision)
    text = _settings_text(
        conn,
        idea.id,
        "Start brainstorm will use:",
        brainstorm._format(request),
        brainstorm.TEMPLATE,
        notes,
    )
    card = _card_for(conn, chat_id)
    same = (
        isinstance(card, dict)
        and card.get("kind") == "brainstorm"
        and card.get("idea_id") == idea.id
        and card.get("outbox_id")
    )
    if same:
        outbox_id = int(card["outbox_id"])
        _rewrite_card(conn, outbox_id, text, keyboard)
    else:
        outbox_id = _enqueue(
            conn, chat_id, "message", text, buttons=keyboard, idea_id=idea.id
        )
    _remember_card(
        conn, chat_id, "brainstorm", idea.id, request.as_fields(), outbox_id=outbox_id
    )


def _open_setup(conn, row, idea: store.Idea) -> None:
    from whyline.ideas import setup

    if idea.status not in {"brainstormed", "setup_configuring"}:
        _say(
            conn,
            row,
            f"This idea can't be set up from {idea.status}.",
            idea_id=idea.id,
        )
        return
    repos = setup.list_repos(conn)
    if not repos:
        _say(
            conn,
            row,
            "No repositories configured. Add one with whyline idea repos add <name> <path>.",
            idea_id=idea.id,
        )
        return
    if idea.status != "setup_configuring":
        try:
            idea = store.transition(
                conn,
                idea.id,
                "setup_configuring",
                expected_revision=idea.revision,
                actor="telegram",
                note="plan",
            )
        except store.StaleRevision:
            _say(conn, row, OUT_OF_DATE, idea_id=idea.id)
            return
        except store.IllegalMove as exc:
            _say(conn, row, str(exc), idea_id=idea.id)
            return

    if len(repos) == 1:
        repo_name = next(iter(repos.keys()))
        store.set_repo(conn, idea.id, repo_name)
        _show_setup(conn, row, idea, repo_name)
    else:
        chat_id = int(_field(row, "chat_id"))
        buttons = [(name, f"repo_{name}") for name in sorted(repos.keys())]
        buttons.append(("Cancel", "cancel"))
        keyboard = _keyboard(buttons, idea.id, idea.revision)
        text = "Which repository should this idea be planned into?"
        outbox_id = _enqueue(
            conn, chat_id, "message", text, buttons=keyboard, idea_id=idea.id
        )
        _remember_card(conn, chat_id, "repo_select", idea.id, {}, outbox_id=outbox_id)


def _choose_repo(conn, row, idea: store.Idea, repo_name: str) -> None:
    from whyline.ideas import setup

    repos = setup.list_repos(conn)
    if repo_name not in repos:
        _say(conn, row, f"Unknown repository: {repo_name}", idea_id=idea.id)
        return
    store.set_repo(conn, idea.id, repo_name)
    _show_setup(conn, row, idea, repo_name)


def _show_setup(conn, row, idea: store.Idea, repo_name: str) -> None:
    from whyline.ideas import setup

    repos = setup.list_repos(conn)
    path_str = repos.get(repo_name)
    if not path_str:
        _say(conn, row, f"Unknown repository: {repo_name}", idea_id=idea.id)
        return
    repo_root = Path(path_str)
    try:
        request, notes = setup.defaults(conn, idea.id, repo_name, repo_root)
    except setup.SetupError as exc:
        # No card is shown, so do not leave the idea in setup_configuring.
        current = store.get(conn, idea.id) or idea
        fresh = _move_or_keep(conn, current, "brainstormed", "setup refused")
        _say(conn, row, str(exc), idea_id=idea.id)
        _retarget_buttons(conn, fresh, fresh.status)
        return
    _show_setup_with_request(conn, row, idea, request, notes)


def _show_setup_with_request(
    conn, row, idea: store.Idea, request, notes: tuple[str, ...]
) -> None:
    from whyline.ideas import setup

    chat_id = int(_field(row, "chat_id"))
    keyboard = _keyboard(buttons_for("setup_configuring"), idea.id, idea.revision)
    text = _settings_text(
        conn,
        idea.id,
        "Set up will use:",
        setup.format_setup(request),
        setup.TEMPLATE,
        notes,
    )
    card = _card_for(conn, chat_id)
    same = (
        isinstance(card, dict)
        and card.get("kind") in {"setup", "plan_setup"}
        and card.get("idea_id") == idea.id
        and card.get("outbox_id")
    )
    if same:
        outbox_id = int(card["outbox_id"])
        _rewrite_card(conn, outbox_id, text, keyboard)
    else:
        outbox_id = _enqueue(
            conn, chat_id, "message", text, buttons=keyboard, idea_id=idea.id
        )
    fields = request.as_fields()
    _remember_card(
        conn, chat_id, "plan_setup", idea.id, fields, outbox_id=outbox_id
    )
    _kv_set_txn(conn, f"{_SETTINGS_KEY}:{idea.id}", json.dumps(fields))


def _update_setup_card(conn, row, routed: intent.Intent, card: dict) -> None:
    from whyline.ideas import setup

    idea_id = card.get("idea_id")
    idea = store.get(conn, int(idea_id)) if idea_id else None
    if idea is None:
        _say(conn, row, "No idea is waiting for settings.")
        return
    card_fields = card.get("fields") or {}
    base = setup.request_from_fields(card_fields)
    plain_edits, errors = _plain_fields(routed.fields)
    if errors:
        _say(conn, row, "\n".join(errors), idea_id=idea.id)
        return
    repo_name = plain_edits.get("repo") or base.repo
    repos = setup.list_repos(conn)
    path_str = repos.get(repo_name)
    if not path_str:
        _say(conn, row, f"Unknown repository: {repo_name}", idea_id=idea.id)
        return
    repo_root = Path(path_str)
    try:
        request, notes = setup.apply(base, plain_edits, root=repo_root)
    except setup.SettingsError as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return
    idea = store.bump_revision(
        conn,
        idea.id,
        expected_revision=idea.revision,
        actor="telegram",
        note="settings edit",
    )
    if request.repo != idea.repo:
        store.set_repo(conn, idea.id, request.repo)
    _show_setup_with_request(conn, row, idea, request, notes)


def _apply_setup_proposal(conn, row, idea, proposal) -> bool:
    from whyline.ideas import setup

    if idea is None or idea.status != "setup_configuring":
        return False
    card = _card_for(conn, _field(row, "chat_id"))
    on_card = bool(
        card and card.get("kind") in {"setup", "plan_setup"} and card.get("idea_id") == idea.id
    )
    if not on_card:
        return False
    card_fields = card.get("fields") or {}
    base = setup.request_from_fields(card_fields)
    repo_name = proposal.fields.get("repo") or base.repo
    repos = setup.list_repos(conn)
    path_str = repos.get(repo_name)
    if not path_str:
        _say(conn, row, f"Unknown repository: {repo_name}", idea_id=idea.id)
        return True
    repo_root = Path(path_str)
    try:
        request, notes = setup.apply(base, proposal.fields, root=repo_root)
    except setup.SettingsError as exc:
        _say(conn, row, str(exc), idea_id=idea.id)
        return True
    idea = store.bump_revision(
        conn,
        idea.id,
        expected_revision=idea.revision,
        actor="telegram",
        note="proposal edit",
    )
    if request.repo != idea.repo:
        store.set_repo(conn, idea.id, request.repo)
    _show_setup_with_request(conn, row, idea, request, notes)
    return True


def _stop_score_for_brainstorm(conn, idea: store.Idea) -> store.Idea:
    """Stop a live score so Brainstorm on that card can open.

    A queued score has not moved the idea yet. A running one is put back
    where it came from, which is a status brainstorm is allowed to leave.
    """
    job = _live_job(conn, idea.id, "score")
    if job is None and idea.status != "scoring":
        return idea
    if job is not None:
        _stop_job(conn, job)
    if idea.status != "scoring":
        return store.get(conn, idea.id) or idea
    return _move_or_keep(conn, idea, _score_origin(conn, idea.id), "brainstorm")


def _score_origin(conn, idea_id: int) -> str:
    row = conn.execute(
        """
        SELECT from_status FROM events
        WHERE idea_id = ? AND to_status = 'scoring'
        ORDER BY id DESC
        LIMIT 1
        """,
        (idea_id,),
    ).fetchone()
    origin = row["from_status"] if row is not None else "captured"
    if origin in {"captured", "scored"}:
        return origin
    return "captured"


def _brainstorm_return(conn, idea_id: int, *, allow_brainstormed: bool = False) -> str:
    row = conn.execute(
        """
        SELECT from_status FROM events
        WHERE idea_id = ? AND to_status = 'brainstorm_configuring'
        ORDER BY id DESC
        LIMIT 1
        """,
        (idea_id,),
    ).fetchone()
    origin = row["from_status"] if row is not None else "captured"
    if origin in {"captured", "scored"}:
        return origin
    if allow_brainstormed and origin == "brainstormed":
        return "brainstormed"
    if _latest_analysis(conn, idea_id) is not None:
        return "scored"
    return "captured"


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
    plain = fields if isinstance(fields, dict) else {}
    if kind in {"brainstorm", "brainstorm_settings", "plan_setup"} and plain:
        heading = (
            "Start brainstorm will use:"
            if kind in {"brainstorm", "brainstorm_settings"}
            else f"{card.title} will use:"
        )
        values = "\n".join(f"{key}: {_show(value)}" for key, value in plain.items())
        example = (
            brainstorm.TEMPLATE
            if kind in {"brainstorm", "brainstorm_settings"}
            else _SETTINGS_TEMPLATE
        )
        text = _settings_text(conn, idea_id, heading, values, example)
    else:
        text = f"{card.title}\n{card.body}"
    chat_id = int(_field(row, "chat_id"))
    bound = idea.id if idea is not None else None
    remembered = _card_for(conn, chat_id)
    same = (
        isinstance(remembered, dict)
        and remembered.get("kind") == kind
        and remembered.get("idea_id") == idea_id
        and remembered.get("outbox_id")
    )
    if same:
        outbox_id = int(remembered["outbox_id"])
        _rewrite_card(conn, outbox_id, text, keyboard)
    else:
        outbox_id = _enqueue(
            conn, chat_id, "message", text, buttons=keyboard, idea_id=bound
        )
    _remember_card(conn, chat_id, kind, idea_id, plain or None, outbox_id=outbox_id)


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
    # Taps are answered in the poll. A leftover callback row is history
    # we must not send, and must not retry.
    if row["kind"] == "callback":
        conn.execute("DELETE FROM outbox WHERE id = ?", (row_id,))
        return False
    try:
        message_id = _deliver(token, row, http)
    except telegram.TelegramError as exc:
        _mark_failed(conn, row, moment, str(exc), http=http)
        return False
    conn.execute(
        "UPDATE outbox SET sent_at = ?, tg_message_id = ? WHERE id = ?",
        (moment, message_id, row_id),
    )
    _remember_sent(conn, row_id, message_id)
    return True


def _mark_failed(conn, row, moment: str, reason: str, *, http=None) -> None:
    attempts = int(row["attempts"]) + 1
    _note_delivery_failure(conn, row, attempts, reason, http=http)
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


def _deliver(token: str, row, http) -> int | None:
    kind = row["kind"]
    if kind == "document":
        path = row["document_path"]
        if not path:
            raise telegram.TelegramError("document is missing a path")
        fields: dict = {"chat_id": row["chat_id"]}
        caption = row["text"] or ""
        if caption:
            fields["caption"] = caption[: telegram.CAPTION_LIMIT]
        keyboard = _load_keyboard(row["buttons_json"])
        if keyboard:
            fields["reply_markup"] = {"inline_keyboard": keyboard}
        result = telegram._call(
            "sendDocument",
            token,
            fields,
            {"document": path},
            http=http,
            sleep=_no_sleep,
        )
        return _result_message_id(result)
    text = (row["text"] or "").strip()
    if not text:
        raise telegram.TelegramError("message is empty")
    fields = {"chat_id": row["chat_id"], "text": text[:_MESSAGE_LIMIT]}
    keyboard = _load_keyboard(row["buttons_json"])
    if keyboard:
        fields["reply_markup"] = {"inline_keyboard": keyboard}
    result = telegram._call(
        "sendMessage",
        token,
        fields,
        None,
        http=http,
        sleep=_no_sleep,
    )
    return _result_message_id(result)


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


def _say(
    conn,
    row,
    text: str,
    keyboard=None,
    *,
    idea_id: int | None = None,
    document_path: str | None = None,
) -> int | None:
    chat_id = _field(row, "chat_id")
    if chat_id is None:
        return None
    kind = "document" if document_path else "message"
    return _enqueue(
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
    http=None,
) -> int:
    # Retire first, outside the insert transaction, so a Telegram edit is
    # not held inside BEGIN. A settings rewrite must not come through here:
    # it would blank the card it is trying to change. Every later buttoned
    # message retires the previous one, including the second Word or PDF
    # of one result, so only the newest keeps buttons.
    if buttons and idea_id is not None:
        _retire_older(conn, int(idea_id), http=http)
    if conn.in_transaction:
        return _insert_outbox(
            conn, chat_id, kind, text, buttons, document_path, idea_id
        )
    with store._txn(conn):
        return _insert_outbox(
            conn, chat_id, kind, text, buttons, document_path, idea_id
        )


def _insert_outbox(
    conn,
    chat_id: int,
    kind: str,
    text: str,
    buttons,
    document_path: str | None,
    idea_id: int | None,
) -> int:
    payload = json.dumps(buttons, ensure_ascii=False) if buttons else None
    cursor = conn.execute(
        """
        INSERT INTO outbox (
          chat_id, kind, text, buttons_json, document_path,
          attempts, next_try_at, sent_at, idea_id
        ) VALUES (?, ?, ?, ?, ?, 0, NULL, NULL, ?)
        """,
        (chat_id, kind, text, payload, document_path, idea_id),
    )
    return int(cursor.lastrowid)


def _request_keyboard(request_id: int, code: str) -> list:
    """Confirm and Cancel bound to ``req:<ok|no>:<id>:<code>``, under 64 bytes."""
    cells = []
    for label, action in (("Confirm", "ok"), ("Cancel", "no")):
        data = f"req:{action}:{request_id}:{code}"
        if len(data.encode("utf-8")) > CALLBACK_DATA_LIMIT:
            raise ValueError(
                f"callback_data exceeds {CALLBACK_DATA_LIMIT} bytes: {data!r}"
            )
        cells.append({"text": label, "callback_data": data})
    return [cells]


def _keyboard(buttons, idea_id: int, revision: int, width: int = 3) -> list:
    """At most three buttons on a row. Four or more puts the main one alone first."""
    span = min(int(width) if width else 3, 3)
    cells = [
        {
            "text": label,
            "callback_data": f"{action}:{idea_id}:{revision}",
        }
        for label, action in buttons
    ]
    if len(cells) >= 4:
        rows = [cells[:1]]
        rest = cells[1:]
    else:
        rows = []
        rest = cells
    rows.extend(rest[index:index + span] for index in range(0, len(rest), span))
    return rows


def _echo(conn, row, name: str, idea_id: int | None) -> None:
    text = _ECHO.get(name)
    if not text:
        return
    _say(conn, row, text, idea_id=idea_id)


def begin_progress(conn, chat_id: int, idea_id: int, text: str) -> int:
    """Queue a new status line and point later edits at that row.

    A later action starts its own line, so "Quick score done ↓" is not
    overwritten by the next report.
    """
    outbox_id = _enqueue(
        conn, int(chat_id), "message", text[:_MESSAGE_LIMIT], idea_id=int(idea_id)
    )
    _remember_progress(conn, int(idea_id), int(chat_id), outbox_id, None)
    return outbox_id


def edit_progress(
    conn,
    idea_id: int,
    text: str,
    *,
    chat_id: int | None = None,
    http=None,
) -> None:
    """Change the current status line. A missing line starts one.

    Called from the outbox transaction when a send fails, so this must not
    open its own transaction. A Telegram edit that the server rejects
    (the message is too old) is ignored.
    """
    text = text[:_MESSAGE_LIMIT]
    pointer = _progress_for(conn, int(idea_id))
    if pointer is None:
        if chat_id is None:
            chat_id = _chat_of_idea(conn, idea_id)
        if chat_id is None:
            return
        begin_progress(conn, int(chat_id), int(idea_id), text)
        return
    row = conn.execute(
        "SELECT * FROM outbox WHERE id = ?", (int(pointer["outbox_id"]),)
    ).fetchone()
    if row is None:
        if chat_id is not None:
            begin_progress(conn, int(chat_id), int(idea_id), text)
        return
    _replace_outbox_text(conn, row, text, http=http)


def mark_delivery(conn, outbox_id: int | None, role: str) -> None:
    """Remember why this row was queued, so a later failure can say so."""
    if outbox_id is None:
        return
    data = _map(conn, _DELIVERY_KEY)
    data[str(int(outbox_id))] = role
    _kv_put(conn, _DELIVERY_KEY, json.dumps(data))


def _progress_for(conn, idea_id: int) -> dict | None:
    item = _map(conn, _PROGRESS_KEY).get(str(int(idea_id)))
    if not isinstance(item, dict) or item.get("outbox_id") is None:
        return None
    return item


def _remember_progress(conn, idea_id: int, chat_id: int, outbox_id: int, message_id) -> None:
    data = _map(conn, _PROGRESS_KEY)
    data[str(int(idea_id))] = {
        "chat_id": int(chat_id),
        "outbox_id": int(outbox_id),
        "message_id": message_id,
    }
    _kv_put(conn, _PROGRESS_KEY, json.dumps(data))


def _remember_sent(conn, outbox_id: int, message_id) -> None:
    if message_id is None:
        return
    data = _map(conn, _PROGRESS_KEY)
    changed = False
    for item in data.values():
        if isinstance(item, dict) and item.get("outbox_id") == outbox_id:
            item["message_id"] = message_id
            changed = True
    if changed:
        _kv_set(conn, _PROGRESS_KEY, json.dumps(data))


def _replace_outbox_text(conn, row, text: str, *, http=None) -> None:
    message_id = _tg_message_id(row)
    if row["sent_at"] is not None and message_id is not None:
        token = telegram.token_get()
        if token:
            _ignore_edit(
                lambda: telegram.edit_message_text(
                    token,
                    int(row["chat_id"]),
                    message_id,
                    text,
                    http=http,
                    sleep=_no_sleep,
                )
            )
    conn.execute("UPDATE outbox SET text = ? WHERE id = ?", (text, int(row["id"])))


def refresh_running_card(conn, idea: store.Idea) -> None:
    """Point the current card at this idea's status and revision.

    Quick score and brainstorm rewrite the buttons when the job is queued,
    before the worker enters the running status and increments the
    revision. A Cancel tap during the run would otherwise carry the old
    revision and be rejected as out of date. No card means nothing to do.
    """
    if idea.status not in _STATUS_BUTTONS:
        return
    _retarget_buttons(conn, idea, idea.status)


def _retarget_buttons(conn, idea: store.Idea, status: str, *, http=None) -> None:
    """Point the newest card for this idea at the buttons for ``status``."""
    row = conn.execute(
        """
        SELECT * FROM outbox
        WHERE idea_id = ? AND buttons_json IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (idea.id,),
    ).fetchone()
    if row is None:
        return
    keyboard = _keyboard(buttons_for(status), idea.id, idea.revision)
    _write_buttons(conn, row, keyboard, http=http)


def _write_buttons(conn, row, keyboard, *, http=None) -> None:
    payload = json.dumps(keyboard, ensure_ascii=False) if keyboard else None
    message_id = _tg_message_id(row)
    if row["sent_at"] is not None and message_id is not None:
        token = telegram.token_get()
        if token:
            _ignore_edit(
                lambda: telegram.edit_reply_markup(
                    token,
                    int(row["chat_id"]),
                    message_id,
                    {"inline_keyboard": keyboard or []},
                    http=http,
                    sleep=_no_sleep,
                )
            )
    conn.execute(
        "UPDATE outbox SET buttons_json = ? WHERE id = ?",
        (payload, int(row["id"])),
    )


def _retire_older(conn, idea_id: int, *, keep_id: int | None = None, http=None) -> None:
    """Older cards for this idea lose their buttons and point at the new one."""
    rows = conn.execute(
        """
        SELECT * FROM outbox
        WHERE idea_id = ? AND buttons_json IS NOT NULL
        ORDER BY id
        """,
        (int(idea_id),),
    ).fetchall()
    for row in rows:
        if keep_id is not None and int(row["id"]) == int(keep_id):
            continue
        _blank_card(conn, row, http=http)


def _blank_card(conn, row, *, http=None) -> None:
    message_id = _tg_message_id(row)
    if row["sent_at"] is not None and message_id is not None:
        token = telegram.token_get()
        if token:
            _ignore_edit(
                lambda: telegram.edit_message_text(
                    token,
                    int(row["chat_id"]),
                    message_id,
                    _MOVED,
                    http=http,
                    sleep=_no_sleep,
                )
            )
            _ignore_edit(
                lambda: telegram.edit_reply_markup(
                    token,
                    int(row["chat_id"]),
                    message_id,
                    {"inline_keyboard": []},
                    http=http,
                    sleep=_no_sleep,
                )
            )
    conn.execute(
        "UPDATE outbox SET text = ?, buttons_json = NULL WHERE id = ?",
        (_MOVED, int(row["id"])),
    )


def _rewrite_card(conn, outbox_id: int, text: str, keyboard, *, http=None) -> None:
    row = conn.execute(
        "SELECT * FROM outbox WHERE id = ?", (int(outbox_id),)
    ).fetchone()
    if row is None:
        return
    message_id = _tg_message_id(row)
    if row["sent_at"] is not None and message_id is not None:
        token = telegram.token_get()
        if token:
            _ignore_edit(
                lambda: telegram.edit_message_text(
                    token,
                    int(row["chat_id"]),
                    message_id,
                    text,
                    http=http,
                    sleep=_no_sleep,
                )
            )
            _ignore_edit(
                lambda: telegram.edit_reply_markup(
                    token,
                    int(row["chat_id"]),
                    message_id,
                    {"inline_keyboard": keyboard or []},
                    http=http,
                    sleep=_no_sleep,
                )
            )
    payload = json.dumps(keyboard, ensure_ascii=False) if keyboard else None
    conn.execute(
        "UPDATE outbox SET text = ?, buttons_json = ? WHERE id = ?",
        (text, payload, int(outbox_id)),
    )


def _settings_text(conn, idea_id: int, heading: str, values: str, example: str, notes=()) -> str:
    """Current values, then either the example once or a one-line reminder."""
    parts = [heading, "", values.rstrip()]
    for note in notes:
        if note:
            parts.extend(["", str(note)])
    flag = f"settings_example:{int(idea_id)}"
    if _kv(conn, flag) == "1":
        parts.extend(["", "Reply `key: value` to change a setting"])
    else:
        parts.extend(["", "To change any of these, reply with lines like:", "", example.rstrip()])
        _kv_put(conn, flag, "1")
    return "\n".join(parts)


def _note_delivery_failure(conn, row, attempts: int, reason: str, *, http=None) -> None:
    idea_id = row["idea_id"]
    if idea_id is None:
        return
    role = _map(conn, _DELIVERY_KEY).get(str(int(row["id"])))
    if role == "synthesis":
        if attempts >= MAX_ATTEMPTS:
            path = _saved_at(conn, row)
            text = f"Couldn't send the synthesis; it is saved at {path} on the Mac"
        else:
            text = (
                f"The synthesis is ready but sending it failed: {reason}; I'll retry"
            )
    elif role == "report":
        text = f"Couldn't send the report: {reason}"
    elif role == "excel":
        text = f"Couldn't send the workbook: {reason}"
    else:
        return
    edit_progress(conn, int(idea_id), text, http=http)


def _saved_at(conn, row) -> str:
    idea_id = row["idea_id"]
    if idea_id is not None:
        idea = store.get(conn, int(idea_id))
        if idea is not None and idea.brainstorm_path:
            return idea.brainstorm_path
    if row["document_path"]:
        return str(row["document_path"])
    return "the inbox"


def _live_job(conn, idea_id: int, kind: str):
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
    ).fetchone()
    if found is None:
        return None
    return conn.execute(
        """
        SELECT * FROM jobs
        WHERE idea_id = ? AND kind = ? AND state IN ('queued', 'running')
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(idea_id), kind),
    ).fetchone()


def _stop_job(conn, job) -> None:
    from whyline.ideas import worker

    pid = _field(job, "pid")
    if pid:
        worker._stop(pid)
    conn.execute(
        """
        UPDATE jobs
        SET state = 'cancelled', lease_until = NULL, pid = NULL
        WHERE id = ? AND state IN ('queued', 'running')
        """,
        (int(job["id"]),),
    )


def _move_or_keep(conn, idea: store.Idea, target: str, note: str) -> store.Idea:
    if idea.status == target:
        return idea
    try:
        return store.transition(
            conn,
            idea.id,
            target,
            expected_revision=idea.revision,
            actor="telegram",
            note=note,
        )
    except (store.IllegalMove, store.StaleRevision):
        return store.get(conn, idea.id) or idea


def _ignore_edit(action) -> None:
    try:
        action()
    except telegram.TelegramError:
        return


def _tg_message_id(row) -> int | None:
    if row is None:
        return None
    keys = row.keys() if isinstance(row, sqlite3.Row) else ()
    if isinstance(row, sqlite3.Row) and "tg_message_id" not in keys:
        return None
    try:
        value = row["tg_message_id"]
    except (KeyError, IndexError, TypeError):
        return None
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _result_message_id(result) -> int | None:
    if isinstance(result, dict) and result.get("message_id") is not None:
        try:
            return int(result["message_id"])
        except (TypeError, ValueError):
            return None
    return None


def _chat_of_idea(conn, idea_id) -> int | None:
    idea = store.get(conn, int(idea_id))
    if idea is None:
        return None
    return _chat_from_ref(idea.source_ref)


def _kv_put(conn, key: str, value: str) -> None:
    if conn.in_transaction:
        _kv_set(conn, key, value)
    else:
        _kv_set_txn(conn, key, value)


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
        if not _subscription_enabled(name):
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


def _remember_card(
    conn, chat_id: int, kind: str, idea_id: int, fields=None, *, outbox_id=None
) -> None:
    with store._txn(conn):
        _remember_card_in(
            conn, chat_id, kind, idea_id, fields, outbox_id=outbox_id
        )


def _remember_card_in(
    conn, chat_id: int, kind: str, idea_id: int, fields, *, outbox_id=None
) -> None:
    data = _map(conn, _CARD_KEY)
    item = {
        "kind": kind,
        "idea_id": idea_id,
        "fields": fields or {},
    }
    if outbox_id is not None:
        item["outbox_id"] = int(outbox_id)
    data[str(int(chat_id))] = item
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
