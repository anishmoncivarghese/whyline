from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from whyline import events, ledger, paths
from whyline.console import relay_ops, tui
from whyline.console.session import SessionEvent
from whyline.sdlc import docset, record, workspace

PLAN = "# Plan\n\n- [ ] T-1: Login\n  Edit `a.py`.\n- [ ] T-2: Logout\n  Edit `b.py`.\n"
TESTS = (
    "# Tests\n\n"
    "- [x] S-1: Login works\n  covers: T-1\n  kind: auto\n  steps:\n    - Run.\n  expected:\n    - Ok.\n"
    "- [ ] S-2: Logout works\n  covers: T-2\n  kind: auto\n  steps:\n    - Run.\n  expected:\n    - Ok.\n"
)
DESIGN = "# Design\n\n## Summary\n\nx\n\n## Decision records\n\nUse sessions.\n\n## Rejected alternatives\n\nnone\n"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def note(root, text, task, ts):
    paths.whyline_dir(root).mkdir(exist_ok=True)
    ledger.append(
        paths.ledger_path(root),
        {"type": events.NOTE, "id": text, "ts": ts, "decision": text, "task": task,
         "because": "b", "alternatives": [], "files": []},
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "docs_root", lambda root: tmp_path)
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "a@b.c")
    git(tmp_path, "config", "user.name", "a")
    (tmp_path / "a.py").write_text("1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base commit")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "b.py").write_text("2\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "feat: build it (T-1)")
    git(tmp_path, "tag", "v1.0.0")
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "login.plan.md").write_text(PLAN)
    (tmp_path / "plans" / "login.tests.md").write_text(TESTS)
    made = docset.create(tmp_path, "Login", "large", "human", roles={"writer": "claude"})
    made.build_base = base
    (tmp_path / made.document("design")["path"]).write_text(DESIGN)
    docset.save(tmp_path, made)
    note(tmp_path, "Use sessions", "T-1", "2026-11-02T10:00:00+00:00")
    note(tmp_path, "Other plan", "ZZ-1", "2026-11-03T10:00:00+00:00")
    note(tmp_path, "Later call", "login", "2026-11-04T10:00:00+00:00")
    note(tmp_path, "Earlier call", "T-2", "2026-11-01T10:00:00+00:00")
    return tmp_path, made


def test_build_inputs_collects_commits_scenarios_decisions_and_tag(repo):
    root, made = repo
    path = record.build_inputs(root, made)
    text = path.read_text()
    assert path == root / "docs/sdlc/login/build-inputs.md"
    assert "feat: build it (T-1)" in text and "base commit" not in text
    assert "S-1: Login works — passed" in text
    assert "S-2: Logout works — failed" in text
    assert "Use sessions" in text and "Earlier call" in text
    assert "Other plan" not in text
    assert "Tagged v1.0.0" in text


def test_build_inputs_reads_scenario_ticks_from_the_build_checkout(repo):
    root, made = repo
    build = root / "build"
    (build / "plans").mkdir(parents=True)
    (build / "plans" / "login.tests.md").write_text(TESTS.replace("- [ ] S-2", "- [x] S-2"))
    text = record.build_inputs(build, made).read_text()
    assert "S-2: Logout works — passed" in text
    assert "S-2: Logout works — failed" not in text
    assert (root / "docs/sdlc/login/build-inputs.md").exists()


def test_build_inputs_has_no_release_without_a_tag(repo):
    root, made = repo
    git(root, "tag", "-d", "v1.0.0")
    assert "## Release" not in record.build_inputs(root, made).read_text()


