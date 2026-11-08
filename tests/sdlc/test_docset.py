from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from whyline.sdlc import docset
from whyline.sdlc.docset import DocSetError, Mode, PrdMode, Size, Status

ROLES = {"implementer": "claude"}


def kinds(sets):
    return [d["kind"] for d in sets.documents]


def test_labels():
    assert Mode.HUMAN.label == "Human in the loop"
    assert Status.IN_REVIEW.label == "In review"
    assert Status.OUT_OF_DATE.label == "Out of date"
    assert PrdMode.NEW.label == "New project: write the PRD"
    assert PrdMode.UPDATE.label == "Update the product PRD"
    assert PrdMode.NONE.label == "No PRD change"
    assert Size.LARGE.label == "Large"


@pytest.mark.parametrize("prd_mode", ["new", "update", "none"])
def test_small_never_has_a_prd(prd_mode):
    assert docset.documents_for("small", False, prd_mode) == ["spec", "plan", "build-record"]
    assert docset.documents_for("small", True, prd_mode) == ["spec", "plan", "build-record"]


@pytest.mark.parametrize("prd_mode", ["new", "update"])
def test_feature_documents(prd_mode):
    assert docset.documents_for("feature", False, prd_mode) == ["prd", "spec", "plan", "build-record"]
    assert docset.documents_for("feature", True, prd_mode) == [
        "brainstorm", "prd", "spec", "plan", "build-record",
    ]


def test_feature_without_prd():
    assert docset.documents_for("feature", False, "none") == ["spec", "plan", "build-record"]
    assert docset.documents_for("feature", True, "none") == [
        "brainstorm", "spec", "plan", "build-record",
    ]


@pytest.mark.parametrize("prd_mode", ["new", "update"])
def test_large_documents(prd_mode):
    assert docset.documents_for("large", False, prd_mode) == [
        "brainstorm", "prd", "design", "plan", "build-record",
    ]


def test_large_without_prd():
    assert docset.documents_for("large", True, "none") == [
        "brainstorm", "design", "plan", "build-record",
    ]


def test_prd_mode_defaults_to_new_without_product_prd(tmp_path):
    made = docset.create(tmp_path, "Login", "feature", "human", roles=ROLES)
    assert made.prd_mode == "new"


def test_prd_mode_defaults_to_update_with_product_prd(tmp_path):
    (tmp_path / "docs" / "product").mkdir(parents=True)
    (tmp_path / "docs" / "product" / "prd.md").write_text("# PRD\n")
    made = docset.create(tmp_path, "Login", "feature", "human", roles=ROLES)
    assert made.prd_mode == "update"
    assert "prd" in kinds(made)


def test_small_always_stores_none(tmp_path):
    (tmp_path / "docs" / "product").mkdir(parents=True)
    (tmp_path / "docs" / "product" / "prd.md").write_text("# PRD\n")
    made = docset.create(tmp_path, "Typo", "small", "auto", prd_mode="new", roles=ROLES)
    assert made.prd_mode == "none"
    assert kinds(made) == ["spec", "plan", "build-record"]


def test_explicit_none_drops_prd(tmp_path):
    made = docset.create(tmp_path, "Login", "large", "auto", prd_mode="none", roles=ROLES)
    assert kinds(made) == ["brainstorm", "design", "plan", "build-record"]


def test_paths_and_fields(tmp_path):
    made = docset.create(
        tmp_path, "Login Flow", "feature", "human",
        brainstorm_first=True, prd_major=True, build=False, roles=ROLES,
    )
    assert made.slug == "login-flow"
    raw = json.loads((tmp_path / "docs/sdlc/login-flow/docset.json").read_text())
    assert raw["schema"] == 1
    assert raw["prd_major"] is True
    assert raw["build"] is False
    assert raw["roles"] == ROLES
    assert raw["created"]
    paths = {d["kind"]: d["path"] for d in raw["documents"]}
    assert paths["plan"] == "plans/login-flow.plan.md"
    assert paths["spec"] == "docs/sdlc/login-flow/spec.md"
    assert paths["build-record"] == "docs/sdlc/login-flow/build-record.md"
    first = raw["documents"][0]
    assert first == {
        "kind": "brainstorm", "path": "docs/sdlc/login-flow/brainstorm.md",
        "status": "draft", "version": 1, "written_by": None, "reviewed_by": None,
        "approved_by": None, "approved_at": None, "upstream": {},
    }


