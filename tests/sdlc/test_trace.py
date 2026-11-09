from __future__ import annotations

from whyline.sdlc import docset, trace

SPEC = """# Spec

## Requirements covered

- R1: Log in
- **R2** — Log out
- R3 — gone, removed in v2

## Other

R9 is not a requirement.
"""

PLAN = """# Plan

- [ ] T-1: Login
  covers: R1, R2
  Edit `a.py`.
- [ ] T-2: Docs
  covers: none (docs only)
- [ ] T-3: Extra
  covers: R7
- [ ] T-4: Bare
  Edit `b.py`.
"""

TESTS = """# Test plan

- [ ] S-1: [R1] Login works
  covers: T-1
  kind: auto
  steps:
    - Run it.
  expected:
    - Passes.
- [ ] S-2: [R2, R7] Logout works
  covers: T-3
  kind: auto
  steps:
    - Run it.
  expected:
    - Passes.
"""


def test_requirements_reads_section_and_skips_removed():
    assert trace.requirements(SPEC) == ["R1", "R2"]
    assert trace.requirements("## Requirements\n\nR4\nR5: x\n") == ["R4", "R5"]
    assert trace.requirements("# Nothing") == []


def test_plan_covers():
    assert trace.plan_covers(PLAN) == {
        "T-1": ["R1", "R2"],
        "T-2": [],
        "T-3": ["R7"],
    }


def test_test_covers_reads_title_tags():
    assert trace.test_covers(TESTS) == {"S-1": ["R1"], "S-2": ["R2", "R7"]}


def test_test_plan_stays_valid_with_requirement_tags():
    from whyline_relay import testplan

    plan = "- [ ] T-1: Login\n  covers: R1\n- [ ] T-3: Extra\n  covers: R7\n"
    assert testplan.validate(TESTS, plan) == []


def _set(tmp_path, spec=SPEC):
    made = docset.create(tmp_path, "Login", "small", "human", roles={"writer": "claude"})
    docset.add_version(tmp_path, made, "spec", spec, author="claude", note="")
    docset.approve(tmp_path, made, "spec", approver="anish")
    docset.add_version(tmp_path, made, "plan", PLAN, author="claude", note="")
    history = docset._history_path(tmp_path, made.slug, "plan", 1)
    docset._write(history.with_name("plan-v1.tests.md"), TESTS)
    return made


def test_coverage_gaps_of_all_four_kinds(tmp_path):
    made = _set(tmp_path)
    found = trace.coverage(tmp_path, made)
    assert found.total == 2
    assert found.unbuilt == []
    assert found.untested == []
    assert found.out_of_scope == ["T-3:R7"]
    assert found.uncovered_tasks == ["T-4"]


def test_coverage_unbuilt_and_untested(tmp_path):
    spec = SPEC.replace("- R1: Log in", "- R1: Log in\n- R4: Audit\n- R5: Export")
    found = trace.coverage(tmp_path, _set(tmp_path, spec))
    assert found.unbuilt == ["R4", "R5"]
    assert found.untested == ["R4", "R5"]


def test_line_text():
    found = trace.Coverage(total=8, untested=["R5"])
    assert found.line() == "Covers 7 of 8 requirements · R5 has no test"
    assert trace.Coverage(total=2).line() == "Covers 2 of 2 requirements"
    full = trace.Coverage(
        total=3, unbuilt=["R2"], out_of_scope=["T-3:R7"], uncovered_tasks=["T-4"]
    )
    assert full.line() == (
        "Covers 2 of 3 requirements · R2 has no task · T-3 covers R7, not in scope"
        " · T-4 has no covers line"
    )
