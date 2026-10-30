"""Read job-alert emails into postings (JOB-16). No AI runs here.

A Mail rule hands one saved message to `handle`. It is accepted only from a
sender the user switched on in ``~/.whyline/jobs/alerts.toml`` whose
``Authentication-Results`` pass the ASST-1 rules (``email_in.is_authenticated``
against the user's own authserv-id). The job cards in its HTML become
`Posting`s in ``~/.whyline/jobs/inbox/``, recorded in the JOB-10 seen store;
the next ``jobs-fetch`` takes them and empties the inbox.
"""
from __future__ import annotations

import dataclasses
import email.utils
import hashlib
import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from . import paths, seen
from .fetch import Posting

SETTINGS_FILE = "alerts.toml"
INBOX_DIR = "inbox"
MAX_MESSAGE_BYTES = 5 * 1024 * 1024
MAX_CARDS = 100
MAX_FIELD = 200
UNKNOWN_COMPANY = "(unknown)"

# All off until the user turns them on.
DEFAULT_SENDERS = (
    "jobalerts-noreply@linkedin.com",
    "alert@indeed.com",
    "noreply@glassdoor.com",
)

AUTHSERV_UNSET = "email authentication is not set up: choose your mail provider in Inbox"


class AlertError(Exception):
    """Raised when alert settings cannot be read or saved."""


# --- settings (alerts.toml) -------------------------------------------------


def settings_path() -> Path:
    return paths.configured_home() / SETTINGS_FILE


def _read_settings() -> dict:
    target = settings_path()
    if target.is_symlink() or not target.is_file():
        return {}
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_private(folder: Path, name: str, text: str) -> Path:
    target = folder / name
    if target.is_symlink():
        raise AlertError(f"Refusing to overwrite symlink: {target}")
    fd, raw_tmp = tempfile.mkstemp(dir=folder, prefix=f".{name}.", suffix=".tmp")
    tmp_path = Path(raw_tmp)
    try:
        if os.name != "nt":
            os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def _save_settings(senders: dict[str, bool], last_count: int, last_at: str) -> None:
    lines = [
        "# Job-alert senders. Only senders set to true are read, and only when",
        "# the message passes email authentication.",
        f"last_count = {int(last_count)}",
        f"last_at = {json.dumps(last_at)}",
        "",
        "[senders]",
    ]
    lines.extend(f"{json.dumps(addr)} = {'true' if on else 'false'}" for addr, on in senders.items())
    try:
        _write_private(paths.home(), SETTINGS_FILE, "\n".join(lines) + "\n")
    except OSError as error:
        raise AlertError(f"Could not save {SETTINGS_FILE}: {error}") from error


def senders() -> dict[str, bool]:
    """Every known sender with its switch; the defaults are off."""
    raw = _read_settings().get("senders")
    saved = raw if isinstance(raw, dict) else {}
    out = {addr: False for addr in DEFAULT_SENDERS}
    for addr, on in saved.items():
        if isinstance(addr, str) and isinstance(on, bool):
            out[addr.strip().lower()] = on
    return out


def enabled_senders() -> list[str]:
    return [addr for addr, on in senders().items() if on]


def set_sender(address: str, enabled: bool) -> dict[str, bool]:
    """Turn one alert sender on or off (the CLI and the console both save here)."""
    addr = (address or "").strip().lower()
    local, _, domain = addr.partition("@")
    if addr.count("@") != 1 or not local or "." not in domain or any(c in addr for c in " ,;\t\r\n"):
        raise AlertError(f"not an email address: {address!r}")
    current = senders()
    current[addr] = bool(enabled)
    count, at = _last_fields()
    _save_settings(current, count, at)
    return current


def _last_fields() -> tuple[int, str]:
    data = _read_settings()
    count = data.get("last_count")
    at = data.get("last_at")
    return (count if isinstance(count, int) and not isinstance(count, bool) else 0,
            at if isinstance(at, str) else "")


def last_read() -> tuple[int, str] | None:
    """(cards read, when) for the last accepted alert, or None if none yet."""
    count, at = _last_fields()
    return (count, at) if at else None


def format_last_read() -> str:
    last = last_read()
    if last is None:
        return "No alert read yet."
    noun = "card" if last[0] == 1 else "cards"
    return f"Last alert read: {last[0]} {noun} ({last[1]})."


# --- parsing the HTML --------------------------------------------------------

