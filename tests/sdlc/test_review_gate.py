from __future__ import annotations

import pytest

from whyline.sdlc import docset, goldfish, guard, review, workspace

SPEC = "# Spec\n\n## Requirements covered\n\n- R1: Log in\n- R2: Log out\n"
PLAN = (
    "# Plan\n\n- [ ] T-1: Login\n  covers: R1\n  Edit `a.py`.\n"
    "- [ ] T-2: Docs\n  covers: none (docs only)\n- [ ] T-3: Bare\n  Edit `b.py`.\n"
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "check", lambda root: None)
    monkeypatch.setattr(guard, "docs_root", lambda root: tmp_path)
    monkeypatch.setattr(workspace, "docs_root", lambda root: tmp_path)
    return tmp_path


def test_plan_coverage_gaps_become_blockers_but_a_none_reason_does_not(env, monkeypatch):
    made = docset.create(
        env, "Login", "feature", "human", roles={"writer": "claude"}, prd_mode="none"
    )
    docset.add_version(env, made, "spec", SPEC, author="claude", note="drafted")
    docset.approve(env, made, "spec", approver="anish")
    docset.add_version(env, made, "plan", PLAN, author="claude", note="drafted")
    path = env / "plan-report.md"
    path.write_text("Blockers: 0 · Major: 0 · Nits: 0 · Not run: none · Reviewer: codex\n")
    monkeypatch.setattr(
        goldfish, "review_document", lambda *a, **k: goldfish.Review(path, [], [], "codex")
    )
    result = review.review_again(env, made.slug, "plan", progress=None)
    found = {(f.section, f.problem) for f in result.findings}
    assert {f.lens for f in result.findings} == {"coverage"}
    assert {f.severity for f in result.findings} == {"blocker"}
    assert found == {
        ("R2", "R2 has no task"),
        ("R1", "R1 has no test"),
        ("R2", "R2 has no test"),
        ("T-3", "T-3 has no covers line"),
    }
    assert review.gate(result) == "fix"
    assert path.read_text().splitlines()[0].startswith("Blockers: 4")
