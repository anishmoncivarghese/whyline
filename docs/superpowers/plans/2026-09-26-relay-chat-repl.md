# Terminal Chat Orchestrator (whyline-relay side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `whyline-relay chat` starts an interactive REPL where free text goes to a fixed default agent, `/claude`/`/codex`/`/agy`/`/grok` targets one agent directly, agentic turns (edits, commands, commits) run under each agent's existing permission floor, and every turn is saved to one shared, per-repo history all agents draw on.

**Architecture:** Reuses whyline-relay's existing `adapters/` (permission-enforced commands) and `agents.py` (subprocess supervision) unchanged in their safety-relevant behavior. Adds: a `capture` mode to `agents.run()` so a turn's response can be read back instead of only teed to a log; an `extract_response` field per adapter to pull the clean final answer out of that captured output; a new `chatlog.py` for the shared, token-budget-capped history; and a new `chat.py` for the REPL loop itself, wired into `cli.py` as a new `chat` subcommand.

**Tech Stack:** Python 3.11+, stdlib only (`tempfile`, `json`, `argparse`). No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-26-chat-repl-design.md`

## Global Constraints

- No new runtime dependency.
- `agents.run()`'s process-group, heartbeat, timeout, and Ctrl+C handling are reused unchanged — only its `capture`/return-type surface changes.
- claude/codex always work in chat with zero relay config present (their managed defaults); agy/grok only work in chat if `.whyline/relay/config.toml` already configures them — chat never invents a separate, weaker permission set (spec D5).
- Every agentic turn that leaves the tree dirty is auto-committed via the existing `gitcheck.commit_all` — no new commit logic (spec D6).
- Shared history is the verbatim, capped tail of the transcript — no summarization (spec D4).
- Every existing test must still pass after every task.

---

### Task 1: `agents.py` — split `capture` from `echo`, and return `RunResult`

**Files:**
- Modify: `src/whyline_relay/agents.py`
- Modify: `src/whyline_relay/loop.py` (no behavior change — confirms the one existing caller is unaffected)
- Test: `tests/test_agents.py`

**Interfaces:**
- Produces: `agents.RunResult` (a `NamedTuple` with fields `exit_code: int`, `output: str | None`). `agents.run(..., capture: bool = False) -> RunResult`. `output` is `None` when `capture=False`; the full buffered stdout text when `capture=True`. Heartbeat behavior (gated on the existing `echo` flag) is unaffected by `capture`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agents.py`:

```python
def test_run_returns_a_runresult_with_no_output_by_default(tmp_path: Path):
    result = agents.run(
        [sys.executable, FAKE, "review", str(tmp_path)],
        "the prompt",
        cwd=tmp_path,
        log_path=tmp_path / "run.log",
        timeout_seconds=30,
        which=lambda name: name,
        echo=False,
    )
    assert isinstance(result, agents.RunResult)
    assert result.exit_code == 0
    assert result.output is None


def test_run_captures_stdout_when_capture_is_true(tmp_path: Path):
    result = agents.run(
        [sys.executable, FAKE, "review", str(tmp_path)],
        "the prompt",
        cwd=tmp_path,
        log_path=tmp_path / "run.log",
        timeout_seconds=30,
        which=lambda name: name,
        echo=False,
        capture=True,
    )
    assert result.exit_code == 0
    assert "fake-agent review received" in result.output


def test_capture_suppresses_raw_echo_but_not_the_heartbeat(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.setenv("WHYLINE_RELAY_HEARTBEAT_SECONDS", "0.05")
    result = agents.run(
        [
            sys.executable,
            "-c",
            "import time; print('started', flush=True); time.sleep(0.18)",
        ],
        "p",
        cwd=tmp_path,
        log_path=tmp_path / "run.log",
        timeout_seconds=30,
        which=lambda name: name,
        agent_name="claude",
        capture=True,
    )
    output = capsys.readouterr().out
    assert "started" not in output
    heartbeat = r"\[\d{2}:\d{2}:\d{2}\] \.\.\. claude still running \(\d+s\)"
    assert len(re.findall(heartbeat, output)) >= 2
    assert "started\n" in result.output
```

Update the two existing tests that unpack a bare int, since the return type
changes for every caller:

```python
def test_run_streams_output_to_the_log(tmp_path: Path):
    log = tmp_path / "run.log"
    result = agents.run(
        [sys.executable, FAKE, "review", str(tmp_path)],
        "the prompt",
        cwd=tmp_path,
        log_path=log,
        timeout_seconds=30,
        which=lambda name: name,
        echo=False,
    )
    assert result.exit_code == 0
    assert "fake-agent review received" in log.read_text()


def test_run_returns_the_agents_exit_code(tmp_path: Path):
    result = agents.run(
        [sys.executable, FAKE, "fail", str(tmp_path)],
        "p",
        cwd=tmp_path,
        log_path=tmp_path / "run.log",
        timeout_seconds=30,
        which=lambda name: name,
        echo=False,
    )
    assert result.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agents.py -v`
Expected: FAIL — `agents.run` currently returns a bare `int`; `result.exit_code`
raises `AttributeError`, and there is no `agents.RunResult` or `capture`
parameter yet.

- [ ] **Step 3: Implement**

In `src/whyline_relay/agents.py`, add near the top (after the existing
imports, before `KILL_GRACE_SECONDS`):

```python
from typing import NamedTuple


class RunResult(NamedTuple):
    exit_code: int
    output: str | None
```

Change `run`'s signature and body. Replace:

```python
def run(
    command: list[str],
    prompt: str,
    *,
    cwd: Path,
    log_path: Path,
    timeout_seconds: int,
    which=None,
    echo: bool = True,
    agent_name: str | None = None,
) -> int:
```

with:

```python
def run(
    command: list[str],
    prompt: str,
    *,
    cwd: Path,
    log_path: Path,
    timeout_seconds: int,
    which=None,
    echo: bool = True,
    agent_name: str | None = None,
    capture: bool = False,
) -> RunResult:
```

Inside the function, before the `try:` block that opens `log_path`, add:

```python
    buffer: list[str] = [] if capture else None
```

In the line-reading loop, replace:

```python
        with log_path.open("w", encoding="utf-8") as log:
            for line in process.stdout or ():
                log.write(line)
                log.flush()
                if echo:
                    with heartbeat_condition:
                        last_output = time.monotonic()
                        heartbeat_condition.notify()
                    with _terminal_lock:
                        sys.stdout.write(line)
                        sys.stdout.flush()
        code = process.wait()
```

