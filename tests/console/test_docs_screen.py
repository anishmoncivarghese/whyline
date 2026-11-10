import pytest
from textual.app import App
from textual.widgets import Button, OptionList, Static

from whyline.console import tui
from whyline.console.docs_screen import DocsScreen
from whyline.sdlc import docset, product

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

ROLES = {"implementer": "claude"}
PRD = "# Product\n\n## Goals\n\nShip it.\n"
REFUSAL = "A relay is running in the documents checkout. Wait for it to finish."


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    def on_mount(self):
        self.push_screen(self._screen)


def _screen(tmp_path, check=lambda root: None, **kwargs):
    return DocsScreen(tmp_path, docs=tmp_path, check=check, **kwargs)


def _labels(widget):
    return [str(widget.get_option_at_index(i).prompt) for i in range(widget.option_count)]


@pytest.fixture
def library(tmp_path):
    product.publish(tmp_path, PRD, set_name="First", slug="first", approver="anish")
    found = docset.create(tmp_path, "Job search", "feature", "human", roles=ROLES)
    docset.add_version(tmp_path, found, "prd", "# PRD\n\nBody.\n", author="claude", note="x")
    docset.add_version(tmp_path, found, "spec", "# Spec\n\nThe spec text.\n", author="claude", note="x")
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "loose.plan.md").write_text("<!-- whyline-plan v1 -->\n- [ ] A-1: do\n", encoding="utf-8")
    return found


async def test_lists_product_first_then_sets_and_earlier_plans(tmp_path, library):
    async with Host(_screen(tmp_path)).run_test() as pilot:
        screen = pilot.app.screen
        left = _labels(screen.query_one("#docs-left", OptionList))
        assert left[0] == "Product PRD v1.0"
        assert left[1] == "Document sets"
        assert left[2].startswith("Job search · Feature")
        assert left[3:] == ["Earlier plans", "loose"]
        assert screen.entry == "product"
        assert "Ship it." in screen.shown_text
        middle = _labels(screen.query_one("#docs-middle", OptionList))
        assert middle[0].startswith("Product PRD · v1.0 · approved by anish")
        assert middle[1] == "Changelog"


async def test_selecting_a_set_lists_its_documents_and_a_document_renders(tmp_path, library):
    async with Host(_screen(tmp_path)).run_test() as pilot:
        screen = pilot.app.screen
        screen.select_entry("set:job-search")
        middle = _labels(screen.query_one("#docs-middle", OptionList))
        assert middle[0].startswith("Prd · ") and "In review" in middle[0]
        assert any(row.startswith("Spec · v1 · In review · not approved") for row in middle)
        screen.select_document("spec")
        assert "The spec text." in screen.shown_text


async def test_opens_on_the_given_set_and_document(tmp_path, library):
    async with Host(_screen(tmp_path, set_slug="job-search", kind="spec")).run_test() as pilot:
        screen = pilot.app.screen
        assert (screen.entry, screen.key) == ("set:job-search", "spec")
        assert "The spec text." in screen.shown_text


async def test_out_of_date_document_shows_its_reason_under_the_row(tmp_path, library):
    found = docset.load(tmp_path, "job-search")
    doc = found.document("spec")
    doc["status"] = docset.Status.OUT_OF_DATE.value
    doc["out_of_date_reason"] = "PRD changed (v1 → v2) after this was approved"
    docset.save(tmp_path, found)
    async with Host(_screen(tmp_path, set_slug="job-search")).run_test() as pilot:
        middle = _labels(pilot.app.screen.query_one("#docs-middle", OptionList))
        row = next(r for r in middle if r.startswith("Spec"))
        assert "Out of date" in row.splitlines()[0]
        assert row.splitlines()[1].strip() == "PRD changed (v1 → v2) after this was approved"


async def test_read_only_while_a_relay_runs(tmp_path, library):
    async with Host(_screen(tmp_path, check=lambda root: REFUSAL, set_slug="job-search")).run_test() as pilot:
        screen = pilot.app.screen
        assert str(screen.query_one("#docs-reason", Static).render()) == REFUSAL
        for button_id in ("docs-check", "docs-open"):
            assert screen.query_one(f"#{button_id}", Button).disabled
        for button_id in ("docs-history", "docs-export"):
            assert not screen.query_one(f"#{button_id}", Button).disabled
        screen.query_one("#docs-history", Button).press()
        await pilot.pause()
        assert screen.shown_text.startswith("No earlier versions") or "History" in screen.shown_text


async def test_actions_are_on_when_nothing_refuses(tmp_path, library):
    async with Host(_screen(tmp_path, set_slug="job-search")).run_test() as pilot:
        screen = pilot.app.screen
        assert str(screen.query_one("#docs-reason", Static).render()) == ""
        for button_id in ("docs-check", "docs-open", "docs-history", "docs-export"):
            assert not screen.query_one(f"#{button_id}", Button).disabled


async def test_open_docs_from_start_pushes_the_screen_on_that_set(tmp_path, library):
    from types import SimpleNamespace

    pushed = []
    fake = SimpleNamespace(
        session=SimpleNamespace(root=tmp_path), push_screen=pushed.append,
        render_event=lambda event: None)
    tui.WhylineConsoleApp._open_docs(fake, "job-search", "spec")
    assert len(pushed) == 1 and isinstance(pushed[0], DocsScreen)
    async with Host(pushed[0]).run_test() as pilot:
        assert (pilot.app.screen.entry, pilot.app.screen.key) == ("set:job-search", "spec")
