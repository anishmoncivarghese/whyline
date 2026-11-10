from types import SimpleNamespace

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
    pushed = []
    fake = SimpleNamespace(
        session=SimpleNamespace(root=tmp_path),
        push_screen=lambda screen, callback=None: pushed.append(screen),
        _docs_closed=None, render_event=lambda event: None)
    tui.WhylineConsoleApp._open_docs(fake, "job-search", "spec")
    assert len(pushed) == 1 and isinstance(pushed[0], DocsScreen)
    async with Host(pushed[0]).run_test() as pilot:
        assert (pilot.app.screen.entry, pilot.app.screen.key) == ("set:job-search", "spec")


class StubReview:
    def __init__(self):
        self.calls = []

    def approve(self, root, slug, kind, *, approver):
        self.calls.append(("approve", slug, kind, approver))

    def ask_for_changes(self, root, slug, kind, comments, *, section="", progress):
        self.calls.append(("changes", kind, comments, section))
        return ["Goals"]

    def redo(self, root, slug, kind, *, progress):
        self.calls.append(("redo", kind))
        return []

    def stop(self, root, slug):
        self.calls.append(("stop", slug))

    def set_mode(self, root, slug, mode):
        self.calls.append(("mode", mode))

    def edited(self, root, slug, kind, *, editor_name):
        self.calls.append(("edited", kind))
        return 2

    def answer_questions(self, root, slug, kind, answers, *, progress):
        self.calls.append(("answer", kind, answers))
        return []


class StubRunner:
    def __init__(self):
        self.calls = []

    def run(self, root, slug, *, progress=None, **kw):
        self.calls.append(slug)
        return SimpleNamespace(state="waiting", message="")


def _on(tmp_path, **kwargs):
    return Host(_screen(tmp_path, set_slug="job-search", kind="spec", **kwargs))


async def _settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def _visible(screen):
    return {b.id for b in screen.query("#docs-review Button") if b.display}


async def test_buttons_show_only_when_they_apply(tmp_path, library):
    async with _on(tmp_path).run_test() as pilot:
        screen = pilot.app.screen
        shown = _visible(screen)
        assert {"docs-approve", "docs-changes", "docs-edit", "docs-redo", "docs-auto"} <= shown
        assert not shown & {"docs-answer", "docs-stop", "docs-finished"}
        screen.select_entry("product")
        assert _visible(screen) == set()


async def test_approve_on_a_human_set_runs_the_rest(tmp_path, library):
    rev, run = StubReview(), StubRunner()
    async with _on(tmp_path, review=rev, runner=run).run_test() as pilot:
        await pilot.click("#docs-approve")
        await _settle(pilot)
        assert rev.calls == [("approve", "job-search", "spec", "human")]
        assert run.calls == ["job-search"]


async def test_auto_redo_and_stop(tmp_path, library):
    rev, run = StubReview(), StubRunner()
    async with _on(tmp_path, review=rev, runner=run).run_test() as pilot:
        screen = pilot.app.screen
        await pilot.click("#docs-auto")
        await _settle(pilot)
        await pilot.click("#docs-redo")
        await _settle(pilot)
        assert rev.calls == [
            ("approve", "job-search", "spec", "human"), ("mode", "auto"), ("redo", "spec")]
        assert run.calls == ["job-search"]
        found = docset.load(tmp_path, "job-search")
        found.stage = "spec"
        docset.save(tmp_path, found)
        screen.select_entry("set:job-search", "spec")
        assert "docs-stop" in _visible(screen)
        screen.query_one("#docs-stop", Button).press()
        await _settle(pilot)
        assert ("stop", "job-search") in rev.calls


async def test_ask_for_changes_form_lists_sections_and_shows_also_changed(tmp_path, library):
    from textual.widgets import Select, TextArea

    rev = StubReview()
    async with _on(tmp_path, review=rev).run_test() as pilot:
        screen = pilot.app.screen
        await pilot.click("#docs-changes")
        await pilot.pause()
        form = pilot.app.screen
        labels = [label for label, _ in form.section_options]
        assert labels[0] == "Whole document" and len(labels) > 1
        form.query_one("#form-comments", TextArea).text = "Tighten this"
        form.query_one("#form-section", Select).value = labels[1]
        await pilot.click("#form-send")
        await _settle(pilot)
        assert rev.calls == [("changes", "spec", "Tighten this", labels[1])]
        assert str(screen.query_one("#docs-also", Static).render()) == "Also changed: Goals"


