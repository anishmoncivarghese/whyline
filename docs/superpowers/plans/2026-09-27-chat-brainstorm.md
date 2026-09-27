# Chat Multi-Model Brainstorm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/brainstorm` in `whyline chat` runs a topic through however many models you pick, in three phases -- independent research, N rounds of combined review, then one designated model's final synthesis -- saving every model's own findings into one shared, real markdown file.

**Architecture:** A new module, `brainstorm.py`, built almost entirely on top of `chat.py`'s existing `run_turn` (reused unchanged as the execution primitive for every phase) plus one small, additive change to `run_turn`/`_execute_agent_call` for distinct per-phase commit messages. Pass-0 independence is structural (separate temp files per model, merged by plain Python code afterward), not merely requested in a prompt.

**Tech Stack:** Python 3.11+, stdlib only (`re` for slugifying). No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-27-chat-brainstorm-design.md`

## Global Constraints

- No new runtime dependency.
- `run_turn` is reused completely unchanged in every phase except for the one new, optional `commit_message` parameter -- no duplicated permission/failover/commit logic anywhere in `brainstorm.py`.
- Pass 0 is structurally blind: a model's independent research goes to its own private temp file, never the shared file, until every selected model has finished and the files are merged by plain code.
- A mid-brainstorm crash on one model never aborts the whole session -- the rest of the phase, and later phases, continue.
- Every existing test must still pass after every task.

**Note on this pairing:** this plan is built with Grok implementing and **Antigravity reviewing** -- a new pairing for this project (every prior plan used Codex as reviewer). If Antigravity's own review-turn behavior needs different handling than what's been observed from Codex (for example, around how it reports approval or runs the test suite), note that as a genuine decision via `whyline note`, the same as any other finding.

---

### Task 1: `chat.py` — `run_turn`/`_execute_agent_call` gain `commit_message`

**Files:**
- Modify: `src/whyline_relay/chat.py`
- Test: `tests/test_chat_turn.py`

**Interfaces:**
- Produces: `_execute_agent_call(..., *, commit_message: str | None = None)` and `run_turn(..., commit_message: str | None = None)`. When omitted, both behave exactly as today (`f"chat: {agent} turn"`). When given, that exact string is used as the commit message for whichever attempt actually gets committed (the primary agent, or its backup if failover switched).

- [ ] **Step 1: Write the failing tests**

First, read `tests/test_chat_turn.py`'s existing `_init_repo` helper (it creates a
real git repo in `tmp_path` with one committed `README.md`) so the new tests
below match it exactly. Add:

```python
def test_execute_agent_call_uses_a_custom_commit_message(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        (tmp_path / "new.txt").write_text("x\n")
        return RunResult(0, '{"type":"result","result":"done"}\n')

    chat._execute_agent_call(
        tmp_path, "claude", "prompt", "full prompt", settings, fake_run_fn,
        commit_message="custom: message",
    )
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=tmp_path,
        check=True, capture_output=True, text=True,
    ).stdout
    assert "custom: message" in log


def test_execute_agent_call_default_commit_message_is_unchanged(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        (tmp_path / "new.txt").write_text("x\n")
        return RunResult(0, '{"type":"result","result":"done"}\n')

    chat._execute_agent_call(
        tmp_path, "claude", "prompt", "full prompt", settings, fake_run_fn
    )
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=tmp_path,
        check=True, capture_output=True, text=True,
    ).stdout
    assert "chat: claude turn" in log


def test_run_turn_threads_a_custom_commit_message(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        (tmp_path / "new.txt").write_text("x\n")
        return RunResult(0, '{"type":"result","result":"done"}\n')

    chat.run_turn(
        tmp_path, agent="claude", prompt="p", settings=settings,
        run_fn=fake_run_fn, commit_message="brainstorm: claude research",
    )
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=tmp_path,
        check=True, capture_output=True, text=True,
    ).stdout
    assert "brainstorm: claude research" in log
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_turn.py -k commit_message -v`
Expected: FAIL — `_execute_agent_call`/`run_turn` do not accept `commit_message`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/chat.py`, change `_execute_agent_call`'s signature.
Replace:

```python
def _execute_agent_call(
    root: Path, agent: str, prompt: str, full_prompt: str,
    settings: "config.Config", run_fn,
) -> dict:
```

with:

```python
def _execute_agent_call(
    root: Path, agent: str, prompt: str, full_prompt: str,
    settings: "config.Config", run_fn, *, commit_message: str | None = None,
) -> dict:
```

