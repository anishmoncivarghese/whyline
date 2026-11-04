"""Guard: relay chat never touches the relay it is asking about.

The agent's read-only mode is the real protection. These checks catch mistakes
in our own code: a run that changes the repo, takes the git index lock, or
starts, stops or interrupts the relay. The AST scan only sees direct calls and
literal argv lists, not getattr, variable function names or argv built at runtime.
"""
import ast
import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.relaychat import agent_choice, ask, history, settings

SRC = Path(__file__).resolve().parents[2] / "src" / "whyline"
SCANNED = [*sorted((SRC / "relaychat").glob("*.py")), SRC / "console" / "relay_chat_tab.py"]
BANNED_CALLS = {"start", "stop", "interrupt", "resume", "select_plan", "launcher"}
WRITE_CALLS = {"write_text", "write_bytes", "open", "mkdir", "touch", "unlink", "rename", "replace",
               "rmtree", "copy", "copy2", "copyfile", "move", "remove", "makedirs", "symlink_to"}
GIT = {"GIT_CONFIG_NOSYSTEM": "1"}


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, **GIT, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _fingerprint(repo):
    """Every file in the repo and .git except the fake relay's own .whyline/relay writes."""
    out = {}
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo)
        if path.is_dir() or rel.parts[:2] == (".whyline", "relay"):
            continue
        out[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


@pytest.fixture
def repo(tmp_path, monkeypatch):
    base = tmp_path / "chat"
    monkeypatch.setattr(settings, "base_dir", lambda b=None: base)
    monkeypatch.setattr(history, "base_dir", lambda b=None: base)
    monkeypatch.setattr(agent_choice, "pick",
                        lambda r, chosen=None: agent_choice.Pick("claude", False, "chosen"))
    monkeypatch.setattr(ask, "_command", lambda r, cli: ["claude", "--permission-mode", "plan"])
    monkeypatch.setattr(ask, "_extract", lambda r, cli, raw, f: raw)
    monkeypatch.setattr("whyline.agents.runner._adapter", lambda defn, cli: None)

    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "first")
    # Make the index stat-dirty so a plain `git status` would want to refresh (and lock) it.
    os.utime(root / "a.txt", (1, 1))
    logs = root / ".whyline" / "relay" / "logs"
    logs.mkdir(parents=True)
    (logs / "run.log").write_text("start\n")
    (root / ".whyline" / "relay" / "running.json").write_text(
        '{"agent": "codex", "task": "T-1", "round": 1, "started": "2026-11-04T10:00:00+00:00",'
        f' "pid": {os.getpid()}, "role": "implementer", "stage": "draft", "visit": 1}}\n')
    return root


def test_ask_leaves_a_running_relay_alone(repo, monkeypatch):
    calls = []

    def fake(name):
        def _fake(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"relay chat called {name}")
        return _fake

    from whyline.console import relay_ops
    from whyline_relay import loop, running

    for module, names in ((loop, ["run_plan", "run_task"]), (running, ["start_turn"]),
                          (relay_ops,["interrupt_live_run", "select_plan", "clear_pause"])):
        for name in names:
            monkeypatch.setattr(module, name, fake(f"{module.__name__}.{name}"))

    log = repo / ".whyline" / "relay" / "logs" / "run.log"
    stop = threading.Event()
    lock = repo / ".git" / "index.lock"
    seen_lock = []

    def relay_writes():
        while not stop.is_set():
            with log.open("a") as handle:
                handle.write("relay line\n")
            time.sleep(0.002)

    def watch_lock():
        while not stop.is_set():
            if lock.exists():
                seen_lock.append(time.monotonic())
            time.sleep(0.0005)

    attempts = []

    def agent(argv, prompt, **kwargs):
        env = kwargs["env"]
        scratch = kwargs["log_path"].parent
        (scratch / "attempt.txt").write_text("written")  # the only place the chat gives it
        attempts.append(env)
        done =subprocess.run(["git", "status", "--porcelain"], cwd=kwargs["cwd"], env={**os.environ, **env},
                              capture_output=True, text=True)
        assert done.returncode == 0
        assert not lock.exists()
        return SimpleNamespace(exit_code=0, output="All quiet.")

    before = _fingerprint(repo)
    threads = [threading.Thread(target=relay_writes), threading.Thread(target=watch_lock)]
    for thread in threads:
        thread.start()
    try:
        answer = ask.ask(repo, "What is happening?", runner=agent)
    finally:
        stop.set()
        for thread in threads:
            thread.join()

    assert answer.ok and answer.text == "All quiet."
    assert attempts and attempts[0]["GIT_OPTIONAL_LOCKS"] == "0"
    assert _fingerprint(repo) == before
    assert not seen_lock and not lock.exists()
    assert calls == []
    assert "relay line" in log.read_text()  # the fake relay really kept writing


def _calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            yield node, name


def _strings(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _mentions_relay_dir(node, tainted):
    texts = _strings(node)
    if any(".whyline/relay" in t for t in texts):
        return True
    if ".whyline" in texts and "relay" in texts:
        return True
    return any(isinstance(n, ast.Name) and n.id in tainted for n in ast.walk(node))


def _scan(tree):
    problems = []
    tainted = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _mentions_relay_dir(node.value, set()):
            tainted.update(t.id for t in node.targets if isinstance(t, ast.Name))
    for node, name in _calls(tree):
        if name in BANNED_CALLS:
            problems.append(f"line {node.lineno}: call to {name}")
        if name in WRITE_CALLS and _mentions_relay_dir(node, tainted):
            problems.append(f"line {node.lineno}: {name} touches .whyline/relay")
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value == "git":
                if "--no-optional-locks" not in _strings(node):
                    problems.append(f"line {node.lineno}: git argv without --no-optional-locks")
    return problems


def test_the_scan_catches_what_it_should():
    bad = ast.parse(
        "relay.stop()\nx.launcher()\nPath('.whyline/relay/a').write_text('x')\n"
        "d = repo / '.whyline' / 'relay'\nd.mkdir()\nrun(['git', 'status'])\n"
    )
    found = _scan(bad)
    assert len(found) == 5
    assert _scan(ast.parse("run(['git', '--no-optional-locks', 'status'])\nPath('x').write_text('y')\n")) == []


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_chat_code_never_drives_or_writes_the_relay(path):
    if not path.exists():  # the tab arrives in a later task
        pytest.skip(f"{path.name} does not exist yet")
    assert _scan(ast.parse(path.read_text(encoding="utf-8"))) == []
