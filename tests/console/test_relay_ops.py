import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from whyline.console import adapters, relay_ops

IST = timezone(timedelta(hours=5, minutes=30))


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def test_plan_slug():
    assert relay_ops.plan_slug("Build the PRD: Trading Platform v1!") == "build-the-prd-trading-platform-v1"
    assert relay_ops.plan_slug("x" * 60) == "x" * 40
    assert relay_ops.plan_slug("!!!") == "plan"


def test_with_marker_puts_one_marker_on_line_one():
    now = datetime(2026, 10, 4, 10, 12, tzinfo=IST)
    text = relay_ops.with_marker("- [ ] T-1: x\n", source="paste", drafted_by="hand", now=now)
    assert text == (
        "<!-- whyline-plan v1 | source: paste | drafted-by: hand | "
        "created: 2026-10-04T10:12:00+05:30 -->\n- [ ] T-1: x\n"
    )
    again = relay_ops.with_marker(text, source="draft", drafted_by="codex", now=now)
    assert again.count("whyline-plan v1") == 1 and "source: draft" in again


def test_save_pasted_plan_writes_a_named_plan(repo):
    path = relay_ops.save_pasted_plan(repo, "- [ ] T-1: build it", "My Plan")
    assert path == repo / "plans" / "my-plan.plan.md"
    assert path.read_text().splitlines()[0].startswith("<!-- whyline-plan v1 | source: paste")
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["plans/my-plan.plan.md"]


def test_save_pasted_plan_rejects_prose(repo):
    with pytest.raises(ValueError, match="no tasks"):
        relay_ops.save_pasted_plan(repo, "just words", "p")


def test_save_pasted_plan_asks_before_replacing(repo):
    relay_ops.save_pasted_plan(repo, "- [ ] OLD-1: old\n", "p")
    with pytest.raises(relay_ops.plan_exists_error()):
        relay_ops.save_pasted_plan(repo, "- [ ] T-1: new\n", "p")
    relay_ops.save_pasted_plan(repo, "- [ ] T-1: new\n", "p", replace=True)
    assert "T-1: new" in (repo / "plans" / "p.plan.md").read_text()




def test_brainstorm_docs_lists_stems(repo):
    folder = repo / "docs" / "brainstorm"
    folder.mkdir(parents=True)
    (folder / "b-topic.md").write_text("x")
    (folder / "a-topic.md").write_text("x")
    (folder / "notes.txt").write_text("x")
    assert relay_ops.brainstorm_docs(repo) == ["a-topic", "b-topic"]
    assert relay_ops.brainstorm_docs(repo / "missing") == []


def test_current_roles_defaults_then_reads_config(repo):
    assert relay_ops.current_roles(repo) == {
        "implementer": "codex",
        "tester": "claude",
        "reviewer": "claude",
        "backup": [],
    }
    relay_ops.save_roles(repo, "claude", "codex", "codex", ["claude"])
    assert relay_ops.current_roles(repo) == {
        "implementer": "claude",
        "tester": "codex",
        "reviewer": "codex",
        "backup": ["claude"],
    }


def test_relay_agents_lists_installed_agents_including_recipes(repo):
    on_path = {"claude", "codex", "agy", "grok"}
    which = lambda binary: f"/bin/{binary}" if binary in on_path else None
    assert relay_ops.relay_agents(repo, which=which) == ["antigravity", "claude", "codex", "grok"]


def test_relay_agents_leaves_out_what_is_not_installed(repo):
    which = lambda binary: "/bin/x" if binary in ("claude", "grok") else None
    assert relay_ops.relay_agents(repo, which=which) == ["claude", "grok"]


def test_current_roles_accepts_grok(repo, monkeypatch):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root, which=None: ["claude", "codex", "grok"])
    relay_ops.save_roles(repo, "grok", "claude", "codex", ["grok"])
    assert relay_ops.current_roles(repo) == {
        "implementer": "grok", "tester": "claude", "reviewer": "codex", "backup": ["grok"],
    }


