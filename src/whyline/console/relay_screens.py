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
from whyline.console.repl import NO_SUBSCRIPTIONS, provider_enabled
from whyline.console.tui import ConfirmScreen

_SOURCES = [
    ("Brainstorm it", "brainstorm"),
    ("I'll describe it", "draft"),
    ("I have a plan already", "paste"),
    ("Auto — brainstorm to implementation", "auto"),
]
NO_AGENTS_SETUP = (
    "No agent is installed here, so the relay has nobody to run. "
    "Install one of claude, codex, antigravity or grok, log in, then press Set up again."
)
CHECKING_MODELS = "Checking models…"
MODEL_REFRESH_FAILED = "Could not refresh models; using the saved/default value."
STALE_CHECK_HINT = "Open Settings or choose an enabled provider."
NO_AGENTS_PLAN = (
    "No agent is installed here, so the relay has nobody to run. "
    "Install one of claude, codex, antigravity or grok, log in, then press Plan again."
)
# Fields that belong to the unsaved Auto request. A change drops the check.
_AUTO_SELECTS = frozenset({
    "bs-final",
    "bs-test-planner",
    "bs-timeout",
    "rp-drafter",
    "rp-test-planner",
    "rp-reviewer",
    "rp-implementer",
    "rp-tester",
    "rp-exec-reviewer",
    "rp-release",
})
_AUTO_INPUTS = frozenset({"rp-name", "bs-topic", "bs-passes"})
_AUTO_BOXES = frozenset({"rp-replace", "rp-continue-paths"})
_TEST_PLANNER_TIP = "Tip: a different agent from the Drafter catches more."


class _PlannerStr(str):
    """Carries `_test_planner` on `drafter` so 3-arg `save_planner` callers
    preserve the selected test planner."""

    _test_planner: str = ""


