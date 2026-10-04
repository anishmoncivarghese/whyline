# Console context bar, repo setup and mode-specific controls: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Run by whyline-relay in `~/agentdock` with **antigravity implementing and codex reviewing**. Task 6 is a release (human).

**Goal:** A context bar to pick and save the agent, model and repo (setting up a new repo in one confirmation); `/` runs any whyline command from any mode in place of Command mode; each mode shows only its own buttons.

**Architecture:**
- `whyline.model` gains a saved default agent (per repo) and a global default in `~/.whyline/console.json`.
- A new `whyline.console.repo_setup` module inspects a path and sets it up step by step. It has no UI.
- `tui.py` gains the `#context-bar` row, `_sync_mode_buttons()`, and slash routing to whyline subcommands.
- `session.mode` loses `"command"`.

**Tech Stack:** Python 3.11+, Textual 0.89.1, pytest + pytest-asyncio, git.

**Spec:** `docs/superpowers/specs/2026-10-05-console-context-bar-design.md`

## Global Constraints

- **Prerequisites:** whyline 0.3.34 (guided flow v2) is released. Agents mode isn't built yet, so the Agents row of the bottom bar is declared here but empty until the Agents plan fills it.
- Repo `~/agentdock`; roles `implementer = "antigravity"`, `reviewer = "codex"`.
- Modes are exactly `("chat", "relay", "agents")`; the default is `"chat"`.
- Bottom-bar rows, verbatim:
  - Chat: `model`, `brainstorm`, `history`;
  - Relay: `relay-run`, `relay-plan`, `relay-setup`, `relay-resume`;
  - Agents: `agents-new`, `agents-list`, `agents-runs`, `agents-scheduler` (when they exist);
  - every mode: `stop`, `help`, `copy`.

  The `attach` button in the input row is Chat-only.
- The global defaults file is `~/.whyline/console.json` with keys `default_agent` (str) and `models` (dict). The repo default is `.whyline/model.json` key `default_agent`.
- Setup's first commit is `chore: set up whyline` and contains only files the setup created.
- Tests must not depend on installed agent CLIs, must not touch the real home folder (point `HOME` at `tmp_path`), must pass on Windows, and every layout must fit 80 columns.
- After each task: `whyline note "<decision>" --because "<why>" --file <path> --actor <agent> --role implementer --task CB-<n>`.
- Never push, tag, bump versions or publish.

## Review Focus

- **The user's own uncommitted files in a folder being set up.** Never committed. Pinned in Task 2.
- **A path inside another repository** (`~/TradingPlatform/sub`). Refused, naming the outer repo. Pinned in Task 2.
- **`/status`**, a console command *and* a whyline subcommand. The console command wins. Pinned in Task 4.
- **Save pressed while a relay run is going.** Agent and model save; the repo switch is refused. Pinned in Task 3.
- **The 80-column bar in every mode,** after Agents adds its four buttons. Pinned in Task 5.

---

### Task 1: Saved default agent, per repo and global

**Files:** Modify `src/whyline/model.py`, `src/whyline/console/repl.py` (`_model_event` saves the default agent; the session starts on the resolved default). Test `tests/test_model_defaults.py`.

**Interfaces:**
- `model.set_default_agent(root, agent)`;
- `model.default_agent(root) -> str | None`;
- `model.global_path() -> Path` (`~/.whyline/console.json`);
- `model.load_global() -> dict`;
- `model.save_global(agent, model_name)`;
- `model.resolve(root) -> tuple[str, str]` (agent, model), resolved in the order repo, then global, then `("claude", "")`.

- [ ] **Step 1: Failing tests**

