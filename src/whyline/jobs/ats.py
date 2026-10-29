"""Public job-board (ATS) detection and rate-limited allowlisted HTTP client."""

from __future__ import annotations

import builtins
import inspect
import ipaddress
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import whyline
from whyline.jobs import profile

TIMEOUT_SECONDS: int = 15
RATE_LIMIT_SECONDS: float = 1.0
MAX_URL_LENGTH: int = 2048
_MAX_RESPONSE_BYTES: int = 5 * 1024 * 1024

BOARD_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}"),
    ("workable", "https://apply.workable.com/api/v1/widget/accounts/{slug}"),
    ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/{slug}/postings"),
    ("recruitee", "https://{slug}.recruitee.com/api/offers/"),
)

ATS_BOARDS: tuple[str, ...] = tuple(board for board, _ in BOARD_ENDPOINTS)

BOARD_API_HOSTS: frozenset[str] = frozenset(
    {
        "boards-api.greenhouse.io",
        "api.lever.co",
        "api.ashbyhq.com",
        "apply.workable.com",
        "api.smartrecruiters.com",
    }
)

_FORBIDDEN_CAREERS_DOMAINS: tuple[str, ...] = (
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
)
_RESERVED_RECRUITEE_SUBDOMAINS: frozenset[str] = frozenset(
    {"www", "app", "api", "support", "help", "docs"}
)
_RESERVED_WORKABLE_SUBDOMAINS: frozenset[str] = frozenset(
    {"apply", "www", "jobs", "api"}
)

_HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PATH_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,78}[a-z0-9])?$")
_ALNUM_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STDLIB_URLOPEN = urllib.request.urlopen


class AtsError(profile.ProfileError):
    """Raised when an ATS URL, host, or HTTP response violates job-board rules."""


class HostNotAllowedError(AtsError):
    """Raised before any network call when a URL targets a disallowed host or scheme."""


def user_agent() -> str:
    """Return the required User-Agent header value `whyline/<version> (personal job search)`."""
    return f"whyline/{whyline.__version__} (personal job search)"


USER_AGENT: str = user_agent()


@dataclass(frozen=True, eq=False)
class DetectionResult:
    """Detected job board (`ats`) and board `slug` (`''` for `careers_page` / `unknown`)."""

    ats: str
    slug: str = ""

    @property
    def board(self) -> str:
        return self.ats

    def __iter__(self) -> Iterator[str]:
        yield self.ats
        yield self.slug

    def __len__(self) -> int:
        return 2

    def __getitem__(self, key: int | str) -> str:
        if isinstance(key, int):
            return (self.ats, self.slug)[key]
        if key in ("ats", "board"):
            return self.ats
        if key == "slug":
            return self.slug
        raise KeyError(key)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DetectionResult):
            return (self.ats, self.slug) == (other.ats, other.slug)
        if isinstance(other, tuple):
            return (self.ats, self.slug) == other
        if isinstance(other, str):
            return self.ats == other
        return NotImplemented


def is_recruitee_board_host(host: str) -> bool:
    """Return True if `host` is `{slug}.recruitee.com` for a valid single-label slug."""
    lowered = host.lower()
    if not lowered.endswith(".recruitee.com"):
        return False
    sub = lowered[: -len(".recruitee.com")]
    return bool(_HOST_LABEL_RE.fullmatch(sub)) and sub not in _RESERVED_RECRUITEE_SUBDOMAINS


def is_board_api_host(host: str) -> bool:
    """Return True if `host` is one of the 6 allowed public job-board API hosts."""
    lowered = host.lower()
    return lowered in BOARD_API_HOSTS or is_recruitee_board_host(lowered)


