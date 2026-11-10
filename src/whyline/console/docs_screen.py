"""The Docs screen: the product PRD, document sets and earlier plans in three
columns (what, which document, its text). It reads the docs checkout; while a
relay runs in that checkout every action except History and Export is off."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from whyline.sdlc import docset, export, guard, library, workspace
from whyline.sdlc import product as prd

PRODUCT = "product"
SET_PREFIX = "set:"
PLAN_PREFIX = "plan:"
PRD_DOC = "prd"
CHANGELOG_DOC = "changelog"
NOTHING = "Nothing to show yet."
_ACTIONS = ("docs-check", "docs-open")
_ALWAYS_ON = ("docs-history", "docs-export", "docs-close")


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


def middle_rows(docs: Path, entry: str) -> list[Row]:
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
            label = (
                f"{title} · {docset.version_label(found, doc, docs)} · "
                f"{status.label} · {_approval(doc)}"
            )
            reason = ""
            if status is docset.Status.OUT_OF_DATE:
                reason = doc.get("out_of_date_reason") or "An earlier document changed."
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
        return (docset._current_text(docs, found, doc) or NOTHING) if doc else NOTHING
    if entry.startswith(PLAN_PREFIX):
        slug = entry[len(PLAN_PREFIX):]
        for plan in library.earlier_plans(docs):
            if plan.slug == slug:
                path = {"plan": plan.plan, "tests": plan.test_plan, "source": plan.source}.get(key)
                return _read(path)
    return NOTHING


def history_text(docs: Path, entry: str, key: str) -> str:
    """The stored versions of the selected document, as Markdown."""
    if entry == PRODUCT:
        folder, pattern = docs / prd.PRODUCT_DIR / prd.HISTORY_DIR, "prd-v*.md"
    elif entry.startswith(SET_PREFIX):
        folder = docs / docset.SDLC_DIR / entry[len(SET_PREFIX):] / docset.HISTORY_DIR
        pattern = f"{key}-v*.md"
    else:
        return "Earlier plans keep no version history."
    files = sorted(folder.glob(pattern)) if folder.is_dir() else []
    if not files:
        return "No earlier versions are stored."
    return "# History\n\n" + "\n".join(f"- `{f.name}`" for f in files) + "\n"


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
    #docs-reason { height: auto; color: $warning; }
    #docs-status { height: auto; }
    #docs-actions { height: auto; }
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
    ) -> None:
        super().__init__()
        self.root = Path(root)
        self._docs = Path(docs) if docs is not None else None
        self._check = check
        self._export = export_pack
        self._opener = opener or (lambda path: subprocess.run(["open", str(path)], check=False))
        self._want_set, self._want_kind = set_slug, kind
        self.entry = ""
        self.key = ""
        self.refusal: str | None = None
        self.shown_text = ""

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
            Static("", id="docs-reason"),
            Horizontal(
                OptionList(id="docs-left"),
                OptionList(id="docs-middle"),
                VerticalScroll(Markdown("", id="docs-text"), id="docs-right"),
                id="docs-columns",
            ),
            Static("", id="docs-status"),
            Horizontal(
                Button("Check", id="docs-check"),
                Button("Open file", id="docs-open"),
                Button("History", id="docs-history"),
                Button("Export", id="docs-export"),
                Button("Close", id="docs-close"),
                id="docs-actions",
            ),
            id="docs-box",
        )

    def on_mount(self) -> None:
        self.refresh_all()
        if self._want_set:
            self.select_entry(SET_PREFIX + self._want_set, self._want_kind)
        elif self.query_one("#docs-left", OptionList).option_count:
            first = next((r for r in left_rows(self.docs) if r.key), None)
            if first is not None:
                self.select_entry(first.key)

    def refresh_all(self) -> None:
        """Re-read the guard and the left column."""
        try:
            self.refusal = self._check(self.root)
        except Exception as error:  # an unreadable relay state must not hide the docs
            self.refusal = None
            self.query_one("#docs-status", Static).update(f"Could not check for a running relay: {error}")
        self.query_one("#docs-reason", Static).update(self.refusal or "")
        left = self.query_one("#docs-left", OptionList)
        left.clear_options()
        left.add_options([_option(r) for r in left_rows(self.docs)])
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        for button_id in _ACTIONS:
            self.query_one(f"#{button_id}", Button).disabled = self.refusal is not None or not (
                self.entry and self.key
            )
        for button_id in _ALWAYS_ON:
            self.query_one(f"#{button_id}", Button).disabled = False
        if not (self.entry and self.key):
            for button_id in ("docs-history", "docs-export"):
                self.query_one(f"#{button_id}", Button).disabled = True

    def select_entry(self, entry: str, kind: str | None = None) -> None:
        self.entry = entry
        left = self.query_one("#docs-left", OptionList)
        for index in range(left.option_count):
            if left.get_option_at_index(index).id == entry:
                left.highlighted = index
                break
        rows = middle_rows(self.docs, entry)
        middle = self.query_one("#docs-middle", OptionList)
        middle.clear_options()
        middle.add_options([_option(r) for r in rows])
        keys = [r.key for r in rows]
        self.select_document(kind if kind in keys else (keys[0] if keys else ""))

    def select_document(self, key: str) -> None:
        self.key = key
        middle = self.query_one("#docs-middle", OptionList)
        for index in range(middle.option_count):
            if middle.get_option_at_index(index).id == key:
                middle.highlighted = index
                break
        self.show(document_text(self.docs, self.entry, key) if key else NOTHING)

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
            self.show(history_text(self.docs, self.entry, self.key))
        elif button_id == "docs-export":
            self._start_export()
        elif button_id in _ACTIONS and self.refusal is not None:
            return
        elif button_id == "docs-check":
            self._run_check()
        elif button_id == "docs-open":
            path = self._selected_path()
            if path is not None and path.is_file():
                self._opener(path)

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

        def work() -> str:
            try:
                result = self._export(self.docs, slug)
            except Exception as error:
                return f"Export failed: {error}"
            files = ", ".join(str(f) for f in getattr(result, "files", []))
            return "Exported: " + files if files else "Nothing was exported."

        def done(text: str) -> None:
            status.update(text)

        def run() -> None:
            self.app.call_from_thread(done, work())

        self.run_worker(run, thread=True, exclusive=True, group="docs-export")

    def action_close(self) -> None:
        self.dismiss(None)