Then, inside the same function, replace:

```python
    committed = gitcheck.commit_all(root, f"chat: {agent} turn")
```

with:

```python
    committed = gitcheck.commit_all(root, commit_message or f"chat: {agent} turn")
```

Change `run_turn`'s signature. Replace:

```python
def run_turn(
    root: Path,
    *,
    agent: str,
    prompt: str,
    settings: "config.Config | None" = None,
    run_fn=None,
    runner=subprocess.run,
) -> dict:
```

with:

```python
def run_turn(
    root: Path,
    *,
    agent: str,
    prompt: str,
    settings: "config.Config | None" = None,
    run_fn=None,
    runner=subprocess.run,
    commit_message: str | None = None,
) -> dict:
```

Inside `run_turn`, there are two calls to `_execute_agent_call`. Replace the
first:

```python
    attempt = _execute_agent_call(root, resolved, prompt, full_prompt, settings, run_fn)
```

with:

```python
    attempt = _execute_agent_call(
        root, resolved, prompt, full_prompt, settings, run_fn,
        commit_message=commit_message,
    )
```

And replace the second (inside the failover-retry branch):

```python
                attempt = _execute_agent_call(
                    root, backup, prompt, full_prompt, settings, run_fn
                )
```

with:

```python
                attempt = _execute_agent_call(
                    root, backup, prompt, full_prompt, settings, run_fn,
                    commit_message=commit_message,
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_turn.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/chat.py tests/test_chat_turn.py
git commit -m "feat: run_turn accepts a custom commit message"
```

---

### Task 2: `brainstorm.py` — setup questions, model parsing, availability check

**Files:**
- Create: `src/whyline_relay/brainstorm.py`
- Test: `tests/test_brainstorm_setup.py`

**Interfaces:**
- Consumes: `chat.resolve_command`, `chat.AgentUnavailable` (existing).
- Produces: `brainstorm.MODEL_OPTIONS` (tuple of `(number, agent_key, label)`). `brainstorm.slugify(topic: str) -> str`. `brainstorm.parse_model_selection(raw: str) -> list[tuple[str, str]] | None` (list of `(agent_key, label)`, `None` if nothing valid was named). `brainstorm.check_availability(settings, models) -> list[tuple[str, str]]` (the unavailable subset). `brainstorm.ask_brainstorm_setup(root, settings, *, input_fn=None, print_fn=None) -> dict | None` (`{"topic": str, "models": list[tuple[str,str]], "passes": int, "final_agent": str}`, or `None` if the user declined after an availability warning).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_brainstorm_setup.py`:

```python
from pathlib import Path

from whyline_relay import brainstorm, config


def test_slugify_lowercases_and_hyphenates():
    assert brainstorm.slugify("Best Caching Strategy!") == "best-caching-strategy"


def test_slugify_truncates_long_topics():
    long_topic = "x" * 200
    assert len(brainstorm.slugify(long_topic)) == 60


def test_slugify_never_returns_empty():
    assert brainstorm.slugify("!!!") == "topic"


def test_parse_model_selection_comma_separated():
    assert brainstorm.parse_model_selection("1,3") == [
        ("claude", "Claude"), ("agy", "Antigravity"),
    ]


def test_parse_model_selection_five_means_all():
    assert brainstorm.parse_model_selection("5") == [
        ("claude", "Claude"), ("codex", "Codex"),
        ("agy", "Antigravity"), ("grok", "Grok"),
    ]


def test_parse_model_selection_rejects_garbage():
    assert brainstorm.parse_model_selection("abc") is None
    assert brainstorm.parse_model_selection("6") is None
    assert brainstorm.parse_model_selection("") is None


def test_parse_model_selection_deduplicates():
    assert brainstorm.parse_model_selection("1,1,2") == [
        ("claude", "Claude"), ("codex", "Codex"),
    ]


def test_check_availability_reports_an_unconfigured_agent(tmp_path: Path):
    settings = config.load(tmp_path)
    unavailable = brainstorm.check_availability(
        settings, [("claude", "Claude"), ("grok", "Grok")]
    )
    assert unavailable == [("grok", "Grok")]


def test_check_availability_empty_when_all_configured(tmp_path: Path):
    settings = config.load(tmp_path)
    unavailable = brainstorm.check_availability(
        settings, [("claude", "Claude"), ("codex", "Codex")]
    )
    assert unavailable == []


