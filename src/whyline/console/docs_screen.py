"""The Docs screen: the product PRD, document sets and earlier plans in three
columns (what, which document, its text). It reads the docs checkout; while a
relay runs in that checkout every action except History and Export is off."""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Checkbox, Input, Markdown, OptionList, RadioButton, RadioSet, Select, SelectionList,
    Static, TextArea,
)
from textual.widgets.option_list import Option

from whyline.sdlc import close as close_mod
from whyline.sdlc import docset, export, github_repo, goldfish, guard, library, stages, templates, trace, workspace
from whyline.sdlc import home as home_mod
from whyline.sdlc import product as prd
from whyline.sdlc import review as review_mod
from whyline.sdlc import runner as runner_mod

PRODUCT = "product"
SET_PREFIX = "set:"
PLAN_PREFIX = "plan:"
PRD_DOC = "prd"
CHANGELOG_DOC = "changelog"
NOTHING = "Nothing to show yet."
_ACTIONS = ("docs-check", "docs-open")
_ALWAYS_ON = ("docs-history", "docs-export", "docs-close")
_SET_ACTIONS = ("docs-close-set", "docs-pr", "docs-switch", "docs-github")
_REVIEW = (
    ("docs-approve", "Approve"),
    ("docs-changes", "Ask for changes"),
    ("docs-edit", "Edit"),
    ("docs-redo", "Redo"),
    ("docs-review-again", "Review again"),
    ("docs-answer", "Answer questions"),
    ("docs-stop", "Stop here"),
    ("docs-auto", "Run the rest on Auto"),
    ("docs-resume", "Resume"),
    ("docs-diff", "Show diff"),
    ("docs-whole", "Show whole PRD"),
    ("docs-finished", "I've finished editing"),
)
WHOLE_DOCUMENT = "Whole document"
NOT_REVIEWED = "Not reviewed yet."
_SEVERITY_ICONS = (("blocker", "🔴", "Blocker"), ("major", "🟡", "Major"), ("nit", "🟢", "Nit"))
_TICKED = ("blocker", "major")


@dataclass(frozen=True)
class Row:
    """One selectable line: its id, the text shown, and the reason under it."""

    key: str
    label: str
    reason: str = ""


def _approval(doc: dict) -> str:
    if not doc.get("approved_by"):
        return "not approved"
    text = f"approved by {doc['approved_by']}"
    if doc.get("approved_at"):
        text += f" on {str(doc['approved_at'])[:10]}"
    return text


def _latest(latest: Callable | None, docs: Path, found: object, kind: str) -> object:
    """The latest review of one document, or None when there is none or it can't be read."""
    try:
        return (latest or goldfish.latest_review)(docs, found, kind)
    except Exception:
        return None


def counts_text(review: object) -> str:
    """`🔴 1 🟡 2` for the severities that have findings; empty with none."""
    findings = getattr(review, "findings", None) or []
    parts = []
    for severity, icon, _ in _SEVERITY_ICONS:
        number = sum(1 for f in findings if f.severity == severity)
        if number:
            parts.append(f"{icon} {number}")
    return " ".join(parts)


def findings_text(review: object) -> str:
    """The Findings panel: first line, findings by severity, and any lenses that did not run."""
    if review is None:
        return NOT_REVIEWED
    path = getattr(review, "path", None)
    try:
        first = Path(path).read_text(encoding="utf-8").splitlines()[0] if path else ""
    except (OSError, IndexError, TypeError):
        first = ""
    lines = [first] if first else []
    findings = list(getattr(review, "findings", None) or [])
    for severity, icon, name in _SEVERITY_ICONS:
        for f in (x for x in findings if x.severity == severity):
            lines.append(f"{icon} {name} · {f.section} · {f.lens}: {f.problem} — {f.fix}")
    not_run = list(getattr(review, "not_run", None) or [])
    if not_run:
        lines.append("Not run: " + ", ".join(not_run))
    return "\n".join(lines) or NOT_REVIEWED


def finding_comment(finding: object) -> str:
    return f"{finding.section}: {finding.problem} — {finding.fix}"


def left_rows(docs: Path) -> list[Row]:
    rows: list[Row] = []
    product = library.product(docs)
    if product is not None:
        rows.append(Row(PRODUCT, f"Product PRD v{product.version}"))
    sets = library.sets(docs)
    if sets:
        rows.append(Row("", "Document sets"))
        rows += [Row(SET_PREFIX + s.slug, s.summary) for s in sets]
    plans = library.earlier_plans(docs)
    if plans:
        rows.append(Row("", "Earlier plans"))
        rows += [Row(PLAN_PREFIX + p.slug, p.slug) for p in plans]
    return rows


def middle_rows(docs: Path, entry: str, latest: Callable | None = None) -> list[Row]:
    if entry == PRODUCT:
        product = library.product(docs)
        if product is None:
            return []
        approval = product.approval and f"approved by {product.approval}" or "not approved"
        return [
            Row(PRD_DOC, f"Product PRD · v{product.version} · {approval}"),
            Row(CHANGELOG_DOC, "Changelog"),
        ]
    if entry.startswith(SET_PREFIX):
        try:
            found = docset.load(docs, entry[len(SET_PREFIX):])
        except docset.DocSetError:
            return []
        rows = []
        for doc in found.documents:
            status = docset.Status(doc["status"])
            title = doc["kind"].replace("-", " ").capitalize()
            counts = counts_text(_latest(latest, docs, found, doc["kind"]))
            label = (
                f"{title} · {docset.version_label(found, doc, docs)} · "
                f"{status.label} · {counts + ' · ' if counts else ''}{_approval(doc)}"
            )
            reason = ""
            if status is docset.Status.OUT_OF_DATE:
                reason = doc.get("out_of_date_reason") or "An earlier document changed."
            if _prd_update(docs, found, doc["kind"]):
                holder = prd.claim_holder(docs)
                if holder and holder != found.slug:
                    reason = f"Waiting: {holder} is updating the PRD"
            if doc["kind"] == "plan":
                line = coverage_line(docs, found)
                reason = f"{reason} · {line}" if reason and line else reason or line
            rows.append(Row(doc["kind"], label, reason))
        return rows
    if entry.startswith(PLAN_PREFIX):
        slug = entry[len(PLAN_PREFIX):]
        for plan in library.earlier_plans(docs):
            if plan.slug == slug:
                rows = [Row("plan", "Plan")]
                if plan.test_plan is not None:
                    rows.append(Row("tests", "Test plan"))
                if plan.source is not None:
                    rows.append(Row("source", plan.source_kind.capitalize() or "Source"))
                return rows
    return []


