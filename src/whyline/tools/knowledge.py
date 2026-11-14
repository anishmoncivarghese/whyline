"""Knowledge packs: named lists of files, folders and web pages an agent may read.

A pack is ``~/.whyline/knowledge/<name>.toml``. ``resolve`` turns pack items into
absolute paths and URLs; ``fetch_pages`` saves web pages as plain text."""
from __future__ import annotations

import hashlib
import json
import re
import time
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from whyline.tools import users

PAGE_LIMIT = 2 * 1024 * 1024
PAGE_SECONDS = 30
PACK_PREFIX = "pack:"

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class Pack:
    name: str
    description: str = ""
    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class Item:
    value: str  # absolute path, or an http(s) URL
    is_url: bool = False


@dataclass(frozen=True)
class Fetched:
    url: str
    path: Path | None = None
    error: str = ""  # why the page was not saved; empty when it was

    @property
    def ok(self) -> bool:
        return not self.error


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name))


def _dir() -> Path:
    return Path.home() / ".whyline" / "knowledge"


def _is_url(text: str) -> bool:
    return text.lower().startswith(("http://", "https://"))


def _read(path: Path) -> Pack | None:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    items = raw.get("items", [])
    if not isinstance(items, list):
        items = []
    return Pack(
        name=str(raw.get("name") or path.stem),
        description=str(raw.get("description", "")),
        items=tuple(str(i) for i in items),
    )


def list_packs() -> list[Pack]:
    folder = _dir()
    if not folder.is_dir():
        return []
    found = [p for f in sorted(folder.glob("*.toml")) if (p := _read(f))]
    return sorted(found, key=lambda p: p.name)


def get_pack(name: str) -> Pack:
    if not valid_name(name):
        raise KeyError(name)
    pack = _read(_dir() / f"{name}.toml")
    if pack is None:
        raise KeyError(name)
    return pack


def save_pack(pack: Pack) -> None:
    if not valid_name(pack.name):
        raise ValueError(f"Pack name {pack.name!r} must be lowercase letters, digits, - or _.")
    for item in pack.items:
        if not item.strip():
            raise ValueError("A pack item cannot be empty.")
        if item.startswith(PACK_PREFIX) and item[len(PACK_PREFIX):] == pack.name:
            raise ValueError("A pack cannot include itself.")
        if "://" in item and not _is_url(item):
            raise ValueError(f"Only http and https addresses are allowed: {item}")
    text = "\n".join([
        f"name = {json.dumps(pack.name)}",
        f"description = {json.dumps(pack.description)}",
        f"items = {json.dumps(list(pack.items))}",
        "",
    ])
    _dir().mkdir(parents=True, exist_ok=True)
    (_dir() / f"{pack.name}.toml").write_text(text, encoding="utf-8")


def remove_pack(name: str) -> None:
    """Delete a pack. Refused, naming the users, while anything uses it."""
    get_pack(name)
    in_use = users.of("pack", name)
    if in_use:
        raise ValueError(f"{name} is used by {', '.join(in_use)}")
    (_dir() / f"{name}.toml").unlink()


def resolve(items, base: Path, _seen: tuple[str, ...] = ()) -> list[Item]:
    """Expand ``pack:<name>``, ``~`` and relative paths; keep URLs. Repeats are dropped."""
    out: list[Item] = []
    for raw in items:
        text = str(raw).strip()
        if not text:
            continue
        if text.startswith(PACK_PREFIX):
            name = text[len(PACK_PREFIX):].strip()
            if name in _seen:
                raise ValueError(f"Pack {name} includes itself.")
            try:
                pack = get_pack(name)
            except KeyError:
                raise ValueError(f"No knowledge pack named {name}.") from None
            out.extend(resolve(pack.items, base, (*_seen, name)))
        elif _is_url(text):
            out.append(Item(text, True))
        else:
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = Path(base) / path
            out.append(Item(str(path)))
    seen: set[Item] = set()
    return [i for i in out if not (i in seen or seen.add(i))]


class _Text(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "head"}
    _BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
              "section", "article", "pre", "table", "ul", "ol", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    body = "\n".join(line for line in lines if line)
    title = " ".join(parser.title.split())
    return f"{title}\n\n{body}" if title and not body.startswith(title) else body


def _default_open(url: str, timeout: float):
    return urllib.request.build_opener(
        urllib.request.HTTPHandler, urllib.request.HTTPSHandler, urllib.request.HTTPRedirectHandler,
    ).open(url, timeout=timeout)


def _filename(url: str) -> str:
    parts = urlparse(url)
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", f"{parts.netloc}{parts.path}").strip("-")[:60] or "page"
    return f"{stem}-{hashlib.sha256(url.encode()).hexdigest()[:8]}.txt"


def _download(url: str, opener: Callable, seconds: float) -> tuple[bytes, str, str]:
    deadline = time.monotonic() + seconds
    response = opener(url, seconds)
    try:
        headers = getattr(response, "headers", None)
        ctype = (headers.get_content_type() if hasattr(headers, "get_content_type")
                 else str((headers or {}).get("Content-Type", "text/html")).split(";")[0].strip().lower())
        charset = (headers.get_content_charset() if hasattr(headers, "get_content_charset") else None) or "utf-8"
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > PAGE_LIMIT:
                raise ValueError(f"page is larger than {PAGE_LIMIT // (1024 * 1024)} MB")
            chunks.append(chunk)
            if time.monotonic() > deadline:
                raise TimeoutError(f"took longer than {seconds:g} seconds")
        return b"".join(chunks), ctype, charset
    finally:
        close = getattr(response, "close", None)
        if close:
            close()


def fetch_pages(urls, dest: Path, *, opener: Callable | None = None) -> list[Fetched]:
    """Save each page as text in ``dest``. A page that fails is noted with its reason
    and the rest go on. ``opener(url, timeout)`` returns a response with ``read`` and ``headers``."""
    opener = opener or _default_open
    dest = Path(dest)
    results: list[Fetched] = []
    for url in urls:
        if not _is_url(url):
            results.append(Fetched(url, error="only http and https addresses are fetched"))
            continue
        try:
            data, ctype, charset = _download(url, opener, PAGE_SECONDS)
            if not (ctype.startswith("text/") or ctype in ("application/xhtml+xml", "application/json", "application/xml")):
                raise ValueError(f"not a text page ({ctype})")
            text = data.decode(charset, errors="replace")
            if ctype in ("text/html", "application/xhtml+xml"):
                text = html_to_text(text)
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / _filename(url)
            path.write_text(text, encoding="utf-8")
            results.append(Fetched(url, path))
        except Exception as error:  # one bad page must not stop the rest
            results.append(Fetched(url, error=str(error) or type(error).__name__))
    return results
