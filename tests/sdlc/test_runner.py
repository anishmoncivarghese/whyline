from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.console import adapters, relay_ops
from whyline.console.session import SessionEvent
from whyline.sdlc import docset, guard, product, runner, workspace
from whyline.sdlc.stages import Stage

ROLES = {"writer": "claude", "brainstorm": ["claude", "codex"]}
PRD = "# Product\n\n## Goals\n\nShip it.\n\n## Users\n\nEveryone.\n"


_REAL_REVISE_DOCUMENT_TEXT = relay_ops.revise_document_text
_REAL_DISCARD_DOCUMENT = relay_ops.discard_document

@pytest.fixture
def env(tmp_path, monkeypatch):
    calls = SimpleNamespace(drafts=[], revises=[], discards=[], brainstorms=[], text="# Draft\n")
    monkeypatch.setattr(guard, "check", lambda root: None)
    monkeypatch.setattr(guard, "docs_root", lambda root: tmp_path)
    monkeypatch.setattr(workspace, "docs_root", lambda root: tmp_path)
    monkeypatch.setattr(runner, "_has_code", lambda docs: False)

    def draft_document(root, kind, request, *, template="", attachments=(), progress):
        calls.drafts.append((kind, request, template, list(attachments)))
        return SimpleNamespace(text=calls.text)

    def revise(root, kind, text, feedback, *, template="", attachments=(), progress):
        calls.revises.append((kind, text, feedback, list(attachments)))
        return SimpleNamespace(text=calls.text)

    def brainstorm(root, **kw):
        calls.brainstorms.append(kw)
        target = root / "docs" / "brainstorm" / (kw["topic"] + ".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Synthesis\n")
        return SessionEvent(kind="output", text="ok")

    monkeypatch.setattr(relay_ops, "draft_document", draft_document)
    monkeypatch.setattr(relay_ops, "revise_document_text", revise)
    monkeypatch.setattr(relay_ops, "discard_document", lambda root, kind: calls.discards.append(kind))
    monkeypatch.setattr(adapters, "run_brainstorm", brainstorm)
    calls.root = tmp_path
    return calls


def make(root, size="feature", **kw):
    made = docset.create(root, "Login", size, "human", roles=ROLES, **kw)
    made.description = "Let people log in."
    return made


def test_brainstorm_adds_version(env):
    made = make(env.root, brainstorm_first=True)
    result = runner.run_stage(env.root, made, Stage("brainstorm", "Brainstorm"), progress=print)
    assert result.done and result.version == 1
    assert env.brainstorms[0]["agents"] == ["claude", "codex"]
    assert "# Synthesis" in (env.root / made.document("brainstorm")["path"]).read_text()
    assert made.document("brainstorm")["status"] == "in_review"
    assert made.stage == "" and made.started_at == ""


def test_spec_draft_attaches_and_discards(env):
    made = make(env.root, brainstorm_first=True, prd_mode="none")
    runner.run_stage(env.root, made, Stage("brainstorm", "B"), progress=print)
    docset.approve(env.root, made, "brainstorm", approver="anish")
    result = runner.run_stage(env.root, made, Stage("spec", "Spec"), progress=print)
    kind, request, template, attachments = env.drafts[0]
    assert result.done and kind == "spec" and request == "Let people log in."
    assert "##" in template
    assert [p.name for p in attachments] == ["brainstorm.md"]
    assert env.discards == ["spec"]
    assert docset.load(env.root, made.slug).document("spec")["status"] == "in_review"


@pytest.mark.parametrize("kind,size", [("design", "large"), ("build-record", "small")])
def test_other_draft_kinds(env, kind, size):
    made = make(env.root, size)
    result = runner.run_stage(env.root, made, Stage(kind, kind), progress=print)
    assert result.done and env.drafts[0][0] == kind and env.discards == [kind]


def test_build_record_attaches_approved_plan(env):
    made = make(env.root, "small")
    plan = env.root / "plans" / f"{made.slug}.plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# Plan\n\n- [ ] T-1: do it\n")
    made.document("plan")["status"] = "approved"
    result = runner.run_stage(env.root, made, Stage("build-record", "Build"), progress=print)
    assert result.done
    assert plan in env.drafts[0][3]


def test_prd_new_mode_plain(env):
    made = make(env.root, prd_mode="new")
    runner.run_stage(env.root, made, Stage("prd", "PRD"), progress=print)
    assert env.drafts[0][1] == "Let people log in."


def test_prd_new_mode_attaches_readme_for_existing_code(env, monkeypatch):
    monkeypatch.setattr(runner, "_has_code", lambda docs: True)
    (env.root / "README.md").write_text("# App\n")
    made = make(env.root, prd_mode="new")
    runner.run_stage(env.root, made, Stage("prd", "PRD"), progress=print)
    _, request, _, attachments = env.drafts[0]
    assert request.startswith("Write the product PRD for this existing project")
    assert request.endswith("Let people log in.")
    assert env.root / "README.md" in attachments


