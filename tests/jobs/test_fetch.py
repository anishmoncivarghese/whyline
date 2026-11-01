from __future__ import annotations

import json
from pathlib import Path

import pytest

from whyline.jobs import ats, companies, fetch

FIXTURES = Path(__file__).parent / "fixtures"


def _fx(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _co(name: str, board: str, slug: str = "acme") -> companies.Company:
    return companies.Company(name=name, status="accepted", ats=board, slug=slug)


def _http(routes: dict[str, bytes]):
    seen: list[str] = []

    def fake(url: str) -> bytes:
        seen.append(url)
        for fragment, body in routes.items():
            if fragment in url:
                return body
        raise OSError(f"no route for {url}")

    fake.seen = seen  # type: ignore[attr-defined]
    return fake


def _fetch(board: str, routes: dict[str, bytes], slug: str = "acme") -> list[fetch.Posting]:
    return fetch.board_jobs(
        _co("Acme", board, slug), http=_http(routes), sleep=lambda _s: None
    )


def test_greenhouse_unescapes_and_strips_content() -> None:
    http = _http({"greenhouse.io": _fx("fetch_greenhouse.json")})
    jobs = fetch.board_jobs(_co("Acme", "greenhouse"), http=http, sleep=lambda _s: None)
    assert http.seen == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"]
    first = jobs[0]
    assert first.uid == "greenhouse:acme:4001"
    assert (first.company, first.title, first.location) == ("Acme", "Staff Engineer", "Berlin, Germany")
    assert first.url.endswith("/4001")
    assert first.text == "Build great things.\n\n- Python\n- SQL"


def test_lever() -> None:
    (job,) = _fetch("lever", {"lever.co": _fx("fetch_lever.json")})
    assert job.uid == "lever:acme:abc-123"
    assert job.remote is True
    assert job.location == "Remote - EU"
    assert job.posted_at.startswith("2025-10-0")
    assert job.text == "Own the API.\n\nShip weekly."


def test_ashby() -> None:
    (job,) = _fetch("ashby", {"ashbyhq.com": _fx("fetch_ashby.json")})
    assert job.uid == "ashby:acme:ash-1"
    assert job.remote is False
    assert job.text == "Role\n\nMove data.\nFast."


def test_workable() -> None:
    (job,) = _fetch("workable", {"workable.com": _fx("fetch_workable.json")})
    assert job.uid == "workable:acme:WK1"
    assert job.location == "Lisbon, Portugal"
    assert job.remote is True
    assert job.posted_at == "2026-10-21"
    assert job.text == "Lead the team.\n\nBe kind."


def test_smartrecruiters_reads_detail_for_text() -> None:
    (job,) = _fetch(
        "smartrecruiters",
        {
            "postings/sr-77": _fx("fetch_smartrecruiters_detail.json"),
            "postings": _fx("fetch_smartrecruiters_list.json"),
        },
    )
    assert job.uid == "smartrecruiters:acme:sr-77"
    assert job.location == "Paris, FR"
    assert job.remote is True
    assert job.url == "https://jobs.smartrecruiters.com/Acme/sr-77"
    assert job.text == "Define the roadmap.\n\n- 5 years"


def test_recruitee() -> None:
    (job,) = _fetch("recruitee", {"recruitee.com": _fx("fetch_recruitee.json")})
    assert job.uid == "recruitee:acme:9001"
    assert job.remote is True
    assert job.text == "Break things & report."


def test_html_is_stripped() -> None:
    text = fetch.html_to_text("<div>a<script>x()</script><b>b</b></div><p>c&nbsp;d</p>")
    assert "<" not in text and "x()" not in text
    assert text == "ab\n\nc d"


def test_missing_fields_are_handled() -> None:
    jobs = _fetch("greenhouse", {"greenhouse.io": _fx("fetch_greenhouse.json")})
    bare = jobs[1]
    assert bare.uid == "greenhouse:acme:4002"
    assert (bare.location, bare.url, bare.posted_at, bare.text) == ("", "", "", "")
    assert bare.remote is None
    md = bare.to_markdown()
    assert "Location: not stated" in md and "Posted: unknown" in md


def test_to_markdown_has_header_then_text() -> None:
    posting = fetch.Posting(
        uid="x", company="Acme", title="Dev", location="Rome", url="https://u", posted_at="2026-10-01", text="Body"
    )
    md = posting.to_markdown()
    assert md.startswith("# Dev")
    for line in ("Company: Acme", "Title: Dev", "Location: Rome", "URL: https://u", "Posted: 2026-10-01"):
        assert line in md
    assert md.rstrip().endswith("Body")


def test_failing_company_does_not_stop_others() -> None:
    http = _http({"api.lever.co": _fx("fetch_lever.json"), "recruitee.com": _fx("fetch_recruitee.json")})
    entries = [
        _co("Broken", "greenhouse", "nope"),
        _co("Lever Co", "lever"),
        _co("No Board", "unknown", ""),
        _co("Rec Co", "recruitee"),
    ]
    result = fetch.fetch_all(entries, http=http, sleep=lambda _s: None)
    assert [p.uid for p in result.postings] == ["lever:acme:abc-123", "recruitee:acme:9001"]
    assert [name for name, _ in result.errors] == ["Broken", "No Board"]


def test_allowlist_is_enforced() -> None:
    called: list[str] = []
    entry = _co("Evil", "recruitee", "bad/host")
    with pytest.raises(fetch.FetchError):
        fetch.board_jobs(entry, http=lambda url: called.append(url) or b"{}", sleep=lambda _s: None)
    assert called == []


def test_rate_limit_and_user_agent_apply() -> None:
    sleeps: list[float] = []
    seen_headers: list[dict[str, str]] = []

    def transport(url: str, headers: dict[str, str]) -> bytes:
        seen_headers.append(headers)
        return _fx("fetch_smartrecruiters_list.json") if url.endswith("/postings") else _fx(
            "fetch_smartrecruiters_detail.json"
        )

    fetch.board_jobs(
        _co("Acme", "smartrecruiters"),
        http=transport,
        clock=lambda: 0.0,
        sleep=sleeps.append,
    )
    assert sleeps == [ats.RATE_LIMIT_SECONDS]
    assert all(h["User-Agent"] == ats.user_agent() for h in seen_headers)


# --- Workday (JOB-30) ---------------------------------------------------------

_WD_SLUG = "acme/wd1/Careers"
_WD_BASE = "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Careers"


def _wdfx(name: str) -> bytes:
    return (FIXTURES / "workday" / name).read_bytes()


def _wd_job(i: int) -> dict:
    return {
        "title": f"Engineer {i}",
        "externalPath": f"/job/Remote/Engineer-{i}_R{i}",
        "locationsText": "Remote, US",
        "postedOn": "Posted 3 Days Ago",
        "bulletFields": [f"R{i}"],
    }


class _WdStub:
    """Workday transport: serves list pages from `jobs`, details from `detail`."""

    def __init__(self, jobs: list[dict], fail_detail: bool = False) -> None:
        self.jobs = jobs
        self.fail_detail = fail_detail
        self.posts: list[dict] = []
        self.details: list[str] = []

    def __call__(self, url, headers=None, method="GET", body=None):
        if url.endswith("/robots.txt"):
            return b"User-agent: *\nAllow: /\n"
        if method == "POST":
            req = json.loads(body)
            self.posts.append(req)
            page = self.jobs[req["offset"] : req["offset"] + req["limit"]]
            return json.dumps({"total": len(self.jobs), "jobPostings": page}).encode()
        self.details.append(url)
        if self.fail_detail:
            raise OSError("boom")
        return _wdfx("detail.json")


@pytest.fixture
def _wd_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)