def test_run_checks_returns_plain_lines(repo, monkeypatch):
    from whyline_relay import preflight

    monkeypatch.setattr(
        preflight,
        "run",
        lambda root: [
            preflight.Check("ok", "fine"),
            preflight.Check("FAIL", "bad", "fix it"),
        ],
    )
    assert relay_ops.run_checks(repo) == [
        relay_ops.CheckLine("ok", "fine", None),
        relay_ops.CheckLine("FAIL", "bad", "fix it"),
    ]


def test_live_run_names_the_task_and_agent(repo, monkeypatch):
    from whyline_relay import running

    monkeypatch.setattr(
        running,
        "live",
        lambda root: running.Running(
            agent="codex",
            task="T3",
            round=1,
            started="2026-09-30T10:00:00",
            pid=1,
            role="implementer",
        ),
    )
    assert relay_ops.live_run(repo) == "T3, codex"
    monkeypatch.setattr(running, "live", lambda root: None)
    assert relay_ops.live_run(repo) is None


def test_clear_live_run_delegates_to_the_owner_safe_relay_clear(repo, monkeypatch):
    from whyline_relay import running

    cleared = []
    monkeypatch.setattr(running, "clear", lambda root: cleared.append(root))
    relay_ops.clear_live_run(repo)
    assert cleared == [repo]


def test_commit_planning_decisions_commits_only_changed_history(repo):
    decisions = repo / ".whyline" / "decisions.md"
    decisions.parent.mkdir(parents=True)
    decisions.write_text("# Decisions\n")
    _git(repo, "add", ".whyline/decisions.md")
    _git(repo, "commit", "-qm", "seed decisions")
    decisions.write_text("# Decisions\n\n## Planned the fix\n")
    (repo / "unrelated.txt").write_text("leave me alone\n")

    assert relay_ops.commit_planning_decisions(repo) is True
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == [
        ".whyline/decisions.md"
    ]
    assert "unrelated.txt" in _git(repo, "status", "--porcelain")
    assert relay_ops.commit_planning_decisions(repo) is False


def test_classify_relay_output_keeps_run_relay_oneshot_behaviour(tmp_path):
    assert (
        adapters.classify_relay_output(tmp_path, "Plan complete: 2 task(s)\n", 0).kind
        == "output"
    )
    assert adapters.classify_relay_output(tmp_path, "boom\n", 2).kind == "error"


def test_current_roles_keep_configured_agents_that_are_not_installed(repo, monkeypatch):
    # CI and fresh machines have no agent CLIs on PATH; Set up must still
    # show what the config says (the ready check flags missing agents).
    relay_ops.save_roles(repo, "antigravity", "grok", "codex", ["claude"])
    monkeypatch.setenv("PATH", "/nonexistent")
    assert relay_ops.current_roles(repo) == {
        "implementer": "antigravity", "tester": "grok", "reviewer": "codex", "backup": ["claude"],
    }


def test_list_plans_reads_markers_counts_and_the_legacy_plan(repo):
    plans = repo / "plans"
    plans.mkdir()
    (plans / "old.plan.md").write_text(
        "<!-- whyline-plan v1 | source: draft | drafted-by: codex | created: 2026-10-01T09:00:00+05:30 -->\n"
        "- [x] A-1: done\n- [ ] A-2: todo\n")
    (plans / "new.plan.md").write_text(
        "<!-- whyline-plan v1 | source: brainstorm | drafted-by: claude | created: 2026-10-03T09:00:00+05:30 -->\n"
        "- [ ] B-1: todo\n")
    (plans / "no-marker.plan.md").write_text("- [ ] C-1: x\n")
    (plans / "no-tasks.plan.md").write_text(
        "<!-- whyline-plan v1 | source: paste | drafted-by: hand | created: 2026-10-02T00:00:00+05:30 -->\nprose\n")
    (repo / "plan.md").write_text("- [ ] L-1: legacy\n")
    found = relay_ops.list_plans(repo)
    assert [(p.name, p.source, p.done, p.total) for p in found] == [
        ("new", "brainstorm", 0, 1),
        ("old", "draft", 1, 2),
        ("plan.md (older format)", "hand", 0, 1),
    ]


def test_select_plan_and_configured_plan(repo):
    path = relay_ops.save_pasted_plan(repo, "- [ ] T-1: x\n", "a")
    relay_ops.select_plan(repo, path)
    assert relay_ops.configured_plan(repo) == path


