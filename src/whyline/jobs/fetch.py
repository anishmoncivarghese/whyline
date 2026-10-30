"""Fetch and normalise postings from public job boards (JOB-7 allowlist, rate limit, UA, timeout)."""

from __future__ import annotations

import builtins
import datetime
import difflib
import html
import json
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from whyline.jobs import ats, companies, profile

_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "table"}
)
_SKIP_TAGS = frozenset({"script", "style"})
_BLANK_RUN_RE = re.compile(r"\n{3,}")

LIST_URLS: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
}
_SMARTRECRUITERS_DETAIL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}"


class FetchError(profile.ProfileError):
    """Raised when one company's board cannot be fetched or parsed."""


@dataclass(frozen=True)
class Posting:
    uid: str
    company: str
    title: str
    location: str = ""
    remote: bool | None = None
    url: str = ""
    posted_at: str = ""
    text: str = ""

    def to_markdown(self) -> str:
        header = [
            f"# {self.title or '(untitled)'}",
            "",
            f"- Company: {self.company}",
            f"- Title: {self.title}",
            f"- Location: {self.location or 'not stated'}",
            f"- URL: {self.url}",
            f"- Posted: {self.posted_at or 'unknown'}",
            "",
        ]
        return "\n".join(header) + self.text.strip() + "\n"


@dataclass(frozen=True)
class FetchResult:
    postings: tuple[Posting, ...] = ()
    errors: tuple[tuple[str, str], ...] = ()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: builtins.list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS and tag != "li":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: Any) -> str:
    """Strip tags from `raw` HTML, keeping line breaks between blocks."""
    if not isinstance(raw, str) or not raw.strip():
        return ""
    source = raw
    if "<" not in source and "&lt;" in source:
        source = html.unescape(source)  # Greenhouse escapes its HTML
    parser = _TextExtractor()
    parser.feed(source)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    return _BLANK_RUN_RE.sub("\n\n", "\n".join(lines)).strip()


def _s(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value))


def _iso_from_ms(value: Any) -> str:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.datetime.fromtimestamp(value / 1000, datetime.timezone.utc).isoformat(
            timespec="seconds"
        )
    return _s(value)


