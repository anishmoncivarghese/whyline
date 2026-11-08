"""Import an existing file as version 1 of a document in a set."""
from __future__ import annotations

from pathlib import Path

from whyline.jobs.profile import ProfileError, read_docx_text, read_pdf_text
from whyline.sdlc.docset import DocSet, DocSetError, add_version, log_review

MAX_TEXT_BYTES = 2 * 1024 * 1024
SUPPORTED = (".md", ".txt", ".pdf", ".docx")
_TOO_BIG = "That file is over the 2 MB text limit."


def _read_text_file(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES * 2:
            raise DocSetError(_TOO_BIG)
        raw = path.read_bytes()
    except OSError as error:
        raise DocSetError(f"Could not read {path.name}: {error.strerror or error}") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocSetError(f"{path.name} must be UTF-8 text.") from None
    return text.replace("\r\n", "\n")


def read_source(path: str | Path) -> str:
    """The text of a .md, .txt, .pdf or .docx file; refuses anything else."""
    path = Path(path).expanduser()
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        shown = path.suffix or "no extension"
        raise DocSetError(f"Cannot import a file with {shown}; choose a .md, .txt, .pdf or .docx file.")
    if not path.is_file():
        raise DocSetError(f"File not found: {path}")
    try:
        if suffix == ".pdf":
            text = read_pdf_text(path)
        elif suffix == ".docx":
            text = read_docx_text(path)
        else:
            text = _read_text_file(path)
    except ProfileError as error:
        raise DocSetError(str(error)) from None
    if not text.strip():
        raise DocSetError(f"{path.name} has no text to import.")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise DocSetError(_TOO_BIG)
    return text


def import_as(root: Path, docset: DocSet, kind: str, path: str | Path, *, actor: str) -> int:
    """Store a file's text as the next version of a document; returns the number."""
    path = Path(path).expanduser()
    text = read_source(path)
    number = add_version(root, docset, kind, text, author=actor, note=f"imported from {path.name}")
    log_review(root, docset, kind, actor=actor, action="imported")
    return number


def import_brainstorm(root: Path, docset: DocSet, path: str | Path, *, actor: str = "user") -> int:
    """Import a brainstorm. A file already in docs/brainstorm/ stays where it is
    (it is only read) and its text is copied into the set."""
    return import_as(root, docset, "brainstorm", path, actor=actor)
