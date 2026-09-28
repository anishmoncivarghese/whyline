"""Bridging whyline console to whyline's own commands and whyline-relay's
already-structured functions. Every function here returns a SessionEvent
instead of printing -- see session.py's own docstring for why.
"""
from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

from whyline.console.session import SessionEvent

_INTERACTIVE_ONLY = {"account", "model"}


def run_whyline_command(argv: list[str]) -> SessionEvent:
    """Runs a non-interactive whyline command in-process, capturing its
    output. Bare "account"/"model" are interactive (real input() calls);
    redirecting stdout does nothing about stdin, so both are refused here
    rather than risking a hang on the wrong input source."""
    if len(argv) == 1 and argv[0] in _INTERACTIVE_ONLY:
        return SessionEvent(
            kind="error",
            text=(
                f"'{argv[0]}' needs a subcommand here (e.g. "
                f"'{argv[0]} status'), or use /model instead of the "
                "interactive wizard."
            ),
        )

    from whyline import cli

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli.main(argv)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else cli.EXIT_ERROR
    text = buf.getvalue()
    return SessionEvent(kind="output" if code == 0 else "error", text=text)
