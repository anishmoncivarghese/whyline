"""The Relay-mode popups: Plan (make and approve plan.md) and Set up
(roles, checks, start). Every relay call goes through relay_ops, run in a
worker thread; results come back through call_from_thread and are dropped
if the user cancelled in the meantime (the same token pattern the console
uses for chat replies)."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from whyline.console import relay_ops

_SOURCES = [
    ("Draft from a description", "draft"),
    ("Paste a plan", "paste"),
    ("From a brainstorm", "brainstorm"),
]

_STATE_BUTTONS = {
    "form": {"rp-go", "rp-cancel"},
    "working": {"rp-cancel"},
    "review": {"rp-approve", "rp-changes", "rp-cancel"},
}


class RelayPlanScreen(ModalScreen):
    DEFAULT_CSS = """
    RelayPlanScreen { align: center middle; }
    RelayPlanScreen > Vertical {
        width: 96; max-width: 100%; height: auto; max-height: 100%; padding: 0 2;
        border: thick $accent; background: $surface;
    }
    RelayPlanScreen #rp-form, RelayPlanScreen #rp-review { height: auto; max-height: 1fr; }
    RelayPlanScreen Vertical, RelayPlanScreen Horizontal { height: auto; }
    RelayPlanScreen .field-label { width: 18; padding: 1 1 0 0; }
    RelayPlanScreen TextArea { height: 8; }
    RelayPlanScreen #rp-refs { height: 4; }
    RelayPlanScreen #rp-source { width: 40; }
    RelayPlanScreen #rp-error { color: $error; height: auto; }
    RelayPlanScreen #rp-error.-empty { display: none; }
    RelayPlanScreen #rp-buttons { margin-top: 1; }
    RelayPlanScreen #rp-buttons Button { margin-right: 1; }
    """

    def __init__(self, root: Path, status: dict, active: str) -> None:
        super().__init__()
        self._root = root
        self._status = status
        self._active = active
        self._token: object | None = None
        self._draft: relay_ops.Draft | None = None
        self._state: str = "form"

    def compose(self) -> ComposeResult:
        form = VerticalScroll(
            Label("Plan: make plan.md, the task list the relay works through."),
            Horizontal(
                Label("Source:", classes="field-label"),
                Select(_SOURCES, value="draft", allow_blank=False, id="rp-source"),
            ),
            Vertical(
                Label("Paste the plan (each task as `- [ ] ID: title`):"),
                TextArea(id="rp-paste"),
                id="rp-paste-group",
            ),
            Vertical(
                Label("What should the plan build?"),
                TextArea(id="rp-description"),
                Label("Reference documents, one path per line (e.g. PRD.md):"),
                TextArea(id="rp-refs"),
                id="rp-draft-group",
            ),
            Vertical(*self._brainstorm_widgets(), id="rp-brainstorm-group"),
            id="rp-form",
        )
        yield Vertical(
            form,
            Vertical(Static("", id="rp-progress"), id="rp-working"),
            VerticalScroll(
                Static("", id="rp-draft"),
                Input(placeholder="What should change?", id="rp-feedback"),
                id="rp-review",
            ),
            Static("", id="rp-error", classes="-empty"),
            Horizontal(
                Button("Save", id="rp-go", variant="success"),
                Button("Approve", id="rp-approve", variant="success"),
                Button("Request changes", id="rp-changes"),
                Button("Send changes", id="rp-send-changes", variant="primary"),
                Button("Resume draft", id="rp-resume-draft", variant="primary"),
                Button("Discard it", id="rp-discard-draft", variant="warning"),
                Button("Cancel", id="rp-cancel"),
                id="rp-buttons",
            ),
        )

    def _brainstorm_widgets(self) -> list:
        """Filled in by Task 11; empty until then."""
        return [Label("Brainstorm source: coming in a later task.")]

    def on_mount(self) -> None:
        self._set_state("form")
        self._show_source("draft")
        pending = relay_ops.pending_draft(self._root)
        if pending:
            self._error(f'A plan draft for "{pending}" was left unfinished.')
            self.query_one("#rp-resume-draft").display = True
            self.query_one("#rp-discard-draft").display = True

    # -- state -----------------------------------------------------------
    def _set_state(self, state: str) -> None:
        self._state = state
        self.query_one("#rp-form").display = state == "form"
        self.query_one("#rp-working").display = state == "working"
        self.query_one("#rp-review").display = state == "review"
        self.query_one("#rp-feedback").display = False
        visible = _STATE_BUTTONS[state]
        for button in self.query("#rp-buttons Button"):
            button.display = button.id in visible
        self.query_one("#rp-go", Button).label = (
            "Save" if self._source() == "paste" else "Make the plan"
        )

    def _source(self) -> str:
        return self.query_one("#rp-source", Select).value

    def _show_source(self, source: str) -> None:
        for name in ("paste", "draft", "brainstorm"):
            self.query_one(f"#rp-{name}-group").display = name == source
        self.query_one("#rp-go", Button).label = (
            "Save" if source == "paste" else "Make the plan"
        )

    def on_select_changed(self, event: "Select.Changed") -> None:
        if event.select.id == "rp-source":
            self._show_source(event.value)

    def _error(self, text: str) -> None:
        error = self.query_one("#rp-error", Static)
        error.update(text)
        error.set_class(not text, "-empty")

    # -- running work off the UI thread -----------------------------------
    def _progress(self, token: object):
        def report(line: str) -> None:
            self.app.call_from_thread(self._add_progress, line, token)

        return report

    def _add_progress(self, line: str, token: object) -> None:
        if token is not self._token:
            return
        progress = self.query_one("#rp-progress", Static)
        progress.update(f"{progress.renderable}\n· {line}".strip())

    def _run(self, work, on_done) -> None:
        """Runs work(progress) in a thread. on_done(result) runs on the UI
        thread; an exception is shown in the error line and returns to the
        form with every input still filled in."""
        token = object()
        self._token = token
        self._error("")
        self.query_one("#rp-progress", Static).update("Working…")
        self._set_state("working")

        def in_thread() -> None:
            try:
                result = work(self._progress(token))
            except Exception as error:  # agent missing, timed out, parse failure...
                self.app.call_from_thread(self._failed, error, token)
                return
            self.app.call_from_thread(self._succeeded, on_done, result, token)

        self.run_worker(in_thread, thread=True)

    def _succeeded(self, on_done, result, token: object) -> None:
        if token is self._token:
            on_done(result)

    def _failed(self, error: Exception, token: object) -> None:
        if token is not self._token:
            return
        self._set_state("form")
        self._error(str(error) or error.__class__.__name__)

    # -- saving ----------------------------------------------------------
    def _confirm_replace(self, retry) -> None:
        from whyline.console.tui import ConfirmScreen

        def answered(confirmed: bool) -> None:
            if confirmed:
                retry()

        self.app.push_screen(
            ConfirmScreen("plan.md already exists. Replace it?", "Replace"), answered
        )

    def _save_paste(self, replace: bool = False) -> None:
        text = self.query_one("#rp-paste", TextArea).text
        try:
            path = relay_ops.save_pasted_plan(self._root, text, replace=replace)
        except relay_ops.plan_exists_error():
            self._confirm_replace(lambda: self._save_paste(replace=True))
            return
        except ValueError as error:
            self._error(str(error))
            return
        self.dismiss(path)

    # -- buttons ---------------------------------------------------------
    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        handler = getattr(self, f"_on_{event.button.id.replace('-', '_')}", None)
        if handler is not None:
            handler()

    def _on_rp_cancel(self) -> None:
        self._token = object()  # a late result from a cancelled run is dropped
        if self._state == "review" and self._draft is not None:
            relay_ops.discard_draft(self._root, self._draft)
        self.dismiss(None)

    def _on_rp_go(self) -> None:
        source = self._source()
        if source == "paste":
            self._save_paste()
        elif source == "draft":
            self._start_draft()
        else:
            self._start_brainstorm()

    def _start_brainstorm(self) -> None:
        """Filled in by Task 11."""
        self._error("Brainstorm source: coming in a later task.")

    def _start_draft(self) -> None:
        description = self.query_one("#rp-description", TextArea).text.strip()
        if not description:
            self._error("Describe what the plan should build.")
            return
        refs = [
            line.strip()
            for line in self.query_one("#rp-refs", TextArea).text.splitlines()
            if line.strip()
        ]
        missing = relay_ops.missing_references(self._root, refs)
        if missing:
            self._error("Can't find: " + ", ".join(missing))
            return
        root = self._root

        def work(progress):
            try:
                return relay_ops.draft_plan(root, description, refs, progress=progress)
            except relay_ops.in_progress_error() as error:
                raise RuntimeError(
                    "A plan draft is already unfinished -- close this and open Plan "
                    "again to resume or discard it."
                ) from error

        self._run(work, self._show_review)

    def _show_review(self, draft: relay_ops.Draft) -> None:
        self._draft = draft
        self.query_one("#rp-draft", Static).update(draft.text)
        self._set_state("review")

    def _on_rp_approve(self, replace: bool = False) -> None:
        try:
            path = relay_ops.approve_plan(self._root, self._draft, replace=replace)
        except relay_ops.plan_exists_error():
            self._confirm_replace(lambda: self._on_rp_approve(replace=True))
            return
        except ValueError as error:  # plan.PlanError: the draft isn't a usable plan
            self._error(f"{error}. The draft is still at {self._draft.path}.")
            return
        self.dismiss(path)

    def _on_rp_changes(self) -> None:
        feedback = self.query_one("#rp-feedback", Input)
        feedback.display = True
        self.query_one("#rp-send-changes").display = True
        self.query_one("#rp-changes").display = False
        feedback.focus()

    def _on_rp_send_changes(self) -> None:
        feedback = self.query_one("#rp-feedback", Input).value.strip()
        if not feedback:
            self._error("Say what should change.")
            return
        draft, root = self._draft, self._root
        self.query_one("#rp-feedback", Input).value = ""
        self._run(
            lambda progress: relay_ops.revise_plan(
                root, draft, feedback, progress=progress
            ),
            self._show_review,
        )

    def _on_rp_resume_draft(self) -> None:
        root = self._root
        self._run(
            lambda progress: relay_ops.resume_draft(root, progress=progress),
            self._show_review,
        )

    def _on_rp_discard_draft(self) -> None:
        relay_ops.discard_draft(self._root, None)
        self._error("")
        self.query_one("#rp-resume-draft").display = False
        self.query_one("#rp-discard-draft").display = False
