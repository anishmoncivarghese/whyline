from __future__ import annotations

from whyline.sdlc import docset, library, product

ROLES = {"implementer": "claude"}
V1 = "# Product\n\n## Goals\n\nShip it.\n"


def _make(root, name, created, size="feature", approve=()):
    found = docset.create(root, name, size, "human", roles=ROLES)
    found.created = created
    for kind in approve:
        found.document(kind)["status"] = docset.Status.APPROVED.value
    docset.save(root, found)
    return found


def _plan(folder, slug, spec=None, tests=True):
    folder.mkdir(parents=True, exist_ok=True)
    spec_field = f" | spec: {spec}" if spec else ""
    (folder / f"{slug}.plan.md").write_text(
        f"<!-- whyline-plan v1 | source: hand | drafted-by: claude{spec_field} | created: x -->\n"
        "- [ ] A-1: do\n",
        encoding="utf-8",
    )
    if tests:
        (folder / f"{slug}.tests.md").write_text("tests\n", encoding="utf-8")


def test_sets_newest_first_with_one_line_summary(tmp_path):
    _make(tmp_path, "Old thing", "2026-01-01T00:00:00+00:00", size="small")
    _make(tmp_path, "Job search 5", "2026-06-01T00:00:00+00:00", approve=("prd", "spec", "plan"))
    found = library.sets(tmp_path)
    assert [s.slug for s in found] == ["job-search-5", "old-thing"]
    assert found[0].summary == "Job search 5 · Feature · PRD ✓ · Spec ✓ · Plan ✓ · Built ⏳"
    assert found[1].summary == "Old thing · Small · Spec ⏳ · Plan ⏳ · Built ⏳"


def test_product_is_none_without_a_prd(tmp_path):
    assert library.product(tmp_path) is None


def test_product_keeps_last_ten_changelog_lines(tmp_path):
    for n in range(12):
        product.publish(
            tmp_path, V1 + f"\n## S{n}\n\nx\n", set_name=f"Set {n}", slug=f"s{n}", approver="anish"
        )
    summary = library.product(tmp_path)
    assert summary.version == "1.11"
    assert summary.approval.startswith("anish on ")
    assert len(summary.changelog) == 10
    assert summary.changelog[-1].startswith("v1.11 ·")
    assert summary.changelog[0].startswith("v1.2 ·")


def test_earlier_plans_skip_set_plans_and_include_done(tmp_path):
    _make(tmp_path, "Owned", "2026-01-01T00:00:00+00:00")
    _plan(tmp_path / "plans", "owned")
    _plan(tmp_path / "plans", "loose")
    _plan(tmp_path / "plans" / "done", "finished", tests=False)
    found = library.earlier_plans(tmp_path)
    assert [p.slug for p in found] == ["loose", "finished"]
    assert found[0].test_plan == tmp_path / "plans" / "loose.tests.md"
    assert found[1].plan == tmp_path / "plans" / "done" / "finished.plan.md"
    assert found[1].test_plan is None


def test_earlier_plan_names_its_spec_and_brainstorm(tmp_path):
    spec = tmp_path / "docs/superpowers/specs/a-design.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("spec", encoding="utf-8")
    brain = tmp_path / "docs/brainstorm/b.md"
    brain.parent.mkdir(parents=True)
    brain.write_text("idea", encoding="utf-8")
    _plan(tmp_path / "plans", "a", spec="docs/superpowers/specs/a-design.md")
    _plan(tmp_path / "plans", "b", spec="docs/brainstorm/b.md")
    a, b = library.earlier_plans(tmp_path)
    assert (a.source, a.source_kind) == (spec.resolve(), "spec")
    assert (b.source, b.source_kind) == (brain.resolve(), "brainstorm")


def test_marker_naming_a_missing_spec_gives_no_source(tmp_path):
    _plan(tmp_path / "plans", "gone", spec="docs/superpowers/specs/missing.md")
    _plan(tmp_path / "plans", "escape", spec="../outside.md")
    gone, escape = library.earlier_plans(tmp_path)
    assert gone.source is None and gone.source_kind == ""
    assert escape.source is None
