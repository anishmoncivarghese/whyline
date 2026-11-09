from __future__ import annotations

import pytest

from whyline.sdlc import docset
from whyline.sdlc.stages import Stage, next_stage, plan_stages, stages_line

BUILD = ["implement", "test", "review", "release", "build-record", "done"]


def kinds(stages):
    return [s.kind for s in stages]


def active(stages):
    return [s.kind for s in stages if not s.skipped]


def by_kind(stages, kind):
    return next(s for s in stages if s.kind == kind)


def stages(size, start="description", *, brainstorm_first=False, build=False, prd_mode="new"):
    return plan_stages(size, start, brainstorm_first=brainstorm_first, build=build, prd_mode=prd_mode)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("small", ["home", "spec", "plan"]),
        ("feature", ["home", "prd", "spec", "plan"]),
        ("large", ["brainstorm", "home", "prd", "design", "design-review", "plan"]),
    ],
)
def test_each_size_from_a_description(size, expected):
    assert active(stages(size)) == expected


@pytest.mark.parametrize("size", ["small", "feature", "large"])
@pytest.mark.parametrize(
    ("start", "skipped", "reason"),
    [
        ("description", [], ""),
        ("brainstorm", ["brainstorm"], "starting from a brainstorm"),
        ("prd", ["brainstorm"], "starting from a PRD"),
        ("spec", ["brainstorm", "prd"], "starting from a spec"),
    ],
)
def test_each_size_and_start(size, start, skipped, reason):
    result = stages(size, start)
    for stage in result:
        if stage.kind == "prd" and size == "small":
            assert stage.skipped and stage.reason == "Small has no PRD"
        elif stage.kind in skipped:
            assert stage.skipped and stage.reason == reason
        elif stage.kind == "brainstorm":
            assert not stage.skipped
        else:
            assert not stage.skipped and stage.reason == ""


def test_brainstorm_stage_presence():
    assert "brainstorm" not in kinds(stages("feature"))
    assert "brainstorm" in kinds(stages("feature", brainstorm_first=True))
    assert "brainstorm" in kinds(stages("feature", "brainstorm"))
    assert "brainstorm" in kinds(stages("large"))


@pytest.mark.parametrize(
    ("prd_mode", "label", "skipped", "reason"),
    [
        ("new", "PRD", False, ""),
        ("update", "PRD update", False, ""),
        ("none", "PRD", True, "no PRD change"),
    ],
)
def test_each_prd_mode(prd_mode, label, skipped, reason):
    for size in ("feature", "large"):
        prd = by_kind(stages(size, prd_mode=prd_mode), "prd")
        assert (prd.label, prd.skipped, prd.reason) == (label, skipped, reason)


def test_small_prd_reason_wins_over_prd_mode():
    prd = by_kind(stages("small", prd_mode="update"), "prd")
    assert prd.skipped and prd.reason == "Small has no PRD"


def test_start_reason_does_not_hide_no_prd_change():
    prd = by_kind(stages("feature", "spec", prd_mode="none"), "prd")
    assert prd.reason == "no PRD change"


def test_large_design_review_follows_design():
    large = kinds(stages("large"))
    assert large.index("design-review") == large.index("design") + 1
    assert "design-review" not in kinds(stages("feature"))
    assert "design" not in kinds(stages("feature"))
    assert "spec" not in kinds(stages("large"))


def test_build_on_and_off():
    off = kinds(stages("feature", build=False))
    on = kinds(stages("feature", build=True))
    assert off == ["home", "prd", "spec", "plan"]
    assert on == off + BUILD
    assert on[-2:] == ["build-record", "done"]


def test_stage_is_frozen_value():
    assert Stage("spec", "Spec") == Stage("spec", "Spec", False, "")


def test_unknown_start_is_refused():
    with pytest.raises(ValueError, match="Unknown start"):
        stages("feature", "idea")


def test_the_designs_example_line():
    roles = {"writer": "claude", "prd_reviewer": "codex", "test_planner": "codex"}
    line = stages_line(stages("feature", build=True), roles)
    assert line == (
        "Project home (you choose) → PRD (claude, reviewed by codex) → Spec (claude) → Plan + test plan (claude, tests by codex)"
        " → Implement → Test → Review → Release → Build record → Done"
    )


def test_line_shows_skipped_stages_with_reason():
    line = stages_line(stages("large", "brainstorm", prd_mode="none"), {"writer": "claude"})
    assert line.startswith(
        "Brainstorm — (starting from a brainstorm) → Project home — (existing project) → PRD — (no PRD change) → Design (claude)"
    )


def test_line_agents_for_large_and_build():
    roles = {
        "writer": "claude",
        "reviewer": "codex",
        "architect_reviewer": "grok",
        "implementer": "claude",
        "tester": "grok",
        "code_reviewer": "codex",
        "release": "claude",
    }
    line = stages_line(stages("large", build=True), roles)
    assert "Design (claude, reviewed by codex) → Design review (grok) → Plan + test plan (claude, reviewed by codex)" in line
    assert "Implement (claude) → Test (grok) → Review (codex) → Release (claude)" in line


def test_line_skip_without_reason():
    assert stages_line([Stage("spec", "Spec", True, "")], {}) == "Spec —"


def make(tmp_path, size="feature", **kwargs):
    return docset.create(tmp_path, "Login", size, "human", roles={}, **kwargs)


def approve_all(made, *kinds_):
    for doc in made.documents:
        if doc["kind"] in kinds_:
            doc["status"] = "approved"


def test_next_stage_walks_the_set(tmp_path):
    made = make(tmp_path, prd_mode="new")
    assert next_stage(made).kind == "home"
    made.skipped["home"] = "chosen by the user: here"
    assert next_stage(made).kind == "prd"
    approve_all(made, "prd")
    assert next_stage(made).kind == "spec"
    approve_all(made, "spec")
    assert next_stage(made).kind == "plan"
    approve_all(made, "plan")
    assert next_stage(made).kind == "implement"
    made.build_base = "abc123"
    assert next_stage(made).kind == "build-record"
    approve_all(made, "build-record")
    assert next_stage(made).kind == "done"
    made.state = "released"
    assert next_stage(made) is None


def test_next_stage_skips_a_missing_prd_and_stops_without_build(tmp_path):
    made = make(tmp_path, prd_mode="none", build=False)
    assert next_stage(made).kind == "spec"
    approve_all(made, "spec", "plan")
    assert next_stage(made) is None


def test_next_stage_large_includes_design_review(tmp_path):
    made = make(tmp_path, "large", prd_mode="none", build=False)
    assert next_stage(made).kind == "brainstorm"
    approve_all(made, "brainstorm")
    assert next_stage(made).kind == "design"
    approve_all(made, "design")
    assert next_stage(made).kind == "design-review"
    made.design_reviewed = True
    assert next_stage(made).kind == "plan"


@pytest.mark.parametrize("prd_mode", ["update", "none"])
def test_home_is_skipped_for_an_existing_project(prd_mode):
    home = by_kind(stages("feature", prd_mode=prd_mode), "home")
    assert (home.label, home.skipped, home.reason) == ("Project home", True, "existing project")


def test_home_follows_brainstorm_and_leads_without_one():
    assert kinds(stages("large"))[:2] == ["brainstorm", "home"]
    assert kinds(stages("feature"))[0] == "home"
    assert not by_kind(stages("feature"), "home").skipped
