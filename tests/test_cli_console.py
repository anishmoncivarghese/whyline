import os

import pytest

from whyline import cli
from whyline.console import editor


class _ImmediateExit:
    def prompt(self, message=""):
        raise EOFError


def test_console_subcommand_runs_the_repl(repo, monkeypatch, capsys):
    monkeypatch.setattr(editor, "build_session", lambda root: _ImmediateExit())
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(["console"])
    finally:
        os.chdir(previous)
    assert code == cli.EXIT_OK
    assert "whyline console" in capsys.readouterr().out


def test_console_ui_flag_launches_the_tui(repo, monkeypatch):
    from whyline import cli
    from whyline.console import tui

    calls = []
    monkeypatch.setattr(tui, "launch", lambda root: calls.append(root))
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(["console", "--ui"])
    finally:
        os.chdir(previous)
    assert code == cli.EXIT_OK
    assert calls == [repo.path.resolve()]


def test_console_ui_flag_reports_a_clear_error_when_textual_is_missing(repo, capsys):
    from whyline import cli
    from whyline.console import tui

    if tui.TUI_AVAILABLE:
        pytest.skip("textual is installed in this environment -- nothing to test here")
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(["console", "--ui"])
    finally:
        os.chdir(previous)
    assert code == cli.EXIT_ERROR
    assert "whyline[ui]" in capsys.readouterr().out


def test_console_ui_flag_reports_a_clear_error_when_tui_raises_unavailable(
    repo, monkeypatch, capsys
):
    from whyline import cli
    from whyline.console import tui

    def _fail(_root):
        raise tui.TuiUnavailable(
            "The mouse TUI needs textual. Run: pip install 'whyline[ui]'"
        )

    monkeypatch.setattr(tui, "launch", _fail)
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(["console", "--ui"])
    finally:
        os.chdir(previous)
    assert code == cli.EXIT_ERROR
    assert "whyline[ui]" in capsys.readouterr().out
