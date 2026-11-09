from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from whyline import paths
from whyline.console import repo_setup
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
        "Pick a folder other than your home folder.")


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


def _project(tmp_path, brainstorm=None):
    root = tmp_path / "old"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "a")
    docset_mod.create(root, "Trade Journal", "feature", "auto", roles={})
    folder = root / "docs" / "sdlc" / "trade-journal"
    data = json.loads((folder / "docset.json").read_text())
    data["description"] = "A trading journal"
    (folder / "docset.json").write_text(json.dumps(data))
    (folder / "brainstorm.md").write_text(brainstorm or "x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _log(path):
    return subprocess.run(["git", "log", "--format=%s", "--name-only"], cwd=path,
                          capture_output=True, encoding="utf-8", check=True).stdout


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "homedir")
    monkeypatch.setattr(home.guard, "check", lambda root: None)
    calls = []

    def setup(inspection, *, agents, progress):
        calls.append((inspection.path, agents))
        inspection.path.mkdir(parents=True, exist_ok=True)
        _git(inspection.path, "init", "-q", "-b", "main")
        _git(inspection.path, "config", "user.email", "a@b.c")
        _git(inspection.path, "config", "user.name", "a")
        _git(inspection.path, "commit", "-q", "--allow-empty", "-m", "first")
        return inspection.path

    monkeypatch.setattr(repo_setup, "setup", setup)
    return calls


def _make(tmp_path):
    parent = tmp_path / "out"
    parent.mkdir()
    return parent


def test_create_home_writes_files_and_commits(stubbed, tmp_path):
    root = _project(tmp_path)
    parent = _make(tmp_path)
    target = home.create_home(root, "trade-journal", parent, "tj", name="TJ",
                              agents=["claude"], progress=None)
    assert target == parent / "tj" and stubbed[0][1] == ["claude"]
    assert (target / "README.md").read_text() == "# TJ\n\nA trading journal\n"
    assert (target / ".gitignore").read_text().split() == [
        ".DS_Store", ".env", ".venv/", "__pycache__/", "node_modules/"]
    copied = json.loads((target / "docs/sdlc/trade-journal/docset.json").read_text())
    assert copied["home"]["created_from"] == str(root) and copied["home"]["at"]
    log = _log(target)
    assert "docs: start TJ" in log and "README.md" in log
    assert "docs/sdlc/trade-journal/brainstorm.md" in log
    assert subprocess.run(["git", "status", "--porcelain"], cwd=target, capture_output=True,
                          encoding="utf-8").stdout == ""
    assert home.last_parent() == parent


def test_create_home_readme_uses_brainstorm_first_paragraph(stubbed, tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setattr(docset_mod, "_current_text",
                        lambda r, ds, doc: "First para.\nstill first.\n\nSecond.")
    data_path = root / "docs/sdlc/trade-journal/docset.json"
    data = json.loads(data_path.read_text())
    data["documents"] = [{"kind": "brainstorm", "path": "b.md", "version": 1}]
    data_path.write_text(json.dumps(data))
    _git(root, "commit", "-qam", "bs")
    target = home.create_home(root, "trade-journal", _make(tmp_path), "tj", name="TJ",
                              agents=[], progress=None)
    assert (target / "README.md").read_text() == "# TJ\n\nFirst para.\nstill first.\n"


def test_create_home_keeps_existing_readme(stubbed, tmp_path, monkeypatch):
    root = _project(tmp_path)
    parent = _make(tmp_path)
    real = repo_setup.setup

    def setup(inspection, **kw):
        path = real(inspection, **kw)
        (path / "README.md").write_text("mine\n")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", "readme")
        return path

    monkeypatch.setattr(repo_setup, "setup", setup)
    target = home.create_home(root, "trade-journal", parent, "tj", name="TJ",
                              agents=[], progress=None)
    assert (target / "README.md").read_text() == "mine\n"


def test_create_home_marks_old_set_moved(stubbed, tmp_path):
    root = _project(tmp_path)
    target = home.create_home(root, "trade-journal", _make(tmp_path), "tj", name="TJ",
                              agents=[], progress=None)
    old = root / "docs/sdlc/trade-journal"
    data = json.loads((old / "docset.json").read_text())
    assert data["state"] == "moved" and data["moved_to"] == str(target)
    assert (old / "brainstorm.md").is_file()
    log = _log(root)
    assert f"docs: TJ moved to {target}" in log and "docset.json" in log
    assert "home" not in data


def test_create_home_refusal_creates_nothing(stubbed, tmp_path):
    root = _project(tmp_path)
    parent = _make(tmp_path)
    (parent / "tj").mkdir()
    (parent / "tj" / "f").write_text("1")
    with pytest.raises(home.HomeError, match="already exists"):
        home.create_home(root, "trade-journal", parent, "tj", name="TJ",
                         agents=[], progress=None)
    assert stubbed == [] and sorted(p.name for p in (parent / "tj").iterdir()) == ["f"]
    assert "moved" not in _log(root)


def test_create_home_guard_refusal(stubbed, tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setattr(home.guard, "check", lambda r: "A relay is running.")
    parent = _make(tmp_path)
    with pytest.raises(home.HomeError, match="A relay is running."):
        home.create_home(root, "trade-journal", parent, "tj", name="TJ",
                         agents=[], progress=None)
    assert stubbed == [] and not (parent / "tj").exists()


def test_create_home_setup_error(stubbed, tmp_path, monkeypatch):
    root = _project(tmp_path)

    def setup(inspection, **kw):
        raise repo_setup.SetupError("git", OSError("boom"))

    monkeypatch.setattr(repo_setup, "setup", setup)
    with pytest.raises(home.HomeError, match="boom"):
        home.create_home(root, "trade-journal", _make(tmp_path), "tj", name="TJ",
                         agents=[], progress=None)
    data = json.loads((root / "docs/sdlc/trade-journal/docset.json").read_text())
    assert "state" not in data


def test_use_here(stubbed, tmp_path):
    root = _project(tmp_path)
    assert home.use_here(root, "trade-journal") == root
    data = json.loads((root / "docs/sdlc/trade-journal/docset.json").read_text())
    assert data["home"]["here"] is True and data["home"]["at"]
    assert "docset.json" in _log(root)
