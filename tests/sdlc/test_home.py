from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from whyline import paths
from whyline.console import repl
from whyline.relaychat import ask
from whyline.sdlc import docset as docset_mod
from whyline.sdlc import home


def _git(path, *args):
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, encoding="utf-8")


def _repo(path, files):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    for name in files:
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A")
    return path


def _set(description="A trading journal", brainstorm=False):
    docs = [{"kind": "brainstorm", "path": "b.md", "version": 1}] if brainstorm else []
    return SimpleNamespace(
        name="Trade Journal", slug="trade-journal", description=description,
        document=lambda kind: docs[0] if docs and kind == "brainstorm" else None)


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(ask, "_command", lambda repo, cli: ["claude", "-p"])
    monkeypatch.setattr(ask, "_extract", lambda repo, cli, raw, f: raw)
    monkeypatch.setattr("whyline.agents.runner._adapter", lambda defn, cli: None)


def _runner(reply, seen=None, code=0):
    def run(command, text, **kwargs):
        if seen is not None:
            seen.append((command, text, kwargs))
        return SimpleNamespace(exit_code=code, output=reply)
    return run


@pytest.mark.parametrize("name, expected", [
    ("Trade Journal!", "trade-journal"),
    ("  --Hello,   World__ ", "hello-world"),
    ("!!!", "project"),
    ("", "project"),
    ("a" * 60, "a" * 40),
    ("ab " * 20, ("ab-" * 14)[:40]),
])
def test_folder_name(name, expected):
    assert home.folder_name(name) == expected
    assert len(home.folder_name(name)) <= 40


def test_suggest_names_parses_three_lines(agent):
    reply = ("1. Ledgerly — a ledger for trades\n"
             "- **Tradebook** — plain and memorable\n"
             "Pipsqueak - small and friendly\n"
             "Extra — fourth line ignored\n")
    ideas = home.suggest_names("/r", _set(), agent="claude", run_fn=_runner(reply))
    assert [i.name for i in ideas] == ["Ledgerly", "Tradebook", "Pipsqueak"]
    assert ideas[0] == home.NameIdea("Ledgerly", "ledgerly", "a ledger for trades")


def test_suggest_names_keeps_two(agent):
    ideas = home.suggest_names("/r", _set(), agent="claude",
                               run_fn=_runner("Sure!\nOne — first\nTwo — second\n"))
    assert [i.name for i in ideas] == ["One", "Two"]


@pytest.mark.parametrize("reply", ["no names here", "Only — one line"])
def test_bad_reply_falls_back(agent, reply):
    ideas = home.suggest_names("/r", _set(), agent="claude", run_fn=_runner(reply))
    assert ideas == [home.NameIdea("Trade Journal", "trade-journal", "from the plan's name")]


def test_agent_error_falls_back(agent):
    def boom(*args, **kwargs):
        raise RuntimeError("agent crashed")

    expected = [home.NameIdea("Trade Journal", "trade-journal", "from the plan's name")]
    assert home.suggest_names("/r", _set(), agent="claude", run_fn=boom) == expected
    failed = _runner("A — b\nC — d\n", code=1)
    assert home.suggest_names("/r", _set(), agent="claude", run_fn=failed) == expected


def test_no_read_only_mode_falls_back(monkeypatch):
    monkeypatch.setattr(ask, "_command", lambda repo, cli: None)
    ideas = home.suggest_names("/r", _set(), agent="claude", run_fn=_runner("A — b\nC — d"))
    assert [i.reason for i in ideas] == ["from the plan's name"]


def test_prompt_holds_only_the_synthesis(agent, monkeypatch, tmp_path):
    monkeypatch.setattr(docset_mod, "_current_text", lambda root, ds, doc: "THE SYNTHESIS")
    seen: list = []
    home.suggest_names(tmp_path, _set(brainstorm=True), agent="claude",
                       run_fn=_runner("A — b\nC — d", seen))
    command, text, kwargs = seen[0]
    assert text == f"THE SYNTHESIS\n\n{home.PROMPT_ASK}"
    assert "A trading journal" not in text
    assert kwargs["cwd"] != tmp_path


def test_prompt_uses_description_without_brainstorm(agent, tmp_path):
    seen: list = []
    home.suggest_names(tmp_path, _set(), agent="claude", run_fn=_runner("A — b\nC — d", seen))
    assert seen[0][1] == f"A trading journal\n\n{home.PROMPT_ASK}"


def test_cancelled_turn_retries_once(agent, monkeypatch):
    calls = []

    def run(command, text, **kwargs):
        calls.append(text)
        return SimpleNamespace(exit_code=0, output="A — b\nC — d" if len(calls) == 2 else "")

    monkeypatch.setattr(ask, "cancelled_turn", lambda cli, raw: raw == "")
    ideas = home.suggest_names("/r", _set(), agent="grok", run_fn=run)
    assert len(calls) == 2 and ask.RETRY_NOTE in calls[1]
    assert [i.name for i in ideas] == ["A", "C"]


def test_is_fresh_with_only_docs(tmp_path):
    root = _repo(tmp_path / "r", ["README.md", "LICENSE", ".gitignore", "docs/a.md",
                                  "plans/p.plan", ".whyline/x.json", ".claude/s.json"])
    assert home.is_fresh(root) is True


def test_is_fresh_false_with_code(tmp_path):
    root = _repo(tmp_path / "r", ["README.md", "src/app.py"])
    assert home.is_fresh(root) is False


def test_check_target_parent_missing(tmp_path):
    missing = tmp_path / "nope"
    assert home.check_target(tmp_path, missing, "x") == f"{missing} doesn't exist."


def test_check_target_not_empty(tmp_path):
    (tmp_path / "out" / "x").mkdir(parents=True)
    (tmp_path / "out" / "x" / "f").write_text("1")
    assert home.check_target(tmp_path / "r", tmp_path / "out", "x") == (
        f"{tmp_path / 'out' / 'x'} already exists and isn't empty. Pick another name or folder.")


def test_check_target_empty_existing_is_fine(tmp_path):
    (tmp_path / "out" / "x").mkdir(parents=True)
    assert home.check_target(tmp_path / "r", tmp_path / "out", "x") is None


def test_check_target_inside_repository(tmp_path):
    root = _repo(tmp_path / "r", ["README.md"])
    message = home.check_target(root, root, "x")
    assert message == (f"{root / 'x'} is inside the repository {root.resolve()}. "
                       "Pick a folder outside it.")


def test_check_target_inside_other_repository(tmp_path):
    outer = _repo(tmp_path / "other", ["a"])
    message = home.check_target(tmp_path / "r", outer, "x")
    assert "is inside the repository" in message and str(outer.resolve()) in message


def test_check_target_home_refused(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert home.check_target(tmp_path / "r", tmp_path.parent, tmp_path.name) == (
        repl._HOME_REFUSAL)


def test_check_target_ok(tmp_path):
    (tmp_path / "out").mkdir()
    assert home.check_target(tmp_path / "r", tmp_path / "out", "new") is None


def test_last_parent_default_and_saved(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert paths.global_whyline_dir() == tmp_path / ".whyline"
    assert home.last_parent() == tmp_path
    (tmp_path / "projects").mkdir()
    assert home.last_parent() == tmp_path / "projects"
    chosen = tmp_path / "elsewhere"
    home.save_parent(chosen)
    assert home.last_parent() == chosen
