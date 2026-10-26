"""Email intake for ideas: ideas and settings by email (IDEA-21).

Allowed senders live in kv key `email_allow`. Incoming messages are verified
against the user's own `Authentication-Results` authserv-id (`email_authserv`):
DMARC pass, or DKIM pass whose `header.d` aligns with the From domain.
Captures an idea when subject is "idea" (or empty). Body key: value lines
become brainstorm settings. Action confirmations use "yes <code>" bound to
the idea's revision. Documents go back as Word and PDF attachments.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import re
import sqlite3
from email.message import Message
from pathlib import Path

from whyline.agents import mail, mail_send
from whyline.ideas import brainstorm, documents, intent, store

ALLOW_KEY = "email_allow"
AUTHSERV_KEY = "email_authserv"
AUTHSERV_UNSET_NOTE = (
    "email authentication is not set up: choose your mail provider in Inbox"
)
AUTHSERV_HINTS = ("mx.google.com", "icloud.com", "mx.microsoft.com")
_SETTING_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*)$")
_YES_CODE_RE = re.compile(r"\byes\b\s*[:,-]?\s*([a-zA-Z0-9]{6})\b", re.IGNORECASE)
_COMMENT_RE = re.compile(r"\([^)]*\)")
_METHOD_RE = re.compile(r"(\w+)\s*=\s*(\w+)", re.IGNORECASE)
_PROP_RE = re.compile(r"(\w+)\s*\.\s*(\w+)\s*=\s*([^\s;]+)", re.IGNORECASE)


class AllowError(Exception):
    """Raised when an address cannot be allowed."""


def _kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _is_address(text: str) -> bool:
    local, _, domain = text.partition("@")
    return (
        text.count("@") == 1
        and bool(local)
        and "." in domain
        and not any(ch in text for ch in " ,;\t\r\n")
    )


def allowed_senders(conn: sqlite3.Connection) -> list[str]:
    """List allowed email sender addresses."""
    raw = _kv(conn, ALLOW_KEY)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    senders: list[str] = []
    for item in parsed:
        if isinstance(item, str):
            clean = item.strip().lower()
            if clean and clean not in senders:
                senders.append(clean)
    return senders


def _save_allowed(conn: sqlite3.Connection, senders: list[str]) -> None:
    unique: list[str] = []
    for addr in senders:
        clean = addr.strip().lower()
        if clean and clean not in unique:
            unique.append(clean)
    with store._txn(conn):
        _kv_set(conn, ALLOW_KEY, json.dumps(unique))


def allow(conn: sqlite3.Connection, address: str) -> str:
    """Allow an email address to send ideas."""
    addr = address.strip().lower()
    if not _is_address(addr):
        raise AllowError(f"not an email address: {address!r}")
    current = allowed_senders(conn)
    if addr not in current:
        current.append(addr)
        _save_allowed(conn, current)
    return addr


def deny(conn: sqlite3.Connection, address: str) -> None:
    """Stop accepting ideas from an email address."""
    addr = address.strip().lower()
    current = [item for item in allowed_senders(conn) if item != addr]
    _save_allowed(conn, current)


def code_for(idea_id: int, revision: int) -> str:
    """Generate a 6-character code bound to this idea's revision."""
    return hashlib.sha256(f"whyline-email:{idea_id}:{revision}".encode("utf-8")).hexdigest()[:6]


def configured_authserv(conn: sqlite3.Connection) -> str | None:
    """The saved Authentication-Results authserv-id, or None when unset."""
    raw = _kv(conn, AUTHSERV_KEY)
    if not raw:
        return None
    text = str(raw).strip()
    return text or None


def set_authserv(conn: sqlite3.Connection, value: str) -> str:
    """Save the mail provider authserv-id used to trust Authentication-Results."""
    token = (value or "").strip()
    if not token:
        raise ValueError("mail provider is required")
    with store._txn(conn):
        _kv_set(conn, AUTHSERV_KEY, token)
    return token


def _authserv_id(header: str) -> str:
    before = header.strip().split(";", 1)[0]
    tokens = before.split()
    return tokens[0] if tokens else ""


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _from_domain(msg: Message) -> str | None:
    addr = email.utils.parseaddr(msg.get("From", ""))[1].strip()
    if "@" not in addr:
        return None
    domain = addr.rsplit("@", 1)[1].strip().lower().rstrip(".")
    return domain or None


def _domain_aligned(header_d: str, from_domain: str) -> bool:
    dkim_d = _unquote(header_d).strip().lower().lstrip("@").rstrip(".")
    from_d = from_domain.strip().lower().rstrip(".")
    if not dkim_d or not from_d:
        return False
    return from_d == dkim_d or from_d.endswith("." + dkim_d)


