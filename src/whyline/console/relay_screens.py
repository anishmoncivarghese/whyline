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
    RelayPlanScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
    /* Textual's own :focus rule adds a tall border, which on a one-line
       checkbox covers the label entirely; its label highlight is enough. */
    RelayPlanScreen Checkbox:focus { border: none; }
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
        from whyline.console.repl import BRAINSTORM_AGENTS
        from whyline.console.tui import brainstorm_field_widgets

        usable = [a for a in BRAINSTORM_AGENTS if self._status[a]["available"]]
        default = self._active if self._active in usable else (usable or ["claude"])[0]
        docs = relay_ops.brainstorm_docs(self._root)
        return [
            Horizontal(
                Label("From:", classes="field-label"),
                Select([("New brainstorm", "new"), *((doc, doc) for doc in docs)],
                       value="new", allow_blank=False, id="rp-from"),
            ),
            Horizontal(
                Label("Plan writer:", classes="field-label"),
                Select([(a, a) for a in (usable or ["claude"])], value=default,
                       allow_blank=False, id="rp-writer"),
                id="rp-writer-row",
            ),
            Vertical(*brainstorm_field_widgets(self._status, default), id="rp-new-group"),
        ]

    def on_mount(self) -> None:
        self._set_state("form")
        self._show_source("draft")
        self.query_one("#rp-writer-row").display = False
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
        elif event.select.id == "rp-from":
            new = event.value == "new"
            self.query_one("#rp-new-group").display = new
            # A new brainstorm's own "Final write-up" also writes the plan.
            self.query_one("#rp-writer-row").display = not new

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
        from whyline.console import adapters
        from whyline.console.tui import collect_brainstorm

        root = self._root
        chosen = self.query_one("#rp-from", Select).value
        if chosen != "new":
            writer = self.query_one("#rp-writer", Select).value
            self._run(
                lambda progress: relay_ops.plan_from_brainstorm(
                    root, chosen, writer, progress=progress
                ),
                self._show_review,
            )
            return
        choice = collect_brainstorm(self.query_one)
        if isinstance(choice, str):
            self._error(choice)
            return

        def work(progress):
            result = adapters.run_brainstorm(root, progress=progress, **choice)
            if result.kind == "error":
                raise RuntimeError(result.text)
            return relay_ops.plan_from_brainstorm(
                root,
                choice["topic"],
                choice["final_agent"],
                progress=progress,
                timeout_minutes=choice["timeout_minutes"],
            )

        self._run(work, self._show_review)

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


class RelaySetupScreen(ModalScreen):
    """Who implements, tests and reviews; a check (doctor); then Start.
    Start is only enabled by a check with no FAIL, and any edit after a
    check clears it, so nothing starts on settings nobody checked."""

    DEFAULT_CSS = """
    RelaySetupScreen { align: center middle; }
    RelaySetupScreen > Vertical {
        width: 90; max-width: 100%; height: auto; max-height: 100%; padding: 0 2;
        border: thick $accent; background: $surface;
    }
    RelaySetupScreen Horizontal { height: auto; }
    RelaySetupScreen .field-label { width: 18; padding: 1 1 0 0; }
    RelaySetupScreen Select { width: 30; }
    RelaySetupScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
    RelaySetupScreen Checkbox:focus { border: none; }
    RelaySetupScreen #rs-results { height: auto; max-height: 12; }
    RelaySetupScreen #rs-error { color: $error; height: auto; }
    RelaySetupScreen #rs-error.-empty { display: none; }
    RelaySetupScreen #rs-buttons { margin-top: 1; }
    RelaySetupScreen #rs-buttons Button { margin-right: 2; }
    """

    ROLES = (("implementer", "Implementer:"), ("tester", "Tester:"), ("reviewer", "Reviewer:"))

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root
        self._agents = relay_ops.relay_agents(root)
        self._roles = relay_ops.current_roles(root)
        self._token: object | None = None
        self._filling = True  # ignore change events while the form is built

    def compose(self) -> ComposeResult:
        rows = [
            Horizontal(
                Label(label, classes="field-label"),
                Select(
                    [(a, a) for a in self._agents],
                    value=self._roles.get(role)
                    if self._roles.get(role) in self._agents
                    else (self._agents[0] if self._agents else None),
                    allow_blank=False,
                    id=f"rs-{role}",
                ),
            )
            for role, label in self.ROLES
        ]
        backups = [
            Checkbox(agent, value=agent in self._roles.get("backup", []), id=f"rs-backup-{agent}")
            for agent in self._agents
        ]
        yield Vertical(
            Label("Set up: who does what, then check everything is ready."),
            *rows,
            Label("Backup, used when an agent fails:"),
            *backups,
            VerticalScroll(Static("", id="rs-checks"), id="rs-results"),
            Static("", id="rs-error", classes="-empty"),
            Horizontal(
                Button("Check", id="rs-check", variant="primary"),
                Button("Start", id="rs-start", variant="success", disabled=True),
                Button("Cancel", id="rs-cancel"),
                id="rs-buttons",
            ),
        )

    def on_mount(self) -> None:
        self.call_after_refresh(self._ready)

    def _ready(self) -> None:
        self._filling = False

    def _error(self, text: str) -> None:
        error = self.query_one("#rs-error", Static)
        error.update(text)
        error.set_class(not text, "-empty")

    def _invalidate(self) -> None:
        if self._filling:
            return
        self._token = object()
        self.query_one("#rs-checks", Static).update("")
        self.query_one("#rs-start", Button).disabled = True

    def on_select_changed(self, event: "Select.Changed") -> None:
        self._invalidate()

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        self._invalidate()

    def _chosen(self) -> tuple[str, str, str, list[str]]:
        implementer, tester, reviewer = (
            self.query_one(f"#rs-{role}", Select).value for role, _ in self.ROLES
        )
        backup = [a for a in self._agents if self.query_one(f"#rs-backup-{a}", Checkbox).value]
        return implementer, tester, reviewer, backup

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "rs-cancel":
            self._token = object()
            self.dismiss(None)
        elif event.button.id == "rs-start":
            self.dismiss("start")
        elif event.button.id == "rs-check":
            self._check()

    def _check(self) -> None:
        token = object()
        self._token = token
        self._error("")
        self.query_one("#rs-start", Button).disabled = True
        self.query_one("#rs-checks", Static).update("Checking…")
        root, chosen = self._root, self._chosen()

        def in_thread() -> None:
            try:
                relay_ops.save_roles(root, *chosen)
                checks = relay_ops.run_checks(root)
                running = relay_ops.live_run(root)
            except Exception as error:
                self.app.call_from_thread(self._check_failed, error, token)
                return
            self.app.call_from_thread(self._show_checks, checks, running, token)

        self.run_worker(in_thread, thread=True)

    def _check_failed(self, error: Exception, token: object) -> None:
        if token is not self._token:
            return
        self.query_one("#rs-checks", Static).update("")
        self._error(str(error) or error.__class__.__name__)

    def _show_checks(self, checks: list, running: str | None, token: object) -> None:
        if token is not self._token:
            return
        lines = []
        for check in checks:
            line = f"{check.status:<4}  {check.message}"
            if check.status != "ok" and check.hint:
                line += f"\n      fix: {check.hint}"
            lines.append(line)
        failures = sum(check.status == "FAIL" for check in checks)
        lines.append("All checks passed." if failures == 0 else f"{failures} problem(s) found.")
        self.query_one("#rs-checks", Static).update("\n".join(lines))
        if running:
            self._error(f"A relay is already running here ({running}).")
        self.query_one("#rs-start", Button).disabled = failures > 0 or bool(running)
