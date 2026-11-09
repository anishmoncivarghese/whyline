from __future__ import annotations

from types import SimpleNamespace

import pytest

from whyline.console import relay_ops
from whyline.sdlc import docset, guard, product, review, runner, workspace
from whyline.sdlc.docset import DocSetError

ROLES = {"writer": "claude"}
PRD = "# Product\n\n## Goals\n\nShip it.\n\n## Users\n\nEveryone.\n"
SPEC = "# Spec\n\n## Goal\n\nOne.\n\n## Scope\n\nTwo.\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    calls = SimpleNamespace(revises=[], commits=[], text=SPEC, root=tmp_path)
    monkeypatch.setattr(guard, "check", lambda root: None)
    monkeypatch.setattr(guard, "docs_root", lambda root: tmp_path)
    monkeypatch.setattr(workspace, "docs_root", lambda root: tmp_path)

    def revise(root, kind, text, feedback, *, template="", attachments=(), progress):
        calls.revises.append((kind, text, feedback, list(attachments)))
        return SimpleNamespace(text=calls.text)

    monkeypatch.setattr(relay_ops, "revise_document_text", revise)
    monkeypatch.setattr(relay_ops, "discard_document", lambda root, kind: None)
    monkeypatch.setattr(
        docset, "commit", lambda root, made, message: calls.commits.append(message) or True
    )
    return calls


def make(env, prd_mode="none", **kw):
    made = docset.create(env.root, "Login", "feature", "human", roles=ROLES, prd_mode=prd_mode, **kw)
    made.description = "Let people log in."
    return made


def draft(env, made, kind, text):
    docset.add_version(env.root, made, kind, text, author="claude", note="drafted")


def test_approve_commits_and_returns_next_stage(env):
    made = make(env)
    draft(env, made, "spec", SPEC)
    following = review.approve(env.root, made.slug, "spec", approver="anish")
    assert env.commits == ["docs: approve Spec v1 for Login"]
    assert docset.load(env.root, made.slug).document("spec")["status"] == "approved"
    assert following is not None and following.kind != "spec"


def test_prd_new_mode_publishes_v1_0(env):
    made = make(env, prd_mode="new")
    draft(env, made, "prd", PRD)
    review.approve(env.root, made.slug, "prd", approver="anish")
    assert product.current(env.root).version == "1.0"
    assert env.commits == ["docs: PRD v1.0 for Login"]


def _update_set(env, major=False):
    product.publish(env.root, PRD, set_name="Old", slug="old", approver="anish")
    product.publish(env.root, PRD, set_name="Old", slug="old", approver="anish")
    made = make(env, prd_mode="update", prd_major=major)
    draft(env, made, "prd", PRD + "\n## Extra\n\nMore.\n")
    made.document("prd")["based_on"] = "1.1"
    docset.save(env.root, made)
    return made


def test_prd_update_publishes_next_minor(env):
    made = _update_set(env)
    review.approve(env.root, made.slug, "prd", approver="anish")
    assert product.current(env.root).version == "1.2"
    assert env.commits == ["docs: PRD v1.2 for Login"]


def test_prd_update_major(env):
    made = _update_set(env, major=True)
    review.approve(env.root, made.slug, "prd", approver="anish")
    assert product.current(env.root).version == "2.0"


def test_moved_prd_refuses_and_approves_nothing(env):
    made = _update_set(env)
    product.publish(env.root, PRD, set_name="Other", slug="other", approver="anish")
    with pytest.raises(DocSetError, match=r"The PRD is now v1\.2\. Redo this update first\."):
        review.approve(env.root, made.slug, "prd", approver="anish")
    assert docset.load(env.root, made.slug).document("prd")["status"] == "in_review"
    assert env.commits == [] and product.current(env.root).version == "1.2"