```python
import json

from whyline import model


def test_repo_default_agent_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".whyline").mkdir()
    assert model.default_agent(tmp_path) is None
    model.set_default_agent(tmp_path, "codex")
    model.set_one(tmp_path, "codex", "gpt-5.6")
    assert model.resolve(tmp_path) == ("codex", "gpt-5.6")
    assert json.loads((tmp_path / ".whyline/model.json").read_text())["default_agent"] == "codex"


def test_global_default_applies_without_a_repo_choice(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / ".whyline").mkdir()
    model.save_global("grok", "")
    assert model.resolve(tmp_path) == ("grok", "")
    assert json.loads((home / ".whyline/console.json").read_text())["default_agent"] == "grok"
    model.set_default_agent(tmp_path, "claude")
    assert model.resolve(tmp_path)[0] == "claude"  # the repo wins


def test_nothing_saved_means_claude(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".whyline").mkdir()
    assert model.resolve(tmp_path) == ("claude", "")


def test_an_unreadable_global_file_is_ignored(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".whyline").mkdir(parents=True)
    (home / ".whyline/console.json").write_text("{nope")
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / ".whyline").mkdir()
    assert model.resolve(tmp_path) == ("claude", "")
```

Also add console tests:
- `/model codex gpt-5.6` saves `default_agent`.
- A new `WhylineConsoleApp(root)` whose repo saved `codex` starts with `session.agent == "codex"`.

- [ ] **Step 2: Run, see them fail.**

- [ ] **Step 3: Implement**

`model.load(root)` returns the whole dict. Today callers treat every key as an agent name, so `default_agent` must not be mistaken for one: make `load` drop the key `default_agent` from the dict it returns, and read it through `default_agent(root)` instead.

```python
def default_agent(root: Path) -> str | None:
    try:
        data = json.loads(paths.model_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    value = data.get("default_agent")
    return value if isinstance(value, str) and value else None


def set_default_agent(root: Path, agent: str) -> None:
    target = paths.model_path(root)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        data = {}
    data["default_agent"] = agent
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def global_path() -> Path:
    return Path.home() / ".whyline" / "console.json"


def load_global() -> dict:
    try:
        data = json.loads(global_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def save_global(agent: str, model_name: str) -> None:
    data = load_global()
    data["default_agent"] = agent
    models = data.setdefault("models", {})
    if model_name:
        models[agent] = model_name
    else:
        models.pop(agent, None)
    global_path().parent.mkdir(parents=True, exist_ok=True)
    global_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def resolve(root: Path) -> tuple[str, str]:
    glob = load_global()
    agent = default_agent(root) or glob.get("default_agent") or "claude"
    chosen = load(root).get(agent) or (glob.get("models") or {}).get(agent) or ""
    return agent, chosen
```

`save` must keep `default_agent` when it writes: read the existing file's `default_agent` and put it back into the data before writing. Check `set_one`, which writes through `save`.

In `repl._model_event`, after `session.agent = agent`, call `model.set_default_agent(session.root, agent)`.

`WhylineConsoleApp.__init__` sets `self.session.agent = model.resolve(root)[0]`. So does `switch_repo` after changing root.

- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit** `feat: saved default agent per repo and for all repos (CB-1)`.

### Task 2: Inspecting and setting up a repo (no UI)

**Files:** Create `src/whyline/console/repo_setup.py`. Test `tests/console/test_repo_setup.py`.

**Interfaces:**
- `@dataclass(frozen=True) Inspection(path: Path, kind: str, outer: Path | None = None, missing: tuple[str, ...] = ())`.
  - `kind` is `"ready"`, `"needs_setup"`, `"home"` or `"nested"`.
  - `missing` lists the steps still to do, from `("folder", "git", "whyline", "agents")`.
- `inspect(path) -> Inspection`.
- `describe(inspection) -> str`: the confirmation text.
- `class SetupError(RuntimeError)` with `.step`.
- `setup(inspection, *, agents: list[str], progress) -> Path`: runs the missing steps, commits only what it created, and returns the repo root.

- [ ] **Step 1: Failing tests**