def _publish(root):
    product.publish(root, PRD, set_name="Old", slug="old", approver="anish")


def test_prd_update_records_based_on(env):
    _publish(env.root)
    made = make(env.root, prd_mode="update")
    env.text = PRD.replace("Ship it.", "Ship it fast.")
    result = runner.run_stage(env.root, made, Stage("prd", "PRD update"), progress=print)
    assert result.done and not result.skipped
    doc = made.document("prd")
    assert doc["based_on"] == "1.0" and doc["note"] == "based on PRD v1.0"
    assert env.revises[0][1] == PRD
    assert "keep every other section word for word" in env.revises[0][2]
    assert product.claim_holder(env.root) == made.slug
    assert env.discards == ["prd"]


def test_no_prd_change_skips_and_releases(env):
    _publish(env.root)
    made = make(env.root, prd_mode="update")
    env.text = "No PRD change: nothing user-facing."
    result = runner.run_stage(env.root, made, Stage("prd", "PRD update"), progress=print)
    assert result.done and result.skipped and result.reason == "nothing user-facing."
    assert made.document("prd") is None and made.prd_mode == "none"
    assert made.skipped["prd"] == "nothing user-facing."
    assert product.claim_holder(env.root) is None
    assert product._meta(env.root)["update_claim"] is None


def test_claim_refused(env):
    _publish(env.root)
    other = make(env.root, prd_mode="update")
    runner.run_stage(env.root, other, Stage("prd", "PRD update"), progress=print)
    second = docset.create(env.root, "Signup", "feature", "human", roles=ROLES, prd_mode="update")
    result = runner.run_stage(env.root, second, Stage("prd", "PRD update"), progress=print)
    assert result.error == "Another feature is updating the PRD (login)"
    assert len(env.revises) == 1 and second.stage == ""


def test_questions_are_saved(env, monkeypatch):
    def ask(*a, **k):
        raise relay_ops.document_questions_error()(
            "asked", Path("x.log"), questions=["Which login?", "Who signs in?"],
            stage="draft", agent="claude",
        )

    monkeypatch.setattr(relay_ops, "draft_document", ask)
    made = make(env.root, prd_mode="none")
    result = runner.run_stage(env.root, made, Stage("spec", "Spec"), progress=print)
    assert result.questions == ("Which login?", "Who signs in?") and not result.done
    saved = docset.load(env.root, made.slug)
    assert saved.pending_questions == {"spec": ["Which login?", "Who signs in?"]}
    assert saved.document("spec")["status"] == "in_review"
    assert saved.stage == ""


def test_stage_and_started_at_recorded_while_running(env, monkeypatch):
    made = make(env.root, prd_mode="none")
    seen = {}

    def draft(root, kind, request, **kw):
        seen["saved"] = docset.load(env.root, made.slug)
        return SimpleNamespace(text="x")

    monkeypatch.setattr(relay_ops, "draft_document", draft)
    runner.run_stage(env.root, made, Stage("spec", "Spec"), progress=print)
    assert seen["saved"].stage == "spec" and seen["saved"].started_at


def test_guard_refuses(env, monkeypatch):
    monkeypatch.setattr(guard, "check", lambda root: "A relay is running in the documents checkout.")
    made = make(env.root, prd_mode="none")
    result = runner.run_stage(env.root, made, Stage("spec", "Spec"), progress=print)
    assert result.error.startswith("A relay is running") and env.drafts == []


def test_design_review_changes_nothing(env):
    made = make(env.root, "large")
    before = made.to_dict()
    assert runner.run_stage(env.root, made, Stage("design-review", "x"), progress=print).done
    assert made.to_dict() == before and env.drafts == []


def test_brainstorm_error(env, monkeypatch):
    monkeypatch.setattr(
        adapters, "run_brainstorm", lambda root, **kw: SessionEvent(kind="error", text="No models.")
    )
    made = make(env.root, brainstorm_first=True)
    result = runner.run_stage(env.root, made, Stage("brainstorm", "B"), progress=print)
    assert result.error == "No models."


PLAN = """# Plan

## Tasks

### T-1: Add login
- [ ] T-1: Add login
Edit `src/login.py` only.
Tests: login works.
"""
TESTS = """# Test plan

- [ ] S-1: Login works
  covers: T-1
  kind: auto
  steps:
    - Run the login test.
  expected:
    - It passes.
"""