def test_slug_clashes_get_a_number(tmp_path):
    slugs = [
        docset.create(tmp_path, "Login", "small", "human", roles=ROLES).slug for _ in range(3)
    ]
    assert slugs == ["login", "login-2", "login-3"]
    assert (tmp_path / "docs/sdlc/login-3/docset.json").is_file()


def test_save_load_round_trip(tmp_path):
    made = docset.create(tmp_path, "Login", "large", "auto", roles=ROLES)
    made.documents[0]["status"] = "approved"
    made.documents[0]["upstream"] = {"spec": "abc"}
    docset.save(tmp_path, made)
    loaded = docset.load(tmp_path, "login")
    assert loaded == made
    assert loaded.document("brainstorm")["status"] == "approved"


def test_all_sets(tmp_path):
    assert docset.all_sets(tmp_path) == []
    docset.create(tmp_path, "B one", "small", "human", roles=ROLES)
    docset.create(tmp_path, "A one", "small", "human", roles=ROLES)
    (tmp_path / "docs/sdlc/stray").mkdir()
    assert [s.slug for s in docset.all_sets(tmp_path)] == ["a-one", "b-one"]


def test_missing_docset_is_a_plain_error(tmp_path):
    with pytest.raises(DocSetError, match="missing"):
        docset.load(tmp_path, "nothing")


@pytest.mark.parametrize("text", ["{not json", "[]", '{"schema": 1}', '{"schema": 9}', ""])
def test_corrupt_docset_is_a_plain_error(tmp_path, text):
    folder = tmp_path / "docs/sdlc/bad"
    folder.mkdir(parents=True)
    (folder / "docset.json").write_text(text)
    with pytest.raises(DocSetError):
        docset.load(tmp_path, "bad")
    assert docset.all_sets(tmp_path) == []


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "other.txt").write_text("x")
    _git(root, "add", "other.txt")
    _git(root, "commit", "-m", "init")
    return root


def test_versions_and_history(tmp_path):
    made = docset.create(tmp_path, "Login", "small", "human", roles=ROLES)
    assert docset.add_version(tmp_path, made, "spec", "one", author="claude", note="first") == 1
    assert docset.add_version(tmp_path, made, "spec", "two", author="claude", note="again") == 2
    assert docset.strip_header((tmp_path / "docs/sdlc/login/spec.md").read_text()) == "two"
    assert (tmp_path / "docs/sdlc/login/history/spec-v1.md").read_text() == "one"
    assert (tmp_path / "docs/sdlc/login/history/spec-v2.md").read_text() == "two"
    loaded = docset.load(tmp_path, "login")
    assert loaded.document("spec")["version"] == 2
    assert loaded.document("spec")["status"] == "in_review"


def test_plan_version_writes_no_plans_file(tmp_path):
    made = docset.create(tmp_path, "Login", "small", "human", roles=ROLES)
    docset.add_version(tmp_path, made, "plan", "the plan", author="claude", note="n")
    assert not (tmp_path / "plans").exists()
    assert (tmp_path / "docs/sdlc/login/history/plan-v1.md").read_text() == "the plan"


def test_review_log_entries(tmp_path):
    made = docset.create(tmp_path, "Login", "small", "human", roles=ROLES)
    docset.add_version(tmp_path, made, "spec", "one", author="claude", note="n")
    docset.log_review(
        tmp_path,
        made,
        "spec",
        actor="codex",
        action="changes requested",
        comment="Too vague",
        section="Goals",
        changed_sections=["Goals", "Scope"],
    )
    docset.log_review(tmp_path, made, "spec", actor="codex", action="comment")
    text = (tmp_path / "docs/sdlc/login/review-log.md").read_text()
    assert " · spec v1 · changes requested · codex\n" in text
    assert text.startswith("### 20")
    assert "Too vague" in text and "Goals" in text and "Changed: Goals, Scope" in text
    assert text.count("### ") == 2