def test_ask_for_changes_adds_version_and_reports_also_changed(env):
    made = make(env)
    draft(env, made, "spec", SPEC)
    env.text = "# Spec\n\n## Goal\n\nOne, better.\n\n## Scope\n\nThree.\n"
    also = review.ask_for_changes(
        env.root, made.slug, "spec", "Sharpen the goal", section="Goal", progress=print
    )
    kind, text, feedback, _ = env.revises[0]
    assert kind == "spec" and text == SPEC
    assert feedback.startswith("Sharpen the goal")
    assert "Change only the section 'Goal' unless the comments say otherwise." in feedback
    assert also == ["Scope"]
    loaded = docset.load(env.root, made.slug)
    assert loaded.document("spec")["version"] == 2
    log = (env.root / "docs" / "sdlc" / made.slug / "review-log.md").read_text()
    assert "changes requested" in log and "Changed: Goal, Scope" in log


def test_ask_for_changes_without_section_has_no_also_changed(env):
    made = make(env)
    draft(env, made, "spec", SPEC)
    env.text = SPEC.replace("Two", "Three")
    assert review.ask_for_changes(env.root, made.slug, "spec", "x", progress=print) == []
    assert "Change only the section" not in env.revises[0][2]


def test_edited_adds_version_only_when_file_differs(env):
    made = make(env)
    draft(env, made, "spec", SPEC)
    assert review.edited(env.root, made.slug, "spec", editor_name="anish") is None
    (env.root / made.document("spec")["path"]).write_text(SPEC + "\nMore.\n")
    assert review.edited(env.root, made.slug, "spec", editor_name="anish") == 2
    loaded = docset.load(env.root, made.slug)
    assert loaded.document("spec")["note"] == "edited by anish"
    assert review.edited(env.root, made.slug, "spec", editor_name="anish") is None


def test_redo_names_upstream_version(env):
    made = make(env, prd_mode="none", brainstorm_first=True)
    draft(env, made, "brainstorm", "# B\n\n## Idea\n\nx\n")
    draft(env, made, "spec", SPEC)
    review.redo(env.root, made.slug, "spec", progress=print)
    assert "Update this to match Brainstorm v1. Change only what that change needs." in (
        env.revises[0][2]
    )


def test_redo_moved_prd_update_rebases(env):
    made = _update_set(env)
    product.publish(env.root, PRD, set_name="Other", slug="other", approver="anish")
    review.redo(env.root, made.slug, "prd", progress=print)
    assert "match PRD v1.2" in env.revises[0][2]
    assert product.current(env.root).path in env.revises[0][3]
    assert not product.moved(env.root, docset.load(env.root, made.slug))


def test_answer_questions_uses_question_feedback(env):
    made = make(env)
    draft(env, made, "spec", SPEC)
    made.pending_questions["spec"] = ["Who logs in?"]
    docset.save(env.root, made)
    review.answer_questions(env.root, made.slug, "spec", "Admins", progress=print)
    assert "1. Who logs in?" in env.revises[0][2] and "Admins" in env.revises[0][2]
    assert "spec" not in docset.load(env.root, made.slug).pending_questions


def test_stop_clears_stage_and_releases_claim(env):
    made = _update_set(env)
    assert product.claim_update(env.root, made.slug)
    made.stage = "prd"
    made.started_at = "now"
    docset.save(env.root, made)
    review.stop(env.root, made.slug)
    loaded = docset.load(env.root, made.slug)
    assert loaded.stage == "" and loaded.started_at == ""
    assert product.claim_holder(env.root) is None
    assert loaded.document("prd")["version"] == 1


@pytest.mark.parametrize(
    "call",
    [
        lambda r, s: review.approve(r, s, "spec", approver="a"),
        lambda r, s: review.ask_for_changes(r, s, "spec", "c", progress=print),
        lambda r, s: review.edited(r, s, "spec", editor_name="a"),
        lambda r, s: review.redo(r, s, "spec", progress=print),
        lambda r, s: review.answer_questions(r, s, "spec", "a", progress=print),
        lambda r, s: review.stop(r, s),
    ],
)
def test_guard_refuses_every_action(env, monkeypatch, call):
    made = make(env)
    draft(env, made, "spec", SPEC)
    monkeypatch.setattr(guard, "check", lambda root: "A relay is running.")
    with pytest.raises(DocSetError, match="A relay is running."):
        call(env.root, made.slug)
    assert env.revises == [] and env.commits == []
