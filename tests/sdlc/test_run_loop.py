from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import worktrees
from whyline.console import adapters, auto_run
from whyline.console.session import SessionEvent
from whyline.sdlc import docset, goldfish, guard, lenses, review, runner, workspace

ROLES = {"writer": "claude", "reviewer": "codex"}


@pytest.fixture
def auto(tmp_path, monkeypatch):
    """Stubs for run(): stage drafting, the reviewer agent, approval commits and Auto's launch."""
    log = SimpleNamespace(
        staged=[], reviewers=[], launches=[], copies=[], preflights=[], fresh=[], findings=[], not_run=[],
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

    def review_document(root, found, kind, *, agent, progress=None, cancel_event=None, run_fn=None):
        log.fresh.append((kind, agent))
        items = log.findings.pop(0) if log.findings else []
        missing = log.not_run.pop(0) if log.not_run else []
        path = tmp_path / f"{kind}-report.md"
        path.write_text(f"Blockers: 0 · Major: 0 · Nits: 0 · Not run: none · Reviewer: {agent}\n")
        return goldfish.Review(path, items, missing, agent)

    monkeypatch.setattr(goldfish, "review_document", review_document)
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
    assert auto.fresh == [("spec", "codex"), ("plan", "codex")]
    assert len(outcome.reviews) == 2 and "codex reviewed the spec" in outcome.reviews[0]
    assert auto.launches == [["start"]]
    assert auto.copies == [(auto.project, made.slug)]
    assert auto.preflights == [str(auto.project / "plans" / (made.slug + ".plan.md"))]
    saved = docset.load(auto.root, made.slug)
    assert saved.build_base == "abc123"
    assert saved.document("spec")["approved_by"] == "codex (Auto, fresh review)"
    assert saved.document("plan")["approved_by"] == "codex (Auto, fresh review)"


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
    assert auto.fresh[-1] == ("plan", "codex")


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
    assert saved.document("design")["approved_by"] == "codex (Auto, fresh review)"


def test_large_human_waits_at_plan_after_design_approved(auto):
    made = make_large(auto, "human")
    assert runner.run(auto.project, made.slug).stage == "brainstorm"
    docset.approve(auto.root, docset.load(auto.root, made.slug), "brainstorm", approver="human")
    assert runner.run(auto.project, made.slug).stage == "design"
    docset.approve(auto.root, docset.load(auto.root, made.slug), "design", approver="human")
    outcome = runner.run(auto.project, made.slug)
    assert outcome.state == "waiting" and outcome.stage == "plan"
    assert auto.staged == ["brainstorm", "design", "plan"]


def make_new_set(log, mode):
    made = docset.create(log.root, "Login", "feature", mode, roles=ROLES, prd_mode="new")
    made.description = "Let people log in."
    docset.save(log.root, made)
    return made


@pytest.mark.parametrize("mode", ["auto", "human"])
def test_run_stops_at_home_in_both_modes(auto, mode):
    made = make_new_set(auto, mode)
    outcome = runner.run(auto.project, made.slug, launcher=lambda argv: None)
    assert (outcome.state, outcome.stage) == ("waiting_for_home", "home")
    assert auto.staged == []


def test_choose_home_new_returns_the_target_and_run_continues_there(auto, monkeypatch):
    from whyline.sdlc import home

    made = make_new_set(auto, "auto")
    target = auto.root / "newproj"
    calls = []

    def create_home(root, slug, parent, folder, *, name, agents, progress):
        calls.append((parent, folder, name, agents))
        return target

    roots = {}

    def docs_root(root):
        roots[str(root)] = True
        return auto.root

    monkeypatch.setattr(home, "create_home", create_home)
    monkeypatch.setattr(workspace, "docs_root", docs_root)
    got = runner.choose_home(
        auto.project, made.slug, choice="new", parent=auto.root, folder="newproj",
        name="Login", agents=["claude"], progress=None,
    )
    assert got == target
    assert calls == [(auto.root, "newproj", "Login", ["claude"])]
    assert docset.load(auto.root, made.slug).skipped["home"]
    outcome = runner.run(got, made.slug, launcher=lambda argv: auto.launches.append(argv))
    assert outcome.state == "launched"
    assert auto.staged == ["prd", "spec", "plan"]


def test_choose_home_here_returns_root(auto, monkeypatch):
    from whyline.sdlc import home

    made = make_new_set(auto, "human")
    monkeypatch.setattr(home, "use_here", lambda root, slug: Path(root))
    got = runner.choose_home(auto.project, made.slug, choice="here", agents=[], progress=None)
    assert got == auto.project
    outcome = runner.run(got, made.slug)
    assert (outcome.state, outcome.stage) == ("waiting", "prd")
    assert auto.staged == ["prd"]


@pytest.mark.parametrize("choice", ["new", "here"])
def test_choose_home_helper_failure_leaves_the_home_stage_pending(auto, monkeypatch, choice):
    from whyline.sdlc import home

    made = make_new_set(auto, "human")

    def boom(*args, **kwargs):
        raise RuntimeError("helper failed")

    monkeypatch.setattr(home, "create_home", boom)
    monkeypatch.setattr(home, "use_here", boom)
    with pytest.raises(RuntimeError, match="helper failed"):
        runner.choose_home(auto.project, made.slug, choice=choice, parent=auto.root,
                           folder="x", name="Login", agents=[], progress=None)
    assert "home" not in docset.load(auto.root, made.slug).skipped


def test_choose_home_refuses_an_unknown_choice(auto):
    made = make_new_set(auto, "human")
    with pytest.raises(ValueError, match="Unknown home choice"):
        runner.choose_home(auto.project, made.slug, choice="elsewhere", agents=[], progress=None)


def _real_project(tmp_path):
    import json
    import subprocess

    def git(path, *args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, encoding="utf-8")

    root = tmp_path / "old"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "a@b.c")
    git(root, "config", "user.name", "a")
    made = docset.create(root, "Login", "feature", "human", roles=ROLES, prd_mode="new")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    manifest = root / "docs" / "sdlc" / made.slug / "docset.json"
    return root, made, manifest, git, json


