import builtins
import os
import sys
from types import ModuleType

import pytest

from whyline import cli


def run_in(repo, arguments):
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        return cli.main(arguments)
    finally:
        os.chdir(previous)


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


def fail_relay_import(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "whyline_relay":
            raise ModuleNotFoundError(
                "No module named 'whyline_relay'", name="whyline_relay"
            )
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "whyline_relay", raising=False)
    monkeypatch.delitem(sys.modules, "whyline_relay.cli", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded_import)


@pytest.mark.parametrize("arguments", [[], ["--yes"]])
def test_default_and_yes_do_not_set_up_relay(repo, monkeypatch, arguments):
    calls = install_fake_relay(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert run_in(repo, ["init", *arguments]) == cli.EXIT_OK
    assert calls == []


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (
            ["--no-instructions", "--no-hooks"],
            ["init", "--repo"],
        ),
        (["--yes"], ["init", "--repo", "--yes"]),
    ],
)
def test_relay_flag_runs_relay_init_with_expected_arguments(
    repo, monkeypatch, extra, expected
):
    calls = install_fake_relay(monkeypatch)

    assert run_in(repo, ["init", "--relay", *extra]) == cli.EXIT_OK
    relay_arguments, prog = calls[0]
    assert relay_arguments == [*expected[:2], str(repo.path), *expected[2:]]
    assert prog == "whyline relay"


def test_no_relay_neither_asks_nor_sets_up(repo, monkeypatch):
    calls = install_fake_relay(monkeypatch)

    def unexpected(prompt):
        raise AssertionError(f"should not have prompted: {prompt}")

    monkeypatch.setattr("builtins.input", unexpected)
    assert (
        run_in(
            repo,
            ["init", "--no-instructions", "--no-hooks", "--no-relay"],
        )
        == cli.EXIT_OK
    )
    assert calls == []


def test_relay_options_are_mutually_exclusive(repo):
    with pytest.raises(SystemExit) as error:
        run_in(repo, ["init", "--relay", "--no-relay"])
    assert error.value.code == cli.EXIT_USAGE


@pytest.mark.parametrize(
    ("answer", "expected_calls"),
    [("y", 1), ("n", 0), ("", 0)],
)
def test_interactive_relay_answers(repo, monkeypatch, answer, expected_calls):
    calls = install_fake_relay(monkeypatch)
    asked = []
    monkeypatch.setattr(
        "builtins.input", lambda prompt: asked.append(prompt) or answer
    )

    assert (
        run_in(repo, ["init", "--no-instructions", "--no-hooks"])
        == cli.EXIT_OK
    )
    assert len(calls) == expected_calls
    assert asked == [
        "Also set up the automated relay (Codex implements, Claude reviews "
        "and commits, unattended)? [y/N] "
    ]


def test_relay_offer_treats_end_of_input_as_no(repo, monkeypatch):
    calls = install_fake_relay(monkeypatch)

    def end_of_input(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", end_of_input)
    assert (
        run_in(repo, ["init", "--no-instructions", "--no-hooks"])
        == cli.EXIT_OK
    )
    assert calls == []


def test_existing_relay_setup_is_reported_without_asking(repo, monkeypatch, capsys):
    config = repo.path / ".whyline" / "relay" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("configured = true\n")
    calls = install_fake_relay(monkeypatch)

    def unexpected(prompt):
        raise AssertionError(f"should not have prompted: {prompt}")

    monkeypatch.setattr("builtins.input", unexpected)
    assert (
        run_in(
            repo,
            ["init", "--no-instructions", "--no-hooks", "--relay"],
        )
        == cli.EXIT_OK
    )
    assert calls == []
    assert "The automated relay is already set up.\n" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("arguments", "expected_code"),
    [(["--relay"], cli.EXIT_ERROR), ([], cli.EXIT_OK)],
)
def test_missing_relay_exit_code_depends_on_explicit_request(
    repo, monkeypatch, capsys, arguments, expected_code
):
    fail_relay_import(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert (
        run_in(
            repo,
            ["init", "--no-instructions", "--no-hooks", *arguments],
        )
        == expected_code
    )
    captured = capsys.readouterr()
    assert cli.relay_install_hint() + "\n" == captured.err


def test_relay_init_failure_is_returned(repo, monkeypatch):
    install_fake_relay(monkeypatch, exit_code=23)
    assert run_in(repo, ["init", "--relay", "--yes"]) == 23


def test_successful_relay_init_prints_next_steps(repo, monkeypatch, capsys):
    install_fake_relay(monkeypatch)
    assert run_in(repo, ["init", "--relay", "--yes"]) == cli.EXIT_OK
    assert (
        "Next: write a plan (whyline relay plan-format shows the format), "
        "commit, then run: whyline relay start\n"
        in capsys.readouterr().out
    )


def test_init_help_describes_both_relay_options(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["init", "--help"])
    assert error.value.code == cli.EXIT_OK
    output = capsys.readouterr().out
    assert "Also set up the automated relay." in output
    assert "Do not offer the automated relay." in output
