"""Jobs home screen for Agents mode: personal CV, review drafts, preferences, and companies."""

from __future__ import annotations

import inspect
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static, TextArea

from whyline.jobs import alerts, apply, companies, doctor, profile, review, tracker
from whyline.jobs.cli import (
    ALERTS_MAIL_SCRIPT,
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

UNKNOWN_BOARD_HINT = "No public job board found: add its careers page URL"
COMPANIES_FETCH_NOTE = "Suggested companies stay out of the fetch list until accepted."

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


def _call_review_run(
    fn: Callable[..., Any],
    cli: str | None,
    progress: Callable[[str], None],
) -> Any:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(cli=cli, progress=progress)

    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if has_var_kw or "progress" in params:
        if has_var_kw or "cli" in params:
            return fn(cli=cli, progress=progress)
        return fn(progress=progress)
    if "cli" in params or any(
        p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        )
        for p in params.values()
    ):
        return fn(cli)
    return fn()


def _call_review_accept(
    fn: Callable[..., Any],
    profile_text: str,
    rubric_text: str,
) -> Any:
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return fn(profile_text, rubric_text)

    positional = [
        p
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    if has_var_pos or len(positional) >= 2:
        return fn(profile_text, rubric_text)
    if has_var_kw:
        return fn(profile_text=profile_text, rubric_text=rubric_text)
    review.save_drafts(profile_text, rubric_text)
    return fn()


def _cell(value: object) -> Text:
    """Render untrusted company values literally rather than as Rich markup."""
    return Text("" if value is None else str(value), no_wrap=True, end="")


def _company_field(item: companies.Company | Mapping[str, Any], key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, "")
    return getattr(item, key, "")


def _coerce_company(item: companies.Company | Mapping[str, Any]) -> companies.Company:
    if isinstance(item, companies.Company):
        return item
    return companies.Company(
        name=str(_company_field(item, "name") or ""),
        status=str(_company_field(item, "status") or "suggested"),
        reason=str(_company_field(item, "reason") or ""),
        ats=str(_company_field(item, "ats") or "unknown"),
        slug=str(_company_field(item, "slug") or ""),
        careers_url=str(_company_field(item, "careers_url") or ""),
        added_by=str(_company_field(item, "added_by") or "user"),
        checked_at=str(_company_field(item, "checked_at") or ""),
    )


def format_company_board(item: companies.Company | Mapping[str, Any]) -> str:
    """Format the Board column cell for a company row."""
    ats_val = str(_company_field(item, "ats") or "unknown")
    if ats_val == "unknown":
        return UNKNOWN_BOARD_HINT
    slug_val = str(_company_field(item, "slug") or "")
    return f"{ats_val} ({slug_val})" if slug_val else ats_val


def _call_companies_check(
    fn: Callable[..., Any],
    progress: Callable[[str], None],
) -> Any:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn("all", progress=progress)

    has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params.values())
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    positional = [
        p
        for p in params.values()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    accepts_progress = has_var_kw or "progress" in params
    if positional or has_var_pos:
        if accepts_progress:
            return fn("all", progress=progress)
        return fn("all")
    if "name" in params:
        if accepts_progress:
            return fn(name="all", progress=progress)
        return fn(name="all")
    if accepts_progress:
        return fn(progress=progress)
    return fn()


def _call_companies_add(
    fn: Callable[..., Any],
    name: str,
    careers_url: str | None,
) -> Any:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(name, careers_url=careers_url)

    has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params.values())
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    positional = [
        p
        for p in params.values()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if "careers_url" in params or has_var_kw:
        return fn(name, careers_url=careers_url)
    if has_var_pos or len(positional) >= 2:
        return fn(name, careers_url)
    return fn(name)


class JobsHomeScreen(ModalScreen):
    """Manage the local job-search profile and companies (~/.whyline/jobs/)."""

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
    JobsHomeScreen .jh-draft-heading { text-style: bold; margin-top: 1; }
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
    JobsHomeScreen #jh-review-cli { width: 1fr; }
    JobsHomeScreen #jh-review-progress { width: 100%; height: auto; margin-top: 1; color: $accent; }
    JobsHomeScreen #jh-review-progress.-empty { display: none; }
    JobsHomeScreen #jh-profile-draft { width: 100%; height: 6; }
    JobsHomeScreen #jh-rubric-draft { width: 100%; height: 6; }
    JobsHomeScreen HorizontalGroup { height: auto; }
    JobsHomeScreen .jh-field-label { width: 15; padding: 1 1 0 0; }
    JobsHomeScreen .jh-field-input { width: 1fr; }
    JobsHomeScreen #jh-remote { width: 1fr; }
    JobsHomeScreen #jh-companies-heading { margin-top: 1; }
    JobsHomeScreen #jh-companies-note { width: 100%; height: auto; color: $text-muted; }
    JobsHomeScreen #jh-jobs-draft-progress { width: 100%; height: auto; color: $accent; }
    JobsHomeScreen #jh-jobs-draft-progress.-empty { display: none; }
    JobsHomeScreen #jh-companies-progress { width: 100%; height: auto; margin-top: 1; color: $accent; }
    JobsHomeScreen #jh-companies-progress.-empty { display: none; }
    JobsHomeScreen #jh-companies-empty { width: 100%; height: auto; color: $text-muted; }
    JobsHomeScreen #jh-companies-empty.-empty { display: none; }
    JobsHomeScreen #jh-companies-table { width: 100%; height: auto; min-height: 3; max-height: 7; margin-top: 1; }
    JobsHomeScreen .jh-companies-actions { height: auto; margin-top: 1; }
    JobsHomeScreen .jh-companies-actions Button { min-width: 8; width: auto; margin-right: 1; }
    JobsHomeScreen #jh-company-name { width: 100%; }
    JobsHomeScreen #jh-company-url { width: 100%; }
    JobsHomeScreen #jh-alerts-heading { margin-top: 1; }
    JobsHomeScreen #jh-alerts-last { width: 100%; height: auto; color: $text-muted; }
    JobsHomeScreen #jh-alerts-mail-result { width: 100%; height: auto; color: $accent; }
    JobsHomeScreen #jh-alerts-mail-result.-empty { display: none; }
    JobsHomeScreen .jh-alert-switch { border: none; height: 1; padding: 0 1; margin: 0; width: auto; }
    JobsHomeScreen .jh-alert-switch:focus { border: none; }
    JobsHomeScreen #jh-jobs-heading { margin-top: 1; }
    JobsHomeScreen #jh-jobs-filter { width: 24; }
    JobsHomeScreen #jh-jobs-empty { width: 100%; height: auto; color: $text-muted; }
    JobsHomeScreen #jh-jobs-empty.-empty { display: none; }
    JobsHomeScreen #jh-jobs-table { width: 100%; height: auto; min-height: 3; max-height: 7; margin-top: 1; }
    JobsHomeScreen .jh-jobs-actions { height: auto; margin-top: 1; }
    JobsHomeScreen .jh-jobs-actions Button { min-width: 8; width: auto; margin-right: 1; }
    JobsHomeScreen #jh-jobs-status-select { width: 24; }
    JobsHomeScreen #jh-jobs-note { width: 100%; }
    JobsHomeScreen #jh-jobs-check { width: 100%; height: auto; margin-top: 1; }
    JobsHomeScreen #jh-jobs-check.-empty { display: none; }
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
        review_run_fn: Callable[..., review.ReviewResult] | None = None,
        review_accept_fn: Callable[..., Any] | None = None,
        review_discard_fn: Callable[[], Any] | None = None,
        enabled_providers_fn: Callable[[], Sequence[str]] | None = None,
        read_drafts_fn: Callable[[], review.DraftBlocks | None] | None = None,
        companies_list_fn: Callable[[], Sequence[companies.Company]] | None = None,
        companies_suggest_fn: Callable[..., Any] | None = None,
        companies_check_fn: Callable[..., Any] | None = None,
        companies_add_fn: Callable[..., Any] | None = None,
        companies_accept_fn: Callable[[str], Any] | None = None,
        companies_remove_fn: Callable[[str], Any] | None = None,
        fetch_fn: Callable[..., Any] | None = None,
        jobs_list_fn: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        jobs_set_fn: Callable[..., Any] | None = None,
        jobs_export_fn: Callable[[], Path] | None = None,
        open_link_fn: Callable[[str], Any] | None = None,
        open_file_fn: Callable[[Path], str] | None = None,
        doctor_fn: Callable[[], Sequence[doctor.Row]] | None = None,
        alert_senders_fn: Callable[[], Mapping[str, bool]] | None = None,
        alert_set_fn: Callable[[str, bool], Any] | None = None,
        alert_last_fn: Callable[[], str] | None = None,
        alert_mail_fn: Callable[[], Path] | None = None,
        draft_fn: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__()
        self._status_fn = status_fn
        self._load_preferences_fn = load_preferences_fn
        self._save_preferences_fn = save_preferences_fn
        self._import_cv_fn = import_cv_fn
        self._import_cv_text_fn = import_cv_text_fn
        self._review_run_fn = review_run_fn
        self._review_accept_fn = review_accept_fn
        self._review_discard_fn = review_discard_fn
        self._enabled_providers_fn = enabled_providers_fn
        self._read_drafts_fn = read_drafts_fn
        self._companies_list_fn = companies_list_fn
        self._companies_suggest_fn = companies_suggest_fn
        self._companies_check_fn = companies_check_fn
        self._companies_add_fn = companies_add_fn
        self._companies_accept_fn = companies_accept_fn
        self._companies_remove_fn = companies_remove_fn
        self._fetch_fn = fetch_fn
        self._jobs_list_fn = jobs_list_fn
        self._jobs_set_fn = jobs_set_fn
        self._jobs_export_fn = jobs_export_fn
        self._open_link_fn = open_link_fn
        self._open_file_fn = open_file_fn
        self._doctor_fn = doctor_fn
        self._alert_senders_fn = alert_senders_fn
        self._alert_set_fn = alert_set_fn
        self._alert_last_fn = alert_last_fn
        self._alert_mail_fn = alert_mail_fn
        self._draft_fn = draft_fn
        self._draft_folder: Path | None = None
        self._drafting = False
        self._draft_token: object | None = None
        self._alert_addresses: list[str] = []
        self._job_rows: list[Mapping[str, Any]] = []
        self._job_edit_mode = ""
        self._reviewing = False
        self._review_token: object | None = None
        self._companies_busy = False
        self._companies_token: object | None = None
        self._company_rows: list[companies.Company] = []

    def _read_alert_senders(self) -> dict[str, bool]:
        fn = self._alert_senders_fn if self._alert_senders_fn is not None else alerts.senders
        try:
            return dict(fn())
        except (OSError, alerts.AlertError):
            return {}

    def _read_alert_last(self) -> str:
        fn = self._alert_last_fn if self._alert_last_fn is not None else alerts.format_last_read
        try:
            return fn()
        except (OSError, alerts.AlertError):
            return "Last alert: unavailable."

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

    def _read_enabled_providers(self) -> list[str]:
        fn = (
            self._enabled_providers_fn
            if self._enabled_providers_fn is not None
            else review.enabled_providers
        )
        try:
            return list(fn())
        except Exception:
            return []

    def _read_drafts(self) -> review.DraftBlocks | None:
        fn = (
            self._read_drafts_fn
            if self._read_drafts_fn is not None
            else review.read_drafts
        )
        try:
            return fn()
        except Exception:
            return None

    def _alert_switches(self) -> list[Checkbox]:
        senders = self._read_alert_senders()
        self._alert_addresses = list(senders)
        return [
            Checkbox(addr, value=on, id=f"jh-alert-{i}", classes="jh-alert-switch")
            for i, (addr, on) in enumerate(senders.items())
        ]

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        box_id = event.checkbox.id or ""
        if not box_id.startswith("jh-alert-"):
            return
        event.stop()
        index = int(box_id[len("jh-alert-"):])
        if index >= len(self._alert_addresses):
            return
        fn = self._alert_set_fn if self._alert_set_fn is not None else alerts.set_sender
        try:
            fn(self._alert_addresses[index], bool(event.value))
        except (OSError, alerts.AlertError) as error:
            self._set_error(str(error))
            return
        self._set_error("")

    def _mail_rule(self) -> None:
        from whyline.agents import mail

        out = self.query_one("#jh-alerts-mail-result", Static)
        if self._alert_mail_fn is None and not mail.supported():
            text = mail.NEEDS_MACOS
        else:
            fn = self._alert_mail_fn or (lambda: mail.install(*ALERTS_MAIL_SCRIPT))
            try:
                path = fn()
                text = (
                    f"Wrote {Path(path).as_posix()}\n"
                    "In Mail → Settings → Rules → Add Rule, set From to an alert sender, "
                    "then Run AppleScript → choose whyline-job-alerts.applescript."
                )
            except (RuntimeError, OSError, ValueError) as error:
                text = str(error)
        out.update(text)
        out.remove_class("-empty")

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

        providers = self._read_enabled_providers()
        provider_options: list[tuple[str, str]] = [(p, p) for p in providers]
        default_provider = providers[0] if providers else Select.BLANK

        pending_drafts = self._read_drafts()
        has_drafts = pending_drafts is not None
        initial_profile_draft = pending_drafts.profile if pending_drafts is not None else ""
        initial_rubric_draft = pending_drafts.rubric if pending_drafts is not None else ""

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
                    Button("Review my CV", id="jh-review-cv", variant="primary"),
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
                    Label("Provider", classes="jh-field-label"),
                    Select(
                        provider_options,
                        value=default_provider,
                        allow_blank=not provider_options,
                        prompt="No enabled AI provider",
                        id="jh-review-cli",
                    ),
                    id="jh-review-provider-row",
                ),
                Static("", id="jh-review-progress", markup=False, classes="-empty"),
                Vertical(
                    Label("Profile draft", classes="jh-draft-heading", id="jh-profile-draft-label"),
                    TextArea(initial_profile_draft, id="jh-profile-draft"),
                    Label("Rubric draft", classes="jh-draft-heading", id="jh-rubric-draft-label"),
                    TextArea(initial_rubric_draft, id="jh-rubric-draft"),
                    Horizontal(
                        Button("Accept", id="jh-review-accept", variant="success"),
                        Button("Discard", id="jh-review-discard"),
                        classes="jh-panel-buttons",
                        id="jh-review-actions",
                    ),
                    id="jh-review-panel",
                    classes="jh-panel" if has_drafts else "jh-panel -hidden",
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
                Label("Companies", classes="jh-section", id="jh-companies-heading"),
                Static(COMPANIES_FETCH_NOTE, id="jh-companies-note", markup=False),
                Static("", id="jh-companies-progress", markup=False, classes="-empty"),
                DataTable(id="jh-companies-table", cursor_type="row", zebra_stripes=True),
                Static(
                    "No companies yet. Suggest some or add one.",
                    id="jh-companies-empty",
                    markup=False,
                ),
                Horizontal(
                    Button("Suggest companies", id="jh-co-suggest", variant="primary"),
                    Button("Check boards", id="jh-co-check"),
                    Button("Fetch now", id="jh-co-fetch"),
                    classes="jh-companies-actions",
                ),
                Horizontal(
                    Button("Accept", id="jh-co-accept", variant="success"),
                    Button("Remove", id="jh-co-remove"),
                    Button("Add company…", id="jh-co-add"),
                    classes="jh-companies-actions",
                ),
                Vertical(
                    Input(placeholder="Company name", id="jh-company-name"),
                    Input(placeholder="Careers page URL (optional)", id="jh-company-url"),
                    Horizontal(
                        Button("Add", id="jh-co-add-confirm", variant="primary"),
                        Button("Cancel", id="jh-co-add-cancel"),
                        classes="jh-panel-buttons",
                    ),
                    id="jh-company-panel",
                    classes="jh-panel -hidden",
                ),
                Label("Alerts", classes="jh-section", id="jh-alerts-heading"),
                Static(
                    "Read job-alert emails from the senders you switch on. "
                    "Each message must pass email authentication.",
                    id="jh-alerts-note",
                    markup=False,
                ),
                *self._alert_switches(),
                Static(self._read_alert_last(), id="jh-alerts-last", markup=False),
                Horizontal(
                    Button("Mail rule…", id="jh-alerts-mail"),
                    classes="jh-companies-actions",
                ),
                Static("", id="jh-alerts-mail-result", markup=False, classes="-empty"),
                Label("Jobs", classes="jh-section", id="jh-jobs-heading"),
                HorizontalGroup(
                    Label("Status", classes="jh-field-label"),
                    Select(
                        [("All", "all"), *[(name, name) for name in tracker.STATUSES]],
                        value="all",
                        allow_blank=False,
                        id="jh-jobs-filter",
                    ),
                ),
                DataTable(id="jh-jobs-table", cursor_type="row", zebra_stripes=True),
                Static("No tracked jobs yet.", id="jh-jobs-empty", markup=False),
                Horizontal(
                    Button("Set status…", id="jh-jobs-set"),
                    Button("Note…", id="jh-jobs-note-open"),
                    Button("Open link", id="jh-jobs-link"),
                    Button("Open Excel", id="jh-jobs-excel"),
                    Button("Check", id="jh-jobs-check-run"),
                    classes="jh-jobs-actions",
                ),
                Horizontal(
                    Button("Draft application", id="jh-jobs-draft", variant="primary"),
                    Button("Open folder", id="jh-jobs-open-folder", disabled=True),
                    classes="jh-jobs-actions",
                ),
                Static("", id="jh-jobs-draft-progress", markup=False, classes="-empty"),
                Vertical(
                    Select(
                        [(name, name) for name in tracker.STATUSES],
                        value=tracker.STATUSES[0],
                        allow_blank=False,
                        id="jh-jobs-status-select",
                    ),
                    Input(placeholder="Note", id="jh-jobs-note"),
                    Horizontal(
                        Button("Save", id="jh-jobs-edit-confirm", variant="primary"),
                        Button("Cancel", id="jh-jobs-edit-cancel"),
                        classes="jh-panel-buttons",
                    ),
                    id="jh-jobs-edit-panel",
                    classes="jh-panel -hidden",
                ),
                Static("", id="jh-jobs-check", markup=False, classes="-empty"),
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
                Button("Tracked jobs", id="jh-tracked"),
                Button("Close", id="jh-close"),
                id="jh-buttons",
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#jh-companies-table", DataTable).add_columns(
            "Name", "Status", "Board", "Reason"
        )
        self._refresh_companies()
        self.query_one("#jh-jobs-table", DataTable).add_columns(
            "Score", "Status", "Company", "Title"
        )
        self._refresh_jobs()

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

    def _set_review_progress(self, message: str) -> None:
        try:
            prog = self.query_one("#jh-review-progress", Static)
        except NoMatches:
            return
        prog.update(message)
        prog.set_class(not message, "-empty")

    def _set_review_busy(self, busy: bool) -> None:
        self._reviewing = busy
        for selector in ("#jh-review-cv", "#jh-review-accept", "#jh-review-discard"):
            try:
                self.query_one(selector, Button).disabled = busy
            except NoMatches:
                pass

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

    def _start_review(self) -> None:
        if self._reviewing:
            return
        self._toggle_import_panel(False)
        self._toggle_paste_panel(False)
        self._set_error("")
        self._set_status("")

        raw_cli = self.query_one("#jh-review-cli", Select).value
        chosen_cli = str(raw_cli) if raw_cli is not Select.BLANK else None
        fn = self._review_run_fn if self._review_run_fn is not None else review.run

        token = object()
        self._review_token = token
        self._set_review_busy(True)
        self._set_review_progress("Reviewing CV…")

        def work() -> None:
            def on_progress(line: str) -> None:
                try:
                    self.app.call_from_thread(self._on_review_progress, line, token)
                except RuntimeError:
                    pass

            try:
                res = _call_review_run(fn, chosen_cli, on_progress)
            except Exception as error:
                try:
                    self.app.call_from_thread(self._on_review_error, str(error), token)
                except RuntimeError:
                    pass
                return
            try:
                self.app.call_from_thread(self._on_review_done, res, token)
            except RuntimeError:
                pass

        self.run_worker(work, thread=True, exclusive=True, group="jobs-review")

    def _on_review_progress(self, line: str, token: object) -> None:
        if token is not self._review_token or not self.is_attached:
            return
        shown = line.strip()
        self._set_review_progress(f"Reviewing CV · {shown}" if shown else "Reviewing CV…")

    def _on_review_error(self, message: str, token: object) -> None:
        if token is not self._review_token or not self.is_attached:
            return
        self._set_review_busy(False)
        self._set_review_progress("")
        self._set_error(message or "CV review failed.")

    def _on_review_done(self, result: review.ReviewResult, token: object) -> None:
        if token is not self._review_token or not self.is_attached:
            return
        self._set_review_busy(False)
        self._set_review_progress("")
        if not result.ok:
            detail = (
                f"{result.outcome}: {result.reason}"
                if result.reason
                else f"Review failed ({result.outcome})."
            )
            self._set_error(detail)
            return

        try:
            prof_area = self.query_one("#jh-profile-draft", TextArea)
            rub_area = self.query_one("#jh-rubric-draft", TextArea)
            panel = self.query_one("#jh-review-panel", Vertical)
        except NoMatches:
            return

        prof_area.load_text(result.profile)
        rub_area.load_text(result.rubric)
        panel.set_class(False, "-hidden")
        self._set_status("Drafts ready. Edit if needed, then press Accept or Discard.")
        panel.scroll_visible()

    def _accept_review(self) -> None:
        prof_area = self.query_one("#jh-profile-draft", TextArea)
        rub_area = self.query_one("#jh-rubric-draft", TextArea)
        profile_text = prof_area.text
        rubric_text = rub_area.text
        fn = self._review_accept_fn if self._review_accept_fn is not None else review.accept
        try:
            _call_review_accept(fn, profile_text, rubric_text)
        except (review.ReviewError, profile.ProfileError, OSError, ValueError) as error:
            self._set_error(str(error))
            return

        prof_area.load_text("")
        rub_area.load_text("")
        self.query_one("#jh-review-panel", Vertical).set_class(True, "-hidden")
        self._refresh_cv_status()
        self._set_status("Accepted profile.md and rubric.md.")

    def _discard_review(self) -> None:
        fn = self._review_discard_fn if self._review_discard_fn is not None else review.discard
        try:
            fn()
        except (review.ReviewError, profile.ProfileError, OSError, ValueError) as error:
            self._set_error(str(error))
            return

        self.query_one("#jh-profile-draft", TextArea).load_text("")
        self.query_one("#jh-rubric-draft", TextArea).load_text("")
        self.query_one("#jh-review-panel", Vertical).set_class(True, "-hidden")
        self._set_status("Discarded review drafts.")

    # ---- Companies ----

    def _refresh_companies(self) -> None:
        fn = self._companies_list_fn if self._companies_list_fn is not None else companies.list
        try:
            rows = [_coerce_company(c) for c in fn()]
        except (companies.CompanyError, OSError, ValueError) as error:
            self._set_error(str(error))
            return
        self._company_rows = rows
        try:
            table = self.query_one("#jh-companies-table", DataTable)
            empty = self.query_one("#jh-companies-empty", Static)
        except NoMatches:
            return
        table.clear()
        for item in rows:
            table.add_row(
                _cell(item.name),
                _cell(item.status),
                _cell(format_company_board(item)),
                _cell(item.reason),
            )
        empty.set_class(bool(rows), "-empty")

    def _selected_company(self) -> str | None:
        try:
            table = self.query_one("#jh-companies-table", DataTable)
        except NoMatches:
            return None
        if not 0 <= table.cursor_row < len(self._company_rows):
            return None
        return self._company_rows[table.cursor_row].name

    def _set_companies_progress(self, message: str) -> None:
        try:
            prog = self.query_one("#jh-companies-progress", Static)
        except NoMatches:
            return
        prog.update(message)
        prog.set_class(not message, "-empty")

    def _set_companies_busy(self, busy: bool) -> None:
        self._companies_busy = busy
        for selector in (
            "#jh-co-suggest",
            "#jh-co-check",
            "#jh-co-fetch",
            "#jh-co-accept",
            "#jh-co-remove",
        ):
            try:
                self.query_one(selector, Button).disabled = busy
            except NoMatches:
                pass

    def _start_companies_work(
        self, label: str, run: Callable[[Callable[[str], None]], str]
    ) -> None:
        if self._companies_busy:
            return
        self._set_error("")
        self._set_status("")
        token = object()
        self._companies_token = token
        self._set_companies_busy(True)
        self._set_companies_progress(f"{label}…")

        def work() -> None:
            def on_progress(line: str) -> None:
                try:
                    self.app.call_from_thread(self._on_companies_progress, label, line, token)
                except RuntimeError:
                    pass

            try:
                summary = run(on_progress)
            except Exception as error:
                try:
                    self.app.call_from_thread(self._on_companies_done, "", str(error), token)
                except RuntimeError:
                    pass
                return
            try:
                self.app.call_from_thread(self._on_companies_done, summary, "", token)
            except RuntimeError:
                pass

        self.run_worker(work, thread=True, exclusive=True, group="jobs-companies")

    def _on_companies_progress(self, label: str, line: str, token: object) -> None:
        if token is not self._companies_token or not self.is_attached:
            return
        shown = line.strip()
        self._set_companies_progress(f"{label} · {shown}" if shown else f"{label}…")

    def _on_companies_done(self, summary: str, error: str, token: object) -> None:
        if token is not self._companies_token or not self.is_attached:
            return
        self._set_companies_busy(False)
        self._set_companies_progress("")
        self._refresh_companies()
        if error:
            self._set_error(error)
        elif summary:
            self._set_status(summary)

    def _suggest_companies(self) -> None:
        fn = (
            self._companies_suggest_fn
            if self._companies_suggest_fn is not None
            else companies.suggest
        )
        raw_cli = self.query_one("#jh-review-cli", Select).value
        chosen_cli = str(raw_cli) if raw_cli is not Select.BLANK else None

        def run(progress: Callable[[str], None]) -> str:
            res = fn(chosen_cli, progress=progress)
            if not res.ok:
                detail = f"{res.outcome}: {res.reason}" if res.reason else res.outcome
                raise companies.CompanyError(f"Suggest failed ({detail}).")
            count = len(res.added)
            return f"Suggested {count} new {'company' if count == 1 else 'companies'}."

        self._start_companies_work("Suggesting companies", run)

    def _check_companies(self) -> None:
        fn = self._companies_check_fn if self._companies_check_fn is not None else companies.check

        def run(progress: Callable[[str], None]) -> str:
            count = len(_call_companies_check(fn, progress))
            return f"Checked {count} {'company' if count == 1 else 'companies'}."

        self._start_companies_work("Checking boards", run)

    def _fetch_now(self) -> None:
        """Run the jobs-fetch step into a preview folder; nothing is marked seen."""
        if self._fetch_fn is not None:
            fn = self._fetch_fn
        else:
            from whyline.jobs import step

            fn = step.preview

        def run(progress: Callable[[str], None]) -> str:
            report = fn(dry_run=True)
            return "\n".join([report.summary(), *report.lines()])

        self._start_companies_work("Fetching postings", run)

    def _company_action(self, kind: str) -> None:
        if self._companies_busy:
            return
        name = self._selected_company()
        if name is None:
            self._set_error("Select a company first.")
            return
        if kind == "accept":
            fn = (
                self._companies_accept_fn
                if self._companies_accept_fn is not None
                else companies.accept
            )
            done = f"Accepted {name}."
        else:
            fn = (
                self._companies_remove_fn
                if self._companies_remove_fn is not None
                else companies.remove
            )
            done = f"Removed {name}."
        try:
            fn(name)
        except (companies.CompanyError, OSError, ValueError) as error:
            self._set_error(str(error))
            return
        self._refresh_companies()
        self._set_status(done)

    def _toggle_company_panel(self, show: bool) -> None:
        panel = self.query_one("#jh-company-panel", Vertical)
        panel.set_class(not show, "-hidden")
        if show:
            self.query_one("#jh-company-name", Input).focus()
            panel.scroll_visible()

    def _do_add_company(self) -> None:
        name_input = self.query_one("#jh-company-name", Input)
        url_input = self.query_one("#jh-company-url", Input)
        name = name_input.value.strip()
        if not name:
            self._set_error("Enter a company name.")
            return
        url = url_input.value.strip() or None
        fn = self._companies_add_fn if self._companies_add_fn is not None else companies.add
        try:
            _call_companies_add(fn, name, url)
        except (companies.CompanyError, OSError, ValueError) as error:
            self._set_error(str(error))
            return
        name_input.value = ""
        url_input.value = ""
        self._toggle_company_panel(False)
        self._refresh_companies()
        self._set_status(f"Added {name}.")

    # ---- Jobs tracker ----

    def _refresh_jobs(self) -> None:
        fn = self._jobs_list_fn if self._jobs_list_fn is not None else tracker.list_rows
        try:
            chosen = self.query_one("#jh-jobs-filter", Select).value
            table = self.query_one("#jh-jobs-table", DataTable)
            empty = self.query_one("#jh-jobs-empty", Static)
        except NoMatches:
            return
        status = None if chosen in (Select.BLANK, "all") else str(chosen)
        try:
            rows = list(fn(status=status))
        except (tracker.TrackerError, OSError, ValueError) as error:
            rows = []
            self._set_error(str(error))
        self._job_rows = rows
        table.clear()
        for row in rows:
            score = row.get("score")
            table.add_row(
                _cell("-" if score is None else score),
                _cell(row.get("status")),
                _cell(row.get("company")),
                _cell(row.get("title")),
            )
        empty.set_class(bool(rows), "-empty")

    def _selected_job(self) -> Mapping[str, Any] | None:
        table = self.query_one("#jh-jobs-table", DataTable)
        if not 0 <= table.cursor_row < len(self._job_rows):
            return None
        return self._job_rows[table.cursor_row]

    def _open_job_edit(self, mode: str) -> None:
        job = self._selected_job()
        if job is None:
            self._set_error("Select a job first.")
            return
        self._job_edit_mode = mode
        select = self.query_one("#jh-jobs-status-select", Select)
        note = self.query_one("#jh-jobs-note", Input)
        select.display = mode == "status"
        note.display = mode == "note"
        if mode == "status" and job.get("status") in tracker.STATUSES:
            select.value = job["status"]
        note.value = str(job.get("notes") or "") if mode == "note" else ""
        panel = self.query_one("#jh-jobs-edit-panel", Vertical)
        panel.set_class(False, "-hidden")
        (select if mode == "status" else note).focus()
        panel.scroll_visible()

    def _close_job_edit(self) -> None:
        self._job_edit_mode = ""
        self.query_one("#jh-jobs-edit-panel", Vertical).set_class(True, "-hidden")

    def _save_job_edit(self) -> None:
        job = self._selected_job()
        if job is None or not self._job_edit_mode:
            self._set_error("Select a job first.")
            return
        if self._job_edit_mode == "status":
            status = str(self.query_one("#jh-jobs-status-select", Select).value)
            note = None
        else:
            status = str(job.get("status") or tracker.STATUSES[0])
            note = self.query_one("#jh-jobs-note", Input).value.strip()
        fn = self._jobs_set_fn if self._jobs_set_fn is not None else tracker.set_status
        try:
            fn(str(job.get("uid") or job.get("row")), status, note)
        except (tracker.TrackerError, OSError, ValueError) as error:
            self._set_error(str(error))
            return
        self._close_job_edit()
        self._refresh_jobs()
        self._set_status(f"Set {job.get('company') or 'job'} to {status}.")

    def _open_job_link(self) -> None:
        job = self._selected_job()
        if job is None:
            self._set_error("Select a job first.")
            return
        url = str(job.get("url") or "")
        if not url.startswith(("https://", "http://")):
            self._set_error("This job has no web link.")
            return
        fn = self._open_link_fn if self._open_link_fn is not None else webbrowser.open
        try:
            fn(url)
        except Exception as error:  # noqa: BLE001 - shown to the user, never crashes the console
            self._set_error(str(error))
            return
        self._set_status(f"Opened {url}")

    def _open_excel(self) -> None:
        export = self._jobs_export_fn if self._jobs_export_fn is not None else tracker.export_xlsx
        try:
            path = Path(export())
        except Exception as error:  # noqa: BLE001
            self._set_error(str(error))
            return
        if self._open_file_fn is not None:
            opener = self._open_file_fn
        else:
            from whyline.console.ideas_screen import _open_with_macos as opener
        message = opener(path)
        if message:
            self._set_error(message)
            return
        self._set_status(f"Opened {tilde_path(path)}.")

    def _set_draft_progress(self, message: str) -> None:
        try:
            prog = self.query_one("#jh-jobs-draft-progress", Static)
        except NoMatches:
            return
        prog.update(message)
        prog.set_class(not message, "-empty")

    def _start_draft(self) -> None:
        job = self._selected_job()
        if job is None:
            self._set_error("Select a job first.")
            return
        if self._drafting:
            return
        self._set_error("")
        self._set_status("")
        fn = self._draft_fn if self._draft_fn is not None else apply.draft
        ref = str(job.get("uid") or job.get("row"))
        label = f"Drafting {job.get('company') or 'application'}"
        token = object()
        self._draft_token = token
        self._drafting = True
        self.query_one("#jh-jobs-draft", Button).disabled = True
        self.query_one("#jh-jobs-open-folder", Button).disabled = True
        self._draft_folder = None
        self._set_draft_progress(f"{label}…")

        def work() -> None:
            def on_progress(line: str) -> None:
                try:
                    self.app.call_from_thread(self._on_draft_progress, label, line, token)
                except RuntimeError:
                    pass

            folder: Path | None = None
            error = ""
            try:
                res = fn(ref, progress=on_progress)
                if getattr(res, "ok", True):
                    folder = getattr(res, "folder", None)
                else:
                    reason = getattr(res, "reason", "")
                    outcome = getattr(res, "outcome", "failed")
                    error = f"{outcome}: {reason}" if reason else str(outcome)
            except Exception as caught:  # noqa: BLE001 - shown to the user
                error = str(caught)
            try:
                self.app.call_from_thread(self._on_draft_done, folder, error, token)
            except RuntimeError:
                pass

        self.run_worker(work, thread=True, exclusive=True, group="jobs-draft")

    def _on_draft_progress(self, label: str, line: str, token: object) -> None:
        if token is not self._draft_token or not self.is_attached:
            return
        shown = line.strip()
        self._set_draft_progress(f"{label} · {shown}" if shown else f"{label}…")

    def _on_draft_done(self, folder: Path | None, error: str, token: object) -> None:
        if token is not self._draft_token or not self.is_attached:
            return
        self._drafting = False
        self.query_one("#jh-jobs-draft", Button).disabled = False
        self._set_draft_progress("")
        self._refresh_jobs()
        if error:
            self._set_error(error)
            return
        self._draft_folder = Path(folder) if folder is not None else None
        self.query_one("#jh-jobs-open-folder", Button).disabled = self._draft_folder is None
        self._set_status(
            f"Draft ready in {tilde_path(self._draft_folder)}." if self._draft_folder else "Draft ready."
        )

    def _open_draft_folder(self) -> None:
        if self._draft_folder is None:
            self._set_error("No draft folder to open.")
            return
        if self._open_file_fn is not None:
            opener = self._open_file_fn
        else:
            from whyline.console.ideas_screen import _open_with_macos as opener
        message = opener(self._draft_folder)
        if message:
            self._set_error(message)
            return
        self._set_status(f"Opened {tilde_path(self._draft_folder)}.")

    def _run_check(self) -> None:
        fn = self._doctor_fn if self._doctor_fn is not None else doctor.check
        try:
            lines = doctor.format_rows(list(fn()))
        except Exception as error:  # noqa: BLE001
            self._set_error(str(error))
            return
        out = self.query_one("#jh-jobs-check", Static)
        out.update("\n".join(lines))
        out.set_class(False, "-empty")
        out.scroll_visible()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "jh-jobs-filter":
            event.stop()
            self._refresh_jobs()

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
        elif event.input.id in ("jh-company-name", "jh-company-url"):
            event.stop()
            self._do_add_company()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        event.stop()
        if button_id == "jh-close":
            self.action_close()
        elif button_id == "jh-save":
            self._save_preferences()
        elif button_id == "jh-jobs-set":
            self._open_job_edit("status")
        elif button_id == "jh-jobs-note-open":
            self._open_job_edit("note")
        elif button_id == "jh-jobs-edit-confirm":
            self._save_job_edit()
        elif button_id == "jh-jobs-edit-cancel":
            self._close_job_edit()
        elif button_id == "jh-jobs-link":
            self._open_job_link()
        elif button_id == "jh-jobs-excel":
            self._open_excel()
        elif button_id == "jh-jobs-draft":
            self._start_draft()
        elif button_id == "jh-jobs-open-folder":
            self._open_draft_folder()
        elif button_id == "jh-jobs-check-run":
            self._run_check()
        elif button_id == "jh-alerts-mail":
            self._mail_rule()
        elif button_id == "jh-tracked":
            self.app.push_screen(TrackedJobsScreen())
        elif button_id == "jh-review-cv":
            self._start_review()
        elif button_id == "jh-review-accept":
            self._accept_review()
        elif button_id == "jh-review-discard":
            self._discard_review()
        elif button_id == "jh-co-suggest":
            self._suggest_companies()
        elif button_id == "jh-co-check":
            self._check_companies()
        elif button_id == "jh-co-fetch":
            self._fetch_now()
        elif button_id == "jh-co-accept":
            self._company_action("accept")
        elif button_id == "jh-co-remove":
            self._company_action("remove")
        elif button_id == "jh-co-add":
            hidden = self.query_one("#jh-company-panel", Vertical).has_class("-hidden")
            self._toggle_company_panel(hidden)
        elif button_id == "jh-co-add-confirm":
            self._do_add_company()
        elif button_id == "jh-co-add-cancel":
            self.query_one("#jh-company-name", Input).value = ""
            self.query_one("#jh-company-url", Input).value = ""
            self._toggle_company_panel(False)
            self._set_error("")
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