def _status(path):
    import subprocess

    return subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True,
                          encoding="utf-8", check=True).stdout


def test_choose_home_here_keeps_the_home_record_and_git_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "check", lambda root: None)
    root, made, manifest, _git, json = _real_project(tmp_path)
    got = runner.choose_home(root, made.slug, choice="here", agents=[], progress=None)
    data = json.loads(manifest.read_text())
    assert got == root
    assert data["home"]["here"] is True and data["skipped"]["home"]
    assert _status(root) == ""


def test_choose_home_new_keeps_the_home_record_and_git_clean(tmp_path, monkeypatch):
    from whyline.console import repo_setup

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "homedir")
    monkeypatch.setattr(guard, "check", lambda root: None)
    root, made, manifest, git, json = _real_project(tmp_path)

    def setup(inspection, *, agents, progress):
        inspection.path.mkdir(parents=True, exist_ok=True)
        git(inspection.path, "init", "-q", "-b", "main")
        git(inspection.path, "config", "user.email", "a@b.c")
        git(inspection.path, "config", "user.name", "a")
        git(inspection.path, "commit", "-q", "--allow-empty", "-m", "first")
        return inspection.path

    monkeypatch.setattr(repo_setup, "setup", setup)
    parent = tmp_path / "out"
    parent.mkdir()
    target = runner.choose_home(root, made.slug, choice="new", parent=parent, folder="login",
                                name="Login", agents=["claude"], progress=None)
    copied = json.loads((target / "docs" / "sdlc" / made.slug / "docset.json").read_text())
    assert copied["home"]["created_from"] == str(root) and copied["skipped"]["home"]
    assert _status(target) == "" and _status(root) == ""


def blocker(section="Scope", problem="Vague", fix="Say what"):
    return lenses.Finding("readiness", "blocker", section, problem, fix)