@pytest.fixture
def plan_env(env, monkeypatch):
    import subprocess

    from whyline_relay import config, testplan

    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"]):
        subprocess.run(["git", *args], cwd=env.root, check=True)
    seen = SimpleNamespace(planner=[], spec=[], descriptions=[], test="codex")
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude", seen.test))

    def save(root, draft, review, test=""):
        seen.planner.append(test)
        seen.test = test

    monkeypatch.setattr(relay_ops, "save_planner", save)
    monkeypatch.setattr(relay_ops, "commit_planning_decisions", lambda root: None)
    monkeypatch.setattr(
        relay_ops,
        "_settings",
        lambda root: SimpleNamespace(
            planner=SimpleNamespace(test=seen.test, draft="codex", review="claude")
        ),
    )

    def draft_plan(root, description, attachments=(), *, progress, spec=None):
        seen.spec.append(spec)
        seen.descriptions.append(description)
        path = config.relay_dir(root) / "plan-draft.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PLAN)
        testplan.path_for(path).write_text(TESTS)
        return SimpleNamespace(path=path, text=PLAN)

    def revise(root, kind, text, feedback, *, template="", attachments=(), progress):
        env.revises.append((kind, text, feedback, list(attachments)))
        path = config.relay_dir(root) / "plan-draft.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(env.text)
        testplan.path_for(path).write_text(TESTS)
        return SimpleNamespace(path=path, text=env.text)

    monkeypatch.setattr(relay_ops, "revise_document_text", revise)
    monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
    monkeypatch.setattr(relay_ops, "discard_draft", lambda root, draft: None)
    return seen


def _approved_spec_set(env):
    made = make(env.root, "small")
    made.roles["test_planner"] = "codex"
    docset.add_version(env.root, made, "spec", "# Spec\n", author="claude", note="")
    docset.approve(env.root, made, "spec", approver="anish")
    return made


def test_plan_stage_adds_plan_and_tests_versions(env, plan_env):
    made = _approved_spec_set(env)
    result = runner.run_stage(env.root, made, Stage("plan", "Plan"), progress=print)
    assert result.done and result.version == 1
    base = docset._history_path(env.root, made.slug, "plan", 1)
    assert base.read_text() == PLAN
    assert base.with_name("plan-v1.tests.md").read_text() == TESTS
    assert plan_env.spec == [env.root / made.document("spec")["path"]]
    assert plan_env.descriptions == [f"Let people log in.\n\n{runner.PLAN_COVERS_REQUEST}"]
    assert "covers: R<n>" in runner.PLAN_COVERS_REQUEST
    assert "covers: none (<reason>)" in runner.PLAN_COVERS_REQUEST


def test_prd_update_feedback_never_renumbers():
    assert "Never renumber requirements" in runner.PRD_UPDATE_FEEDBACK
    assert "next free R-number" in runner.PRD_UPDATE_FEEDBACK
    assert "removed in v<version>" in runner.PRD_UPDATE_FEEDBACK


def test_approve_plan_writes_both_files_with_spec_marker(env, plan_env):
    from whyline_relay import testplan

    made = _approved_spec_set(env)
    runner.run_stage(env.root, made, Stage("plan", "Plan"), progress=print)
    target = runner.approve_plan(env.root, made, approver="anish")
    assert target == env.root / "plans" / f"{made.slug}.plan.md"
    text = target.read_text()
    assert f"spec: {made.document('spec')['path']}" in text.splitlines()[0]
    tests = testplan.path_for(target)
    assert tests.read_text() == TESTS
    assert testplan.validate(tests.read_text(), text) == []
    assert made.document("plan")["status"] == "approved"


def test_revise_plan_uses_plan_kind_and_keeps_tests(env, plan_env):
    made = _approved_spec_set(env)
    runner.run_stage(env.root, made, Stage("plan", "Plan"), progress=print)
    env.text = PLAN + "\nMore.\n"
    result = runner.revise_plan(env.root, made, "add more", progress=print)
    assert result.done and result.version == 2
    assert env.revises[0][0] == "plan" and env.revises[0][1] == PLAN


def test_revise_plan_reaches_the_relay_with_the_plan_kind(env, plan_env, monkeypatch):
    from whyline_relay import config, documents, testplan

    made = _approved_spec_set(env)
    runner.run_stage(env.root, made, Stage("plan", "Plan"), progress=print)
    kinds = []

    def revise_text(root, settings, kind, text, feedback, **kwargs):
        kinds.append(kind)
        path = config.relay_dir(root) / "plan-draft.md"
        path.write_text(PLAN + "\nMore.\n")
        testplan.path_for(path).write_text(TESTS)
        return path

    monkeypatch.setattr(relay_ops, "revise_document_text", _REAL_REVISE_DOCUMENT_TEXT)
    monkeypatch.setattr(relay_ops, "discard_document", _REAL_DISCARD_DOCUMENT)
    monkeypatch.setattr(documents, "revise_text", revise_text)
    monkeypatch.setattr(documents, "discard", lambda root, kind: kinds.append(kind))
    result = runner.revise_plan(env.root, made, "add more", progress=print)
    assert result.done and result.version == 2
    assert kinds == [documents.PLAN_KIND, documents.PLAN_KIND]