with:

```python
        with log_path.open("w", encoding="utf-8") as log:
            for line in process.stdout or ():
                log.write(line)
                log.flush()
                if capture:
                    buffer.append(line)
                if echo:
                    with heartbeat_condition:
                        last_output = time.monotonic()
                        heartbeat_condition.notify()
                    if not capture:
                        with _terminal_lock:
                            sys.stdout.write(line)
                            sys.stdout.flush()
        code = process.wait()
```

Finally, replace the function's last line:

```python
    return code
```

with:

```python
    return RunResult(code, "".join(buffer) if capture else None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agents.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Confirm the one existing caller is unaffected**

Read `src/whyline_relay/loop.py` around its `agents.run(...)` call (currently
near line 145) and confirm it does not assign or use the return value at all
(routing there comes from `whyline handoff` records, per `agents.py`'s own
module docstring). No code change needed in `loop.py` — this step is a
verification, not an edit.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/agents.py tests/test_agents.py
git commit -m "feat: agents.run can capture output without echoing it raw"
```

---

### Task 2: `init.py` — a shared, idempotent relay-gitignore writer

**Files:**
- Modify: `src/whyline_relay/init.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Produces: `init.RELAY_GITIGNORE_LINES: tuple[str, ...]` and
  `init.ensure_relay_gitignore(root: Path) -> None` — writes
  `.whyline/relay/.gitignore` with the full canonical content if it does not
  already exist; does nothing if it does. Used by this task's own `init.run`
  and, later in this plan, by `chat.py`'s first-launch setup (so `chat`
  produces a correct `.gitignore` even in a repo that never ran
  `whyline-relay init`).

- [ ] **Step 1: Write the failing test**

First, read `tests/test_init.py` for its existing fixture/assertion style
around the generated `.gitignore` file (search for `.gitignore` in that
file) so the new test matches it. Then add:

```python
def test_ensure_relay_gitignore_creates_it_when_absent(tmp_path: Path):
    from whyline_relay import init

    init.ensure_relay_gitignore(tmp_path)
    content = (tmp_path / ".whyline" / "relay" / ".gitignore").read_text()
    assert content == (
        "logs/\nstate.json\nSTOP\nrunning.json\nchat.json\nchat-history.jsonl\n"
    )


def test_ensure_relay_gitignore_leaves_an_existing_one_alone(tmp_path: Path):
    from whyline_relay import init

    target = tmp_path / ".whyline" / "relay"
    target.mkdir(parents=True)
    (target / ".gitignore").write_text("custom\n")
    init.ensure_relay_gitignore(tmp_path)
    assert (target / ".gitignore").read_text() == "custom\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init.py -k ensure_relay_gitignore -v`
Expected: FAIL — `init.ensure_relay_gitignore` does not exist yet.

- [ ] **Step 3: Implement**

In `src/whyline_relay/init.py`, find the line:

```python
        (relay / ".gitignore", "logs/\nstate.json\nSTOP\nrunning.json\n"),
```

Replace the whole `generated = [...]` list construction so the `.gitignore`
entry is produced by a new, reusable function instead of an inline literal.
Add, near the top of the module (after imports, before the function that
builds `generated`):

```python
RELAY_GITIGNORE_LINES = (
    "logs/",
    "state.json",
    "STOP",
    "running.json",
    "chat.json",
    "chat-history.jsonl",
)


def ensure_relay_gitignore(root: Path) -> None:
    """Write .whyline/relay/.gitignore with the canonical content, once.

    Both `whyline-relay init` and `chat`'s own first-launch setup call this,
    since chat can run in a repo that never ran `init` at all -- whichever
    runs first creates a correct file; the other is then a no-op.
    """
    path = root / ".whyline" / "relay" / ".gitignore"
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(RELAY_GITIGNORE_LINES) + "\n")
```

Then change the `generated` list's `.gitignore` line to stop writing it
inline — remove this entry from `generated` entirely:

```python
        (relay / ".gitignore", "logs/\nstate.json\nSTOP\nrunning.json\n"),
```

and, in `init.run` (wherever `generated` is written out, right after that
loop finishes writing every other generated file), add:

```python
    ensure_relay_gitignore(root)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_init.py -v`
Expected: PASS, all of them. If an existing test asserted the old 4-line
`.gitignore` content directly, update its expected string to the new 6-line
content from `RELAY_GITIGNORE_LINES` (search `tests/test_init.py` for
`"logs/\nstate.json"` to find it).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/init.py tests/test_init.py
git commit -m "feat: relay .gitignore also covers chat's own state files"
```

---

### Task 3: Adapters gain `extract_response` and `uses_output_file`

**Files:**
- Modify: `src/whyline_relay/adapters/base.py`
- Modify: `src/whyline_relay/adapters/claude.py`
- Modify: `src/whyline_relay/adapters/codex.py`
- Modify: `src/whyline_relay/adapters/generic.py`
- Test: `tests/test_adapters_extract_response.py` (new file)

**Interfaces:**
- Consumes: none from earlier tasks.
- Produces: `Adapter.extract_response: Callable[[str], str]` and
  `Adapter.uses_output_file: bool` on every adapter (`claude.ADAPTER`,
  `codex.ADAPTER`, `adapters.GENERIC`). Later tasks call
  `config.adapter_for(settings, agent).extract_response(text)` and check
  `.uses_output_file` to decide whether `text` should come from a temp file
  or from `RunResult.output`.

`Adapter` is a frozen dataclass with no default values on any field, so
every one of its three constructors (`claude.py`, `codex.py`, `generic.py`)
must be updated in this same task — the class cannot be changed one
constructor at a time without breaking the other two's `Adapter(...)` calls.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_adapters_extract_response.py`:

