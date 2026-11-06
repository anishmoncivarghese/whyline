"""The Security popup (findings, Fix, Ignore once, Allow, scans) and the
Security section of the Release Set up tab. Scans, the editor and the tools
lookup are injected, so nothing here needs git, the network or an installed tool."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

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
    .sec-row { height: auto; margin-bottom: 1; }
    .sec-row Static { width: 1fr; }
    .sec-row Button { margin-left: 1; }
    #sec-allow, #sec-actions { height: auto; }
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
            with VerticalScroll(id="sec-list"):
                pass
            with Vertical(id="sec-allow", classes="-hidden"):
                yield Static("", id="sec-allow-what", markup=False)
                yield Input(placeholder="Why is this safe?", id="sec-reason")
                with Horizontal():
                    yield Button("Allow", id="sec-allow-ok", variant="warning")
                    yield Button("Cancel", id="sec-allow-cancel")
            with Horizontal(id="sec-actions"):
                yield Button("Scan again", id="sec-rescan")
                yield Button("Scan history", id="sec-history")
                yield Button("Stop", id="sec-stop", disabled=True)
                yield Button("Copy report", id="sec-copy")
                yield Button("Close", id="sec-close")

    async def on_mount(self) -> None:
        if self._scan_on_open:
            self._start_scan("release")

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
        if bid == "sec-close":
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
        if self._cancel is not None:
            self._cancel.set()
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