def coverage_line(docs: Path, found: object) -> str:
    """`Covers 3 of 4 requirements · ...` for the plan row; empty when it can't be worked out."""
    try:
        return trace.coverage(docs, found).line()
    except Exception:
        return ""


def _github_recorded(docs: Path, slug: str) -> bool:
    """True when a GitHub repository was already created for the set."""
    try:
        data = json.loads((docset._folder(docs, slug) / docset.MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(isinstance(data, dict) and data.get("github"))


def set_actions(docs: Path, slug: str) -> set[str]:
    """Close on a set whose build record is approved; Open pull request on a closed set with no PR."""
    try:
        found = docset.load(docs, slug)
    except docset.DocSetError:
        return set()
    shown: set[str] = set()
    if found.state == "moved":
        return {"docs-switch"} if library._moved_to(docs, slug) else shown
    if not _github_recorded(docs, slug):
        shown.add("docs-github")
    built = found.document("build-record")
    closed = found.state in ("released", "built")
    if built is not None and built["status"] == docset.Status.APPROVED.value and not closed:
        shown.add("docs-close-set")
    if closed and not found.pr_url:
        shown.add("docs-pr")
    return shown


def _prd_update(docs: Path, found: object, kind: str) -> bool:
    return kind == "prd" and found.prd_mode == docset.PrdMode.UPDATE.value


def prd_moved_line(docs: Path, found: object) -> str:
    """`The PRD is now v<new>. Redo this update first.` when the product PRD moved on, else empty."""
    now = prd.current(docs)
    if now is None or not prd.moved(docs, found):
        return ""
    return f"The PRD is now v{now.version}. Redo this update first."


def prd_update_text(docs: Path, found: object, view: str = "summary") -> str:
    """The right pane of a PRD update: changed sections, then the diff or the whole PRD."""
    doc = found.document("prd")
    mine = (docset._current_text(docs, found, doc) or "") if doc else ""
    now = prd.current(docs)
    base = prd.body(now.text) if now is not None else ""
    if view == "whole":
        return mine or NOTHING
    changed = ", ".join(prd.changed_sections(base, mine)) or "none"
    lines = [f"Changed sections: {changed}", ""]
    moved = prd_moved_line(docs, found)
    if moved:
        lines += [moved, ""]
    if view == "diff":
        diff = "\n".join(difflib.unified_diff(
            base.splitlines(), mine.splitlines(), "product PRD", "this update", lineterm=""))
        lines += ["```diff", diff or "No differences.", "```"]
    return "\n".join(lines)


def _read(path: Path | None) -> str:
    if path is None:
        return NOTHING
    try:
        return docset.strip_header(path.read_text(encoding="utf-8")) or NOTHING
    except (OSError, UnicodeDecodeError):
        return NOTHING


def document_text(docs: Path, entry: str, key: str) -> str:
    """The Markdown of one document."""
    if entry == PRODUCT:
        if key == CHANGELOG_DOC:
            return _read(docs / prd.PRODUCT_DIR / prd.CHANGELOG)
        now = prd.current(docs)
        return prd.body(now.text) if now is not None else NOTHING
    if entry.startswith(SET_PREFIX):
        try:
            found = docset.load(docs, entry[len(SET_PREFIX):])
        except docset.DocSetError as error:
            return str(error)
        doc = found.document(key)
        if doc is not None and _prd_update(docs, found, key):
            return prd_update_text(docs, found)
        return (docset._current_text(docs, found, doc) or NOTHING) if doc else NOTHING
    if entry.startswith(PLAN_PREFIX):
        slug = entry[len(PLAN_PREFIX):]
        for plan in library.earlier_plans(docs):
            if plan.slug == slug:
                path = {"plan": plan.plan, "tests": plan.test_plan, "source": plan.source}.get(key)
                return _read(path)
    return NOTHING


def _version_order(label: str) -> tuple[int, ...]:
    return tuple(int(part) for part in label.split("."))


def history_versions(docs: Path, entry: str, key: str) -> list[tuple[str, Path]]:
    """(label, file) of each stored version of the selected document, oldest first."""
    if entry == PRODUCT:
        folder, stem = docs / prd.PRODUCT_DIR / prd.HISTORY_DIR, "prd"
    elif entry.startswith(SET_PREFIX):
        folder = docs / docset.SDLC_DIR / entry[len(SET_PREFIX):] / docset.HISTORY_DIR
        stem = key
    else:
        return []
    found = []
    for path in folder.glob(f"{stem}-v*.md") if folder.is_dir() and stem else []:
        number = path.name[len(stem) + 2:-3]
        if re.fullmatch(r"\d+(\.\d+)*", number):
            found.append((number, path))
    return sorted(found, key=lambda item: _version_order(item[0]))


def review_log_entries(docs: Path, entry: str) -> list[str]:
    """The entries of the set's review-log.md, each starting at its ### line."""
    if not entry.startswith(SET_PREFIX):
        return []
    path = docs / docset.SDLC_DIR / entry[len(SET_PREFIX):] / docset.REVIEW_LOG
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    entries: list[str] = []
    for line in text.splitlines():
        if line.startswith("### "):
            entries.append(line)
        elif entries:
            entries[-1] += "\n" + line
    return [e.strip() for e in entries]


def history_text(docs: Path, entry: str, key: str, picks: tuple[str, ...] = ()) -> str:
    """Versions and review-log entries of the selected document, as Markdown.

    One pick shows that version's text; two picks show a unified diff.
    """
    if not entry == PRODUCT and not entry.startswith(SET_PREFIX):
        return "Earlier plans keep no version history."
    versions = dict(history_versions(docs, entry, key))
    chosen = [n for n in picks if n in versions][:2]
    if len(chosen) == 1:
        return f"# Version {chosen[0]}\n\n{_read(versions[chosen[0]])}\n"
    if len(chosen) == 2:
        old, new = sorted(chosen, key=_version_order)
        diff = "\n".join(difflib.unified_diff(
            _read(versions[old]).splitlines(), _read(versions[new]).splitlines(),
            f"v{old}", f"v{new}", lineterm=""))
        return f"# Version {old} → {new}\n\n```diff\n{diff or 'No differences.'}\n```\n"
    logged = review_log_entries(docs, entry)
    if not versions and not logged:
        return "No earlier versions are stored."
    lines = ["# History", ""]
    if versions:
        lines += ["## Versions", ""] + [f"- v{n} · `{p.name}`" for n, p in sorted(versions.items(), key=lambda item: _version_order(item[0]))]
        lines += ["", "Pick one version to read it, or two to compare them.", ""]
    if logged:
        lines += ["## Review log", ""] + [e + "\n" for e in logged]
    return "\n".join(lines) + "\n"


def section_choices(docs: Path, slug: str, kind: str) -> list[tuple[str, str]]:
    """(label, value) pairs for the section select; "Whole document" (value "") first."""
    try:
        found = docset.load(docs, slug)
        names = templates.sections(templates.template_for(docs, kind, found.size))
    except Exception:
        names = []
    return [(WHOLE_DOCUMENT, "")] + [(name, name) for name in names]


def available_actions(docs: Path, slug: str, kind: str, editing: bool = False) -> set[str]:
    """The ids of the review buttons that apply to one document of a set."""
    try:
        found = docset.load(docs, slug)
    except docset.DocSetError:
        return set()
    doc = found.document(kind)
    if doc is None:
        return set()
    if editing:
        return {"docs-finished"}
    shown: set[str] = set()
    in_review = doc["status"] == docset.Status.IN_REVIEW.value
    upcoming = stages.next_stage(found)
    out_of_date = doc["status"] == docset.Status.OUT_OF_DATE.value
    if in_review:
        shown |= {"docs-approve", "docs-changes", "docs-edit", "docs-review-again"}
    updating = _prd_update(docs, found, kind)
    if (in_review or out_of_date) and (found.documents[0]["kind"] != kind or updating):
        shown.add("docs-redo")
    if updating:
        shown |= {"docs-diff", "docs-whole"}
    if found.pending_questions.get(kind):
        shown.add("docs-answer")
    if found.stage:
        shown.add("docs-stop")
    elif upcoming is not None and not in_review and not out_of_date:
        shown.add("docs-resume")
    if found.mode == docset.Mode.HUMAN.value and upcoming is not None and not out_of_date:
        shown.add("docs-auto")
    return shown


def _outcome_text(result: object) -> str:
    state = getattr(result, "state", "")
    if not state:
        return ""
    return str(getattr(result, "message", "") or f"Run: {state}")


class ConfirmForm(ModalScreen):
    """A question with Yes and No. Dismisses with True or False."""

    BINDINGS = [("escape", "no", "No")]
    DEFAULT_CSS = """
    ConfirmForm { align: center middle; }
    #confirm-box { width: 70; height: auto; border: round $accent; background: $surface; padding: 1 2; }
    """

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._question, id="confirm-question"),
            Horizontal(Button("Yes", id="confirm-yes"), Button("No", id="confirm-no")),
            id="confirm-box",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_no(self) -> None:
        self.dismiss(False)


class ReviewForm(ModalScreen):
    """A comments box and, when `sections` is given, a section select. Dismisses with
    (comments, section), or None on Cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ReviewForm { align: center middle; }
    #form-box { width: 70; height: auto; border: round $accent; background: $surface; padding: 1 2; }
    #form-comments { height: 8; }
    #form-findings { height: 8; }
    """

    def __init__(
        self,
        title: str,
        sections: list[tuple[str, str]] | None = None,
        findings: list | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self.section_options = sections
        self.findings = list(findings or [])

    def compose(self) -> ComposeResult:
        children: list = [Static(self._title), TextArea(id="form-comments")]
        if self.findings:
            children.append(Static("Findings to include"))
            children.append(SelectionList[int](
                *[
                    (f"{finding_comment(f)} ({f.severity})", index, f.severity in _TICKED)
                    for index, f in enumerate(self.findings)
                ],
                id="form-findings",
            ))
        if self.section_options is not None:
            children.append(Select(self.section_options, allow_blank=False, id="form-section"))
        children.append(
            Horizontal(Button("Send", id="form-send"), Button("Cancel", id="form-cancel"))
        )
        yield Vertical(*children, id="form-box")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "form-cancel":
            self.dismiss(None)
            return
        comments = self.query_one("#form-comments", TextArea).text.strip()
        if self.findings:
            ticked = self.query_one("#form-findings", SelectionList).selected
            lines = [finding_comment(f) for i, f in enumerate(self.findings) if i in ticked]
            comments = "\n".join(([comments] if comments else []) + lines)
        if not comments:
            return
        section = ""
        if self.section_options is not None:
            value = self.query_one("#form-section", Select).value
            section = value if isinstance(value, str) else ""
        self.dismiss((comments, section))

    def action_cancel(self) -> None:
        self.dismiss(None)


def _option(row: Row) -> Option:
    text = Text(row.label)
    if row.reason:
        text.append("\n  " + row.reason, style="dim")
    return Option(text, id=row.key or None, disabled=not row.key)


class DocsScreen(ModalScreen):
    """Closes with None. Opens on `set_slug` and `kind` when given."""

    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    DocsScreen { align: center middle; }
    #docs-box { width: 95%; height: 95%; border: round $accent; background: $surface; padding: 1 2; }
    #docs-columns { height: 1fr; }
    #docs-left { width: 1fr; }
    #docs-middle { width: 1fr; }
    #docs-right { width: 2fr; height: 100%; border: round $primary; }
    #docs-location { height: auto; color: $text-muted; }
    #docs-reason { height: auto; color: $warning; }
    #docs-versions { height: auto; max-height: 8; display: none; }
    #docs-findings { height: auto; padding: 1 0 0 0; }
    #docs-status { height: auto; }
    #docs-actions { height: auto; }
    #docs-review { height: auto; }
    #docs-review Button { min-width: 6; padding: 0 1; }
    #docs-also { height: auto; color: $text-muted; }
    """

    def __init__(
        self,
        root: Path | str,
        *,
        set_slug: str | None = None,
        kind: str | None = None,
        docs: Path | None = None,
        check: Callable[[Path], str | None] = guard.check,
        export_pack: Callable[..., object] = export.export_pack,
        opener: Callable[[Path], object] | None = None,
        revealer: Callable[[Path], object] | None = None,
        review: object = review_mod,
        runner: object = runner_mod,
        approver: str = "human",
        latest: Callable | None = None,
        closer: Callable[..., object] = close_mod.close,
        pr_opener: Callable[..., str] = close_mod.open_pr,
        repo_creator: object = github_repo,
        open_home: bool = False,
        resume: bool = False,
        home_options: dict | None = None,
    ) -> None:
        super().__init__()
        self._open_home_on_mount = open_home
        self._resume_on_mount = resume
        self._home_options = dict(home_options or {})
        self._closer = closer
        self._pr_opener = pr_opener
        self._repo_creator = repo_creator
        self.root = Path(root)
        self._docs = Path(docs) if docs is not None else None
        self._check = check
        self._export = export_pack
        self._opener = opener or (lambda path: subprocess.run(["open", str(path)], check=False))
        self._revealer = revealer or (lambda path: subprocess.run(["open", "-R", str(path)], check=False))
        self._exported: list[Path] = []
        self._review = review
        self._runner = runner
        self._approver = approver
        self._latest = latest
        self._editing: tuple[str, str] | None = None
        self._busy = False
        self._want_set, self._want_kind = set_slug, kind
        self.entry = ""
        self.key = ""
        self.refusal: str | None = None
        self.shown_text = ""
        self.findings_shown = ""
        self.history_picks: list[str] = []

    @property
    def docs(self) -> Path:
        if self._docs is None:
            try:
                self._docs = workspace.docs_root(self.root)
            except Exception:
                self._docs = self.root
        return self._docs

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Docs", id="docs-title"),
            Static("", id="docs-location"),
            Static("", id="docs-reason"),
            Horizontal(
                OptionList(id="docs-left"),
                OptionList(id="docs-middle"),
                VerticalScroll(
                    OptionList(id="docs-versions"),
                    Markdown("", id="docs-text"), Static("", id="docs-findings"), id="docs-right"
                ),
                id="docs-columns",
            ),
            Static("", id="docs-status"),
            Static("", id="docs-also"),
            Horizontal(*[Button(label, id=bid) for bid, label in _REVIEW], id="docs-review"),
            Horizontal(
                Button("Check", id="docs-check"),
                Button("Open file", id="docs-open"),
                Button("Close set", id="docs-close-set"),
                Button("Open pull request", id="docs-pr"),
                Button("Switch to it", id="docs-switch"),
                Button("Create GitHub repository", id="docs-github"),
                Button("History", id="docs-history"),
                Button("Export pack", id="docs-export"),
                Button("Reveal in Finder", id="docs-reveal"),
                Button("Close", id="docs-close"),
                id="docs-actions",
            ),
            id="docs-box",
        )

    def on_mount(self) -> None:
        self.watch(self.app, "app_focus", self._focus_changed)
        self.refresh_all()
        if self._want_set:
            self.select_entry(SET_PREFIX + self._want_set, self._want_kind)
        elif self.query_one("#docs-left", OptionList).option_count:
            first = next((r for r in left_rows(self.docs) if r.key), None)
            if first is not None:
                self.select_entry(first.key)
        if self._open_home_on_mount and self._want_set:
            self.open_home(self._want_set)
        elif self._resume_on_mount and self._want_set:
            slug, root = self._want_set, self.root
            self._work("Continuing…", lambda progress: self._runner.run(root, slug, progress=progress))

    def refresh_all(self) -> None:
        """Re-read the guard and the left column."""
        try:
            self.refusal = self._check(self.root)
        except Exception as error:  # an unreadable relay state must not hide the docs
            self.refusal = None
            self.query_one("#docs-status", Static).update(f"Could not check for a running relay: {error}")
        self.query_one("#docs-reason", Static).update(self.refusal or "")
        self.query_one("#docs-location", Static).update(library.location_line(self.docs, self.root))
        left = self.query_one("#docs-left", OptionList)
        left.clear_options()
        left.add_options([_option(r) for r in left_rows(self.docs)])
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.query_one("#docs-reveal", Button).display = bool(self._exported)
        for button_id in _ACTIONS:
            self.query_one(f"#{button_id}", Button).disabled = self.refusal is not None or not (
                self.entry and self.key
            )
        for button_id in _ALWAYS_ON:
            self.query_one(f"#{button_id}", Button).disabled = False
        if not (self.entry and self.key):
            for button_id in ("docs-history", "docs-export"):
                self.query_one(f"#{button_id}", Button).disabled = True
        shown: set[str] = set()
        if self.refusal is None and not self._busy and self.entry.startswith(SET_PREFIX) and self.key:
            shown = available_actions(
                self.docs, self._slug(), self.key, self._editing is not None
            )
        for button_id, _ in _REVIEW:
            self.query_one(f"#{button_id}", Button).display = button_id in shown
        self.query_one("#docs-approve", Button).disabled = self._prd_moved()
        wanted: set[str] = set()
        if self.refusal is None and not self._busy and self.entry.startswith(SET_PREFIX):
            wanted = set_actions(self.docs, self._slug())
        for button_id in _SET_ACTIONS:
            self.query_one(f"#{button_id}", Button).display = button_id in wanted

    def _prd_moved(self) -> bool:
        """True when the selected document is a PRD update the product PRD has moved past."""
        if not (self.entry.startswith(SET_PREFIX) and self.key == "prd"):
            return False
        try:
            found = docset.load(self.docs, self._slug())
        except docset.DocSetError:
            return False
        return _prd_update(self.docs, found, "prd") and bool(prd_moved_line(self.docs, found))

    def select_entry(self, entry: str, kind: str | None = None) -> None:
        self.entry = entry
        left = self.query_one("#docs-left", OptionList)
        for index in range(left.option_count):
            if left.get_option_at_index(index).id == entry:
                left.highlighted = index
                break
        rows = middle_rows(self.docs, entry, self._latest)
        middle = self.query_one("#docs-middle", OptionList)
        middle.clear_options()
        middle.add_options([_option(r) for r in rows])
        keys = [r.key for r in rows]
        self.select_document(kind if kind in keys else (keys[0] if keys else ""))

    def select_document(self, key: str) -> None:
        self.key = key
        self._hide_history()
        middle = self.query_one("#docs-middle", OptionList)
        for index in range(middle.option_count):
            if middle.get_option_at_index(index).id == key:
                middle.highlighted = index
                break
        self.show(document_text(self.docs, self.entry, key) if key else NOTHING)
        self._show_findings()

    def _hide_history(self) -> None:
        self.history_picks = []
        self.query_one("#docs-versions", OptionList).display = False

    def show_history(self) -> None:
        """Show versions and review log; the version list picks one or two to read or compare."""
        self.history_picks = []
        versions = self.query_one("#docs-versions", OptionList)
        versions.clear_options()
        found = history_versions(self.docs, self.entry, self.key)
        for number, _path in found:
            versions.add_option(Option(f"v{number}", id=f"v{number}"))
        versions.display = bool(found)
        self.show(history_text(self.docs, self.entry, self.key))

    def pick_version(self, number: str) -> None:
        """Toggle a version; a third pick drops the oldest pick."""
        if number in self.history_picks:
            self.history_picks.remove(number)
        else:
            self.history_picks = (self.history_picks + [number])[-2:]
        versions = self.query_one("#docs-versions", OptionList)
        for index in range(versions.option_count):
            name = versions.get_option_at_index(index).id
            mark = "● " if name[1:] in self.history_picks else ""
            versions.replace_option_prompt_at_index(index, f"{mark}{name}")
        self.show(history_text(self.docs, self.entry, self.key, tuple(self.history_picks)))

    def _show_findings(self) -> None:
        panel = self.query_one("#docs-findings", Static)
        self.findings_shown = ""
        if self.entry.startswith(SET_PREFIX) and self.key:
            try:
                found = docset.load(self.docs, self._slug())
            except docset.DocSetError:
                found = None
            if found is not None and found.document(self.key) is not None:
                self.findings_shown = "Findings\n" + findings_text(
                    _latest(self._latest, self.docs, found, self.key))
        panel.display = bool(self.findings_shown)
        panel.update(Text(self.findings_shown))

    def show(self, text: str) -> None:
        self.shown_text = text
        self.query_one("#docs-text", Markdown).update(text)
        self._sync_buttons()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id is None:
            return
        if event.option_list.id == "docs-left":
            self.select_entry(event.option_id)
        elif event.option_list.id == "docs-middle":
            self.select_document(event.option_id)
        elif event.option_list.id == "docs-versions":
            self.pick_version(event.option_id[1:])

    def _selected_path(self) -> Path | None:
        if self.entry == PRODUCT:
            name = prd.CHANGELOG if self.key == CHANGELOG_DOC else prd.PRD_FILE
            return self.docs / prd.PRODUCT_DIR / name
        if self.entry.startswith(SET_PREFIX):
            try:
                found = docset.load(self.docs, self.entry[len(SET_PREFIX):])
            except docset.DocSetError:
                return None
            doc = found.document(self.key)
            if doc is None:
                return None
            if doc["kind"] == "plan":
                return docset.plan_file(self.docs, found.slug)
            return self.docs / doc["path"]
        if self.entry.startswith(PLAN_PREFIX):
            for plan in library.earlier_plans(self.docs):
                if plan.slug == self.entry[len(PLAN_PREFIX):]:
                    return {"plan": plan.plan, "tests": plan.test_plan, "source": plan.source}.get(self.key)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "docs-close":
            self.dismiss(None)
        elif button_id == "docs-history":
            self.show_history()
        elif button_id == "docs-export":
            self._start_export()
        elif button_id == "docs-reveal":
            if self._exported:
                self._revealer(self._exported[0])
        elif button_id in _SET_ACTIONS:
            self._set_action(button_id)
        elif button_id in _ACTIONS and self.refusal is not None:
            return
        elif button_id == "docs-check":
            self._run_check()
        elif button_id == "docs-open":
            path = self._selected_path()
            if path is not None and path.is_file():
                self._opener(path)
        elif button_id in dict(_REVIEW):
            self._review_action(button_id)

    def _slug(self) -> str:
        return self.entry[len(SET_PREFIX):]

    def _review_action(self, button_id: str) -> None:
        if not self.entry.startswith(SET_PREFIX) or not self.key or self._busy:
            return
        slug, kind, root = self._slug(), self.key, self.root
        review = self._review
        if button_id == "docs-approve":
            self._work("Approving…", lambda progress: self._approve(root, slug, kind, progress))
        elif button_id in ("docs-diff", "docs-whole"):
            found = docset.load(self.docs, slug)
            view = "diff" if button_id == "docs-diff" else "whole"
            self.show(prd_update_text(self.docs, found, view))
        elif button_id == "docs-redo":
            self._work("Redoing…", lambda progress: review.redo(root, slug, kind, progress=progress))
        elif button_id == "docs-review-again":
            self._work("Reviewing again…", lambda progress: review.review_again(
                root, slug, kind, progress=progress))
        elif button_id == "docs-stop":
            self._work("Stopping…", lambda progress: review.stop(root, slug))
        elif button_id == "docs-auto":
            self._work("Running the rest on Auto…", lambda progress: self._auto(root, slug, kind, progress))
        elif button_id == "docs-resume":
            self._work("Resuming…", lambda progress: self._runner.run(root, slug, progress=progress))
        elif button_id == "docs-changes":
            latest = _latest(self._latest, self.docs, docset.load(self.docs, slug), kind)
            form = ReviewForm(
                "What should change?",
                section_choices(self.docs, slug, kind),
                list(getattr(latest, "findings", None) or []),
            )

            def asked(result) -> None:
                if result:
                    comments, section = result
                    self._work("Asking for changes…", lambda progress: review.ask_for_changes(
                        root, slug, kind, comments, section=section, progress=progress))

            self.app.push_screen(form, asked)
        elif button_id == "docs-answer":
            def answered(result) -> None:
                if result:
                    self._work("Sending answers…", lambda progress: review.answer_questions(
                        root, slug, kind, result[0], progress=progress))

            self.app.push_screen(ReviewForm("Your answers"), answered)
        elif button_id == "docs-edit":
            path = self._selected_path()
            if path is not None and path.is_file():
                self._editing = (slug, kind)
                self._opener(path)
                self._sync_buttons()
        elif button_id == "docs-finished":
            self.finish_editing()

    def _set_action(self, button_id: str) -> None:
        if button_id == "docs-switch" and self.entry.startswith(SET_PREFIX):
            slug = self._slug()
            moved = library._moved_to(self.docs, slug)
            if moved:
                self.dismiss(HomeResult(slug, Path(moved), True))
            return
        if not self.entry.startswith(SET_PREFIX) or self._busy or self.refusal is not None:
            return
        slug, root, docs = self._slug(), self.root, self.docs
        if button_id == "docs-close-set":
            self._work("Closing…", lambda progress: self._close(root, slug))
            return
        if button_id == "docs-github":
            self._create_github(root, slug)
            return
        try:
            branch = workspace._current_branch(root)
        except Exception:
            branch = "the branch"

        def asked(yes) -> None:
            if yes:
                self._work("Opening the pull request…", lambda progress: self._open_pr(root, docs, slug))

        self.app.push_screen(ConfirmForm(f"Push {branch} to origin and open a pull request?"), asked)

    def _create_github(self, root: Path, slug: str) -> None:
        """Ask, then create the repository for this set. A refusal is shown, never raised."""
        creator = self._repo_creator
        try:
            owner = creator.default_owner(root) or ""
        except Exception:
            owner = ""
        name = root.name

        def asked(yes) -> None:
            if yes:
                self._work("Creating the GitHub repository…", lambda progress: self._make_repo(
                    root, slug, owner, name))

        self.app.push_screen(ConfirmForm(creator.describe(owner or "<owner>", name, True)), asked)

    def _make_repo(self, root: Path, slug: str, owner: str, name: str) -> object:
        url = self._repo_creator.create_repo(root, owner=owner, name=name, private=True, slug=slug)
        return SimpleNamespace(state="github", message=f"GitHub repository created: {url}")

    def _close(self, root: Path, slug: str) -> object:
        result = self._closer(root, slug)
        if getattr(result, "error", ""):
            raise RuntimeError(result.error)
        version = getattr(result, "version", "")
        what = f"released v{version}" if version else "built"
        return SimpleNamespace(state=getattr(result, "state", "") or "closed", message=f"Closed: {what}.")

    def _open_pr(self, root: Path, docs: Path, slug: str) -> object:
        url = self._pr_opener(root, docs, slug)
        return SimpleNamespace(state="pr", message=f"Pull request: {url}")

    def _approve(self, root: Path, slug: str, kind: str, progress) -> object:
        self._review.approve(root, slug, kind, approver=self._approver)
        if docset.load(self.docs, slug).mode == docset.Mode.HUMAN.value:
            return self._runner.run(root, slug, progress=progress)
        return None

    def _auto(self, root: Path, slug: str, kind: str, progress) -> object:
        found = docset.load(self.docs, slug)
        doc = found.document(kind)
        if doc is not None and doc["status"] == docset.Status.IN_REVIEW.value:
            self._review.approve(root, slug, kind, approver=self._approver)
        self._review.set_mode(root, slug, docset.Mode.AUTO.value)
        return self._runner.run(root, slug, progress=progress)

    def _focus_changed(self, focused: bool) -> None:
        if focused and self._editing is not None:
            self.finish_editing()

    def finish_editing(self) -> None:
        """Add the hand-edited file as a new version, when it changed."""
        if self._editing is None:
            return
        slug, kind = self._editing
        self._editing = None
        root = self.root
        self._work("Saving your edit…", lambda progress: self._review.edited(
            root, slug, kind, editor_name=self._approver))

    def open_home(self, slug: str) -> None:
        """Ask where the project lives, then apply the choice and carry on."""
        screen = ProjectHomeScreen(self.root, slug, docs=self.docs, **self._home_options)

        def chosen(choice: HomeChoice | None) -> None:
            if choice is None:
                self.query_one("#docs-status", Static).update(
                    "Choose where this project lives, then Resume.")
                return
            self._apply_home(slug, choice)

        self.app.push_screen(screen, chosen)

    def _apply_home(self, slug: str, choice: HomeChoice) -> None:
        root = self.root
        try:
            agents = home_agents(docset.load(self.docs, slug))
        except docset.DocSetError:
            agents = ["claude"]

        def apply(progress) -> object:
            def say(line: str) -> None:
                progress(f"home · {line}")

            say("starting")
            target = Path(self._runner.choose_home(
                root, slug, choice=choice.choice,
                parent=choice.parent, folder=choice.folder or None,
                name=choice.name or None, agents=agents, progress=say))
            changed = target.resolve() != root.resolve()
            if not changed and not choice.github:
                return self._runner.run(root, slug, progress=progress)
            return HomeResult(slug, target, changed, choice if choice.github else None)

        def then(result: object) -> None:
            if isinstance(result, HomeResult):
                self.dismiss(result)

        self._work("home · starting", apply, then=then)

    def _work(self, label: str, call: Callable[[Callable[[str], None]], object],
              then: Callable[[object], None] | None = None) -> None:
        """Run `call(progress)` in a thread worker and show its outcome."""
        status = self.query_one("#docs-status", Static)
        also = self.query_one("#docs-also", Static)
        status.update(label)
        also.update("")
        self._busy = True
        self._sync_buttons()

        def progress(text: str) -> None:
            self.app.call_from_thread(status.update, str(text))

        def done(result: object, error: str) -> None:
            self._busy = False
            keep = self.key
            self.refresh_all()
            self.select_entry(self.entry, keep)
            if error:
                status.update(error)
                return
            if isinstance(result, HomeResult):
                status.update("Project home ready.")
            else:
                status.update(_outcome_text(result) or "Done.")
            if then is not None:
                then(result)
            if getattr(result, "state", "") == "waiting_for_home" and self.entry.startswith(SET_PREFIX):
                self.open_home(self.entry[len(SET_PREFIX):])
            if isinstance(result, list) and result:
                also.update("Also changed: " + ", ".join(result))

        def run() -> None:
            result, error = None, ""
            try:
                result = call(progress)
            except Exception as exc:
                error = str(exc) or type(exc).__name__
            self.app.call_from_thread(done, result, error)

        self.run_worker(run, thread=True, exclusive=True, group="docs-review")

    def _run_check(self) -> None:
        if not self.entry.startswith(SET_PREFIX):
            self.query_one("#docs-status", Static).update("Check works on a document set.")
            return
        try:
            found = docset.load(self.docs, self.entry[len(SET_PREFIX):])
            marked = docset.refresh_out_of_date(self.docs, found)
        except docset.DocSetError as error:
            self.query_one("#docs-status", Static).update(str(error))
            return
        self.query_one("#docs-status", Static).update(
            f"{len(marked)} document(s) now out of date." if marked else "Nothing is out of date."
        )
        keep = self.key
        self.select_entry(self.entry, keep)

    def _start_export(self) -> None:
        if not self.entry.startswith(SET_PREFIX):
            self.query_one("#docs-status", Static).update("Export works on a document set.")
            return
        slug = self.entry[len(SET_PREFIX):]
        status = self.query_one("#docs-status", Static)
        status.update("Exporting…")
        self._exported = []
        self.query_one("#docs-reveal", Button).display = False

        def work() -> tuple[str, list[Path]]:
            try:
                result = self._export(self.docs, slug)
            except Exception as error:
                return f"Export failed: {error}", []
            files = [Path(f) for f in getattr(result, "files", [])]
            notes = [str(n) for n in getattr(result, "notes", [])]
            head = "Exported: " + ", ".join(str(f) for f in files) if files else "Nothing was exported."
            return "\n".join([head, *notes]), files

        def done(outcome: tuple[str, list[Path]]) -> None:
            text, files = outcome
            status.update(Text(text))
            self._exported = files
            self.query_one("#docs-reveal", Button).display = bool(files)

        def run() -> None:
            self.app.call_from_thread(done, work())

        self.run_worker(run, thread=True, exclusive=True, group="docs-export")

    def action_close(self) -> None:
        self.dismiss(None)


@dataclass(frozen=True)
class HomeChoice:
    """What the Project home screen collected."""

    choice: str  # "new" or "here"
    parent: Path | None = None
    folder: str = ""
    name: str = ""
    github: bool = False
    private: bool = True
    owner: str = ""
    repo: str = ""  # the GitHub repository name


@dataclass(frozen=True)
class HomeResult:
    """Docs closes with this when the console must switch repository or ask about GitHub."""

    slug: str
    root: Path
    changed: bool
    github: HomeChoice | None = None


def home_agents(found: object) -> list[str]:
    names: set[str] = set()
    for value in (getattr(found, "roles", None) or {}).values():
        for item in value if isinstance(value, (list, tuple)) else [value]:
            if item:
                names.add(str(item))
    return sorted(names) or ["claude"]


def _pick_folder() -> Path | None:
    from whyline.console import agents_screens, mac_input

    return agents_screens._first_folder(mac_input.pick_files())


SUGGESTING = "Suggesting names…"
OWN_NAME = "My own name"


class ProjectHomeScreen(ModalScreen):
    """Where should this project live? Dismisses with a HomeChoice, or None on Cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ProjectHomeScreen { align: center middle; }
    #home-box { width: 80%; height: 90%; border: round $accent; background: $surface; padding: 1 2; }
    #home-names { height: auto; max-height: 8; }
    #home-path { height: auto; }
    #home-github-fix { height: auto; color: $warning; }
    #home-buttons { height: auto; }
    """

    def __init__(
        self,
        root: Path | str,
        slug: str,
        *,
        docs: Path | None = None,
        home: object = home_mod,
        github: object = github_repo,
        pick_folder_fn: Callable[[], Path | None] | None = None,
    ) -> None:
        super().__init__()
        self.root = Path(root)
        self.slug = slug
        self._docs = Path(docs) if docs is not None else self.root
        self._home = home
        self._github = github
        self._pick = pick_folder_fn or _pick_folder
        self.set_name = slug
        self.agent = "claude"
        self.choice = ""
        self.ideas: list = []
        self.suggesting = False
        self._suggested = False
        self.project = ""
        self.folder = ""
        self.save_in = Path.home()
        self.refusal: str | None = None
        self.path_shown = ""
        self.github_fix: str | None = None
        self.github_on = False
        self.private = True
        self.owner = ""

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Project home", id="home-title"),
            Static("Where should this project live?"),
            RadioSet(
                RadioButton("Create a new folder", id="home-new"),
                RadioButton(f"Use this repository ({self.root.name})", id="home-here"),
                id="home-where",
            ),
            VerticalScroll(
                Vertical(
                    OptionList(id="home-names"),
                    Input(placeholder="Project name", id="home-own"),
                    Input(placeholder="Folder name", id="home-folder"),
                    Static("", id="home-parent"),
                    Button("Choose folder…", id="home-choose"),
                    id="home-newbox",
                ),
                Static("", id="home-path"),
                Checkbox("Create GitHub repository", False, id="home-github"),
                Static("", id="home-github-fix"),
                Vertical(
                    RadioSet(
                        RadioButton("Private", True, id="home-private"),
                        RadioButton("Public", id="home-public"),
                        id="home-visibility",
                    ),
                    Input(placeholder="Owner", id="home-owner"),
                    id="home-gh-options",
                ),
            ),
            Horizontal(
                Button("Continue", id="home-continue", variant="primary"),
                Button("Cancel", id="home-cancel"),
                id="home-buttons",
            ),
            id="home-box",
        )

    def on_mount(self) -> None:
        try:
            found = docset.load(self._docs, self.slug)
            self.set_name = found.name
            self.agent = str(found.roles.get("writer") or "claude")
        except docset.DocSetError:
            pass
        try:
            fresh = bool(self._home.is_fresh(self.root))
        except Exception:
            fresh = False
        try:
            self.save_in = Path(self._home.last_parent())
        except Exception:
            pass
        self.project = self.set_name
        self.folder = self._home.folder_name(self.project)
        self._load_github()
        self.choose_where("here" if fresh else "new")

    def _load_github(self) -> None:
        box = self.query_one("#home-github", Checkbox)
        try:
            self.github_fix = self._github.gh_ready(self.root)
        except Exception as error:
            self.github_fix = str(error) or "GitHub is not ready."
        if self.github_fix:
            box.disabled = True
            self.query_one("#home-github-fix", Static).update(self.github_fix)
            return

        def find() -> None:
            try:
                owner = self._github.default_owner(self.root) or ""
            except Exception:
                owner = ""
            self.app.call_from_thread(self._set_owner, owner)

        self.run_worker(find, thread=True, group="home-owner")

    def _set_owner(self, owner: str) -> None:
        if not self.owner:
            self.owner = owner
            self.query_one("#home-owner", Input).value = owner
        self._sync()

    def choose_where(self, choice: str) -> None:
        self.choice = choice
        for button in self.query_one("#home-where", RadioSet).query(RadioButton):
            want = button.id == ("home-new" if choice == "new" else "home-here")
            if button.value != want:
                button.value = want
        self.query_one("#home-newbox").display = choice == "new"
        if choice == "new" and not self._suggested:
            self._suggested = True
            self._start_suggesting()
        self._fill_names()
        self._sync()

    def _start_suggesting(self) -> None:
        self.suggesting = True
        root = self.root

        def work() -> None:
            try:
                found = docset.load(self._docs, self.slug)
                ideas = list(self._home.suggest_names(root, found, agent=self.agent))
            except Exception:
                ideas = []
            self.app.call_from_thread(self._suggested_names, ideas)

        self.run_worker(work, thread=True, group="home-names")

    def _suggested_names(self, ideas: list) -> None:
        self.suggesting = False
        self.ideas = ideas
        self._fill_names()
        if ideas:
            self.choose_name(0)
        else:
            self._sync()

    def _fill_names(self) -> None:
        names = self.query_one("#home-names", OptionList)
        names.clear_options()
        if self.suggesting:
            names.add_option(Option(SUGGESTING, id="wait", disabled=True))
        for index, idea in enumerate(self.ideas):
            names.add_option(Option(f"{idea.name} — {idea.reason}", id=f"idea:{index}"))
        names.add_option(Option(OWN_NAME, id="own"))

    def choose_name(self, index: int | None) -> None:
        """Pick suggestion `index`, or My own name with None."""
        own = self.query_one("#home-own", Input)
        if index is None:
            own.display = True
            self._set_name(own.value.strip())
            return
        own.display = False
        self._set_name(self.ideas[index].name, self.ideas[index].folder)

    def _set_name(self, name: str, folder: str | None = None) -> None:
        self.project = name
        self.folder = folder if folder is not None else (
            self._home.folder_name(name) if name else "")
        self.query_one("#home-folder", Input).value = self.folder
        self._sync()

    def _repo_name(self) -> str:
        return self.folder.strip() if self.choice == "new" else self.root.name

    def _sync(self) -> None:
        self.query_one("#home-parent", Static).update(f"Save in: {self.save_in}")
        refusal: str | None = None
        if self.choice == "new":
            folder = self.folder.strip()
            if not self.project:
                refusal = "Give the project a name."
            elif not folder:
                refusal = "Give the folder a name."
            else:
                try:
                    refusal = self._home.check_target(self.root, self.save_in, folder)
                except Exception as error:
                    refusal = str(error) or "That folder can't be used."
            shown = refusal or str(self.save_in / folder)
        else:
            shown = f"The project stays in {self.root}."
        self.refusal = refusal
        self.path_shown = shown
        self.query_one("#home-path", Static).update(shown)
        self.query_one("#home-gh-options").display = self.github_on
        self.query_one("#home-continue", Button).disabled = (
            refusal is not None or (self.github_on and not self.owner.strip()))

    def set_github(self, on: bool) -> None:
        self.github_on = bool(on) and not self.github_fix
        self._sync()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        button_id = event.pressed.id
        if button_id in ("home-new", "home-here"):
            choice = "new" if button_id == "home-new" else "here"
            if choice != self.choice:
                self.choose_where(choice)
        elif button_id in ("home-private", "home-public"):
            self.private = button_id == "home-private"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        option_id = event.option_id or ""
        if option_id == "own":
            self.choose_name(None)
        elif option_id.startswith("idea:"):
            self.choose_name(int(option_id.split(":", 1)[1]))

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        self.set_github(event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if event.input.id == "home-own":
            self._set_name(event.value.strip())
        elif event.input.id == "home-folder":
            self.folder = event.value
            self._sync()
        elif event.input.id == "home-owner":
            self.owner = event.value.strip()
            self._sync()

    def choose_parent(self, path: Path | str) -> None:
        self.save_in = Path(path).expanduser()
        self._sync()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "home-cancel":
            self.dismiss(None)
        elif event.button.id == "home-choose":
            self._choose_folder()
        elif event.button.id == "home-continue":
            self.submit()

    def _choose_folder(self) -> None:
        def work() -> None:
            try:
                picked = self._pick()
            except Exception as error:
                self.app.call_from_thread(
                    self.query_one("#home-path", Static).update, f"Could not open the picker: {error}")
                return
            if picked:
                self.app.call_from_thread(self.choose_parent, picked)

        self.run_worker(work, thread=True, group="home-pick")

    def submit(self) -> None:
        if self.query_one("#home-continue", Button).disabled:
            return
        new = self.choice == "new"
        self.dismiss(HomeChoice(
            choice=self.choice,
            parent=self.save_in if new else None,
            folder=self.folder.strip() if new else "",
            name=self.project if new else self.set_name,
            github=self.github_on,
            private=self.private,
            owner=self.owner.strip(),
            repo=self._repo_name(),
        ))

    def action_cancel(self) -> None:
        self.dismiss(None)


class DocsTab(Vertical):
    """Read-only view of the document set that owns the active plan, for the Files pane."""

    NO_SET = "This plan has no document set."
    DEFAULT_CSS = """
    DocsTab { height: 1fr; min-height: 0; }
    DocsTab OptionList { height: auto; max-height: 8; }
    DocsTab VerticalScroll { height: 1fr; min-height: 0; }
    DocsTab Button { height: 1; min-height: 1; border: none; padding: 0 1; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.docs: Path | None = None
        self.slug = ""
        self.key = ""
        self.shown_text = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="file-docs-status", markup=False)
        yield OptionList(id="file-docs-list")
        yield VerticalScroll(Static("", id="file-docs-text", markup=False))
        yield Button("Open in Docs", id="file-docs-open")

    def show_set(self, owner: tuple[Path, str] | None) -> None:
        """Show the set at (docs checkout, slug), or the no-set message."""
        options = self.query_one("#file-docs-list", OptionList)
        options.clear_options()
        self.key = ""
        opener = self.query_one("#file-docs-open", Button)
        status = self.query_one("#file-docs-status", Static)
        if owner is None:
            self.docs, self.slug = None, ""
            status.update(self.NO_SET)
            self._show_text("")
            opener.display = False
            return
        self.docs, self.slug = owner
        rows = middle_rows(self.docs, SET_PREFIX + self.slug)
        status.update(self.slug)
        opener.display = True
        options.add_options([_option(r) for r in rows])
        if rows:
            self.select_document(rows[0].key)
        else:
            self._show_text(NOTHING)

    def select_document(self, key: str) -> None:
        if self.docs is None:
            return
        self.key = key
        self._show_text(document_text(self.docs, SET_PREFIX + self.slug, key))

    def _show_text(self, text: str) -> None:
        self.shown_text = text
        self.query_one("#file-docs-text", Static).update(text)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id:
            self.select_document(str(event.option.id))
