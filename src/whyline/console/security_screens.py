"""The Security popup (findings, Fix, Ignore once, Allow, scans) and the
Security section of the Release Set up tab. Scans, the editor and the tools
lookup are injected, so nothing here needs git, the network or an installed tool."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TabbedContent, TabPane

from whyline.release import config as release_config
from whyline.security import external, scan
from whyline.security import settings as st
from whyline.security.findings import Finding
from whyline.security.settings import SecuritySettings

BREW_COMMAND = "brew install gitleaks osv-scanner"
BREW_HINT = f"Install the optional scanners with: {BREW_COMMAND}"
ROTATE_HINT = "Rotate this key; deleting it doesn't remove it from history once pushed."
REASON_NEEDED = "Allowing a finding needs a reason."
BADGES = {"critical": "[CRIT]", "high": "[HIGH]", "medium": "[MED]", "low": "[LOW]",
          "unknown": "[?]"}
KINDS = (("secret", "Secrets"), ("dependency", "Dependencies"),
         ("contents", "Package contents"), ("audit", "Audit"))
_ORDER = {name: i for i, name in enumerate(BADGES)}
BLOCK_LEVELS = (("block", "block"), ("warn", "warn"), ("off", "off"))
DEP_LEVELS = (("block", "block"), ("block-high", "block-high"), ("warn", "warn"), ("off", "off"))
AUDIT_LEVELS = tuple((v, v) for v in st.AUDIT)
AUDIT_NOTICE = ("The deep audit uses your main agent, may take a long time and many tokens, "
                "and a single run finds only part of what repeated runs do.")


# -- pure helpers ---------------------------------------------------------------


def badge(finding: Finding) -> str:
    return BADGES.get(finding.severity, BADGES["unknown"])


def group_findings(findings) -> list[tuple[str, list[Finding]]]:
    """Findings by kind in a fixed order, worst severity first; empty kinds left out."""
    groups = []
    for kind, title in KINDS:
        rows = sorted((f for f in findings if f.kind == kind),
                      key=lambda f: _ORDER.get(f.severity, len(_ORDER)))
        if rows:
            groups.append((title, rows))
    return groups


def where(finding: Finding) -> str:
    return f"{finding.path}:{finding.line}" if finding.path and finding.line else finding.path


def hint(finding: Finding) -> str:
    """The fix hint; a secret's also says to rotate the key."""
    if finding.kind != "secret":
        return finding.fix_hint
    return f"{finding.fix_hint} {ROTATE_HINT}".strip()


def finding_text(finding: Finding) -> str:
    head = f"{badge(finding)} {finding.title}"
    bits = [where(finding), finding.commit[:7] if finding.commit else "", finding.preview]
    lines = [head, "    " + "  ".join(b for b in bits if b)]
    if hint(finding):
        lines.append(f"    {hint(finding)}")
    return "\n".join(lines)


def report_text(findings) -> str:
    """A copyable report: the masked preview only, never a whole value."""
    lines: list[str] = []
    for title, rows in group_findings(findings):
        lines.append(f"{title}:")
        for f in rows:
            place = "  ".join(b for b in (where(f), f.commit[:7] if f.commit else "") if b)
            lines.append(f"  {badge(f)} {f.title} {place} {f.preview}".rstrip())
            if hint(f):
                lines.append(f"      {hint(f)}")
    return "\n".join(lines) if lines else "No findings."


