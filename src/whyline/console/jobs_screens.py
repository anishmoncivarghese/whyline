"""Jobs home screen for Agents mode: personal CV and job-search preferences."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from whyline.jobs import profile
from whyline.jobs.cli import (
    format_cv_status,
    format_list_preference,
    parse_preference_value,
    tilde_path,
)

PRIVACY_SENTENCE = (
    "Your CV stays in ~/.whyline/jobs on this Mac. It is sent to the AI "
    "provider you choose each time a job-search agent runs, and never to "
    "email or Telegram."
)

_REMOTE_OPTIONS: list[tuple[str, str]] = [
    ("Any", "any"),
    ("Remote", "remote"),
    ("Hybrid", "hybrid"),
    ("Onsite", "onsite"),
]

_DEFAULT_PREFERENCES: dict[str, Any] = {
    "roles": [],
    "seniority": "",
    "locations": [],
    "remote": "any",
    "salary_min": 0,
    "currency": "",
    "languages": [],
    "deal_breakers": [],
    "notes": "",
}


class JobsHomeScreen(ModalScreen):
    """Manage the local job-search profile (~/.whyline/jobs/)."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    JobsHomeScreen { align: center middle; }
    JobsHomeScreen > Vertical {
        width: 110; max-width: 100%; height: 100%; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    JobsHomeScreen #jh-title { text-style: bold; }
    JobsHomeScreen #jh-body { height: 1fr; }
    JobsHomeScreen .jh-section { text-style: bold; }
    JobsHomeScreen #jh-privacy { width: 100%; height: auto; color: $text-muted; }
    JobsHomeScreen #jh-cv-status { width: 100%; height: auto; margin-top: 1; }
    JobsHomeScreen #jh-cv-actions { height: auto; margin-top: 1; }
    JobsHomeScreen #jh-cv-actions Button { min-width: 8; width: auto; margin-right: 1; }
    JobsHomeScreen .jh-panel { height: auto; margin-top: 1; }
    JobsHomeScreen .jh-panel.-hidden { display: none; }
    JobsHomeScreen .jh-panel-buttons { height: auto; margin-top: 1; }
    JobsHomeScreen .jh-panel-buttons Button { min-width: 8; width: auto; margin-right: 1; }
    JobsHomeScreen #jh-cv-path { width: 100%; }
    JobsHomeScreen #jh-cv-text { width: 100%; height: 6; }
    JobsHomeScreen HorizontalGroup { height: auto; }
    JobsHomeScreen .jh-field-label { width: 15; padding: 1 1 0 0; }
    JobsHomeScreen .jh-field-input { width: 1fr; }
    JobsHomeScreen #jh-remote { width: 1fr; }
    JobsHomeScreen #jh-error { height: auto; max-height: 3; color: $error; }
    JobsHomeScreen #jh-error.-empty { display: none; }
    JobsHomeScreen #jh-status { height: auto; max-height: 2; color: $success; }
    JobsHomeScreen #jh-status.-empty { display: none; }
    JobsHomeScreen #jh-buttons { height: auto; margin-top: 1; }
    JobsHomeScreen #jh-buttons Button { min-width: 8; width: auto; margin-right: 1; }
    """

    def __init__(
        self,
        *,
        status_fn: Callable[[], Mapping[str, profile.FileStatus]] | None = None,
        load_preferences_fn: Callable[[], Mapping[str, Any]] | None = None,
        save_preferences_fn: Callable[[Mapping[str, Any]], Any] | None = None,
        import_cv_fn: Callable[[str | Path], Any] | None = None,
        import_cv_text_fn: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__()
        self._status_fn = status_fn
        self._load_preferences_fn = load_preferences_fn
        self._save_preferences_fn = save_preferences_fn
        self._import_cv_fn = import_cv_fn
        self._import_cv_text_fn = import_cv_text_fn

    def _read_statuses(self) -> Mapping[str, profile.FileStatus]:
        fn = self._status_fn if self._status_fn is not None else profile.status
        return fn()

    def _read_preferences(self) -> tuple[dict[str, Any], str]:
        fn = (
            self._load_preferences_fn
            if self._load_preferences_fn is not None
            else profile.load_preferences
        )
        try:
            loaded = fn()
        except (profile.ProfileError, OSError, ValueError) as error:
            return dict(_DEFAULT_PREFERENCES), str(error)
        merged = {**_DEFAULT_PREFERENCES, **(dict(loaded) if isinstance(loaded, Mapping) else {})}
        return merged, ""

    def compose(self) -> ComposeResult:
        try:
            statuses = self._read_statuses()
            cv_status_line = format_cv_status(statuses)
            status_err = ""
        except (profile.ProfileError, OSError, ValueError) as error:
            cv_status_line = "CV: status unavailable"
            status_err = str(error)

        prefs, prefs_err = self._read_preferences()
        initial_err = prefs_err or status_err

        remote_val = str(prefs.get("remote", "any"))
        if remote_val not in profile.REMOTE_MODES:
            remote_val = "any"

        roles_val = format_list_preference(
            list(prefs["roles"]) if isinstance(prefs.get("roles"), list) else []
        )
        locations_val = format_list_preference(
            list(prefs["locations"]) if isinstance(prefs.get("locations"), list) else []
        )
        languages_val = format_list_preference(
            list(prefs["languages"]) if isinstance(prefs.get("languages"), list) else []
        )
        deal_breakers_val = format_list_preference(
            list(prefs["deal_breakers"]) if isinstance(prefs.get("deal_breakers"), list) else []
        )

        yield Vertical(
            Label("Jobs", id="jh-title"),
            VerticalScroll(
                Label("Profile", classes="jh-section", id="jh-profile-heading"),
                Static(PRIVACY_SENTENCE, id="jh-privacy", markup=False),
                Static(cv_status_line, id="jh-cv-status", markup=False),
                Horizontal(
                    Button("Import CV…", id="jh-import-cv"),
                    Button("Paste CV…", id="jh-paste-cv"),
                    id="jh-cv-actions",
                ),
                Vertical(
                    Input(
                        placeholder="~/Documents/cv.docx (.md, .txt, or .docx)",
                        id="jh-cv-path",
                    ),
                    Horizontal(
                        Button("Import", id="jh-cv-import-confirm", variant="primary"),
                        Button("Cancel", id="jh-cv-import-cancel"),
                        classes="jh-panel-buttons",
                    ),
                    id="jh-import-panel",
                    classes="jh-panel -hidden",
                ),
                Vertical(
                    TextArea("", id="jh-cv-text"),
                    Horizontal(
                        Button("Save CV", id="jh-cv-paste-confirm", variant="primary"),
                        Button("Cancel", id="jh-cv-paste-cancel"),
                        classes="jh-panel-buttons",
                    ),
                    id="jh-paste-panel",
                    classes="jh-panel -hidden",
                ),
                HorizontalGroup(
                    Label("Roles", classes="jh-field-label"),
                    Input(
                        value=roles_val,
                        placeholder="Backend Engineer, Staff Engineer",
                        id="jh-roles",
                        classes="jh-field-input",
                    ),
                ),
                HorizontalGroup(
                    Label("Seniority", classes="jh-field-label"),
                    Input(
                        value=str(prefs.get("seniority") or ""),
                        placeholder="Senior, Staff",
                        id="jh-seniority",
                        classes="jh-field-input",
                    ),
                ),
                HorizontalGroup(
                    Label("Locations", classes="jh-field-label"),
                    Input(
                        value=locations_val,
                        placeholder="London, Berlin",
                        id="jh-locations",
                        classes="jh-field-input",
                    ),
                ),
                HorizontalGroup(
                    Label("Remote", classes="jh-field-label"),
                    Select(
                        _REMOTE_OPTIONS,
                        value=remote_val,
                        allow_blank=False,
                        id="jh-remote",
                    ),
                ),
                HorizontalGroup(
                    Label("Min salary", classes="jh-field-label"),
                    Input(
                        value=str(prefs.get("salary_min", 0)),
                        placeholder="0",
                        id="jh-salary-min",
                        classes="jh-field-input",
                    ),
                ),
                HorizontalGroup(
                    Label("Currency", classes="jh-field-label"),
                    Input(
                        value=str(prefs.get("currency") or ""),
                        placeholder="GBP, USD, EUR",
                        id="jh-currency",
                        classes="jh-field-input",
                    ),
                ),
                HorizontalGroup(
                    Label("Languages", classes="jh-field-label"),
                    Input(
                        value=languages_val,
                        placeholder="English",
                        id="jh-languages",
                        classes="jh-field-input",
                    ),
                ),
                HorizontalGroup(
                    Label("Deal-breakers", classes="jh-field-label"),
                    Input(
                        value=deal_breakers_val,
                        placeholder="crypto, unpaid",
                        id="jh-deal-breakers",
                        classes="jh-field-input",
                    ),
                ),
                HorizontalGroup(
                    Label("Notes", classes="jh-field-label"),
                    Input(
                        value=str(prefs.get("notes") or ""),
                        placeholder="Optional notes",
                        id="jh-notes",
                        classes="jh-field-input",
                    ),
                ),
                id="jh-body",
            ),
            Static(
                initial_err,
                id="jh-error",
                markup=False,
                classes="" if initial_err else "-empty",
            ),
            Static("", id="jh-status", markup=False, classes="-empty"),
            Horizontal(
                Button("Save", id="jh-save", variant="success"),
                Button("Close", id="jh-close"),
                id="jh-buttons",
            ),
        )

    def action_close(self) -> None:
        self.dismiss(None)

    def _set_error(self, message: str) -> None:
        try:
            err = self.query_one("#jh-error", Static)
            ok = self.query_one("#jh-status", Static)
        except NoMatches:
            return
        err.update(message)
        err.set_class(not message, "-empty")
        if message:
            ok.update("")
            ok.set_class(True, "-empty")

    def _set_status(self, message: str) -> None:
        try:
            err = self.query_one("#jh-error", Static)
            ok = self.query_one("#jh-status", Static)
        except NoMatches:
            return
        err.update("")
        err.set_class(True, "-empty")
        ok.update(message)
        ok.set_class(not message, "-empty")

    def _refresh_cv_status(self) -> None:
        try:
            statuses = self._read_statuses()
            self.query_one("#jh-cv-status", Static).update(format_cv_status(statuses))
        except (profile.ProfileError, OSError, ValueError, NoMatches):
            pass

    def _toggle_import_panel(self, show: bool) -> None:
        imp = self.query_one("#jh-import-panel", Vertical)
        paste = self.query_one("#jh-paste-panel", Vertical)
        if show:
            paste.set_class(True, "-hidden")
            imp.set_class(False, "-hidden")
            self.query_one("#jh-cv-path", Input).focus()
        else:
            imp.set_class(True, "-hidden")

    def _toggle_paste_panel(self, show: bool) -> None:
        imp = self.query_one("#jh-import-panel", Vertical)
        paste = self.query_one("#jh-paste-panel", Vertical)
        if show:
            imp.set_class(True, "-hidden")
            paste.set_class(False, "-hidden")
            self.query_one("#jh-cv-text", TextArea).focus()
        else:
            paste.set_class(True, "-hidden")

    def _do_import_cv(self) -> None:
        path_input = self.query_one("#jh-cv-path", Input)
        raw_path = path_input.value.strip()
        if not raw_path:
            self._set_error("Enter a path to a .md, .txt, or .docx file.")
            return
        fn = self._import_cv_fn if self._import_cv_fn is not None else profile.import_cv
        try:
            written = fn(raw_path)
        except (profile.ProfileError, OSError, ValueError) as error:
            self._set_error(str(error))
            return
        path_input.value = ""
        self._toggle_import_panel(False)
        self._refresh_cv_status()
        if isinstance(written, Path):
            self._set_status(f"Imported CV to {tilde_path(written)}.")
        else:
            self._set_status("Imported CV.")

    def _do_paste_cv(self) -> None:
        area = self.query_one("#jh-cv-text", TextArea)
        raw_text = area.text
        if not raw_text.strip():
            self._set_error("Paste your CV text before saving.")
            return
        fn = (
            self._import_cv_text_fn
            if self._import_cv_text_fn is not None
            else profile.import_cv_text
        )
        try:
            written = fn(raw_text)
        except (profile.ProfileError, OSError, ValueError) as error:
            self._set_error(str(error))
            return
        area.load_text("")
        self._toggle_paste_panel(False)
        self._refresh_cv_status()
        if isinstance(written, Path):
            self._set_status(f"Saved pasted CV to {tilde_path(written)}.")
        else:
            self._set_status("Saved pasted CV.")

    def _collect_preferences(self) -> dict[str, Any]:
        raw_salary = self.query_one("#jh-salary-min", Input).value.strip() or "0"
        remote_val = self.query_one("#jh-remote", Select).value
        remote_str = str(remote_val) if remote_val is not Select.BLANK else "any"
        return {
            "roles": parse_preference_value(
                "roles", self.query_one("#jh-roles", Input).value
            ),
            "seniority": parse_preference_value(
                "seniority", self.query_one("#jh-seniority", Input).value
            ),
            "locations": parse_preference_value(
                "locations", self.query_one("#jh-locations", Input).value
            ),
            "remote": parse_preference_value("remote", remote_str),
            "salary_min": parse_preference_value("salary_min", raw_salary),
            "currency": parse_preference_value(
                "currency", self.query_one("#jh-currency", Input).value
            ),
            "languages": parse_preference_value(
                "languages", self.query_one("#jh-languages", Input).value
            ),
            "deal_breakers": parse_preference_value(
                "deal_breakers", self.query_one("#jh-deal-breakers", Input).value
            ),
            "notes": parse_preference_value(
                "notes", self.query_one("#jh-notes", Input).value
            ),
        }

    def _save_preferences(self) -> None:
        try:
            prefs = self._collect_preferences()
            fn = (
                self._save_preferences_fn
                if self._save_preferences_fn is not None
                else profile.save_preferences
            )
            fn(prefs)
        except (profile.ProfileError, OSError, ValueError) as error:
            self._set_error(str(error))
            return
        self._refresh_cv_status()
        self._set_status("Preferences saved.")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "jh-cv-path":
            event.stop()
            self._do_import_cv()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        event.stop()
        if button_id == "jh-close":
            self.action_close()
        elif button_id == "jh-save":
            self._save_preferences()
        elif button_id == "jh-import-cv":
            if self.query_one("#jh-cv-path", Input).value.strip():
                self._do_import_cv()
            else:
                hidden = self.query_one("#jh-import-panel", Vertical).has_class("-hidden")
                self._toggle_import_panel(hidden)
        elif button_id == "jh-cv-import-confirm":
            self._do_import_cv()
        elif button_id == "jh-cv-import-cancel":
            self.query_one("#jh-cv-path", Input).value = ""
            self._toggle_import_panel(False)
            self._set_error("")
        elif button_id == "jh-paste-cv":
            if self.query_one("#jh-cv-text", TextArea).text.strip():
                self._do_paste_cv()
            else:
                hidden = self.query_one("#jh-paste-panel", Vertical).has_class("-hidden")
                self._toggle_paste_panel(hidden)
        elif button_id == "jh-cv-paste-confirm":
            self._do_paste_cv()
        elif button_id == "jh-cv-paste-cancel":
            self.query_one("#jh-cv-text", TextArea).load_text("")
            self._toggle_paste_panel(False)
            self._set_error("")
