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
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from whyline.console import relay_ops
from whyline.console.attachments_ui import AttachmentsField
from whyline.console.chain_editor import OrderedChain
from whyline.console.plan_job import PlanRequest
from whyline.console.tui import ConfirmScreen

_SOURCES = [
    ("Brainstorm it", "brainstorm"),
    ("I'll describe it", "draft"),
    ("I have a plan already", "paste"),
    ("Auto — brainstorm to implementation", "auto"),
]
# Fields that belong to the unsaved Auto request. A change drops the check.
_AUTO_SELECTS = frozenset({
    "bs-final",
    "bs-timeout",
    "rp-drafter",
    "rp-reviewer",
    "rp-implementer",
    "rp-tester",
    "rp-exec-reviewer",
    "rp-release",
})
_AUTO_INPUTS = frozenset({"rp-name", "bs-topic", "bs-passes"})
_AUTO_BOXES = frozenset({"rp-replace", "rp-continue-paths"})
_CHECK_HEADINGS = (
    "Repository",
    "Agents and logins",
    "Inputs",
    "Planning",
    "Execution",
    "Concurrency",
    "Will write",
)


def _format_check_lines(checks: list) -> str:
    """Set up's status line, under the candidate_checks headings.

    Known headings stay in that order. A heading with no lines is omitted.
    A non-ok line keeps its hint, including a warning.
    """
    grouped: dict[str, list] = {}
    order: list[str] = []
    for check in checks:
        group = getattr(check, "group", "") or ""
        if group not in grouped:
            grouped[group] = []
            order.append(group)
        grouped[group].append(check)
    known = [heading for heading in _CHECK_HEADINGS if heading in grouped]
    rest = [group for group in order if group not in _CHECK_HEADINGS]
    lines: list[str] = []
    for group in known + rest:
        if group:
            lines.append(group)
        for check in grouped[group]:
            line = f"{check.status:<4}  {check.message}"
            if check.status != "ok" and check.hint:
                line += f"\n      fix: {check.hint}"
            lines.append(line)
    return "\n".join(lines)


class _PlanChain(OrderedChain):
    """Auto's shared chain. Up, Down, Automatic, and None stop on the chain,
    so the plan screen hears about the new order from here."""

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        before = self.order()
        super().on_checkbox_changed(event)
        self._notify(before)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        before = self.order()
        super().on_button_pressed(event)
        self._notify(before)

    def _notify(self, before: list[str]) -> None:
        screen = self.screen
        if not isinstance(screen, RelayPlanScreen):
            return
        screen._refresh_auto_summary()
        # Up at the end of the chain stops here and does not change order.
        if self.order() != before:
            screen._drop_stored_check()


