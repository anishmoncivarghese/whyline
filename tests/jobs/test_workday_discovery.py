"""JOB-31: finding a company's Workday board."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from whyline import account
from whyline.jobs import ats, companies

_WD_OK = b'{"total": 1, "jobPostings": [{"title": "Engineer", "externalPath": "/job/x"}]}'


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _ExecResult:
    def __init__(self, exit_code: int, output: str) -> None:
        self.exit_code = exit_code
        self.output = output


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setattr(account.paths, "global_whyline_dir", lambda: home_dir / ".whyline")
    return home_dir


def _not_found(url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b""))  # type: ignore[arg-type]


def _world(
    page: bytes | None,
    *,
    careers_robots: bytes = b"",
    workday_ok: tuple[str, ...] = ("acme",),
) -> tuple[Any, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def transport(url: str, method: str = "GET", body: bytes | None = None) -> bytes:
        calls.append({"url": url, "method": method, "body": body})
        parts = urllib.parse.urlsplit(url)
        if parts.path == "/robots.txt":
            return careers_robots if parts.hostname == "careers.acme.example" else b""
        if method == "POST":
            tenant = (parts.hostname or "").split(".")[0]
            if tenant in workday_ok:
                return _WD_OK
            raise _not_found(url)
        if parts.hostname == "careers.acme.example" and page is not None:
            return page
        raise _not_found(url)

    return transport, calls


def _detect(name: str, careers_url: str, transport: Any) -> Any:
    clock = _Clock()
    return ats.detect(name, careers_url=careers_url, http=transport, clock=clock, sleep=clock.sleep)


def _posts(calls: list[dict[str, Any]]) -> list[str]:
    return [c["url"] for c in calls if c["method"] == "POST"]


def test_direct_workday_careers_url_is_detected_with_a_limit_one_probe() -> None:
    transport, calls = _world(None)
    res = _detect("Acme", "https://acme.wd1.myworkdayjobs.com/en-US/Careers", transport)
    assert res == ("workday", "acme/wd1/Careers")
    assert _posts(calls) == ["https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"]
    post = next(c for c in calls if c["method"] == "POST")
    assert json.loads(post["body"])["limit"] == 1


def test_careers_page_linking_to_workday_is_detected_and_lookalike_host_ignored() -> None:
    page = (
        b'<a href="https://acme.wd1.myworkdayjobs.com.evil.example/Fake">x</a>'
        b'<a href="https://evil.example/acme.wd1.myworkdayjobs.com/Fake">y</a>'
        b'<a href="https://acme.wd5.myworkdayjobs.com/en-US/Real_Site">Jobs</a>'
    )
    transport, calls = _world(page)
    res = _detect("Acme", "https://careers.acme.example/jobs", transport)
    assert res == ("workday", "acme/wd5/Real_Site")
    assert _posts(calls) == ["https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Real_Site/jobs"]


def test_workday_link_in_an_inline_script_is_found() -> None:
    page = b'<script>var board = "https:\\/\\/acme.wd3.myworkdayjobs.com\\/Acme_Jobs";</script>'
    transport, _ = _world(page)
    res = _detect("Acme", "https://careers.acme.example/jobs", transport)
    assert res == ("workday", "acme/wd3/Acme_Jobs")


def test_page_without_workday_link_falls_through_to_careers_page() -> None:
    transport, calls = _world(b'<a href="/jobs/1">Engineer</a>')
    res = _detect("Acme", "https://careers.acme.example/jobs", transport)
    assert res == ("careers_page", "")
    assert _posts(calls) == []


def test_unreachable_careers_page_falls_through_to_careers_page() -> None:
    transport, _ = _world(None)
    assert _detect("Acme", "https://careers.acme.example/jobs", transport) == ("careers_page", "")


def test_no_careers_url_is_unknown_and_never_scans() -> None:
    transport, calls = _world(b"")
    assert _detect("Acme", "", transport) == ("unknown", "")
    assert all(urllib.parse.urlsplit(c["url"]).hostname != "careers.acme.example" for c in calls)


def test_at_most_three_workday_probes() -> None:
    links = "".join(
        f'<a href="https://t{n}.wd1.myworkdayjobs.com/Site">x</a>' for n in range(6)
    ).encode()
    transport, calls = _world(links, workday_ok=())
    assert _detect("Acme", "https://careers.acme.example/jobs", transport) == ("careers_page", "")
    assert len(_posts(calls)) == 3


def test_robots_disallowing_the_careers_page_stops_the_scan() -> None:
    transport, calls = _world(
        b'<a href="https://acme.wd1.myworkdayjobs.com/Careers">Jobs</a>',
        careers_robots=b"User-agent: *\nDisallow: /jobs\n",
    )
    assert _detect("Acme", "https://careers.acme.example/jobs", transport) == ("careers_page", "")
    assert _posts(calls) == []
    assert "https://careers.acme.example/jobs" not in [c["url"] for c in calls]


def test_failed_direct_workday_url_is_unknown_not_careers_page() -> None:
    transport, calls = _world(None, workday_ok=())
    res = _detect("Acme", "https://acme.wd1.myworkdayjobs.com/en-US/Careers", transport)
    assert res == ("unknown", "")
    assert len(_posts(calls)) == 1


def test_careers_page_redirect_to_another_allowlisted_host_is_refused() -> None:
    import urllib.request

    target = "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"
    request = urllib.request.Request("https://careers.acme.example/jobs")
    strict = ats._SafeRedirectHandler(
        careers_url="https://careers.acme.example/jobs", same_host=True
    )
    with pytest.raises(ats.AtsError):
        strict.redirect_request(request, None, 302, "Found", {}, target)
    same = strict.redirect_request(request, None, 302, "Found", {}, "/jobs/2")
    assert same is not None
    assert same.full_url == "https://careers.acme.example/jobs/2"
    loose = ats._SafeRedirectHandler(careers_url="https://careers.acme.example/jobs")
    assert loose.redirect_request(request, None, 302, "Found", {}, target) is not None


def test_suggest_prompt_mentions_myworkdayjobs() -> None:
    account.save_global(
        {name: {"enabled": name == "claude", "available": True} for name in account.AGENT_ORDER}
    )
    prompts: list[str] = []

    def fake(command: list[str], prompt: str, **kwargs: Any) -> _ExecResult:
        prompts.append(prompt)
        answer = "```companies\n[]\n```"
        return _ExecResult(
            0, json.dumps({"type": "result", "result": answer, "permission_denials": []})
        )

    companies.suggest(run_fn=fake)
    assert len(prompts) == 1
    assert "myworkdayjobs.com" in prompts[0]
    assert "Greenhouse" in prompts[0] and "Lever" in prompts[0]


def test_readding_a_company_with_a_workday_link_then_checking_records_workday() -> None:
    companies.add("Acme", careers_url="https://acme.example/jobs")

    def offline(url: str) -> bytes:
        raise OSError("offline")

    first = companies.check("Acme", http=offline)
    assert (first.ats, first.slug) == ("careers_page", "")

    readded = companies.add("Acme", careers_url="https://acme.wd1.myworkdayjobs.com/en-US/Careers")
    assert (readded.ats, readded.slug, readded.checked_at) == ("unknown", "", "")
    assert readded.status == "accepted"

    def transport(url: str, method: str = "GET", body: bytes | None = None) -> bytes:
        if url.endswith("/robots.txt"):
            return b""
        if method == "POST":
            return b'{"total": 1, "jobPostings": [{"title": "Engineer"}]}'
        raise OSError("offline")

    second = companies.check("Acme", http=transport)
    assert (second.ats, second.slug) == ("workday", "acme/wd1/Careers")
    assert companies.list()[0].ats == "workday"
