"""Attachments the user adds in the console (console attachments spec,
section 1). Files are copied into the repository, under a git-ignored
folder, so every agent can read the same stable copy. No UI code here."""
from __future__ import annotations

import fnmatch
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_MESSAGE_BYTES = 50 * 1024 * 1024
MAX_FILES = 10

_SESSION = re.compile(r"^\d{8}-\d{6}$")
_SECRETS = (".env*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "*credentials*")


class AttachmentError(ValueError):
    """A file that can't be attached, with a message for the user."""


@dataclass(frozen=True)
class Attachment:
    id: str
    name: str
    path: Path
    kind: str  # "image" | "file"
    size: int
    source: str  # "picker" | "clipboard" | "drop"
    warning: str = ""


@dataclass
class PendingAttachments:
    items: list[Attachment] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(a.size for a in self.items)

    def add(self, attachment: Attachment) -> None:
        self.items.append(attachment)

    def remove(self, attachment_id: str) -> None:
        self.items = [a for a in self.items if a.id != attachment_id]

    def clear(self) -> None:
        self.items = []

    def paths(self) -> list[Path]:
        return [a.path for a in self.items]


def _megabytes(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB"


def session_name(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def safe_name(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    clean = re.sub(r"[^A-Za-z0-9._-]", "-", stem) or "file"
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)[:78]
    limit = 80 - (len(ext) + 1 if ext else 0)
    return f"{clean[:limit]}.{ext}" if ext else clean[:80]


def ensure_ignored(root: Path) -> None:
    ignore = root / ".whyline" / ".gitignore"
    ignore.parent.mkdir(parents=True, exist_ok=True)
    lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if "attachments/" not in lines:
        content = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        with ignore.open("a", encoding="utf-8") as out:
            if content and not content.endswith("\n"):
                out.write("\n")
            out.write("attachments/\n")
        # whyline's own file: commit just this line, or the next relay start
        # refuses a dirty tree. Never anything else in the repository.
        from whyline_relay import gitcheck

        try:
            gitcheck.commit_paths(root, [ignore], "chore: ignore whyline attachments")
        except Exception:  # no git identity, not a repo yet: the ignore rule still works
            pass
    probe = root / ".whyline" / "attachments" / "probe"
    checked = subprocess.run(
        ["git", "check-ignore", "-q", str(probe)], cwd=root, capture_output=True
    )
    if checked.returncode != 0:
        raise AttachmentError(
            "Can't attach files here: .whyline/attachments isn't ignored by git, "
            "so the copies could end up in a commit."
        )


def _kind(path: Path) -> str:
    with open(path, "rb") as handle:
        head = handle.read(12)
    if (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"\xff\xd8\xff")
        or head.startswith((b"GIF87a", b"GIF89a"))
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
    ):
        return "image"
    return "file"


def stage(
    root: Path,
    original: Path,
    *,
    session: str,
    source: str,
    pending: PendingAttachments | None = None,
) -> Attachment:
    original = Path(original).expanduser()
    if original.is_dir():
        raise AttachmentError("Folders can't be attached yet; attach the files inside.")
    try:
        resolved = original.resolve(strict=True)
        info = resolved.stat()
    except OSError as error:
        raise AttachmentError(f"Can't read {original.name}: {error.strerror or error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise AttachmentError(f"{original.name} isn't a regular file, so it can't be attached.")
    if info.st_size > MAX_FILE_BYTES:
        raise AttachmentError(
            f"{original.name} is {_megabytes(info.st_size)}; the limit is "
            f"{_megabytes(MAX_FILE_BYTES)} per file."
        )
    if pending is not None:
        if len(pending.items) >= MAX_FILES:
            raise AttachmentError(f"A message can have at most {MAX_FILES} files.")
        if pending.total_bytes + info.st_size > MAX_MESSAGE_BYTES:
            raise AttachmentError(
                f"Adding {original.name} would go over {_megabytes(MAX_MESSAGE_BYTES)} for one message."
            )
    ensure_ignored(root)
    attachment_id = secrets.token_hex(4)
    name = safe_name(original.name)
    folder = root / ".whyline" / "attachments" / session / attachment_id
    folder.mkdir(parents=True, mode=0o700)
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".partial-")
    os.close(handle)
    try:
        shutil.copyfile(resolved, temp)
        os.replace(temp, folder / name)
    except OSError:
        Path(temp).unlink(missing_ok=True)
        raise
    warning = "looks like a secret" if any(
        fnmatch.fnmatch(original.name.lower(), p) for p in _SECRETS
    ) else ""
    return Attachment(
        attachment_id, name, folder / name, _kind(folder / name), info.st_size, source, warning
    )


def dropped_paths(text: str) -> list[Path] | None:
    """The files a drag-and-drop pasted, or None when the text is anything
    else. Never runs the text through a shell."""
    try:
        tokens = shlex.split(text.strip(), posix=True)
    except ValueError:  # an unbalanced quote: ordinary text
        return None
    if not tokens:
        return None
    paths = []
    for token in tokens:
        if token.startswith("file://"):
            token = unquote(urlparse(token).path)
        path = Path(token).expanduser()
        if not path.is_absolute() or not path.is_file():
            return None
        paths.append(path)
    return paths


def clean_old(root: Path, *, days: int = 7, now: float | None = None) -> list[Path]:
    base = root / ".whyline" / "attachments"
    if not base.is_dir() or base.is_symlink():
        return []
    cutoff = (now if now is not None else time.time()) - days * 86400
    removed = []
    for entry in sorted(base.iterdir()):
        if entry.is_symlink() or not entry.is_dir() or not _SESSION.match(entry.name):
            continue
        if entry.lstat().st_mtime < cutoff:
            shutil.rmtree(entry)
            removed.append(entry)
    return removed