def _method_results(header: str) -> list[tuple[str, str, dict[str, str]]]:
    text = _COMMENT_RE.sub(" ", header)
    parts = text.split(";")[1:]
    results: list[tuple[str, str, dict[str, str]]] = []
    for part in parts:
        method_match = _METHOD_RE.search(part)
        if not method_match:
            continue
        method = method_match.group(1).lower()
        result = method_match.group(2).lower()
        props: dict[str, str] = {}
        for prop in _PROP_RE.finditer(part):
            key = f"{prop.group(1).lower()}.{prop.group(2).lower()}"
            props[key] = _unquote(prop.group(3))
        results.append((method, result, props))
    return results


def is_authenticated(msg: Message, authserv: str) -> bool:
    """Trust only the topmost Authentication-Results header from *authserv*.

    Accepts ``dmarc=pass``, or ``dkim=pass`` whose ``header.d`` is the From
    domain or a parent of it. SPF alone does not count.
    """
    wanted = (authserv or "").strip().lower()
    if not wanted:
        return False
    headers = msg.get_all("Authentication-Results") or []
    if isinstance(headers, str):
        headers = [headers]
    chosen = None
    for header in headers:
        if not header:
            continue
        if _authserv_id(str(header)).lower() == wanted:
            chosen = str(header)
            break
    if chosen is None:
        return False
    from_domain = _from_domain(msg)
    for method, result, props in _method_results(chosen):
        if method == "dmarc" and result == "pass":
            return True
        if method == "dkim" and result == "pass" and from_domain:
            header_d = props.get("header.d", "")
            if header_d and _domain_aligned(header_d, from_domain):
                return True
    return False


def extract_body(msg: Message) -> str:
    """Extract plain text body from an email Message."""
    if msg.is_multipart():
        body_parts: list[str] = []
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                if isinstance(payload, bytes):
                    body_parts.append(payload.decode(charset, errors="replace"))
                elif isinstance(payload, str):
                    body_parts.append(payload)
        if body_parts:
            return "\n".join(body_parts).strip()
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace").strip()
    if isinstance(payload, str):
        return payload.strip()
    raw = msg.get_payload()
    if isinstance(raw, str):
        return raw.strip()
    return ""


def extract_settings(body: str) -> tuple[dict, str]:
    """Extract key: value lines matching IDEA-9 keys, returning (fields, remaining_text)."""
    settings_fields: dict = {}
    idea_lines: list[str] = []
    for line in body.splitlines():
        match = _SETTING_LINE.match(line.strip())
        if match:
            key = match.group(1).lower()
            val = match.group(2).strip()
            if key in intent.SETTING_KEYS:
                field_val = intent._field(key, val)
                if field_val is not None:
                    settings_fields[key] = field_val
                continue
        idea_lines.append(line)
    return settings_fields, "\n".join(idea_lines).strip()


def _record_handled(conn: sqlite3.Connection, text: str = "") -> None:
    with store._txn(conn):
        conn.execute(
            """
            INSERT INTO inbound (at, kind, text, handled)
            VALUES (?, 'email', ?, 1)
            """,
            (store._now(), text),
        )


def _forward_to_telegram(conn: sqlite3.Connection, idea: store.Idea) -> None:
    from whyline.ideas import bot, telegram_in

    allowed = telegram_in.allowed_chats(conn)
    if not allowed:
        return
    for chat_id in allowed:
        line = bot._normalised_first_line(idea.original_text)
        keyboard = bot._keyboard(bot.buttons_for("captured"), idea.id, idea.revision)
        with store._txn(conn):
            if _kv(conn, f"capture_card:{idea.id}:{chat_id}"):
                continue
            outbox_id = bot._insert_outbox(
                conn, chat_id, "message", line, keyboard, None, idea.id
            )
            _kv_set(conn, f"capture_card:{idea.id}:{chat_id}", "1")
            bot._remember_card_in(
                conn, chat_id, "capture", idea.id, None, outbox_id=outbox_id
            )