async def test_edit_opens_the_file_then_finished_calls_edited(tmp_path, library):
    rev, opened = StubReview(), []
    async with _on(tmp_path, review=rev, opener=opened.append).run_test() as pilot:
        screen = pilot.app.screen
        await pilot.click("#docs-edit")
        assert len(opened) == 1
        assert _visible(screen) == {"docs-finished"}
        await pilot.click("#docs-finished")
        await _settle(pilot)
        assert rev.calls == [("edited", "spec")]


async def test_regaining_focus_finishes_the_edit(tmp_path, library):
    rev = StubReview()
    async with _on(tmp_path, review=rev, opener=lambda path: None).run_test() as pilot:
        screen = pilot.app.screen
        await pilot.click("#docs-edit")
        screen._focus_changed(True)
        await _settle(pilot)
        assert rev.calls == [("edited", "spec")]


async def test_answer_questions_sends_the_answers(tmp_path, library):
    from textual.widgets import TextArea

    found = docset.load(tmp_path, "job-search")
    found.pending_questions["spec"] = ["Who pays?"]
    docset.save(tmp_path, found)
    rev = StubReview()
    async with _on(tmp_path, review=rev).run_test() as pilot:
        await pilot.click("#docs-answer")
        await pilot.pause()
        pilot.app.screen.query_one("#form-comments", TextArea).text = "The user"
        await pilot.click("#form-send")
        await _settle(pilot)
        assert rev.calls == [("answer", "spec", "The user")]


async def test_out_of_date_document_offers_redo_not_resume(tmp_path, library):
    found = docset.load(tmp_path, "job-search")
    found.document("spec")["status"] = docset.Status.OUT_OF_DATE.value
    docset.save(tmp_path, found)
    rev = StubReview()
    async with _on(tmp_path, review=rev).run_test() as pilot:
        screen = pilot.app.screen
        shown = _visible(screen)
        assert "docs-redo" in shown and "docs-resume" not in shown
        assert "docs-auto" not in shown
        await pilot.click("#docs-redo")
        await _settle(pilot)
        assert rev.calls == [("redo", "spec")]


async def test_resume_runs_the_pipeline(tmp_path, library):
    found = docset.load(tmp_path, "job-search")
    found.document("spec")["status"] = docset.Status.APPROVED.value
    docset.save(tmp_path, found)
    run = StubRunner()
    async with _on(tmp_path, runner=run).run_test() as pilot:
        assert "docs-resume" in _visible(pilot.app.screen)
        await pilot.click("#docs-resume")
        await _settle(pilot)
        assert run.calls == ["job-search"]


def _review(tmp_path, *findings, not_run=()):
    from whyline.sdlc import goldfish, lenses

    path = tmp_path / "report.md"
    path.write_text("Blockers: 1 · Major: 1 · Nits: 1 · Not run: none · Reviewer: codex\n", encoding="utf-8")
    return goldfish.Review(path, [lenses.Finding("risk", *f) for f in findings], list(not_run), "codex")


FINDINGS = (
    ("nit", "Goals", "Vague word", "Name it"),
    ("blocker", "Goals", "No owner", "Add one"),
    ("major", "Scope", "Too wide", "Cut it"),
)


async def test_findings_panel_with_and_without_a_review(tmp_path, library):
    async with _on(tmp_path, latest=lambda *a: None).run_test() as pilot:
        assert pilot.app.screen.findings_shown == "Findings\nNot reviewed yet."
    review = _review(tmp_path, *FINDINGS, not_run=["security"])
    async with _on(tmp_path, latest=lambda *a: review).run_test() as pilot:
        text = pilot.app.screen.findings_shown
        assert text.index("🔴 Blocker · Goals · risk") < text.index("🟡 Major") < text.index("🟢 Nit")
        assert text.startswith("Findings\nBlockers: 1") and text.endswith("Not run: security")


