"""Tests for the `jobs-fetch` step (JOB-12)."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from whyline import cli
from whyline.agents import before
from whyline.jobs import alerts, companies, fetch, seen, step

NOW = datetime(2026, 10, 30, 7, 0)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)


def _co(name: str, slug: str, ats: str = "greenhouse") -> companies.Company:
    return companies.Company(name=name, status="accepted", ats=ats, slug=slug)


def _board(count: int, start: int = 1) -> bytes:
    jobs = [
        {
            "id": start + i,
            "title": f"Engineer {start + i}",
            "location": {"name": "Remote"},
            "absolute_url": f"https://x.example/{start + i}",
            "updated_at": f"2026-10-{(i % 28) + 1:02d}T00:00:00Z",
            "content": "<p>Build things.</p>",
        }
        for i in range(count)
    ]
    return json.dumps({"jobs": jobs}).encode()


def _http(routes):
    def fake(url: str) -> bytes:
        for fragment, body in routes.items():
            if fragment in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise OSError(f"no route for {url}")

    return fake


def _use(monkeypatch, *entries: companies.Company) -> None:
    monkeypatch.setattr(step.companies, "list", lambda status=None: list(entries))


def test_writes_files_and_manifest_and_returns_count(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Acme", "acme"))
    out = tmp_path / "run"
    n = step.jobs_fetch(None, out, NOW, http=_http({"acme": _board(3)}))
    assert n == 3
    files = sorted(p.name for p in out.glob("*.md"))
    assert len(files) == 3 and files[0].startswith("01-acme-engineer-")
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest) == set(files)
    entry = manifest[files[0]]
    assert entry["uid"].startswith("greenhouse:acme:") and entry["company"] == "Acme"
    assert entry["url"].startswith("https://x.example/")
    # second run: everything already seen, nothing written
    again = tmp_path / "run2"
    assert step.jobs_fetch(None, again, NOW, http=_http({"acme": _board(3)})) == 0
    assert not (again / "manifest.json").exists()


def test_cap_of_40_leaves_the_rest_for_next_run(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Acme", "acme"))
    http = _http({"acme": _board(45)})
    assert step.jobs_fetch(None, tmp_path / "a", NOW, http=http) == 40
    assert len(list((tmp_path / "a").glob("*.md"))) == 40
    assert step.jobs_fetch(None, tmp_path / "b", NOW, http=http) == 5


def test_dry_run_marks_nothing_seen(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Acme", "acme"))
    http = _http({"acme": _board(2)})
    report = step.Report()
    assert step.jobs_fetch(None, tmp_path / "a", NOW, dry_run=True, http=http, report=report) == 2
    assert report.dry_run and report.companies["Acme"].new == 2
    assert step.jobs_fetch(None, tmp_path / "b", NOW, http=http) == 2


def test_failed_output_write_leaves_postings_new_for_retry(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Acme", "acme"))
    http = _http({"acme": _board(2)})
    real = step.json.dumps

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(step.json, "dumps", boom)
    with pytest.raises(OSError):
        step.jobs_fetch(None, tmp_path / "a", NOW, http=http)
    monkeypatch.setattr(step.json, "dumps", real)
    assert step.jobs_fetch(None, tmp_path / "b", NOW, http=http) == 2


def test_failed_dropped_write_leaves_chosen_new_and_retry_repairs_reasons(
    tmp_path, monkeypatch
) -> None:
    _use(monkeypatch, _co("Acme", "acme"), _co("Bad", "bad"))
    real_match = step.guard.match

    def match(posting, prefs):
        if posting.company == "Bad":
            return step.guard.Decision(False, "deal breaker: bad")
        return real_match(posting, prefs)

    monkeypatch.setattr(step.guard, "match", match)
    http = _http({"acme": _board(2), "bad": _board(2, start=10)})
    real_mark = seen.mark_dropped
    calls = {"n": 0}

    def flaky(uid, reason, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("db locked")
        real_mark(uid, reason, **kwargs)

    monkeypatch.setattr(step.seen, "mark_dropped", flaky)
    with pytest.raises(OSError):
        step.jobs_fetch(None, tmp_path / "a", NOW, http=http)
    monkeypatch.setattr(step.seen, "mark_dropped", real_mark)
    assert step.jobs_fetch(None, tmp_path / "b", NOW, http=http) == 2
    conn = seen._connect()
    try:
        rows = conn.execute(
            "SELECT dropped_reason FROM postings WHERE uid LIKE 'greenhouse:bad:%'"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("deal breaker: bad",)] * 2


def test_per_company_errors_are_reported(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Acme", "acme"), _co("Broken", "broken"))
    http = _http({"acme": _board(1), "broken": OSError("boom")})
    report = step.Report()
    assert step.jobs_fetch(None, tmp_path / "r", NOW, http=http, report=report) == 1
    assert report.companies["Broken"].errors == 1
    assert report.errors[0][0] == "Broken"
    assert any(line.startswith("Broken") for line in report.lines())


def test_preference_drops_are_recorded_with_reason(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Acme", "acme"))
    monkeypatch.setattr(step.profile, "load_preferences", lambda: {"deal_breakers": ["things"]})
    report = step.Report()
    http = _http({"acme": _board(2)})
    assert step.jobs_fetch(None, tmp_path / "r", NOW, http=http, report=report) == 0
    assert report.companies["Acme"].dropped == 2
    assert report.dropped[0][2] == "deal breaker: things"
    conn = seen._connect()
    try:
        rows = conn.execute("SELECT dropped_reason FROM postings").fetchall()
    finally:
        conn.close()
    assert rows == [("deal breaker: things",)] * 2


def test_unknown_boards_are_skipped(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Nowhere", "", ats="unknown"))
    report = step.Report()
    assert step.jobs_fetch(None, tmp_path / "r", NOW, http=_http({}), report=report) == 0
    assert report.errors == []


def test_registered_with_skip_when_empty() -> None:
    assert before.STEPS["jobs-fetch"].skip_when_empty is True


def test_cli_fetch_dry_run_shows_counts(monkeypatch, capsys) -> None:
    calls = []

    def fake_preview(*, dry_run, **_kw):
        calls.append(dry_run)
        report = step.Report(written=2, dry_run=dry_run)
        report.count("Acme").new = 2
        report.errors.append(("Broken", "boom"))
        report.count("Broken").errors = 1
        return report

    monkeypatch.setattr(step, "preview", fake_preview)
    assert cli.main(["jobs", "fetch", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert calls == [True]
    assert "Acme: 2 new, 0 dropped, 0 errors" in out
    assert "Broken: error: boom" in out


# --- alert jobs get the company's own board description (JOB-17) ---------------------------


def _card(title: str, company: str, link: str) -> fetch.Posting:
    card = fetch.Posting(
        uid=f"alert:a@b.c:{abs(hash(link))}", company=company, title=title, url=link,
        text="Found in a job-alert email from a@b.c. The full description is at the link.",
    )
    alerts._store([card])
    return card


def _board_of(slug: str, *titles: str) -> bytes:
    jobs = [
        {"id": 100 + i, "title": t, "location": {"name": "Remote"},
         "absolute_url": f"https://boards.greenhouse.io/{slug}/jobs/{100 + i}",
         "content": "<p>Full board description.</p>"}
        for i, t in enumerate(titles)
    ]
    return json.dumps({"jobs": jobs}).encode()


def test_alert_match_swaps_in_the_board_posting(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Acme Inc", "acme"))
    card = _card("Senior Backend Engineer", "ACME, Ltd.", "https://www.linkedin.com/jobs/view/1")
    http = _http({"acme": _board_of("acme", "Senior Backend Engineer (Remote)", "Designer")})
    out = tmp_path / "run"
    step.jobs_fetch(None, out, NOW, http=http)
    texts = [p.read_text() for p in out.glob("*.md")]
    assert len(texts) == 2 and all("Full board description." in t for t in texts)
    assert not any("Only the alert summary" in t or "linkedin" in t for t in texts)
    manifest = json.loads((out / "manifest.json").read_text())
    assert sum(m["title"].startswith("Senior Backend") for m in manifest.values()) == 1
    assert alerts.pending() == []
    assert seen.new_only([card]) == []  # the alert uid stays in the seen store
    board = fetch.Posting(uid="greenhouse:acme:100", company="Acme Inc", title="x")
    assert seen.new_only([board]) == []  # and so does the board uid


def test_alert_without_a_match_keeps_the_card_with_a_note(tmp_path, monkeypatch) -> None:
    _use(monkeypatch, _co("Acme", "acme"))
    _card("Quantum Chef", "Acme", "https://www.linkedin.com/jobs/view/2")
    out = tmp_path / "run"
    step.jobs_fetch(None, out, NOW, http=_http({"acme": _board_of("acme", "Designer")}))
    (text,) = [p.read_text() for p in out.glob("*quantum*.md")]
    assert "Found in a job-alert email" in text
    assert "Only the alert summary is available for this job." in text


def test_a_linkedin_link_is_never_requested(tmp_path, monkeypatch) -> None:
    _use(monkeypatch)
    _card("Anything", "Nobody", "https://www.linkedin.com/jobs/view/3")
    requested: list[str] = []

    def http(url: str) -> bytes:
        requested.append(url)
        raise OSError("no network")

    step.jobs_fetch(None, tmp_path / "run", NOW, http=http)
    assert requested == []


def test_a_board_link_is_fetched(tmp_path, monkeypatch) -> None:
    _use(monkeypatch)
    _card("Platform Engineer", "Zed Corp", "https://boards.greenhouse.io/zed/jobs/100?gh_src=x")
    requested: list[str] = []

    def http(url: str) -> bytes:
        requested.append(url)
        return _board_of("zed", "Platform Engineer")

    out = tmp_path / "run"
    step.jobs_fetch(None, out, NOW, http=http)
    assert requested and all("boards-api.greenhouse.io/v1/boards/zed/" in u for u in requested)
    (text,) = [p.read_text() for p in out.glob("*.md")]
    assert "Full board description." in text and "Only the alert summary" not in text