def _json(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8").lstrip("﻿")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _items(data: Any, *keys: str) -> builtins.list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), builtins.list):
                data = data[key]
                break
    if not isinstance(data, builtins.list):
        raise FetchError("Board response did not contain a job list.")
    return [item for item in data if isinstance(item, dict)]


def _join(*parts: Any) -> str:
    return ", ".join(p for p in (_s(x) for x in parts) if p)


def _greenhouse(name: str, slug: str, client: Callable[[str], Any]) -> builtins.list[Posting]:
    data = _json(client(LIST_URLS["greenhouse"].format(slug=slug)))
    out = []
    for job in _items(data, "jobs"):
        loc = job.get("location")
        location = _s(loc.get("name")) if isinstance(loc, dict) else _s(loc)
        out.append(
            Posting(
                uid=f"greenhouse:{slug}:{_s(job.get('id'))}",
                company=name,
                title=_s(job.get("title")),
                location=location,
                remote=True if "remote" in location.lower() else None,
                url=_s(job.get("absolute_url")),
                posted_at=_s(job.get("updated_at") or job.get("first_published")),
                text=html_to_text(job.get("content")),
            )
        )
    return out


def _lever(name: str, slug: str, client: Callable[[str], Any]) -> builtins.list[Posting]:
    data = _json(client(LIST_URLS["lever"].format(slug=slug)))
    out = []
    for job in _items(data, "postings", "jobs"):
        cats = job.get("categories") if isinstance(job.get("categories"), dict) else {}
        workplace = _s(job.get("workplaceType") or cats.get("workplaceType")).lower()
        text = html_to_text(job.get("description")) or _s(job.get("descriptionPlain"))
        out.append(
            Posting(
                uid=f"lever:{slug}:{_s(job.get('id'))}",
                company=name,
                title=_s(job.get("text")),
                location=_s(cats.get("location")),
                remote=(workplace == "remote") if workplace else None,
                url=_s(job.get("hostedUrl")),
                posted_at=_iso_from_ms(job.get("createdAt")),
                text=text,
            )
        )
    return out


def _ashby(name: str, slug: str, client: Callable[[str], Any]) -> builtins.list[Posting]:
    data = _json(client(LIST_URLS["ashby"].format(slug=slug)))
    out = []
    for job in _items(data, "jobs", "jobPostings"):
        remote = job.get("isRemote")
        text = html_to_text(job.get("descriptionHtml")) or _s(job.get("descriptionPlain"))
        out.append(
            Posting(
                uid=f"ashby:{slug}:{_s(job.get('id'))}",
                company=name,
                title=_s(job.get("title")),
                location=_s(job.get("location")),
                remote=remote if isinstance(remote, bool) else None,
                url=_s(job.get("jobUrl")),
                posted_at=_s(job.get("publishedAt")),
                text=text,
            )
        )
    return out


def _workable(name: str, slug: str, client: Callable[[str], Any]) -> builtins.list[Posting]:
    data = _json(client(LIST_URLS["workable"].format(slug=slug)))
    out = []
    for job in _items(data, "jobs"):
        remote = job.get("telecommuting")
        out.append(
            Posting(
                uid=f"workable:{slug}:{_s(job.get('shortcode') or job.get('id'))}",
                company=name,
                title=_s(job.get("title")),
                location=_join(job.get("city"), job.get("state"), job.get("country")),
                remote=remote if isinstance(remote, bool) else None,
                url=_s(job.get("url") or job.get("shortlink")),
                posted_at=_s(job.get("published_on") or job.get("created_at")),
                text=html_to_text(job.get("description")),
            )
        )
    return out


def _smartrecruiters(name: str, slug: str, client: Callable[[str], Any]) -> builtins.list[Posting]:
    data = _json(client(LIST_URLS["smartrecruiters"].format(slug=slug)))
    out = []
    for job in _items(data, "content", "jobs"):
        job_id = _s(job.get("id"))
        loc = job.get("location") if isinstance(job.get("location"), dict) else {}
        remote = loc.get("remote")
        url = ""
        text = ""
        if job_id:
            try:
                detail = _json(
                    client(_SMARTRECRUITERS_DETAIL.format(slug=slug, id=job_id))
                )
            except (ats.AtsError, OSError, ValueError):
                detail = {}
            if isinstance(detail, dict):
                url = _s(detail.get("postingUrl"))
                sections = (detail.get("jobAd") or {}).get("sections") or {}
                chunks = [
                    html_to_text((sec or {}).get("text"))
                    for sec in (sections.values() if isinstance(sections, dict) else [])
                ]
                text = "\n\n".join(c for c in chunks if c)
        out.append(
            Posting(
                uid=f"smartrecruiters:{slug}:{job_id}",
                company=name,
                title=_s(job.get("name")),
                location=_join(loc.get("city"), loc.get("region"), _s(loc.get("country")).upper()),
                remote=remote if isinstance(remote, bool) else None,
                url=url,
                posted_at=_s(job.get("releasedDate")),
                text=text,
            )
        )
    return out


def _recruitee(name: str, slug: str, client: Callable[[str], Any]) -> builtins.list[Posting]:
    data = _json(client(LIST_URLS["recruitee"].format(slug=slug)))
    out = []
    for job in _items(data, "offers", "jobs"):
        remote = job.get("remote")
        out.append(
            Posting(
                uid=f"recruitee:{slug}:{_s(job.get('id'))}",
                company=name,
                title=_s(job.get("title")),
                location=_s(job.get("location")),
                remote=remote if isinstance(remote, bool) else None,
                url=_s(job.get("careers_url")),
                posted_at=_s(job.get("published_at")),
                text=html_to_text(job.get("description")),
            )
        )
    return out


_PARSERS: dict[str, Callable[[str, str, Callable[[str], Any]], builtins.list[Posting]]] = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workable": _workable,
    "smartrecruiters": _smartrecruiters,
    "recruitee": _recruitee,
}