class _AntigravityTrustScreen(ConfirmScreen):
    """Check's trust question. Escape dismisses None, which is not Not now."""

    BINDINGS = [("escape", "dismiss(None)", "Dismiss")]


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
    RelayPlanScreen #rp-form { height: auto; max-height: 70vh; }  /* 1fr has no effect in an auto-height popup */
    RelayPlanScreen Vertical, RelayPlanScreen Horizontal { height: auto; }
    RelayPlanScreen .field-label { width: 18; padding: 1 1 0 0; }
    RelayPlanScreen TextArea { height: 8; }
    RelayPlanScreen #rp-source, RelayPlanScreen #rp-drafter, RelayPlanScreen #rp-reviewer,
    RelayPlanScreen #rp-implementer, RelayPlanScreen #rp-tester,
    RelayPlanScreen #rp-exec-reviewer, RelayPlanScreen #rp-release { width: 40; }
    RelayPlanScreen #rp-name { width: 1fr; }
    RelayPlanScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
    RelayPlanScreen Checkbox:focus { border: none; }
    RelayPlanScreen #rp-replace, RelayPlanScreen #rp-continue-paths { height: auto; }
    RelayPlanScreen #rp-committer, RelayPlanScreen #rp-auto-summary { height: auto; }
    RelayPlanScreen #rp-error { color: $error; height: auto; }
    RelayPlanScreen #rp-error.-empty { display: none; }
    RelayPlanScreen #rp-checks { height: auto; }
    RelayPlanScreen #rp-checks.-empty { display: none; }
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
        self._final_writer: str | None = None
        self._token: object | None = None
        self._check_fingerprint: str | None = None
        self._load_execution_defaults()

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
                Select(_SOURCES, value="brainstorm", allow_blank=False, id="rp-source"),
            ),
            Vertical(
                Label("Paste the plan (each task as `- [ ] ID: title`):"),
                TextArea(id="rp-paste"),
                id="rp-paste-group",
            ),
            Vertical(
                Label("What should the plan build?"),
                TextArea(id="rp-description"),
                AttachmentsField(self._root, self.app._attach_session, id="rp-attachments"),
                Checkbox("Write a spec first", value=True, id="rp-spec-first"),
                id="rp-draft-group",
            ),
            Vertical(*self._brainstorm_widgets(), id="rp-brainstorm-group"),
            # brainstorm_field_widgets hard-codes #bs-* ids, so Auto and a new
            # brainstorm share this one mount instead of composing a second copy.
            Vertical(*self._research_widgets(), id="rp-new-group"),
            Vertical(
                Horizontal(
                    Label("Drafter:", classes="field-label"),
                    self._agent_select(drafter, "rp-drafter"),
                    id="rp-drafter-row",
                ),
                Horizontal(
                    Label("Reviewer:", classes="field-label"),
                    self._agent_select(reviewer, "rp-reviewer"),
                    id="rp-reviewer-row",
                ),
                id="rp-roles-row",
            ),
            self._auto_group(),
            id="rp-form",
        )
        check = Button("Check", id="rp-check", variant="primary")
        check.display = False
        yield Vertical(
            form,
            Static("", id="rp-error", classes="-empty"),
            Static("", id="rp-checks", classes="-empty", markup=False),
            Horizontal(
                check,
                Button("Make the plan", id="rp-go", variant="success"),
                Button("Resume draft", id="rp-resume-draft", variant="primary"),
                Button("Discard it", id="rp-discard-draft", variant="warning"),
                Button("Cancel", id="rp-cancel"),
                id="rp-buttons",
            ),
        )

    def _research_default(self) -> str:
        from whyline.console.repl import BRAINSTORM_AGENTS

        usable = [a for a in BRAINSTORM_AGENTS if self._status[a]["available"]]
        return self._active if self._active in usable else (usable or ["claude"])[0]

    def _brainstorm_widgets(self) -> list:
        docs = relay_ops.brainstorm_docs(self._root)
        default = self._research_default()
        from whyline.console.repl import BRAINSTORM_AGENTS

        usable = [a for a in BRAINSTORM_AGENTS if self._status[a]["available"]]
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
        ]

    def _research_widgets(self) -> list:
        from whyline.console.tui import brainstorm_field_widgets

        default = self._research_default()
        self._final_writer = default
        return brainstorm_field_widgets(
            self._status, default, self.app.session.root, self.app._attach_session
        )

    def _load_execution_defaults(self) -> None:
        """Roles from the saved form, or a recommendation. The chain is only read_backup."""
        if relay_ops.roles_configured(self._root):
            roles = relay_ops.current_roles(self._root)
            self._release = relay_ops.release_role(self._root)
        else:
            roles = relay_ops.recommend_roles(
                relay_ops.usable_agents(self._root, self._status)
            )
            self._release = "human"
        self._role_values = {
            "implementer": roles.get("implementer", ""),
            "tester": roles.get("tester", ""),
            "reviewer": roles.get("reviewer", ""),
        }
        self._chain = list(relay_ops.read_backup(self._root))

    def _role_value(self, wanted: str) -> str:
        if wanted in self._agents:
            return wanted
        return self._agents[0]

    def _auto_group(self) -> Vertical:
        group = Vertical(*self._auto_widgets(), id="rp-auto-group")
        group.display = False
        return group

    def _auto_widgets(self) -> list:
        rows = [
            Horizontal(
                Label(label, classes="field-label"),
                Select(
                    [(agent, agent) for agent in self._agents],
                    value=self._role_value(self._role_values[key]),
                    allow_blank=False,
                    id=widget_id,
                ),
            )
            for key, label, widget_id in (
                ("implementer", "Implementer:", "rp-implementer"),
                ("tester", "Tester:", "rp-tester"),
                ("reviewer", "Reviewer:", "rp-exec-reviewer"),
            )
        ]
        release_options = [("you", "human"), *[(agent, agent) for agent in self._agents]]
        release_values = [value for _label, value in release_options]
        release = self._release if self._release in release_values else "human"
        chain = _PlanChain(self._agents, self._fill_backup, id="rp-chain")
        rows.extend(
            [
                Horizontal(
                    Label("Release:", classes="field-label"),
                    Select(release_options, value=release, allow_blank=False, id="rp-release"),
                ),
                Static("Committer: whyline (automatic)", id="rp-committer", markup=False),
                Label("Backup, used when an agent fails:"),
                chain,
                Checkbox(
                    "Replace an existing brainstorm, spec, or plan",
                    value=False,
                    id="rp-replace",
                ),
                Checkbox(
                    "Continue anyway: some agents get images as file paths only",
                    value=False,
                    id="rp-continue-paths",
                ),
                Static("", id="rp-auto-summary", markup=False),
            ]
        )
        return rows

    def _fill_backup(self) -> list[str]:
        """Names for an empty Auto chain. Automatic is not a stored value."""
        from whyline import account, model

        primary, _chosen_model = model.resolve(self._root)
        usable = relay_ops.usable_agents(self._root, account.agent_status(self._root))
        return relay_ops.staged_backup(primary, usable)

    def on_mount(self) -> None:
        self._show_source("brainstorm")
        pending = relay_ops.pending_draft(self._root)
        spec = relay_ops.pending_spec(self._root)
        resume = bool(pending or spec)
        self.query_one("#rp-resume-draft").display = resume
        self.query_one("#rp-discard-draft").display = resume
        if pending:
            self._error(f'A plan draft for "{pending}" was left unfinished.')
        # The chain's own on_mount sync returns while is_mounted is still false.
        # Nothing saved yet: open on Automatic rather than on no backup.
        self.query_one("#rp-chain", OrderedChain).load(self._chain or self._fill_backup())
        self._sync_planner_agents()
        self._sync_brainstorm_agents()
        self._refresh_auto_summary()
        self._watch_auto_attachments()

    def _sync_planner_agents(self) -> None:
        try:
            drafter = self.query_one("#rp-drafter", Select).value
            reviewer = self.query_one("#rp-reviewer", Select).value
            field = self.query_one("#rp-attachments", AttachmentsField)
        except Exception:
            return
        agents = [a for a in (drafter, reviewer) if a]
        field.set_agents(agents)

    def _sync_brainstorm_agents(self) -> None:
        from whyline.console.repl import BRAINSTORM_AGENTS

        try:
            field = self.query_one("#bs-attachments", AttachmentsField)
        except Exception:
            return
        agents = [a for a in BRAINSTORM_AGENTS if self.query_one(f"#bs-{a}", Checkbox).value]
        field.set_agents(agents)

    def _source(self) -> str:
        return self.query_one("#rp-source", Select).value

    def _show_source(self, source: str) -> None:
        for name in ("paste", "draft", "brainstorm", "auto"):
            self.query_one(f"#rp-{name}-group").display = name == source
        self._sync_from(source)
        roles_shown = source in ("draft", "brainstorm", "auto")
        self.query_one("#rp-roles-row").display = roles_shown
        self.query_one("#rp-drafter-row").display = roles_shown
        self.query_one("#rp-reviewer-row").display = roles_shown
        self.query_one("#rp-drafter").display = roles_shown
        self.query_one("#rp-reviewer").display = roles_shown
        go = self.query_one("#rp-go", Button)
        go.display = source != "auto"
        if source != "auto":
            go.label = "Save" if source == "paste" else "Make the plan"
        self.query_one("#rp-check", Button).display = source == "auto"
        self._drop_stored_check()

    def _sync_from(self, source: str | None = None) -> None:
        source = self._source() if source is None else source
        new = self.query_one("#rp-from", Select).value == "new"
        self.query_one("#rp-new-group").display = source == "auto" or (
            source == "brainstorm" and new
        )
        self.query_one("#rp-writer-row").display = source == "brainstorm" and not new

    def on_select_changed(self, event: "Select.Changed") -> None:
        select_id = event.select.id
        if select_id == "rp-source":
            self._show_source(event.value)
        elif select_id == "rp-from":
            self._sync_from()
        elif select_id == "bs-final":
            self._follow_drafter(event.value)
            self._refresh_auto_summary()
        elif select_id in ("rp-drafter", "rp-reviewer"):
            self._sync_planner_agents()
            self._refresh_auto_summary()
        elif select_id in ("rp-implementer", "rp-tester", "rp-exec-reviewer", "rp-release"):
            self._refresh_auto_summary()
        if select_id in _AUTO_SELECTS:
            self._drop_stored_check()

    def on_input_changed(self, event: "Input.Changed") -> None:
        if event.input.id in _AUTO_INPUTS:
            self._drop_stored_check()

    def _follow_drafter(self, current: str) -> None:
        """On Auto, move the drafter from A to B only while it is still A.

        Brainstorm uses this same final-writer select. Following there would
        change a plan request the other sources already build.
        """
        previous = self._final_writer
        self._final_writer = current
        if (
            self._source() != "auto"
            or not previous
            or previous == current
            or current not in self._agents
        ):
            return
        drafter = self.query_one("#rp-drafter", Select)
        if drafter.value == previous:
            drafter.value = current

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        box_id = event.checkbox.id or ""
        if box_id.startswith("bs-"):
            self._sync_brainstorm_agents()
            self._refresh_auto_summary()
            self._drop_stored_check()
        elif box_id in _AUTO_BOXES:
            self._drop_stored_check()

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
        source = self._source()
        if source == "draft":
            field = self.query_one("#rp-attachments", AttachmentsField)
            risky = field.needs_confirmation()
        elif source == "brainstorm" and self.query_one("#rp-from", Select).value == "new":
            field = self.query_one("#bs-attachments", AttachmentsField)
            risky = field.needs_confirmation()
        else:
            risky = []

        if risky and not getattr(self, "_attachments_confirmed", False):
            from whyline.console.tui import ConfirmScreen

            def answered(confirmed: bool) -> None:
                if confirmed:
                    self._attachments_confirmed = True
                    self._submit(request)

            self.app.push_screen(
                ConfirmScreen(
                    f"{', '.join(risky)} get images as file paths only and may not see them.",
                    "Continue",
                ),
                answered,
            )
            return

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
        self._token = object()
        self.dismiss(None)

    def _on_rp_check(self) -> None:
        """Ask first when a named agent is Antigravity and this repo is `ask`.

        The worker starts only after that dialog returns. Tests spy on
        `_start_check_worker`.
        """
        from whyline.console.auto_run import named_agents

        named = "antigravity" in named_agents(self._auto_view())
        if named and relay_ops.antigravity_state(self._root) == "ask":
            self._ask_antigravity_trust()
            return
        self._start_check_worker()

    def _ask_antigravity_trust(self) -> None:
        """Same wording as `_with_antigravity`. That helper is unchanged."""
        from whyline_relay import antigravity

        message = (
            "Antigravity can only read and edit files in folders listed in "
            f"{antigravity.settings_path()}, a setting for the whole machine. Add "
            f"{self._root} to it, and allow Antigravity's file and command tools?"
        )

        def answered(trusted: bool | None) -> None:
            # True trusts, False declines. None (Escape) and any other dismiss
            # write nothing: Not now is the only decline.
            if trusted is True:
                writer = relay_ops.trust_antigravity
            elif trusted is False:
                writer = relay_ops.decline_antigravity
            else:
                return
            try:
                writer(self._root)
            except Exception as error:
                self._show_check_failure(error)
                return
            self._start_check_worker()

        self.app.push_screen(
            _AntigravityTrustScreen(message, "Trust it", "Not now"),
            answered,
        )

    def _show_check_failure(self, error: Exception) -> None:
        """One FAIL line. No fingerprint, and the worker does not start."""
        self._check_fingerprint = None
        checks = self.query_one("#rp-checks", Static)
        checks.update(f"FAIL  {error}")
        checks.remove_class("-empty")

    def _drop_stored_check(self) -> None:
        """Forget the last check. Run is not mounted; a missing fingerprint
        is what would leave it disabled.
        """
        self._token = object()
        self._check_fingerprint = None
        try:
            checks = self.query_one("#rp-checks", Static)
        except NoMatches:
            return
        checks.update("")
        checks.add_class("-empty")

    def _watch_auto_attachments(self) -> None:
        """The attachment tray does not post a message this screen can hear."""
        try:
            pending = self.query_one("#bs-attachments", AttachmentsField).pending
        except NoMatches:
            return
        add, remove, clear = pending.add, pending.remove, pending.clear

        def added(attachment) -> None:
            add(attachment)
            self._drop_stored_check()

        def removed(attachment_id: str) -> None:
            remove(attachment_id)
            self._drop_stored_check()

        def cleared() -> None:
            clear()
            self._drop_stored_check()

        pending.add = added
        pending.remove = removed
        pending.clear = cleared

    def _auto_request(self):
        """The unsaved Auto form. An empty name stays empty so path fallback
        belongs to candidate_checks, matching `_plan_name` there.
        """
        from whyline.console.plan_job import AutoRunRequest
        from whyline.console.repl import BRAINSTORM_AGENTS

        raw_passes = self.query_one("#bs-passes", Input).value.strip() or "0"
        if not raw_passes.isdigit():
            raise ValueError("Review passes must be a whole number (0 or more).")
        return AutoRunRequest(
            name=self.query_one("#rp-name", Input).value.strip(),
            topic=self.query_one("#bs-topic", Input).value.strip(),
            replace=bool(self.query_one("#rp-replace", Checkbox).value),
            continue_paths=bool(self.query_one("#rp-continue-paths", Checkbox).value),
            agents=tuple(
                agent
                for agent in BRAINSTORM_AGENTS
                if self.query_one(f"#bs-{agent}", Checkbox).value
            ),
            passes=int(raw_passes),
            final_agent=str(self.query_one("#bs-final", Select).value),
            timeout_minutes=self.query_one("#bs-timeout", Select).value,
            attachments=tuple(
                self.query_one("#bs-attachments", AttachmentsField).pending.paths()
            ),
            drafter=str(self.query_one("#rp-drafter", Select).value),
            reviewer=str(self.query_one("#rp-reviewer", Select).value),
            implementer=str(self.query_one("#rp-implementer", Select).value),
            tester=str(self.query_one("#rp-tester", Select).value),
            reviewer_role=str(self.query_one("#rp-exec-reviewer", Select).value),
            release=str(self.query_one("#rp-release", Select).value),
            chain=tuple(self.query_one("#rp-chain", OrderedChain).order()),
        )

    def _start_check_worker(self) -> None:
        """Same token as Set up. Reads the form, writes nothing, stores a
        fingerprint only when the report has no FAIL.
        """
        try:
            request = self._auto_request()
        except (TypeError, ValueError) as error:
            self._show_check_failure(error)
            return
        token = object()
        self._token = token
        self._check_fingerprint = None
        self._error("")
        widget = self.query_one("#rp-checks", Static)
        widget.update("Checking…")
        widget.remove_class("-empty")
        root = self._root

        def in_thread() -> None:
            from whyline.console import auto_run

            try:
                checks = relay_ops.candidate_checks(root, request)
                # Called after the trust dialog, including when a line failed.
                # A git error must not hide those FAIL lines. A clean check
                # has nothing else to show, so that error is the result.
                try:
                    digest = auto_run.fingerprint(root, request)
                except Exception:
                    if any(check.status == "FAIL" for check in checks):
                        digest = None
                    else:
                        raise
            except Exception as error:
                self.app.call_from_thread(self._check_worker_failed, error, token)
                return
            if any(check.status == "FAIL" for check in checks):
                digest = None
            self.app.call_from_thread(self._show_auto_checks, checks, digest, token)

        self.run_worker(in_thread, thread=True)

    def _check_worker_failed(self, error: Exception, token: object) -> None:
        if token is not self._token or not self.is_attached:
            return
        try:
            self._show_check_failure(error)
        except NoMatches:
            return

    def _show_auto_checks(self, checks: list, digest: str | None, token: object) -> None:
        if token is not self._token or not self.is_attached:
            return
        failures = sum(check.status == "FAIL" for check in checks)
        try:
            widget = self.query_one("#rp-checks", Static)
            text = _format_check_lines(checks)
            widget.update(text)
            widget.set_class(not text, "-empty")
            self._check_fingerprint = digest if failures == 0 else None
        except NoMatches:
            return

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
        field = self.query_one("#rp-attachments", AttachmentsField)
        spec_first = self.query_one("#rp-spec-first", Checkbox).value
        return PlanRequest(
            "draft",
            self._plan_name(description),
            description=description,
            attachments=tuple(field.pending.paths()),
            drafter=self.query_one("#rp-drafter", Select).value,
            reviewer=self.query_one("#rp-reviewer", Select).value,
            spec_first=spec_first,
        )

    def _brainstorm_request(self) -> PlanRequest | None:
        from whyline.console.tui import collect_brainstorm

        chosen = self.query_one("#rp-from", Select).value
        drafter = self.query_one("#rp-drafter", Select).value
        reviewer = self.query_one("#rp-reviewer", Select).value
        if chosen != "new":
            return PlanRequest(
                "existing",
                self._plan_name(chosen),
                topic=chosen,
                writer=self.query_one("#rp-writer", Select).value,
                drafter=drafter,
                reviewer=reviewer,
            )
        choice = collect_brainstorm(self.query_one)
        if isinstance(choice, str):
            self._error(choice)
            return None
        return PlanRequest(
            "brainstorm",
            self._plan_name(choice["topic"]),
            brainstorm=choice,
            drafter=drafter,
            reviewer=reviewer,
        )

    def _on_rp_resume_draft(self) -> None:
        pending = relay_ops.pending_draft(self._root) or "plan"
        self._submit(PlanRequest("resume", self._plan_name(pending)))

    def _on_rp_discard_draft(self) -> None:
        relay_ops.discard_draft(self._root, None)
        self._error("")
        self.query_one("#rp-resume-draft").display = False
        self.query_one("#rp-discard-draft").display = False

    def _auto_view(self):
        from types import SimpleNamespace

        from whyline.console.repl import BRAINSTORM_AGENTS

        agents = tuple(
            agent for agent in BRAINSTORM_AGENTS if self.query_one(f"#bs-{agent}", Checkbox).value
        )
        return SimpleNamespace(
            root=self._root,
            agents=agents,
            final_agent=self.query_one("#bs-final", Select).value,
            drafter=self.query_one("#rp-drafter", Select).value,
            reviewer=self.query_one("#rp-reviewer", Select).value,
            implementer=self.query_one("#rp-implementer", Select).value,
            tester=self.query_one("#rp-tester", Select).value,
            reviewer_role=self.query_one("#rp-exec-reviewer", Select).value,
            release=self.query_one("#rp-release", Select).value,
            chain=tuple(self.query_one("#rp-chain", OrderedChain).order()),
        )

    def _refresh_auto_summary(self) -> None:
        try:
            text = relay_ops.auto_summary(self._auto_view())
        except NoMatches:
            return
        self.query_one("#rp-auto-summary", Static).update(text)


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


