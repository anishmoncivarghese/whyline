from __future__ import annotations

from pathlib import Path

import pytest

from whyline.jobs import careers_page, companies, fetch

FIXTURES = Path(__file__).parent / "fixtures"
HOME = "https://careers.acme.test/careers"
ROBOTS_OK = b"User-agent: *\nDisallow: /private\n"


def _fx(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _co() -> companies.Company:
    return companies.Company(
        name="Acme", status="accepted", ats="careers_page", careers_url=HOME
    )


def _http(routes: dict[str, bytes]):
    seen: list[str] = []

    def fake(url: str) -> bytes:
        seen.append(url)
        if url in routes:
            return routes[url]
        raise OSError(f"no route for {url}")

    fake.seen = seen  # type: ignore[attr-defined]
    return fake


def _run(routes: dict[str, bytes]):
    http = _http(routes)
    return fetch.board_jobs(_co(), http=http, sleep=lambda _s: None), http


def test_single_json_ld_posting_and_same_host_job_link() -> None:
    page = _fx("careers_single.html")
    jobs, http = _run(
        {
            "https://careers.acme.test/robots.txt": ROBOTS_OK,
            HOME: page,
            "https://careers.acme.test/jobs/42": page,
        }
    )
    assert http.seen == [
        "https://careers.acme.test/robots.txt",
        HOME,
        "https://careers.acme.test/jobs/42",
    ]
    (job,) = jobs
    assert job.uid == "careers_page:careers.acme.test:42"
    assert (job.company, job.title, job.location) == ("Acme", "Engineer", "Berlin, DE")
    assert job.remote is True
    assert job.posted_at == "2026-10-01"
    assert job.text == "Build things."


def test_graph_json_ld_postings() -> None:
    jobs, _ = _run(
        {"https://careers.acme.test/robots.txt": ROBOTS_OK, HOME: _fx("careers_graph.html")}
    )
    assert [j.title for j in jobs] == ["Designer", "Analyst"]
    assert jobs[0].text == "Design."


def test_robots_disallow_stops_before_fetching_the_page() -> None:
    http = _http(
        {
            "https://careers.acme.test/robots.txt": b"User-agent: *\nDisallow: /careers\n",
            HOME: _fx("careers_graph.html"),
        }
    )
    with pytest.raises(fetch.FetchError, match="robots.txt disallows this page"):
        fetch.board_jobs(_co(), http=http, sleep=lambda _s: None)
    assert HOME not in http.seen


def test_off_host_link_is_ignored() -> None:
    page = _fx("careers_single.html")
    _, http = _run(
        {
            "https://careers.acme.test/robots.txt": ROBOTS_OK,
            HOME: page,
            "https://careers.acme.test/jobs/42": page,
        }
    )
    assert not any("other.example" in url for url in http.seen)


def test_job_links_are_capped_at_twenty() -> None:
    links = "".join(f'<a href="/jobs/{n}">j</a>' for n in range(30)).encode()
    routes = {"https://careers.acme.test/robots.txt": ROBOTS_OK, HOME: b"<html>" + links}
    routes.update({f"https://careers.acme.test/jobs/{n}": _fx("careers_graph.html") for n in range(30)})
    jobs, http = _run(routes)
    assert len(http.seen) == 2 + 20
    assert len(jobs) == 2


def test_response_over_two_megabytes_is_cut_off() -> None:
    head = _fx("careers_graph.html")
    filler = b"<!-- " + b"x" * (careers_page.MAX_BYTES + 10) + b" -->"
    late = b'<script type="application/ld+json">{"@type":"JobPosting","title":"Late"}</script>'
    jobs, _ = _run(
        {
            "https://careers.acme.test/robots.txt": ROBOTS_OK,
            HOME: head + filler + late,
        }
    )
    assert [j.title for j in jobs] == ["Designer", "Analyst"]


def test_page_with_no_json_ld_needs_a_browser() -> None:
    with pytest.raises(fetch.FetchError) as caught:
        _run({"https://careers.acme.test/robots.txt": ROBOTS_OK, HOME: _fx("careers_none.html")})
    assert str(caught.value) == "No machine-readable jobs found: this page needs a browser"


def test_missing_robots_txt_allows_the_page() -> None:
    jobs, _ = _run({HOME: _fx("careers_graph.html")})
    assert len(jobs) == 2