def _attach_test_planner(request, test_planner: str):
    if getattr(request, "drafter", ""):
        drafter = _PlannerStr(request.drafter)
        drafter._test_planner = test_planner
        object.__setattr__(request, "drafter", drafter)
    object.__setattr__(request, "test_planner", test_planner)
    object.__setattr__(request, "test", test_planner)
    return request


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
    RelayPlanScreen #rp-form { height: auto; max-height: 45vh; }  /* 1fr has no effect in an auto-height popup */
    RelayPlanScreen Vertical, RelayPlanScreen Horizontal { height: auto; }
    RelayPlanScreen .field-label { width: 18; padding: 1 1 0 0; }
    RelayPlanScreen TextArea { height: 8; }
    RelayPlanScreen #rp-source, RelayPlanScreen #rp-drafter, RelayPlanScreen #rp-test-planner,
    RelayPlanScreen #rp-reviewer, RelayPlanScreen #rp-implementer, RelayPlanScreen #rp-tester,
    RelayPlanScreen #rp-exec-reviewer, RelayPlanScreen #rp-release,
    RelayPlanScreen #bs-test-planner { width: 40; }
    RelayPlanScreen #rp-test-planner-tip,
    RelayPlanScreen #bs-test-planner-tip { color: $text-muted; height: auto; display: none; }
    RelayPlanScreen #rp-name { width: 1fr; }
    RelayPlanScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
    RelayPlanScreen Checkbox:focus { border: none; }
    RelayPlanScreen #rp-replace, RelayPlanScreen #rp-continue-paths { height: auto; }
    RelayPlanScreen #rp-committer, RelayPlanScreen #rp-auto-summary { height: auto; }
    RelayPlanScreen #rp-error { color: $error; height: auto; }
    RelayPlanScreen #rp-error.-empty { display: none; }
    RelayPlanScreen #rp-checks { height: auto; max-height: 25vh; overflow-y: auto; }
    RelayPlanScreen #rp-checks.-empty { display: none; }
    RelayPlanScreen #rp-buttons { margin-top: 1; }
    RelayPlanScreen #rp-buttons Button { margin-right: 1; }
    """

    def __init__(self, root: Path, status: dict, active: str, source: str = "brainstorm") -> None:
        super().__init__()
        self._root = root
        self._status = status
        self._active = active
        self._agents = relay_ops.relay_agents(root)
        raw_planner = relay_ops.planner_agents(root)
        self._planner = (
            (raw_planner[0], raw_planner[1], raw_planner[2])
            if len(raw_planner) >= 3
            else (raw_planner[0], raw_planner[1], "")
        )
        self._final_writer: str | None = None
        self._token: object | None = None
        self._check_fingerprint: str | None = None
        self._initial_source = source
        self._checkpoint_loaded = False
        self._filling = False
        self._load_execution_defaults()

    def _agent_select(self, wanted: str, select_id: str) -> Select | Label:
        if not self._agents:
            return Label(NO_AGENTS_PLAN, id=select_id)
        value = wanted if wanted in self._agents else self._agents[0]
        return Select([(a, a) for a in self._agents], value=value, allow_blank=False, id=select_id)

    def _test_planner_select(
        self, wanted: str, select_id: str = "rp-test-planner"
    ) -> Select | Label:
        if not self._agents:
            return Label(NO_AGENTS_PLAN, id=select_id)
        usable = [
            a for a in self._agents if self._status.get(a, {}).get("available")
        ] or list(self._agents)
        options: list[tuple[str, str]] = [("None", ""), *((a, a) for a in usable)]
        if wanted and wanted in self._agents and wanted not in usable:
            options.append((wanted, wanted))
        value = wanted if any(v == wanted for _, v in options) else ""
        return Select(options, value=value, allow_blank=False, id=select_id)

    def compose(self) -> ComposeResult:
        drafter, reviewer, test_planner = self._planner
        if self._agents:
            roles_row = Vertical(
                Horizontal(
                    Label("Drafter:", classes="field-label"),
                    self._agent_select(drafter, "rp-drafter"),
                    id="rp-drafter-row",
                ),
                Horizontal(
                    Label("Test planner:", classes="field-label"),
                    self._test_planner_select(test_planner, "rp-test-planner"),
                    id="rp-test-planner-row",
                ),
                Static(
                    _TEST_PLANNER_TIP,
                    id="rp-test-planner-tip",
                    markup=False,
                ),
                Horizontal(
                    Label("Reviewer:", classes="field-label"),
                    self._agent_select(reviewer, "rp-reviewer"),
                    id="rp-reviewer-row",
                ),
                id="rp-roles-row",
            )
        else:
            roles_row = Vertical(
                Label(NO_AGENTS_PLAN),
                id="rp-roles-row",
            )
        form = VerticalScroll(
            Label("Plan: make a plan the relay works through, saved under plans/."),
            Horizontal(
                Label("Plan name:", classes="field-label"),
                Input(placeholder="leave empty to name it from the description", id="rp-name"),
            ),
            Horizontal(
                Label("Source:", classes="field-label"),
                Select(_SOURCES, value=self._initial_source, allow_blank=False, id="rp-source"),
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
            roles_row,
            self._auto_group(),
            id="rp-form",
        )
        check = Button("Check", id="rp-check", variant="primary", disabled=not self._agents)
        check.display = False
        run_btn = Button("Run", id="rp-run", variant="success", disabled=True)
        run_btn.display = False
        yield Vertical(
            form,
            Static("", id="rp-error", classes="-empty", markup=False),
            Static("", id="rp-checks", classes="-empty", markup=False),
            Horizontal(
                check,
                run_btn,
                Button("Make the plan", id="rp-go", variant="success", disabled=not self._agents),
                Button("Resume draft", id="rp-resume-draft", variant="primary"),
                Button("Discard it", id="rp-discard-draft", variant="warning"),
                Button("Cancel", id="rp-cancel"),
                id="rp-buttons",
            ),
        )

    def _research_default(self) -> str:
        from whyline.console.repl import BRAINSTORM_AGENTS

        usable = [a for a in BRAINSTORM_AGENTS if self._status.get(a, {}).get("available")]
        return self._active if self._active in usable else (usable or ["claude"])[0]

    def _brainstorm_widgets(self) -> list:
        docs = relay_ops.brainstorm_docs(self._root)
        default = self._research_default()
        from whyline.console.repl import BRAINSTORM_AGENTS

        usable = [a for a in BRAINSTORM_AGENTS if self._status.get(a, {}).get("available")]
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
        return self._agents[0] if self._agents else ""

    def _auto_group(self) -> Vertical:
        group = Vertical(*self._auto_widgets(), id="rp-auto-group")
        group.display = False
        return group

    def _auto_widgets(self) -> list:
        if not self._agents:
            return [Label(NO_AGENTS_PLAN)]
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
        self._show_source(self._initial_source)
        pending = relay_ops.pending_draft(self._root)
        spec = relay_ops.pending_spec(self._root)
        resume = bool(pending or spec)
        self.query_one("#rp-resume-draft").display = resume
        self.query_one("#rp-discard-draft").display = resume
        if pending:
            self._error(f'A plan draft for "{pending}" was left unfinished.')
        # The chain's own on_mount sync returns while is_mounted is still false.
        # Nothing saved yet: open on Automatic rather than on no backup.
        if self.query("#rp-chain"):
            self.query_one("#rp-chain", OrderedChain).load(self._chain or self._fill_backup())
        self._sync_test_planner_tip()
        self._sync_planner_agents()
        self._sync_brainstorm_agents()
        self._refresh_auto_summary()
        self._watch_auto_attachments()
        if not self._agents:
            self.query_one("#rp-check", Button).disabled = True
            self.query_one("#rp-run", Button).disabled = True
            self.query_one("#rp-go", Button).disabled = True

    def _selected_test_planner(self) -> str:
        rp_val = None
        bs_val = None
        try:
            val = self.query_one("#rp-test-planner", Select).value
            if isinstance(val, str):
                rp_val = val
        except Exception:
            pass
        try:
            val = self.query_one("#bs-test-planner", Select).value
            if isinstance(val, str):
                bs_val = val
        except Exception:
            pass
        initial = self._planner[2]
        if rp_val is not None and bs_val is not None and rp_val != bs_val:
            if bs_val != initial and rp_val == initial:
                return bs_val
            return rp_val
        if rp_val is not None:
            return rp_val
        if bs_val is not None:
            return bs_val
        return initial

    def _sync_test_planner_tip(self) -> None:
        if not self._agents:
            return
        try:
            drafter = str(self.query_one("#rp-drafter", Select).value)
        except Exception:
            drafter = self._planner[0]
        test_planner = self._selected_test_planner()
        roles_shown = self._source() in ("draft", "brainstorm", "auto")
        show_tip = roles_shown and bool(test_planner) and test_planner == drafter
        for tip_id in ("#rp-test-planner-tip", "#bs-test-planner-tip"):
            try:
                self.query_one(tip_id, Static).display = show_tip
            except Exception:
                pass

    def _sync_planner_agents(self) -> None:
        try:
            drafter = self.query_one("#rp-drafter", Select).value
            reviewer = self.query_one("#rp-reviewer", Select).value
            field = self.query_one("#rp-attachments", AttachmentsField)
        except Exception:
            return
        test_planner = self._selected_test_planner()
        agents = [a for a in (drafter, test_planner, reviewer) if a]
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
        if self._agents:
            self.query_one("#rp-drafter-row").display = roles_shown
            self.query_one("#rp-test-planner-row").display = roles_shown
            self.query_one("#rp-reviewer-row").display = roles_shown
            self.query_one("#rp-drafter").display = roles_shown
            self.query_one("#rp-test-planner").display = roles_shown
            self.query_one("#rp-reviewer").display = roles_shown
        self._sync_test_planner_tip()
        go = self.query_one("#rp-go", Button)
        go.display = source != "auto"
        if not self._agents:
            go.disabled = True
        elif source != "auto":
            go.label = "Save" if source == "paste" else "Make the plan"
        self.query_one("#rp-check", Button).display = source == "auto"
        self.query_one("#rp-run", Button).display = source == "auto"
        self._drop_stored_check()
        if source == "auto":
            self._load_auto_checkpoint()

    def _sync_from(self, source: str | None = None) -> None:
        source = self._source() if source is None else source
        new = self.query_one("#rp-from", Select).value == "new"
        self.query_one("#rp-new-group").display = source == "auto" or (
            source == "brainstorm" and new
        )
        self.query_one("#rp-writer-row").display = source == "brainstorm" and not new

    def on_select_changed(self, event: "Select.Changed") -> None:
        if getattr(self, "_filling", False):
            return
        select_id = event.select.id
        if select_id == "rp-source":
            self._show_source(event.value)
        elif select_id == "rp-from":
            self._sync_from()
        elif select_id == "bs-final":
            self._follow_drafter(event.value)
            self._refresh_auto_summary()
        elif select_id in ("rp-drafter", "rp-reviewer"):
            self._sync_test_planner_tip()
            self._sync_planner_agents()
            self._refresh_auto_summary()
        elif select_id in ("rp-test-planner", "bs-test-planner"):
            other_id = "#bs-test-planner" if select_id == "rp-test-planner" else "#rp-test-planner"
            try:
                other = self.query_one(other_id, Select)
                if isinstance(event.value, str) and other.value != event.value:
                    self._filling = True
                    try:
                        other.value = event.value
                    finally:
                        self._filling = False
            except Exception:
                pass
            self._sync_test_planner_tip()
            self._sync_planner_agents()
            self._refresh_auto_summary()
        elif select_id in ("rp-implementer", "rp-tester", "rp-exec-reviewer", "rp-release"):
            self._refresh_auto_summary()
        if select_id in _AUTO_SELECTS:
            self._drop_stored_check()

    def on_input_changed(self, event: "Input.Changed") -> None:
        if getattr(self, "_filling", False):
            return
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
            self._sync_test_planner_tip()

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        if getattr(self, "_filling", False):
            return
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

    def _save_form_planner(self, request: PlanRequest) -> None:
        if not request.drafter or not request.reviewer:
            return
        test_planner = getattr(
            request,
            "test_planner",
            getattr(request.drafter, "_test_planner", self._selected_test_planner()),
        )
        try:
            relay_ops.save_planner(
                self._root, str(request.drafter), str(request.reviewer), str(test_planner)
            )
        except TypeError:
            try:
                relay_ops.save_planner(self._root, request.drafter, request.reviewer)
            except Exception:
                pass
        except Exception:
            pass

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
            def replace_and_dismiss() -> None:
                replaced = _attach_test_planner(
                    dc_replace(request, replace=True),
                    getattr(request, "test_planner", self._selected_test_planner()),
                )
                self._save_form_planner(replaced)
                self.dismiss(replaced)

            self._confirm_replace(path, replace_and_dismiss)
            return
        self._save_form_planner(request)
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
        if not self._agents:
            return
        from whyline.console.auto_run import named_agents

        named = "antigravity" in named_agents(self._auto_view())
        if named and relay_ops.antigravity_state(self._root) == "ask":
            self._ask_antigravity_trust()
            return
        self._start_check_worker()

    def _on_rp_run(self) -> None:
        if not self._agents:
            return
        from whyline.console import auto_run

        try:
            request = self._auto_request()
        except (TypeError, ValueError) as error:
            self._show_check_failure(error)
            return

        try:
            fresh_doc = auto_run.document(self._root, request)
            fresh_fp = auto_run._digest(fresh_doc)
        except Exception:
            fresh_doc = None
            fresh_fp = None

        saved = None
        checkpoint_file = auto_run.checkpoint_path(self._root)
        if checkpoint_file.is_file():
            from whyline.state import load_object
            try:
                saved = load_object(checkpoint_file)
            except Exception:
                saved = None
        is_checkpoint = isinstance(saved, dict) and (saved.get("phase") in ("paused", "stopped") or "pause" in saved)

        matches = False
        if self._check_fingerprint and fresh_fp is not None:
            if fresh_fp == self._check_fingerprint:
                matches = True
            elif is_checkpoint:
                form_matches = (saved.get("request") == auto_run._form_view(fresh_doc))
                clean_tree = (fresh_doc.get("porcelain") == "") and not auto_run._repository_failures(self._root)
                if form_matches and clean_tree and self._check_fingerprint in (saved.get("fingerprint"), saved.get("last_check")):
                    matches = True

        if not matches:
            self._drop_stored_check()
            if hasattr(self.app, "render_event"):
                from whyline.console.session import SessionEvent
                self.app.render_event(
                    SessionEvent(kind="error", text="This check is out of date. Check again.")
                )
            return

        self.dismiss((request, self._check_fingerprint))

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
        try:
            self.query_one("#rp-run", Button).disabled = True
        except NoMatches:
            pass
        checks = self.query_one("#rp-checks", Static)
        checks.update(f"FAIL  {error}")
        checks.remove_class("-empty")

    def _drop_stored_check(self) -> None:
        """Forget the last check."""
        if self._source() == "auto":
            from whyline.console import auto_run
            from whyline.state import load_object

            path = auto_run.checkpoint_path(self._root)
            saved = None
            if path.is_file():
                try:
                    saved = load_object(path)
                except Exception:
                    saved = None
            if isinstance(saved, dict) and (
                saved.get("phase") in ("paused", "stopped") or "pause" in saved
            ):
                saved_req = saved.get("request")
                try:
                    current_request = self._auto_request()
                    fresh_doc = auto_run.document(self._root, current_request)
                    form_matches = saved_req == auto_run._form_view(fresh_doc)
                    clean_tree = (fresh_doc.get("porcelain") == "") and not auto_run._repository_failures(self._root)
                    if form_matches and clean_tree:
                        self._check_fingerprint = saved.get("fingerprint") or saved.get("last_check")
                        try:
                            self.query_one("#rp-run", Button).disabled = False
                        except NoMatches:
                            pass
                        return
                except Exception:
                    pass

        self._token = object()
        self._check_fingerprint = None
        try:
            checks = self.query_one("#rp-checks", Static)
        except NoMatches:
            return
        checks.update("")
        checks.add_class("-empty")
        try:
            self.query_one("#rp-run", Button).disabled = True
        except NoMatches:
            pass

    def _load_auto_checkpoint(self) -> None:
        from whyline.console import auto_run
        from whyline.state import load_object

        path = auto_run.checkpoint_path(self._root)
        if not path.is_file():
            return
        try:
            saved = load_object(path)
        except Exception:
            return
        if not isinstance(saved, dict) or saved.get("schema") != auto_run.SCHEMA:
            return
        is_paused_or_stopped = (saved.get("phase") in ("paused", "stopped") or "pause" in saved)
        if not is_paused_or_stopped:
            return
        saved_req = saved.get("request")
        if not isinstance(saved_req, dict):
            return

        run_btn = self.query_one("#rp-run", Button)
        run_btn.label = "Resume"

        self._filling = True
        try:
            self._populate_auto_form(saved_req)
        finally:
            self._filling = False

        self._sync_test_planner_tip()
        self._refresh_auto_summary()
        self._sync_planner_agents()
        self._sync_brainstorm_agents()

        try:
            current_request = self._auto_request()
            fresh_doc = auto_run.document(self._root, current_request)
            form_matches = (saved_req == auto_run._form_view(fresh_doc))
            clean_tree = (fresh_doc.get("porcelain") == "") and not auto_run._repository_failures(self._root)
            if form_matches and clean_tree:
                self._check_fingerprint = saved.get("fingerprint") or saved.get("last_check")
                run_btn.disabled = False
            else:
                self._check_fingerprint = None
                run_btn.disabled = True
        except Exception:
            self._check_fingerprint = None
            run_btn.disabled = True

    def _populate_auto_form(self, saved_req: dict) -> None:
        if "name" in saved_req:
            self.query_one("#rp-name", Input).value = str(saved_req["name"])
        if "topic" in saved_req:
            self.query_one("#bs-topic", Input).value = str(saved_req["topic"])
        if "replace" in saved_req:
            self.query_one("#rp-replace", Checkbox).value = bool(saved_req["replace"])
        if "continue_paths" in saved_req:
            self.query_one("#rp-continue-paths", Checkbox).value = bool(saved_req["continue_paths"])
        from whyline.console.repl import BRAINSTORM_AGENTS
        req_agents = set(saved_req.get("agents") or ())
        for a in BRAINSTORM_AGENTS:
            try:
                self.query_one(f"#bs-{a}", Checkbox).value = (a in req_agents)
            except NoMatches:
                pass
        if "passes" in saved_req:
            self.query_one("#bs-passes", Input).value = str(saved_req["passes"])
        if "final_agent" in saved_req and saved_req["final_agent"]:
            try:
                self.query_one("#bs-final", Select).value = saved_req["final_agent"]
                self._final_writer = saved_req["final_agent"]
            except Exception:
                pass
        if "timeout_minutes" in saved_req:
            try:
                minutes = saved_req["timeout_minutes"]
                self.query_one("#bs-timeout", Select).value = (
                    "none" if minutes == 0 else minutes
                )
            except Exception:
                pass
        if "drafter" in saved_req and saved_req["drafter"]:
            try:
                self.query_one("#rp-drafter", Select).value = saved_req["drafter"]
            except Exception:
                pass
        if "test_planner" in saved_req or "test" in saved_req:
            test_val = str(saved_req.get("test_planner") or saved_req.get("test") or "")
            for sel_id in ("#rp-test-planner", "#bs-test-planner"):
                try:
                    self.query_one(sel_id, Select).value = test_val
                except Exception:
                    pass
        if "reviewer" in saved_req and saved_req["reviewer"]:
            try:
                self.query_one("#rp-reviewer", Select).value = saved_req["reviewer"]
            except Exception:
                pass
        if "implementer" in saved_req and saved_req["implementer"]:
            try:
                self.query_one("#rp-implementer", Select).value = saved_req["implementer"]
            except Exception:
                pass
        if "tester" in saved_req and saved_req["tester"]:
            try:
                self.query_one("#rp-tester", Select).value = saved_req["tester"]
            except Exception:
                pass
        if "reviewer_role" in saved_req and saved_req["reviewer_role"]:
            try:
                self.query_one("#rp-exec-reviewer", Select).value = saved_req["reviewer_role"]
            except Exception:
                pass
        if "release" in saved_req and saved_req["release"]:
            try:
                self.query_one("#rp-release", Select).value = saved_req["release"]
            except Exception:
                pass
        if "chain" in saved_req:
            try:
                self.query_one("#rp-chain", OrderedChain).load(list(saved_req["chain"]))
            except Exception:
                pass
        try:
            att_field = self.query_one("#bs-attachments", AttachmentsField)
            att_field.pending.clear()
            from whyline.console import attachments as att
            for item in saved_req.get("attachments") or ():
                p_str = item.get("path") if isinstance(item, dict) else str(item)
                p = Path(p_str)
                if p.is_file():
                    import secrets
                    att_item = att.Attachment(
                        id=secrets.token_hex(4),
                        name=p.name,
                        path=p,
                        kind=att._kind(p),
                        size=p.stat().st_size,
                        source="picker",
                    )
                    att_field.pending.add(att_item)
            att_field.refresh_view()
        except Exception:
            pass

    def _watch_auto_attachments(self) -> None:
        """The attachment tray does not post a message this screen can hear."""
        try:
            pending = self.query_one("#bs-attachments", AttachmentsField).pending
        except NoMatches:
            return
        add, remove, clear = pending.add, pending.remove, pending.clear

        def added(attachment) -> None:
            add(attachment)
            if not getattr(self, "_filling", False):
                self._drop_stored_check()

        def removed(attachment_id: str) -> None:
            remove(attachment_id)
            if not getattr(self, "_filling", False):
                self._drop_stored_check()

        def cleared() -> None:
            clear()
            if not getattr(self, "_filling", False):
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
        timeout = self.query_one("#bs-timeout", Select).value
        req = AutoRunRequest(
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
            timeout_minutes=0 if timeout == "none" else timeout,
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
        return _attach_test_planner(req, self._selected_test_planner())

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
        try:
            self.query_one("#rp-run", Button).disabled = True
        except NoMatches:
            pass
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
            self.query_one("#rp-run", Button).disabled = self._check_fingerprint is None
        except NoMatches:
            return

    def _on_rp_go(self) -> None:
        if not self._agents:
            return
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
        req = PlanRequest(
            "draft",
            self._plan_name(description),
            description=description,
            attachments=tuple(field.pending.paths()),
            drafter=self.query_one("#rp-drafter", Select).value,
            reviewer=self.query_one("#rp-reviewer", Select).value,
            spec_first=spec_first,
        )
        return _attach_test_planner(req, self._selected_test_planner())

    def _brainstorm_request(self) -> PlanRequest | None:
        from whyline.console.tui import collect_brainstorm

        chosen = self.query_one("#rp-from", Select).value
        drafter = self.query_one("#rp-drafter", Select).value
        reviewer = self.query_one("#rp-reviewer", Select).value
        test_planner = self._selected_test_planner()
        if chosen != "new":
            req = PlanRequest(
                "existing",
                self._plan_name(chosen),
                topic=chosen,
                writer=self.query_one("#rp-writer", Select).value,
                drafter=drafter,
                reviewer=reviewer,
            )
            return _attach_test_planner(req, test_planner)
        choice = collect_brainstorm(self.query_one)
        if isinstance(choice, str):
            self._error(choice)
            return None
        if not test_planner and isinstance(choice, dict):
            test_planner = str(
                getattr(choice, "test_planner", "") or choice.get("test_planner") or ""
            )
        req = PlanRequest(
            "brainstorm",
            self._plan_name(choice["topic"]),
            brainstorm=choice,
            drafter=drafter,
            reviewer=reviewer,
        )
        return _attach_test_planner(req, test_planner)

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
        test_planner = self._selected_test_planner()
        return SimpleNamespace(
            root=self._root,
            agents=agents,
            final_agent=self.query_one("#bs-final", Select).value,
            drafter=self.query_one("#rp-drafter", Select).value,
            test_planner=test_planner,
            test=test_planner,
            reviewer=self.query_one("#rp-reviewer", Select).value,
            implementer=self.query_one("#rp-implementer", Select).value,
            tester=self.query_one("#rp-tester", Select).value,
            reviewer_role=self.query_one("#rp-exec-reviewer", Select).value,
            release=self.query_one("#rp-release", Select).value,
            chain=tuple(self.query_one("#rp-chain", OrderedChain).order()),
        )

    def _refresh_auto_summary(self) -> None:
        if not self._agents:
            if self.query("#rp-auto-summary"):
                self.query_one("#rp-auto-summary", Static).update("")
            if self.query("#rp-check"):
                self.query_one("#rp-check", Button).disabled = True
            if self.query("#rp-run"):
                self.query_one("#rp-run", Button).disabled = True
            return
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
    None also clears a hidden disabled saved member so it can be removed
    without enabling it in Settings or showing it as a choice.
    """

    def parked(self) -> list[str]:
        """Saved names that are not enabled choices."""
        return list(self._unknown)

    def _clear(self) -> None:
        self._unknown = []
        super()._clear()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        before = self.order()
        before_parked = self.parked()
        super().on_button_pressed(event)
        event.prevent_default()
        screen = self.screen
        if isinstance(screen, RelaySetupScreen) and event.button.id == "chain-none":
            screen._backup_stale = []
            screen._invalidate()
            screen._update_models()
            return
        if self.order() == before and self.parked() == before_parked:
            return
        if isinstance(screen, RelaySetupScreen):
            if event.button.id == "chain-automatic":
                screen._backup_stale = []
            screen._invalidate()
            screen._update_models()

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        before = self.order()
        super().on_checkbox_changed(event)
        if self.order() == before:
            return
        screen = self.screen
        if isinstance(screen, RelaySetupScreen):
            screen._invalidate()
            screen._update_models()


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
    RelaySetupScreen .field-label { width: 20; padding: 1 1 0 0; }
    RelaySetupScreen Select { width: 30; }
    RelaySetupScreen .model-input { width: 24; margin-left: 1; }
    RelaySetupScreen .model-input.-empty { display: none; }
    RelaySetupScreen .model-out { padding: 0 0 0 2; color: $warning; height: auto; }
    RelaySetupScreen .model-out.-empty { display: none; }
    RelaySetupScreen .model-status { padding: 0 0 0 2; color: $text-muted; height: auto; }
    RelaySetupScreen .model-status.-empty { display: none; }
    RelaySetupScreen .model-row { height: auto; }
    RelaySetupScreen .model-row.-empty { display: none; }
    RelaySetupScreen .model-row Horizontal { height: auto; }
    RelaySetupScreen #rs-models { height: auto; }
    RelaySetupScreen #rs-stale { color: $warning; height: auto; }
    RelaySetupScreen #rs-stale.-empty { display: none; }
    RelaySetupScreen #rs-empty { height: auto; }
    RelaySetupScreen #rs-plan { width: 70; }
    RelaySetupScreen #rs-no-plan { color: $warning; padding: 1 0 0 0; }
    RelaySetupScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
    RelaySetupScreen Checkbox:focus { border: none; }
    RelaySetupScreen #rs-roles { height: auto; }
    RelaySetupScreen .role-override { color: $accent; padding: 0 0 0 20; height: auto; }
    RelaySetupScreen .role-override.-empty { display: none; }
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
    RelaySetupScreen #rs-open-settings { display: none; }
    """

    ROLES = (("implementer", "Implementer:"), ("tester", "Tester:"), ("reviewer", "Reviewer:"))

    def __init__(
        self,
        root: Path,
        *,
        guided: bool = False,
        plan: Path | None = None,
        paused: bool | None = None,
        focus_agent: str | None = None,
        out_until: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._root = root
        self._guided = guided
        self._focus_agent = focus_agent
        if out_until is not None:
            self._out_until = dict(out_until)
        else:
            try:
                from whyline.console import recovery

                self._out_until = recovery.find_out_until_models(root)
            except Exception:
                self._out_until = {}
        if paused is not None:
            self._paused = paused
        else:
            try:
                self._paused = bool(relay_ops.paused_run(root))
            except Exception:
                self._paused = False
        try:
            from whyline_relay import failover

            self._overrides = failover.read_overrides(root)
        except Exception:
            self._overrides = {}
        self._cleared_info: dict[str, str] = {}
        try:
            status = relay_ops.cached_agent_status(root)
        except Exception:
            status = {}
        self._status = status
        self._enabled_providers = {
            name for name, row in status.items() if provider_enabled(row)
        }
        self._agents = relay_ops.setup_choice_agents(root, status)
        self._saved_models = {a: relay_ops.read_agent_model(root, a) for a in self._agents}
        self._roles = relay_ops.current_roles(root)
        self._configured_roles = dict(self._roles)
        self._configured = relay_ops.roles_configured(root)
        self._plans = relay_ops.list_plans(root)
        current = relay_ops.configured_plan(root)
        listed = [str(getattr(info, "path", info)) for info in self._plans]
        if plan is not None and str(plan) in listed:
            self._plan_default = str(plan)
        elif current is not None and str(current) in listed:
            self._plan_default = str(current)
        else:
            self._plan_default = listed[0] if listed else None

        if self._guided:
            self._usable = relay_ops.usable_agents(root, status)
            self._recommended = relay_ops.recommend_roles(self._usable)
            in_use = [self._roles[r] for r in ("implementer", "tester", "reviewer")]
            self._unusable = [a for a in dict.fromkeys(in_use) if a not in self._usable]
            if not self._configured:
                self._roles = {**self._recommended}
            elif self._unusable:
                # Keep disabled saved roles so stale_setup_names and blank
                # dropdowns still show them; only substitute enabled agents
                # that are not logged in.
                self._roles = {
                    **self._roles,
                    **{
                        r: self._recommended[r]
                        for r in ("implementer", "tester", "reviewer")
                        if self._roles[r] in self._unusable
                        and self._roles[r] in self._enabled_providers
                    },
                }
        else:
            self._usable = self._agents
            self._recommended = {}
            self._unusable = []

        self._release = relay_ops.release_role(root)
        self._release_saved = self._release
        # current_roles() fills unsaved defaults; those are not a saved
        # configuration, so first-run must not treat them as stale.
        if self._configured:
            self._stale = relay_ops.stale_setup_names(
                self._configured_roles, self._release, self._enabled_providers
            )
            self._backup_stale = [
                agent
                for agent in (self._configured_roles.get("backup") or [])
                if agent and agent not in self._enabled_providers
            ]
        else:
            self._stale = []
            self._backup_stale = []
        self._summary = self._guided and self._configured and bool(self._agents)
        self._backup = list(self._roles.get("backup") or [])
        self._timeout = relay_ops.relay_timeout(root)
        self._resolve_mode = relay_ops.resolve_mode(root)
        self._token: object | None = None
        self._model_token: object | None = None
        self._filling = True  # ignore change events while the form is built
        self._fail_lines: list[str] = []

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
    def _stale_warning_text(names: list[str]) -> str:
        if not names:
            return ""
        listed = ", ".join(names)
        verb = "is" if len(names) == 1 else "are"
        return (
            f"Saved configuration uses {listed}, which {verb} off in Settings. "
            "Check cannot pass until you choose enabled providers."
        )

    def _role_options(self, wanted: str) -> list[tuple[str, str]]:
        return [(a, a) for a in self._agents]

    def _role_value(self, wanted: str) -> str | None:
        if wanted and wanted in self._agents:
            return wanted
        if wanted:
            return None
        return self._agents[0] if self._agents else None

    @staticmethod
    def _is_blank(value: object) -> bool:
        return value is Select.BLANK or value is None or value == ""

    @staticmethod
    def _plan_label(info: "relay_ops.PlanInfo" | str) -> str:
        if isinstance(info, str):
            return info
        parts = [info.name, f"{info.done}/{info.total} done", info.source, info.created[:10]]
        return " · ".join(part for part in parts if part)

    def compose(self) -> ComposeResult:
        stale_text = self._stale_warning_text(self._stale)
        stale_widget = Static(
            stale_text,
            id="rs-stale",
            markup=False,
            classes="" if stale_text else "-empty",
        )
        if self._agents:
            rows = []
            for role, label in self.ROLES:
                wanted = self._roles.get(role) or ""
                value = self._role_value(wanted)
                rows.append(
                    Horizontal(
                        Label(label, classes="field-label"),
                        Select(
                            self._role_options(wanted),
                            value=value if value is not None else Select.BLANK,
                            allow_blank=value is None,
                            id=f"rs-{role}",
                        ),
                    )
                )
                override = self._overrides.get(role)
                override_text = (
                    f"now on backup {override.agent} ({override.backup_for} hit a limit)"
                    if override is not None
                    else ""
                )
                rows.append(
                    Static(
                        override_text,
                        id=f"rs-{role}-override",
                        classes="role-override" + ("" if override_text else " -empty"),
                    )
                )
            chain = _SetupChain(self._agents, self._fill_backup, id="rs-backup")
            chain.load([agent for agent in self._backup if agent in self._agents])
            model_rows = []
            initial_active = set(self._initial_model_agents())
            for agent in self._agents:
                current_model = self._saved_models.get(agent, "")
                model_opts = relay_ops.cached_model_options(agent)
                agy_status = (
                    relay_ops.antigravity_models_status() if agent == "antigravity" else "ok"
                )
                checking = agent == "antigravity" and agy_status == "untried"
                failed = agent == "antigravity" and agy_status == "failed"
                picker = Horizontal(
                    *self._model_picker_controls(agent, model_opts, current_model),
                    id=f"rs-model-picker-{agent}",
                )
                status_text = (
                    CHECKING_MODELS if checking else (MODEL_REFRESH_FAILED if failed else "")
                )
                out_line = self._out_until.get(agent, "")
                model_rows.append(
                    Vertical(
                        Horizontal(
                            Label(f"Model ({agent}):", classes="field-label"),
                            picker,
                        ),
                        Static(
                            status_text,
                            id=f"rs-model-status-{agent}",
                            markup=False,
                            classes="model-status" + ("" if status_text else " -empty"),
                        ),
                        Static(
                            out_line,
                            id=f"rs-model-out-{agent}",
                            markup=False,
                            classes="model-out" + ("" if out_line else " -empty"),
                        ),
                        id=f"rs-model-row-{agent}",
                        classes="model-row" + ("" if agent in initial_active else " -empty"),
                    )
                )
            release_options = [("you", "human")] + [(a, a) for a in self._agents]
            release_values = [value for _label, value in release_options]
            release_blank = bool(
                self._release
                and self._release not in ("human", "you")
                and self._release not in self._agents
            )
            if release_blank:
                release = Select.BLANK
            elif self._release in release_values:
                release = self._release
            else:
                release = "human"
            roles_body = [
                Static("Recommended for the agents you have.", id="rs-recommended"),
                stale_widget,
                *rows,
                Horizontal(
                    Static("Committer: whyline (automatic)", id="rs-committer"),
                ),
                Horizontal(
                    Label("Release:", classes="field-label"),
                    Select(
                        release_options,
                        value=release,
                        allow_blank=release_blank,
                        id="rs-release",
                    ),
                ),
                Horizontal(
                    Label("Timeout:", classes="field-label"),
                    Select(
                        self._timeout_options(),
                        value=self._timeout,
                        allow_blank=False,
                        id="rs-timeout",
                    ).with_tooltip("How long one agent may run before the relay stops it"),
                ),
                Horizontal(
                    Label("Resolve:", classes="field-label"),
                    Select(
                        [
                            ("Review: show the fix, wait for my click", "review"),
                            ("Auto: apply the recommended fix and continue", "auto"),
                        ],
                        value=self._resolve_mode,
                        allow_blank=False,
                        id="rs-resolve-mode",
                    ),
                ),
                Label("Backup, used when an agent fails:"),
                chain,
                Static("", id="rs-meaning"),
                Vertical(*model_rows, id="rs-models"),
            ]
        else:
            roles_body = [
                Static(NO_SUBSCRIPTIONS, id="rs-empty", markup=False),
                stale_widget,
            ]

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
                        [(self._plan_label(p), str(getattr(p, "path", p))) for p in self._plans],
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
                *roles_body,
                id="rs-roles",
            ),
            id="rs-fields"),
            VerticalScroll(Static("", id="rs-checks", markup=False), id="rs-results"),
            Static("", id="rs-error", classes="-empty", markup=False),
            Horizontal(
                Button("Open Settings", id="rs-open-settings", variant="primary"),
                Button("Make a plan", id="rs-make-plan", variant="primary", disabled=not self._agents),
                Button("Check", id="rs-check", variant="primary", disabled=(not self._plans or not self._agents)),
                Button("Resolve", id="rs-resolve", variant="warning", disabled=True),
                Button("Resume" if self._paused else "Start", id="rs-start", variant="success", disabled=True),
                Button("Cancel", id="rs-cancel"),
                id="rs-buttons",
            ),
        )

    def _timeout_options(self) -> list[tuple[str, int]]:
        """30, 45, 60 minutes, then none (0). A saved value outside those stays
        selectable, so opening Set up never rewrites a timeout nobody touched."""
        minutes = sorted({*relay_ops.RELAY_TIMEOUT_OPTIONS, self._timeout} - {0})
        return [(f"{m} minutes", m) for m in minutes] + [("none (no limit)", 0)]

    def on_mount(self) -> None:
        has_choices = bool(self._agents)
        self.query_one("#rs-open-settings").display = not has_choices
        self.query_one("#rs-make-plan").display = has_choices and not self._plans
        if not has_choices:
            self.query_one("#rs-check", Button).display = False
            self.query_one("#rs-check", Button).disabled = True
            self.query_one("#rs-start", Button).display = False
            self.query_one("#rs-start", Button).disabled = True
            self.query_one("#rs-resolve", Button).display = False
            self.query_one("#rs-make-plan", Button).disabled = True
            if self.query("#rs-summary-row"):
                self.query_one("#rs-summary-row").display = False
            self.query_one("#rs-roles").display = True
            self.call_after_refresh(self._ready)
            return

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
        # Disabled saved members stay out of the editor; they remain a
        # separate stale blocker until None or Automatic replaces them.
        chain = self.query_one("#rs-backup", OrderedChain)
        if self._backup:
            chain.load([agent for agent in self._backup if agent in self._agents])
        else:
            chain.load(self._fill_backup())
        self._update_meaning()
        self._update_models()
        if getattr(self, "_focus_agent", None):
            target_id = f"rs-model-{self._focus_agent}"
            if self.query(f"#{target_id}"):
                widget = self.query_one(f"#{target_id}")
                self.call_after_refresh(widget.focus)
                row = self.query_one(f"#rs-model-row-{self._focus_agent}")
                self.call_after_refresh(row.scroll_visible)
        self.call_after_refresh(self._ready)

    def _initial_model_agents(self) -> list[str]:
        in_use = [
            self._roles.get("implementer"),
            self._roles.get("tester"),
            self._roles.get("reviewer"),
            self._release,
            *self._backup,
        ]
        if getattr(self, "_focus_agent", None):
            in_use.append(self._focus_agent)
        if hasattr(self, "_out_until"):
            in_use.extend(self._out_until.keys())
        res = []
        for a in in_use:
            if a and a in self._agents and a not in res:
                res.append(a)
        return res

    def _chosen_release(self) -> str:
        try:
            if self.query("#rs-release"):
                value = self.query_one("#rs-release", Select).value
                return "" if self._is_blank(value) else value
        except Exception:
            pass
        value = getattr(self, "_release", "human")
        return "" if self._is_blank(value) else value

    def _model_agents(self) -> list[str]:
        if not self._agents:
            return []
        implementer, tester, reviewer, backup = self._chosen()
        release = self._chosen_release()
        res = []
        for a in (implementer, tester, reviewer, release, *backup):
            if a and a in self._agents and a not in res:
                res.append(a)
        if getattr(self, "_focus_agent", None):
            if self._focus_agent in self._agents and self._focus_agent not in res:
                res.append(self._focus_agent)
        if hasattr(self, "_out_until"):
            for a in self._out_until:
                if a in self._agents and a not in res:
                    res.append(a)
        return res

    def _update_models(self) -> None:
        if not self._agents:
            return
        active = set(self._model_agents())
        for agent in self._agents:
            if self.query(f"#rs-model-row-{agent}"):
                row = self.query_one(f"#rs-model-row-{agent}")
                row.set_class(agent not in active, "-empty")

    def _chosen_model(self, agent: str) -> str:
        if self.query(f"#rs-model-{agent}"):
            widget = self.query_one(f"#rs-model-{agent}")
            if isinstance(widget, Input):
                return widget.value.strip()
            if isinstance(widget, Select):
                val = widget.value
                if val == "other":
                    if self.query(f"#rs-model-input-{agent}"):
                        return self.query_one(f"#rs-model-input-{agent}", Input).value.strip()
                    return ""
                return val if val != Select.BLANK else ""
        if self.query(f"#rs-model-input-{agent}"):
            return self.query_one(f"#rs-model-input-{agent}", Input).value.strip()
        return ""

    def _fill_backup(self) -> list[str]:
        """Names for an empty editor. Automatic is not a value Check stores."""
        from whyline import model

        primary, _chosen_model = model.resolve(self._root)
        usable = relay_ops.usable_agents(self._root, self._status)
        return relay_ops.staged_backup(primary, usable)

    def _update_meaning(self) -> None:
        if not self._agents:
            if self.query("#rs-meaning"):
                self.query_one("#rs-meaning", Static).update("")
            return
        i, t, r, _ = self._chosen()
        rel = self._chosen_release()
        if any(self._is_blank(value) for value in (i, t, r, rel)):
            self.query_one("#rs-meaning", Static).update("")
            return
        self.query_one("#rs-meaning", Static).update(relay_ops.role_meaning(i, t, r, rel))

    def _ready(self) -> None:
        self._filling = False
        self._start_model_discovery()

    def _model_picker_controls(
        self, agent: str, model_opts: list[tuple[str, str]] | None, current_model: str
    ) -> list:
        if model_opts is not None:
            opts = [("CLI default", "")]
            for lbl, val in model_opts:
                opts.append((lbl, val))
            known_vals = {v for _, v in opts}
            if current_model and current_model not in known_vals:
                opts.append((current_model, current_model))
            opts.append(("Other…", "other"))
            select_val = current_model if current_model in {v for _, v in opts} else "other"
            return [
                Select(
                    opts,
                    value=select_val,
                    allow_blank=False,
                    id=f"rs-model-{agent}",
                ),
                Input(
                    value=current_model if select_val == "other" else "",
                    placeholder="type model name",
                    classes="model-input" + ("" if select_val == "other" else " -empty"),
                    id=f"rs-model-input-{agent}",
                ),
            ]
        return [
            Input(
                value=current_model,
                placeholder="CLI default",
                classes="model-input",
                id=f"rs-model-{agent}",
            )
        ]

    def _set_model_status(self, agent: str, text: str) -> None:
        if not self.query(f"#rs-model-status-{agent}"):
            return
        widget = self.query_one(f"#rs-model-status-{agent}", Static)
        widget.update(text)
        widget.set_class(not text, "-empty")

    def _rebuild_model_picker(
        self,
        agent: str,
        model_opts: list[tuple[str, str]] | None,
        *,
        checking: bool = False,
        failed: bool = False,
    ) -> None:
        if not self.query(f"#rs-model-picker-{agent}"):
            return
        picker = self.query_one(f"#rs-model-picker-{agent}")
        current = self._chosen_model(agent) or self._saved_models.get(agent, "")
        self._filling = True
        try:
            picker.remove_children()
            for child in list(picker.children):
                picker._nodes._remove(child)
            for widget in self._model_picker_controls(agent, model_opts, current):
                picker.mount(widget)
            if checking:
                status = CHECKING_MODELS
            elif failed:
                status = MODEL_REFRESH_FAILED
            else:
                status = ""
            self._set_model_status(agent, status)
        finally:
            self._filling = False

    def _start_model_discovery(self) -> None:
        """After paint: one worker for an enabled Antigravity row with no cache."""
        if "antigravity" not in self._agents:
            return
        if relay_ops.antigravity_models_status() != "untried":
            return
        if not self.query("#rs-model-row-antigravity"):
            return
        token = object()
        self._model_token = token

        def work() -> None:
            try:
                models = relay_ops.antigravity_models()
            except Exception:
                models = None
            try:
                self.app.call_from_thread(self._on_antigravity_models, models, token)
            except Exception:
                return

        self.run_worker(work, thread=True, group="agy-models")

    def _on_antigravity_models(
        self, models: list[tuple[str, str]] | None, token: object
    ) -> None:
        if token is not self._model_token or not self.is_attached:
            return
        try:
            self._rebuild_model_picker(
                "antigravity", models, checking=False, failed=not models
            )
        except NoMatches:
            return

    def _error(self, text: str) -> None:
        error = self.query_one("#rs-error", Static)
        error.update(text)
        error.set_class(not text, "-empty")

    def _refresh_stale_warning(self) -> None:
        if not self.query("#rs-stale"):
            return
        text = self._stale_warning_text(self._disabled_selected())
        widget = self.query_one("#rs-stale", Static)
        widget.update(text)
        widget.set_class(not text, "-empty")

    def _invalidate(self) -> None:
        if self._filling:
            return
        self._token = object()
        self.query_one("#rs-checks", Static).update("")
        self.query_one("#rs-start", Button).disabled = True
        self.query_one("#rs-resolve", Button).disabled = True
        self._fail_lines = []
        self._cleared_info = None
        self._refresh_stale_warning()

    def on_select_changed(self, event: "Select.Changed") -> None:
        try:
            if self.query("#rs-release"):
                value = self.query_one("#rs-release", Select).value
                if not self._is_blank(value):
                    self._release = value
        except Exception:
            pass
        if event.select.id and event.select.id.startswith("rs-model-"):
            agent = event.select.id.removeprefix("rs-model-")
            if self.query(f"#rs-model-input-{agent}"):
                inp = self.query_one(f"#rs-model-input-{agent}", Input)
                if event.value == "other":
                    inp.remove_class("-empty")
                    inp.focus()
                else:
                    inp.add_class("-empty")
        self._invalidate()
        self._update_meaning()
        self._update_models()

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        self._invalidate()
        self._update_models()

    def on_input_changed(self, event: "Input.Changed") -> None:
        if event.input.id and (
            event.input.id.startswith("rs-model-") or event.input.id.startswith("rs-model-input-")
        ):
            self._invalidate()

    def _chosen(self) -> tuple[str, str, str, list[str]]:
        if not self._agents:
            return ("", "", "", [])
        implementer, tester, reviewer = (
            self.query_one(f"#rs-{role}", Select).value for role, _ in self.ROLES
        )
        backup = self.query_one("#rs-backup", OrderedChain).order()
        return (
            "" if self._is_blank(implementer) else implementer,
            "" if self._is_blank(tester) else tester,
            "" if self._is_blank(reviewer) else reviewer,
            backup,
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "rs-cancel":
            self._token = object()
            self._model_token = object()
            self.dismiss(None)
        elif event.button.id == "rs-open-settings":
            self._token = object()
            self._model_token = object()
            self.dismiss("open-settings")
        elif event.button.id == "rs-start":
            if not self._agents:
                return
            if self._paused:
                cleared_lines = []
                implementer, tester, reviewer, backup = self._chosen()
                picked = {"implementer": implementer, "tester": tester, "reviewer": reviewer}
                cleared = getattr(self, "_cleared_info", None)
                if cleared is None:
                    try:
                        cleared = relay_ops.save_roles(self._root, implementer, tester, reviewer, backup) or {}
                    except Exception:
                        cleared = {}
                for role, old_backup in (cleared or {}).items():
                    now_agent = picked.get(role, "")
                    cleared_lines.append(f"{role} was on backup {old_backup}; it now uses {now_agent}")
                self.dismiss(("resume", cleared_lines))
            else:
                self.dismiss("start")
        elif event.button.id == "rs-resolve":
            self.dismiss(("resolve", list(self._fail_lines)))
        elif event.button.id == "rs-check":
            self._check()
        elif event.button.id == "rs-looks-good":
            self._check()
        elif event.button.id == "rs-change":
            self.query_one("#rs-summary-row").display = False
            self.query_one("#rs-roles").display = True
            self.query_one("#rs-check").display = True
        elif event.button.id == "rs-make-plan":
            if not self._agents:
                return
            self.dismiss("plan")


    def _disabled_selected(self) -> list[str]:
        """Role, release, or backup-chain values that are still off in Settings."""
        if not self.query("#rs-implementer"):
            return list(self._stale)
        implementer, tester, reviewer, backup = self._chosen()
        release = self._chosen_release()
        found: list[str] = []
        for role, value in (
            ("implementer", implementer),
            ("tester", tester),
            ("reviewer", reviewer),
        ):
            if self._is_blank(value):
                if self._configured:
                    saved = self._configured_roles.get(role) or ""
                    if saved and saved not in self._enabled_providers:
                        found.append(saved)
                continue
            if value not in ("human", "you") and value not in self._enabled_providers:
                found.append(value)
        if self._is_blank(release):
            saved_release = self._release_saved
            if (
                self._configured
                and saved_release
                and saved_release not in ("human", "you")
                and saved_release not in self._enabled_providers
            ):
                found.append(saved_release)
        elif release not in ("human", "you") and release not in self._enabled_providers:
            found.append(release)
        for agent in backup:
            if agent and agent not in self._enabled_providers:
                found.append(agent)
        found.extend(self._backup_stale)
        return list(dict.fromkeys(name for name in found if name))

    def _check(self) -> None:
        if not self._agents:
            return
        stale = self._disabled_selected()
        if stale:
            listed = ", ".join(stale)
            self._token = object()
            self._error("")
            self.query_one("#rs-start", Button).disabled = True
            self.query_one("#rs-resolve", Button).disabled = True
            self._fail_lines = []
            self.query_one("#rs-checks", Static).update(
                f"FAIL  Saved configuration uses {listed}, which is off in Settings.\n"
                f"      fix: {STALE_CHECK_HINT}"
            )
            return
        token = object()
        self._token = token
        self._error("")
        self.query_one("#rs-start", Button).disabled = True
        self.query_one("#rs-resolve", Button).disabled = True
        self._fail_lines = []
        self.query_one("#rs-checks", Static).update("Checking…")
        root, chosen = self._root, self._chosen()
        release = self.query_one("#rs-release", Select).value
        timeout = self.query_one("#rs-timeout", Select).value
        resolve_mode = self.query_one("#rs-resolve-mode", Select).value
        plan = Path(self.query_one("#rs-plan", Select).value) if self._plans else None
        models_to_save = {a: self._chosen_model(a) for a in self._model_agents()}

        def in_thread() -> None:
            try:
                if "antigravity" in (chosen[0], chosen[1], chosen[2], release, *chosen[3]):
                    relay_ops.forget_antigravity_decline(root)
                cleared = relay_ops.save_roles(root, *chosen) or {}
                relay_ops.save_release(root, release)
                # Only on a change: each write is its own config commit.
                if timeout != relay_ops.relay_timeout(root):
                    relay_ops.save_timeout(root, timeout)
                if resolve_mode != relay_ops.resolve_mode(root):
                    relay_ops.save_resolve_mode(root, resolve_mode)
                for a, picked_model in models_to_save.items():
                    current_model = relay_ops.read_agent_model(root, a)
                    if picked_model != current_model:
                        relay_ops.save_agent_model(root, a, picked_model)
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
            self.app.call_from_thread(self._show_checks, checks, running, cleared, token)

        self.run_worker(in_thread, thread=True)

    def _check_failed(self, error: Exception, token: object) -> None:
        if token is not self._token or not self.is_attached:
            return  # cancelled, re-checked, or the popup has closed
        try:
            self.query_one("#rs-checks", Static).update("")
            self.query_one("#rs-resolve", Button).disabled = True
            self._fail_lines = []
            self._error(str(error) or error.__class__.__name__)
        except NoMatches:
            return  # the popup's children were removed during teardown

    def _show_checks(
        self, checks: list, running: str | None, cleared: dict[str, str], token: object
    ) -> None:
        if token is not self._token or not self.is_attached:
            return  # cancelled, re-checked, or the popup has closed
        self._cleared_info = cleared or {}
        try:
            from whyline_relay import failover

            self._overrides = failover.read_overrides(self._root)
        except Exception:
            self._overrides = {}
        for role, _ in self.ROLES:
            try:
                widget = self.query_one(f"#rs-{role}-override", Static)
                override = self._overrides.get(role)
                if override is not None:
                    widget.update(
                        f"now on backup {override.agent} ({override.backup_for} hit a limit)"
                    )
                    widget.remove_class("-empty")
                else:
                    widget.update("")
                    widget.add_class("-empty")
            except NoMatches:
                pass
        lines = []
        fail_lines = []
        for check in checks:
            line = f"{check.status:<4}  {check.message}"
            if check.status != "ok" and check.hint:
                line += f"\n      fix: {check.hint}"
            lines.append(line)
            if check.status == "FAIL":
                fail_lines.append(f"{check.status:<4}  {check.message}")
        failures = sum(check.status == "FAIL" for check in checks)
        lines.append("All checks passed." if failures == 0 else f"{failures} problem(s) found.")
        self._fail_lines = fail_lines
        try:
            self.query_one("#rs-checks", Static).update("\n".join(lines))
            if running:
                self._error(f"A relay is already running here ({running}).")
            self.query_one("#rs-start", Button).disabled = failures > 0 or bool(running)
            self.query_one("#rs-resolve", Button).disabled = failures == 0
        except NoMatches:
            return  # the popup's children were removed during teardown


class ResolveProposalScreen(ModalScreen):
    """The Resolve proposal screen showing the diagnosis and numbered steps."""

    DEFAULT_CSS = """
    ResolveProposalScreen {
        align: center middle;
    }
    #rps-dialog {
        width: 80;
        height: auto;
        max-height: 85%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #rps-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #rps-diagnosis {
        margin-bottom: 1;
    }
    #rps-notes {
        color: $warning;
        margin-bottom: 1;
    }
    #rps-notes.-empty, #rps-result.-empty {
        display: none;
    }
    #rps-result {
        margin-bottom: 1;
    }
    #rps-steps {
        margin-bottom: 1;
    }
    #rps-buttons {
        height: auto;
        align: right middle;
    }
    #rps-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        root: Path | str,
        diagnosis: str = "",
        steps: list[dict] | None = None,
        notes: list[str] | None = None,
        *,
        launch: object = None,
        proposal: object = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._root = Path(root).resolve()
        if proposal is not None:
            self._diagnosis = str(getattr(proposal, "diagnosis", diagnosis) or diagnosis)
            self._steps = list(getattr(proposal, "steps", steps or []) or [])
            self._notes = list(getattr(proposal, "notes", notes or []) or [])
        else:
            self._diagnosis = diagnosis
            self._steps = list(steps or [])
            self._notes = list(notes or [])
        self._launch = launch
        self._applying = False
        self._result: object = None

    def compose(self) -> ComposeResult:
        from whyline.console import recovery

        with Vertical(id="rps-dialog"):
            yield Label("Agent Diagnosis & Proposed Steps", id="rps-title")
            yield Static(f"Diagnosis:\n{self._diagnosis}", id="rps-diagnosis")
            notes_text = "\n".join(f"- {n}" for n in self._notes) if self._notes else ""
            notes_classes = "" if notes_text else "-empty"
            yield Static(f"Notes:\n{notes_text}", id="rps-notes", classes=notes_classes)
            step_lines = [
                f"{i}. {recovery.format_step_label(step)}"
                for i, step in enumerate(self._steps, 1)
            ]
            steps_content = "\n".join(step_lines) if step_lines else "No steps proposed."
            yield Static(f"Proposed Steps:\n{steps_content}", id="rps-steps")
            yield Static("", id="rps-result", classes="-empty")
            with Horizontal(id="rps-buttons"):
                yield Button(
                    "Apply all", id="apply-all", variant="primary", disabled=not self._steps
                )
                yield Button("Apply step 1 only", id="apply-step-1", disabled=not self._steps)
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "apply-all":
            self._start_apply(all_steps=True)
        elif button_id == "apply-step-1":
            self._start_apply(all_steps=False)
        elif button_id == "cancel":
            self.dismiss(self._result if self._result is not None else "cancel")

    def _start_apply(self, all_steps: bool) -> None:
        """Run the steps off the UI thread: the console's launcher reaches the
        app through call_from_thread, which refuses the app's own thread."""
        from whyline.console import recovery

        if self._applying or self._result is not None:
            return
        self._applying = True
        for bid in ("apply-all", "apply-step-1", "cancel"):
            self.query_one(f"#{bid}", Button).disabled = True
        steps_to_run = self._steps if all_steps else self._steps[:1]

        def in_thread() -> None:
            try:
                res = recovery.apply_steps(self._root, steps_to_run, launch=self._launch)
            except Exception as exc:
                res = recovery.StepApplyResult(success=False, message=f"Resolve error: {exc}")
            self.app.call_from_thread(self._apply_finished, res)

        self.run_worker(in_thread, thread=True)

    def _apply_finished(self, res: object) -> None:
        self._applying = False
        self._result = res
        try:
            result = self.query_one("#rps-result", Static)
            result.update(str(getattr(res, "message", res) or ""))
            result.remove_class("-empty")
            close = self.query_one("#cancel", Button)
            close.label = "Close"
            close.disabled = False
        except NoMatches:
            return  # the popup's children were removed during teardown

    def _apply(self, all_steps: bool = True) -> None:
        from whyline.console import recovery

        steps_to_run = self._steps if all_steps else self._steps[:1]
        res = recovery.apply_steps(self._root, steps_to_run, launch=self._launch)
        try:
            self.dismiss(res)
        except Exception:
            pass

    def apply_all(self) -> None:
        self._apply(all_steps=True)

    def apply_step_1(self) -> None:
        self._apply(all_steps=False)