def test_planner_agents_default_and_saved(repo):
    assert relay_ops.planner_agents(repo) == ("codex", "claude")
    relay_ops.save_planner(repo, "claude", "codex")
    assert relay_ops.planner_agents(repo) == ("claude", "codex")


def test_open_questions_reads_only_that_section():
    text = (
        "# Plan\n\n## Open questions\n1. Which broker? (a) Kite (b) Upstox\n"
        "- Paper trading in V1?\n\n## Phase 1\n- [ ] T-1: x\n"
    )
    assert relay_ops.open_questions(text) == [
        "Which broker? (a) Kite (b) Upstox", "Paper trading in V1?",
    ]
    assert relay_ops.open_questions("- [ ] T-1: x\n") == []
    assert relay_ops.open_questions("## Open questions\n1. Question?\n\n- [ ] T-1: task\n") == ["Question?"]


def test_question_feedback():
    assert relay_ops.question_feedback(["Which broker?"], "Kite") == (
        "You listed these open questions:\n1. Which broker?\nThe human answered:\nKite\n"
        "Rewrite the whole plan with these decisions, and remove the answered "
        "questions from ## Open questions."
    )


def test_approve_plan(repo):
    draft_path = repo / "draft.md"
    draft_path.write_text("- [ ] T-1: approved\n")
    draft = relay_ops.Draft(
        path=draft_path,
        text="- [ ] T-1: approved\n",
        drafted_by="codex (reviewed by claude)",
        source="planner",
    )
    path = relay_ops.approve_plan(repo, draft, "Approved Plan")
    assert path == repo / "plans" / "approved-plan.plan.md"
    lines = path.read_text().splitlines()
    assert lines[0].startswith("<!-- whyline-plan v1 | source: draft | drafted-by: codex (reviewed by claude)")
    assert lines[1] == "- [ ] T-1: approved"


def test_planner_draft_drafted_by(repo):
    draft_path = repo / "d.md"
    draft_path.write_text("- [ ] T-1: x\n")
    draft = relay_ops._planner_draft(repo, draft_path)
    assert draft.drafted_by == "codex (reviewed by claude)"


def test_plan_questions_error():
    from whyline_relay import planner

    assert relay_ops.plan_questions_error() is planner.PlanQuestions


def test_answer_plan(repo, monkeypatch):
    from whyline_relay import planner

    calls = []
    draft_path = repo / "answered.md"
    draft_path.write_text("- [ ] T-1: answered\n")
    monkeypatch.setattr(
        planner, "answer", lambda root, settings, answers, print_fn=None: calls.append(answers) or draft_path
    )
    draft = relay_ops.answer_plan(repo, "answer 1", progress=lambda line: None)
    assert calls == ["answer 1"]
    assert draft.path == draft_path


def test_a_paused_run_whose_task_is_ticked_is_stale(repo):
    from whyline_relay import state

    plan_file = repo / "p.md"
    plan_file.write_text("- [x] CRS-4: release\n")
    state.save(repo, state.RelayState(
        plan=str(plan_file), branch="b", task_id="CRS-4", round=1,
        base_commit="", paused_reason="blocked", log_path="",
    ))
    assert relay_ops.stale_pause(repo) == "CRS-4"
    relay_ops.clear_pause(repo)
    assert state.load(repo) is None


def test_a_paused_run_with_work_left_is_not_stale(repo):
    from whyline_relay import state

    plan_file = repo / "p.md"
    plan_file.write_text("- [ ] CRS-4: release\n")
    state.save(repo, state.RelayState(
        plan=str(plan_file), branch="b", task_id="CRS-4", round=1,
        base_commit="", paused_reason="blocked", log_path="",
    ))
    assert relay_ops.stale_pause(repo) is None


def test_roles_configured(repo):
    assert relay_ops.roles_configured(repo) is False
    relay_ops.save_roles(repo, "codex", "claude", "claude", [])
    assert relay_ops.roles_configured(repo) is True


