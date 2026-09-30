"""Starting whyline in a folder with no git repo of its own asks to set one
up there, instead of silently using whatever repo is found above it --
which, for a new project folder in ~, was the home directory's own repo."""

import subprocess
from pathlib import Path

from whyline import cli, paths


def _enter(monkeypatch, home: Path, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(folder)


def _launched(monkeypatch):
    from whyline.console import tui

    seen = []
    monkeypatch.setattr(tui, "TUI_AVAILABLE", True)
    monkeypatch.setattr(tui, "launch", lambda root: seen.append(Path(root).resolve()))
    return seen


def _run(answers, printed):
    answers = iter(answers)
    return cli.run_entry_menu(
        relay_available=lambda: True,
        exec_fn=lambda *a: None,
        input_fn=lambda prompt="": printed.append(prompt) or next(answers),
        print_fn=printed.append,
        offer_git=True,
    )


def test_yes_sets_up_git_and_whyline_here_and_opens_the_console(tmp_path, monkeypatch):
    project = tmp_path / "TradingPlatform"
    _enter(monkeypatch, tmp_path, project)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # ~ is a repo
    seen = _launched(monkeypatch)
    printed = []

    assert _run(["y"], printed) is True

    assert (project / ".git").is_dir()
    assert paths.is_initialised(project)
    assert seen == [project.resolve()]
    assert any("has no git repository of its own" in line for line in printed)


def test_no_keeps_the_repo_above_but_says_so(tmp_path, monkeypatch):
    project = tmp_path / "TradingPlatform"
    _enter(monkeypatch, tmp_path, project)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    seen = _launched(monkeypatch)
    printed = []

    _run(["n"], printed)

    assert not (project / ".git").exists()
    assert seen == [tmp_path.resolve()]


def test_a_folder_with_no_repo_anywhere_is_offered_too(tmp_path, monkeypatch):
    project = tmp_path / "fresh"
    _enter(monkeypatch, tmp_path / "home-elsewhere", project)
    seen = _launched(monkeypatch)
    printed = []
    _run(["", ], printed)  # Enter accepts
    assert (project / ".git").is_dir() and seen == [project.resolve()]


def test_a_subfolder_of_a_real_project_is_not_offered(tmp_path, monkeypatch):
    repo = tmp_path / "work" / "monorepo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _enter(monkeypatch, tmp_path, repo / "packages" / "api")
    seen = _launched(monkeypatch)
    printed = []
    _run([], printed)  # would raise StopIteration if it asked
    assert seen == [repo.resolve()]
    assert not any("git repository of its own" in line for line in printed)


def test_no_terminal_never_creates_a_repo(tmp_path, monkeypatch):
    project = tmp_path / "fresh"
    _enter(monkeypatch, tmp_path / "home-elsewhere", project)
    _launched(monkeypatch)

    import pytest

    def closed(prompt=""):
        raise EOFError

    # stdin is not a terminal under pytest, so no offer is made at all
    with pytest.raises(EOFError):  # the pre-existing plain menu still asks
        cli.run_entry_menu(
            relay_available=lambda: True, exec_fn=lambda *a: None,
            input_fn=closed, print_fn=lambda *a: None,
        )
    assert not (project / ".git").exists()


def test_whyline_console_offers_the_same(tmp_path, monkeypatch):
    project = tmp_path / "TradingPlatform"
    _enter(monkeypatch, tmp_path, project)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    seen = _launched(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli.main(["console", "--ui"]) == cli.EXIT_OK
    assert seen == [project.resolve()]