def _is_unsafe_network_host(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if not lowered or lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    if lowered.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(lowered)
        return True
    except ValueError:
        return False


def _parse_https_url(raw_url: Any, label: str = "URL") -> urllib.parse.SplitResult:
    if not isinstance(raw_url, str):
        raise HostNotAllowedError(f"{label} must be an https:// URL string.")
    cleaned = raw_url.strip()
    if not cleaned or len(cleaned) > MAX_URL_LENGTH:
        raise HostNotAllowedError(f"{label} is empty or exceeds {MAX_URL_LENGTH} characters.")
    if not cleaned.isprintable() or any(ch.isspace() for ch in cleaned):
        raise HostNotAllowedError(f"{label} must not contain whitespace or control characters.")
    try:
        parts = urllib.parse.urlsplit(cleaned)
        _ = parts.port
    except ValueError as error:
        raise HostNotAllowedError(f"Invalid {label}: {error}") from error
    if parts.scheme.lower() != "https":
        raise HostNotAllowedError(f"{label} must use https://.")
    if parts.username is not None or parts.password is not None:
        raise HostNotAllowedError(f"{label} must not include credentials.")
    host = parts.hostname or ""
    if not host or host.startswith(".") or host.endswith(".") or ".." in host:
        raise HostNotAllowedError(f"{label} must include a valid host.")
    return parts


def _validated_careers_origin(careers_url: str) -> tuple[str, int]:
    parts = _parse_https_url(careers_url, label="careers_url")
    host = (parts.hostname or "").lower()
    if _is_unsafe_network_host(host):
        raise HostNotAllowedError(f"Refusing disallowed careers_url host: {host}")
    for domain in _FORBIDDEN_CAREERS_DOMAINS:
        if host == domain or host.endswith("." + domain):
            raise HostNotAllowedError(f"Refusing disallowed careers_url host: {host}")
    return host, parts.port if parts.port is not None else 443


def validate_fetch_url(url: str, *, careers_url: str | None = None) -> str:
    """Validate that `url` uses https and targets an allowlisted board host (or `careers_url` host)."""
    parts = _parse_https_url(url, label="Request URL")
    host = (parts.hostname or "").lower()
    port = parts.port if parts.port is not None else 443

    allowed = False
    if is_board_api_host(host) and port == 443:
        allowed = True
    elif careers_url is not None and careers_url.strip():
        allowed_host, allowed_port = _validated_careers_origin(careers_url)
        if host == allowed_host and port == allowed_port:
            allowed = True

    if not allowed:
        raise HostNotAllowedError(f"Refusing HTTP request to disallowed host: {host}")

    netloc = host if parts.port in (None, 443) else f"{host}:{parts.port}"
    return urllib.parse.urlunsplit(
        ("https", netloc, parts.path or "/", parts.query, "")
    )


def is_allowed_url(url: str, *, careers_url: str | None = None) -> bool:
    """Return True if `url` is permitted by the job-board / `careers_page` host allowlist."""
    try:
        validate_fetch_url(url, careers_url=careers_url)
    except AtsError:
        return False
    return True


class RateLimiter:
    """Enforce at most 1 request per `min_interval` seconds per host."""

    def __init__(
        self,
        *,
        min_interval: float = RATE_LIMIT_SECONDS,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.min_interval = float(min_interval)
        self._clock = clock
        self._sleep = sleep
        self._last_by_host: dict[str, float] = {}

    def wait(self, host: str) -> float:
        key = host.lower()
        clock_fn = self._clock if self._clock is not None else time.monotonic
        sleep_fn = self._sleep if self._sleep is not None else time.sleep
        now = float(clock_fn())
        previous = self._last_by_host.get(key)
        if previous is not None:
            elapsed = now - previous
            if elapsed < self.min_interval:
                delay = self.min_interval - elapsed
                sleep_fn(delay)
                self._last_by_host[key] = now + delay
                return delay
        self._last_by_host[key] = now
        return 0.0


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse HTTP redirects that leave the host allowlist or downgrade https."""

    def __init__(
        self,
        *,
        careers_url: str | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        super().__init__()
        self._careers_url = careers_url
        self._limiter = limiter

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        clean_target = validate_fetch_url(resolved, careers_url=self._careers_url)
        prev_host = (urllib.parse.urlsplit(req.full_url).hostname or "").lower()
        next_host = (urllib.parse.urlsplit(clean_target).hostname or "").lower()
        if self._limiter is not None and next_host and next_host != prev_host:
            self._limiter.wait(next_host)
        redirected = super().redirect_request(req, fp, code, msg, headers, clean_target)
        if redirected is not None:
            redirected.add_unredirected_header("User-Agent", user_agent())
        return redirected


class HttpClient:
    """Allowlisted, per-host rate-limited HTTP client."""

    def __init__(
        self,
        transport: Callable[..., Any] | None = None,
        *,
        urlopen: Callable[..., Any] | None = None,
        careers_url: str | None = None,
        timeout: float = TIMEOUT_SECONDS,
        limiter: RateLimiter | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if careers_url is not None and careers_url.strip():
            _validated_careers_origin(careers_url)
            self.careers_url: str | None = careers_url.strip()
        else:
            self.careers_url = None
        self._transport = transport
        self._urlopen = urlopen
        self.timeout = timeout
        self.limiter = (
            limiter
            if limiter is not None
            else RateLimiter(min_interval=RATE_LIMIT_SECONDS, clock=clock, sleep=sleep)
        )

    def __call__(self, url: str) -> Any:
        clean_url = validate_fetch_url(url, careers_url=self.careers_url)
        host = (urllib.parse.urlsplit(clean_url).hostname or "").lower()
        self.limiter.wait(host)

        headers = {
            "User-Agent": user_agent(),
            "Accept": "application/json",
        }

        if self._transport is not None:
            return _call_injected_transport(self._transport, clean_url, headers, self.timeout)

        request = urllib.request.Request(clean_url, headers=headers)
        if self._urlopen is not None:
            with self._urlopen(request, timeout=self.timeout) as response:
                return _read_bounded_response(response)
        if urllib.request.urlopen is not _STDLIB_URLOPEN:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _read_bounded_response(response)

        opener = urllib.request.build_opener(
            _SafeRedirectHandler(careers_url=self.careers_url, limiter=self.limiter)
        )
        with opener.open(request, timeout=self.timeout) as response:
            return _read_bounded_response(response)


def _call_injected_transport(
    transport: Callable[..., Any],
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> Any:
    try:
        sig = inspect.signature(transport)
    except (TypeError, ValueError):
        return transport(url)

    kwargs: dict[str, Any] = {}
    if "headers" in sig.parameters:
        kwargs["headers"] = dict(headers)
    if "timeout" in sig.parameters:
        kwargs["timeout"] = timeout
    return transport(url, **kwargs)


def _read_bounded_response(response: Any) -> bytes:
    status = getattr(response, "status", None)
    if status is None and hasattr(response, "getcode"):
        status = response.getcode()
    if isinstance(status, int) and (status < 200 or status >= 300):
        raise AtsError(f"Unexpected HTTP status {status}.")
    raw = response.read(_MAX_RESPONSE_BYTES + 1)
    if isinstance(raw, str):
        encoded = raw.encode("utf-8")
        if len(encoded) > _MAX_RESPONSE_BYTES:
            raise AtsError("HTTP response exceeds size limit.")
        return encoded
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise AtsError("HTTP response exceeds size limit.")
    return bytes(raw)


def make_http(
    http: Callable[..., Any] | None = None,
    *,
    careers_url: str | None = None,
    timeout: float = TIMEOUT_SECONDS,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> HttpClient:
    """Wrap `http` (or default `urllib.request`) in an allowlisted, rate-limited `HttpClient`."""
    normalized_careers = careers_url.strip() if isinstance(careers_url, str) and careers_url.strip() else None
    if isinstance(http, HttpClient):
        if (
            http.careers_url == normalized_careers
            and clock is None
            and sleep is None
            and http.timeout == timeout
        ):
            return http
        limiter = (
            http.limiter
            if clock is None and sleep is None
            else RateLimiter(min_interval=RATE_LIMIT_SECONDS, clock=clock, sleep=sleep)
        )
        return HttpClient(
            transport=http._transport,
            urlopen=http._urlopen,
            careers_url=normalized_careers,
            timeout=timeout,
            limiter=limiter,
        )
    return HttpClient(
        transport=http,
        careers_url=normalized_careers,
        timeout=timeout,
        clock=clock,
        sleep=sleep,
    )


def _clean_path_slug(raw: str) -> str | None:
    candidate = raw.strip().lower()
    if _PATH_SLUG_RE.fullmatch(candidate):
        return candidate
    return None


def _extract_board_matches(careers_url: str | None) -> builtins.list[tuple[str, str]]:
    """Extract `(board, slug)` pairs when `careers_url` is on a known job-board host."""
    if not careers_url or not isinstance(careers_url, str) or not careers_url.strip():
        return []
    try:
        parts = _parse_https_url(careers_url, label="careers_url")
    except AtsError:
        return []

    host = (parts.hostname or "").lower()
    segments = [seg for seg in parts.path.split("/") if seg]
    matches: builtins.list[tuple[str, str]] = []

    def _add(board: str, raw_slug: str) -> None:
        cleaned = _clean_path_slug(raw_slug)
        if cleaned is not None and (board, cleaned) not in matches:
            matches.append((board, cleaned))

    if host in {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "job-boards.eu.greenhouse.io",
    }:
        if segments and segments[0].lower() == "embed":
            qs = urllib.parse.parse_qs(parts.query)
            for item in qs.get("for", []):
                _add("greenhouse", item)
        elif segments and segments[0].lower() not in {"v1", "embed"}:
            _add("greenhouse", segments[0])
    elif host == "boards-api.greenhouse.io":
        if len(segments) >= 3 and segments[0].lower() == "v1" and segments[1].lower() == "boards":
            _add("greenhouse", segments[2])
    elif host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        if segments:
            _add("lever", segments[0])
    elif host in {"api.lever.co", "api.eu.lever.co"}:
        if len(segments) >= 3 and segments[0].lower() == "v0" and segments[1].lower() == "postings":
            _add("lever", segments[2])
    elif host == "jobs.ashbyhq.com":
        if segments:
            _add("ashby", segments[0])
    elif host == "api.ashbyhq.com":
        if (
            len(segments) >= 3
            and segments[0].lower() == "posting-api"
            and segments[1].lower() == "job-board"
        ):
            _add("ashby", segments[2])
    elif host == "apply.workable.com":
        lowered_segs = [s.lower() for s in segments]
        if len(lowered_segs) >= 5 and lowered_segs[:4] == ["api", "v1", "widget", "accounts"]:
            _add("workable", segments[4])
        elif len(lowered_segs) >= 4 and lowered_segs[0] == "api" and lowered_segs[2] == "accounts":
            _add("workable", segments[3])
        elif segments and lowered_segs[0] not in {"api", "j"}:
            _add("workable", segments[0])
    elif host == "jobs.workable.com":
        if len(segments) >= 3 and segments[0].lower() == "company":
            _add("workable", segments[2])
    elif host.endswith(".workable.com"):
        sub = host[: -len(".workable.com")]
        if _HOST_LABEL_RE.fullmatch(sub) and sub not in _RESERVED_WORKABLE_SUBDOMAINS:
            _add("workable", sub)
    elif host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}:
        if segments:
            _add("smartrecruiters", segments[0])
    elif host == "api.smartrecruiters.com":
        if (
            len(segments) >= 3
            and segments[0].lower() == "v1"
            and segments[1].lower() == "companies"
        ):
            _add("smartrecruiters", segments[2])
    elif is_recruitee_board_host(host):
        sub = host[: -len(".recruitee.com")]
        _add("recruitee", sub)

    return matches


def extract_board_slugs(careers_url: str | None) -> builtins.list[str]:
    """Return unique safe slugs extracted from `careers_url` when on a known board host."""
    slugs: builtins.list[str] = []
    for _, slug in _extract_board_matches(careers_url):
        if slug not in slugs:
            slugs.append(slug)
        if "_" in slug:
            hyphenated = re.sub(r"[_-]+", "-", slug).strip("-")
            if _PATH_SLUG_RE.fullmatch(hyphenated) and hyphenated not in slugs:
                slugs.append(hyphenated)
    return slugs


def _fold_ascii_lower(name: str) -> str:
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()


def slug_guesses(name: str, careers_url: str | None = None) -> builtins.list[str]:
    """Build ordered unique slug guesses from `careers_url` (if on a board host) and `name`."""
    if not isinstance(name, str) or not name.strip():
        raise AtsError("Company name must be a non-empty string.")

    guesses: builtins.list[str] = []

    def _push(candidate: str) -> None:
        if _PATH_SLUG_RE.fullmatch(candidate) and candidate not in guesses:
            guesses.append(candidate)

    for url_slug in extract_board_slugs(careers_url):
        _push(url_slug)

    folded = _fold_ascii_lower(name)
    if not any(ch.isspace() for ch in name):
        no_spaces = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "", folded)).strip("-")
        if no_spaces:
            _push(no_spaces)

    tokens = _ALNUM_TOKEN_RE.findall(folded)
    if tokens:
        _push("".join(tokens))
        _push("-".join(tokens))

    return guesses


def _has_valid_careers_url(careers_url: str | None) -> bool:
    if not careers_url or not isinstance(careers_url, str) or not careers_url.strip():
        return False
    try:
        _parse_https_url(careers_url, label="careers_url")
    except AtsError:
        return False
    return True


def _is_job_dict_list(value: Any) -> bool:
    return isinstance(value, builtins.list) and all(isinstance(item, dict) for item in value)


def _is_valid_jobs_payload(
    board: str,
    raw: Any,
    *,
    from_smartrecruiters_url: bool = False,
) -> bool:
    if raw is None:
        return False
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], int):
        status, body = raw
        if status < 200 or status >= 300:
            return False
        raw = body
    elif hasattr(raw, "read") and callable(raw.read):
        try:
            raw = _read_bounded_response(raw)
        except (OSError, AtsError):
            return False

    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > _MAX_RESPONSE_BYTES:
            return False
        try:
            text = bytes(raw).decode("utf-8").lstrip("\ufeff")
        except UnicodeDecodeError:
            return False
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False
    elif isinstance(raw, str):
        if len(raw.encode("utf-8", errors="ignore")) > _MAX_RESPONSE_BYTES:
            return False
        try:
            data = json.loads(raw.lstrip("\ufeff"))
        except json.JSONDecodeError:
            return False
    elif isinstance(raw, (builtins.list, dict)):
        data = raw
    else:
        return False

    items: Any = None
    if board == "greenhouse":
        if isinstance(data, dict):
            items = data.get("jobs")
        elif isinstance(data, builtins.list):
            items = data
    elif board == "lever":
        if isinstance(data, builtins.list):
            items = data
        elif isinstance(data, dict):
            items = data.get("postings", data.get("jobs"))
    elif board == "ashby":
        if isinstance(data, dict):
            if data.get("success") is False:
                return False
            items = data.get("jobs", data.get("jobPostings"))
        elif isinstance(data, builtins.list):
            items = data
    elif board == "workable":
        if isinstance(data, dict):
            items = data.get("jobs")
        elif isinstance(data, builtins.list):
            items = data
    elif board == "smartrecruiters":
        if isinstance(data, dict):
            items = data.get("content", data.get("jobs"))
            if (
                _is_job_dict_list(items)
                and len(items) == 0
                and data.get("totalFound") == 0
                and not from_smartrecruiters_url
            ):
                return False
        elif isinstance(data, builtins.list):
            items = data
    elif board == "recruitee":
        if isinstance(data, dict):
            items = data.get("offers", data.get("jobs"))
        elif isinstance(data, builtins.list):
            items = data

    return _is_job_dict_list(items)


def detect(
    name: str,
    careers_url: str | None = None,
    http: Callable[..., Any] | None = None,
    *,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> DetectionResult:
    """Probe public ATS endpoints in order and stop at the first returning a valid job list."""
    slugs = slug_guesses(name, careers_url)
    sr_url_slugs = {
        slug for board, slug in _extract_board_matches(careers_url) if board == "smartrecruiters"
    }
    client = make_http(http, clock=clock, sleep=sleep)

    for slug in slugs:
        for board, template in BOARD_ENDPOINTS:
            if board == "recruitee" and not (
                _HOST_LABEL_RE.fullmatch(slug) and slug not in _RESERVED_RECRUITEE_SUBDOMAINS
            ):
                continue
            endpoint_url = template.format(slug=slug)
            try:
                payload = client(endpoint_url)
            except HostNotAllowedError:
                continue
            except (urllib.error.URLError, TimeoutError, OSError, AtsError, ValueError):
                continue

            if _is_valid_jobs_payload(
                board,
                payload,
                from_smartrecruiters_url=(slug in sr_url_slugs),
            ):
                return DetectionResult(ats=board, slug=slug)

    if _has_valid_careers_url(careers_url):
        return DetectionResult(ats="careers_page", slug="")
    return DetectionResult(ats="unknown", slug="")
