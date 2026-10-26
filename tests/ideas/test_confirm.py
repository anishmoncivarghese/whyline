"""Confirmation codes are random, bound to a subject, and one-shot."""

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from whyline.ideas import confirm, store


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _kv_map(conn):
    return {
        row["key"]: row["value"]
        for row in conn.execute("SELECT key, value FROM kv")
    }


def _issue(conn, **overrides):
    kwargs = {
        "scope": "email",
        "subject": "idea:12:rev:4",
        "actor": "alice@example.com",
    }
    kwargs.update(overrides)
    return confirm.issue(conn, **kwargs)


def test_two_issues_differ(conn):
    first = _issue(conn)
    second = _issue(conn, subject="idea:12:rev:5")
    assert first != second
    assert len(first) == 8
    assert len(second) == 8
    for code in (first, second):
        assert code == code.lower()
        assert code.isalnum()
        for lookalike in "01ilo":
            assert lookalike not in code
        predictable = sha256(b"whyline-email:12:4").hexdigest()[:8]
        assert code != predictable
    raw = conn.execute(
        "SELECT value FROM kv WHERE key = ?", (f"confirm:{first}",)
    ).fetchone()[0]
    data = json.loads(raw)
    assert data["scope"] == "email"
    assert data["subject"] == "idea:12:rev:4"
    assert data["actor"] == "alice@example.com"
    expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    assert now < expires <= now + timedelta(minutes=31)


def test_wrong_code_fails_and_changes_nothing(conn):
    kept = _issue(conn)
    before = _kv_map(conn)
    assert (
        confirm.consume(
            conn,
            "zzzzzzzz",
            scope="email",
            subject="idea:12:rev:4",
            actor="alice@example.com",
        )
        is False
    )
    assert _kv_map(conn) == before
    assert (
        confirm.consume(
            conn,
            kept,
            scope="email",
            subject="idea:12:rev:4",
            actor="alice@example.com",
        )
        is True
    )


def test_wrong_actor_fails_and_changes_nothing(conn):
    code = _issue(conn)
    before = _kv_map(conn)
    assert (
        confirm.consume(
            conn,
            code,
            scope="email",
            subject="idea:12:rev:4",
            actor="bob@example.com",
        )
        is False
    )
    assert _kv_map(conn) == before


def test_wrong_scope_fails_and_changes_nothing(conn):
    code = _issue(conn)
    before = _kv_map(conn)
    assert (
        confirm.consume(
            conn,
            code,
            scope="telegram",
            subject="idea:12:rev:4",
            actor="alice@example.com",
        )
        is False
    )
    assert _kv_map(conn) == before


def test_wrong_subject_fails_and_changes_nothing(conn):
    code = _issue(conn)
    before = _kv_map(conn)
    assert (
        confirm.consume(
            conn,
            code,
            scope="email",
            subject="idea:12:rev:5",
            actor="alice@example.com",
        )
        is False
    )
    assert _kv_map(conn) == before


def test_expired_code_fails_and_changes_nothing(conn):
    code = _issue(conn, ttl_minutes=30)
    before = _kv_map(conn)
    later = datetime.now(timezone.utc) + timedelta(minutes=31)
    assert (
        confirm.consume(
            conn,
            code,
            scope="email",
            subject="idea:12:rev:4",
            actor="alice@example.com",
            now=later,
        )
        is False
    )
    assert _kv_map(conn) == before


def test_second_use_fails_and_changes_nothing(conn):
    code = _issue(conn)
    assert (
        confirm.consume(
            conn,
            code,
            scope="email",
            subject="idea:12:rev:4",
            actor="alice@example.com",
        )
        is True
    )
    after = _kv_map(conn)
    assert f"confirm:{code}" not in after
    assert (
        confirm.consume(
            conn,
            code,
            scope="email",
            subject="idea:12:rev:4",
            actor="alice@example.com",
        )
        is False
    )
    assert _kv_map(conn) == after