def test_approve_records_upstream_hashes(tmp_path):
    made = docset.create(tmp_path, "Login", "small", "human", roles=ROLES)
    docset.add_version(tmp_path, made, "spec", "spec text", author="claude", note="n")
    docset.approve(tmp_path, made, "spec", approver="anish")
    docset.add_version(tmp_path, made, "plan", "plan text", author="claude", note="n")
    docset.approve(tmp_path, made, "plan", approver="anish")
    loaded = docset.load(tmp_path, "login")
    spec, plan = loaded.document("spec"), loaded.document("plan")
    assert spec["status"] == "approved" and spec["approved_by"] == "anish"
    assert spec["approved_at"] and spec["upstream"] == {}
    assert plan["upstream"] == {"spec": hashlib.sha256(b"spec text").hexdigest()}
    assert "approved · anish" in (tmp_path / "docs/sdlc/login/review-log.md").read_text()


def test_commit_touches_only_the_sets_paths(repo):
    made = docset.create(repo, "Login", "small", "human", roles=ROLES)
    docset.add_version(repo, made, "spec", "spec text", author="claude", note="n")
    (repo / "unrelated.txt").write_text("keep out")
    assert docset.commit(repo, made, "docs: login") is True
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert files and all(f.startswith("docs/sdlc/login/") for f in files)
    assert "docs/sdlc/login/spec.md" in files
    assert "unrelated.txt" in _git(repo, "status", "--porcelain")
    assert docset.commit(repo, made, "docs: again") is False


def test_header_round_trip_leaves_body_untouched(tmp_path):
    made = docset.create(tmp_path, "Login", "small", "human", roles=ROLES)
    body = "# Spec\n\nline  with trailing  \n\n\nend"
    docset.add_version(tmp_path, made, "spec", body, author="claude", note="n")
    path = tmp_path / "docs/sdlc/login/spec.md"
    first = path.read_text()
    assert first.startswith(docset.HEADER_START)
    assert first.endswith(body) and docset.strip_header(first) == body
    assert "In review" in first and "v1" in first and "claude" in first
    assert "[Plan](../../../plans/login.plan.md)" in first
    docset.approve(tmp_path, made, "spec", approver="anish")
    second = path.read_text()
    assert "Approved by:** anish on" in second
    assert second.count(docset.HEADER_START) == 1
    assert docset.strip_header(second) == body
    assert second.endswith(body)


def test_apply_header_keeps_text_around_the_block():
    header = "<!-- docset-header -->\nnew\n<!-- /docset-header -->\n"
    old = "before\n<!-- docset-header -->\nold\n<!-- /docset-header -->\nafter"
    assert docset.apply_header(old, header) == "before\n" + header + "after"
    assert docset.apply_header("body", header) == header + "\nbody"


def test_plan_gets_no_header(tmp_path):
    made = docset.create(tmp_path, "Login", "small", "human", roles=ROLES)
    plan = tmp_path / "plans/login.plan.md"
    plan.parent.mkdir()
    plan.write_text("# plan\n")
    docset.add_version(tmp_path, made, "plan", "the plan", author="claude", note="n")
    docset.approve(tmp_path, made, "plan", approver="anish")
    assert plan.read_text() == "# plan\n"


def test_index_content(tmp_path):
    made = docset.create(tmp_path, "Login", "small", "human", roles=ROLES)
    docset.add_version(tmp_path, made, "spec", "s", author="claude", note="n")
    docset.approve(tmp_path, made, "spec", approver="anish")
    text = (tmp_path / "docs/sdlc/login/index.md").read_text()
    assert text.startswith("# Login")
    assert "Small" in text and "Human in the loop" in text
    assert "| [Spec](spec.md) | Approved | v1 | anish on 20" in text
    assert "| [Plan](../../../plans/login.plan.md) | Draft | v1 | — |" in text
    assert "- [Plan](../../../plans/login.plan.md)" in text
    assert "- [Test plan](../../../plans/login.tests.md)" in text


