from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from whyline import worktrees
from whyline.console import adapters, auto_run
from whyline.console.session import SessionEvent
from whyline.sdlc import docset, guard, review, runner, workspace

ROLES = {"writer": "claude", "reviewer": "codex"}


@pytest.fixture
def auto(tmp_path, monkeypatch):
    """Stubs for run(): stage drafting, the reviewer agent, approval commits and Auto's launch."""
    log = SimpleNamespace(
        staged=[], reviewers=[], launches=[], copies=[], preflights=[],
        cancel=threading.Event(), after_stage=None, root=tmp_path, project=tmp_path / "app",
    )
    log.project.mkdir()
    monkeypatch.setattr(guard, "check", lambda root: None)
    monkeypatch.setattr(guard, "docs_root", lambda root: tmp_path)
    monkeypatch.setattr(workspace, "docs_root", lambda root: tmp_path)

    def run_stage(root, found, stage, *, progress):
        log.staged.append(stage.kind)
        docset.add_version(tmp_path, found, stage.kind, f"# {stage.kind}\n", author="claude", note="drafted")
        if log.after_stage:
            log.after_stage(stage.kind)
        return runner.StageResult(done=True, version=1)

    def chat(root, *, agent, prompt, timeout_seconds, cancel_event):
        log.reviewers.append(agent)
        return SessionEvent(kind="output", text=f"[{agent}] Looks fine.")

    def approve_plan(root, found, *, approver):
        docset.approve(tmp_path, found, "plan", approver=approver)

    def preflight(root, current, *, progress):
        log.preflights.append(current["plan"]["path"])
        return current

    monkeypatch.setattr(runner, "run_stage", run_stage)
    monkeypatch.setattr(runner, "approve_plan", approve_plan)
    monkeypatch.setattr(adapters, "run_chat_turn", chat)
    monkeypatch.setattr(docset, "commit", lambda *a, **k: True)
    monkeypatch.setattr(workspace, "copy_plan_to", lambda root, docs, slug: log.copies.append((root, slug)))
    monkeypatch.setattr(auto_run, "_preflight_phase", preflight)
    monkeypatch.setattr(worktrees, "_git", lambda root, *args: "abc123\n")
    return log


def make_set(log, mode="auto"):
    made = docset.create(log.root, "Login", "feature", mode, roles=ROLES, prd_mode="none")
    made.description = "Let people log in."
    docset.save(log.root, made)
    return made


def test_run_auto_goes_from_description_to_launch(auto):
    made = make_set(auto)
    outcome = runner.run(auto.project, made.slug, launcher=lambda argv: auto.launches.append(argv))
    assert outcome.state == "launched" and outcome.build_base == "abc123"
    assert auto.staged == ["spec", "plan"]
    assert auto.reviewers == ["codex", "codex"]
    assert outcome.reviews == ("Looks fine.", "Looks fine.")
    assert auto.launches == [["start"]]
    assert auto.copies == [(auto.project, made.slug)]
    assert auto.preflights == [str(auto.project / "plans" / (made.slug + ".plan.md"))]
    saved = docset.load(auto.root, made.slug)
    assert saved.build_base == "abc123"
    assert saved.document("spec")["approved_by"] == "codex (Auto)"
    assert saved.document("plan")["approved_by"] == "codex (Auto)"
    log_text = (auto.root / "docs" / "sdlc" / made.slug / "review-log.md").read_text()
    assert "Looks fine." in log_text


def test_build_base_is_sampled_before_the_launcher_runs(auto, monkeypatch):
    head = ["before\n"]
    monkeypatch.setattr(worktrees, "_git", lambda root, *args: head[0])
    made = make_set(auto)

    def launcher(argv):
        head[0] = "after\n"  # a fast relay commits as soon as it starts
        auto.launches.append(argv)

    outcome = runner.run(auto.project, made.slug, launcher=launcher)
    assert auto.launches == [["start"]]
    assert outcome.build_base == "before"
    assert docset.load(auto.root, made.slug).build_base == "before"


def test_run_human_stops_after_one_stage(auto):
    made = make_set(auto, "human")
    outcome = runner.run(auto.project, made.slug, launcher=lambda argv: None)
    assert outcome.state == "waiting" and outcome.stage == "spec"
    assert auto.staged == ["spec"] and auto.reviewers == []
    again = runner.run(auto.project, made.slug, launcher=lambda argv: None)
    assert again.state == "waiting" and auto.staged == ["spec"]


def test_run_stops_on_questions(auto, monkeypatch):
    made = make_set(auto)
    monkeypatch.setattr(
        runner, "run_stage",
        lambda root, found, stage, *, progress: runner.StageResult(questions=("Which?",)),
    )
    outcome = runner.run(auto.project, made.slug)
    assert outcome.state == "questions" and outcome.questions == ("Which?",)
    assert auto.reviewers == []


def test_switching_to_human_mid_run_stops_after_the_stage(auto):
    made = make_set(auto)
    auto.after_stage = lambda kind: review.set_mode(auto.project, made.slug, "human")
    outcome = runner.run(auto.project, made.slug, launcher=lambda argv: None)
    assert outcome.state == "waiting" and outcome.stage == "spec"
    assert docset.load(auto.root, made.slug).mode == "human"
    assert auto.reviewers == []


def test_run_the_rest_on_auto(auto):
    made = make_set(auto, "human")
    runner.run(auto.project, made.slug)
    review.approve(auto.project, made.slug, "spec", approver="anish")
    review.set_mode(auto.project, made.slug, "auto")
    outcome = runner.run(auto.project, made.slug, launcher=lambda argv: auto.launches.append(argv))
    assert outcome.state == "launched"
    assert auto.staged == ["spec", "plan"]
    assert auto.reviewers == ["codex"]


def test_cancel_between_stages(auto):
    made = make_set(auto)
    auto.after_stage = lambda kind: auto.cancel.set() if kind == "spec" else None
    outcome = runner.run(
        auto.project, made.slug, cancel_event=auto.cancel,
        launcher=lambda argv: auto.launches.append(argv),
    )
    assert outcome.state == "cancelled"
    assert auto.staged == ["spec"] and auto.launches == []


def test_set_mode_rejects_unknown_mode(auto):
    made = make_set(auto)
    with pytest.raises(ValueError):
        review.set_mode(auto.project, made.slug, "turbo")


def make_large(log, mode="auto"):
    made = docset.create(log.root, "Login", "large", mode, roles=ROLES, prd_mode="none")
    made.description = "Let people log in."
    docset.save(log.root, made)
    return made


def test_large_auto_goes_from_description_to_launch(auto):
    made = make_large(auto)
    outcome = runner.run(auto.project, made.slug, launcher=lambda argv: auto.launches.append(argv))
    assert outcome.state == "launched"
    assert auto.staged == ["brainstorm", "design", "plan"]
    assert auto.launches == [["start"]]
    saved = docset.load(auto.root, made.slug)
    assert saved.document("design")["approved_by"] == "codex (Auto)"


def test_large_human_waits_at_plan_after_design_approved(auto):
    made = make_large(auto, "human")
    assert runner.run(auto.project, made.slug).stage == "brainstorm"
    docset.approve(auto.root, docset.load(auto.root, made.slug), "brainstorm", approver="human")
    assert runner.run(auto.project, made.slug).stage == "design"
    docset.approve(auto.root, docset.load(auto.root, made.slug), "design", approver="human")
    outcome = runner.run(auto.project, made.slug)
    assert outcome.state == "waiting" and outcome.stage == "plan"
    assert auto.staged == ["brainstorm", "design", "plan"]