```python
import subprocess
from pathlib import Path

import pytest

from whyline.console import repo_setup as rs


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def test_home_and_nested_paths_are_refused(home, tmp_path):
    assert rs.inspect(home).kind == "home"
    outer = tmp_path / "outer"
    (outer / "sub").mkdir(parents=True)
    _git(outer, "init", "-q")
    got = rs.inspect(outer / "sub")
    assert got.kind == "nested" and got.outer == outer.resolve()


def test_a_missing_folder_needs_every_step(tmp_path):
    got = rs.inspect(tmp_path / "new")
    assert got.kind == "needs_setup" and got.missing == ("folder", "git", "whyline", "agents")
    assert "create the folder" in rs.describe(got) and "git init" in rs.describe(got)


def test_setup_creates_repo_and_commits_only_its_own_files(tmp_path, monkeypatch):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "notes.txt").write_text("the user's, uncommitted")
    lines = []

    def fake_prepare(root, agents):
        settings = root / ".whyline/relay/claude-settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("{}")
        return [settings]

    monkeypatch.setattr(rs, "_prepare_agents", fake_prepare)
    root = rs.setup(rs.inspect(target), agents=["claude"], progress=lines.append)
    assert root == target.resolve()
    committed = _git(root, "show", "--name-only", "--format=", "HEAD").split()
    assert "notes.txt" not in committed and ".whyline/relay/claude-settings.json" in committed
    assert _git(root, "log", "-1", "--format=%s").strip() == "chore: set up whyline"
    assert "notes.txt" in _git(root, "status", "--porcelain")
    assert rs.inspect(root).kind == "ready"
    assert "run git init" in lines


def test_a_failed_step_is_named_and_a_retry_finishes(tmp_path, monkeypatch):
    target = tmp_path / "proj2"
    calls = {"n": 0}
    real = rs._whyline_init

    def flaky(root):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(root)

    monkeypatch.setattr(rs, "_whyline_init", flaky)
    monkeypatch.setattr(rs, "_prepare_agents", lambda root, agents: [])
    with pytest.raises(rs.SetupError) as failed:
        rs.setup(rs.inspect(target), agents=[], progress=lambda l: None)
    assert failed.value.step == "whyline"
    assert rs.inspect(target).missing == ("whyline", "agents")
    rs.setup(rs.inspect(target), agents=[], progress=lambda l: None)
    assert rs.inspect(target).kind == "ready"
```

- [ ] **Step 2: Run, see them fail.**

- [ ] **Step 3: Implement**

```python
"""Inspecting a path the user typed into the context bar, and setting it up
for whyline step by step (spec section 3). No UI here."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

STEPS = ("folder", "git", "whyline", "agents")
_WORDS = {"folder": "create the folder", "git": "run git init", "whyline": "run whyline init",
          "agents": "write the relay's agent permission settings"}


@dataclass(frozen=True)
class Inspection:
    path: Path
    kind: str
    outer: Path | None = None
    missing: tuple[str, ...] = ()


class SetupError(RuntimeError):
    def __init__(self, step: str, error: Exception):
        super().__init__(f"Setting up stopped at '{_WORDS[step]}': {error}")
        self.step = step


def _git_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    while not probe.exists():
        probe = probe.parent
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=probe, capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 else None


def inspect(path: Path) -> Inspection:
    path = Path(path).expanduser().resolve()
    if path == Path.home().resolve():
        return Inspection(path, "home")
    root = _git_root(path)
    if root is not None and root != path:
        return Inspection(path, "nested", outer=root)
    missing = []
    if not path.exists():
        missing.append("folder")
    if root is None:
        missing.append("git")
    if not (path / ".whyline").is_dir():
        missing.append("whyline")
    if not (path / ".whyline/relay/claude-settings.json").exists():
        missing.append("agents")
    return Inspection(path, "ready" if not missing else "needs_setup", missing=tuple(missing))


def describe(inspection: Inspection) -> str:
    shown = inspection.path.as_posix().replace(Path.home().as_posix(), "~", 1)
    steps = " · ".join(_WORDS[s] for s in inspection.missing)
    return (f"Set up {shown} for whyline? This will: {steps} · make a first commit with "
            "those files. Antigravity will ask separately whether to trust this folder.")


def _whyline_init(root: Path) -> list[Path]:
    before = set(p for p in root.rglob("*") if p.is_file()) if root.exists() else set()
    subprocess.run(["whyline", "init", "--yes"], cwd=root, check=True, capture_output=True, text=True)
    return [p for p in root.rglob("*") if p.is_file() and p not in before and ".git" not in p.parts]


def _prepare_agents(root: Path, agents: list[str]) -> list[Path]:
    from whyline.console import relay_ops
    return relay_ops.prepare_agents(root, agents)


def setup(inspection: Inspection, *, agents: list[str], progress) -> Path:
    from whyline_relay import gitcheck

    root = inspection.path
    created: list[Path] = []
    for step in inspection.missing:
        progress(_WORDS[step])
        try:
            if step == "folder":
                root.mkdir(parents=True, exist_ok=True)
            elif step == "git":
                subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True,
                               capture_output=True, text=True)
            elif step == "whyline":
                created += _whyline_init(root)
            elif step == "agents":
                created += _prepare_agents(root, agents)
        except (OSError, subprocess.CalledProcessError) as error:
            raise SetupError(step, error) from error
    if created:
        gitcheck.commit_paths(root, created, "chore: set up whyline")
    return root
```