def _approved_feature(tmp_path):
    made = docset.create(tmp_path, "Login", "feature", "human", prd_mode="new", roles=ROLES)
    docset.add_version(tmp_path, made, "prd", "prd text", author="claude", note="n")
    docset.approve(tmp_path, made, "prd", approver="anish")
    docset.add_version(tmp_path, made, "spec", "spec text", author="claude", note="n")
    docset.approve(tmp_path, made, "spec", approver="anish")
    return made


def test_prd_reapproval_marks_the_spec(tmp_path):
    made = _approved_feature(tmp_path)
    assert docset.refresh_out_of_date(tmp_path, made) == []
    docset.add_version(tmp_path, made, "prd", "prd text v2", author="claude", note="n")
    docset.approve(tmp_path, made, "prd", approver="anish")
    marked = docset.refresh_out_of_date(tmp_path, made)
    assert marked == [("spec", "PRD changed (v1 \u2192 v2) after this was approved")]
    assert docset.load(tmp_path, "login").document("spec")["status"] == "out_of_date"
    assert "Out of date" in (tmp_path / "docs/sdlc/login/spec.md").read_text()


def test_edit_on_disk_marks_and_revert_clears(tmp_path):
    made = _approved_feature(tmp_path)
    prd = tmp_path / made.document("prd")["path"]
    original = prd.read_text()
    prd.write_text(original + "extra")
    marked = docset.refresh_out_of_date(tmp_path, made)
    assert marked == [("spec", "PRD was edited on disk after this was approved")]
    assert docset.refresh_out_of_date(tmp_path, made) == []
    prd.write_text(original)
    assert docset.refresh_out_of_date(tmp_path, made) == []
    assert made.document("spec")["status"] == "approved"
    assert "out_of_date_reason" not in made.document("spec")


def test_ticked_tasks_hash_the_same():
    open_ = "- [ ] SDLC-1: a\n- [ ] SDLC-2: b\n"
    ticked = "- [x] SDLC-1: a\n- [ ] SDLC-2: b\n"
    assert docset.content_hash("plan", open_) == docset.content_hash("plan", ticked)
    assert docset.content_hash("spec", open_) != docset.content_hash("spec", ticked)


def test_plan_moved_to_done_is_still_found(tmp_path):
    made = docset.create(tmp_path, "Login", "small", "human", roles=ROLES)
    docset.add_version(tmp_path, made, "spec", "spec text", author="claude", note="n")
    docset.approve(tmp_path, made, "spec", approver="anish")
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "login.plan.md").write_text("- [ ] T-1: a\n")
    docset.add_version(tmp_path, made, "plan", "- [ ] T-1: a\n", author="claude", note="n")
    docset.approve(tmp_path, made, "plan", approver="anish")
    build = made.document("build-record")
    build["status"] = "approved"
    build["upstream"] = {"plan": docset.content_hash("plan", "- [ ] T-1: a\n")}
    assert docset.plan_file(tmp_path, "login") == plans / "login.plan.md"
    (plans / "done").mkdir()
    (plans / "login.plan.md").rename(plans / "done" / "login.plan.md")
    assert docset.plan_file(tmp_path, "login") == plans / "done" / "login.plan.md"
    assert docset.plan_file(tmp_path, "other") is None
    (plans / "done" / "login.plan.md").write_text("- [x] T-1: a\n")
    assert docset.refresh_out_of_date(tmp_path, made) == []
    (plans / "done" / "login.plan.md").write_text("- [x] T-1: changed\n")
    assert [k for k, _ in docset.refresh_out_of_date(tmp_path, made)] == ["build-record"]
