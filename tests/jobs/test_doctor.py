"""Tests for the job-search setup check, with every probe stubbed."""

from __future__ import annotations

from types import SimpleNamespace

from whyline.jobs import doctor, profile


def _file(exists: bool) -> SimpleNamespace:
    return SimpleNamespace(exists=exists)


def _good(**over):
    agent = SimpleNamespace(runner="claude", backup=("codex",), agent_id="personal:job-search")
    stubs = dict(
        statuses_fn=lambda: {
            profile.CV_FILE: _file(True),
            profile.PROFILE_FILE: _file(True),
            profile.RUBRIC_FILE: _file(True),
        },
        companies_fn=lambda: [SimpleNamespace(ats="greenhouse")],
        find_agent_fn=lambda: agent,
        agent_status_fn=lambda defn: "active",
        enabled_fn=lambda: ["claude"],
        unattended_fn=lambda cli: True,
        scheduler_fn=lambda: True,
        delivery_fn=lambda agent_id: SimpleNamespace(empty=False),
    )
    stubs.update(over)
    return doctor.check(**stubs)


def _by_name(rows):
    return {row.name: row for row in rows}


def _boom():
    raise RuntimeError("boom")


def test_everything_ready_is_all_ok_with_no_fix_sentences() -> None:
    rows = _good()
    assert [row.name for row in rows] == [
        "CV", "Profile and rubric", "Companies", "Agent", "Runner", "Scheduler", "Delivery",
    ]
    assert {row.state for row in rows} == {doctor.OK}
    assert all(row.fix == "" for row in rows)


def test_cv_row_fails_without_a_cv() -> None:
    row = _by_name(_good(statuses_fn=lambda: {profile.CV_FILE: _file(False)}))["CV"]
    assert row.state == doctor.FAIL and row.fix


def test_profile_row_needs_both_profile_and_rubric() -> None:
    files = {profile.CV_FILE: _file(True), profile.PROFILE_FILE: _file(True)}
    row = _by_name(_good(statuses_fn=lambda: files))["Profile and rubric"]
    assert row.state == doctor.FAIL and row.fix


def test_companies_row_needs_an_accepted_company_with_a_known_board() -> None:
    unknown = _by_name(_good(companies_fn=lambda: [SimpleNamespace(ats="unknown")]))["Companies"]
    none = _by_name(_good(companies_fn=lambda: []))["Companies"]
    assert unknown.state == none.state == doctor.FAIL
    assert unknown.fix and none.fix


def test_agent_row_fails_when_missing_or_not_accepted() -> None:
    assert _by_name(_good(find_agent_fn=_boom))["Agent"].state == doctor.FAIL
    for status in ("not accepted", "needs_review"):
        row = _by_name(_good(agent_status_fn=lambda defn, s=status: s))["Agent"]
        assert row.state == doctor.FAIL and row.fix


def test_runner_row_accepts_a_backup_and_fails_when_none_is_cleared() -> None:
    backup = _by_name(_good(enabled_fn=lambda: ["codex"]))["Runner"]
    assert backup.state == doctor.OK and "codex" in backup.detail
    off = _by_name(_good(enabled_fn=lambda: []))["Runner"]
    held = _by_name(_good(unattended_fn=lambda cli: False))["Runner"]
    assert off.state == held.state == doctor.FAIL and off.fix


def test_scheduler_row_warns_when_not_loaded() -> None:
    row = _by_name(_good(scheduler_fn=lambda: False))["Scheduler"]
    assert row.state == doctor.WARN and row.fix


def test_delivery_row_warns_when_unset_or_empty() -> None:
    unset = _by_name(_good(delivery_fn=lambda agent_id: None))["Delivery"]
    empty = _by_name(_good(delivery_fn=lambda agent_id: SimpleNamespace(empty=True)))["Delivery"]
    assert unset.state == empty.state == doctor.WARN and unset.fix


def test_a_broken_probe_is_a_failed_row_not_a_crash() -> None:
    rows = _by_name(_good(statuses_fn=_boom, companies_fn=_boom, scheduler_fn=_boom))
    assert rows["CV"].state == doctor.FAIL
    assert rows["Companies"].state == doctor.FAIL
    assert rows["Scheduler"].state == doctor.WARN


def test_format_rows_puts_the_fix_under_a_failing_row() -> None:
    lines = doctor.format_rows(_good(scheduler_fn=lambda: False))
    assert lines[-3].startswith("WARN")
    assert lines[-2].strip() == "Turn the scheduler on in Agents."