@pytest.mark.parametrize("usable, expected", [
    (["antigravity", "claude", "codex", "grok"],
     {"implementer": "codex", "tester": "claude", "reviewer": "grok", "backup": ["antigravity"]}),
    (["claude", "codex"],
     {"implementer": "codex", "tester": "claude", "reviewer": "claude", "backup": []}),
    (["grok"],
     {"implementer": "grok", "tester": "grok", "reviewer": "grok", "backup": []}),
])
def test_recommend_roles(usable, expected):
    assert relay_ops.recommend_roles(usable) == expected


def test_role_meaning():
    assert relay_ops.role_meaning("antigravity", "claude", "codex") == (
        "antigravity writes the code → claude runs the tests → codex reviews; whyline commits; you do the release steps."
    )
    assert relay_ops.role_meaning("codex", "claude", "claude", "human") == (
        "codex writes the code → claude runs the tests → claude reviews; whyline commits; you do the release steps."
    )
    assert relay_ops.role_meaning("codex", "claude", "claude", "codex") == (
        "codex writes the code → claude runs the tests → claude reviews; whyline commits; codex does the release steps."
    )




def test_prepare_agents_writes_and_commits_only_their_settings_files(repo):
    (repo / "mine.txt").write_text("uncommitted, the user's\n")
    created = relay_ops.prepare_agents(repo, ["codex", "claude", "grok"])
    settings = repo / ".whyline" / "relay" / "claude-settings.json"
    assert created == [settings] and settings.exists()
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == [
        ".whyline/relay/claude-settings.json"
    ]
    assert "mine.txt" in _git(repo, "status", "--porcelain")
    assert relay_ops.prepare_agents(repo, ["claude"]) == []  # never overwritten


def test_prepare_agents_can_leave_the_commit_to_the_caller(repo):
    created = relay_ops.prepare_agents(repo, ["claude"], commit=False)
    settings = repo / ".whyline" / "relay" / "claude-settings.json"
    assert created == [settings] and settings.exists()
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    assert ".whyline/relay/claude-settings.json" in status
    assert _git(repo, "log", "-1", "--format=%s").strip() == "initial"


def test_approve_spec_writes_docs_specs(repo):
    d = relay_ops.Draft(path=repo / "d.md", text="# S\n", drafted_by="codex", source="spec")
    d.path.write_text("# S\n")
    assert relay_ops.approve_spec(repo, d, "My Spec") == repo / "docs/specs/my-spec.md"
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["docs/specs/my-spec.md"]


def test_marker_records_the_spec(repo):
    text = relay_ops.with_marker("- [ ] T-1: x\n", source="draft", drafted_by="codex",
                                 spec="docs/specs/s.md")
    assert "| spec: docs/specs/s.md |" in text.splitlines()[0]
    path = repo / "plans" / "p.plan.md"
    path.parent.mkdir()
    path.write_text(text)
    assert relay_ops.list_plans(repo)[0].spec == "docs/specs/s.md"


def test_release_task_reads_the_pause(repo):
    from whyline_relay import state
    state.save(repo, state.RelayState(
        plan=str(repo / "plan.md"), branch="b", task_id="T-2", round=1, base_commit="",
        paused_reason="release task for you: T-2\nBump the version.\nTag v1.0 and push.", log_path=""))
    assert relay_ops.release_task(repo) == ("T-2", ["Bump the version.", "Tag v1.0 and push."])
    assert relay_ops.release_task(repo / "empty") is None


def test_release_task_ignores_non_release_pauses(repo):
    from whyline_relay import state
    state.save(repo, state.RelayState(
        plan=str(repo / "plan.md"), branch="b", task_id="T-2", round=1, base_commit="",
        paused_reason="blocked on review", log_path=""))
    assert relay_ops.release_task(repo) is None


def test_release_role_and_save_release(repo):
    assert relay_ops.release_role(repo) == "human"
    relay_ops.save_release(repo, "codex")
    assert relay_ops.release_role(repo) == "codex"