class TrackedJobsScreen(ModalScreen):
    """Tracked job postings: change status and notes, export jobs.xlsx."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    TrackedJobsScreen { align: center middle; }
    TrackedJobsScreen > Vertical {
        width: 110; max-width: 100%; height: 100%; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    TrackedJobsScreen #tj-title { text-style: bold; }
    TrackedJobsScreen #tj-empty { height: auto; color: $text-muted; }
    TrackedJobsScreen #tj-empty.-empty { display: none; }
    TrackedJobsScreen #tj-table { width: 100%; height: 1fr; min-height: 3; }
    TrackedJobsScreen #tj-edit { height: auto; margin-top: 1; }
    TrackedJobsScreen #tj-status-select { width: 20; }
    TrackedJobsScreen #tj-note { width: 1fr; }
    TrackedJobsScreen #tj-error { height: auto; max-height: 3; color: $error; }
    TrackedJobsScreen #tj-error.-empty { display: none; }
    TrackedJobsScreen #tj-status { height: auto; max-height: 2; color: $success; }
    TrackedJobsScreen #tj-status.-empty { display: none; }
    TrackedJobsScreen #tj-buttons { height: auto; margin-top: 1; }
    TrackedJobsScreen #tj-buttons Button { min-width: 8; width: auto; margin-right: 1; }
    """

    def __init__(
        self,
        *,
        list_fn: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        set_fn: Callable[..., Any] | None = None,
        export_fn: Callable[[], Path] | None = None,
    ) -> None:
        super().__init__()
        self._list_fn = list_fn
        self._set_fn = set_fn
        self._export_fn = export_fn
        self._rows: list[Mapping[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Tracked jobs", id="tj-title"),
            Static("No tracked jobs yet.", id="tj-empty", markup=False, classes="-empty"),
            DataTable(id="tj-table", cursor_type="row"),
            Horizontal(
                Select(
                    [(name, name) for name in tracker.STATUSES],
                    allow_blank=False,
                    value=tracker.STATUSES[0],
                    id="tj-status-select",
                ),
                Input(placeholder="Note (optional)", id="tj-note"),
                id="tj-edit",
            ),
            Static("", id="tj-error", markup=False, classes="-empty"),
            Static("", id="tj-status", markup=False, classes="-empty"),
            Horizontal(
                Button("Set status", id="tj-set", variant="success"),
                Button("Clear note", id="tj-clear-note"),
                Button("Export Excel", id="tj-export"),
                Button("Close", id="tj-close"),
                id="tj-buttons",
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#tj-table", DataTable).add_columns(
            "Row", "Score", "Status", "Company", "Title", "Notes"
        )
        self._refresh()

    def action_close(self) -> None:
        self.dismiss(None)

    def _show(self, error: str = "", status: str = "") -> None:
        for widget_id, text in (("#tj-error", error), ("#tj-status", status)):
            widget = self.query_one(widget_id, Static)
            widget.update(text)
            widget.set_class(not text, "-empty")

    def _refresh(self) -> None:
        fn = self._list_fn if self._list_fn is not None else tracker.list_rows
        try:
            self._rows = list(fn())
        except (tracker.TrackerError, OSError, ValueError) as error:
            self._rows = []
            self._show(error=str(error))
        table = self.query_one("#tj-table", DataTable)
        table.clear()
        for row in self._rows:
            table.add_row(
                _cell(row.get("row")),
                _cell(row.get("score")),
                _cell(row.get("status")),
                _cell(row.get("company")),
                _cell(row.get("title")),
                _cell(row.get("notes")),
            )
        self.query_one("#tj-empty", Static).set_class(bool(self._rows), "-empty")

    def _selected(self) -> Mapping[str, Any] | None:
        table = self.query_one("#tj-table", DataTable)
        if not self._rows or not 0 <= table.cursor_row < len(self._rows):
            return None
        return self._rows[table.cursor_row]

    def _set_selected(self, clear_note: bool = False) -> None:
        row = self._selected()
        if row is None:
            self._show(error="Select a job first.")
            return
        status = self.query_one("#tj-status-select", Select).value
        # An empty string clears the stored note; None keeps it.
        note = "" if clear_note else (self.query_one("#tj-note", Input).value.strip() or None)
        fn = self._set_fn if self._set_fn is not None else tracker.set_status
        try:
            fn(str(row.get("uid") or row.get("row")), str(status), note)
        except (tracker.TrackerError, OSError, ValueError) as error:
            self._show(error=str(error))
            return
        self.query_one("#tj-note", Input).value = ""
        self._refresh()
        self._show(status=f"Set {row.get('company') or 'job'} to {status}.")

    def _export(self) -> None:
        fn = self._export_fn if self._export_fn is not None else tracker.export_xlsx
        try:
            path = fn()
        except Exception as error:  # noqa: BLE001 - shown to the user, never crashes the console
            self._show(error=str(error))
            return
        self._show(status=f"Exported {tilde_path(Path(path))}.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id == "tj-close":
            self.action_close()
        elif button_id == "tj-set":
            self._set_selected()
        elif button_id == "tj-clear-note":
            self._set_selected(clear_note=True)
        elif button_id == "tj-export":
            self._export()