def handle(
    conn: sqlite3.Connection,
    raw_or_msg,
    *,
    mail_fn=None,
    run_fn=None,
) -> store.Idea | None:
    """Ingest one incoming email message.

    Accepts raw RFC 822 string, bytes, Path, Message, or dict.
    Verifies allowed sender and the user's Authentication-Results authserv.
    Captures idea on subject "idea" or no subject.
    Executes confirmed action on reply "yes <code>".
    """
    msg = mail.read_message(raw_or_msg)
    sender = email.utils.parseaddr(msg.get("From", ""))[1].strip().lower()
    subject = str(msg.get("Subject", "")).strip()
    msg_id = str(msg.get("Message-ID", "")).strip() or None
    body = extract_body(msg)

    # 1. Verification of sender and authentication
    authserv = configured_authserv(conn)
    if not authserv:
        _record_handled(conn, AUTHSERV_UNSET_NOTE)
        return None
    allowed = set(allowed_senders(conn))
    if sender not in allowed or not is_authenticated(msg, authserv):
        _record_handled(conn, body)
        return None

    # 2. Check for confirmation reply: "yes <code>"
    yes_match = _YES_CODE_RE.search(body)
    if yes_match:
        code = yes_match.group(1).lower()
        code_entry = _kv(conn, f"email_code:{code}")
        if not code_entry:
            # Wrong code changes nothing
            return None
        try:
            code_data = json.loads(code_entry)
        except json.JSONDecodeError:
            return None
        idea_id = code_data.get("idea_id")
        expected_revision = code_data.get("revision")
        if idea_id is None or expected_revision is None:
            return None

        # Cross-sender confirmation rejection: only the originating authenticated sender may confirm
        originating_sender = code_data.get("sender") or _kv(conn, f"email_sender:{idea_id}")
        if originating_sender and sender != originating_sender.strip().lower():
            return None

        idea = store.get(conn, int(idea_id))
        if idea is None or idea.revision != expected_revision:
            # Stale code changes nothing
            return None

        # Current code matches: start the brainstorm
        raw_settings = _kv(conn, f"telegram_settings:{idea.id}")
        notes: tuple[str, ...] = ()
        fields = None
        if raw_settings:
            try:
                parsed = json.loads(raw_settings)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                fields = parsed
                try:
                    request, notes = brainstorm.request_from_fields(fields)
                except brainstorm.SettingsError:
                    request, notes = brainstorm.defaults(conn)
            else:
                request, notes = brainstorm.defaults(conn)
        else:
            request, notes = brainstorm.defaults(conn)
        disabled = brainstorm.disabled_provider(request)
        if disabled is None and isinstance(fields, dict):
            disabled = brainstorm.disabled_in_fields(fields)
        if disabled:
            raise brainstorm.BrainstormError(
                f"Enable {disabled} in Settings or choose another provider."
            )
        if not request.models or not request.final:
            hint = next(
                (
                    note.split(": ", 1)[-1]
                    for note in notes
                    if " in Settings or choose another provider." in note
                ),
                "No agent can brainstorm unattended.",
            )
            raise brainstorm.BrainstormError(hint)

        dest = brainstorm.run(conn, idea.id, request, run_fn=run_fn)
        fresh = store.get(conn, idea.id)
        if fresh is None:
            fresh = idea

        exported = documents.export(dest, formats="both")
        attachments = [
            p
            for p in (exported.docx, exported.pdf)
            if p is not None and p.is_file()
        ]
        if not attachments and dest.is_file():
            attachments = [dest]

        reply_sender = mail_fn or mail_send.send
        reply_subject = f"Re: {subject}" if subject else f"Brainstorm: {fresh.title}"
        reply_body = (
            f"Brainstorm completed for: {fresh.title}\n\n"
            "Documents are attached."
        )
        reply_sender([sender], reply_subject, reply_body, attachments)
        return fresh

    # 3. Capture idea if subject is "idea" or empty
    subj_norm = subject.lower().strip()
    if subj_norm not in ("", "idea"):
        _record_handled(conn, body)
        return None

    # Deduplicate Message-ID
    if msg_id:
        existing = conn.execute(
            "SELECT * FROM ideas WHERE source = 'email' AND source_ref = ?",
            (msg_id,),
        ).fetchone()
        if existing is not None:
            # Repeated Message-ID is ignored
            return None

    idea = store.add(conn, body, source="email", source_ref=msg_id)
    settings_fields, _ = extract_settings(body)
    base, _notes = brainstorm.defaults(conn)
    if settings_fields:
        request, _ = brainstorm.apply(base, settings_fields)
    else:
        request = base
    _kv_set(conn, f"telegram_settings:{idea.id}", json.dumps(request.as_fields()))

    # Generate six-character code bound to the idea's revision
    code = code_for(idea.id, idea.revision)
    _kv_set(
        conn,
        f"email_code:{code}",
        json.dumps({
            "idea_id": idea.id,
            "revision": idea.revision,
            "action": "start_brainstorm",
            "sender": sender,
        }),
    )
    _kv_set(conn, f"email_rev_code:{idea.id}:{idea.revision}", code)
    _kv_set(conn, f"email_sender:{idea.id}", sender)

    # Send confirmation email
    reply_sender = mail_fn or mail_send.send
    reply_subject = f"Re: {subject}" if subject else f"Idea: {idea.title}"
    reply_body = (
        f"Idea captured: {idea.title}\n\n"
        "Start brainstorm will use:\n"
        f"{brainstorm._format(request)}\n\n"
        f"Reply 'yes {code}' to start the brainstorm."
    )
    reply_sender([sender], reply_subject, reply_body, [])

    # Post to Telegram if allowed chats exist
    _forward_to_telegram(conn, idea)
    return idea


ingest = handle
handle_message = handle


def handle_file(
    conn: sqlite3.Connection,
    path: Path | str,
    *,
    mail_fn=None,
    run_fn=None,
) -> store.Idea | None:
    """Handle an email from a file path."""
    return handle(conn, Path(path), mail_fn=mail_fn, run_fn=run_fn)