_STOP_TITLES = frozenset({
    "view job", "view jobs", "see job", "see jobs", "apply", "apply now", "easy apply",
    "view all jobs", "see all jobs", "unsubscribe", "view more jobs", "view details",
    "view in browser", "manage alerts", "edit alert", "job alert",
})
_TITLE_WORDS = re.compile(
    r"\b(engineer|developer|manager|designer|analyst|scientist|director|lead|architect|"
    r"specialist|consultant|administrator|coordinator|officer|recruiter|intern|"
    r"programmer|researcher|technician|writer|editor|owner|head|vp|devops|sre|"
    r"product|data|software|marketing|sales|support|operations)\b",
    re.IGNORECASE,
)
_BLOCK_TAGS = frozenset({
    "p", "div", "br", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "td", "th", "table", "section", "span",
})
_SKIP_TAGS = frozenset({"script", "style", "head"})


@dataclass(frozen=True)
class _Rule:
    link: re.Pattern[str]
    keep_params: tuple[str, ...] = ()


_RULES: dict[str, _Rule] = {
    "jobalerts-noreply@linkedin.com": _Rule(
        re.compile(r"^https?://([a-z0-9-]+\.)*linkedin\.com/(comm/)?jobs/view/\d+", re.I)
    ),
    "alert@indeed.com": _Rule(
        re.compile(r"^https?://([a-z0-9-]+\.)*indeed\.com/(m/)?(rc/clk|viewjob|pagead/clk)", re.I),
        ("jk", "vjk"),
    ),
    "noreply@glassdoor.com": _Rule(
        re.compile(
            r"^https?://([a-z0-9-]+\.)*glassdoor\.[a-z.]+/(job-listing|partner/jobListing)", re.I
        ),
        ("jl",),
    ),
}


class _Tokens(HTMLParser):
    """Flatten HTML into ordered ("link", href, text) and ("text", "", text) items."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str, str]] = []
        self._text: list[str] = []
        self._href: str | None = None
        self._link: list[str] = []
        self._skip = 0

    def _flush_text(self) -> None:
        text = " ".join("".join(self._text).split())
        self._text = []
        if text:
            self.items.append(("text", "", text))

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "a":
            self._flush_text()
            self._href = dict(attrs).get("href") or ""
            self._link = []
        elif tag in _BLOCK_TAGS:
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._href is not None:
            text = " ".join("".join(self._link).split())
            self.items.append(("link", self._href, text))
            self._href = None
        elif tag in _BLOCK_TAGS:
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        (self._link if self._href is not None else self._text).append(data)

    def close(self) -> None:
        super().close()
        self._flush_text()


def _canonical(href: str, keep: tuple[str, ...]) -> str:
    parts = urlsplit(href.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    query = [(k, v) for k, v in parse_qsl(parts.query) if k in keep]
    tail = "?" + urlencode(query) if query else ""
    return f"{parts.scheme}://{parts.netloc.lower()}{parts.path}{tail}"


def _field(value: str) -> str:
    return " ".join(value.split())[:MAX_FIELD]


def _looks_like_title(text: str) -> bool:
    words = text.split()
    if not 2 <= len(words) <= 10 or len(text) > 100:
        return False
    return text.lower() not in _STOP_TITLES and bool(_TITLE_WORDS.search(text))


def _details(lines: list[str]) -> tuple[str, str]:
    """Company and location from the text lines after a title."""
    if len(lines) == 1:
        for sep in (" · ", " • "):
            if sep in lines[0]:
                company, _, location = lines[0].partition(sep)
                return _field(company), _field(location)
    company = _field(lines[0]) if lines else ""
    location = _field(lines[1]) if len(lines) > 1 else ""
    return company, location


def parse_cards(html: str, sender: str) -> list[tuple[str, str, str, str]]:
    """(title, company, location, link) cards: the sender's own parser, else the fallback."""
    parser = _Tokens()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed HTML must not stop the intake
        pass
    items = parser.items
    rule = _RULES.get(sender)
    cards = _cards(items, rule) if rule else []
    return cards or _cards(items, None)


def _cards(items: list[tuple[str, str, str]], rule: _Rule | None) -> list[tuple[str, str, str, str]]:
    keep = rule.keep_params if rule else ()
    marks: list[tuple[int, str, str]] = []  # (index, title, link)
    for index, (kind, href, text) in enumerate(items):
        if kind != "link":
            continue
        title = _field(text)
        if rule is not None:
            ok = rule.link.match(href.strip()) is not None and bool(title) and title.lower() not in _STOP_TITLES
        else:
            ok = _looks_like_title(title)
        link = _canonical(href, keep) if ok else ""
        if link:
            marks.append((index, title, link))
    cards: list[tuple[str, str, str, str]] = []
    done: set[str] = set()
    for n, (index, title, link) in enumerate(marks):
        if link in done:
            continue
        done.add(link)
        end = marks[n + 1][0] if n + 1 < len(marks) else len(items)
        lines = [text for kind, _h, text in items[index + 1:end] if kind == "text"][:2]
        company, location = _details(lines)
        cards.append((title, company, location, link))
        if len(cards) >= MAX_CARDS:
            break
    return cards


