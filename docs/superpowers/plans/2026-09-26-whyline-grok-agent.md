# Grok Agent Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `whyline run grok "<task>"` and `whyline model set grok <model>` work, using the same interactive-hand-to-a-human model `claude`/`codex`/`antigravity` already use.

**Architecture:** A pure data addition to `runner.py`'s `AGENTS`/`MODEL_FLAG` dicts — `cli.py` already derives its `choices=` for both `whyline run` and `whyline model set` dynamically from `runner.AGENTS` (confirmed by reading the code, not assumed), so no `cli.py` change is needed at all.

**Tech Stack:** Python 3.11+, stdlib only. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-26-grok-generic-recipe-design.md`, section 5.1. This is phase 1 of that spec's two-repo build order; phase 2 (whyline-relay's README recipe and `preflight.py` warning) is a separate plan, independent of this one shipping first.

## Global Constraints

- No new runtime dependency.
- `grok "<prompt>"` starts an interactive session directly (confirmed via `grok --help`: `[PROMPT] Initial prompt for the interactive session`) — no special flag needed, unlike Antigravity's `-i`.
- Every existing test must still pass after every task.

---

### Task 1: `runner.py` — add `grok` to `AGENTS` and `MODEL_FLAG`

**Files:**
- Modify: `src/whyline/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces: `runner.AGENTS["grok"] == ["grok"]`, `runner.MODEL_FLAG["grok"] == "--model"`. No new public function — `build_argv`/`launch` already take `agent: str` generically.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_runner.py`:

```python
def test_build_argv_supports_grok():
    assert runner.build_argv("grok", "task", "ctx")[0] == "grok"


def test_build_argv_gives_grok_the_prompt_directly_no_special_flag():
    # Unlike Antigravity's -i, grok's own --help documents that a bare
    # `grok "<prompt>"` already starts an interactive session with it.
    assert runner.build_argv("grok", "task", "ctx") == ["grok", "ctx\n\ntask"]


def test_build_argv_appends_the_model_flag_for_grok():
    argv = runner.build_argv("grok", "task", "ctx", model="grok-4.6")
    assert argv == ["grok", "--model", "grok-4.6", "ctx\n\ntask"]


def test_launch_execs_grok_directly():
    calls = []
    runner.launch(
        "grok", "task", "ctx", which=lambda name: f"/usr/bin/{name}",
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
    )
    assert calls == [("grok", ["grok", "ctx\n\ntask"])]
```

Extend the existing `test_build_argv_never_adds_permission_bypass_flags` and
`test_no_code_path_can_reach_the_real_execvp_during_tests` tests (both already loop over a tuple of
agent names) to include `"grok"`:

```python
def test_build_argv_never_adds_permission_bypass_flags():
    for agent in ("claude", "codex", "antigravity", "grok"):
        argv = runner.build_argv(agent, "task", "ctx")
        joined = " ".join(argv)
        for forbidden in (
            "--dangerously-skip-permissions",
            "--yolo",
            "--dangerously-bypass-hook-trust",
            "--approval-mode",
            "--permission-mode",
        ):
            assert forbidden not in joined, f"{agent}: {joined}"
```

(this also adds `"--permission-mode"` to the forbidden-substring list — Grok's own bypass form,
`--permission-mode bypassPermissions`, is a real flag this project must never pass, matching the same
guard whyline-relay's `bypass.py` already enforces on its side)

```python
def test_no_code_path_can_reach_the_real_execvp_during_tests(monkeypatch):
    def poisoned(binary, argv):  # pragma: no cover - must never run
        raise AssertionError(f"real execvp reached with {binary}")

    monkeypatch.setattr(runner.os, "execvp", poisoned)
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    for agent in ("claude", "codex", "antigravity", "grok"):
        with pytest.raises(runner.AgentMissing):
            runner.launch(agent, "task", "ctx")
    with pytest.raises(runner.UnknownAgent):
        runner.launch("gemini", "task", "ctx")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runner.py -k grok -v`
Expected: FAIL — `runner.UnknownAgent: Unknown agent 'grok'. Known agents: antigravity, claude, codex`.

- [ ] **Step 3: Implement**

In `src/whyline/runner.py`, change:

```python
AGENTS = {
    "claude": ["claude"],
    "codex": ["codex"],
    # "agy" is the real binary. -i (--prompt-interactive) seeds a session with
    # the prompt and then hands over the terminal -- the same shape a bare
    # `claude "<prompt>"`/`codex "<prompt>"` already gets for free. Gemini CLI
    # itself is dead (its free personal tier was withdrawn); Antigravity is
    # the account's actual working path and is not the same binary.
    "antigravity": ["agy", "-i"],
}

MODEL_FLAG = {"claude": "--model", "codex": "--model", "antigravity": "--model"}
```

to:

```python
AGENTS = {
    "claude": ["claude"],
    "codex": ["codex"],
    # "agy" is the real binary. -i (--prompt-interactive) seeds a session with
    # the prompt and then hands over the terminal -- the same shape a bare
    # `claude "<prompt>"`/`codex "<prompt>"` already gets for free. Gemini CLI
    # itself is dead (its free personal tier was withdrawn); Antigravity is
    # the account's actual working path and is not the same binary.
    "antigravity": ["agy", "-i"],
    # "grok" (xAI's official CLI, "Grok Build") takes the prompt as a plain
    # trailing positional argument for its interactive mode -- confirmed via
    # `grok --help`: "[PROMPT] Initial prompt for the interactive session" --
    # no special flag needed, unlike Antigravity's -i.
    "grok": ["grok"],
}

MODEL_FLAG = {
    "claude": "--model",
    "codex": "--model",
    "antigravity": "--model",
    "grok": "--model",
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — `cli.py`'s `whyline run`/`whyline model set` subcommands already derive their
`choices=` dynamically from `runner.AGENTS` (confirmed: `parser.add_argument("agent",
choices=tuple(runner.AGENTS))` appears at both call sites), so `grok` becomes a valid choice for both
without any `cli.py` change.

- [ ] **Step 6: Commit**

```bash
git add src/whyline/runner.py tests/test_runner.py
git commit -m "feat: whyline run/model support grok"
```

---

### Task 2: README — document Grok support

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the line documenting supported agents for `run` (added in 0.3.1: "`run` supports Claude Code,
Codex, and Antigravity (`agy`)") and update it:

```markdown
- **`run` supports Claude Code, Codex, Antigravity (`agy`), and Grok (`grok`, "Grok Build")** — Gemini CLI itself is dead (its free personal tier was withdrawn); Antigravity is Google's actual working successor and is not the same binary or invocation.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document whyline run/model support for grok"
```

## Not in this plan

- **whyline-relay's generic-adapter recipe for Grok** — a separate plan
  (`2026-09-26-whyline-relay-grok-recipe.md`), independent of this one shipping first.
- **A managed `adapters/grok.py` in whyline-relay** — explicitly out of scope per the spec's
  non-goals (the `model_flag`/`-p` ordering incompatibility, no login-status check, generic denial
  text, no plan-tier field).
