"""The Release popup: pick a version and mode, run the Ready check, see the
planned steps, and Start. Starting is handed to an injected `start_release`
(the console wires it to the real run); nothing here publishes anything."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TabbedContent, TabPane

from whyline.release import config as release_config
from whyline.release import plan as release_plan
from whyline.release import ready as release_ready
from whyline.release import version as release_version

CUSTOM = "custom"
CURRENT = "current"
VERSION_KINDS = (*release_version.BUMPS, CURRENT, CUSTOM)
SETUP_LATER = "Set up comes in a later task"
IRREVERSIBLE_MARK = "⚠"


@dataclass(frozen=True)
class ReleaseChoice:
    version: str
    mode: str


def next_versions(current: str) -> dict[str, str]:
    """The version each choice gives; a choice that cannot be worked out is left out."""
    found = {CURRENT: current}
    for kind in release_version.BUMPS:
        try:
            found[kind] = release_version.bump(current, kind)
        except release_version.VersionError:
            pass
    return found


def _default_steps(root: Path, cfg, version: str) -> list[tuple[str, bool]]:
    plan = release_plan.build(root, cfg, version)
    return [(step.title, step.irreversible) for step in plan.steps]


class ReleaseScreen(ModalScreen):
    """Closes with None on Close, or after calling start_release(choice) on Start."""

    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    ReleaseScreen { align: center middle; }
    #release-box { width: 90%; max-width: 100; height: 90%; border: round $accent; background: $surface; padding: 1 2; }
    #release-body { height: 1fr; }
    #release-custom { display: none; }
    #release-actions { height: auto; }
    """

    def __init__(
        self,
        root: Path | str,
        *,
        start_release: Callable[[ReleaseChoice], object],
        config: release_config.ReleaseConfig | None = None,
        current_version: str | None = None,
        ready_check: Callable[[str], list[release_ready.ReadyItem]] | None = None,
        steps: Callable[[str], list[tuple[str, bool]]] | None = None,
    ) -> None:
        super().__init__()
        self.root = Path(root)
        self._start_release = start_release
        self._cfg = config
        self._current = current_version
        self._ready_check = ready_check
        self._steps = steps
        self._items: list[release_ready.ReadyItem] | None = None
        self._checked_version = ""
        self._load_error = ""

    # -- inputs -------------------------------------------------------------

    def _config(self) -> release_config.ReleaseConfig:
        if self._cfg is None:
            self._cfg = release_config.load(self.root)
        return self._cfg

    def current_version(self) -> str:
        if self._current is None:
            self._current = release_version.current(self.root, self._config())
        return self._current

    def _version_options(self) -> dict[str, str]:
        try:
            return next_versions(self.current_version())
        except Exception as exc:  # noqa: BLE001 - shown in the popup instead of crashing it
            self._load_error = str(exc)
            return {}

    def chosen_version(self) -> str:
        """The version the form currently asks for; "" when it is not valid."""
        kind = self.query_one("#release-kind", Select).value
        if kind == CUSTOM:
            text = self.query_one("#release-custom", Input).value.strip()
            try:
                return release_version.validate(text)
            except release_version.VersionError:
                return ""
        return self._version_options().get(str(kind), "")

    def chosen_mode(self) -> str:
        value = self.query_one("#release-mode", Select).value
        return str(value) if value in release_config.MODES else "ask"

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        options = self._version_options()
        kinds = [(f"{kind} → {options[kind]}" if kind in options else kind, kind)
                 for kind in VERSION_KINDS if kind == CUSTOM or kind in options]
        try:
            mode = self._config().mode
        except Exception:  # noqa: BLE001 - the popup still opens; the versions line says why
            mode = "ask"
        with Vertical(id="release-box"):
            yield Label("Release", id="release-title")
            with TabbedContent(initial="release-tab"):
                with TabPane("Release", id="release-tab"):
                    with VerticalScroll(id="release-body"):
                        yield Static(self._versions_text(options), id="release-versions")
                        yield Select(kinds, value="patch" if "patch" in options else CUSTOM,
                                     allow_blank=False, id="release-kind")
                        yield Input(placeholder="X.Y.Z", id="release-custom")
                        yield Select([(m, m) for m in release_config.MODES], value=mode,
                                     allow_blank=False, id="release-mode")
                        yield Static("", id="release-check-result")
                        yield Static("", id="release-steps")
                with TabPane("Set up", id="setup-tab"):
                    yield Static(SETUP_LATER, id="release-setup-later")
            with Horizontal(id="release-actions"):
                yield Button("Check", id="release-check")
                yield Button("Start", id="release-start", variant="primary", disabled=True)
                yield Button("Close", id="release-close")

    def _versions_text(self, options: dict[str, str]) -> str:
        if not options:
            return f"Could not read the version: {self._load_error}" if self._load_error else ""
        text = f"Current version: {options[CURRENT]}"
        nxt = options.get("patch")
        return f"{text} · next: {nxt}" if nxt else text

    def on_mount(self) -> None:
        self._show_steps()

    # -- events -------------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "release-kind":
            self.query_one("#release-custom", Input).display = event.value == CUSTOM
            self._invalidate()
            self._show_steps()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "release-custom":
            self._invalidate()
            self._show_steps()

    def _invalidate(self) -> None:
        """A different version needs its own check; Start waits for it."""
        self._items = None
        self.query_one("#release-start", Button).disabled = True
        self.query_one("#release-check-result", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "release-close":
            self.dismiss(None)
        elif button_id == "release-check":
            self._run_check()
        elif button_id == "release-start":
            self._start()

    def action_close(self) -> None:
        self.dismiss(None)

    # -- steps --------------------------------------------------------------

    def steps_text(self, version: str) -> str:
        if not version:
            return "Pick a valid version to see the steps."
        try:
            source = self._steps or (lambda v: _default_steps(self.root, self._config(), v))
            steps = source(version)
        except Exception as exc:  # noqa: BLE001
            return f"Could not list the steps: {exc}"
        lines = [f"Steps for {version}:"]
        for title, irreversible in steps:
            lines.append(f"  {IRREVERSIBLE_MARK} {title} (cannot be undone)" if irreversible
                         else f"    {title}")
        return "\n".join(lines)

    def _show_steps(self) -> None:
        self.query_one("#release-steps", Static).update(self.steps_text(self.chosen_version()))

    # -- check --------------------------------------------------------------

    def _run_check(self) -> None:
        version = self.chosen_version()
        if not version:
            self.query_one("#release-check-result", Static).update("Pick a valid version first.")
            return
        self.query_one("#release-check", Button).disabled = True
        self.query_one("#release-start", Button).disabled = True
        self.query_one("#release-check-result", Static).update("Checking…")
        self.run_worker(lambda: self._check_in_thread(version), thread=True, exclusive=True,
                        name="release-check")

    def _check_in_thread(self, version: str) -> None:
        try:
            check = self._ready_check or (
                lambda v: release_ready.check(self.root, self._config(), v))
            items = check(version)
        except Exception as exc:  # noqa: BLE001
            items = [release_ready.ReadyItem("check", False, f"could not check: {exc}")]
        self.app.call_from_thread(self._show_check, version, items)

    def _show_check(self, version: str, items: list[release_ready.ReadyItem]) -> None:
        self.query_one("#release-check", Button).disabled = False
        if version != self.chosen_version():
            return  # the form moved on while the check ran
        self._items, self._checked_version = items, version
        lines = []
        for item in items:
            lines.append(f"{'✓' if item.ok else '✗'} {item.text}")
            if not item.ok and item.fix:
                lines.append(f"    {item.fix}")
        self.query_one("#release-check-result", Static).update("\n".join(lines))
        self.query_one("#release-start", Button).disabled = not (
            items and release_ready.ok(items))

    # -- start --------------------------------------------------------------

    def _start(self) -> None:
        version = self.chosen_version()
        if not (self._items and release_ready.ok(self._items)) or version != self._checked_version:
            return
        choice = ReleaseChoice(version, self.chosen_mode())
        self.dismiss(None)
        self._start_release(choice)