`relay_ops.prepare_agents` (0.3.32) commits its own files. When called from `setup`, that commit happens before `chore: set up whyline`. That's acceptable: both commits contain only setup's files. If you prefer one commit, add a `commit: bool = True` parameter to `prepare_agents` and pass `commit=False` here. Do that, and update its test.

Progress lines are exactly the step words: `create the folder`, `run git init`, `run whyline init`, `write the relay's agent permission settings`.

- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit** `feat: inspect and set up a repo step by step (CB-2)`.

### Task 3: The context bar

**Files:** Modify `src/whyline/console/tui.py`. Test `tests/console/test_context_bar.py`.

**Interfaces:**
- the `#context-bar` row (Horizontal), with `#cb-agent` (Select), `#cb-model` (Input), `#cb-repo` (Input), `#cb-global` (Checkbox) and `#cb-save` (Button);
- `_cb_dirty() -> bool`, `_cb_refresh()` and `_cb_save()`.

- [ ] **Step 1: Failing tests** (stub `account.agent_status` with claude and codex available and grok unavailable; `HOME` → tmp):

```python
async def test_save_is_greyed_until_something_changes(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        save = app.query_one("#cb-save", tui.Button)
        assert save.disabled
        app.query_one("#cb-model", tui.Input).value = "gpt-5.6"
        await pilot.pause()
        assert not save.disabled


async def test_save_sets_the_repo_default_and_optionally_global(tmp_path, home):
    root = _repo(tmp_path)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-model", tui.Input).value = "gpt-5.6"
        app.query_one("#cb-global", tui.Checkbox).value = True
        await pilot.click("#cb-save")
        await pilot.pause()
        assert app.session.agent == "codex" and app.query_one("#cb-save", tui.Button).disabled
    assert model.resolve(root) == ("codex", "gpt-5.6")
    assert model.load_global()["default_agent"] == "codex"


async def test_an_unavailable_agent_snaps_back_with_its_hint(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-agent", tui.Select).value = "!grok"
        await pilot.pause()
        assert app.query_one("#cb-agent", tui.Select).value == "claude"
        assert any("Run /login grok" in l for l in _lines(app))


async def test_switching_repo_is_refused_while_a_job_runs_but_agent_saves(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        monkeypatch.setattr(app, "_relay_running", lambda: True)
        app.query_one("#cb-agent", tui.Select).value = "codex"
        app.query_one("#cb-repo", tui.Input).value = str(tmp_path / "other")
        await pilot.click("#cb-save")
        await pilot.pause()
        assert app.session.agent == "codex" and app.session.root == tmp_path / "repo"
        assert any("Finish or stop the current job before switching repo" in l for l in _lines(app))


async def test_a_new_folder_is_set_up_after_one_confirmation(tmp_path, monkeypatch):
    from whyline.console import repo_setup
    ran = []
    monkeypatch.setattr(repo_setup, "setup", lambda insp, agents, progress: ran.append(insp.path) or insp.path)
    monkeypatch.setattr(tui, "switch_repo", lambda session, root: setattr(session, "root", root)
                        or tui.SessionEvent(kind="output", text=f"Now in {root}"))
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#cb-repo", tui.Input).value = str(tmp_path / "fresh")
        await pilot.click("#cb-save")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        assert "git init" in str(app.screen.query_one("Label").renderable)
        await pilot.click("#confirm")
        for _ in range(50):
            if ran:
                break
            await pilot.pause(0.05)
    assert ran == [(tmp_path / "fresh").resolve()]


async def test_the_bar_fits_80_columns(tmp_path):
    app = tui.WhylineConsoleApp(root=_repo(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.query_one("#cb-save").region.right <= 80
```

