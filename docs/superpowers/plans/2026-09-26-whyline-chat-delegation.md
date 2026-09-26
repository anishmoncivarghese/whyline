# Terminal Chat Orchestrator (whyline side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bare `whyline` (no arguments) execs into `whyline-relay chat` if whyline-relay is installed, so typing `whyline` really does start the chat REPL; if it isn't installed, `whyline` falls through to its existing usage output, unchanged.

**Architecture:** A single, small change to `main()`'s existing "no command given" branch in `cli.py`, using the same `which`/`exec_fn`-resolved-at-call-time pattern `runner.py` already uses and already tests via monkeypatching — no new pattern introduced, no permission or adapter logic duplicated from whyline-relay.

**Tech Stack:** Python 3.11+, stdlib only (`os`, `shutil`). No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-26-chat-repl-design.md`, Decision D2 and the "Architecture" section's `whyline`-delegation bullet.

## Global Constraints

- No new runtime dependency.
- No permission/bypass logic is duplicated into whyline — this plan only ever execs into `whyline-relay`, never invokes an agent directly.
- `which`/`exec_fn` must be resolved at call time, not bound as default arguments (the exact defect `runner.py`'s own comments document being bitten by twice already) — a test must be able to monkeypatch them without risking a real exec during the test run.
- Every existing test must still pass after every task.

---

### Task 1: `whyline` execs into `whyline-relay chat` when no command is given

**Files:**
- Modify: `src/whyline/cli.py`
- Test: `tests/test_cli_chat_delegation.py` (new file)

**Interfaces:**
- Produces: `cli.exec_into_chat(which=None, exec_fn=None) -> bool` — returns `True` and (in real use) never returns again if it exec'd; returns `False` if whyline-relay is not installed, so the caller can fall through to the existing usage output. `main()`'s existing "no command" branch calls this first.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_chat_delegation.py`:

```python
from whyline import cli


def test_execs_into_whyline_relay_chat_when_installed():
    calls = []
    result = cli.exec_into_chat(
        which=lambda name: f"/usr/bin/{name}" if name == "whyline-relay" else None,
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
    )
    assert result is True
    assert calls == [("whyline-relay", ["whyline-relay", "chat"])]


def test_falls_through_when_whyline_relay_is_not_installed():
    calls = []
    result = cli.exec_into_chat(
        which=lambda name: None,
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
    )
    assert result is False
    assert calls == []


def test_main_with_no_args_delegates_to_chat(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "exec_into_chat",
        lambda which=None, exec_fn=None: calls.append("called") or True,
    )
    code = cli.main([])
    assert calls == ["called"]
    assert code == cli.EXIT_OK


def test_main_with_no_args_prints_usage_when_whyline_relay_is_absent(monkeypatch, capsys):
    monkeypatch.setattr(cli, "exec_into_chat", lambda which=None, exec_fn=None: False)
    code = cli.main([])
    assert code == cli.EXIT_USAGE
    assert capsys.readouterr().err  # existing usage text, unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_chat_delegation.py -v`
Expected: FAIL — `cli.exec_into_chat` does not exist yet, and `main()` does
not call it.

- [ ] **Step 3: Implement**

In `src/whyline/cli.py`, add near the top of the file (after the existing
imports — `cli.py` already imports `os`/`shutil`-style modules for other
commands; add `import os` and `import shutil` at module level if either is
not already imported there):

```python
def _which(name: str) -> str | None:
    return shutil.which(name)


def _exec(binary: str, argv: list[str]) -> None:
    os.execvp(binary, argv)


def exec_into_chat(which=None, exec_fn=None) -> bool:
    """Replace this process with `whyline-relay chat`, if it's installed.

    `which`/`exec_fn` are resolved here, not as default arguments -- binding
    them in the signature would capture the function objects at import time,
    so a test's monkeypatch would silently have no effect and this would exec
    the real whyline-relay during a test run. `runner.py` documents this
    exact defect happening twice already; the same shape is used here on
    purpose.
    """
    which = which if which is not None else _which
    exec_fn = exec_fn if exec_fn is not None else _exec
    binary = which("whyline-relay")
    if binary is None:
        return False
    exec_fn("whyline-relay", ["whyline-relay", "chat"])
    return True  # unreachable when exec_fn is the real os.execvp
```

Change `main()`. Replace:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return COMMANDS[args.command](args)
```

with:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        if exec_into_chat():
            return EXIT_OK
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return COMMANDS[args.command](args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_chat_delegation.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Fix a pre-existing test this change makes unsafe**

`tests/test_cli.py` already has `test_no_command_is_a_usage_error`, which
calls `cli.main([])` completely unmocked. In a real environment with
whyline-relay actually installed on PATH (common — it's the companion tool
this whole feature depends on), that call would now reach the real
`exec_into_chat()`, find the real `whyline-relay` binary, and really
`os.execvp` into it, replacing the test process itself — the exact
"hung a test run" failure mode `runner.py`'s own comments already warn about
elsewhere in this codebase. Find it in `tests/test_cli.py` (search for
`test_no_command_is_a_usage_error`) and change:

```python
def test_no_command_is_a_usage_error():
    assert cli.main([]) == cli.EXIT_USAGE
```

to:

```python
def test_no_command_is_a_usage_error(monkeypatch):
    # Real environments often have whyline-relay on PATH, which would make an
    # unmocked cli.main([]) actually exec into it (replacing this test
    # process) rather than reach the usage-error path this test checks.
    monkeypatch.setattr(cli, "exec_into_chat", lambda which=None, exec_fn=None: False)
    assert cli.main([]) == cli.EXIT_USAGE
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline/cli.py tests/test_cli.py tests/test_cli_chat_delegation.py
git commit -m "feat: bare whyline execs into whyline-relay chat"
```

---

### Task 2: README — document that bare `whyline` starts chat

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the line documenting `run`'s supported agents (added in 0.3.4: "`run`
supports Claude Code, Codex, Antigravity (`agy`), and Grok..."). Add a new
line immediately after it:

```markdown
- **Typing `whyline` with no arguments starts an interactive chat REPL** (`whyline-relay chat`, if whyline-relay is installed) — free text goes to a default agent, `/claude`/`/codex`/`/agy`/`/grok` targets one directly, and every agent shares one conversation history for the repo. See whyline-relay's own README, "Chat: talk to any configured agent from one terminal," for the full picture (permissions, auto-commit, meta-commands). If whyline-relay isn't installed, `whyline` with no arguments prints its usual usage instead.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document that bare whyline starts the chat REPL"
```

## Not in this plan

- **The chat REPL itself** — built in whyline-relay, plan `2026-09-26-relay-chat-repl.md`. This plan's delegation works correctly once that plan ships a real `chat` subcommand; it can be built and tested independently before or after, since it only depends on `whyline-relay`'s binary name and its `chat` subcommand existing, not on any of that plan's internals.