def test_ask_brainstorm_setup_happy_path(tmp_path: Path):
    settings = config.load(tmp_path)
    answers = iter(["caching strategy", "1,2", "2", "claude"])
    result = brainstorm.ask_brainstorm_setup(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result == {
        "topic": "caching strategy",
        "models": [("claude", "Claude"), ("codex", "Codex")],
        "passes": 2,
        "final_agent": "claude",
    }


def test_ask_brainstorm_setup_rejects_empty_topic_then_accepts(tmp_path: Path):
    settings = config.load(tmp_path)
    answers = iter(["", "real topic", "1", "0", "claude"])
    result = brainstorm.ask_brainstorm_setup(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result["topic"] == "real topic"
    assert result["passes"] == 0


def test_ask_brainstorm_setup_defaults_passes_to_one(tmp_path: Path):
    settings = config.load(tmp_path)
    answers = iter(["topic", "1", "", "claude"])
    result = brainstorm.ask_brainstorm_setup(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result["passes"] == 1


def test_ask_brainstorm_setup_rejects_a_final_model_not_selected(tmp_path: Path):
    settings = config.load(tmp_path)
    answers = iter(["topic", "1", "1", "codex", "claude"])
    result = brainstorm.ask_brainstorm_setup(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result["final_agent"] == "claude"


def test_ask_brainstorm_setup_declines_and_aborts_on_unavailable_model(tmp_path: Path):
    settings = config.load(tmp_path)
    answers = iter(["topic", "1,4", "1", "claude", "n"])
    result = brainstorm.ask_brainstorm_setup(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result is None


def test_ask_brainstorm_setup_proceeds_without_an_unavailable_model(tmp_path: Path):
    settings = config.load(tmp_path)
    answers = iter(["topic", "1,4", "1", "claude", "y"])
    result = brainstorm.ask_brainstorm_setup(
        tmp_path, settings,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    assert result["models"] == [("claude", "Claude")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brainstorm_setup.py -v`
Expected: FAIL — `whyline_relay.brainstorm` does not exist.

- [ ] **Step 3: Implement**

Create `src/whyline_relay/brainstorm.py`:

```python
"""Multi-model brainstorming: independent research, combined review passes,
then one model's final synthesis -- all built on ordinary chat turns."""

from __future__ import annotations

import re
from pathlib import Path

from whyline_relay import chat, config

MODEL_OPTIONS = (
    ("1", "claude", "Claude"),
    ("2", "codex", "Codex"),
    ("3", "agy", "Antigravity"),
    ("4", "grok", "Grok"),
)


def slugify(topic: str) -> str:
    lowered = topic.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug[:60] or "topic"


def parse_model_selection(raw: str) -> list[tuple[str, str]] | None:
    """Parses "1,2,4" or "5" (all) into [(agent_key, label), ...], in
    MODEL_OPTIONS' own order. None if the input names nothing valid."""
    raw = raw.strip()
    if not raw:
        return None
    if raw == "5":
        return [(key, label) for _, key, label in MODEL_OPTIONS]
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    by_number = {number: (key, label) for number, key, label in MODEL_OPTIONS}
    chosen: list[tuple[str, str]] = []
    for token in tokens:
        if token not in by_number:
            return None
        pair = by_number[token]
        if pair not in chosen:
            chosen.append(pair)
    return chosen or None


def check_availability(
    settings: "config.Config", models: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """The subset of `models` chat.resolve_command would refuse right now --
    checked before any turn runs (spec B6)."""
    unavailable = []
    for agent_key, label in models:
        try:
            chat.resolve_command(settings, agent_key)
        except chat.AgentUnavailable:
            unavailable.append((agent_key, label))
    return unavailable


def ask_brainstorm_setup(
    root: Path,
    settings: "config.Config",
    *,
    input_fn=None,
    print_fn=None,
) -> dict | None:
    """Asks topic/models/passes/final-model, validating and reprompting.

    Returns {"topic", "models", "passes", "final_agent"}, or None if the
    user declined to proceed after an availability warning.
    """
    input_fn = input_fn if input_fn is not None else input
    print_fn = print_fn if print_fn is not None else print

    topic = ""
    while not topic:
        topic = input_fn("What should we research? ").strip()

    models: list[tuple[str, str]] | None = None
    while models is None:
        menu = ", ".join(f"{n} {label}" for n, _, label in MODEL_OPTIONS)
        raw = input_fn(f"Which models? ({menu}, 5 all): ").strip()
        models = parse_model_selection(raw)
        if models is None:
            print_fn(
                "Not understood -- use comma-separated numbers, e.g. 1,2, "
                "or 5 for all."
            )

    passes = None
    while passes is None:
        raw_passes = input_fn("How many passes? [1]: ").strip()
        if not raw_passes:
            passes = 1
        elif raw_passes.isdigit():
            passes = int(raw_passes)
        else:
            print_fn("Enter a whole number of passes (0 or more).")

    valid_keys = {key for key, _ in models}
    default_final = models[0][0]
    final_agent = None
    while final_agent is None:
        raw_final = (
            input_fn(
                f"Which model gives the final synthesis? [{default_final}]: "
            ).strip()
            or default_final
        )
        if raw_final in valid_keys:
            final_agent = raw_final
        else:
            print_fn(
                f"{raw_final} wasn't one of the models you selected -- pick "
                f"one of: {', '.join(valid_keys)}"
            )

    unavailable = check_availability(settings, models)
    if unavailable:
        names = ", ".join(label for _, label in unavailable)
        pronoun = "them" if len(unavailable) > 1 else "it"
        proceed = (
            input_fn(
                f"{names} not configured for chat in this repo. Proceed "
                f"without {pronoun}? [y/N]: "
            )
            .strip()
            .lower()
        )
        if proceed != "y":
            return None
        unavailable_keys = {key for key, _ in unavailable}
        models = [(key, label) for key, label in models if key not in unavailable_keys]
        if not models:
            print_fn("No models left to brainstorm with.")
            return None
        if final_agent in unavailable_keys:
            final_agent = models[0][0]
            print_fn(f"Final synthesis will come from {models[0][1]} instead.")

    return {
        "topic": topic,
        "models": models,
        "passes": passes,
        "final_agent": final_agent,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brainstorm_setup.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/brainstorm.py tests/test_brainstorm_setup.py
git commit -m "feat: brainstorm setup -- topic, model selection, availability check"
```

---

### Task 3: `brainstorm.py` — pass 0 and the merge

**Files:**
- Modify: `src/whyline_relay/brainstorm.py`
- Modify: `src/whyline_relay/init.py`
- Test: `tests/test_brainstorm_pass0.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `chat.run_turn` with its new `commit_message` parameter (Task 1); `ask_brainstorm_setup`'s returned `models`/`topic` shape (Task 2).
- Produces: `brainstorm.temp_path(root, agent: str) -> Path` (`.whyline/relay/brainstorm-tmp/<agent>.md`). `brainstorm.shared_path(root, topic: str) -> Path` (`docs/brainstorm/<slug>.md`). `brainstorm.run_pass_zero(root, models, topic, *, settings, run_fn=None, runner=None, print_fn=None) -> None` (runs each model's research turn; degrades gracefully per spec B7 -- an `AgentMissing`/`AgentTimeout` is caught, printed, and that model is simply skipped for pass 0, leaving no temp file for it). `brainstorm.merge_pass_zero(root, models, topic) -> None` (reads each model's temp file if present and non-empty, writes `shared_path`, commits, deletes the temp files).

- [ ] **Step 1: Add `brainstorm-tmp/` to the relay gitignore list, with a failing test**

In `tests/test_init.py`, find the existing test for `RELAY_GITIGNORE_LINES`'
content (search for `"logs/\nstate.json"` or similar) and add:

```python
def test_relay_gitignore_covers_brainstorm_temp_files(tmp_path: Path):
    from whyline_relay import init

    init.ensure_relay_gitignore(tmp_path)
    content = (tmp_path / ".whyline" / "relay" / ".gitignore").read_text()
    assert "brainstorm-tmp/" in content
```

Run: `uv run pytest tests/test_init.py -k brainstorm -v`
Expected: FAIL — `brainstorm-tmp/` is not yet in `RELAY_GITIGNORE_LINES`.

In `src/whyline_relay/init.py`, change:

```python
RELAY_GITIGNORE_LINES = (
    "logs/",
    "state.json",
    "STOP",
    "running.json",
    "chat.json",
    "chat-history.jsonl",
)
```

to:

```python
RELAY_GITIGNORE_LINES = (
    "logs/",
    "state.json",
    "STOP",
    "running.json",
    "chat.json",
    "chat-history.jsonl",
    "brainstorm-tmp/",
)
```

Run: `uv run pytest tests/test_init.py -v`
Expected: PASS, all of them.

```bash
git add src/whyline_relay/init.py tests/test_init.py
git commit -m "feat: relay gitignore also covers brainstorm's temp files"
```

- [ ] **Step 2: Write the failing tests for pass 0 and the merge**

Create `tests/test_brainstorm_pass0.py`:

```python
import subprocess
from pathlib import Path

from whyline_relay import brainstorm, config


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    (root / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def test_temp_path_is_per_agent_under_the_gitignored_directory(tmp_path: Path):
    path = brainstorm.temp_path(tmp_path, "claude")
    assert path == tmp_path / ".whyline" / "relay" / "brainstorm-tmp" / "claude.md"


def test_shared_path_uses_the_slugified_topic(tmp_path: Path):
    path = brainstorm.shared_path(tmp_path, "Best Caching Strategy!")
    assert path == tmp_path / "docs" / "brainstorm" / "best-caching-strategy.md"


def test_run_pass_zero_writes_a_temp_file_per_model(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    models = [("claude", "Claude"), ("codex", "Codex")]

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        # Simulate the agent editing its own temp file, the way a real
        # agent's own tool use would -- run_fn itself never writes files in
        # production; this fake stands in for that.
        for agent in ("claude", "codex"):
            if agent in command[0]:
                brainstorm.temp_path(tmp_path, agent).parent.mkdir(
                    parents=True, exist_ok=True
                )
                brainstorm.temp_path(tmp_path, agent).write_text(
                    f"{agent} findings\n"
                )
        return RunResult(0, '{"type":"result","result":"done"}\n')

    brainstorm.run_pass_zero(
        tmp_path, models, "my topic", settings=settings, run_fn=fake_run_fn,
        print_fn=lambda *a, **k: None,
    )
    assert brainstorm.temp_path(tmp_path, "claude").read_text() == "claude findings\n"
    assert brainstorm.temp_path(tmp_path, "codex").read_text() == "codex findings\n"


def test_run_pass_zero_skips_a_model_that_is_missing(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    models = [("claude", "Claude")]

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay import agents
        raise agents.AgentMissing("claude is not installed")

    printed = []
    brainstorm.run_pass_zero(
        tmp_path, models, "my topic", settings=settings, run_fn=fake_run_fn,
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    )
    assert not brainstorm.temp_path(tmp_path, "claude").exists()
    assert any("claude" in line for line in printed)


def test_merge_pass_zero_combines_temp_files_into_the_shared_file(tmp_path: Path):
    _init_repo(tmp_path)
    models = [("claude", "Claude"), ("codex", "Codex")]
    brainstorm.temp_path(tmp_path, "claude").parent.mkdir(parents=True, exist_ok=True)
    brainstorm.temp_path(tmp_path, "claude").write_text("claude findings\n")
    brainstorm.temp_path(tmp_path, "codex").write_text("codex findings\n")

    brainstorm.merge_pass_zero(tmp_path, models, "my topic")

    shared = brainstorm.shared_path(tmp_path, "my topic").read_text()
    assert "## Claude" in shared
    assert "claude findings" in shared
    assert "## Codex" in shared
    assert "codex findings" in shared
    assert shared.index("## Claude") < shared.index("## Codex")
    assert not brainstorm.temp_path(tmp_path, "claude").exists()
    assert not brainstorm.temp_path(tmp_path, "codex").exists()
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=tmp_path,
        check=True, capture_output=True, text=True,
    ).stdout
    assert 'brainstorm: merge independent research on "my topic"' in log


def test_merge_pass_zero_skips_an_empty_or_missing_temp_file(tmp_path: Path):
    _init_repo(tmp_path)
    models = [("claude", "Claude"), ("codex", "Codex")]
    brainstorm.temp_path(tmp_path, "claude").parent.mkdir(parents=True, exist_ok=True)
    brainstorm.temp_path(tmp_path, "claude").write_text("claude findings\n")
    # codex's temp file was never created (e.g. it was skipped in pass 0)

    brainstorm.merge_pass_zero(tmp_path, models, "my topic")

    shared = brainstorm.shared_path(tmp_path, "my topic").read_text()
    assert "## Claude" in shared
    assert "## Codex" not in shared
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_brainstorm_pass0.py -v`
Expected: FAIL — `temp_path`/`shared_path`/`run_pass_zero`/`merge_pass_zero`
do not exist.

- [ ] **Step 4: Implement**

Add to `src/whyline_relay/brainstorm.py`. Extend the imports:

```python
from whyline_relay import agents, chat, config, gitcheck
```

Then add:

```python
def temp_path(root: Path, agent: str) -> Path:
    return config.relay_dir(root) / "brainstorm-tmp" / f"{agent}.md"


def shared_path(root: Path, topic: str) -> Path:
    return root / "docs" / "brainstorm" / f"{slugify(topic)}.md"


def run_pass_zero(
    root: Path,
    models: list[tuple[str, str]],
    topic: str,
    *,
    settings: "config.Config",
    run_fn=None,
    runner=None,
    print_fn=None,
) -> None:
    """Each model researches independently into its own temp file. A model
    that can't run is skipped (spec B7) -- it simply leaves no temp file,
    which merge_pass_zero already treats as absent, not an error."""
    print_fn = print_fn if print_fn is not None else print
    for agent_key, label in models:
        prompt = (
            f'Research "{topic}" independently. Write your findings to '
            f"{temp_path(root, agent_key)} as plain markdown. This is your "
            "own independent pass -- you haven't seen, and shouldn't need, "
            "any other model's perspective yet."
        )
        kwargs = {"run_fn": run_fn} if run_fn is not None else {}
        if runner is not None:
            kwargs["runner"] = runner
        try:
            chat.run_turn(
                root,
                agent=agent_key,
                prompt=prompt,
                settings=settings,
                commit_message=(
                    f'brainstorm: {agent_key} independent research on "{topic}"'
                ),
                **kwargs,
            )
        except (agents.AgentMissing, agents.AgentTimeout, chat.AgentUnavailable) as error:
            print_fn(f"{label} could not research this pass: {error}")


def merge_pass_zero(root: Path, models: list[tuple[str, str]], topic: str) -> None:
    """Combines every model's non-empty temp file into the one shared file,
    under a `## <Label>` heading each, in `models`' own order. Deletes the
    temp files afterward. An empty or missing temp file is skipped, not an
    error (spec: "an empty/missing pass-0 temp file is skipped")."""
    sections = []
    used_paths = []
    for agent_key, label in models:
        path = temp_path(root, agent_key)
        if path.exists() and path.read_text(encoding="utf-8").strip():
            sections.append(f"## {label}\n\n{path.read_text(encoding='utf-8').strip()}\n")
            used_paths.append(path)

    target = shared_path(root, topic)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = f"# Brainstorm: {topic}\n\n" + "\n".join(sections)
    target.write_text(body, encoding="utf-8")

    for path in used_paths:
        path.unlink()

    gitcheck.commit_all(root, f'brainstorm: merge independent research on "{topic}"')
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_brainstorm_pass0.py -v`
Expected: PASS, all of them.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/brainstorm.py tests/test_brainstorm_pass0.py
git commit -m "feat: brainstorm pass 0 -- independent research, then the merge"
```

---

### Task 4: `brainstorm.py` — review passes and the final synthesis

**Files:**
- Modify: `src/whyline_relay/brainstorm.py`
- Test: `tests/test_brainstorm_passes.py`

**Interfaces:**
- Consumes: `chat.run_turn` with `commit_message` (Task 1); `shared_path` (Task 3).
- Produces: `brainstorm.run_review_pass(root, models, topic, pass_number, *, settings, run_fn=None, runner=None, print_fn=None) -> None`. `brainstorm.run_final_synthesis(root, final_agent, models, topic, *, settings, run_fn=None, runner=None) -> dict` (the raw `chat.run_turn` record).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_brainstorm_passes.py`:

```python
import subprocess
from pathlib import Path

from whyline_relay import brainstorm, config


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    (root / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def test_run_review_pass_invokes_every_model_once(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    models = [("claude", "Claude"), ("codex", "Codex")]
    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        return RunResult(0, '{"type":"result","result":"revised"}\n')

    brainstorm.run_review_pass(
        tmp_path, models, "my topic", 1, settings=settings, run_fn=fake_run_fn,
        print_fn=lambda *a, **k: None,
    )
    assert calls == ["claude", "codex"]


def test_run_review_pass_skips_a_model_that_times_out(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    models = [("claude", "Claude"), ("codex", "Codex")]
    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay import agents
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        if command[0] == "claude":
            raise agents.AgentTimeout("claude exceeded 300s")
        return RunResult(0, '{"type":"result","result":"revised"}\n')

    printed = []
    brainstorm.run_review_pass(
        tmp_path, models, "my topic", 1, settings=settings, run_fn=fake_run_fn,
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    )
    assert calls == ["claude", "codex"]  # codex still ran despite claude's timeout
    assert any("claude" in line for line in printed)


def test_run_review_pass_commit_message_names_the_pass_and_topic(
    tmp_path: Path, monkeypatch
):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    models = [("claude", "Claude")]
    seen = {}

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        return RunResult(0, '{"type":"result","result":"revised"}\n')

    real_run_turn = brainstorm.chat.run_turn

    def spying_run_turn(*args, **kwargs):
        seen["commit_message"] = kwargs.get("commit_message")
        return real_run_turn(*args, **kwargs)

    monkeypatch.setattr(brainstorm.chat, "run_turn", spying_run_turn)
    brainstorm.run_review_pass(
        tmp_path, models, "my topic", 2, settings=settings,
        run_fn=fake_run_fn, print_fn=lambda *a, **k: None,
    )
    assert seen["commit_message"] == 'brainstorm: claude review pass 2 on "my topic"'


def test_run_final_synthesis_only_invokes_the_designated_model(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)
    models = [("claude", "Claude"), ("codex", "Codex")]
    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        return RunResult(0, '{"type":"result","result":"final answer"}\n')

    record = brainstorm.run_final_synthesis(
        tmp_path, "codex", models, "my topic", settings=settings, run_fn=fake_run_fn
    )
    assert calls == ["codex"]
    assert record["response"] == "final answer"
    assert record["agent"] == "codex"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brainstorm_passes.py -v`
Expected: FAIL — `run_review_pass`/`run_final_synthesis` do not exist.

- [ ] **Step 3: Implement**

Add to `src/whyline_relay/brainstorm.py`:

```python
def run_review_pass(
    root: Path,
    models: list[tuple[str, str]],
    topic: str,
    pass_number: int,
    *,
    settings: "config.Config",
    run_fn=None,
    runner=None,
    print_fn=None,
) -> None:
    """Every selected model, once, revises only its own section. A model
    that can't run this pass is skipped (spec B7) -- its section simply
    keeps whatever it held from the last successful pass."""
    print_fn = print_fn if print_fn is not None else print
    shared = shared_path(root, topic)
    for agent_key, label in models:
        prompt = (
            f'Combined review pass {pass_number} of a brainstorm on '
            f'"{topic}". Read {shared} in full. Update your own section '
            f'("## {label}") in place based on what you now see from the '
            "others -- replace it with your revised thinking, rather than "
            "appending a new dated block; the file should only ever show "
            "your current view, not a history of past passes. Do not touch "
            "any other model's section."
        )
        kwargs = {"run_fn": run_fn} if run_fn is not None else {}
        if runner is not None:
            kwargs["runner"] = runner
        try:
            record = chat.run_turn(
                root,
                agent=agent_key,
                prompt=prompt,
                settings=settings,
                commit_message=(
                    f'brainstorm: {agent_key} review pass {pass_number} '
                    f'on "{topic}"'
                ),
                **kwargs,
            )
        except (agents.AgentMissing, agents.AgentTimeout, chat.AgentUnavailable) as error:
            print_fn(f"{label} could not review this pass: {error}")
            continue
        if not record["ok"]:
            print_fn(f"⚠ {label}'s review pass {pass_number} reported a failure.")


def run_final_synthesis(
    root: Path,
    final_agent: str,
    models: list[tuple[str, str]],
    topic: str,
    *,
    settings: "config.Config",
    run_fn=None,
    runner=None,
) -> dict:
    shared = shared_path(root, topic)
    prompt = (
        f'All review passes are complete for this brainstorm on "{topic}". '
        f"Read {shared} in full and write a new \"## Final Synthesis\" "
        "section (at the top, right after the title) combining the "
        "strongest ideas from every model's section into one clear, "
        "actionable recommendation."
    )
    kwargs = {"run_fn": run_fn} if run_fn is not None else {}
    if runner is not None:
        kwargs["runner"] = runner
    return chat.run_turn(
        root,
        agent=final_agent,
        prompt=prompt,
        settings=settings,
        commit_message=f'brainstorm: {final_agent} final synthesis on "{topic}"',
        **kwargs,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brainstorm_passes.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/brainstorm.py tests/test_brainstorm_passes.py
git commit -m "feat: brainstorm review passes and the final synthesis"
```

---

### Task 5: `chat.py` — wire `/brainstorm` into the REPL

**Files:**
- Modify: `src/whyline_relay/chat.py`
- Test: `tests/test_chat_repl.py`

**Interfaces:**
- Consumes: `brainstorm.ask_brainstorm_setup`, `brainstorm.run_pass_zero`, `brainstorm.merge_pass_zero`, `brainstorm.run_review_pass`, `brainstorm.run_final_synthesis` (Tasks 2-4).
- Produces: `/brainstorm` recognized by `repl()`.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_chat_repl.py`'s existing `_repo`/`_fake_run_fn` fixtures
(already used throughout that file) before writing these, so the new tests
match them exactly. Add:

```python
def test_repl_brainstorm_runs_the_whole_flow(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    answers = iter([
        "/brainstorm",
        "caching strategy",  # topic
        "1,2",  # models: claude, codex
        "0",  # passes
        "claude",  # final synthesis model
        "/exit",
    ])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert any("an answer" in line for line in printed)
    from whyline_relay import brainstorm
    shared = brainstorm.shared_path(root, "caching strategy")
    assert shared.exists()


def test_repl_brainstorm_declined_after_unavailable_model_does_nothing(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    answers = iter([
        "/brainstorm",
        "some topic",
        "4",  # grok -- not configured for chat in this repo
        "0",
        "grok",
        "n",  # decline to proceed without it
        "/exit",
    ])
    chat.repl(
        root,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    from whyline_relay import brainstorm
    assert not brainstorm.shared_path(root, "some topic").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_repl.py -k brainstorm -v`
Expected: FAIL — `/brainstorm` is rejected as an unknown command.

- [ ] **Step 3: Implement**

In `src/whyline_relay/chat.py`, add `brainstorm` to the `whyline_relay`
import line:

```python
from whyline_relay import adapters, agents, brainstorm, chatlog, config, failover, gitcheck, init, invocation
```

Update `SLASH_COMMANDS`. Change:

```python
SLASH_COMMANDS = (
    "/default", "/agents", "/history", "/clear", "/exit",
    "/backups", "/reset-backup",
)
```

to:

```python
SLASH_COMMANDS = (
    "/default", "/agents", "/history", "/clear", "/exit",
    "/backups", "/reset-backup", "/brainstorm",
)
```

Add a new branch in `repl()`'s main loop, right after the existing
`/reset-backup` branch and before the `/default` branch:

```python
        if line == "/brainstorm":
            setup = brainstorm.ask_brainstorm_setup(
                root, settings, input_fn=input_fn, print_fn=print_fn
            )
            if setup is None:
                continue
            brainstorm.run_pass_zero(
                root, setup["models"], setup["topic"], settings=settings,
                run_fn=run_fn, print_fn=print_fn,
            )
            brainstorm.merge_pass_zero(root, setup["models"], setup["topic"])
            for pass_number in range(1, setup["passes"] + 1):
                brainstorm.run_review_pass(
                    root, setup["models"], setup["topic"], pass_number,
                    settings=settings, run_fn=run_fn, print_fn=print_fn,
                )
            record = brainstorm.run_final_synthesis(
                root, setup["final_agent"], setup["models"], setup["topic"],
                settings=settings, run_fn=run_fn,
            )
            print_fn(f"[{record['agent']}] {record['response']}")
            continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_repl.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/chat.py tests/test_chat_repl.py
git commit -m "feat: wire /brainstorm into the chat REPL"
```

---

### Task 6: README — document `/brainstorm`

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the "## Chat: talk to any configured agent from one terminal" section
and add a new paragraph, immediately after its existing "Automatic backup"
paragraph (added for 0.2.17):

````markdown
**`/brainstorm` runs a topic through several models at once:**

```
> /brainstorm
What should we research? caching strategy for the API
Which models? (1 Claude, 2 Codex, 3 Antigravity, 4 Grok, 5 all): 1,2
How many passes? [1]: 1
Which model gives the final synthesis? [claude]: 
```

Each selected model independently researches the topic into its own
private file first (true independence -- no model can see another's until
every one has finished); those get merged into one real file,
`docs/brainstorm/<topic>.md`, under a heading per model. Each configured
review pass has every model re-read the whole file and revise only its own
section based on what it now sees from the others. Finally, the model you
named writes a "Final Synthesis" section and its answer is shown like any
normal chat response. Every step is an ordinary, auto-committed chat turn
under the hood -- brainstorming inherits the same permission floor and
automatic backup/failover chat already has for everything else. A model
that can't run a given pass (missing, timed out, or not configured) is
skipped for that pass rather than stopping the whole session; you're told
which one and why.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document /brainstorm"
```

## Not in this plan

- **Relay's "create a plan" via brainstorming** -- a separate, subsequent
  plan that reuses this engine, per the design spec's own non-goals.
- **True concurrency** -- explicit non-goal; every phase is a sequence of
  ordinary, sequential chat turns.
