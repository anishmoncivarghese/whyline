"""Word and PDF copies of a Markdown idea document.

Both files land in ``paths.documents_dir()``, named after the Markdown
file. Word comes from ``whyline.agents.convert.to_docx``. PDF is the same
HTML rendered by AppKit, then a plain-text ``cupsfilter`` fallback. No new
dependency: when PDF cannot be made, Word still goes out and ``notes``
says so.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from whyline.agents import convert
from whyline.ideas import paths, store

# cupsfilter writes the converted document to stdout. There is no output-path
# flag, and a shell redirect is not used. text/html has no PDF filter on
# macOS, so the fallback feeds it plain text.
OSASCRIPT = "/usr/bin/osascript"
TEXTUTIL = "/usr/bin/textutil"
CUPSFILTER = "/usr/sbin/cupsfilter"
_TIMEOUT_SECONDS = 60
_FORMATS = frozenset({"word", "pdf", "both"})
_KV_KEY = "doc_formats"
# A disc marker and a little item padding, so each list item shows one
# bullet. 0.4em keeps the marker off the words.
_LIST_CSS = "ul { list-style-type: disc; }li { padding-left: 0.4em; }"

PDF_NOTE = "PDF not available on this machine; sent Word only"
PLAIN_TEXT_NOTE = "PDF is plain text on this Mac"
BOTH_FAILED_NOTE = "Word and PDF could not be written; sent the Markdown file."
WORD_FAILED_NOTE = "Word could not be written; sent the Markdown file."
WORD_FAILED_PDF_NOTE = "Word could not be written; sent PDF only."
PDF_FAILED_NOTE = "PDF not available on this machine; sent the Markdown file."

# Doctor converts this and nothing else. A heading, a two-item list, and a
# two-row table exercise the three things a report uses.
SAMPLE_HTML = (
    "<html><head><meta charset='utf-8'></head><body>"
    "<h1>Sample</h1>"
    "<ul><li>One</li><li>Two</li></ul>"
    "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
    "</body></html>"
)


@dataclass(frozen=True)
class Exported:
    docx: Path | None
    pdf: Path | None
    notes: list[str]


@dataclass(frozen=True)
class PdfResult:
    """``route`` is ``appkit``, ``plain``, or None when nothing was written."""

    route: str | None
    reason: str = ""


def export(md_path, *, formats=None, run=subprocess.run) -> Exported:
    """Write the requested copies of ``md_path``.

    ``formats`` is ``word``, ``pdf``, or ``both``. When it is omitted, the
    ``doc_formats`` kv value is used, and a missing or unrecognised value
    means ``both``. ``run`` is ``subprocess.run`` in production; tests pass
    a fake converter. Callers send the Markdown file when both paths are
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
    pdf = None
    plain = False
    if chosen in ("pdf", "both"):
        pdf, plain = _pdf(md_path, folder / f"{stem}.pdf", run)
    return Exported(docx=docx, pdf=pdf, notes=_notes(chosen, docx, pdf, plain))


def probe_pdf(run=subprocess.run) -> PdfResult:
    """Convert the built-in sample in a temporary folder and name the route.

    Nothing is written outside that folder. The folder is removed before
    this returns.
    """
    with tempfile.TemporaryDirectory(prefix="whyline-pdf-") as tmp:
        folder = Path(tmp)
        return render_html(SAMPLE_HTML, folder / "sample.pdf", run=run, work=folder)


def render_html(html, out, *, run=subprocess.run, work: Path | None = None) -> PdfResult:
    """Write ``html`` to ``out``. The route is ``appkit``, ``plain``, or None."""
    if work is None:
        with tempfile.TemporaryDirectory(prefix="whyline-pdf-") as tmp:
            return render_html(html, out, run=run, work=Path(tmp))
    out = Path(out)
    page = Path(work) / "page.html"
    page.write_text(_with_list_css(html), encoding="utf-8")
    appkit_reason = _appkit(page, out, run)
    if appkit_reason is None:
        return PdfResult("appkit")
    out.unlink(missing_ok=True)
    plain_reason = _plain_text(page, out, run, Path(work))
    if plain_reason is None:
        return PdfResult("plain")
    out.unlink(missing_ok=True)
    return PdfResult(None, f"{appkit_reason}; {plain_reason}")


def script_path() -> Path:
    return Path(__file__).with_name("html_to_pdf.js")


def _with_list_css(html: str) -> str:
    if "</style>" in html:
        return html.replace("</style>", _LIST_CSS + "</style>", 1)
    block = f"<style>{_LIST_CSS}</style>"
    if "</head>" in html:
        return html.replace("</head>", block + "</head>", 1)
    return block + html


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


