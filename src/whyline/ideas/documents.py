"""Word and PDF copies of a Markdown idea document.

Both files land in ``paths.documents_dir()``, named after the Markdown
file. Word comes from ``whyline.agents.convert.to_docx``. PDF is the same
HTML passed to macOS ``cupsfilter``. No new dependency: when PDF cannot be
made, Word still goes out and ``notes`` says so.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from whyline.agents import convert
from whyline.ideas import paths, store

# cupsfilter writes the converted document to stdout. There is no output-path
# flag, and a shell redirect is not used.
CUPSFILTER = "/usr/sbin/cupsfilter"
_TIMEOUT_SECONDS = 60
_FORMATS = frozenset({"word", "pdf", "both"})
_KV_KEY = "doc_formats"

PDF_NOTE = "PDF not available on this machine; sent Word only"
BOTH_FAILED_NOTE = "Word and PDF could not be written; sent the Markdown file."
WORD_FAILED_NOTE = "Word could not be written; sent the Markdown file."
WORD_FAILED_PDF_NOTE = "Word could not be written; sent PDF only."
PDF_FAILED_NOTE = "PDF not available on this machine; sent the Markdown file."


@dataclass(frozen=True)
class Exported:
    docx: Path | None
    pdf: Path | None
    notes: list[str]


def export(md_path, *, formats=None, run=subprocess.run) -> Exported:
    """Write the requested copies of ``md_path``.

    ``formats`` is ``word``, ``pdf``, or ``both``. When it is omitted, the
    ``doc_formats`` kv value is used, and a missing or unrecognised value
    means ``both``. ``run`` is ``subprocess.run`` in production; tests pass
    a fake cupsfilter. Callers send the Markdown file when both paths are
    ``None``.
    """
    md_path = Path(md_path)
    chosen = _resolve_formats(formats)
    folder = paths.documents_dir()
    stem = md_path.stem
    docx = (
        _word(md_path, folder / f"{stem}.docx")
        if chosen in ("word", "both")
        else None
    )
    pdf = (
        _pdf(md_path, folder / f"{stem}.pdf", run)
        if chosen in ("pdf", "both")
        else None
    )
    return Exported(docx=docx, pdf=pdf, notes=_notes(chosen, docx, pdf))


def _resolve_formats(formats: str | None) -> str:
    if formats is None:
        formats = _stored_formats()
    if formats not in _FORMATS:
        raise ValueError(f"formats must be word, pdf, or both, not {formats!r}")
    return formats


def _stored_formats() -> str:
    conn = store.connect()
    try:
        row = conn.execute(
            "SELECT value FROM kv WHERE key = ?", (_KV_KEY,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return "both"
    value = row["value"]
    if isinstance(value, str) and value in _FORMATS:
        return value
    return "both"


def _word(md_path: Path, out: Path) -> Path | None:
    made = convert.to_docx(md_path, out)
    if made is None or not made.is_file() or made.stat().st_size == 0:
        out.unlink(missing_ok=True)
        return None
    return made


def _pdf(md_path: Path, out: Path, run) -> Path | None:
    try:
        html = convert.to_html(md_path.read_text(encoding="utf-8"))
    except OSError:
        out.unlink(missing_ok=True)
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="whyline-pdf-") as tmp:
            page = Path(tmp) / f"{md_path.stem}.html"
            page.write_text(html, encoding="utf-8")
            completed = run(
                [CUPSFILTER, "-i", "text/html", "-m", "application/pdf", str(page)],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=_TIMEOUT_SECONDS,
                shell=False,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        out.unlink(missing_ok=True)
        return None
    stdout = getattr(completed, "stdout", None)
    code = getattr(completed, "returncode", 1)
    if code != 0 or not isinstance(stdout, (bytes, bytearray)) or len(stdout) == 0:
        out.unlink(missing_ok=True)
        return None
    try:
        out.write_bytes(stdout)
    except OSError:
        out.unlink(missing_ok=True)
        return None
    if not out.is_file() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        return None
    return out


def _notes(chosen: str, docx: Path | None, pdf: Path | None) -> list[str]:
    want_word = chosen in ("word", "both")
    want_pdf = chosen in ("pdf", "both")
    if want_word and want_pdf:
        if docx is not None and pdf is not None:
            return []
        if docx is not None:
            return [PDF_NOTE]
        if pdf is not None:
            return [WORD_FAILED_PDF_NOTE]
        return [BOTH_FAILED_NOTE]
    if want_word and docx is None:
        return [WORD_FAILED_NOTE]
    if want_pdf and pdf is None:
        return [PDF_FAILED_NOTE]
    return []