def test_gate_outcomes():
    path = Path("x")
    assert review.gate(goldfish.Review(path, [], [], "codex")) == "pass"
    major = lenses.Finding("zoom-out", "major", "A", "b", "c")
    assert review.gate(goldfish.Review(path, [major], [], "codex")) == "pass"
    assert review.gate(goldfish.Review(path, [blocker()], [], "codex")) == "fix"
    assert review.gate(goldfish.Review(path, [], ["readiness"], "codex")) == "stop"


def test_auto_fix_round_clears(auto, monkeypatch):
    made = make_set(auto)
    asked = []
    monkeypatch.setattr(review, "ask_for_changes", lambda root, slug, kind, comments, **k: asked.append((kind, comments)))
    auto.findings += [[blocker(), lenses.Finding("zoom-out", "major", "Goal", "Fuzzy", "Sharpen"),
                       lenses.Finding("zoom-out", "nit", "Tone", "Dry", "Warm")]]
    outcome = runner.run(auto.project, made.slug, launcher=lambda argv: auto.launches.append(argv))
    assert outcome.state == "launched"
    assert asked == [("spec", "Scope: Vague — Say what\nGoal: Fuzzy — Sharpen")]
    assert [kind for kind, _ in auto.fresh] == ["spec", "spec", "plan"]


def test_auto_stops_after_two_fix_rounds(auto, monkeypatch):
    made = make_set(auto)
    asked = []
    monkeypatch.setattr(review, "ask_for_changes", lambda *a, **k: asked.append(1))
    auto.findings += [[blocker()], [blocker()], [blocker()]]
    outcome = runner.run(auto.project, made.slug)
    assert outcome.state == "waiting" and outcome.stage == "spec"
    assert outcome.message == "Still has blockers after 2 rounds of changes"
    assert len(asked) == review.MAX_FIX_ROUNDS == 2 and len(auto.fresh) == 3
    assert docset.load(auto.root, made.slug).document("spec")["status"] != "approved"


def test_auto_stops_when_a_lens_did_not_run(auto):
    made = make_set(auto)
    auto.not_run += [["readiness", "zoom-out"]]
    outcome = runner.run(auto.project, made.slug)
    assert outcome.state == "waiting"
    assert outcome.message == "A reviewer didn't run: readiness, zoom-out"
    assert len(auto.fresh) == 1


def test_human_mode_reviews_before_returning(auto):
    made = make_set(auto, "human")
    outcome = runner.run(auto.project, made.slug)
    assert outcome.state == "waiting" and outcome.stage == "spec"
    assert auto.fresh == [("spec", "codex")]


def test_design_review_uses_the_architect_with_five_lenses(auto, monkeypatch):
    made = make_large(auto)
    made.roles = {**ROLES, "architect_reviewer": "gemini"}
    docset.save(auto.root, made)
    seen = []
    real = goldfish.review_document
    monkeypatch.setattr(goldfish, "review_document",
                        lambda root, found, kind, **k: (seen.append(lenses.lenses_for(found.size, kind)), real(root, found, kind, **k))[1])
    outcome = runner.run(auto.project, made.slug, launcher=lambda argv: auto.launches.append(argv))
    assert outcome.state == "launched"
    assert ("design", "gemini") in auto.fresh
    assert list(lenses.LENSES) in seen


def test_approving_with_blockers_is_logged(auto):
    made = make_set(auto, "human")
    runner.run(auto.project, made.slug)
    found = docset.load(auto.root, made.slug)
    version = found.document("spec")["version"]
    report = goldfish._reviews_dir(auto.root, made.slug) / f"spec-v{version}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "Blockers: 1 · Major: 0 · Nits: 0 · Not run: none · Reviewer: codex\n\n## Blockers\n\n"
        "- Scope — Vague — Say what (lenses: readiness)\n"
    )
    review.approve(auto.project, made.slug, "spec", approver="anish")
    log_text = (auto.root / "docs" / "sdlc" / made.slug / "review-log.md").read_text()
    assert "approved with 1 blockers" in log_text
