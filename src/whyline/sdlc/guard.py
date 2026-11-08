"""Keep SDLC drafting to one document at a time, away from a running relay."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from whyline.sdlc.workspace import docs_root


class DraftingBusy(RuntimeError):
    """Another document is already being written."""


def check(root: Path) -> str | None:
    """A plain refusal when a relay is running in the docs checkout itself."""
    from whyline_relay import running, state as relay_state

    docs = docs_root(root)
    if running.live(docs) is not None:
        return (
            "A relay is running in the documents checkout. "
            "Wait for it to finish or stop it first, then write documents."
        )
    try:
        saved = relay_state.load(docs)
    except Exception:
        saved = None
    if saved is not None and getattr(saved, "paused_reason", ""):
        return (
            "A relay is paused in the documents checkout. "
            "Finish or stop it first, then write documents."
        )
    return None


def _lock_path(docs: Path) -> Path:
    return docs / ".whyline" / "sdlc" / "drafting.lock"


def _read(path: Path) -> dict | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get("pid"), int):
        return None
    return record


@contextmanager
def drafting(root: Path, set_name: str = "", kind: str = "") -> Iterator[Path]:
    from whyline_relay import running

    path = _lock_path(docs_root(root))
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"pid": os.getpid(), "set": set_name, "kind": kind}) + "\n"
    with _mutex(path):
        # Publish the complete record atomically: link() fails if the lock
        # exists and never exposes a half-written file.
        staged = path.with_name(f"drafting.{os.getpid()}.{os.urandom(4).hex()}.tmp")
        staged.write_text(body, encoding="utf-8")
        try:
            while True:
                try:
                    os.link(staged, path)
                    break
                except FileExistsError:
                    held = _read(path)
                    if held is not None and running.pid_is_alive(held["pid"]):
                        raise DraftingBusy(
                            f"Another document is being written ({held.get('set', '')}, {held.get('kind', '')})"
                        ) from None
                    # Dead owner or corrupt record; the mutex keeps anyone
                    # else from replacing it while we remove it.
                    path.unlink(missing_ok=True)
        finally:
            staged.unlink(missing_ok=True)
    try:
        yield path
    finally:
        with _mutex(path):
            held = _read(path)
            if held is not None and held["pid"] == os.getpid():
                path.unlink(missing_ok=True)


@contextmanager
def _mutex(path: Path) -> Iterator[None]:
    """Short exclusive section serialising lock acquire, takeover and release."""
    import fcntl

    with open(path.with_name("drafting.mutex"), "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