```python
import json

from whyline_relay import adapters
from whyline_relay.adapters import claude as claude_adapter
from whyline_relay.adapters import codex as codex_adapter


def test_claude_extracts_the_result_field():
    captured = (
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"pong","permission_denials":[]}\n'
    )
    assert claude_adapter.ADAPTER.extract_response(captured) == "pong"


def test_claude_falls_back_to_last_line_detail_on_malformed_json():
    captured = "not json at all\n"
    assert claude_adapter.ADAPTER.extract_response(captured) == "not json at all"


def test_claude_does_not_use_an_output_file():
    assert claude_adapter.ADAPTER.uses_output_file is False


def test_codex_strips_whitespace_from_the_output_file_contents():
    assert codex_adapter.ADAPTER.extract_response("  pong\n") == "pong"


def test_codex_uses_an_output_file():
    assert codex_adapter.ADAPTER.uses_output_file is True


def test_generic_tries_result_then_response_then_text_then_message():
    assert adapters.GENERIC.extract_response('{"result":"a"}') == "a"
    assert adapters.GENERIC.extract_response('{"response":"b"}') == "b"
    assert adapters.GENERIC.extract_response('{"text":"c"}') == "c"
    assert adapters.GENERIC.extract_response('{"message":"d"}') == "d"


def test_generic_verified_agy_and_grok_shapes():
    # Exact shapes captured from real `agy`/`grok` invocations this session.
    grok_output = json.dumps({"text": "pong", "stopReason": "end_turn"})
    agy_output = json.dumps({"status": "SUCCESS", "response": "pong\n"})
    assert adapters.GENERIC.extract_response(grok_output) == "pong"
    assert adapters.GENERIC.extract_response(agy_output).strip() == "pong"


def test_generic_falls_back_to_last_line_detail_when_no_known_field():
    captured = '{"unrelated_field": "x"}\n'
    assert adapters.GENERIC.extract_response(captured) == '{"unrelated_field": "x"}'


def test_generic_does_not_use_an_output_file():
    assert adapters.GENERIC.uses_output_file is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_adapters_extract_response.py -v`
Expected: FAIL — `Adapter.__init__()` does not accept `extract_response`,
`uses_output_file` does not exist, `claude_adapter`/`codex_adapter` have no
`ADAPTER.extract_response`.

- [ ] **Step 3: Implement `base.py`**

In `src/whyline_relay/adapters/base.py`, add near `last_line_detail` (note:
`last_line_detail` itself returns a prefixed, quoted fragment meant for
error messages -- `; its last output was: "..."` -- so this new function
does not call it; it builds its own plain fallback string the same way):

```python
def extract_or_fallback(text: str, field_names: tuple[str, ...]) -> str:
    """Try each field name in order against the last JSON line; else return
    the raw last non-blank line. Shared by claude and generic."""
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and lines[-1].strip().startswith("{"):
        try:
            parsed = json.loads(lines[-1])
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            for field in field_names:
                value = parsed.get(field)
                if isinstance(value, str):
                    return value
    if lines:
        return "".join(ch for ch in lines[-1].strip() if ch.isprintable())
    return ""
```

Add `import json` to `base.py`'s existing imports if not already present.

Change the `Adapter` dataclass. Replace:

```python
@dataclass(frozen=True)
class Adapter:
    name: str
    default_command: tuple[str, ...] | None
    binary: str | None
    login_argv: tuple[str, ...] | None
    login_fix: str | None
    permission_files: Callable[[str], dict[str, str]]
    diagnose: Callable[[str], str]
    manages: Manages
    model_flag: tuple[str, ...] | None
```

with:

```python
@dataclass(frozen=True)
class Adapter:
    name: str
    default_command: tuple[str, ...] | None
    binary: str | None
    login_argv: tuple[str, ...] | None
    login_fix: str | None
    permission_files: Callable[[str], dict[str, str]]
    diagnose: Callable[[str], str]
    manages: Manages
    model_flag: tuple[str, ...] | None
    extract_response: Callable[[str], str]
    uses_output_file: bool
```

- [ ] **Step 4: Implement `claude.py`**

In `src/whyline_relay/adapters/claude.py`, add near the top-level functions
(after `diagnose`):

```python
def extract_response(text: str) -> str:
    return extract_or_fallback(text, ("result",))
```

Update the import line:

```python
from whyline_relay.adapters.base import Adapter, Manages, last_line_detail
```

to:

```python
from whyline_relay.adapters.base import (
    Adapter,
    Manages,
    extract_or_fallback,
    last_line_detail,
)
```

Add the two new fields to the `ADAPTER = Adapter(...)` call:

```python
    manages=Manages(True, True, True),
    model_flag=("--model",),
)
```

becomes:

```python
    manages=Manages(True, True, True),
    model_flag=("--model",),
    extract_response=extract_response,
    uses_output_file=False,
)
```

- [ ] **Step 5: Implement `codex.py`**

In `src/whyline_relay/adapters/codex.py`, add:

```python
def extract_response(text: str) -> str:
    return text.strip()
```

Add the two new fields to its `ADAPTER = Adapter(...)` call:

```python
    manages=Manages(True, True, True),
    model_flag=("--model",),
)
```

becomes:

```python
    manages=Manages(True, True, True),
    model_flag=("--model",),
    extract_response=extract_response,
    uses_output_file=True,
)
```

- [ ] **Step 6: Implement `generic.py`**

In `src/whyline_relay/adapters/generic.py`, replace the whole file with:

