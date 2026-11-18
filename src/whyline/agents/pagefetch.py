"""A careful page fetch for watch agents: public addresses only, no cookies, never raises."""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import ipaddress
import json
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from whyline import __version__
from whyline.ideas.guard import clean
from whyline.tools import knowledge

MAX_REDIRECTS = 5
MAX_TEXT = 200_000
CACHE_SECONDS = 5 * 60
MAX_RETRY = timedelta(hours=24)
BLOCK_STATUSES = {401: "login", 403: "block", 407: "login", 429: "slow", 503: "slow"}
BLOCK_PHRASES = ("captcha", "are you a robot", "unusual traffic", "verify you are human",
                 "enable javascript", "sign in to continue")
BLOCK_PAGE_LIMIT = 3000
REASONS = {
    "login": "the site asked for a login",
    "block": "the site is blocking automated checks",
    "slow": "the site asked to slow down",
}
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml")
PRIVATE = "that address is on a private network"


@dataclass(frozen=True)
class Page:
    url: str
    state: str  # ok, blocked, failed
    text: str = ""
    reason: str = ""
    retry_at: datetime | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _default_opener(url: str, headers: dict, timeout: float):
    """One request, no redirects, no cookies. An HTTP error status is returned as a response."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPHandler, urllib.request.HTTPSHandler, _NoRedirect,
    )
    try:
        return opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)
    except urllib.error.HTTPError as err:
        return err


def _default_resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _private(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified)


def _check_address(url: str, resolve: Callable) -> str:
    """Return a failure reason, or '' when every address the host resolves to is public."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        return "only http and https addresses can be checked"
    host = parts.hostname
    if not host:
        return "that address has no site name"
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = list(resolve(host))
        except Exception:
            return "could not find that site"
    if not addresses:
        return "could not find that site"
    try:
        if any(_private(a) for a in addresses):
            return PRIVATE
    except ValueError:
        return PRIVATE
    return ""


def _header(headers, name: str) -> str:
    if headers is None:
        return ""
    try:
        value = headers.get(name)
        if value is None and hasattr(headers, "items"):
            value = next((v for k, v in headers.items() if k.lower() == name.lower()), None)
    except Exception:
        return ""
    return str(value or "").strip()


def _retry_at(headers, now: datetime) -> datetime | None:
    value = _header(headers, "Retry-After")
    if not value:
        return None
    try:
        try:
            seconds = int(value)
            when = now + timedelta(seconds=max(0, min(seconds, int(MAX_RETRY.total_seconds()))))
        except ValueError:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None and now.tzinfo is not None:
                when = when.replace(tzinfo=now.tzinfo)
            elif when.tzinfo is not None and now.tzinfo is None:
                when = when.astimezone(timezone.utc).replace(tzinfo=None)
        return max(now, min(when, now + MAX_RETRY))
    except (TypeError, ValueError, OverflowError):
        return None


def _status(response) -> int:
    for attr in ("status", "code"):
        value = getattr(response, attr, None)
        if isinstance(value, int):
            return value
    getter = getattr(response, "getcode", None)
    return int(getter()) if getter else 200


def _close(response) -> None:
    close = getattr(response, "close", None)
    if close:
        try:
            close()
        except Exception:
            pass


def _cache_file(cache_dir: Path, url: str) -> Path:
    return cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:32]}.json"


def _load_cache(path: Path, now: datetime) -> Page | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(data["fetched_at"])
        raw = data["page"]
        retry = datetime.fromisoformat(raw["retry_at"]) if raw.get("retry_at") else None
        page = Page(raw["url"], raw["state"], raw.get("text", ""), raw.get("reason", ""), retry)
        fresh = now - fetched < timedelta(seconds=CACHE_SECONDS)
        waiting = retry is not None and now < retry
        return page if (fresh or waiting) and fetched <= now else None
    except Exception:
        return None


def _save_cache(path: Path, page: Page, now: datetime) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = {
            "fetched_at": now.isoformat(),
            "page": {
                "url": page.url, "state": page.state, "text": page.text, "reason": page.reason,
                "retry_at": page.retry_at.isoformat() if page.retry_at else None,
            },
        }
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle)
        os.replace(tmp, path)
    except Exception:
        pass


def _get(url: str, now: datetime, opener: Callable, resolve: Callable) -> Page:
    headers = {
        "User-Agent": f"whyline-watch/{__version__}",
        "Accept": "text/html, application/json, text/plain",
    }
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        problem = _check_address(current, resolve)
        if problem:
            return Page(url, "failed", reason=problem)
        response = opener(current, headers, knowledge.PAGE_SECONDS)
        status = _status(response)
        if status in (301, 302, 303, 307, 308):
            location = _header(getattr(response, "headers", None), "Location")
            _close(response)
            if not location:
                return Page(url, "failed", reason="the site redirected without saying where")
            current = urljoin(current, location)
            continue
        break
    else:
        return Page(url, "failed", reason="the site redirected too many times")

    if status in BLOCK_STATUSES:
        kind = BLOCK_STATUSES[status]
        retry = _retry_at(getattr(response, "headers", None), now) if status in (429, 503) else None
        _close(response)
        return Page(url, "blocked", reason=REASONS[kind], retry_at=retry)
    if status >= 400:
        _close(response)
        return Page(url, "failed", reason=f"the site answered {status}")

    body, ctype, charset = knowledge._download(current, lambda _u, _t: response, knowledge.PAGE_SECONDS)
    if not ctype.startswith(TEXT_TYPES):
        return Page(url, "failed", reason="that page is not text")
    try:
        raw = body.decode(charset, errors="replace")
    except LookupError:
        raw = body.decode("utf-8", errors="replace")
    if "html" in ctype:
        raw = knowledge.html_to_text(raw)
    text, _flagged = clean(raw)
    text = text[:MAX_TEXT]
    if len(text) < BLOCK_PAGE_LIMIT:
        lowered = text.lower()
        for phrase in BLOCK_PHRASES:
            if phrase in lowered:
                kind = "login" if phrase == "sign in to continue" else "block"
                return Page(url, "blocked", reason=REASONS[kind])
    return Page(url, "ok", text=text)


_UNCACHED: contextvars.ContextVar[list | None] = contextvars.ContextVar("uncached", default=None)


@contextlib.contextmanager
def uncached():
    """Fetch fresh and write no cache inside this block. Yields the pages fetched."""
    seen: list[Page] = []
    token = _UNCACHED.set(seen)
    try:
        yield seen
    finally:
        _UNCACHED.reset(token)


def fetch(url: str, *, now: datetime, opener: Callable | None = None,
          resolve: Callable | None = None, cache_dir: Path | None = None) -> Page:
    """Fetch one page and say what happened. Never raises."""
    try:
        seen = _UNCACHED.get()
        if seen is not None:
            page = _get(url, now, opener or _default_opener, resolve or _default_resolve)
            seen.append(page)
            return page
        directory = cache_dir if cache_dir is not None else Path.home() / ".whyline" / "agents" / "pages"
        path = _cache_file(directory, url)
        cached = _load_cache(path, now)
        if cached is not None:
            return cached
        page = _get(url, now, opener or _default_opener, resolve or _default_resolve)
        _save_cache(path, page, now)
        return page
    except Exception as err:  # the caller must always get a Page
        page = Page(url, "failed", reason=str(err) or err.__class__.__name__)
        seen = _UNCACHED.get()
        if seen is not None:
            seen.append(page)
        return page
