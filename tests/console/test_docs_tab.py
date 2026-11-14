import json
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import Button, OptionList, Static

from whyline.console import tui
from whyline.console.docs_screen import DocsScreen
from whyline.console.file_pane import linked_design, owning_set
from whyline.sdlc import docset

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

ROLES = {"implementer": "claude"}


def _plan(root, name, text="# plan\n"):
    config = root / ".whyline" / "relay" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("plan = " + json.dumps("plans/" + name) + "\n", encoding="utf-8")
    plan = root / "plans" / name
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(text, encoding="utf-8")


def _set(root):
    found = docset.create(root, "Job search", "feature", "human", roles=ROLES)
    docset.add_version(root, found, "spec", "# Spec\n\nThe spec text.\n", author="claude", note="x")
    return found


async def _open_docs_tab(pilot):
    await pilot.click("#mode-relay")
    await pilot.pause()
    await pilot.click("#see-files")
    await pilot.pause()
    await pilot.click("#file-docs")
    await pilot.pause()
    await pilot.pause()


async def test_docs_tab_shows_the_owning_set(tmp_path):
    _set(tmp_path)
    _plan(tmp_path, "job-search.plan.md")
    assert owning_set(tmp_path) == (tmp_path, "job-search")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_docs_tab(pilot)
        panel = app.query_one("#file-docs-panel")
        assert panel.display is True
        assert app.query_one("#file-view").display is False
        assert str(app.query_one("#file-docs-status", Static).renderable) == "job-search"
        listed = app.query_one("#file-docs-list", OptionList)
        labels = [str(listed.get_option_at_index(i).prompt) for i in range(listed.option_count)]
        assert any(label.startswith("Spec") for label in labels)
        panel.select_document("spec")
        assert "The spec text." in panel.shown_text
        assert app.query_one("#file-docs-open", Button).display is True


async def test_docs_tab_open_in_docs_pushes_the_screen(tmp_path):
    _set(tmp_path)
    _plan(tmp_path, "job-search.plan.md")
    app = tui.WhylineConsoleApp(root=tmp_path)
    opened = []
    app.open_docs = lambda slug=None, kind=None: opened.append((slug, kind))
    async with app.run_test() as pilot:
        await _open_docs_tab(pilot)
        app.query_one("#file-docs-open", Button).press()
        await pilot.pause()
        assert opened and opened[0][0] == "job-search"


async def test_docs_tab_without_a_set(tmp_path):
    _plan(tmp_path, "other.plan.md")
    assert owning_set(tmp_path) is None
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_docs_tab(pilot)
        assert str(app.query_one("#file-docs-status", Static).renderable) == (
            "This plan has no document set."
        )
        assert app.query_one("#file-docs-open", Button).display is False


def _spec(root, text="# Design\n\nThe design text.\n"):
    spec = root / "docs" / "superpowers" / "specs" / "d.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(text, encoding="utf-8")
    return spec


def test_linked_design_from_header_spec_field(tmp_path):
    spec = _spec(tmp_path)
    _plan(tmp_path, "x.plan.md",
          "<!-- whyline-plan v1 | source: hand | spec: docs/superpowers/specs/d.md | created: t -->\n# x\n")
    assert linked_design(tmp_path) == spec


def test_linked_design_from_design_line(tmp_path):
    spec = _spec(tmp_path)
    _plan(tmp_path, "x.plan.md",
          "<!-- whyline-plan v1 -->\n# x\n\nRuns first. Design: `docs/superpowers/specs/d.md`. Read it.\n")
    assert linked_design(tmp_path) == spec


def test_linked_design_from_spec_line(tmp_path):
    spec = _spec(tmp_path)
    _plan(tmp_path, "x.plan.md", "# x\n\nSpec: `docs/superpowers/specs/d.md`.\n")
    assert linked_design(tmp_path) == spec


def test_linked_design_ignores_missing_outside_and_late_links(tmp_path):
    _plan(tmp_path, "a.plan.md", "# x\n\nDesign: `docs/missing.md`.\n")
    assert linked_design(tmp_path) is None
    outside = tmp_path.parent / "outside-design.md"
    outside.write_text("secret", encoding="utf-8")
    _plan(tmp_path, "b.plan.md", "# x\n\nDesign: `../outside-design.md`.\n")
    assert linked_design(tmp_path) is None
    _spec(tmp_path)
    late = "# x\n" + "line\n" * 40 + "Design: `docs/superpowers/specs/d.md`\n"
    _plan(tmp_path, "c.plan.md", late)
    assert linked_design(tmp_path) is None


async def test_docs_tab_without_a_set_shows_the_linked_design(tmp_path):
    _spec(tmp_path)
    _plan(tmp_path, "other.plan.md", "# x\n\nDesign: `docs/superpowers/specs/d.md`.\n")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_docs_tab(pilot)
        status = str(app.query_one("#file-docs-status", Static).renderable)
        assert status == "Design (from the plan): docs/superpowers/specs/d.md"
        panel = app.query_one("#file-docs-panel")
        assert "The design text." in panel.shown_text
        assert app.query_one("#file-docs-open", Button).display is False
        assert app.query_one("#file-docs-list", OptionList).option_count == 0


async def test_leaving_the_docs_tab_restores_the_file_view(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _open_docs_tab(pilot)
        await pilot.click("#file-plan")
        await pilot.pause()
        assert app.query_one("#file-docs-panel").display is False
        assert app.query_one("#file-view").display is True


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    def on_mount(self):
        self.push_screen(self._screen)


async def test_export_pack_shows_files_and_notes_and_reveals(tmp_path):
    _set(tmp_path)
    out = tmp_path / "out.docx"
    calls, revealed = [], []

    def stub(docs, slug):
        calls.append(slug)
        return SimpleNamespace(files=[out], notes=["PDF skipped."])

    screen = DocsScreen(tmp_path, docs=tmp_path, check=lambda root: None,
                        export_pack=stub, revealer=revealed.append,
                        set_slug="job-search", kind="spec")
    async with Host(screen).run_test() as pilot:
        await pilot.pause()
        reveal = screen.query_one("#docs-reveal", Button)
        assert reveal.display is False
        screen.query_one("#docs-export", Button).press()
        for _ in range(100):
            if reveal.display:
                break
            await pilot.pause(0.05)
        assert calls == ["job-search"]
        text = str(screen.query_one("#docs-status", Static).renderable)
        assert str(out) in text and "PDF skipped." in text
        screen.query_one("#docs-reveal", Button).press()
        await pilot.pause()
        assert revealed == [out]