def elapsed_text(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def audit_finding_text(finding: Finding) -> str:
    place = where(finding)
    head = f"{finding.rule} {badge(finding)} {finding.title}"
    return "\n".join([head, *([f"    {place}"] if place else [])])


def audit_run_text(run_: scan.AuditRun) -> str:
    if not run_.valid:
        return f"Run {run_.number}: findings.json is invalid"
    return (f"Run {run_.number}: {run_.count('confirmed')} confirmed, "
            f"{run_.count('needs_validation')} need validation, {run_.rejected} rejected")


def progress_text(done: int, total: int) -> str:
    return f"commits {done} of {total}" if total else f"commits {done}"


def rules_text() -> str:
    try:
        from importlib import resources
        raw = resources.files("whyline.security").joinpath("rules/VERSION").read_text("utf-8")
    except (OSError, ModuleNotFoundError):
        return "Rules: version unknown"
    version, _, when = raw.strip().partition(" ")
    return f"Rules: {version}" + (f", {when}" if when else "")


def tools_text(tools: dict[str, str]) -> tuple[str, bool]:
    """The tools line and whether any optional tool is missing."""
    names = (*external.SECRET_TOOLS, external.DEP_TOOL)
    lines = [f"{name}: {tools.get(name, 'not found')}" for name in names]
    missing = any(name not in tools for name in names)
    if missing:
        lines.append(BREW_HINT)
    return "\n".join(lines), missing


# -- the popup --------------------------------------------------------------------


def _default_open(root: Path) -> Callable[[Path, int], str]:
    def opener(path: Path, line: int) -> str:
        from whyline.console.ideas_screen import _open_with_macos
        return _open_with_macos(path)
    return opener


class SecurityScreen(ModalScreen):
    """Findings from the last scan. Closes with None."""

    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    SecurityScreen { align: center middle; }
    #sec-box { width: 90%; max-width: 110; height: 90%; border: round $accent; background: $surface; padding: 1 2; }
    #sec-list { height: 1fr; }
    #aud-list { height: 1fr; }
    .sec-row { height: auto; margin-bottom: 1; }
    .sec-row Static { width: 1fr; }
    .sec-row Button { margin-left: 1; }
    #sec-allow, #sec-actions, #aud-confirm, #aud-actions { height: auto; }
    #sec-tabs { height: 1fr; }
    #sec-allow { border: round $primary; padding: 0 1; }
    .-hidden { display: none; }
    """

    def __init__(
        self,
        root: Path | str,
        *,
        config: release_config.ReleaseConfig | None = None,
        scan_run: Callable[..., scan.ScanReport] | None = None,
        open_file: Callable[[Path, int], str] | None = None,
        scan_on_open: bool = True,
        audit_run: Callable[..., object] | None = None,
        audit_base: Path | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__()
        self.root = Path(root)
        self._cfg = config
        self._scan_run = scan_run or scan.run
        self._open_file = open_file or _default_open(self.root)
        self._scan_on_open = scan_on_open
        self._findings: list[Finding] = []
        self._allowing: Finding | None = None
        self._cancel: threading.Event | None = None
        self._audit_run = audit_run or scan.run_audit
        self._audit_base = audit_base
        self._clock = clock or time.monotonic
        self._audit_cancel: threading.Event | None = None
        self._audit_started = 0.0
        self._audit_progress = ""
        self._audit_runs: list[scan.AuditRun] = []
        self._audit_shown: scan.AuditRun | None = None

    @property
    def findings(self) -> list[Finding]:
        return list(self._findings)

    def _config(self) -> release_config.ReleaseConfig:
        if self._cfg is None:
            self._cfg = release_config.load(self.root)
        return self._cfg

    def compose(self) -> ComposeResult:
        with Vertical(id="sec-box"):
            yield Label("Security", id="sec-title")
            yield Static("", id="sec-status", markup=False)
            with TabbedContent(id="sec-tabs"):
                with TabPane("Findings", id="sec-tab-findings"):
                    with VerticalScroll(id="sec-list"):
                        pass
                    with Vertical(id="sec-allow", classes="-hidden"):
                        yield Static("", id="sec-allow-what", markup=False)
                        yield Input(placeholder="Why is this safe?", id="sec-reason")
                        with Horizontal():
                            yield Button("Allow", id="sec-allow-ok", variant="warning")
                            yield Button("Cancel", id="sec-allow-cancel")
                with TabPane("Audit", id="sec-tab-audit"):
                    yield Static("", id="aud-status", markup=False)
                    with Vertical(id="aud-confirm", classes="-hidden"):
                        yield Static(AUDIT_NOTICE, id="aud-notice", markup=False)
                        with Horizontal():
                            yield Button("Start audit", id="aud-start", variant="warning")
                            yield Button("Cancel", id="aud-cancel")
                    with Horizontal(id="aud-actions"):
                        yield Button("Run deep audit", id="aud-run")
                        yield Button("Stop", id="aud-stop", disabled=True)
                        yield Button("Open report", id="aud-open", disabled=True)
                    with VerticalScroll(id="aud-list"):
                        pass
            with Horizontal(id="sec-actions"):
                yield Button("Scan again", id="sec-rescan")
                yield Button("Scan history", id="sec-history")
                yield Button("Stop", id="sec-stop", disabled=True)
                yield Button("Copy report", id="sec-copy")
                yield Button("Close", id="sec-close")

    async def on_mount(self) -> None:
        self.set_interval(1.0, self._tick_audit)
        await self._refresh_audit()
        if self._scan_on_open:
            self._start_scan("release")

    # -- the Audit tab --------------------------------------------------------

    def _audit_say(self, text: str) -> None:
        self.query_one("#aud-status", Static).update(text)

    def _audit_running(self) -> bool:
        return self._audit_cancel is not None

    def _tick_audit(self) -> None:
        if self._audit_running():
            self._audit_say(self._audit_line())

    def _audit_line(self) -> str:
        spent = elapsed_text(self._clock() - self._audit_started)
        return f"Auditing… {spent} elapsed. {self._audit_progress}".strip()

    async def _refresh_audit(self, show: scan.AuditRun | None = None) -> None:
        self._audit_runs = scan.audit_runs(self.root, self._audit_base)
        self._audit_shown = show or next((r for r in self._audit_runs if r.valid), None)
        shown = self._audit_shown
        self.query_one("#aud-open", Button).disabled = not (shown and shown.has_report)
        box = self.query_one("#aud-list", VerticalScroll)
        await box.remove_children()
        widgets: list = []
        if shown is None:
            widgets.append(Static("No audit has been run yet.", id="aud-empty"))
        else:
            widgets.append(Label(f"Run {shown.number}", classes="sec-group"))
            rows = scan.sort_audit_findings(shown.findings)
            widgets.extend(Static(audit_finding_text(f), markup=False, classes="aud-finding")
                           for f in rows)
            if not rows:
                widgets.append(Static("No findings in this run.", classes="aud-finding"))
        if self._audit_runs:
            widgets.append(Label("Past runs", classes="sec-group"))
        for r in self._audit_runs:
            widgets.append(Horizontal(
                Static(audit_run_text(r), markup=False, classes="aud-run-text"),
                Button("Show", id=f"aud-show-{r.number}", disabled=not r.valid),
                Button("Open report", id=f"aud-report-{r.number}", disabled=not r.has_report),
                classes="sec-row"))
        await box.mount_all(widgets)

    def _start_audit(self) -> None:
        self.query_one("#aud-confirm").add_class("-hidden")
        self._audit_cancel = threading.Event()
        self._audit_started = self._clock()
        self._audit_progress = ""
        self.query_one("#aud-run", Button).disabled = True
        self.query_one("#aud-stop", Button).disabled = False
        self._audit_say(self._audit_line())
        cancel = self._audit_cancel
        self.run_worker(lambda: self._audit_in_thread(cancel), thread=True, exclusive=True,
                        group="sec-audit", name="security-audit")

    def _audit_in_thread(self, cancel: threading.Event) -> None:
        def on_progress(message: str) -> None:
            self.app.call_from_thread(self._set_audit_progress, message)

        extra = {"out_dir": self._audit_base} if self._audit_base else {}
        try:
            report = self._audit_run(self.root, cancel_event=cancel, on_progress=on_progress, **extra)
            error = ""
        except Exception as exc:  # noqa: BLE001 - shown instead of crashing the popup
            report, error = None, str(exc)
        self.app.call_from_thread(self._audit_done, report, error)

    def _set_audit_progress(self, message: str) -> None:
        self._audit_progress = message

    async def _audit_done(self, report, error: str) -> None:
        self._audit_cancel = None
        self.query_one("#aud-run", Button).disabled = False
        self.query_one("#aud-stop", Button).disabled = True
        if error:
            self._audit_say(f"The audit could not run: {error}")
        elif getattr(report, "cancelled", False):
            self._audit_say("The audit was stopped.")
        else:
            self._audit_say(getattr(report, "summary", "") or "The audit finished.")
        await self._refresh_audit()

    def _open_report(self, run_: scan.AuditRun | None) -> None:
        if run_ is None or not run_.has_report:
            self._audit_say("This run has no REPORT.md.")
            return
        message = self._open_file(run_.report_path, 0)
        self._audit_say(f"Could not open the report: {message}" if message
                        else f"Opened {run_.report_path}.")

    async def _show_run(self, number: int) -> None:
        run_ = next((r for r in self._audit_runs if r.number == number), None)
        if run_ is not None and run_.valid:
            await self._refresh_audit(run_)

    def _audit_button(self, bid: str) -> None:
        if bid == "aud-run":
            if not self._audit_running():
                self.query_one("#aud-confirm").remove_class("-hidden")
        elif bid == "aud-cancel":
            self.query_one("#aud-confirm").add_class("-hidden")
        elif bid == "aud-start":
            if not self._audit_running():
                self._start_audit()
        elif bid == "aud-stop":
            if self._audit_cancel is not None:
                self._audit_cancel.set()
            self._audit_say("Stopping…")
        elif bid == "aud-open":
            self._open_report(self._audit_shown)
        else:
            kind, _, number = bid[len("aud-"):].partition("-")
            if number.isdigit() and kind == "show":
                self.call_later(self._show_run, int(number))
            elif number.isdigit() and kind == "report":
                self._open_report(next((r for r in self._audit_runs
                                        if r.number == int(number)), None))

    # -- scans ----------------------------------------------------------------

    def _status(self, text: str) -> None:
        self.query_one("#sec-status", Static).update(text)

    def _busy(self, busy: bool, *, stoppable: bool = False) -> None:
        for bid in ("sec-rescan", "sec-history"):
            self.query_one(f"#{bid}", Button).disabled = busy
        self.query_one("#sec-stop", Button).disabled = not stoppable

    def _start_scan(self, scope: str) -> None:
        try:
            cfg = self._config()
        except Exception as exc:  # noqa: BLE001 - shown instead of crashing the popup
            self._status(f"Could not read the settings: {exc}")
            return
        self._cancel = threading.Event()
        history = scope == "history"
        self._busy(True, stoppable=history)
        self._status("Scanning history…" if history else "Scanning…")
        cancel = self._cancel
        self.run_worker(lambda: self._scan_in_thread(scope, cfg, cancel), thread=True,
                        exclusive=True, group="sec-scan", name=f"security-{scope}")

    def _scan_in_thread(self, scope: str, cfg, cancel: threading.Event) -> None:
        def on_progress(done: int, total: int) -> None:
            self.app.call_from_thread(self._status, progress_text(done, total))

        kwargs = {"branch": cfg.branch, "cancel_event": cancel}
        if scope == "history":
            kwargs["on_progress"] = on_progress
        try:
            report = self._scan_run(self.root, scope, cfg.security, **kwargs)
        except Exception as exc:  # noqa: BLE001
            report = scan.ScanReport(scope, error=str(exc))
        self.app.call_from_thread(self._show_report, report)

    async def _show_report(self, report: scan.ScanReport) -> None:
        self._busy(False)
        if report.error:
            self._status(f"Security scan failed: {report.error}")
        else:
            d = report.decision
            tail = " The scan was stopped; results are partial." if report.cancelled else ""
            self._status(f"{len(d.blocking)} blocking, {len(d.warnings)} warnings, "
                         f"{len(d.allowed)} allowed.{tail}")
        d = report.decision
        self._findings = [*d.blocking, *d.warnings]
        await self._rebuild()

    async def _rebuild(self) -> None:
        box = self.query_one("#sec-list", VerticalScroll)
        await box.remove_children()
        widgets = []
        n = 0
        for title, rows in group_findings(self._findings):
            widgets.append(Label(title, classes="sec-group"))
            for f in rows:
                index = self._findings.index(f)
                row = Horizontal(
                    Static(finding_text(f), markup=False, classes="sec-text"),
                    Button("Fix", id=f"sec-fix-{index}"),
                    Button("Ignore once", id=f"sec-ignore-{index}"),
                    Button("Allow…", id=f"sec-allow-{index}"),
                    classes="sec-row",
                )
                widgets.append(row)
                n += 1
        if not widgets:
            widgets.append(Static("No findings.", id="sec-empty"))
        await box.mount_all(widgets)

    # -- buttons --------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id or ""
        if bid.startswith("aud-"):
            self._audit_button(bid)
        elif bid == "sec-close":
            self.action_close()
        elif bid == "sec-rescan":
            self._start_scan("release")
        elif bid == "sec-history":
            self._start_scan("history")
        elif bid == "sec-stop":
            if self._cancel is not None:
                self._cancel.set()
            self._status("Stopping…")
        elif bid == "sec-copy":
            self.app.copy_to_clipboard(report_text(self._findings))
            self._status("Copied the report (values are masked).")
        elif bid == "sec-allow-ok":
            self._confirm_allow()
        elif bid == "sec-allow-cancel":
            self._show_allow(None)
        elif bid.startswith(("sec-fix-", "sec-ignore-", "sec-allow-")):
            action, _, number = bid[len("sec-"):].partition("-")
            if number.isdigit() and int(number) < len(self._findings):
                finding = self._findings[int(number)]
                {"fix": self._fix, "ignore": self._ignore, "allow": self._show_allow}[action](finding)

    def _fix(self, finding: Finding) -> None:
        path = self.root / finding.path if finding.path else self.root
        message = self._open_file(path, finding.line)
        lines = [f"Opened {where(finding) or finding.rule}." if not message
                 else f"Could not open {where(finding)}: {message}"]
        if hint(finding):
            lines.append(hint(finding))
        self._status("\n".join(lines))

    async def _remove(self, finding: Finding) -> None:
        self._findings = [f for f in self._findings if f is not finding]
        await self._rebuild()

    def _ignore(self, finding: Finding) -> None:
        try:
            st.ignore_once(scan.state_dir(self.root), finding)
        except (OSError, st.SettingsError) as exc:
            self._status(f"Could not ignore: {exc}")
            return
        self._status("Ignored for this release run.")
        self.call_later(self._remove, finding)

    def _show_allow(self, finding: Finding | None) -> None:
        self._allowing = finding
        panel = self.query_one("#sec-allow")
        panel.set_class(finding is None, "-hidden")
        reason = self.query_one("#sec-reason", Input)
        reason.value = ""
        if finding is not None:
            self.query_one("#sec-allow-what", Static).update(
                f"Allow {finding.title} in {where(finding) or finding.rule}? "
                "This is saved in .whyline/security-allow.toml.")
            reason.focus()

    def _confirm_allow(self) -> None:
        finding = self._allowing
        if finding is None:
            return
        reason = self.query_one("#sec-reason", Input).value.strip()
        if not reason:
            self._status(REASON_NEEDED)
            return
        try:
            st.allow(self.root, finding, reason)
        except (OSError, st.SettingsError) as exc:
            self._status(f"Could not allow: {exc}")
            return
        self._show_allow(None)
        self._status("Allowed; it is on the committed allowlist.")
        self.call_later(self._remove, finding)

    def action_close(self) -> None:
        for event in (self._cancel, self._audit_cancel):
            if event is not None:
                event.set()
        self.dismiss(None)


# -- the Set up tab section ---------------------------------------------------------


def compose_security_setup(settings: SecuritySettings,
                           tools: dict[str, str] | None = None) -> ComposeResult:
    """Widgets for the Security section; `collect_security` reads them back."""
    found = external.available() if tools is None else tools
    text, missing = tools_text(found)
    yield Label("Security")
    yield Label("Secrets")
    yield Select(BLOCK_LEVELS, value=settings.secrets, allow_blank=False, id="rs-sec-secrets")
    yield Label("Dependencies")
    yield Select(DEP_LEVELS, value=settings.dependencies, allow_blank=False,
                 id="rs-sec-dependencies")
    yield Label("Package contents")
    yield Select(BLOCK_LEVELS, value=settings.contents, allow_blank=False, id="rs-sec-contents")
    yield Checkbox("Check every commit", settings.pre_commit, id="rs-sec-pre-commit")
    yield Label("Deep audit")
    yield Select(AUDIT_LEVELS, value=settings.audit, allow_blank=False, id="rs-sec-audit")
    yield Static(text, id="rs-sec-tools", markup=False)
    yield Button("Copy", id="rs-sec-copy", classes="-hidden" if not missing else "")
    yield Static("", id="rs-sec-hook-line", markup=False, classes="-hidden")
    yield Button("Copy", id="rs-sec-hook-copy", classes="-hidden")
    yield Static(rules_text(), id="rs-sec-rules", markup=False)
    yield Button("Open Security…", id="rs-sec-open")


def collect_security(screen, base: SecuritySettings) -> SecuritySettings:
    def pick(name: str, choices) -> str:
        value = screen.query_one(f"#rs-sec-{name}", Select).value
        return str(value) if value in {v for _, v in choices} else getattr(base, name)

    return replace(
        base,
        secrets=pick("secrets", BLOCK_LEVELS),
        dependencies=pick("dependencies", DEP_LEVELS),
        contents=pick("contents", BLOCK_LEVELS),
        audit=pick("audit", AUDIT_LEVELS),
        pre_commit=screen.query_one("#rs-sec-pre-commit", Checkbox).value,
    )


def apply_commit_hook(root: Path, settings: SecuritySettings) -> str:
    """The Check every commit switch: install or remove the pre-commit hook, as
    `whyline security hook install|uninstall` does. Returns a status line or ''."""
    from whyline.security import hook

    return hook.set_installed(root, settings.pre_commit)