```python
"""Generic adapter for explicitly configured agent commands."""

from __future__ import annotations

from whyline_relay.adapters.base import Adapter, Manages, extract_or_fallback, last_line_detail

GENERIC_RESPONSE_FIELDS = ("result", "response", "text", "message")


def extract_response(text: str) -> str:
    return extract_or_fallback(text, GENERIC_RESPONSE_FIELDS)


ADAPTER = Adapter(
    name="generic",
    default_command=None,
    binary=None,
    login_argv=None,
    login_fix=None,
    permission_files=lambda stack: {},
    diagnose=last_line_detail,
    manages=Manages(False, False, False),
    model_flag=None,
    extract_response=extract_response,
    uses_output_file=False,
)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_adapters_extract_response.py -v`
Expected: PASS, all of them.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/whyline_relay/adapters/ tests/test_adapters_extract_response.py
git commit -m "feat: adapters can extract a clean final response from a turn"
```

---

### Task 4: `chatlog.py` — shared, capped conversation history

**Files:**
- Create: `src/whyline_relay/chatlog.py`
- Test: `tests/test_chatlog.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `chatlog.append(root: Path, *, agent: str, prompt: str, response: str, files_changed: int, ok: bool) -> None`. `chatlog.load(root: Path) -> list[dict]` (every turn, oldest first, corrupt lines skipped). `chatlog.recent(root: Path, token_budget: int = 1200) -> str` (formatted plain text of the newest turns that fit the budget, oldest of those first). `chatlog.clear(root: Path) -> None` (deletes the history file; a no-op if it doesn't exist).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chatlog.py`:

```python
import json
from pathlib import Path

from whyline_relay import chatlog


def test_append_creates_the_file_and_writes_one_json_line(tmp_path: Path):
    chatlog.append(
        tmp_path, agent="claude", prompt="hi", response="hello",
        files_changed=0, ok=True,
    )
    path = tmp_path / ".whyline" / "relay" / "chat-history.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["agent"] == "claude"
    assert record["prompt"] == "hi"
    assert record["response"] == "hello"
    assert record["files_changed"] == 0
    assert record["ok"] is True
    assert "timestamp" in record


def test_load_returns_no_turns_when_the_file_is_absent(tmp_path: Path):
    assert chatlog.load(tmp_path) == []


def test_load_skips_a_corrupted_line_without_crashing(tmp_path: Path):
    chatlog.append(
        tmp_path, agent="codex", prompt="a", response="b",
        files_changed=1, ok=True,
    )
    path = tmp_path / ".whyline" / "relay" / "chat-history.jsonl"
    with path.open("a") as handle:
        handle.write("not json\n")
    chatlog.append(
        tmp_path, agent="codex", prompt="c", response="d",
        files_changed=0, ok=True,
    )
    turns = chatlog.load(tmp_path)
    assert [t["prompt"] for t in turns] == ["a", "c"]


def test_recent_returns_empty_string_with_no_history(tmp_path: Path):
    assert chatlog.recent(tmp_path) == ""


def test_recent_includes_every_turn_within_budget(tmp_path: Path):
    chatlog.append(
        tmp_path, agent="claude", prompt="q1", response="a1",
        files_changed=0, ok=True,
    )
    chatlog.append(
        tmp_path, agent="codex", prompt="q2", response="a2",
        files_changed=0, ok=True,
    )
    text = chatlog.recent(tmp_path, token_budget=1200)
    assert "q1" in text
    assert "a1" in text
    assert "q2" in text
    assert "a2" in text
    # oldest first, matching a normal transcript's reading order
    assert text.index("q1") < text.index("q2")


def test_recent_drops_the_oldest_turns_first_once_over_budget(tmp_path: Path):
    for i in range(50):
        chatlog.append(
            tmp_path, agent="claude", prompt=f"question {i}" * 20,
            response=f"answer {i}" * 20, files_changed=0, ok=True,
        )
    text = chatlog.recent(tmp_path, token_budget=200)
    assert "question 49" in text
    assert "question 0" * 20 not in text


def test_clear_removes_the_history_file(tmp_path: Path):
    chatlog.append(
        tmp_path, agent="claude", prompt="q", response="a",
        files_changed=0, ok=True,
    )
    chatlog.clear(tmp_path)
    assert chatlog.load(tmp_path) == []
    assert not (tmp_path / ".whyline" / "relay" / "chat-history.jsonl").exists()


def test_clear_is_a_no_op_when_there_is_no_history(tmp_path: Path):
    chatlog.clear(tmp_path)  # must not raise
    assert chatlog.load(tmp_path) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chatlog.py -v`
Expected: FAIL — `whyline_relay.chatlog` does not exist.

- [ ] **Step 3: Implement**

Create `src/whyline_relay/chatlog.py`:

```python
"""Shared, per-repo conversation history for `whyline-relay chat`.

One JSON object per line, oldest first, append-only. Never imports or reads
anything from whyline itself -- same rule `whyline_model.py` already follows,
so ownership of this file never contends with any other tool.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from math import ceil
from pathlib import Path

DEFAULT_TOKEN_BUDGET = 1200


def _path(root: Path) -> Path:
    return root / ".whyline" / "relay" / "chat-history.jsonl"


def _approximate_tokens(text: str) -> int:
    """Conservative, dependency-free estimate: bytes over three, not a real
    tokeniser. Every caller must treat this as approximate."""
    return ceil(len(text.encode("utf-8")) / 3)


def append(
    root: Path,
    *,
    agent: str,
    prompt: str,
    response: str,
    files_changed: int,
    ok: bool,
) -> None:
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "agent": agent,
        "prompt": prompt,
        "response": response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "files_changed": files_changed,
        "ok": ok,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def load(root: Path) -> list[dict]:
    path = _path(root)
    if not path.exists():
        return []
    turns: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            turns.append(json.loads(line))
        except ValueError:
            continue
    return turns


def _format_turn(turn: dict) -> str:
    return f"[{turn['agent']}] {turn['prompt']}\n{turn['response']}"


def recent(root: Path, token_budget: int = DEFAULT_TOKEN_BUDGET) -> str:
    turns = load(root)
    if not turns:
        return ""
    kept: list[str] = []
    used = 0
    for turn in reversed(turns):
        formatted = _format_turn(turn)
        cost = _approximate_tokens(formatted)
        if kept and used + cost > token_budget:
            break
        kept.append(formatted)
        used += cost
    return "\n\n".join(reversed(kept))


def clear(root: Path) -> None:
    """Delete this repo's chat history, if any. Safe to call when absent."""
    path = _path(root)
    if path.exists():
        path.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chatlog.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/chatlog.py tests/test_chatlog.py
git commit -m "feat: shared, capped chat history for the chat REPL"
```

---

### Task 5: `chat.py` — first-launch setup wizard

**Files:**
- Create: `src/whyline_relay/chat.py`
- Test: `tests/test_chat_setup.py`

**Interfaces:**
- Consumes: `init.ensure_relay_gitignore` (Task 2).
- Produces: `chat.CHAT_AGENTS = ("claude", "codex", "agy", "grok")`.
  `chat.chat_config_path(root: Path) -> Path` (`.whyline/relay/chat.json`).
  `chat.load_default_agent(root: Path) -> str | None` (`None` if unset).
  `chat.save_default_agent(root: Path, agent: str) -> None`.
  `chat.run_setup_wizard(root: Path, *, which=None, input_fn=None, print_fn=None) -> str` — detects installed agents, prompts for a default, saves it, returns the chosen agent. Raises `chat.NoAgentsInstalled` if none of `CHAT_AGENTS` are found.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chat_setup.py`:

```python
from pathlib import Path

import pytest

from whyline_relay import chat


def test_load_default_agent_is_none_when_unset(tmp_path: Path):
    assert chat.load_default_agent(tmp_path) is None


def test_save_and_load_default_agent_round_trip(tmp_path: Path):
    chat.save_default_agent(tmp_path, "codex")
    assert chat.load_default_agent(tmp_path) == "codex"


def test_setup_wizard_detects_installed_agents_and_saves_the_choice(tmp_path: Path):
    which = lambda name: f"/bin/{name}" if name in ("claude", "codex") else None
    answers = iter(["codex"])
    chosen = chat.run_setup_wizard(
        tmp_path,
        which=which,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert chosen == "codex"
    assert chat.load_default_agent(tmp_path) == "codex"


def test_setup_wizard_refuses_a_choice_that_is_not_installed(tmp_path: Path):
    which = lambda name: "/bin/claude" if name == "claude" else None
    answers = iter(["grok", "claude"])
    chosen = chat.run_setup_wizard(
        tmp_path,
        which=which,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert chosen == "claude"


def test_setup_wizard_raises_when_nothing_is_installed(tmp_path: Path):
    with pytest.raises(chat.NoAgentsInstalled):
        chat.run_setup_wizard(
            tmp_path,
            which=lambda name: None,
            input_fn=lambda prompt="": "",
            print_fn=lambda *a, **k: None,
        )


def test_setup_wizard_writes_the_relay_gitignore(tmp_path: Path):
    which = lambda name: "/bin/claude" if name == "claude" else None
    chat.run_setup_wizard(
        tmp_path,
        which=which,
        input_fn=lambda prompt="": "claude",
        print_fn=lambda *a, **k: None,
    )
    gitignore = tmp_path / ".whyline" / "relay" / ".gitignore"
    assert "chat.json" in gitignore.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_setup.py -v`
Expected: FAIL — `whyline_relay.chat` does not exist.

- [ ] **Step 3: Implement**

Create `src/whyline_relay/chat.py`:

```python
"""The `whyline-relay chat` REPL: setup, routing, and the turn pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from whyline_relay import init

CHAT_AGENTS = ("claude", "codex", "agy", "grok")


class NoAgentsInstalled(RuntimeError):
    """None of claude/codex/agy/grok are on PATH."""


def chat_config_path(root: Path) -> Path:
    return root / ".whyline" / "relay" / "chat.json"


def load_default_agent(root: Path) -> str | None:
    path = chat_config_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    agent = data.get("default_agent")
    return agent if isinstance(agent, str) else None


def save_default_agent(root: Path, agent: str) -> None:
    path = chat_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"default_agent": agent}) + "\n")


def run_setup_wizard(
    root: Path,
    *,
    which=None,
    input_fn=None,
    print_fn=None,
) -> str:
    which = which if which is not None else shutil.which
    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print

    installed = [name for name in CHAT_AGENTS if which(name) is not None]
    if not installed:
        raise NoAgentsInstalled(
            "none of claude, codex, agy, grok were found on PATH"
        )
    missing = [name for name in CHAT_AGENTS if name not in installed]
    print_fn(f"Detected: {', '.join(installed)}.")
    if missing:
        print_fn(f"Not found: {', '.join(missing)}.")

    default_hint = installed[0]
    while True:
        answer = input_fn(f"Pick your default agent [{default_hint}]: ").strip()
        chosen = answer or default_hint
        if chosen in installed:
            break
        print_fn(f"{chosen} is not installed here -- pick one of: {', '.join(installed)}")

    save_default_agent(root, chosen)
    init.ensure_relay_gitignore(root)
    print_fn(f"Saved. Starting chat -- default agent is {chosen}.")
    return chosen
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_setup.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/chat.py tests/test_chat_setup.py
git commit -m "feat: chat's first-launch setup wizard"
```

---

### Task 6: `chat.py` — the turn pipeline

**Files:**
- Modify: `src/whyline_relay/chat.py`
- Test: `tests/test_chat_turn.py`

**Interfaces:**
- Consumes: `agents.run`/`agents.RunResult`/`agents.rate_limited` (Task 1 and existing), `Adapter.extract_response`/`.uses_output_file` (Task 3), `chatlog.append`/`chatlog.recent` (Task 4), `config.load`/`config.adapter_for`/`config.relay_dir` (existing), `gitcheck.commit_all` (existing) and `gitcheck.commit_stat` (this task).
- Produces: `chat.AgentUnavailable` (raised when a generic agent has no
  configured command). `chat.CHAT_TIMEOUT_SECONDS = 300`.
  `chat.resolve_command(settings, agent: str) -> list[str]` (raises
  `AgentUnavailable` if unconfigured). `chat.run_turn(root: Path, *, agent: str, prompt: str, settings=None, run_fn=None) -> dict` — runs one full turn (build prompt with history, run, extract, log, commit) and returns the appended `chatlog` record: the same shape `chatlog.append` writes, plus `"rate_limited": bool` (from the existing `agents.rate_limited()`) and `"diff_stat": str` set only when a commit happened. `run_turn` itself does not catch `agents.AgentMissing`/`agents.AgentTimeout` -- those propagate to the caller (`chat.repl`, Task 7), which is what decides how to show them without crashing.

- [ ] **Step 1: Write the failing tests**

First, add a helper to `gitcheck.py` this task needs (it doesn't exist yet):
read `src/whyline_relay/gitcheck.py`'s existing `_git` helper and `commit_all`
function, then add, right after `commit_all`:

```python
def commit_stat(root: Path) -> str:
    """The diffstat of HEAD against its parent (or, for a root commit,
    against nothing). Deliberately reads the *commit*, not the working tree:
    `git diff --stat` never shows a brand-new untracked file, only changes to
    already-tracked ones -- but a committed new file shows correctly here,
    since by then it's part of the commit being described."""
    return _git(root, "show", "--stat", "--format=", "HEAD")
```

Add a test for it to `tests/test_gitcheck.py`, using that file's own existing
`repo` fixture (it already creates a git repo in `tmp_path` with one
committed file, `README.md`):

```python
def test_commit_stat_reports_a_new_file_in_the_latest_commit(repo: Path):
    (repo / "new.txt").write_text("made by an agent\n")
    gitcheck.commit_all(repo, "add new.txt")
    assert "new.txt" in gitcheck.commit_stat(repo)


def test_commit_stat_reports_a_change_to_a_tracked_file(repo: Path):
    (repo / "README.md").write_text("changed\n")
    gitcheck.commit_all(repo, "change readme")
    assert "README.md" in gitcheck.commit_stat(repo)
```

Now create `tests/test_chat_turn.py`:

```python
import json
import subprocess
from pathlib import Path

import pytest

from whyline_relay import chat, chatlog, config


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    (root / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def test_resolve_command_works_for_claude_with_no_config_file(tmp_path: Path):
    settings = config.load(tmp_path)
    command = chat.resolve_command(settings, "claude")
    assert command[0] == "claude"


def test_resolve_command_refuses_an_unconfigured_generic_agent(tmp_path: Path):
    settings = config.load(tmp_path)
    with pytest.raises(chat.AgentUnavailable):
        chat.resolve_command(settings, "grok")


def test_resolve_command_works_for_a_configured_generic_agent(tmp_path: Path):
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    (relay / "config.toml").write_text(
        '[agents.grok]\nadapter = "generic"\ncommand = ["grok", "-p"]\n'
    )
    settings = config.load(tmp_path)
    assert chat.resolve_command(settings, "grok") == ["grok", "-p"]


def test_run_turn_captures_the_response_and_logs_it(tmp_path: Path, monkeypatch):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult

        return RunResult(0, '{"type":"result","result":"pong"}\n')

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings, run_fn=fake_run_fn
    )
    assert record["response"] == "pong"
    assert record["agent"] == "claude"
    assert record["ok"] is True
    turns = chatlog.load(tmp_path)
    assert len(turns) == 1
    assert turns[0]["response"] == "pong"


def test_run_turn_commits_when_the_agent_leaves_the_tree_dirty(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult

        (tmp_path / "new.txt").write_text("made by the agent\n")
        return RunResult(0, '{"type":"result","result":"done"}\n')

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="add a file", settings=settings, run_fn=fake_run_fn
    )
    assert record["files_changed"] == 1
    assert "new.txt" in record["diff_stat"]
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout
    assert "chat: claude turn" in log


def test_run_turn_does_not_commit_when_the_tree_is_clean(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult

        return RunResult(0, '{"type":"result","result":"just an answer"}\n')

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="what is this", settings=settings, run_fn=fake_run_fn
    )
    assert record["files_changed"] == 0
    assert "diff_stat" not in record


def test_run_turn_marks_a_reported_failure_but_still_logs_it(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult

        return RunResult(1, "agent crashed\n")

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="do it", settings=settings, run_fn=fake_run_fn
    )
    assert record["ok"] is False


def test_run_turn_flags_a_rate_limited_response(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult

        return RunResult(1, "You have exceeded your usage limit. Try again later.\n")

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="do it", settings=settings, run_fn=fake_run_fn
    )
    assert record["rate_limited"] is True


def test_run_turn_includes_recent_history_in_the_prompt(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    chatlog.append(
        tmp_path, agent="codex", prompt="earlier question",
        response="earlier answer", files_changed=0, ok=True,
    )
    seen_prompts = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult

        seen_prompts.append(prompt)
        return RunResult(0, '{"type":"result","result":"ok"}\n')

    chat.run_turn(
        tmp_path, agent="claude", prompt="new question", settings=settings, run_fn=fake_run_fn
    )
    assert "earlier question" in seen_prompts[0]
    assert "new question" in seen_prompts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_turn.py tests/test_gitcheck.py -v`
Expected: FAIL — `chat.resolve_command`/`chat.run_turn`/`chat.AgentUnavailable`
and `gitcheck.commit_stat` do not exist yet.

- [ ] **Step 3: Implement `gitcheck.commit_stat`**

Add the function shown in Step 1 to `src/whyline_relay/gitcheck.py`, right
after `commit_all`.

- [ ] **Step 4: Implement `chat.py`'s turn pipeline**

Add to `src/whyline_relay/chat.py` (extending the imports at the top first):

```python
import tempfile
from pathlib import Path

from whyline_relay import agents, chatlog, config, gitcheck, init
```

(`init` is already imported from Task 5; add `agents`, `chatlog`, `config`,
`gitcheck` alongside it, and `tempfile` to the stdlib imports.)

Then add:

```python
CHAT_TIMEOUT_SECONDS = 300


class AgentUnavailable(RuntimeError):
    """This agent has no command configured for chat in this repo."""


def resolve_command(settings: "config.Config", agent: str) -> list[str]:
    command = settings.agents.get(agent)
    if command is None:
        raise AgentUnavailable(
            f"{agent} is not configured for chat in this repo -- see "
            "`whyline-relay doctor` and the README, "
            f"'Using {agent} today', to add it to .whyline/relay/config.toml."
        )
    return list(command)


def _build_prompt(root: Path, new_input: str) -> str:
    history = chatlog.recent(root)
    return f"{history}\n\n{new_input}" if history else new_input


def run_turn(
    root: Path,
    *,
    agent: str,
    prompt: str,
    settings: "config.Config | None" = None,
    run_fn=None,
) -> dict:
    settings = settings if settings is not None else config.load(root)
    run_fn = run_fn if run_fn is not None else agents.run
    command = resolve_command(settings, agent)
    adapter = config.adapter_for(settings, agent)
    full_prompt = _build_prompt(root, prompt)

    turn_command = list(command)
    output_file: Path | None = None
    if adapter.uses_output_file:
        handle = tempfile.NamedTemporaryFile(
            prefix="whyline-relay-chat-", suffix=".txt", delete=False
        )
        output_file = Path(handle.name)
        handle.close()
        turn_command += ["-o", str(output_file)]

    log_path = config.relay_dir(root) / "logs" / "chat-last-turn.log"
    result = run_fn(
        turn_command,
        full_prompt,
        cwd=root,
        log_path=log_path,
        timeout_seconds=CHAT_TIMEOUT_SECONDS,
        capture=True,
        echo=True,
        agent_name=agent,
    )

    if adapter.uses_output_file:
        raw = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
    else:
        raw = result.output or ""
    response = adapter.extract_response(raw)
    ok = result.exit_code == 0
    rate_limited = agents.rate_limited(raw)

    # commit_all stages everything and no-ops (returns False) when the tree
    # is already clean -- safe to call unconditionally rather than checking
    # is_dirty first, and it's the only reliable way to see a brand-new
    # untracked file in the resulting stat (git diff on the working tree
    # never shows untracked files; the committed diff always does).
    committed = gitcheck.commit_all(root, f"chat: {agent} turn")
    diff_stat = gitcheck.commit_stat(root) if committed else ""
    files_changed = max(len(diff_stat.splitlines()) - 1, 0) if diff_stat else 0

    chatlog.append(
        root, agent=agent, prompt=prompt, response=response,
        files_changed=files_changed, ok=ok,
    )
    record = {
        "agent": agent,
        "prompt": prompt,
        "response": response,
        "files_changed": files_changed,
        "ok": ok,
        "rate_limited": rate_limited,
    }
    if committed:
        record["diff_stat"] = diff_stat
    return record
```

Note: `config.relay_dir` already exists (confirmed in `config.py`) and
returns `root / ".whyline" / "relay"` -- reused here for the log path rather
than inventing a new path helper.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_turn.py tests/test_gitcheck.py -v`
Expected: PASS, all of them.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/chat.py src/whyline_relay/gitcheck.py tests/test_chat_turn.py tests/test_gitcheck.py
git commit -m "feat: chat's turn pipeline -- run, extract, log, auto-commit"
```

---

### Task 7: `chat.py` — the REPL loop, meta-commands, and `cli.py` wiring

**Files:**
- Modify: `src/whyline_relay/chat.py`
- Modify: `src/whyline_relay/cli.py`
- Test: `tests/test_chat_repl.py`
- Test: `tests/test_cli_chat.py`

**Interfaces:**
- Consumes: everything from Tasks 5-6 (`run_setup_wizard`, `load_default_agent`, `run_turn`, `CHAT_AGENTS`).
- Produces: `chat.repl(root: Path, *, input_fn=None, print_fn=None, run_fn=None) -> None`. `cli.cmd_chat(args) -> int`. `whyline-relay chat` on the command line.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chat_repl.py`:

```python
from pathlib import Path

from whyline_relay import chat, chatlog


def _repo(tmp_path: Path) -> Path:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _fake_run_fn(command, prompt, **kwargs):
    from whyline_relay.agents import RunResult

    return RunResult(0, '{"type":"result","result":"an answer"}\n')


def test_repl_runs_setup_once_then_routes_to_the_default_agent(tmp_path: Path):
    root = _repo(tmp_path)
    which = lambda name: "/bin/claude" if name == "claude" else None
    lines = iter(["hello there", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=_fake_run_fn,
        which=which,
        setup_answers=iter(["claude"]),
    )
    assert any("an answer" in line for line in printed)
    assert chatlog.load(root)[0]["agent"] == "claude"


def test_repl_prefix_targets_a_specific_agent_without_changing_the_default(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    lines = iter(["/codex what changed", "/exit"])
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: None,
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert chatlog.load(root)[0]["agent"] == "codex"
    assert chat.load_default_agent(root) == "claude"


def test_repl_default_command_changes_the_saved_default(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    lines = iter(["/default codex", "/exit"])
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: None,
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert chat.load_default_agent(root) == "codex"


def test_repl_continues_after_a_missing_agent(tmp_path: Path):
    from whyline_relay import agents

    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")

    def raise_missing(command, prompt, **kwargs):
        raise agents.AgentMissing("claude is not installed or not on PATH")

    lines = iter(["hello", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=raise_missing,
        which=lambda name: "/bin/x",
    )
    assert any("not installed" in line for line in printed)
    assert chatlog.load(root) == []


def test_repl_continues_after_a_timed_out_turn(tmp_path: Path):
    from whyline_relay import agents

    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")

    def raise_timeout(command, prompt, **kwargs):
        raise agents.AgentTimeout("claude exceeded 300s and was terminated")

    lines = iter(["hello", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=raise_timeout,
        which=lambda name: "/bin/x",
    )
    assert any("try again" in line.lower() for line in printed)


def test_repl_flags_a_rate_limited_turn(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")

    def fake_rate_limited(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult

        return RunResult(1, "You have exceeded your usage limit. Try again later.\n")

    lines = iter(["hello", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=fake_rate_limited,
        which=lambda name: "/bin/x",
    )
    assert any("rate-limited" in line for line in printed)


def test_repl_unknown_slash_command_is_rejected_without_a_turn(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    lines = iter(["/notacommand", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert chatlog.load(root) == []
    assert any("Unknown command" in line for line in printed)


def test_repl_history_command_replays_the_transcript(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    chatlog.append(root, agent="claude", prompt="q", response="a", files_changed=0, ok=True)
    lines = iter(["/history", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert any("q" in line for line in printed)


def test_repl_clear_wipes_history_after_confirmation(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    chatlog.append(root, agent="claude", prompt="q", response="a", files_changed=0, ok=True)
    lines = iter(["/clear", "y", "/exit"])
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: None,
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert chatlog.load(root) == []
```

Create `tests/test_cli_chat.py`:

```python
import os
from pathlib import Path

from whyline_relay import cli


def test_chat_subcommand_is_registered():
    parser = cli.build_parser()
    args = parser.parse_args(["chat"])
    assert args.command == "chat"


def test_cmd_chat_calls_chat_repl(tmp_path: Path, monkeypatch):
    from whyline_relay import chat

    calls = []
    monkeypatch.setattr(chat, "repl", lambda root, **kwargs: calls.append(root))
    previous = os.getcwd()
    os.chdir(tmp_path)
    try:
        args = cli.build_parser().parse_args(["chat"])
        code = cli.cmd_chat(args)
    finally:
        os.chdir(previous)
    assert code == cli.EXIT_OK
    assert calls == [tmp_path.resolve()]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_repl.py tests/test_cli_chat.py -v`
Expected: FAIL — `chat.repl` and the `chat` subcommand do not exist yet.

- [ ] **Step 3: Implement `chat.py`'s REPL loop**

Add to `src/whyline_relay/chat.py`:

```python
SLASH_COMMANDS = ("/default", "/agents", "/history", "/clear", "/exit")


def _agent_status_lines(settings: "config.Config", which) -> list[str]:
    lines = []
    for name in CHAT_AGENTS:
        configured = name in settings.agents
        found = which(name) is not None
        if configured and found:
            state = "installed, configured"
        elif found:
            state = "installed, not configured for chat"
        elif configured:
            state = "configured, but not installed"
        else:
            state = "not available"
        lines.append(f"{name}: {state}")
    return lines


def repl(
    root: Path,
    *,
    input_fn=None,
    print_fn=None,
    run_fn=None,
    which=None,
    setup_answers=None,
) -> None:
    import shutil as _shutil

    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print
    which = which if which is not None else _shutil.which

    default_agent = load_default_agent(root)
    if default_agent is None:
        wizard_input = input_fn
        if setup_answers is not None:
            wizard_input = lambda prompt="": next(setup_answers)
        default_agent = run_setup_wizard(
            root, which=which, input_fn=wizard_input, print_fn=print_fn
        )

    settings = config.load(root)
    while True:
        line = input_fn("> ").strip()
        if not line:
            continue
        if line == "/exit":
            return
        if line.startswith("/") and line.split()[0] not in (
            *(f"/{a}" for a in CHAT_AGENTS),
            *SLASH_COMMANDS,
        ):
            print_fn(
                f"Unknown command: {line.split()[0]}. Try "
                + ", ".join(f"/{a}" for a in CHAT_AGENTS)
                + ", " + ", ".join(SLASH_COMMANDS) + "."
            )
            continue
        if line == "/agents":
            for status_line in _agent_status_lines(settings, which):
                print_fn(status_line)
            continue
        if line == "/history":
            for turn in chatlog.load(root):
                print_fn(f"[{turn['agent']}] {turn['prompt']}")
                print_fn(turn["response"])
            continue
        if line == "/clear":
            confirm = input_fn("Clear all chat history for this repo? [y/N] ").strip().lower()
            if confirm == "y":
                chatlog.clear(root)
                print_fn("History cleared.")
            continue
        if line.startswith("/default"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip() in CHAT_AGENTS:
                save_default_agent(root, parts[1].strip())
                default_agent = parts[1].strip()
                print_fn(f"Default agent is now {default_agent}.")
            else:
                print_fn(f"Usage: /default <{'|'.join(CHAT_AGENTS)}>")
            continue

        agent = default_agent
        prompt = line
        first_word = line.split(maxsplit=1)[0]
        if first_word in (f"/{a}" for a in CHAT_AGENTS):
            agent = first_word[1:]
            rest = line.split(maxsplit=1)
            prompt = rest[1] if len(rest) == 2 else ""

        try:
            record = run_turn(root, agent=agent, prompt=prompt, settings=settings, run_fn=run_fn)
        except AgentUnavailable as error:
            print_fn(str(error))
            continue
        except agents.AgentMissing as error:
            print_fn(str(error))
            continue
        except agents.AgentTimeout as error:
            print_fn(f"{error} -- try again, or /default another agent.")
            continue

        print_fn(f"[{record['agent']}] {record['response']}")
        if record["rate_limited"]:
            print_fn(f"{record['agent']} looks rate-limited -- /default another agent, or wait.")
        if record.get("diff_stat"):
            prefix = "" if record["ok"] else "⚠ "
            print_fn(f"{prefix}{record['diff_stat'].strip()}")
```

- [ ] **Step 4: Wire `cli.py`**

In `src/whyline_relay/cli.py`, add `chat` to the module-level import from
`whyline_relay` (alongside `adapters, agents, config, ...`):

```python
from whyline_relay import (
    adapters,
    agents,
    chat,
    config,
    failover,
    gitcheck,
    init,
    invocation,
    loop,
    notify,
    plan,
    planhelp,
    planner,
    preflight,
    prompts,
    remove,
    roles,
    running,
    state,
    whylinecmd,
)
```

In `build_parser()`, right before its final `return parser`, add:

```python
    chat_parser = subparsers.add_parser("chat", help="Start the interactive chat REPL")
    chat_parser.add_argument(
        "--repo", default=".", help="Use this repository root (default: current directory)."
    )
```

Add a new command function, near `cmd_status`:

```python
def cmd_chat(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    chat.repl(root)
    return EXIT_OK
```

Find `main()`'s dispatch table (search for where `"status": cmd_status` or
similar appears, likely a `COMMANDS = {...}` dict or an `if/elif` chain
dispatching on `args.command`) and add `"chat": cmd_chat` to it, matching
that exact existing style.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_repl.py tests/test_cli_chat.py -v`
Expected: PASS, all of them.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/chat.py src/whyline_relay/cli.py tests/test_chat_repl.py tests/test_cli_chat.py
git commit -m "feat: whyline-relay chat -- the REPL loop and CLI wiring"
```

---

### Task 8: README — document `whyline-relay chat`

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the "## Backup agents" heading (or the section immediately following
the generic-adapter recipes) and add a new section immediately before it:

````markdown
## Chat: talk to any configured agent from one terminal

`whyline-relay chat` starts an interactive REPL. Plain text goes to a fixed
default agent; `/claude`, `/codex`, `/agy`, `/grok` sends one message to that
agent specifically. Every agent shares one conversation history for the
repo, saved to `.whyline/relay/chat-history.jsonl` and replayed (capped to a
token budget, oldest turns dropped first) into every new turn's prompt --
so switching agents mid-conversation doesn't lose context.

First run in a repo asks which of claude/codex/agy/grok are actually
installed and which one should be the default; `/default <agent>` changes
it later.

Agentic turns (file edits, commands) run under each agent's *existing*
permission floor -- claude and codex always work here, even with no
`config.toml` in the repo, using their own managed defaults. `agy`/`grok`
only work in chat if they're already configured as a generic agent (see
"Using Antigravity today" / "Using Grok today" above) -- chat never invents
a separate, looser permission set. A turn that changes files is committed
automatically (`chat: <agent> turn`), and the diff-stat is printed right
after so you always see what changed before typing your next line.

Meta-commands: `/agents` (what's installed vs. configured), `/history`
(replay the saved transcript), `/clear` (wipe history, asks first), `/exit`.

```
$ whyline-relay chat
Detected: claude, codex, agy. Not found: grok.
Pick your default agent [claude]:
Saved. Starting chat -- default agent is claude.

> what does the auth middleware do?
[claude] The middleware in src/auth/...

> /codex refactor validate_token to raise instead of returning None
[codex] Done -- validate_token now raises AuthError...
  3 files changed, committed as a1b2c3d
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document whyline-relay chat"
```

## Not in this plan

- **whyline's own delegation** (`whyline` with no args execs into `whyline-relay chat`) -- a separate plan, `2026-09-26-whyline-chat-delegation.md`, independent of this one shipping first (it only needs `whyline-relay` to be installed and have a `chat` subcommand, which this plan produces).
- **Content-based auto-routing, summarized history, per-turn model selection, or a softer/harder permission set just for chat** -- all explicit non-goals in the spec.