def _pdf(md_path: Path, out: Path, run) -> tuple[Path | None, bool]:
    try:
        html = convert.to_html(md_path.read_text(encoding="utf-8"))
    except OSError:
        out.unlink(missing_ok=True)
        return None, False
    result = render_html(html, out, run=run)
    if result.route == "appkit" and _valid_pdf(out):
        return out, False
    if result.route == "plain" and _valid_pdf(out):
        return out, True
    out.unlink(missing_ok=True)
    return None, False


def _appkit(page: Path, out: Path, run) -> str | None:
    """None when ``out`` is a PDF. Otherwise a short reason."""
    script = script_path()
    if not script.is_file():
        return "AppKit: html_to_pdf.js is missing"
    completed = _command(
        [OSASCRIPT, "-l", "JavaScript", str(script), str(page), str(out)],
        run,
    )
    if not _ok(completed):
        return "AppKit: " + _detail(completed, out)
    if _valid_pdf(out):
        return None
    return "AppKit: " + _file_reason(out)


def _plain_text(page: Path, out: Path, run, work: Path) -> str | None:
    """None when ``out`` is a PDF made from plain text. Otherwise a reason."""
    text = work / "page.txt"
    completed = _command(
        [TEXTUTIL, "-convert", "txt", "-output", str(text), str(page)],
        run,
    )
    if not _ok(completed) or not text.is_file() or text.stat().st_size == 0:
        return "plain text: " + _detail(completed, text)
    completed = _command(
        [CUPSFILTER, "-i", "text/plain", "-m", "application/pdf", str(text)],
        run,
    )
    data = _stdout(completed)
    if not _ok(completed) or not data.startswith(b"%PDF"):
        return "plain text: " + _bytes_reason(completed, data)
    try:
        out.write_bytes(data)
    except OSError as exc:
        out.unlink(missing_ok=True)
        return "plain text: " + _one_line(str(exc))
    if _valid_pdf(out):
        return None
    return "plain text: " + _file_reason(out)


def _command(argv: list[str], run):
    try:
        return run(
            argv,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return exc


def _ok(completed) -> bool:
    return not isinstance(completed, Exception) and getattr(completed, "returncode", 1) == 0


def _stdout(completed) -> bytes:
    if isinstance(completed, Exception):
        return b""
    data = getattr(completed, "stdout", None)
    if isinstance(data, str):
        data = data.encode("utf-8")
    if isinstance(data, (bytes, bytearray)) and len(data) > 0:
        return bytes(data)
    return b""


def _valid_pdf(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        with path.open("rb") as handle:
            return handle.read(5).startswith(b"%PDF")
    except OSError:
        return False


def _detail(completed, path: Path) -> str:
    if isinstance(completed, Exception):
        return _one_line(str(completed) or completed.__class__.__name__)
    if not _ok(completed):
        return _failure(completed)
    try:
        empty = (not path.is_file()) or path.stat().st_size == 0
    except OSError:
        empty = True
    if empty:
        return "plain text was empty"
    return _file_reason(path)


def _bytes_reason(completed, data: bytes) -> str:
    if isinstance(completed, Exception):
        return _one_line(str(completed) or completed.__class__.__name__)
    if not _ok(completed):
        return _failure(completed)
    if len(data) == 0:
        return "PDF was empty"
    return "PDF was not a PDF"


def _failure(completed) -> str:
    message = _stderr(completed)
    if message:
        return message
    return f"converter exited {getattr(completed, 'returncode', 1)}"


def _file_reason(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return "PDF was empty"
    except OSError:
        return "PDF was empty"
    return "PDF was not a PDF"


def _stderr(completed) -> str:
    data = getattr(completed, "stderr", None)
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    if not isinstance(data, str):
        return ""
    lines = [line.strip() for line in data.splitlines() if line.strip()]
    if not lines:
        return ""
    return _one_line(lines[-1])


def _one_line(text: str) -> str:
    return " ".join(text.split())[:300]


def _notes(chosen: str, docx: Path | None, pdf: Path | None, plain: bool) -> list[str]:
    want_word = chosen in ("word", "both")
    want_pdf = chosen in ("pdf", "both")
    notes: list[str] = []
    if want_word and want_pdf:
        if docx is not None and pdf is not None:
            notes = []
        elif docx is not None:
            notes = [PDF_NOTE]
        elif pdf is not None:
            notes = [WORD_FAILED_PDF_NOTE]
        else:
            notes = [BOTH_FAILED_NOTE]
    elif want_word and docx is None:
        notes = [WORD_FAILED_NOTE]
    elif want_pdf and pdf is None:
        notes = [PDF_FAILED_NOTE]
    if plain and pdf is not None:
        notes.append(PLAIN_TEXT_NOTE)
    return notes