(`_repo(tmp_path)` creates `tmp_path/"repo"` with `git init` and `.whyline/`; `_lines` reads the transcript through `app._main`.)

- [ ] **Step 2: Run, see them fail.**

- [ ] **Step 3: Implement**

`compose`: below the `#modes` Horizontal, yield:

```python
        yield Horizontal(
            Label("Agent", id="cb-agent-label"), Select([], allow_blank=False, id="cb-agent"),
            Label("Model", id="cb-model-label"), Input(placeholder="default", id="cb-model"),
            Label("Repo", id="cb-repo-label"), Input(id="cb-repo"),
            Checkbox("all repos", id="cb-global"),
            Button("Save", id="cb-save", disabled=True),
            id="context-bar",
        )
```

Remove the old `#context` Static and its updates. CSS:
- `#context-bar { height: auto; }`;
- `#cb-agent { width: 20; }`;
- `#cb-model { width: 18; }`;
- `#cb-repo { width: 1fr; }`;
- `#context-bar Label { padding: 1 0 0 1; }`.

In `on_resize`, when `self.size.width < 100`, set the three labels to `A`, `M` and `R` and `#cb-agent` width to 14. Otherwise restore them.

Behaviour:
- `_cb_refresh()` fills the agent Select from `account.agent_status(root)`: available agents as `(f"{a} · {label}", a)`, then unavailable ones as `(f"{a} · {label}", f"!{a}")`. It sets the values from `model.resolve(root)` and the repo path (`~`-shortened). It records the saved tuple `(agent, model, repo)` in `self._cb_saved`, and disables Save. Call it from `on_mount`, after `/model`, after `switch_repo`, and after Run's setup steps change the agent.
- `on_select_changed` for `#cb-agent`: a value starting with `!` renders the agent's hint (`account.agent_status(root)[name]["hint"]`) and resets the value to `self._cb_saved[0]`. Otherwise, `#cb-model` shows that agent's saved model. Then update Save's `disabled = not self._cb_dirty()`.
- `on_input_changed` for `#cb-model` and `#cb-repo`: update Save the same way. `on_input_submitted` for them calls `_cb_save()`.
- `_cb_save()`:
  1. If the agent or model changed, reject a model containing whitespace with an error line. Otherwise call `model.set_default_agent`, then `model.set_one(root, agent, model)` (or remove the key when empty). If `#cb-global` is ticked, call `model.save_global(agent, model)`. Set `session.agent`, render `Default for this repo: <agent> · <model or "default model">` plus ` (also for every repo without its own)` when global, untick the box, and call `_cb_refresh()`.
  2. If the repo path changed:
     - When a relay, plan or brainstorm job runs (`self._relay_running()`, `self._plan_state`, `self._busy_text`), render "Finish or stop the current job before switching repo." and reset the repo field.
     - Otherwise call `repo_setup.inspect(path)`:
       - `home` → the existing `_HOME_REFUSAL`;
       - `nested` → `"<path> is inside the repository <outer>. Use <outer>, or pick a folder outside it."`;
       - `ready` → the existing `self._switch_repo(path, …)` confirmation flow;
       - `needs_setup` → `ConfirmScreen(repo_setup.describe(insp), "Set up")`. On yes, run `repo_setup.setup(insp, agents=relay_ops.relay_agents(root=None, which=shutil.which), progress=...)` in a worker, render each step as `setup · <step>`, then switch to the repo (call `switch_repo` directly; the user already confirmed), then `self._with_antigravity("antigravity" in relay_ops.relay_agents(insp.path), lambda ok: None)`. A `SetupError` renders its message.

- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit** `feat: context bar for agent, model and repo (CB-3)`.

### Task 4: Remove Command mode; `/` runs whyline commands

**Files:** Modify `src/whyline/console/session.py`, `src/whyline/console/repl.py`, `src/whyline/console/tui.py`. Test `tests/console/test_slash_whyline.py`, and update existing tests that use `mode == "command"`.

**Interfaces:**
- `repl.whyline_subcommands() -> dict[str, str]`: name → help, read from `whyline.cli.build_parser()`'s subparsers action.
- `ConsoleSession.mode` defaults to `"chat"`.
- `handle_slash_command` routes unknown `/word …` to `run_whyline_command` when `word` is a whyline subcommand.

- [ ] **Step 1: Failing tests**

```python
from whyline.console import adapters, repl
from whyline.console.session import ConsoleSession, SessionEvent


def test_whyline_subcommands_come_from_the_parser():
    subs = repl.whyline_subcommands()
    assert "timeline" in subs and "note" in subs and subs["note"]


def test_slash_runs_a_whyline_command(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(adapters, "run_whyline_command",
                        lambda argv: ran.append(argv) or SessionEvent(kind="output", text="ok"))
    session = ConsoleSession(root=tmp_path)
    assert session.mode == "chat"
    event = repl.handle_slash_command(session, "/timeline --limit 5")
    assert ran == [["timeline", "--limit", "5"]] and event.text == "ok"


def test_console_commands_win_over_whyline_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "run_whyline_command", lambda argv: (_ for _ in ()).throw(AssertionError))
    event = repl.handle_slash_command(ConsoleSession(root=tmp_path), "/status")
    assert event is not None  # the console's own /status


def test_route_command_explains(tmp_path):
    event = repl.handle_slash_command(ConsoleSession(root=tmp_path), "/route command")
    assert "Command mode is gone" in event.text and "/timeline" in event.text


def test_help_lists_whyline_commands(tmp_path):
    text = repl.handle_slash_command(ConsoleSession(root=tmp_path), "/help").text
    assert "whyline commands" in text and "/timeline" in text
```

Add a TUI test: the mode buttons are exactly `#mode-chat`, `#mode-relay` and `#mode-agents` (no `#mode-command`), and the console opens with `session.mode == "chat"`. Add another: typing only `/` shows `#slash-hint`, containing `/timeline`, and the next keystroke hides it.

- [ ] **Step 2: Run, see them fail.**

- [ ] **Step 3: Implement**

- `session.py`: `mode: str = "chat"  # "chat" | "relay" | "agents"`.
- `repl.py`:

```python
def whyline_subcommands() -> dict[str, str]:
    import argparse

    from whyline import cli

    parser = cli.build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {name: (choice.description or getattr(choice, "help", "") or "")
                    for name, choice in action.choices.items()}
    return {}
```

  Use the subparser's `help=` text where `description` is empty: collect it from `action._choices_actions` (each has `.dest` and `.help`).

  At the end of `handle_slash_command`, before `return None`:

```python
    if text.startswith("/"):
        head, *rest = text[1:].split()
        if head in whyline_subcommands() and head != "console":
            return adapters.run_whyline_command([head, *rest])
```

  - `/route`: accept `chat`, `relay` and `agents`. For `command`, return the explanation text from the spec. Update its usage string and the `/route` help line.
  - `/help`: append a section `whyline commands (type them with /):`, one line per subcommand (`/<name>  <help>`).
  - `_dispatch`: remove the `command` branch. A mode value `"command"` coming from anywhere (an old caller or a test) is treated as `"chat"`.
  - The keyboard REPL's prompt and help text: replace any mention of "command" mode.
- `tui.py`:
  - `_MODES = ("chat", "relay", "agents")`;
  - compose `Button("Chat", id="mode-chat")`, `Button("Relay", id="mode-relay")` and `Button("Agents", id="mode-agents")`;
  - `_placeholder` has no command branch;
  - a `Static("", id="slash-hint")` above the input row (`display: none`). `on_input_changed` for `#prompt` shows it with `/status /timeline /note /decisions /handoff /model /repo /help` when the value is exactly `/`, and hides it otherwise.

  Until Agents mode exists, `#mode-agents` routes to `/route agents`, which renders "Agents mode arrives in a later release." and stays in the current mode.

