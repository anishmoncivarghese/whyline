"""A thin, import-guarded wrapper over prompt_toolkit's multiline editor.

Guarded so the rest of the console package stays importable and testable
without the [console] extra installed -- only actually starting the
editor (build_session) requires it.
"""

from __future__ import annotations

from pathlib import Path

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory

    AVAILABLE = True
except ImportError:
    PromptSession = None
    FileHistory = None
    AVAILABLE = False


class EditorUnavailable(RuntimeError):
    """prompt_toolkit is not installed."""


def build_session(root: Path):
    if not AVAILABLE:
        raise EditorUnavailable(
            "The console's editor needs prompt_toolkit, which is missing "
            "from this install. Run: uv tool install --reinstall whyline"
        )
    history_path = root / ".whyline" / "console-history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    return PromptSession(multiline=True, history=FileHistory(str(history_path)))