async def test_middle_list_shows_counts_after_the_status(tmp_path, library):
    review = _review(tmp_path, *FINDINGS)
    async with _on(tmp_path, latest=lambda *a: review).run_test() as pilot:
        labels = _labels(pilot.app.screen.query_one("#docs-middle", OptionList))
        assert any("In review · 🔴 1 🟡 1 🟢 1 · " in label for label in labels)


async def test_changes_form_adds_ticked_findings_to_the_comments(tmp_path, library):
    from textual.widgets import SelectionList, TextArea

    rev = StubReview()
    review = _review(tmp_path, *FINDINGS)
    async with _on(tmp_path, review=rev, latest=lambda *a: review).run_test() as pilot:
        await pilot.click("#docs-changes")
        await pilot.pause()
        form = pilot.app.screen
        assert form.query_one("#form-findings", SelectionList).selected == [1, 2]
        form.query_one("#form-comments", TextArea).text = "Also this"
        await pilot.click("#form-send")
        await _settle(pilot)
        comments = rev.calls[0][2]
        assert comments == "Also this\nGoals: No owner — Add one\nScope: Too wide — Cut it"


async def test_review_again_runs_and_is_off_while_guard_refuses(tmp_path, library):
    rev = StubReview()
    rev.review_again = lambda root, slug, kind, *, progress: rev.calls.append(("again", kind))
    async with _on(tmp_path, review=rev).run_test() as pilot:
        await pilot.click("#docs-review-again")
        await _settle(pilot)
        assert rev.calls == [("again", "spec")]
    async with _on(tmp_path, check=lambda root: REFUSAL).run_test() as pilot:
        assert "docs-review-again" not in _visible(pilot.app.screen)


def _update_set(tmp_path, name="Edit prd", body="# Product\n\n## Goals\n\nShip it faster.\n"):
    found = docset.create(tmp_path, name, "feature", "human", prd_mode="update", roles=ROLES)
    docset.add_version(tmp_path, found, "prd", body, author="claude", note="x")
    found = docset.load(tmp_path, found.slug)
    found.document("prd")["based_on"] = product.current(tmp_path).version
    docset.save(tmp_path, found)
    return found


def _prd_screen(tmp_path, slug, **kwargs):
    return Host(_screen(tmp_path, set_slug=slug, kind="prd", **kwargs))


async def test_prd_update_shows_changed_sections_and_the_diff(tmp_path, library):
    found = _update_set(tmp_path)
    async with _prd_screen(tmp_path, found.slug).run_test() as pilot:
        screen = pilot.app.screen
        assert screen.shown_text.startswith("Changed sections: Goals")
        assert {"docs-diff", "docs-whole"} <= _visible(screen)
        screen.query_one("#docs-diff", Button).press()
        await pilot.pause()
        assert "-Ship it." in screen.shown_text and "+Ship it faster." in screen.shown_text
        screen.query_one("#docs-whole", Button).press()
        await pilot.pause()
        assert "Ship it faster." in screen.shown_text
        assert "Changed sections" not in screen.shown_text


async def test_moved_prd_disables_approve_until_redo(tmp_path, library):
    found = _update_set(tmp_path)
    product.publish(tmp_path, "# Product\n\n## Goals\n\nElsewhere.\n", set_name="Other",
                    slug="other", approver="anish")
    now = product.current(tmp_path).version
    async with _prd_screen(tmp_path, found.slug, review=StubReview()).run_test() as pilot:
        screen = pilot.app.screen
        assert f"The PRD is now v{now}. Redo this update first." in screen.shown_text
        assert screen.query_one("#docs-approve", Button).disabled
        assert "docs-redo" in _visible(screen)
        again = docset.load(tmp_path, found.slug)
        again.document("prd")["based_on"] = now
        docset.save(tmp_path, again)
        screen.select_entry("set:" + found.slug, "prd")
        assert not screen.query_one("#docs-approve", Button).disabled
        assert "Redo this update first" not in screen.shown_text


