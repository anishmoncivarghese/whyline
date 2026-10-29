from __future__ import annotations

import os
import sqlite3
import stat

import pytest

from whyline.jobs import seen
from whyline.jobs.fetch import Posting


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)


def _p(uid: str) -> Posting:
    return Posting(uid=uid, company="Acme", title="Eng", url=f"https://x/{uid}")


def test_repeated_uid_is_not_new() -> None:
    assert seen.new_only([_p("a"), _p("b")]) == ["a", "b"]
    assert seen.new_only([_p("b"), _p("c")]) == ["c"]
    assert seen.new_only([_p("a")]) == []


def test_duplicate_within_batch_counts_once() -> None:
    assert seen.new_only([_p("a"), _p("a")]) == ["a"]


def test_database_is_created_private() -> None:
    seen.new_only([_p("a")])
    path = seen.db_path()
    assert path.name == "jobs.sqlite"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_rows_and_dropped_reason() -> None:
    seen.new_only([_p("a")])
    seen.mark_dropped("a", "not remote")
    with sqlite3.connect(seen.db_path()) as conn:
        row = conn.execute(
            "SELECT uid, company, title, url, first_seen, last_seen, dropped_reason FROM postings"
        ).fetchone()
    assert row[:4] == ("a", "Acme", "Eng", "https://x/a")
    assert row[4] and row[5]
    assert row[6] == "not remote"