def test_build_inputs_ignores_a_tag_on_a_divergent_branch(repo):
    root, made = repo
    git(root, "tag", "-d", "v1.0.0")
    git(root, "checkout", "-q", "-b", "side", made.build_base)
    (root / "c.py").write_text("3\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "side work")
    git(root, "tag", "v-side")
    git(root, "checkout", "-q", "-")
    assert "v-side" not in record.build_inputs(root, made).read_text()


def test_render_decisions_design_records_then_decisions_newest_last(repo):
    root, made = repo
    text = record.render_decisions(root, made)
    assert text.index("Use sessions.") < text.index("— Earlier call")
    order = [text.index(f"— {name}") for name in ("Earlier call", "Use sessions", "Later call")]
    assert order == sorted(order)
    assert "Other plan" not in text


def test_render_decisions_without_a_design(repo):
    root, made = repo
    spec = docset.create(root, "Plain", "small", "human", roles={"writer": "claude"})
    assert "## Decision records" not in record.render_decisions(root, spec)
    assert "No decisions have been recorded yet." in record.render_decisions(root, spec)


def test_console_hook_runs_the_stage_once(repo, monkeypatch):
    root, made = repo
    calls, shown = [], []
    plan = root / "plans" / "login.plan.md"
    monkeypatch.setattr(relay_ops, "configured_plan", lambda r: plan)
    monkeypatch.setattr(
        relay_ops, "list_plans", lambda r: [SimpleNamespace(path=plan, total=2, done=2)]
    )
    monkeypatch.setattr(
        record, "run_build_record",
        lambda r, slug, progress=None: calls.append(slug) or "waiting",
    )
    fake = SimpleNamespace(
        session=SimpleNamespace(root=root),
        run_worker=lambda fn, thread=True: fn(),
        call_from_thread=lambda fn, *a: fn(*a),
        render_event=shown.append,
    )
    tui.WhylineConsoleApp._build_record_after_plan(fake)
    assert calls == ["login"] and fake._build_record_running is False
    assert any("waiting in Docs" in e.text for e in shown if isinstance(e, SessionEvent))
    # a set whose build record is already drafted is left alone
    made = docset.load(root, "login")
    made.document("build-record")["status"] = "in_review"
    docset.save(root, made)
    tui.WhylineConsoleApp._build_record_after_plan(fake)
    assert calls == ["login"]


def test_other_task_with_a_set_file_is_not_a_decision(repo):
    root, made = repo
    ledger.append(
        paths.ledger_path(root),
        {"type": events.NOTE, "id": "Stray", "ts": "2026-11-05T10:00:00+00:00",
         "decision": "Stray", "task": "ZZ-9", "because": "b", "alternatives": [],
         "files": ["docs/sdlc/login/design.md"]},
    )
    assert "Stray" not in record.render_decisions(root, made)


def test_approval_regenerates_and_commits_decisions(repo, monkeypatch):
    from whyline.sdlc import guard, review

    root, made = repo
    monkeypatch.setattr(guard, "check", lambda r: None)
    committed = {}
    monkeypatch.setattr(
        docset, "commit",
        lambda r, found, message: committed.update(
            text=(root / "docs/sdlc/login/decisions.md").read_text()
        ) or True,
    )
    review.approve(root, "login", "design", approver="anish")
    assert "Use sessions" in committed["text"] and "Other plan" not in committed["text"]


@pytest.fixture
def lens_env(repo, monkeypatch):
    from whyline.relaychat import agent_choice, ask
    from whyline.sdlc import guard

    monkeypatch.setattr(guard, "check", lambda r: None)
    monkeypatch.setattr(agent_choice, "choices", lambda r: ["claude", "codex"])
    monkeypatch.setattr(ask, "command", lambda r, cli: [cli, "--read-only"])
    monkeypatch.setattr(ask, "extract", lambda r, cli, raw, f: raw)
    monkeypatch.setattr("whyline.agents.runner._adapter", lambda defn, cli: None)
    return repo


def test_drift_review_prompt_has_the_diff_stat_and_the_document_path(lens_env):
    root, made = lens_env
    seen = []

    def run(command, text, **kwargs):
        seen.append(text)
        return SimpleNamespace(exit_code=0, output="- [major] Login — promised, not built — build it")

    path = record.drift_review(root, made, agent="codex", run_fn=run)
    assert path == root / "docs/sdlc/login/reviews/drift.md"
    assert "docs/sdlc/login/design.md" in seen[0]
    assert f"git diff --stat {made.build_base}..HEAD" in seen[0] and "b.py" in seen[0]
    assert record.DRIFT_LINE in seen[0]
    assert "promised, not built" in path.read_text()


def test_build_record_attaches_drift_next_to_the_inputs(lens_env, monkeypatch):
    root, made = lens_env
    got = {}
    monkeypatch.setattr(
        record, "drift_review",
        lambda r, found, **kw: (root / "docs/sdlc/login/reviews/drift.md"),
    )
    monkeypatch.setattr(
        relay_ops, "draft_document",
        lambda docs, kind, request, **kw: got.update(kw) or SimpleNamespace(text="# Record\n"),
    )
    monkeypatch.setattr(relay_ops, "discard_document", lambda *a, **k: None)
    monkeypatch.setattr(docset, "commit", lambda *a, **k: True)
    record.run_build_record(root, "login")
    names = [p.name for p in got["attachments"]]
    assert names[-2:] == ["build-inputs.md", "drift.md"]


def test_drift_that_does_not_run_still_gets_a_record(lens_env, monkeypatch):
    root, made = lens_env
    got = {}
    monkeypatch.setattr(
        relay_ops, "draft_document",
        lambda docs, kind, request, **kw: got.update(kw) or SimpleNamespace(text="# Record\n"),
    )
    monkeypatch.setattr(relay_ops, "discard_document", lambda *a, **k: None)
    monkeypatch.setattr(docset, "commit", lambda *a, **k: True)
    monkeypatch.setattr(
        "whyline_relay.agents.run",
        lambda *a, **k: SimpleNamespace(exit_code=1, output=""),
    )
    record.run_build_record(root, "login")
    drift = got["attachments"][-1]
    assert drift.name == "drift.md"
    assert drift.read_text().startswith("Drift check didn't run: ")


def _build(root, plan=PLAN, tests=TESTS):
    build = root / "build"
    (build / "plans").mkdir(parents=True, exist_ok=True)
    (build / "plans" / "login.plan.md").write_text(plan)
    (build / "plans" / "login.tests.md").write_text(tests)
    return build


def test_amendments_list_added_removed_and_changed_tasks(repo):
    root, made = repo
    plan = "# Plan\n\n- [ ] T-1: Login now with SSO\n  Edit `a.py`.\n- [ ] T-3: Audit\n  Edit `c.py`.\n"
    amended = record.plan_amendments(_build(root, plan), root, made)
    assert (amended.added, amended.removed, amended.changed) == (["T-3"], ["T-2"], ["T-1"])
    assert amended.summary() == "added T-3; removed T-2; changed T-1"


def test_amendments_ignore_ticks_and_summarise_ranges(repo):
    root, made = repo
    ticked = PLAN.replace("- [ ] T-1", "- [x] T-1")
    assert not record.plan_amendments(_build(root, ticked), root, made)
    many = record.Amendments(added=[f"GFR-{n}" for n in range(1, 7)], changed=["SDLC-13"])
    assert many.summary() == "added GFR-1..6; changed SDLC-13"


def test_amendments_see_test_plan_scenarios(repo):
    root, made = repo
    tests = TESTS + "- [ ] S-3: New\n  covers: T-1\n  kind: auto\n  steps:\n    - Run.\n  expected:\n    - Ok.\n"
    assert record.plan_amendments(_build(root, tests=tests), root, made).added == ["S-3"]


def test_record_amendments_adds_a_version_and_logs_it(repo):
    root, made = repo
    plan = PLAN + "- [ ] T-3: Audit\n  Edit `c.py`.\n"
    build = _build(root, plan)
    made = docset.load(root, "login")
    record.record_amendments(build, root, made)
    made = docset.load(root, "login")
    doc = made.document("plan")
    assert doc["version"] == 2 and doc["status"] == "approved"
    assert doc["approved_by"].endswith(" (during build)")
    assert doc["note"] == "amended during build: added T-3"
    assert docset.version_label(made, doc) == "Plan v2 (amended during build)"
    assert "amended during build" in (root / "docs/sdlc/login/review-log.md").read_text()
    assert not record.plan_amendments(build, root, made)
    assert "T-3" in record.build_inputs(build, made).read_text()


def test_record_amendments_versions_a_test_plan_only_change(repo):
    root, made = repo
    tests = TESTS + "- [ ] S-3: New\n  covers: T-1\n  kind: auto\n  steps:\n    - Run.\n  expected:\n    - Ok.\n"
    build = _build(root, tests=tests)
    made = docset.load(root, "login")
    record.record_amendments(build, root, made)
    made = docset.load(root, "login")
    doc = made.document("plan")
    assert doc["version"] == 2 and doc["status"] == "approved"
    assert doc["note"] == "amended during build: added S-3"
    history = docset._history_path(root, "login", "plan", 2).parent
    assert (history / "plan-v2.tests.md").read_text() == tests
    assert (history / "plan-v1.tests.md").read_text() == TESTS
    assert not record.plan_amendments(build, root, made)


def test_record_amendments_does_nothing_without_changes(repo):
    root, made = repo
    assert not record.record_amendments(_build(root), root, made)
    assert docset.load(root, "login").document("plan")["version"] == 1


def test_build_inputs_lists_plan_changes(repo):
    root, made = repo
    build = _build(root, PLAN + "- [ ] T-3: Audit\n  Edit `c.py`.\n")
    text = record.build_inputs(build, made).read_text()
    assert "## Plan changes during the build" in text and "- Added: T-3" in text