async def test_prd_row_says_waiting_when_another_set_holds_the_claim(tmp_path, library):
    holder = _update_set(tmp_path, "Holder")
    waiting = _update_set(tmp_path, "Waiter")
    assert product.claim_update(tmp_path, holder.slug)
    async with _prd_screen(tmp_path, waiting.slug).run_test() as pilot:
        labels = _labels(pilot.app.screen.query_one("#docs-middle", OptionList))
        assert any(f"Waiting: {holder.slug} is updating the PRD" in text for text in labels)
    async with _prd_screen(tmp_path, holder.slug).run_test() as pilot:
        labels = _labels(pilot.app.screen.query_one("#docs-middle", OptionList))
        assert not any("Waiting:" in text for text in labels)


def _built(tmp_path, **fields):
    found = docset.load(tmp_path, "job-search")
    found.document("build-record")["status"] = "approved"
    for name, value in fields.items():
        setattr(found, name, value)
    docset.save(tmp_path, found)


def _set_buttons(screen):
    return {b.id for b in screen.query("#docs-actions Button") if b.display}


def _status(screen):
    return str(screen.query_one("#docs-status", Static).render())


class StubClose:
    def __init__(self, error=""):
        self.calls, self.error = [], error

    def __call__(self, root, slug):
        self.calls.append(slug)
        return SimpleNamespace(error=self.error, state="released", version="1.2", tag="v1.2")


async def test_close_shows_on_an_approved_build_record_and_calls_close(tmp_path, library):
    closer = StubClose()
    async with _on(tmp_path, closer=closer).run_test() as pilot:
        assert "docs-close-set" not in _set_buttons(pilot.app.screen)
    _built(tmp_path)
    async with _on(tmp_path, closer=closer).run_test() as pilot:
        assert "docs-close-set" in _set_buttons(pilot.app.screen)
        assert "docs-pr" not in _set_buttons(pilot.app.screen)
        await pilot.click("#docs-close-set")
        await _settle(pilot)
        assert closer.calls == ["job-search"]
        assert "released v1.2" in _status(pilot.app.screen)


async def test_close_shows_a_refusal(tmp_path, library):
    _built(tmp_path)
    closer = StubClose(error="Approve the build record before closing the feature.")
    async with _on(tmp_path, closer=closer).run_test() as pilot:
        await pilot.click("#docs-close-set")
        await _settle(pilot)
        assert "Approve the build record" in _status(pilot.app.screen)


async def test_open_pull_request_asks_first_then_shows_the_url(tmp_path, library):
    _built(tmp_path, state="built")
    calls = []

    def opener(root, docs, slug):
        calls.append(slug)
        return "https://github.com/a/b/pull/7"

    async with _on(tmp_path, pr_opener=opener).run_test() as pilot:
        screen = pilot.app.screen
        shown = _set_buttons(screen)
        assert "docs-pr" in shown and "docs-close-set" not in shown
        await pilot.click("#docs-pr")
        await pilot.pause()
        question = str(pilot.app.screen.query_one("#confirm-question", Static).render())
        assert question.startswith("Push ") and question.endswith(" to origin and open a pull request?")
        await pilot.click("#confirm-no")
        await _settle(pilot)
        assert calls == []
        await pilot.click("#docs-pr")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await _settle(pilot)
        assert calls == ["job-search"]
        assert "https://github.com/a/b/pull/7" in _status(screen)


async def test_open_pull_request_hides_once_a_pr_exists(tmp_path, library):
    _built(tmp_path, state="released", version="1.2", pr_url="https://x/pull/1")
    async with _on(tmp_path).run_test() as pilot:
        assert _set_buttons(pilot.app.screen).isdisjoint({"docs-pr", "docs-close-set"})


async def test_plan_row_shows_the_coverage_line_and_the_location_line(tmp_path, library, monkeypatch):
    from whyline.sdlc import trace

    monkeypatch.setattr(
        trace, "coverage", lambda docs, found: SimpleNamespace(line=lambda: "Covers 2 of 3 requirements")
    )
    async with _on(tmp_path).run_test() as pilot:
        screen = pilot.app.screen
        labels = _labels(screen.query_one("#docs-middle", OptionList))
        assert any("Covers 2 of 3 requirements" in label for label in labels)
        assert str(screen.query_one("#docs-location", Static).render()).startswith(f"Documents: {tmp_path}")
