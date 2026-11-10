"""The New plan form: fields by size, start and mode, PRD defaults, the file picker,
and an Auto checkpoint from before this release."""

import os

import pytest

from whyline.console import auto_run, relay_ops, tui
from whyline.console.relay_screens import RelayPlanScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {
    agent: {"available": agent in ("claude", "codex"), "label": "ok"}
    for agent in ("claude", "codex", "antigravity", "grok")
}


@pytest.fixture(autouse=True)
def quiet_ops(monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "pending_spec", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok"]
    )
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude", ""))


async def _open(app, pilot, **kwargs):
    screen = RelayPlanScreen(app.session.root, STATUS, "claude", **kwargs)
    app.push_screen(screen)
    await pilot.pause()
    return screen


def _shown(screen, *ids):
    return [screen.query_one(i).display for i in ids]


def _text(screen, selector):
    return str(screen.query_one(selector, tui.Static).renderable)


async def _wait_for(pilot, condition, what):
    for _ in range(200):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


async def test_sources_are_new_plan_and_an_existing_plan(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        source = screen.query_one("#rp-source", tui.Select)
        assert source.value == "new"
        assert source._options == [("New plan", "new"), ("I have a plan already", "paste")]


async def test_fields_by_size(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        size = screen.query_one("#rp-size", tui.Select)
        ids = ("#rp-brainstorm-first", "#rp-prd-group", "#rp-no-prd", "#rp-architect-row")
        assert size.value == "feature"
        assert _shown(screen, *ids) == [True, True, False, False]
        assert "PRD, spec and plan" in _text(screen, "#rp-size-hint")
        size.value = "small"
        await pilot.pause()
        assert _shown(screen, *ids) == [False, False, True, False]
        assert _text(screen, "#rp-no-prd") == "Small has no PRD."
        assert "no PRD" in _text(screen, "#rp-size-hint")
        size.value = "large"
        await pilot.pause()
        assert _shown(screen, *ids) == [False, True, False, True]
        assert screen.query_one("#rp-architect").display
        assert "design" in _text(screen, "#rp-size-hint")


async def test_start_from_shows_its_own_fields(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        ids = ("#rp-draft-group", "#rp-brainstorm-group", "#rp-document-group")
        start = screen.query_one("#rp-start", tui.Select)
        assert start.value == "description"
        assert _shown(screen, *ids) == [True, False, False]
        start.value = "brainstorm"
        await pilot.pause()
        assert _shown(screen, *ids) == [False, True, False]
        assert screen.query_one("#rp-pick-brainstorm").display
        start.value = "document"
        await pilot.pause()
        assert _shown(screen, *ids) == [False, False, True]
        assert screen.query_one("#rp-pick-document").display


async def test_mode_and_build_control_the_execution_roles(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        build = screen.query_one("#rp-build", tui.Checkbox)
        assert screen.query_one("#rp-mode", tui.Select).value == "human"
        assert build.value is True and not build.disabled
        assert _shown(screen, "#rp-auto-group", "#rp-exec-roles", "#rp-legacy-rest") == [
            True, True, False,
        ]
        build.value = False
        await pilot.pause()
        assert not screen.query_one("#rp-auto-group").display
        assert screen.new_plan_options()["build"] is False
        screen.query_one("#rp-mode", tui.Select).value = "auto"
        await pilot.pause()
        assert build.value is True and build.disabled
        assert screen.query_one("#rp-auto-group").display
        assert screen.new_plan_options()["build"] is True
        screen.query_one("#rp-mode", tui.Select).value = "human"
        await pilot.pause()
        assert not build.disabled


async def test_prd_defaults_to_update_with_a_product_prd(tmp_path):
    folder = tmp_path / "docs" / "product"
    folder.mkdir(parents=True)
    (folder / "prd.md").write_text("<!-- product-prd v1.2 -->\n# Product\n", encoding="utf-8")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        prd = screen.query_one("#rp-prd", tui.Select)
        assert prd.value == "update"
        assert [label for label, _ in prd._options] == [
            "New project: write the PRD", "Update the product PRD", "No PRD change",
        ]
        assert _text(screen, "#rp-prd-current") == "current v1.2"
        major = screen.query_one("#rp-prd-major", tui.Checkbox)
        assert major.display and major.value is False
        assert str(major.label) == "Major version (v2.0)"
        prd.value = "none"
        await pilot.pause()
        assert not major.display
        assert screen.new_plan_options()["prd_mode"] == "none"
        prd.value = "update"
        await pilot.pause()
        major.value = True
        assert screen.new_plan_options()["prd_major"] is True


async def test_prd_defaults_to_new_without_a_product_prd(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        assert screen.query_one("#rp-prd", tui.Select).value == "new"
        assert _text(screen, "#rp-prd-current") == ""
        assert not screen.query_one("#rp-prd-major").display
        screen.query_one("#rp-size", tui.Select).value = "small"
        await pilot.pause()
        assert screen.new_plan_options()["prd_mode"] == "none"


async def test_options_follow_size_and_roles(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        screen.query_one("#rp-brainstorm-first", tui.Checkbox).value = True
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        await pilot.pause()
        options = screen.new_plan_options()
        assert options["brainstorm_first"] is True
        assert options["roles"]["writer"] == "grok"
        assert "architect" not in options["roles"]
        assert {"implementer", "tester", "exec_reviewer"} <= set(options["roles"])
        screen.query_one("#rp-size", tui.Select).value = "large"
        await pilot.pause()
        options = screen.new_plan_options()
        assert options["brainstorm_first"] is False
        assert "architect" in options["roles"]


async def test_brainstorm_select_lists_newest_first(tmp_path, monkeypatch):
    folder = tmp_path / "docs" / "brainstorm"
    folder.mkdir(parents=True)
    for name, age in (("old", 300), ("newest", 0), ("middle", 100)):
        path = folder / f"{name}.md"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (1_800_000_000 - age, 1_800_000_000 - age))
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: ["middle", "newest", "old"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        choices = screen.query_one("#rp-from", tui.Select)
        assert [value for _label, value in choices._options] == ["newest", "middle", "old"]
        assert choices.value == "newest"


async def test_choose_file_uses_the_injected_picker(tmp_path):
    chosen = tmp_path / "notes" / "prd.md"
    chosen.parent.mkdir()
    chosen.write_text("# PRD\n", encoding="utf-8")
    calls = []

    def pick():
        calls.append(1)
        return [chosen]

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot, pick_files_fn=pick)
        screen.query_one("#rp-start", tui.Select).value = "document"
        await pilot.pause()
        screen.query_one("#rp-document-kind", tui.Select).value = "spec"
        screen.query_one("#rp-pick-document", tui.Button).press()
        await _wait_for(pilot, lambda: screen._picked["document"] == chosen, "the picked file")
        assert calls == [1]
        assert _text(screen, "#rp-document-file") == "prd.md"
        options = screen.new_plan_options()
        assert options["file"] == chosen
        assert options["document_kind"] == "spec"
        screen.query_one("#rp-start", tui.Select).value = "brainstorm"
        await pilot.pause()
        screen.query_one("#rp-pick-brainstorm", tui.Button).press()
        await _wait_for(pilot, lambda: screen._picked["brainstorm"] == chosen, "the brainstorm file")
        assert _text(screen, "#rp-brainstorm-file") == "prd.md"


async def test_a_failed_picker_shows_why_and_picks_nothing(tmp_path):
    def broken():
        raise RuntimeError("the file picker failed")

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot, pick_files_fn=broken)
        screen.query_one("#rp-start", tui.Select).value = "document"
        await pilot.pause()
        screen.query_one("#rp-pick-document", tui.Button).press()
        await _wait_for(pilot, lambda: "failed" in _text(screen, "#rp-error"), "the picker error")
        assert screen._picked["document"] is None


async def test_without_an_old_checkpoint_there_is_no_resume_source(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        assert [v for _l, v in screen.query_one("#rp-source", tui.Select)._options] == [
            "new", "paste",
        ]


async def test_an_old_auto_checkpoint_still_offers_resume(tmp_path):
    from whyline.state import atomic_write_json

    path = auto_run.checkpoint_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {
        "schema": auto_run.SCHEMA,
        "phase": "paused",
        "request": {"name": "old-plan"},
        "pause": {"reason": "paused for test", "actions": ["resume", "cancel"]},
    })
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        source = screen.query_one("#rp-source", tui.Select)
        assert source.value == "new"
        assert ("Resume the earlier Auto run", "auto") in source._options
        assert not screen.query_one("#rp-run").display
        source.value = "auto"
        await pilot.pause()
        run = screen.query_one("#rp-run", tui.Button)
        assert run.display
        assert str(run.label) == "Resume"
        assert screen.query_one("#rp-name", tui.Input).value == "old-plan"
        assert not screen.query_one("#rp-go").display


async def test_stages_line_for_each_size(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        size = screen.query_one("#rp-size", tui.Select)
        line = _text(screen, "#rp-stages")
        assert "PRD (codex" in line and "Spec (codex" in line and "Design" not in line
        size.value = "small"
        await pilot.pause()
        assert "PRD — (Small has no PRD)" in _text(screen, "#rp-stages")
        size.value = "large"
        await pilot.pause()
        line = _text(screen, "#rp-stages")
        assert line.startswith("Brainstorm") and "Design (" in line and "Design review (" in line
        assert "test cases for each task" in _text(screen, "#rp-test-plan-note")
        assert "manual checks the relay pauses for." in _text(screen, "#rp-test-plan-note")


async def test_stages_line_updates_when_a_role_changes(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen = await _open(app, pilot)
        assert "PRD (codex, reviewed by claude)" in _text(screen, "#rp-stages")
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        await pilot.pause()
        assert "PRD (grok, reviewed by claude)" in _text(screen, "#rp-stages")
        screen.query_one("#rp-reviewer", tui.Select).value = "codex"
        await pilot.pause()
        assert "PRD (grok, reviewed by codex)" in _text(screen, "#rp-stages")