def _html_of(msg) -> str:
    parts: list[str] = []
    for part in msg.walk():
        if part.get_content_type() != "text/html":
            continue
        if "attachment" in str(part.get("Content-Disposition", "")).lower():
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    return "\n".join(parts)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _posting(sender: str, card: tuple[str, str, str, str]) -> Posting:
    title, company, location, link = card
    return Posting(
        uid=f"alert:{sender}:{_hash(link)}",
        company=company or UNKNOWN_COMPANY,
        title=title,
        location=location,
        remote=True if "remote" in location.lower() else None,
        url=link,
        text=f"Found in a job-alert email from {sender}. The full description is at the link.",
    )


# --- the inbox ---------------------------------------------------------------


def inbox_dir() -> Path:
    return paths.configured_home() / INBOX_DIR


def _ensure_inbox() -> Path:
    folder = paths.home() / INBOX_DIR
    if folder.is_symlink():
        raise OSError(f"refusing symlinked inbox folder: {folder}")
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def _file_for(uid: str) -> str:
    return f"{_hash(uid)}.json"


def _store(postings: list[Posting]) -> None:
    folder = _ensure_inbox()
    for posting in postings:
        _write_private(folder, _file_for(posting.uid), json.dumps(dataclasses.asdict(posting)) + "\n")


def pending() -> list[Posting]:
    """Postings waiting in the inbox for the next fetch (nothing is removed)."""
    folder = inbox_dir()
    if folder.is_symlink() or not folder.is_dir():
        return []
    fields = {f.name for f in dataclasses.fields(Posting)}
    out: list[Posting] = []
    for path in sorted(folder.glob("*.json")):
        if path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(Posting(**{k: v for k, v in data.items() if k in fields}))
        except (OSError, ValueError, TypeError):
            continue
    return out


def discard(uids: list[str] | set[str]) -> None:
    """Remove the inbox files of postings the fetch has taken."""
    folder = inbox_dir()
    for uid in uids:
        (folder / _file_for(uid)).unlink(missing_ok=True)


# --- handling one message ----------------------------------------------------


@dataclass(frozen=True)
class Result:
    sender: str = ""
    cards: int = 0
    new: int = 0
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return not self.reason

    def summary(self) -> str:
        if not self.accepted:
            return f"Ignored: {self.reason}."
        return f"Read {self.cards} job cards from {self.sender}; {self.new} new."


def _configured_authserv() -> str | None:
    from whyline.ideas import email_in, store

    conn = store.connect()
    try:
        return email_in.configured_authserv(conn)
    finally:
        conn.close()


def handle(
    eml_path: str | Path,
    *,
    authserv: str | None = None,
    seen_path: Path | None = None,
) -> Result:
    """Read one job-alert message; returns what was done (nothing for a stranger)."""
    from whyline.agents import mail
    from whyline.ideas import email_in

    path = Path(eml_path)
    if path.stat().st_size > MAX_MESSAGE_BYTES:
        return Result(reason="message is too large")
    msg = mail.read_message(path)
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1].strip().lower()
    if not sender or not senders().get(sender, False):
        return Result(sender=sender, reason="sender is not switched on")
    server = authserv if authserv is not None else _configured_authserv()
    if not server:
        return Result(sender=sender, reason=AUTHSERV_UNSET)
    if not email_in.is_authenticated(msg, server):
        return Result(sender=sender, reason="message failed email authentication")

    postings = [_posting(sender, card) for card in parse_cards(_html_of(msg), sender)]
    # Write to the inbox before recording seen, so a failed write leaves nothing
    # marked seen and the same message can be retried.
    waiting = {p.uid for p in pending()}
    added = [p.uid for p in postings if p.uid not in waiting]
    try:
        _store(postings)
        fresh = set(seen.new_only(postings, path=seen_path))
    except BaseException:
        discard(added)
        raise
    # Cards already seen (and already taken by a fetch) must not come back.
    discard([uid for uid in added if uid not in fresh])
    new = [p for p in postings if p.uid in fresh]
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save_settings(senders(), len(postings), when)
    return Result(sender=sender, cards=len(postings), new=len(new))
