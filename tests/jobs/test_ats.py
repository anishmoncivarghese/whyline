"""Tests for `whyline.jobs.ats`, `companies.check`, and `whyline jobs companies check`."""

from __future__ import annotations

import datetime
import io
import json
import os
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import whyline
from whyline import cli
from whyline.jobs import ats, companies, paths

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FakeClock:
    """Deterministic fake monotonic clock that never sleeps."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def isolated_home_and_no_sleep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))

    def _forbid_real_sleep(seconds: float) -> None:
        raise AssertionError(f"Real time.sleep({seconds}) must never be called in tests.")

    monkeypatch.setattr(time, "sleep", _forbid_real_sleep)

    def _forbid_real_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Real network urlopen must never be called in tests.")

    monkeypatch.setattr(urllib.request, "urlopen", _forbid_real_network)
    return home_dir


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_DIR / f"{name}.json").read_bytes()


def _not_found(url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b'{"error":"not found"}'))


@pytest.mark.parametrize(
    ("board", "company_name", "expected_slug", "expected_url"),
    [
        (
            "greenhouse",
            "Stripe",
            "stripe",
            "https://boards-api.greenhouse.io/v1/boards/stripe/jobs",
        ),
        (
            "lever",
            "Palantir",
            "palantir",
            "https://api.lever.co/v0/postings/palantir?mode=json",
        ),
        (
            "ashby",
            "Linear",
            "linear",
            "https://api.ashbyhq.com/posting-api/job-board/linear",
        ),
        (
            "workable",
            "Workable Demo",
            "workable-demo",
            "https://apply.workable.com/api/v1/widget/accounts/workable-demo",
        ),
        (
            "smartrecruiters",
            "Bosch Group",
            "boschgroup",
            "https://api.smartrecruiters.com/v1/companies/boschgroup/postings",
        ),
        (
            "recruitee",
            "Homeday",
            "homeday",
            "https://homeday.recruitee.com/api/offers/",
        ),
    ],
)
def test_each_board_detected_from_recorded_fixtures_and_stops_at_first(
    board: str,
    company_name: str,
    expected_slug: str,
    expected_url: str,
) -> None:
    payload = _fixture_bytes(board)
    requested: list[str] = []
    clock = FakeClock()

    def fake_http(url: str) -> bytes:
        requested.append(url)
        if url == expected_url:
            return payload
        raise _not_found(url)

    result = ats.detect(
        company_name,
        http=fake_http,
        clock=clock,
        sleep=clock.sleep,
    )
    assert result.ats == board
    assert result.slug == expected_slug
    assert tuple(result) == (board, expected_slug)
    assert requested[-1] == expected_url
    # Stops immediately at the matching endpoint without probing subsequent boards.
    assert requested.count(expected_url) == 1


def test_probe_order_stops_at_first_matching_board() -> None:
    requested: list[str] = []

    def fake_http(url: str) -> bytes:
        requested.append(url)
        if "api.lever.co" in url:
            return _fixture_bytes("lever")
        if "api.ashbyhq.com" in url:
            return _fixture_bytes("ashby")
        raise _not_found(url)

    result = ats.detect("Palantir", http=fake_http)
    assert result.ats == "lever"
    assert result.slug == "palantir"
    assert requested == [
        "https://boards-api.greenhouse.io/v1/boards/palantir/jobs",
        "https://api.lever.co/v0/postings/palantir?mode=json",
    ]


def test_not_found_returns_unknown_or_careers_page_and_handles_invalid_payloads() -> None:
    clock = FakeClock()
    responses = iter(
        [
            b"<html>404 Not Found</html>",
            b'{"ok": false, "error": "Document not found"}',
            b'{"success": false, "errors": ["board_not_found"]}',
            b'{"error": "Account not found"}',
            b'{"totalFound": 0, "offset": 0, "limit": 100, "content": []}',
            b'["not-a-job-dict"]',
        ]
    )

    def mixed_bad_http(url: str) -> bytes:
        try:
            return next(responses)
        except StopIteration:
            raise _not_found(url)

    unknown_res = ats.detect(
        "Mystery Venture",
        http=mixed_bad_http,
        clock=clock,
        sleep=clock.sleep,
    )
    assert unknown_res.ats == "unknown"
    assert unknown_res.slug == ""

    empty_url_res = ats.detect(
        "SoloName",
        careers_url="",
        http=lambda url: b"{}",
        clock=clock,
        sleep=clock.sleep,
    )
    assert empty_url_res.ats == "unknown"
    assert empty_url_res.slug == ""

    careers_res = ats.detect(
        "Stripe",
        careers_url="https://stripe.com/jobs",
        http=lambda url: (_ for _ in ()).throw(_not_found(url)),
        clock=clock,
        sleep=clock.sleep,
    )
    assert careers_res.ats == "careers_page"
    assert careers_res.slug == ""


@pytest.mark.parametrize(
    ("careers_url", "board", "expected_slug", "expected_api_url"),
    [
        (
            "https://boards.greenhouse.io/figma-hq/jobs/4019283",
            "greenhouse",
            "figma-hq",
            "https://boards-api.greenhouse.io/v1/boards/figma-hq/jobs",
        ),
        (
            "https://job-boards.greenhouse.io/anthropic",
            "greenhouse",
            "anthropic",
            "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        ),
        (
            "https://boards.greenhouse.io/embed/job_board?for=embeddedslug",
            "greenhouse",
            "embeddedslug",
            "https://boards-api.greenhouse.io/v1/boards/embeddedslug/jobs",
        ),
        (
            "https://jobs.lever.co/custom-lever/8f3c1e72",
            "lever",
            "custom-lever",
            "https://api.lever.co/v0/postings/custom-lever?mode=json",
        ),
        (
            "https://jobs.ashbyhq.com/linear-eu",
            "ashby",
            "linear-eu",
            "https://api.ashbyhq.com/posting-api/job-board/linear-eu",
        ),
        (
            "https://apply.workable.com/workable-custom/",
            "workable",
            "workable-custom",
            "https://apply.workable.com/api/v1/widget/accounts/workable-custom",
        ),
        (
            "https://jobs.smartrecruiters.com/BoschGroup",
            "smartrecruiters",
            "boschgroup",
            "https://api.smartrecruiters.com/v1/companies/boschgroup/postings",
        ),
        (
            "https://custom-tenant.recruitee.com/o/backend-engineer",
            "recruitee",
            "custom-tenant",
            "https://custom-tenant.recruitee.com/api/offers/",
        ),
    ],
)
def test_careers_url_on_known_board_host_extracts_slug_and_detects_board(
    careers_url: str,
    board: str,
    expected_slug: str,
    expected_api_url: str,
) -> None:
    requested: list[str] = []
    clock = FakeClock()
    fixture = _fixture_bytes(board)

    def fake_http(url: str) -> bytes:
        requested.append(url)
        if url == expected_api_url:
            return fixture
        raise _not_found(url)

    result = ats.detect(
        "Unrelated Display Name",
        careers_url=careers_url,
        http=fake_http,
        clock=clock,
        sleep=clock.sleep,
    )
    assert result.ats == board
    assert result.slug == expected_slug
    assert expected_api_url in requested
    # Human-facing board page hosts (e.g. jobs.lever.co, boards.greenhouse.io) are never fetched directly.
    for req_url in requested:
        host = urllib.parse.urlsplit(req_url).hostname or ""
        assert ats.is_board_api_host(host), req_url


def test_host_outside_allowlist_is_never_requested() -> None:
    requested: list[str] = []
    clock = FakeClock()

    def spy_http(url: str) -> bytes:
        requested.append(url)
        raise _not_found(url)

    for name, offlist_url in (
        ("Acme", "https://acme.example.com/careers"),
        ("Acme", "https://www.linkedin.com/company/acme/jobs"),
        ("Acme", "https://boards.greenhouse.io.evil.example/acme"),
        ("Acme", "https://boards.greenhouse.io/../../evil.example"),
        ("../../evil.example/steal", "https://evil.example/jobs"),
    ):
        res = ats.detect(
            name,
            careers_url=offlist_url,
            http=spy_http,
            clock=clock,
            sleep=clock.sleep,
        )
        assert res.ats == "careers_page"

    assert requested
    for url in requested:
        parsed = urllib.parse.urlsplit(url)
        assert parsed.scheme == "https"
        assert ats.is_board_api_host(parsed.hostname or ""), url

    # Direct HttpClient calls also refuse off-list hosts, non-https, and scraped sites before calling transport.
    transport_calls: list[str] = []
    strict_client = ats.make_http(
        lambda url: (transport_calls.append(url), b"[]")[1],
        clock=clock,
        sleep=clock.sleep,
    )
    for forbidden_url in (
        "https://evil.example.com/api/jobs",
        "https://www.linkedin.com/jobs/view/123",
        "https://boards.greenhouse.io/stripe",
        "http://boards-api.greenhouse.io/v1/boards/stripe/jobs",
        "https://user:pass@boards-api.greenhouse.io/v1/boards/stripe/jobs",
        "https://www.recruitee.com/api/offers/",
        "https://a.b.recruitee.com/api/offers/",
    ):
        with pytest.raises(ats.HostNotAllowedError):
            strict_client(forbidden_url)
    assert transport_calls == []

    # When careers_url is explicitly configured for `careers_page`, only that host + board hosts are allowed.
    careers_client = ats.make_http(
        lambda url: (transport_calls.append(url), b"<html/>")[1],
        careers_url="https://careers.acme.example/openings",
        clock=clock,
        sleep=clock.sleep,
    )
    careers_client("https://careers.acme.example/openings")
    careers_client("https://careers.acme.example/jobs/backend")
    with pytest.raises(ats.HostNotAllowedError):
        careers_client("https://other.acme.example/jobs")
    with pytest.raises(ats.HostNotAllowedError):
        careers_client("http://careers.acme.example/openings")
    assert transport_calls == [
        "https://careers.acme.example/openings",
        "https://careers.acme.example/jobs/backend",
    ]

    # _SafeRedirectHandler also blocks redirects leaving the allowlist or downgrading https.
    redirect_handler = ats._SafeRedirectHandler(limiter=ats.RateLimiter(clock=clock, sleep=clock.sleep))
    initial_req = urllib.request.Request("https://boards-api.greenhouse.io/v1/boards/acme/jobs")
    with pytest.raises(ats.HostNotAllowedError):
        redirect_handler.redirect_request(
            initial_req, None, 302, "Found", {}, "https://evil.example.com/jobs"
        )
    with pytest.raises(ats.HostNotAllowedError):
        redirect_handler.redirect_request(
            initial_req, None, 302, "Found", {}, "http://boards-api.greenhouse.io/v1/boards/acme/jobs"
        )


def test_rate_limit_one_request_per_second_per_host_with_injected_clock() -> None:
    clock = FakeClock(start=50.0)
    call_log: list[tuple[str, float]] = []

    def recording_http(url: str) -> bytes:
        host = urllib.parse.urlsplit(url).hostname or ""
        call_log.append((host, clock()))
        # Simulate 0.1s network latency on each call.
        clock.now += 0.1
        raise _not_found(url)

    # Two-word company produces ["scaleai", "scale-ai"], probing the 5 shared hosts twice.
    res = ats.detect("Scale AI", http=recording_http, clock=clock, sleep=clock.sleep)
    assert res.ats == "unknown"

    by_host: dict[str, list[float]] = {}
    for host, timestamp in call_log:
        by_host.setdefault(host, []).append(timestamp)

    # First 6 probes hit 6 distinct hosts without sleeping; second slug hits boards-api.greenhouse.io
    # at t=50.6 (0.6s after its t=50.0 request) and sleeps 0.4s so second request fires at t=51.0.
    assert len(by_host["boards-api.greenhouse.io"]) == 2
    for host, stamps in by_host.items():
        for prev, curr in zip(stamps, stamps[1:]):
            assert curr - prev >= 1.0 - 1e-9, f"{host}: {stamps}"

    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] == pytest.approx(0.4)


def test_default_http_sets_user_agent_and_15_second_timeout() -> None:
    captured_requests: list[tuple[urllib.request.Request, float]] = []
    clock = FakeClock()

    class _FakeResponse:
        status = 200

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return _fixture_bytes("greenhouse")

    def fake_urlopen(req: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        captured_requests.append((req, timeout))
        return _FakeResponse()

    client = ats.HttpClient(urlopen=fake_urlopen, clock=clock, sleep=clock.sleep)
    result = ats.detect("Stripe", http=client)

    assert result.ats == "greenhouse"
    assert result.slug == "stripe"
    assert len(captured_requests) == 1
    req, timeout = captured_requests[0]
    assert timeout == 15
    expected_ua = f"whyline/{whyline.__version__} (personal job search)"
    assert req.get_header("User-agent") == expected_ua


def test_companies_check_and_cli_save_ats_slug_and_checked_at(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Checking before any companies exist is side-effect-free.
    assert companies.check("all") == []
    assert not paths.configured_home().exists()

    companies.add("Stripe", careers_url="https://stripe.com/jobs")
    companies.add("Linear", careers_url="https://jobs.ashbyhq.com/linear-app")
    companies.add("CustomSite", careers_url="https://customsite.example/careers")
    companies.add("UnknownCo")
    companies.add("RemovedCo")
    companies.remove("RemovedCo")

    # Add one suggested company as well to verify `all` checks accepted + suggested, skipping removed.
    store = companies._load_store()
    store["homeday"] = companies.Company(
        name="Homeday",
        status="suggested",
        reason="Berlin proptech",
        added_by="ai",
    )
    companies._write_private_companies(store)

    clock = FakeClock()
    probed_urls: list[str] = []

    def fake_http(url: str) -> bytes:
        probed_urls.append(url)
        if url == "https://boards-api.greenhouse.io/v1/boards/stripe/jobs":
            return _fixture_bytes("greenhouse")
        if url == "https://api.ashbyhq.com/posting-api/job-board/linear-app":
            return _fixture_bytes("ashby")
        if url == "https://homeday.recruitee.com/api/offers/":
            return _fixture_bytes("recruitee")
        raise _not_found(url)

    fixed_now = datetime.datetime(2026, 10, 29, 12, 0, 0, tzinfo=datetime.timezone.utc)

    # Check single company first.
    single = companies.check(
        "Stripe",
        http=fake_http,
        clock=clock,
        sleep=clock.sleep,
        now=fixed_now,
    )
    assert len(single) == 1
    assert single.ats == "greenhouse"
    assert single.slug == "stripe"
    assert single.checked_at == "2026-10-29T12:00:00+00:00"

    # Check all via CLI (`whyline jobs companies check` and `whyline jobs companies check <name>`).
    orig_check = companies.check
    monkeypatch.setattr(
        companies,
        "check",
        lambda name="all": orig_check(
            name,
            http=fake_http,
            clock=clock,
            sleep=clock.sleep,
            now=fixed_now,
        ),
    )

    code, out, err = _invoke_cli(["jobs", "companies", "check"], capsys)
    assert code == 0, err
    assert "Checked 5 companies" in out
    assert "greenhouse (stripe)" in out
    assert "ashby (linear-app)" in out
    assert "recruitee (homeday)" in out
    assert "careers_page" in out
    assert "unknown" in out
    assert "RemovedCo" not in out

    # RemovedCo was never probed.
    assert not any("removedco" in u for u in probed_urls)

    # Verify TOML persistence and 0600 permissions.
    toml_path = companies.companies_path()
    if os.name != "nt":
        assert (toml_path.stat().st_mode & 0o777) == 0o600
    parsed = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    assert parsed["stripe"]["ats"] == "greenhouse"
    assert parsed["stripe"]["slug"] == "stripe"
    assert parsed["stripe"]["checked_at"] == "2026-10-29T12:00:00+00:00"
    assert parsed["linear"]["ats"] == "ashby"
    assert parsed["linear"]["slug"] == "linear-app"
    assert parsed["customsite"]["ats"] == "careers_page"
    assert parsed["customsite"]["slug"] == ""
    assert parsed["unknownco"]["ats"] == "unknown"
    assert parsed["unknownco"]["slug"] == ""
    assert parsed["homeday"]["ats"] == "recruitee"
    assert parsed["homeday"]["slug"] == "homeday"
    assert parsed["homeday"]["status"] == "suggested"
    assert parsed["removedco"]["checked_at"] == ""

    # Single-company CLI check and --json output, plus unknown company error.
    code, json_out, err = _invoke_cli(["jobs", "companies", "check", "Linear", "--json"], capsys)
    assert code == 0, err
    rows = json.loads(json_out)
    assert len(rows) == 1
    assert rows[0]["name"] == "Linear"
    assert rows[0]["ats"] == "ashby"
    assert rows[0]["slug"] == "linear-app"

    code, out, err = _invoke_cli(["jobs", "companies", "check", "NoSuchCompany"], capsys)
    assert code == 1
    assert out == ""
    assert "not found" in err.lower()


def _invoke_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err