def _wd_fetch(stub, slug: str = _WD_SLUG):
    return fetch.board_jobs(_co("Acme", "workday", slug), http=stub, sleep=lambda _s: None)


def test_workday_two_pages_then_empty_page_stops(_wd_home) -> None:
    pages = [_wdfx("list_page1.json"), _wdfx("list_page2.json"), _wdfx("list_empty.json")]
    posts: list[dict] = []

    def stub(url, headers=None, method="GET", body=None):
        if url.endswith("/robots.txt"):
            return b""
        if method == "POST":
            posts.append(json.loads(body))
            return pages[len(posts) - 1]
        return _wdfx("detail.json")

    jobs = _wd_fetch(stub)
    assert [p["offset"] for p in posts] == [0, 20, 40]
    assert posts[0] == {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    assert [j.uid for j in jobs] == [f"workday:{_WD_SLUG}:R{i}" for i in (1, 2, 3)]
    first = jobs[0]
    assert first.title == "Engineer 1"
    assert first.location == "Remote, US"
    assert first.url == "https://acme.wd1.myworkdayjobs.com/Careers/job/Remote/Engineer-1_R1"
    assert first.posted_at == "Posted 3 Days Ago"


def test_workday_stops_at_total(_wd_home) -> None:
    stub = _WdStub([_wd_job(i) for i in range(1, 4)])
    assert len(_wd_fetch(stub)) == 3
    assert len(stub.posts) == 1


def test_workday_caps_list_at_200(_wd_home) -> None:
    stub = _WdStub([_wd_job(i) for i in range(1, 251)])
    assert len(_wd_fetch(stub)) == 200
    assert len(stub.posts) == 10


def test_workday_detail_text_reaches_posting(_wd_home) -> None:
    stub = _WdStub([_wd_job(1)])
    job = _wd_fetch(stub)[0]
    assert "Build things." in job.text
    assert "- Python" in job.text
    assert job.remote is True
    assert stub.details == [f"{_WD_BASE}/job/Remote/Engineer-1_R1"]


def test_workday_detail_cap_and_report_line(_wd_home) -> None:
    stub = _WdStub([_wd_job(i) for i in range(1, 46)])
    jobs = _wd_fetch(stub)
    assert len(stub.details) == 40
    assert [bool(j.text) for j in jobs] == [True] * 40 + [False] * 5
    assert jobs.notes == ["Acme: 5 more Workday jobs will be read on the next run"]


def test_workday_fetch_all_carries_report_line(_wd_home) -> None:
    stub = _WdStub([_wd_job(i) for i in range(1, 43)])
    result = fetch.fetch_all([_co("Acme", "workday", _WD_SLUG)], http=stub, sleep=lambda _s: None)
    assert len(result.postings) == 42
    assert result.notes == ("Acme: 2 more Workday jobs will be read on the next run",)


def test_workday_failed_detail_keeps_posting_with_note(_wd_home) -> None:
    job = _wd_fetch(_WdStub([_wd_job(1)], fail_detail=True))[0]
    assert job.title == "Engineer 1"
    assert job.text == "Only the job title and location are available for this job."


def test_workday_seen_jobs_get_no_detail_request(_wd_home) -> None:
    from whyline.jobs import seen

    stub = _WdStub([_wd_job(1), _wd_job(2)])
    seen.new_only([fetch.Posting(uid=f"workday:{_WD_SLUG}:R1", company="Acme", title="Engineer 1")])
    jobs = _wd_fetch(stub)
    assert len(jobs) == 2
    assert stub.details == [f"{_WD_BASE}/job/Remote/Engineer-2_R2"]
    assert jobs[0].text == ""


def test_workday_malformed_list_names_company(_wd_home) -> None:
    def stub(url, headers=None, method="GET", body=None):
        return b"" if url.endswith("/robots.txt") else b'{"unexpected": true}'

    with pytest.raises(fetch.FetchError, match="Acme"):
        _wd_fetch(stub)