- [ ] **Step 4: Run** `uv run pytest -q`. Existing tests that set `session.mode = "command"` or click `#mode-command` must change: use `/<command>` in chat mode instead. Keep what they check; change only how they get there.
- [ ] **Step 5: Commit** `feat: retire Command mode; /<command> runs whyline anywhere (CB-4)`.

### Task 5: Each mode shows only its own buttons

**Files:** Modify `src/whyline/console/tui.py`. Test `tests/console/test_mode_buttons.py`.

**Interfaces:** `_MODE_BUTTONS = {"chat": (...), "relay": (...), "agents": (...)}`, `_SHARED_BUTTONS = ("stop", "help", "copy")`, and `_sync_mode_buttons()`.

- [ ] **Step 1: Failing test**

```python
import pytest

from whyline.console import tui

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]


@pytest.mark.parametrize("mode, visible", [
    ("chat", {"model", "brainstorm", "history", "stop", "help", "copy"}),
    ("relay", {"relay-run", "relay-plan", "relay-setup", "relay-resume", "stop", "help", "copy"}),
])
async def test_each_mode_shows_only_its_buttons_within_80_columns(tmp_path, mode, visible):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.session.mode = mode
        app._sync_mode_indicator()
        await pilot.pause()
        shown = {b.id for b in app.query("#controls Button") if b.display}
        assert shown == visible
        assert all(app.query_one(f"#{b}").region.right <= 80 for b in shown)
        assert app.query_one("#attach").display is (mode == "chat")
```

- [ ] **Step 2: Run, see it fail.**

- [ ] **Step 3: Implement**

```python
_MODE_BUTTONS = {
    "chat": ("model", "brainstorm", "history"),
    "relay": ("relay-run", "relay-plan", "relay-setup", "relay-resume"),
    "agents": ("agents-new", "agents-list", "agents-runs", "agents-scheduler"),
}
_SHARED_BUTTONS = ("stop", "help", "copy")


    def _sync_mode_buttons(self) -> None:
        wanted = set(_MODE_BUTTONS.get(self.session.mode, ())) | set(_SHARED_BUTTONS)
        for button in self._main("#controls").query(Button):
            button.display = button.id in wanted
        self._main("#attach").display = self.session.mode == "chat"
```

- Call it at the end of `_sync_mode_indicator`.
- In `_sync_relay_buttons`, delete any `display` assignments it has; keep its enable and disable logic.
- Ordering: put the shared buttons **last** in `#controls`, so each mode's own buttons come first.

- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit** `feat: each mode shows only its own buttons (CB-5)`.

### Task 6: Release whyline 0.3.35 (human)

Bump to `0.3.35`, write `docs/releases/v0.3.35.md` (the context bar with saved defaults, setting up a new repo from the bar, Command mode replaced by `/<command>`, mode-specific buttons), run the suite with and without agent CLIs on PATH, push, tag `v0.3.35`, watch every OS, confirm PyPI, and `uv tool upgrade whyline`.

**Check by hand first:**
- switch to `~/tmp-new-project` via the bar and accept the setup;
- `/timeline` works in Chat;
- Relay mode shows only Run, Plan, Set up and Resume, plus Stop, Help and Copy.

---

## Running this plan with the relay

In `~/agentdock`, with roles `implementer = "antigravity"` and `reviewer = "codex"`, commit `.whyline/relay/cb.md` with tasks CB-1 to CB-5. Each says "Implement 'Task N' from `docs/superpowers/plans/2026-10-05-console-context-bar.md`; tests first; no dependence on installed agent CLIs or the real home folder; Windows-safe paths; fits 80 columns; never push, tag or publish". Run `start --plan .whyline/relay/cb.md` in Relay mode.

After this ships, the Agents plan's Task 8 only needs to add its four buttons to `_MODE_BUTTONS["agents"]` and its screens; the visibility logic already exists.
