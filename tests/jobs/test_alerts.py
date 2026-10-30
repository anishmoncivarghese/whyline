"""Tests for reading job-alert emails (JOB-16)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from whyline import cli
from whyline.agents import mail
from whyline.jobs import alerts, seen, step

FIXTURES = Path(__file__).parent / "fixtures"
LINKEDIN = "jobalerts-noreply@linkedin.com"
NOW = datetime(2026, 10, 30, 7, 0)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)


def _handle(name: str, **kw):
    return alerts.handle(FIXTURES / name, authserv="mx.google.com", **kw)


def test_senders_default_to_off() -> None:
    assert alerts.senders() == {a: False for a in alerts.DEFAULT_SENDERS}
    assert alerts.enabled_senders() == []


def test_linkedin_fixture_gives_its_cards() -> None:
    alerts.set_sender(LINKEDIN, True)
    result = _handle("alert_linkedin.eml")
    assert (result.cards, result.new, result.reason) == (3, 3, "")
    by_title = {p.title: p for p in alerts.pending()}
    assert set(by_title) == {"Senior Python Engineer", "Backend Developer", "Data Engineer"}
    first = by_title["Senior Python Engineer"]
    assert (first.company, first.location) == ("Acme Corp", "Berlin, Germany")
    assert first.url == "https://www.linkedin.com/comm/jobs/view/3901"
    assert first.uid.startswith(f"alert:{LINKEDIN}:")
    globex = by_title["Backend Developer"]
    assert (globex.company, globex.location, globex.remote) == ("Globex", "Remote", True)
    assert alerts.last_read()[0] == 3


def test_a_sender_that_is_off_is_ignored() -> None:
    result = _handle("alert_linkedin.eml")
    assert not result.accepted
    assert alerts.pending() == []


def test_forged_or_unauthenticated_sender_is_ignored(tmp_path) -> None:
    alerts.set_sender(LINKEDIN, True)
    text = (FIXTURES / "alert_linkedin.eml").read_text()
    forged = tmp_path / "forged.eml"
    forged.write_text(text.replace("dmarc=pass", "dmarc=fail").replace("dkim=pass", "dkim=fail"))
    assert not alerts.handle(forged, authserv="mx.google.com").accepted
    # An Authentication-Results header from some other server is not trusted.
    other = tmp_path / "other.eml"
    other.write_text(
        text.replace("Authentication-Results: mx.google.com", "Authentication-Results: evil.example")
    )
    assert not alerts.handle(other, authserv="mx.google.com").accepted
    # A DKIM pass for a domain that does not align with From is not enough.
    unaligned = tmp_path / "unaligned.eml"
    unaligned.write_text(
        text.replace("header.d=linkedin.com", "header.d=evil.example").replace("dmarc=pass", "dmarc=none")
    )
    assert not alerts.handle(unaligned, authserv="mx.google.com").accepted
    assert alerts.pending() == []
    assert alerts.last_read() is None


def test_authserv_must_be_set(monkeypatch) -> None:
    alerts.set_sender(LINKEDIN, True)
    monkeypatch.setattr(alerts, "_configured_authserv", lambda: None)
    result = alerts.handle(FIXTURES / "alert_linkedin.eml")
    assert result.reason == alerts.AUTHSERV_UNSET


def test_a_repeated_email_gives_nothing_new() -> None:
    alerts.set_sender(LINKEDIN, True)
    assert _handle("alert_linkedin.eml").new == 3
    again = _handle("alert_linkedin.eml")
    assert (again.cards, again.new) == (3, 0)
    assert len(alerts.pending()) == 3


def test_a_failed_inbox_write_can_be_retried_into_pending(monkeypatch) -> None:
    alerts.set_sender(LINKEDIN, True)
    real = alerts._store

    def boom(postings):
        raise OSError("disk full")

    monkeypatch.setattr(alerts, "_store", boom)
    with pytest.raises(OSError):
        _handle("alert_linkedin.eml")
    assert alerts.pending() == []
    monkeypatch.setattr(alerts, "_store", real)
    retry = _handle("alert_linkedin.eml")
    assert retry.new == 3
    assert len(alerts.pending()) == 3


def test_cards_are_recorded_in_the_seen_store() -> None:
    alerts.set_sender(LINKEDIN, True)
    _handle("alert_linkedin.eml")
    posts = alerts.pending()
    assert seen.new_only(posts) == []


def test_generic_fallback_collects_links_that_look_like_titles() -> None:
    alerts.set_sender("alert@indeed.com", True)
    result = _handle("alert_generic.eml")
    assert result.cards == 2
    titles = {p.title: p for p in alerts.pending()}
    assert set(titles) == {"Staff Platform Engineer", "Product Designer"}
    staff = titles["Staff Platform Engineer"]
    assert (staff.company, staff.location) == ("Hooli", "Remote - EU")
    assert staff.url.startswith("https://example.org/j/1")


def test_settings_file_is_private_and_round_trips() -> None:
    alerts.set_sender("Alert@Indeed.com", True)
    assert alerts.senders()["alert@indeed.com"] is True
    assert (alerts.settings_path().stat().st_mode & 0o777) == 0o600
    with pytest.raises(alerts.AlertError):
        alerts.set_sender("not an address", True)


def test_cards_reach_the_next_fetch_and_empty_the_inbox(tmp_path, monkeypatch) -> None:
    alerts.set_sender(LINKEDIN, True)
    _handle("alert_linkedin.eml")
    monkeypatch.setattr(step.companies, "list", lambda status=None: [])
    out = tmp_path / "run"
    assert step.jobs_fetch(None, out, NOW) == 3
    manifest = json.loads((out / step.MANIFEST).read_text())
    assert {m["title"] for m in manifest.values()} == {
        "Senior Python Engineer", "Backend Developer", "Data Engineer",
    }
    assert alerts.pending() == []
    assert step.jobs_fetch(None, tmp_path / "run2", NOW) == 0


def test_a_dry_run_leaves_the_inbox(tmp_path, monkeypatch) -> None:
    alerts.set_sender(LINKEDIN, True)
    _handle("alert_linkedin.eml")
    monkeypatch.setattr(step.companies, "list", lambda status=None: [])
    assert step.jobs_fetch(None, tmp_path / "run", NOW, dry_run=True) == 3
    assert len(alerts.pending()) == 3


def test_jobs_alert_command_runs_handle(capsys, monkeypatch) -> None:
    alerts.set_sender(LINKEDIN, True)
    monkeypatch.setattr(alerts, "_configured_authserv", lambda: "mx.google.com")
    assert cli.main(["jobs", "alert", str(FIXTURES / "alert_linkedin.eml")]) == 0
    assert "Read 3 job cards" in capsys.readouterr().out
    assert len(alerts.pending()) == 3


def test_jobs_alert_command_reports_an_unreadable_file(tmp_path) -> None:
    assert cli.main(["jobs", "alert", str(tmp_path / "missing.eml")]) == 1


def test_mail_script_runs_jobs_alert_not_agents_trigger() -> None:
    text = mail.script_text("job-alerts", "/opt/bin/whyline", ("jobs", "alert"))
    assert '"/opt/bin/whyline jobs alert " & quoted form of tmp' in text
    assert "agents trigger" not in text
    assert "open for access" in text


def test_alerts_mail_script_command_installs_job_alerts(capsys, monkeypatch) -> None:
    monkeypatch.setattr(mail, "_whyline_path", lambda: "/opt/bin/whyline")
    monkeypatch.setattr(mail, "supported", lambda: True)
    assert cli.main(["jobs", "alerts", "mail-script"]) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.name == "whyline-job-alerts.applescript"
    assert "jobs alert " in path.read_text()