def test_draft_spec_and_spec_lifecycle(repo, monkeypatch):
    from whyline_relay import specs

    draft_path = repo / "draft-spec.md"
    draft_path.write_text("# Spec\n")
    calls = []
    monkeypatch.setattr(
        specs, "draft",
        lambda root, settings, req, attachments=(), print_fn=None: calls.append(("draft", req, attachments)) or draft_path,
    )
    monkeypatch.setattr(
        specs, "revise",
        lambda root, settings, fb, print_fn=None: calls.append(("revise", fb)) or draft_path,
    )
    monkeypatch.setattr(
        specs, "resume_draft",
        lambda root, settings, print_fn=None: calls.append(("resume",)) or draft_path,
    )
    monkeypatch.setattr(
        specs, "answer",
        lambda root, settings, ans, print_fn=None: calls.append(("answer", ans)) or draft_path,
    )
    monkeypatch.setattr(
        specs, "discard",
        lambda root: calls.append(("discard",)),
    )
    monkeypatch.setattr(
        specs, "pending_description",
        lambda root: "pending req",
    )

    d = relay_ops.draft_spec(repo, "spec req", [repo / "ref.txt"], progress=lambda l: None)
    assert d.source == "spec"
    assert d.drafted_by == "codex (reviewed by claude)"
    assert calls[0] == ("draft", "spec req", [repo / "ref.txt"])

    draft_path.write_text("# Revised Spec\n")
    revised = relay_ops.revise_spec(repo, d, "add section", progress=lambda l: None)
    assert revised.text == "# Revised Spec\n"
    assert calls[1] == ("revise", "add section")

    resumed = relay_ops.resume_spec(repo, progress=lambda l: None)
    assert resumed.source == "spec"
    assert calls[2] == ("resume",)

    answered = relay_ops.answer_spec(repo, "my answer", progress=lambda l: None)
    assert answered.source == "spec"
    assert calls[3] == ("answer", "my answer")

    relay_ops.discard_spec(repo)
    assert calls[4] == ("discard",)

    assert relay_ops.pending_spec(repo) == "pending req"


def test_spec_questions_error():
    from whyline_relay import planner
    assert relay_ops.spec_questions_error() is planner.PlanQuestions


def test_draft_plan_passes_spec(repo, monkeypatch):
    from whyline_relay import planner

    seen = []
    draft_path = repo / "plan.md"
    draft_path.write_text("- [ ] T-1: task\n")
    monkeypatch.setattr(
        planner, "draft",
        lambda root, settings, desc, attachments=(), print_fn=None, spec=None: seen.append(spec) or draft_path,
    )
    relay_ops.draft_plan(repo, "desc", progress=lambda l: None, spec=repo / "docs/specs/s.md")
    assert seen == [repo / "docs/specs/s.md"]


def test_final_synthesis_and_revise_synthesis(repo, monkeypatch):
    from whyline_relay import brainstorm

    monkeypatch.setattr(brainstorm, "final_synthesis", lambda root, topic: "agreed direction")
    assert relay_ops.final_synthesis(repo, "topic") == "agreed direction"

    revised = []
    monkeypatch.setattr(
        brainstorm, "revise_synthesis",
        lambda root, settings, agent, models, topic, feedback, attachments=(), **kw: revised.append(
            (agent, models, topic, feedback)
        ),
    )
    relay_ops.revise_synthesis(
        repo, "topic", "claude", ["claude", "codex"], "more details",
        progress=lambda l: None,
    )
    assert revised == [
        ("claude", [("claude", "Claude"), ("codex", "Codex")], "topic", "more details")
    ]


def test_interrupt_live_run_signals_the_running_relay(tmp_path, monkeypatch):
    import os
    import signal
    from types import SimpleNamespace

    from whyline_relay import running

    sent = []
    monkeypatch.setattr(running, "live", lambda root: SimpleNamespace(pid=4242))
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert relay_ops.interrupt_live_run(tmp_path) is True
    if os.name == "nt":  # no Ctrl+C for another process: pause after this turn
        assert sent == [] and (tmp_path / ".whyline/relay/STOP").exists()
    else:
        assert sent == [(4242, signal.SIGINT)]


def test_interrupt_live_run_with_nothing_running(tmp_path, monkeypatch):
    from whyline_relay import running

    monkeypatch.setattr(running, "live", lambda root: None)
    assert relay_ops.interrupt_live_run(tmp_path) is False