def _resolve(company: companies.Company | str) -> companies.Company:
    if isinstance(company, companies.Company):
        return company
    key = " ".join(str(company).split()).casefold()
    for entry in companies.list():
        if " ".join(entry.name.split()).casefold() == key:
            return entry
    raise FetchError(f"Company not found: {company}")


def board_jobs(
    company: companies.Company | str,
    http: Callable[..., Any] | None = None,
    *,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> builtins.list[Posting]:
    """Return normalised postings from the board JOB-7 recorded for `company`."""
    entry = _resolve(company)
    if entry.ats == "careers_page" and entry.careers_url.startswith("https://"):
        from whyline.jobs import careers_page

        client = ats.make_http(http, careers_url=entry.careers_url, clock=clock, sleep=sleep)
        try:
            return careers_page.careers_jobs(entry, client)
        except FetchError:
            raise
        except Exception as error:
            raise FetchError(f"{entry.name}: {type(error).__name__}: {error}") from error
    parser = _PARSERS.get(entry.ats)
    if parser is None or not entry.slug:
        raise FetchError(f"{entry.name}: no supported job board recorded (ats={entry.ats}).")
    client = ats.make_http(http, clock=clock, sleep=sleep)
    try:
        return parser(entry.name, entry.slug, client)
    except FetchError:
        raise
    except Exception as error:  # one board's failure must be reportable, not fatal
        raise FetchError(f"{entry.name}: {type(error).__name__}: {error}") from error


TITLE_MATCH_MIN = 0.85
_COMPANY_SUFFIXES = frozenset(
    {"inc", "incorporated", "ltd", "limited", "llc", "gmbh", "ag", "plc", "corp",
     "corporation", "co", "company", "sa", "bv", "nv", "oy", "ab", "srl", "pty"}
)
_WORD_RE = re.compile(r"[a-z0-9]+")


def company_key(name: str) -> str:
    """A company name folded for matching: case, punctuation and "Inc"/"Ltd"/"GmbH" ignored."""
    words = _WORD_RE.findall(name.casefold())
    while len(words) > 1 and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def best_title_match(title: str, postings: builtins.list[Posting]) -> Posting | None:
    """The posting whose normalised title is closest to `title`, if it scores >= 0.85."""
    wanted = " ".join(_WORD_RE.findall(title.casefold()))
    best, best_score = None, 0.0
    for posting in postings:
        found = " ".join(_WORD_RE.findall(posting.title.casefold()))
        score = difflib.SequenceMatcher(None, wanted, found).ratio() if wanted and found else 0.0
        if score > best_score:
            best, best_score = posting, score
    return best if best_score >= TITLE_MATCH_MIN else None


def board_job_for_link(
    link: str, company: str, client: Callable[..., Any]
) -> Posting | None:
    """Fetch the board behind `link` (only when it is on a known board host) and return that job.

    Any other link, LinkedIn included, is never requested.
    """
    try:
        found = ats._extract_board_matches(link)
        path = [seg for seg in urllib.parse.urlsplit(link).path.split("/") if seg]
    except (ValueError, ats.AtsError):
        return None
    bare = link.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    for board, slug in found:
        entry = companies.Company(name=company, status="accepted", ats=board, slug=slug)
        try:
            jobs = board_jobs(entry, client)
        except Exception:
            continue
        for job in jobs:
            job_id = job.uid.rsplit(":", 1)[-1]
            if (job_id and job_id in path) or (job.url and job.url.rstrip("/") == bare):
                return job
    return None


def fetch_all(
    entries: builtins.list[companies.Company] | None = None,
    http: Callable[..., Any] | None = None,
    *,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> FetchResult:
    """Fetch every company (default: accepted ones); report errors per company and carry on."""
    if entries is None:
        entries = companies.list("accepted")
    client = ats.make_http(http, clock=clock, sleep=sleep)
    postings: builtins.list[Posting] = []
    errors: builtins.list[tuple[str, str]] = []
    for entry in entries:
        try:
            postings.extend(board_jobs(entry, client))
        except Exception as error:
            errors.append((entry.name, str(error)))
    return FetchResult(postings=tuple(postings), errors=tuple(errors))
