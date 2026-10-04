"""The Relay-mode popups: Plan (make and approve plan.md) and Set up
(roles, checks, start). Every relay call goes through relay_ops, run in a
worker thread; results come back through call_from_thread and are dropped
if the user cancelled in the meantime (the same token pattern the console
uses for chat replies)."""

from __future__ import annotations

from dataclasses import replace as dc_replace
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from whyline.console import relay_ops
from whyline.console.plan_job import PlanRequest

_SOURCES = [
    ("Draft from a description", "draft"),
    ("Paste a plan", "paste"),
    ("From a brainstorm", "brainstorm"),
]


class RelayPlanScreen(ModalScreen):
    """Collects what to plan, then dismisses with a PlanRequest; the main
    window runs it, shows progress and the draft, and asks the questions.
    Pasting is instant, so a pasted plan is still saved here."""

    DEFAULT_CSS = """
    RelayPlanScreen { align: center middle; }
    RelayPlanScreen > Vertical {
        width: 96; max-width: 100%; height: auto; max-height: 100%; padding: 0 2;
        border: thick $accent; background: $surface;
    }
    RelayPlanScreen #rp-form { height: auto; max-height: 1fr; }
    RelayPlanScreen Vertical, RelayPlanScreen Horizontal { height: auto; }
    RelayPlanScreen .field-label { width: 18; padding: 1 1 0 0; }
    RelayPlanScreen TextArea { height: 8; }
    RelayPlanScreen #rp-refs { height: 4; }
    RelayPlanScreen #rp-source, RelayPlanScreen #rp-drafter, RelayPlanScreen #rp-reviewer { width: 40; }
    RelayPlanScreen #rp-name { width: 1fr; }
    RelayPlanScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
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
        self._agents = relay_ops.relay_agents(root) or ["claude", "codex"]
        self._planner = relay_ops.planner_agents(root)

    def _agent_select(self, wanted: str, select_id: str) -> Select:
        value = wanted if wanted in self._agents else self._agents[0]
        return Select([(a, a) for a in self._agents], value=value, allow_blank=False, id=select_id)

    def compose(self) -> ComposeResult:
        drafter, reviewer = self._planner
        form = VerticalScroll(
            Label("Plan: make a plan the relay works through, saved under plans/."),
            Horizontal(
                Label("Plan name:", classes="field-label"),
                Input(placeholder="leave empty to name it from the description", id="rp-name"),
            ),
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
                Horizontal(
                    Label("Drafter:", classes="field-label"),
                    self._agent_select(drafter, "rp-drafter"),
                ),
                Horizontal(
                    Label("Reviewer:", classes="field-label"),
                    self._agent_select(reviewer, "rp-reviewer"),
                ),
                id="rp-draft-group",
            ),
            Vertical(*self._brainstorm_widgets(), id="rp-brainstorm-group"),
            id="rp-form",
        )
        yield Vertical(
            form,
            Static("", id="rp-error", classes="-empty"),
            Horizontal(
                Button("Make the plan", id="rp-go", variant="success"),
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
                Select(
                    [("New brainstorm", "new"), *((doc, doc) for doc in docs)],
                    value="new",
                    allow_blank=False,
                    id="rp-from",
                ),
            ),
            Horizontal(
                Label("Plan writer:", classes="field-label"),
                Select(
                    [(a, a) for a in (usable or ["claude"])],
                    value=default,
                    allow_blank=False,
                    id="rp-writer",
                ),
                id="rp-writer-row",
            ),
            Vertical(*brainstorm_field_widgets(self._status, default), id="rp-new-group"),
        ]

    def on_mount(self) -> None:
        self._show_source("draft")
        self.query_one("#rp-writer-row").display = False
        pending = relay_ops.pending_draft(self._root)
        self.query_one("#rp-resume-draft").display = bool(pending)
        self.query_one("#rp-discard-draft").display = bool(pending)
        if pending:
            self._error(f'A plan draft for "{pending}" was left unfinished.')

    def _source(self) -> str:
        return self.query_one("#rp-source", Select).value

    def _show_source(self, source: str) -> None:
        for name in ("paste", "draft", "brainstorm"):
            self.query_one(f"#rp-{name}-group").display = name == source
        self.query_one("#rp-go", Button).label = "Save" if source == "paste" else "Make the plan"

    def on_select_changed(self, event: "Select.Changed") -> None:
        if event.select.id == "rp-source":
            self._show_source(event.value)
        elif event.select.id == "rp-from":
            new = event.value == "new"
            self.query_one("#rp-new-group").display = new
            self.query_one("#rp-writer-row").display = not new

    def _error(self, text: str) -> None:
        error = self.query_one("#rp-error", Static)
        error.update(text)
        error.set_class(not text, "-empty")

    def _plan_name(self, fallback: str) -> str:
        return self.query_one("#rp-name", Input).value.strip() or fallback.strip() or "plan"

    def _confirm_replace(self, path: Path, retry) -> None:
        from whyline.console.tui import ConfirmScreen

        shown = (path.relative_to(self._root) if path.is_relative_to(self._root) else path).as_posix()

        def answered(confirmed: bool) -> None:
            if confirmed:
                retry()

        self.app.push_screen(
            ConfirmScreen(f"{shown} already exists. Replace it?", "Replace"),
            answered,
        )

    def _submit(self, request: PlanRequest) -> None:
        path = relay_ops.plan_path(self._root, request.name)
        if path.exists() and not request.replace:
            self._confirm_replace(path, lambda: self.dismiss(dc_replace(request, replace=True)))
            return
        self.dismiss(request)

    def _save_paste(self, replace: bool = False) -> None:
        text = self.query_one("#rp-paste", TextArea).text
        heading = next(
            (line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")), ""
        )
        name = self._plan_name(heading)
        try:
            path = relay_ops.save_pasted_plan(self._root, text, name, replace=replace)
        except relay_ops.plan_exists_error():
            self._confirm_replace(
                relay_ops.plan_path(self._root, name),
                lambda: self._save_paste(replace=True),
            )
            return
        except ValueError as error:
            self._error(str(error))
            return
        self.dismiss(path)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        handler = getattr(self, f"_on_{event.button.id.replace('-', '_')}", None)
        if handler is not None:
            handler()

    def _on_rp_cancel(self) -> None:
        self.dismiss(None)

    def _on_rp_go(self) -> None:
        source = self._source()
        if source == "paste":
            self._save_paste()
            return
        request = self._draft_request() if source == "draft" else self._brainstorm_request()
        if request is not None:
            self._submit(request)

    def _draft_request(self) -> PlanRequest | None:
        description = self.query_one("#rp-description", TextArea).text.strip()
        if not description:
            self._error("Describe what the plan should build.")
            return None
        refs = [
            line.strip()
            for line in self.query_one("#rp-refs", TextArea).text.splitlines()
            if line.strip()
        ]
        missing = relay_ops.missing_references(self._root, refs)
        if missing:
            self._error("Can't find: " + ", ".join(missing))
            return None
        return PlanRequest(
            "draft",
            self._plan_name(description),
            description=description,
            refs=tuple(refs),
            drafter=self.query_one("#rp-drafter", Select).value,
            reviewer=self.query_one("#rp-reviewer", Select).value,
        )

    def _brainstorm_request(self) -> PlanRequest | None:
        from whyline.console.tui import collect_brainstorm

        chosen = self.query_one("#rp-from", Select).value
        if chosen != "new":
            return PlanRequest(
                "existing",
                self._plan_name(chosen),
                topic=chosen,
                writer=self.query_one("#rp-writer", Select).value,
            )
        choice = collect_brainstorm(self.query_one)
        if isinstance(choice, str):
            self._error(choice)
            return None
        return PlanRequest("brainstorm", self._plan_name(choice["topic"]), brainstorm=choice)

    def _on_rp_resume_draft(self) -> None:
        pending = relay_ops.pending_draft(self._root) or "plan"
        self._submit(PlanRequest("resume", self._plan_name(pending)))

    def _on_rp_discard_draft(self) -> None:
        relay_ops.discard_draft(self._root, None)
        self._error("")
        self.query_one("#rp-resume-draft").display = False
        self.query_one("#rp-discard-draft").display = False


class PlanDraftScreen(ModalScreen):
    """The full draft, read-only."""

    DEFAULT_CSS = """
    PlanDraftScreen { align: center middle; }
    PlanDraftScreen > Vertical {
        width: 110; max-width: 100%; height: 90%; padding: 0 2;
        border: thick $accent; background: $surface;
    }
    PlanDraftScreen VerticalScroll { height: 1fr; }
    PlanDraftScreen Horizontal { height: auto; margin-top: 1; }
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        yield Vertical(
            VerticalScroll(Static(self._text, markup=False)),
            Horizontal(Button("Close", id="pd-close", variant="primary")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss(None)


class RunChoiceScreen(ModalScreen):
    """Run, step 1: a new plan or a saved one."""

    DEFAULT_CSS = """
    RunChoiceScreen { align: center middle; }
    RunChoiceScreen > Vertical {
        width: 70; height: auto; padding: 1 2;
        border: thick $accent; background: $surface;
    }
    RunChoiceScreen Horizontal { height: auto; margin-top: 1; }
    RunChoiceScreen Button { margin-right: 2; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Run the relay. Which plan should it work through?"),
            Horizontal(
                Button("Make a new plan", id="run-new", variant="primary"),
                Button("Use an existing plan", id="run-existing", variant="success"),
                Button("Cancel", id="run-cancel"),
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss({"run-new": "new", "run-existing": "existing"}.get(event.button.id))


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
    RelaySetupScreen #rs-plan { width: 70; }
    RelaySetupScreen #rs-no-plan { color: $warning; padding: 1 0 0 0; }
    RelaySetupScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
    RelaySetupScreen Checkbox:focus { border: none; }
    RelaySetupScreen #rs-roles { height: auto; }
    RelaySetupScreen #rs-summary { width: 1fr; padding: 1 1 0 0; }
    RelaySetupScreen #rs-summary-row Button { margin-left: 1; }
    RelaySetupScreen #rs-meaning { color: $text-muted; padding: 1 0; }
    RelaySetupScreen #rs-results { height: auto; max-height: 12; }
    RelaySetupScreen #rs-error { color: $error; height: auto; }
    RelaySetupScreen #rs-error.-empty { display: none; }
    RelaySetupScreen #rs-buttons { margin-top: 1; }
    RelaySetupScreen #rs-buttons Button { margin-right: 2; }
    """

    ROLES = (("implementer", "Implementer:"), ("tester", "Tester:"), ("reviewer", "Reviewer:"))

    def __init__(self, root: Path, *, guided: bool = False, plan: Path | None = None) -> None:
        super().__init__()
        self._root = root
        self._guided = guided
        self._agents = relay_ops.relay_agents(root)
        self._roles = relay_ops.current_roles(root)
        self._configured_roles = dict(self._roles)
        self._configured = relay_ops.roles_configured(root)
        self._plans = relay_ops.list_plans(root)
        current = relay_ops.configured_plan(root)
        listed = [str(info.path) for info in self._plans]
        if plan is not None and str(plan) in listed:
            self._plan_default = str(plan)
        elif current is not None and str(current) in listed:
            self._plan_default = str(current)
        else:
            self._plan_default = listed[0] if listed else None

        if self._guided:
            from whyline import account

            self._usable = relay_ops.usable_agents(root, account.agent_status(root))
            self._recommended = relay_ops.recommend_roles(self._usable)
            in_use = [self._roles[r] for r in ("implementer", "tester", "reviewer")]
            self._unusable = [a for a in dict.fromkeys(in_use) if a not in self._usable]
            if not self._configured or self._unusable:
                self._roles = {**self._recommended} if not self._configured else {
                    **self._roles,
                    **{
                        r: self._recommended[r]
                        for r in ("implementer", "tester", "reviewer")
                        if self._roles[r] in self._unusable
                    },
                }
        else:
            self._usable = self._agents
            self._recommended = {}
            self._unusable = []

        self._summary = self._guided and self._configured
        self._token: object | None = None
        self._filling = True  # ignore change events while the form is built

    def _roles_line(self) -> str:
        r = self._configured_roles
        backup = " → ".join(r.get("backup", [])) or "none"
        line = (
            f"Implementer: {r['implementer']} · Tester: {r['tester']} · "
            f"Reviewer: {r['reviewer']} · Backup: {backup}"
        )
        if self._unusable:
            line += "   ⚠ " + ", ".join(f"{a} isn't logged in" for a in self._unusable)
        return line

    @staticmethod
    def _plan_label(info: "relay_ops.PlanInfo") -> str:
        parts = [info.name, f"{info.done}/{info.total} done", info.source, info.created[:10]]
        return " · ".join(part for part in parts if part)

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
        title = (
            "Run: check who does what, then start."
            if self._guided
            else "Set up: who does what, then check everything is ready."
        )
        yield Vertical(
            Label(title),
            (
                Horizontal(
                    Label("Plan:", classes="field-label"),
                    Select(
                        [(self._plan_label(p), str(p.path)) for p in self._plans],
                        value=self._plan_default,
                        allow_blank=False,
                        id="rs-plan",
                    ),
                )
                if self._plans
                else Static("No plan yet. Make one first.", id="rs-no-plan")
            ),
            *(
                [
                    Horizontal(
                        Static(self._roles_line(), id="rs-summary"),
                        Button("Looks good", id="rs-looks-good", variant="success"),
                        Button("Change", id="rs-change"),
                        id="rs-summary-row",
                    )
                ]
                if self._summary
                else []
            ),
            Vertical(
                Static("Recommended for the agents you have.", id="rs-recommended"),
                *rows,
                Label("Backup, used when an agent fails:"),
                *backups,
                Static("", id="rs-meaning"),
                id="rs-roles",
            ),
            VerticalScroll(Static("", id="rs-checks"), id="rs-results"),
            Static("", id="rs-error", classes="-empty"),
            Horizontal(
                Button("Make a plan", id="rs-make-plan", variant="primary"),
                Button("Check", id="rs-check", variant="primary", disabled=not self._plans),
                Button("Start", id="rs-start", variant="success", disabled=True),
                Button("Cancel", id="rs-cancel"),
                id="rs-buttons",
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#rs-make-plan").display = not self._plans
        if self._configured or not self._guided:
            self.query_one("#rs-recommended").display = False
        if self._summary:
            if self._unusable:
                self.query_one("#rs-roles").display = True
                self.query_one("#rs-summary-row").display = True
            else:
                self.query_one("#rs-roles").display = False
                self.query_one("#rs-check").display = False
        self._update_meaning()
        self.call_after_refresh(self._ready)

    def _update_meaning(self) -> None:
        i, t, r, _ = self._chosen()
        self.query_one("#rs-meaning", Static).update(relay_ops.role_meaning(i, t, r))

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
        self._update_meaning()

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
        elif event.button.id == "rs-looks-good":
            self._check()
        elif event.button.id == "rs-change":
            self.query_one("#rs-summary-row").display = False
            self.query_one("#rs-roles").display = True
            self.query_one("#rs-check").display = True
        elif event.button.id == "rs-make-plan":
            self.dismiss("plan")


    def _check(self) -> None:
        token = object()
        self._token = token
        self._error("")
        self.query_one("#rs-start", Button).disabled = True
        self.query_one("#rs-checks", Static).update("Checking…")
        root, chosen = self._root, self._chosen()
        plan = Path(self.query_one("#rs-plan", Select).value) if self._plans else None

        def in_thread() -> None:
            try:
                if "antigravity" in (chosen[0], chosen[1], chosen[2], *chosen[3]):
                    relay_ops.forget_antigravity_decline(root)
                relay_ops.save_roles(root, *chosen)
                relay_ops.prepare_agents(root, [chosen[0], chosen[1], chosen[2], *chosen[3]])
                if plan is not None:
                    relay_ops.select_plan(root, plan)
                checks = relay_ops.run_checks(root, plan)
                running = relay_ops.live_run(root)
            except Exception as error:
                self.app.call_from_thread(self._check_failed, error, token)
                return
            self.app.call_from_thread(self._show_checks, checks, running, token)

        self.run_worker(in_thread, thread=True)

    def _check_failed(self, error: Exception, token: object) -> None:
        if token is not self._token or not self.is_attached:
            return  # cancelled, re-checked, or the popup has closed
        self.query_one("#rs-checks", Static).update("")
        self._error(str(error) or error.__class__.__name__)

    def _show_checks(self, checks: list, running: str | None, token: object) -> None:
        if token is not self._token or not self.is_attached:
            return  # cancelled, re-checked, or the popup has closed
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