class _SetupChain(OrderedChain):
    """The Set up chain. Up, Down, Automatic, and None stop their own presses.

    Those edits never reach ``RelaySetupScreen``, and Check has already
    written the previous order by the time Start runs. Tell the screen when
    the order actually changes so Start cannot launch an unchecked chain.
    """

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        before = self.order()
        super().on_button_pressed(event)
        event.prevent_default()
        if self.order() == before:
            return
        screen = self.screen
        if isinstance(screen, RelaySetupScreen):
            screen._invalidate()


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
    RelaySetupScreen #rs-committer { padding: 1 1 0 0; }
    RelaySetupScreen #rs-summary { width: 1fr; padding: 1 1 0 0; }
    RelaySetupScreen #rs-summary-row Button { margin-left: 1; }
    RelaySetupScreen #rs-meaning { color: $text-muted; padding: 1 0; }
    RelaySetupScreen #rs-fields { height: auto; max-height: 45vh; }
    RelaySetupScreen #rs-results { height: auto; max-height: 25vh; }
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

        self._release = relay_ops.release_role(root)
        self._summary = self._guided and self._configured
        self._backup = list(self._roles.get("backup") or [])
        self._token: object | None = None
        self._filling = True  # ignore change events while the form is built

    def _roles_line(self) -> str:
        r = self._configured_roles
        backup = " → ".join(r.get("backup", [])) or "none"
        rel_label = "you" if self._release in ("human", "you") else self._release
        line = (
            f"Implementer: {r['implementer']} · Tester: {r['tester']} · "
            f"Reviewer: {r['reviewer']} · Backup: {backup} · Release: {rel_label}"
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
        chain = _SetupChain(self._agents, self._fill_backup, id="rs-backup")
        chain.load(self._backup)
        title = (
            "Run: check who does what, then start."
            if self._guided
            else "Set up: who does what, then check everything is ready."
        )
        # The fields scroll; the check results, error line and buttons stay
        # pinned below, so Check and Start are reachable on an 80x24 terminal.
        yield Vertical(VerticalScroll(
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
                Horizontal(
                    Static("Committer: whyline (automatic)", id="rs-committer"),
                ),
                Horizontal(
                    Label("Release:", classes="field-label"),
                    Select(
                        [("you", "human")] + [(a, a) for a in self._agents],
                        value=self._release if self._release in (["human"] + self._agents) else "human",
                        allow_blank=False,
                        id="rs-release",
                    ),
                ),
                Label("Backup, used when an agent fails:"),
                chain,
                Static("", id="rs-meaning"),
                id="rs-roles",
            ),
            id="rs-fields"),
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
        # compose() loads before the chain is mounted, and the chain's own
        # on_mount sync returns while is_mounted is still false.
        # Nothing saved yet: open on Automatic rather than on no backup.
        self.query_one("#rs-backup", OrderedChain).load(self._backup or self._fill_backup())
        self._update_meaning()
        self.call_after_refresh(self._ready)

    def _fill_backup(self) -> list[str]:
        """Names for an empty editor. Automatic is not a value Check stores."""
        from whyline import account, model

        primary, _chosen_model = model.resolve(self._root)
        usable = relay_ops.usable_agents(self._root, account.agent_status(self._root))
        return relay_ops.staged_backup(primary, usable)

    def _update_meaning(self) -> None:
        i, t, r, _ = self._chosen()
        try:
            rel = self.query_one("#rs-release", Select).value
        except Exception:
            rel = self._release
        self.query_one("#rs-meaning", Static).update(relay_ops.role_meaning(i, t, r, rel))

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
        try:
            if self.query("#rs-release"):
                self._release = self.query_one("#rs-release", Select).value
        except Exception:
            pass
        self._invalidate()
        self._update_meaning()

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        self._invalidate()

    def _chosen(self) -> tuple[str, str, str, list[str]]:
        implementer, tester, reviewer = (
            self.query_one(f"#rs-{role}", Select).value for role, _ in self.ROLES
        )
        backup = self.query_one("#rs-backup", OrderedChain).order()
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
        release = self.query_one("#rs-release", Select).value
        plan = Path(self.query_one("#rs-plan", Select).value) if self._plans else None

        def in_thread() -> None:
            try:
                if "antigravity" in (chosen[0], chosen[1], chosen[2], release, *chosen[3]):
                    relay_ops.forget_antigravity_decline(root)
                relay_ops.save_roles(root, *chosen)
                relay_ops.save_release(root, release)
                agents_to_prepare = [chosen[0], chosen[1], chosen[2], *chosen[3]]
                if release != "human":
                    agents_to_prepare.append(release)
                relay_ops.prepare_agents(root, agents_to_prepare)
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
        try:
            self.query_one("#rs-checks", Static).update("")
            self._error(str(error) or error.__class__.__name__)
        except NoMatches:
            return  # the popup's children were removed during teardown

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
        try:
            self.query_one("#rs-checks", Static).update("\n".join(lines))
            if running:
                self._error(f"A relay is already running here ({running}).")
            self.query_one("#rs-start", Button).disabled = failures > 0 or bool(running)
        except NoMatches:
            return  # the popup's children were removed during teardown
