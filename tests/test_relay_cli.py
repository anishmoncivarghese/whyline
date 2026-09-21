import builtins
import importlib
import sys
from types import ModuleType

import pytest

from whyline import cli


def install_fake_relay(monkeypatch, exit_code=0):
    calls = []
    relay_cli = ModuleType("whyline_relay.cli")

    def main(argv, prog):
        calls.append((argv, prog))
        return exit_code

    relay_cli.main = main
    relay_package = ModuleType("whyline_relay")
    relay_package.cli = relay_cli
    monkeypatch.setitem(sys.modules, "whyline_relay", relay_package)
    monkeypatch.setitem(sys.modules, "whyline_relay.cli", relay_cli)
    return calls


def fail_relay_import(monkeypatch, missing_name):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "whyline_relay":
            raise ModuleNotFoundError(
                f"No module named {missing_name!r}", name=missing_name
            )
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "whyline_relay", raising=False)
    monkeypatch.delitem(sys.modules, "whyline_relay.cli", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_relay_passes_arguments_prog_and_exit_code(monkeypatch):
    calls = install_fake_relay(monkeypatch, exit_code=23)

    assert cli.main(["relay", "start", "--rounds", "3"]) == 23
    assert calls == [(["start", "--rounds", "3"], "whyline relay")]


@pytest.mark.parametrize("arguments", [["--help"], []])
def test_relay_passes_help_and_no_arguments_through(monkeypatch, arguments):
    calls = install_fake_relay(monkeypatch)

    assert cli.main(["relay", *arguments]) == cli.EXIT_OK
    assert calls == [(arguments, "whyline relay")]


def test_relay_missing_package_prints_install_hint(monkeypatch, capsys):
    fail_relay_import(monkeypatch, "whyline_relay")

    assert cli.main(["relay"]) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == cli.relay_install_hint() + "\n"


def test_relay_does_not_swallow_dependency_import_failure(monkeypatch):
    fail_relay_import(monkeypatch, "relay_dependency")

    with pytest.raises(ModuleNotFoundError) as error:
        cli.main(["relay"])
    assert error.value.name == "relay_dependency"


def test_whyline_help_lists_relay(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == cli.EXIT_OK
    help_output = " ".join(capsys.readouterr().out.split())
    assert (
        "Run a plan through Codex and Claude unattended "
        "(needs the whyline-relay package)."
    ) in help_output


def test_importing_cli_does_not_import_relay(monkeypatch):
    monkeypatch.delitem(sys.modules, "whyline_relay", raising=False)
    monkeypatch.delitem(sys.modules, "whyline_relay.cli", raising=False)

    importlib.reload(cli)

    assert "whyline_relay" not in sys.modules
