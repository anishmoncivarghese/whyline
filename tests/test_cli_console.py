import os

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
