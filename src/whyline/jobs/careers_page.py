"""Read schema.org JobPosting JSON-LD from a company's own careers page (JOB-18).

Polite by construction: robots.txt first, the careers page plus at most 20 same-host job
links, one request per second (the shared client), no cookies, no login, no off-host links.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import urllib.parse
import urllib.robotparser
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

from whyline.jobs import ats, companies, fetch

MAX_LINKS = 20
MAX_BYTES = 2 * 1024 * 1024
JOB_PATH_MARKERS = ("/job", "/jobs/", "/careers/", "/positions/")
ROBOTS_MESSAGE = "robots.txt disallows this page"
NO_JOBS_MESSAGE = "No machine-readable jobs found: this page needs a browser"


class _PageScan(HTMLParser):
    """Collect `<a href>` values and `application/ld+json` script bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: builtins.list[str] = []
        self.blocks: builtins.list[str] = []
        self._ld: builtins.list[str] | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        elif tag == "script" and (values.get("type") or "").strip().lower() == "application/ld+json":
            self._ld = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._ld is not None:
            self.blocks.append("".join(self._ld))
            self._ld = None

    def handle_data(self, data: str) -> None:
        if self._ld is not None:
            self._ld.append(data)


def _text(raw: Any) -> str:
    body = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8")
    return bytes(body[:MAX_BYTES]).decode("utf-8", errors="replace").lstrip("﻿")


def _origin(url: str) -> tuple[str, int]:
    parts = urllib.parse.urlsplit(url)
    return (parts.hostname or "").lower(), parts.port or 443


def _job_links(base: str, links: builtins.list[str]) -> builtins.list[str]:
    host = _origin(base)
    start = base.split("#", 1)[0]
    found: builtins.list[str] = []
    for href in links:
        try:
            absolute = urllib.parse.urljoin(base, href.strip()).split("#", 1)[0]
            parts = urllib.parse.urlsplit(absolute)
            same = parts.scheme == "https" and _origin(absolute) == host
        except ValueError:
            continue
        path = parts.path.lower()
        if not same or absolute == start or absolute in found:
            continue
        if any(marker in path for marker in JOB_PATH_MARKERS):
            found.append(absolute)
        if len(found) == MAX_LINKS:
            break
    return found


def _types(node: dict[str, Any]) -> builtins.list[str]:
    kind = node.get("@type")
    return [kind] if isinstance(kind, str) else [k for k in kind or [] if isinstance(k, str)]


def _walk(node: Any) -> builtins.list[dict[str, Any]]:
    """Every JobPosting object in a JSON-LD value, looking through lists and `@graph`."""
    if isinstance(node, builtins.list):
        return [job for item in node for job in _walk(item)]
    if not isinstance(node, dict):
        return []
    out = [node] if "JobPosting" in _types(node) else []
    return out + _walk(node.get("@graph"))


def _location(node: dict[str, Any]) -> str:
    places = node.get("jobLocation")
    places = places if isinstance(places, builtins.list) else [places]
    names = []
    for place in places:
        address = place.get("address") if isinstance(place, dict) else None
        if isinstance(address, dict):
            name = fetch._join(
                address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")
            )
        else:
            name = fetch._s(address)
        if name:
            names.append(name)
    return "; ".join(names)


def _posting(company: str, node: dict[str, Any], page_url: str) -> fetch.Posting:
    title = fetch._s(node.get("title") or node.get("name"))
    own_url = fetch._s(node.get("url"))
    url = own_url or page_url
    ident = node.get("identifier")
    ident = fetch._s(ident.get("value") if isinstance(ident, dict) else ident)
    key = ident or own_url or hashlib.sha1(f"{page_url}\n{title}".encode()).hexdigest()[:16]
    remote = True if fetch._s(node.get("jobLocationType")).upper() == "TELECOMMUTE" else None
    return fetch.Posting(
        uid=f"careers_page:{_origin(page_url)[0]}:{key}",
        company=company,
        title=title,
        location=_location(node),
        remote=remote,
        url=url,
        posted_at=fetch._s(node.get("datePosted")),
        text=fetch.html_to_text(node.get("description")),
    )


def _page_postings(company: str, url: str, raw: Any) -> tuple[builtins.list[fetch.Posting], _PageScan]:
    scan = _PageScan()
    scan.feed(_text(raw))
    scan.close()
    found = []
    for block in scan.blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        found.extend(_posting(company, node, url) for node in _walk(data))
    return found, scan


def careers_jobs(entry: companies.Company, client: Callable[[str], Any]) -> builtins.list[fetch.Posting]:
    """Postings from `entry.careers_url`; `client` must already be limited to that host."""
    url = entry.careers_url
    host, port = _origin(url)
    netloc = host if port == 443 else f"{host}:{port}"
    robots = urllib.robotparser.RobotFileParser()
    try:
        robots.parse(_text(client(f"https://{netloc}/robots.txt")).splitlines())
    except (ats.AtsError, OSError, ValueError):
        robots.parse([])  # no readable robots.txt: nothing is disallowed

    def allowed(target: str) -> bool:
        return robots.can_fetch(ats.user_agent(), target)

    if not allowed(url):
        raise fetch.FetchError(ROBOTS_MESSAGE)

    postings, scan = _page_postings(entry.name, url, client(url))
    for link in _job_links(url, scan.links):
        if not allowed(link):
            continue
        try:
            more, _ = _page_postings(entry.name, link, client(link))
        except (ats.AtsError, OSError, ValueError):
            continue
        postings.extend(more)

    unique = list({p.uid: p for p in postings}.values())
    if not unique:
        raise fetch.FetchError(NO_JOBS_MESSAGE)
    return unique
