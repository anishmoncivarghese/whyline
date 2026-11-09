"""Export a document set as one Word file and one PDF in a downloads folder."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from whyline.agents import convert
from whyline.ideas import documents
from whyline.sdlc import docset as docset_mod, product

_RULE = "\n\n---\n\n"


@dataclass
class ExportResult:
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def default_out_dir() -> Path:
    return Path.home() / "Downloads"


def _read(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return docset_mod.strip_header(path.read_text(encoding="utf-8")).strip()
    except OSError:
        return None


def _prd_section(root: Path, found: docset_mod.DocSet, doc: dict, notes: list[str]) -> str | None:
    """The base product PRD with the set's changed sections, or None to use the set's own text."""
    if found.prd_mode != docset_mod.PrdMode.UPDATE.value:
        return None
    version = doc.get("based_on_prd") or doc.get("based_on")
    if not version:
        return None
    base = _read(root / product.PRODUCT_DIR / product.HISTORY_DIR / f"prd-v{version}.md")
    if base is None:
        notes.append(f"Product PRD v{version} is not in history; the set's own PRD is used.")
        return None
    mine = _read(root / doc["path"])
    parts = [f"# Product PRD v{version}", "", product.body(base).strip()]
    if mine is not None:
        wanted = set(product.changed_sections(product.body(base), mine))
        changed = [(name, text) for name, text in product._split(mine) if name in wanted]
        if changed:
            parts += ["", "## Changed sections in this set"]
            for name, text in changed:
                parts += ["", f"### {name}", "", text]
    return "\n".join(parts)


def build_markdown(root: Path, found: docset_mod.DocSet, notes: list[str]) -> str:
    root = Path(root)
    sections: list[str] = []
    cover = _read(root / docset_mod.SDLC_DIR / found.slug / docset_mod.INDEX)
    if cover is None:
        notes.append("index.md is missing; the pack has no cover.")
        cover = f"# {found.name}"
    sections.append(cover)
    for doc in found.documents:
        kind = doc["kind"]
        label = kind.replace("-", " ").capitalize()
        if kind == "plan":
            for tests, title in ((False, "Plan"), (True, "Test plan")):
                text = _read(docset_mod.plan_file(root, found.slug, tests=tests))
                if text is None:
                    notes.append(f"{title} is missing; skipped.")
                else:
                    sections.append(text)
            continue
        text = None
        if kind == "prd":
            text = _prd_section(root, found, doc, notes)
        if text is None:
            text = _read(root / doc["path"])
        if text is None:
            notes.append(f"{label} is missing; skipped.")
            continue
        sections.append(text)
    log = _read(root / docset_mod.SDLC_DIR / found.slug / docset_mod.REVIEW_LOG)
    if log is None:
        notes.append("Review log is missing; skipped.")
    else:
        sections.append("# Review log\n\n" + log)
    return _RULE.join(sections) + "\n"


def export_pack(
    root: Path,
    slug: str,
    out_dir: Path | None = None,
    *,
    run=subprocess.run,
) -> ExportResult:
    """Write `<slug>-docs.docx` and `<slug>-docs.pdf` into `out_dir` (default ~/Downloads)."""
    root = Path(root)
    found = docset_mod.load(root, slug)
    out = Path(out_dir) if out_dir is not None else default_out_dir()
    out.mkdir(parents=True, exist_ok=True)
    result = ExportResult()
    markdown = build_markdown(root, found, result.notes)
    with tempfile.TemporaryDirectory(prefix="whyline-export-") as tmp:
        md_path = Path(tmp) / f"{slug}-docs.md"
        md_path.write_text(markdown, encoding="utf-8")
        word = convert.to_docx(md_path, out / f"{slug}-docs.docx")
        if word is not None and word.is_file() and word.stat().st_size > 0:
            result.files.append(word)
        else:
            result.notes.append("Word could not be written.")
        pdf_path = out / f"{slug}-docs.pdf"
        pdf = documents.render_html(convert.to_html(markdown), pdf_path, run=run)
        if pdf.route is None or not pdf_path.is_file():
            pdf_path.unlink(missing_ok=True)
            result.notes.append(documents.PDF_NOTE.replace("; sent Word only", "."))
        else:
            result.files.append(pdf_path)
            if pdf.route == "plain":
                result.notes.append(documents.PLAIN_TEXT_NOTE)
    return result
