"""The Release popup: pick a version and mode, run the Ready check, see the
planned steps, and Start. Starting is handed to an injected `start_release`
(the console wires it to the real run); nothing here publishes anything."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Checkbox, Input, Label, Select, Static, TabbedContent, TabPane, TextArea,
)

from whyline.console import security_screens
from whyline.release import config as release_config
from whyline.release import plan as release_plan
from whyline.release import ready as release_ready
from whyline.release import setup_github
from whyline.release import version as release_version
from whyline.release.targets import pypi as pypi_target
from whyline.security import hook

CUSTOM = "custom"
CURRENT = "current"
VERSION_KINDS = (*release_version.BUMPS, CURRENT, CUSTOM)
IRREVERSIBLE_MARK = "⚠"
SUGGESTED = "Suggested; press Save to keep."
UNSAVED_PROMPT = "You have unsaved changes."
PART_2 = "Comes with release part 2"
GITHUB_WHY = "GitHub is ticked because every release target publishes through it."
PROTECTION_NOTE = ("GitHub's push protection is a second net, not a replacement for the "
                   "local secret scan.")
PROTECTION_LABELS = (
    ("secret_scanning", "Secret scanning"),
    ("secret_scanning_push_protection", "Push protection"),
    ("dependabot_alerts", "Dependabot alerts"),
)
BREW_HINT ="GitHub's gh tool is missing. Install it with: brew install gh"
BREW_COMMAND = "brew install gh"
TARGETS = (
    ("github", "GitHub"), ("pypi", "PyPI"), ("npm", "npm"), ("docker", "Docker"),
    ("homebrew", "Homebrew"), (CUSTOM, "Custom"),
)
PRIVATE, PUBLIC = "private", "public"


def _lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip())


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
    .-hidden { display: none; }
    .rs-row { height: auto; }
    .rs-row Static { width: 1fr; padding: 1 1; }
    #rs-checks, #rs-ci-ignore, #rs-after { height: 5; }
    #rs-gh { height: auto; border: round $primary; padding: 0 1; margin-top: 1; }
    #rs-pypi { height: auto; border: round $primary; padding: 0 1; margin-top: 1; }
    #rs-gh-code { text-style: bold; text-align: center; border: heavy $accent; padding: 1 2; }
    #rs-confirm { height: auto; }
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
        gh_run: setup_github.Run | None = None,
        gh_run_streaming: setup_github.RunStreaming | None = None,
        chat_turn: Callable[..., object] | None = None,
        agent: str | None = None,
        security_screen: Callable[[], ModalScreen] | None = None,
        pypi_get: Callable[[str], int] | None = None,
        open_url: Callable[[str], object] | None = None,
    ) -> None:
        super().__init__()
        self.root = Path(root)
        self._security_screen = security_screen
        self._gh_run = gh_run
        self._pypi = pypi_target.PyPITarget(get=pypi_get)
        self._open_url = open_url
        self._gh_run_streaming = gh_run_streaming
        self._chat_turn = chat_turn
        self._agent = agent
        self._gh_status: setup_github.GitHubStatus | None = None
        self._gh_error = ""
        self._gh_repo = ""
        self._pypi_lines: list[str] = []
        self._suggested = False
        self._saved_form: release_config.ReleaseConfig | None = None
        self._setup_base = release_config.ReleaseConfig()
        self._setup_error = ""
        self._given_config = config is not None
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
                        yield Button("Open Security…", id="release-fix-security", classes="-hidden")
                        yield Static("", id="release-steps")
                with TabPane("Set up", id="setup-tab"):
                    yield from self._compose_setup()
            with Horizontal(id="rs-confirm", classes="-hidden"):
                yield Static(UNSAVED_PROMPT)
                yield Button("Save", id="rs-confirm-save", variant="success")
                yield Button("Discard", id="rs-confirm-discard")
                yield Button("Keep editing", id="rs-confirm-keep")
            with Horizontal(id="release-actions"):
                yield Button("Check", id="release-check")
                yield Button("Security…", id="release-security")
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
        self._saved_form = self._collect()

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
            self.action_close()
        elif button_id == "release-check":
            self._run_check()
        elif button_id in ("release-security", "release-fix-security", "rs-sec-open"):
            self._open_security()
        elif button_id == "rs-sec-copy":
            self.app.copy_to_clipboard(security_screens.BREW_COMMAND)
            self._set_status("Copied.")
        elif button_id == "rs-sec-hook-copy":
            self.app.copy_to_clipboard(hook.COMMAND)
            self._set_status("Copied.")
        elif button_id == "release-start":
            self._start()
        elif button_id is None:
            return
        elif button_id.startswith("rs-setup-"):
            self._setup_target(button_id[len("rs-setup-"):])
        elif button_id == "rs-save":
            self._save_setup()
        elif button_id == "rs-confirm-save":
            if self._save_setup():
                self.dismiss(None)
        elif button_id == "rs-confirm-discard":
            self.dismiss(None)
        elif button_id == "rs-confirm-keep":
            self._show_confirm(False)
        elif button_id == "rs-gh-signin":
            self._start_sign_in()
        elif button_id == "rs-gh-create":
            self._start_create()
        elif button_id == "rs-gh-copy":
            self.app.copy_to_clipboard(BREW_COMMAND)
            self._set_status("Copied.")
        elif button_id == "rs-gh-ask":
            self._start_ask()
        elif button_id == "rs-pypi-add":
            self._add_pypi_workflow()
        elif button_id == "rs-pypi-open":
            self._open_pypi()
        elif button_id == "rs-pypi-ask":
            self._start_ask("rs-pypi", self._pypi_ask_prompt())
        elif button_id.startswith("rs-gh-prot-on-"):
            self._start_protection(button_id[len("rs-gh-prot-on-"):])

    def action_close(self) -> None:
        if self._has_unsaved():
            self._show_confirm(True)
            return
        self.dismiss(None)

    # -- set up: the form ---------------------------------------------------

    def _load_setup(self) -> release_config.ReleaseConfig:
        """The saved file, or what detection suggests when there is none."""
        if self._given_config and self._cfg is not None:
            return self._cfg
        if (self.root / release_config.CONFIG_PATH).exists():
            try:
                return release_config.load(self.root)
            except release_config.ConfigError as exc:
                self._setup_error = str(exc)
        self._suggested = True
        return release_config.detect(self.root)

    def _compose_setup(self) -> ComposeResult:
        cfg = self._load_setup()
        self._setup_base = cfg
        t = cfg.targets
        ticked = {"github": t.github, "pypi": t.pypi, "npm": t.npm, "docker": t.docker,
                  "homebrew": t.homebrew, CUSTOM: bool(t.custom)}
        note = self._setup_error or (SUGGESTED if self._suggested else "")
        with VerticalScroll(id="rs-body"):
            yield Static(note, id="rs-source", markup=False)
            for key, label in TARGETS:
                with Horizontal(classes="rs-row"):
                    yield Checkbox(label, ticked[key], id=f"rs-t-{key}")
                    yield Static("Not checked" if key == "github" else "", id=f"rs-s-{key}",
                                 markup=False)
                    yield Button("Set up…", id=f"rs-setup-{key}")
            yield Static("", id="rs-why", markup=False)
            yield Label("Mode")
            yield Select([(m, m) for m in release_config.MODES], value=cfg.mode,
                         allow_blank=False, id="rs-mode")
            yield Label("Branch")
            yield Input(cfg.branch, id="rs-branch")
            yield Checkbox("Release when a plan completes", cfg.start_after_plan,
                           id="rs-after-plan")
            yield Label("Checks (one per line)")
            yield TextArea("\n".join(cfg.checks), id="rs-checks")
            yield Label("CI jobs to ignore (one per line)")
            yield TextArea("\n".join(cfg.ci_ignore), id="rs-ci-ignore")
            yield Label("Notes path")
            yield Input(cfg.notes, id="rs-notes")
            yield Label("After-commands (one per line)")
            yield TextArea("\n".join(cfg.after), id="rs-after")
            with Vertical(id="rs-gh", classes="-hidden"):
                yield Label("GitHub")
                yield Static("", id="rs-gh-status", markup=False)
                yield Static("", id="rs-gh-code", markup=False, classes="-hidden")
                yield Static(BREW_HINT, id="rs-gh-install", markup=False, classes="-hidden")
                yield Button("Copy", id="rs-gh-copy", classes="-hidden")
                yield Button("Sign in", id="rs-gh-signin", classes="-hidden")
                with Vertical(id="rs-gh-create-box", classes="-hidden"):
                    yield Label("Repository name")
                    yield Input(self.root.name, id="rs-gh-name")
                    yield Select([("Private", PRIVATE), ("Public", PUBLIC)], value=PRIVATE,
                                 allow_blank=False, id="rs-gh-visibility")
                    yield Label("Description")
                    yield Input("", id="rs-gh-description")
                    yield Button("Create repository", id="rs-gh-create")
                with Vertical(id="rs-gh-prot-box", classes="-hidden"):
                    yield Label("GitHub's own protection")
                    yield Static(PROTECTION_NOTE, id="rs-gh-prot-note", markup=False)
                    for key, label in PROTECTION_LABELS:
                        yield Static(label, id=f"rs-gh-prot-{key}", markup=False)
                        yield Button("Turn on", id=f"rs-gh-prot-on-{key}",
                                     classes="-hidden")
                    yield Static("", id="rs-gh-prot-msg", markup=False)
                yield Button("Ask agent", id="rs-gh-ask")
                yield Static("", id="rs-gh-reply", markup=False)
            with Vertical(id="rs-pypi", classes="-hidden"):
                yield Label("PyPI")
                yield Static("", id="rs-pypi-status", markup=False)
                yield Button("Add workflow", id="rs-pypi-add", classes="-hidden")
                yield Button("Open pypi.org", id="rs-pypi-open")
                yield Button("Ask agent", id="rs-pypi-ask")
                yield Static("", id="rs-pypi-reply", markup=False)
            yield from security_screens.compose_security_setup(cfg.security)
            yield Static("", id="rs-status", markup=False)
            yield Button("Save", id="rs-save", variant="success")

    def _collect(self) -> release_config.ReleaseConfig:
        """The form as a config; unticked Custom drops the custom targets."""
        def box(name: str) -> bool:
            return self.query_one(f"#rs-t-{name}", Checkbox).value

        base = self._setup_base
        mode = self.query_one("#rs-mode", Select).value
        targets = replace(
            base.targets,
            github=box("github"), pypi=box("pypi"), npm=box("npm"),
            docker=box("docker"), homebrew=box("homebrew"),
            custom=base.targets.custom if box(CUSTOM) else (),
        )
        return replace(
            base,
            mode=str(mode) if mode in release_config.MODES else base.mode,
            branch=self.query_one("#rs-branch", Input).value.strip() or base.branch,
            start_after_plan=self.query_one("#rs-after-plan", Checkbox).value,
            checks=_lines(self.query_one("#rs-checks", TextArea).text),
            ci_ignore=_lines(self.query_one("#rs-ci-ignore", TextArea).text),
            notes=self.query_one("#rs-notes", Input).value.strip() or base.notes,
            after=_lines(self.query_one("#rs-after", TextArea).text),
            targets=targets,
            security=security_screens.collect_security(self, base.security),
        )

    def _has_unsaved(self) -> bool:
        if self._saved_form is None:
            return False
        try:
            return self._collect() != self._saved_form
        except NoMatches:
            return False

    def _show_confirm(self, show: bool) -> None:
        self.query_one("#rs-confirm", Horizontal).set_class(not show, "-hidden")

    def _set_status(self, text: str) -> None:
        self.query_one("#rs-status", Static).update(text)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if not (event.checkbox.id or "").startswith("rs-t-"):
            return
        others = any(self.query_one(f"#rs-t-{key}", Checkbox).value
                     for key, _ in TARGETS if key != "github")
        github = self.query_one("#rs-t-github", Checkbox)
        why = self.query_one("#rs-why", Static)
        if others and not github.value:
            github.value = True
            why.update(GITHUB_WHY)
        elif not others:
            why.update("")

    def _save_setup(self) -> bool:
        cfg = release_config.normalise(self._collect())
        try:
            release_config.save(self.root, cfg)
        except (OSError, release_config.ConfigError) as exc:
            self._set_status(f"Could not save: {exc}")
            return False
        self._cfg = cfg
        self._setup_base = cfg
        hook_note = security_screens.apply_commit_hook(self.root, cfg.security)
        self._suggested = False
        self.query_one("#rs-source", Static).update("")
        github = self.query_one("#rs-t-github", Checkbox)
        if cfg.targets.github != github.value:
            github.value = cfg.targets.github
        self._saved_form = self._collect()
        self._show_confirm(False)
        refused = cfg.security.pre_commit and hook.foreign(self.root)
        self.query_one("#rs-sec-hook-line", Static).update(
            f"Add this line to your pre-commit hook: {hook.COMMAND}" if refused else "")
        self.query_one("#rs-sec-hook-line", Static).set_class(not refused, "-hidden")
        self.query_one("#rs-sec-hook-copy", Button).set_class(not refused, "-hidden")
        self._set_status(f"Saved to {release_config.CONFIG_PATH.as_posix()}."
                         + (f" {hook_note}" if hook_note else ""))
        self._invalidate()
        self._show_steps()
        return True

    def _setup_target(self, key: str) -> None:
        if key == "pypi":
            self.query_one("#rs-pypi", Vertical).remove_class("-hidden")
            self._refresh_pypi()
            return
        if key != "github":
            self.query_one(f"#rs-s-{key}", Static).update(PART_2)
            return
        self.query_one("#rs-gh", Vertical).remove_class("-hidden")
        self._refresh_github()

    # -- set up: GitHub -----------------------------------------------------

    def _run_kwargs(self) -> dict:
        return {"run": self._gh_run} if self._gh_run is not None else {}

    def _refresh_github(self) -> None:
        self.query_one("#rs-gh-status", Static).update("Checking GitHub…")
        self.run_worker(self._status_in_thread, thread=True, exclusive=True,
                        group="rs-gh-status", name="release-gh-status")

    def _status_in_thread(self) -> None:
        try:
            found = setup_github.status(self.root, **self._run_kwargs())
        except Exception as exc:  # noqa: BLE001 - shown in the panel
            self.app.call_from_thread(self._github_failed, str(exc))
            return
        self.app.call_from_thread(self._show_github, found)

    def _github_failed(self, message: str) -> None:
        self._gh_error = message
        self.query_one("#rs-gh-status", Static).update(f"Could not check GitHub: {message}")

    def _show_github(self, found: setup_github.GitHubStatus) -> None:
        self._gh_status = found
        if not found.gh_installed:
            line, short = "gh is not installed.", "gh is not installed"
        elif not found.signed_in:
            line, short = "gh is installed; not signed in.", "Not signed in"
        else:
            who = found.user or "unknown user"
            line, short = f"Signed in as {who}.", f"Signed in as {who}"
        origin = found.origin_url or "none"
        self.query_one("#rs-gh-status", Static).update(f"{line}\nOrigin: {origin}")
        self.query_one("#rs-s-github", Static).update(short)

        def show(widget_id: str, visible: bool) -> None:
            self.query_one(widget_id).set_class(not visible, "-hidden")

        show("#rs-gh-install", not found.gh_installed)
        show("#rs-gh-copy", not found.gh_installed)
        show("#rs-gh-signin", found.gh_installed and not found.signed_in)
        show("#rs-gh-create-box",
             found.gh_installed and found.signed_in and not found.origin_url)
        self._gh_repo = (setup_github.owner_repo(found.origin_url)
                         if found.signed_in else "")
        show("#rs-gh-prot-box", bool(self._gh_repo))
        if self._gh_repo:
            self._load_protection()

    def _load_protection(self) -> None:
        repo = self._gh_repo
        self.run_worker(lambda: self._protection_in_thread(repo), thread=True,
                        exclusive=True, group="rs-gh-prot", name="release-gh-protection")

    def _protection_in_thread(self, repo: str, enable: str = "") -> None:
        error = ""
        try:
            if enable:
                error = setup_github.enable_protection(repo, enable, **self._run_kwargs())
            states = setup_github.protection_status(repo, **self._run_kwargs())
        except Exception as exc:  # noqa: BLE001 - shown in the panel
            self.app.call_from_thread(self._show_protection, {}, str(exc))
            return
        self.app.call_from_thread(self._show_protection, states, error)

    def _start_protection(self, key: str) -> None:
        if not self._gh_repo or key not in setup_github.PROTECTIONS:
            return
        self.query_one(f"#rs-gh-prot-on-{key}", Button).disabled = True
        self.query_one("#rs-gh-prot-msg", Static).update("Turning on…")
        repo = self._gh_repo
        self.run_worker(lambda: self._protection_in_thread(repo, key), thread=True,
                        exclusive=True, group="rs-gh-prot", name="release-gh-protect")

    def _show_protection(self, states: dict, error: str) -> None:
        self.query_one("#rs-gh-prot-msg", Static).update(error)
        for key, label in PROTECTION_LABELS:
            state = states.get(key, setup_github.UNAVAILABLE)
            self.query_one(f"#rs-gh-prot-{key}", Static).update(f"{label}: {state}")
            button = self.query_one(f"#rs-gh-prot-on-{key}", Button)
            button.disabled = False
            button.set_class(state != setup_github.OFF, "-hidden")

    def _start_sign_in(self) -> None:
        self.query_one("#rs-gh-signin", Button).disabled = True
        self.query_one("#rs-gh-status", Static).update("Signing in; finish in your browser…")
        self.run_worker(self._sign_in_in_thread, thread=True, exclusive=True,
                        group="rs-gh-action", name="release-gh-sign-in")

    def _sign_in_in_thread(self) -> None:
        def on_line(line: str) -> None:
            self.app.call_from_thread(self._sign_in_line, line)

        kwargs = ({"run_streaming": self._gh_run_streaming}
                  if self._gh_run_streaming is not None else {})
        try:
            code = setup_github.sign_in(on_line=on_line, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._sign_in_done, 1, str(exc))
            return
        self.app.call_from_thread(self._sign_in_done, code, "")

    def _sign_in_line(self, line: str) -> None:
        if re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b", line):
            code = self.query_one("#rs-gh-code", Static)
            code.update(line.strip())
            code.remove_class("-hidden")

    def _sign_in_done(self, code: int, error: str) -> None:
        self.query_one("#rs-gh-signin", Button).disabled = False
        self.query_one("#rs-gh-code", Static).add_class("-hidden")
        if code == 0:
            self._gh_error = ""
            self._refresh_github()
            return
        self._gh_error = error or f"gh sign in ended with exit code {code}"
        self.query_one("#rs-gh-status", Static).update(f"Sign in failed: {self._gh_error}")

    def _start_create(self) -> None:
        name = self.query_one("#rs-gh-name", Input).value.strip()
        private = self.query_one("#rs-gh-visibility", Select).value != PUBLIC
        description = self.query_one("#rs-gh-description", Input).value.strip()
        self.query_one("#rs-gh-create", Button).disabled = True
        self.query_one("#rs-gh-status", Static).update("Creating the repository…")
        self.run_worker(lambda: self._create_in_thread(name, private, description),
                        thread=True, exclusive=True, group="rs-gh-action",
                        name="release-gh-create")

    def _create_in_thread(self, name: str, private: bool, description: str) -> None:
        try:
            url = setup_github.create_repo(self.root, name, private=private,
                                           description=description, **self._run_kwargs())
        except setup_github.SetupError as exc:
            self.app.call_from_thread(self._create_done, "", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._create_done, "", str(exc))
            return
        self.app.call_from_thread(self._create_done, url, "")

    def _create_done(self, url: str, error: str) -> None:
        self.query_one("#rs-gh-create", Button).disabled = False
        if error:
            self._gh_error = error
            self.query_one("#rs-gh-status", Static).update(error)
            return
        self._gh_error = ""
        self._set_status(f"Created {url}" if url else "Created the repository.")
        self._refresh_github()

    def _ask_prompt(self) -> str:
        found = self._gh_status
        if found is None:
            state = "GitHub status has not been checked yet."
        else:
            state = (f"gh installed: {found.gh_installed}; signed in: {found.signed_in}; "
                     f"user: {found.user or 'none'}; origin: {found.origin_url or 'none'}; "
                     f"origin is GitHub: {found.origin_is_github}.")
        return ("I am setting up GitHub releases for this project. "
                f"{state}\nLast error: {self._gh_error or 'none'}\n"
                "Explain what to do next in plain words. Answer in text only: do not run "
                "commands and do not change files.")

    def _start_ask(self, prefix: str = "rs-gh", prompt: str | None = None) -> None:
        self.query_one(f"#{prefix}-ask", Button).disabled = True
        self.query_one(f"#{prefix}-reply", Static).update("Asking…")
        prompt = self._ask_prompt() if prompt is None else prompt
        self.run_worker(lambda: self._ask_in_thread(prompt, prefix), thread=True,
                        exclusive=True, group=f"{prefix}-ask", name=f"release-{prefix}-ask")

    def _ask_in_thread(self, prompt: str, prefix: str = "rs-gh") -> None:
        try:
            turn = self._chat_turn
            if turn is None:
                from whyline.console import adapters
                turn = adapters.run_chat_turn
            agent = self._agent
            if agent is None:
                from whyline import model
                agent = model.resolve(self.root)[0]
            event = turn(self.root, agent=agent, prompt=prompt)
            text = str(getattr(event, "text", event))
        except Exception as exc:  # noqa: BLE001
            text = f"Could not ask the agent: {exc}"
        self.app.call_from_thread(self._show_reply, text, prefix)

    def _show_reply(self, text: str, prefix: str = "rs-gh") -> None:
        self.query_one(f"#{prefix}-ask", Button).disabled = False
        self.query_one(f"#{prefix}-reply", Static).update(text)

    # -- set up: PyPI -------------------------------------------------------

    def _pypi_ask_prompt(self) -> str:
        lines = "\n".join(self._pypi_lines) or "PyPI status has not been checked yet."
        return ("I am setting up PyPI releases with a trusted publisher for this project. "
                f"Current status:\n{lines}\nExplain what to do next on pypi.org in plain "
                "words. Answer in text only: do not run commands and do not change files.")

    def _refresh_pypi(self) -> None:
        self.query_one("#rs-pypi-status", Static).update("Checking PyPI…")
        self.run_worker(self._pypi_in_thread, thread=True, exclusive=True,
                        group="rs-pypi-status", name="release-pypi-status")

    def _pypi_in_thread(self) -> None:
        try:
            lines = self._pypi.setup_status(self.root, self._config(),
                                            **self._run_kwargs_or_default())
        except Exception as exc:  # noqa: BLE001 - shown in the panel
            self.app.call_from_thread(self._show_pypi, [f"Could not check PyPI: {exc}"], False)
            return
        has_workflow = pypi_target.workflow_path(self.root) is not None
        self.app.call_from_thread(self._show_pypi, lines, has_workflow)

    def _run_kwargs_or_default(self) -> dict:
        return {"run": self._gh_run or release_ready.default_run}

    def _show_pypi(self, lines: list[str], has_workflow: bool) -> None:
        self._pypi_lines = lines
        self.query_one("#rs-pypi-status", Static).update("\n".join(lines))
        self.query_one("#rs-pypi-add", Button).set_class(has_workflow, "-hidden")
        self.query_one("#rs-s-pypi", Static).update(
            "Workflow found" if has_workflow else "No workflow yet")

    def _add_pypi_workflow(self) -> None:
        try:
            path = pypi_target.add_workflow(self.root)
        except OSError as exc:
            self.query_one("#rs-pypi-reply", Static).update(f"Could not add the workflow: {exc}")
            return
        self.query_one("#rs-pypi-reply", Static).update(
            f"Added {path.relative_to(self.root).as_posix()}. Commit it with the release.")
        self._refresh_pypi()

    def _open_pypi(self) -> None:
        opener = self._open_url or (lambda url: subprocess.run(["open", url], check=False))
        try:
            opener(pypi_target.PUBLISHING_URL)
        except OSError as exc:
            self.query_one("#rs-pypi-reply", Static).update(f"Could not open the page: {exc}")

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
        self.query_one("#release-fix-security", Button).set_class(
            not any(item.key == "security" and not item.ok for item in items), "-hidden")
        self.query_one("#release-start", Button).disabled = not (
            items and release_ready.ok(items))

    # -- security -----------------------------------------------------------

    def _open_security(self) -> None:
        screen = (self._security_screen() if self._security_screen is not None
                  else security_screens.SecurityScreen(self.root, config=self._cfg))
        self.app.push_screen(screen)

    # -- start --------------------------------------------------------------

    def _start(self) -> None:
        version = self.chosen_version()
        if not (self._items and release_ready.ok(self._items)) or version != self._checked_version:
            return
        choice = ReleaseChoice(version, self.chosen_mode())
        self.dismiss(None)
        self._start_release(choice)


# -- the run's popups ---------------------------------------------------------

GO = "Go"
STOP_HERE = "Stop here"
EDIT = "edit"
USE = "use"
STOP = "stop"
RESUME = "resume"
OPEN_PR = "open-pr"


class ConfirmStepScreen(ModalScreen):
    """Names the step about to run and what it will do. True on Go, False on Stop here."""

    BINDINGS = [("escape", "stop_here", STOP_HERE)]
    DEFAULT_CSS = """
    ConfirmStepScreen { align: center middle; }
    ConfirmStepScreen > Vertical { width: 70; height: auto; padding: 1 2;
        border: thick $warning; background: $surface; }
    ConfirmStepScreen Horizontal { height: auto; margin-top: 1; }
    ConfirmStepScreen Button { margin-right: 2; }
    """

    def __init__(self, title: str, irreversible: bool) -> None:
        super().__init__()
        self._title = title
        self._irreversible = irreversible

    def compose(self) -> ComposeResult:
        what = ("This cannot be undone once it runs." if self._irreversible
                else "This changes your project.")
        with Vertical():
            yield Label(f"Next step: {self._title}", id="release-confirm-title")
            yield Label(what, id="release-confirm-what")
            with Horizontal():
                yield Button(GO, id="release-go", variant="warning")
                yield Button(STOP_HERE, id="release-stop-here")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "release-go")

    def action_stop_here(self) -> None:
        self.dismiss(False)


class NotesReviewScreen(ModalScreen):
    """Shows the drafted notes read-only. Closes with EDIT, USE or STOP."""

    BINDINGS = [("escape", "stop", "Stop")]
    DEFAULT_CSS = """
    NotesReviewScreen { align: center middle; }
    NotesReviewScreen > Vertical { width: 90%; max-width: 100; height: 90%; padding: 1 2;
        border: round $accent; background: $surface; }
    NotesReviewScreen TextArea { height: 1fr; }
    NotesReviewScreen Horizontal { height: auto; margin-top: 1; }
    NotesReviewScreen Button { margin-right: 2; }
    """

    def __init__(self, path: Path | str, text: str) -> None:
        super().__init__()
        self._path = Path(path)
        self._text = text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Release notes drafted in {self._path}", id="release-notes-title")
            yield TextArea(self._text, read_only=True, id="release-notes-text")
            with Horizontal():
                yield Button("Edit", id="release-notes-edit")
                yield Button("Use these", id="release-notes-use", variant="primary")
                yield Button("Stop", id="release-notes-stop")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        choices = {"release-notes-edit": EDIT, "release-notes-use": USE}
        self.dismiss(choices.get(event.button.id or "", STOP))

    def action_stop(self) -> None:
        self.dismiss(STOP)


class ReleaseFailedScreen(ModalScreen):
    """Shows why the release stopped. Closes with RESUME, OPEN_PR or None."""

    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    ReleaseFailedScreen { align: center middle; }
    ReleaseFailedScreen > Vertical { width: 80; height: auto; max-height: 90%; padding: 1 2;
        border: thick $error; background: $surface; }
    ReleaseFailedScreen Horizontal { height: auto; margin-top: 1; }
    ReleaseFailedScreen Button { margin-right: 2; }
    """

    def __init__(self, reason: str, open_pr: bool = False) -> None:
        super().__init__()
        self._reason = reason
        self._open_pr = open_pr

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("The release stopped", id="release-failed-title")
            yield Static(self._reason, id="release-failed-reason")
            with Horizontal():
                yield Button("Resume release", id="release-resume", variant="primary")
                if self._open_pr:
                    yield Button("Open PR", id="release-open-pr")
                yield Button("Close", id="release-failed-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        choices = {"release-resume": RESUME, "release-open-pr": OPEN_PR}
        self.dismiss(choices.get(event.button.id or ""))

    def action_close(self) -> None:
        self.dismiss(None)
