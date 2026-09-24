# `init` Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `whyline-relay init` (run genuinely interactively — no `--yes`) now asks about each role's agent and, for a built-in, its model, writing `[roles]` and `[agents.<name>]` entries from real answers instead of silent defaults. `--yes` and explicit `--implementer`/`--reviewer` flags are completely unaffected — this is additive to the one existing interactive touchpoint (`init` already asks "Write these? [Y/n]"), not a replacement for it.

**Architecture:** `init.run()` gains two small helpers, `_ask_agent` and `_ask_model`, called only when `not assume_yes` (the same `confirm` callable the existing y/n question already uses). A role's agent question is skipped when that role's agent was already given via flag (`--implementer`/`--reviewer`) — matching the same "an explicit flag disables its own prompt" rule `roles set` established. The model question, by contrast, has no existing flag equivalent, so it always runs for every role's resolved agent when the session is interactive, regardless of how that agent was chosen. `config.toml`'s `[agents.<name>]` block gains a `model = "..."` line only when one was actually chosen — the exact same conditional-write discipline `init` already uses for permission files.

**Tech Stack:** Python 3.11+, stdlib only.

**Spec:** `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md`, D11 and §5.10 ("`init` asks about every role a `[pipeline]` (or the legacy pair, if none) defines: which agent, and optionally which model"). Scoped to the legacy pair only — a fresh `init` has no existing `[pipeline]` to read roles from in the first place, since `init` never reads an existing `config.toml` at all (see "Not in this plan").

## Global Constraints

- `assume_yes=True` (`--yes`) must never call `confirm` for any reason — verified by a test whose `confirm` raises on any call. This is the single most load-bearing guarantee in this plan: every sandbox and CI invocation in this project's own history uses `whyline-relay init --yes`.
- An explicit `--implementer`/`--reviewer` flag skips that role's *agent* question (matching `roles set`'s established rule that an explicit flag disables its own prompt), but never skips that role's *model* question — there has never been a flag for model selection in `init`, so no flag can be said to have already answered it.
- A blank answer to an agent question keeps that role's existing default (`codex` for implementer, `claude` for reviewer); a blank answer to a model question means no `model` key is written at all, not an empty one.
- An agent answer that isn't in `adapters.BUILTIN` is refused with a clear message and a non-zero exit — nothing is written. `init` has never supported a generic or aliased agent name interactively (only via hand-edited `config.toml` afterward), and this plan does not add that.
- `--overwrite`'s existing behavior (regenerate every file from scratch, discarding any hand edits including an existing `[pipeline]` table) is unchanged and correct as documented — this plan does not touch it.
- Every existing test must still pass, including the two existing `assume_yes=False` tests (`test_declining_writes_nothing`, `test_no_terminal_means_nothing_is_written`), whose intent is updated to account for the new questions preceding the final one.

---

### Task 1: `init.py` — the agent and model questions

**Files:**
- Modify: `src/whyline_relay/init.py` (add `_ask_agent`/`_ask_model` after `detect_stack` at line 12; restructure `run()` starting at line 25; extend the `[agents.<name>]` block builder at line 72)
- Modify (existing tests, matching the new, correct behavior): `tests/test_init.py` (`test_declining_writes_nothing`'s answer sequence)
- Test: `tests/test_init.py` (new cases, added to the existing file)

**Interfaces:**
- Produces: `init._ask_agent(confirm, role, default) -> str | None` (`None` signals an answer that isn't a built-in agent name). `init._ask_model(confirm, agent) -> str | None`. `init.run()`'s public signature and its two other behaviors (`assume_yes=True`; explicit `implementer`/`reviewer` flags with no interactive session) are unchanged in every observable way.

- [ ] **Step 1: Write the failing tests**

First, update the existing `test_declining_writes_nothing` (its premise — that the *first* question is the write confirmation — no longer holds once earlier questions exist):

```python
def test_declining_writes_nothing(tmp_path: Path):
    # Blank answers accept every wizard default (implementer/reviewer agent,
    # then a model for each); "n" only answers the final write confirmation.
    answers = iter(["", "", "", "", "n"])
    assert init.run(tmp_path, assume_yes=False, confirm=lambda prompt: next(answers)) != 0
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".whyline" / "relay").exists()
```

Then add these new tests to `tests/test_init.py`:

```python
def test_wizard_asks_for_each_role_agent_and_model(tmp_path: Path):
    answers = iter(["claude", "codex", "opus", "", "y"])
    seen = []

    def confirm(prompt):
        seen.append(prompt)
        return next(answers)

    assert init.run(tmp_path, assume_yes=False, confirm=confirm) == 0
    assert seen == [
        "Implementer agent [codex]: ",
        "Reviewer agent [claude]: ",
        "Model for claude (blank for default): ",
        "Model for codex (blank for default): ",
        "Write these? [Y/n] ",
    ]
    text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text()
    assert 'implementer = "claude"' in text and 'reviewer = "codex"' in text
    assert '[agents.claude]' in text and 'model = "opus"' in text
    assert "model" not in text.split("[agents.codex]")[1]


def test_wizard_blank_answers_keep_every_default(tmp_path: Path):
    answers = iter(["", "", "", "", "y"])
    assert init.run(tmp_path, assume_yes=False, confirm=lambda p: next(answers)) == 0
    text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text()
    assert 'implementer = "codex"' in text and 'reviewer = "claude"' in text
    assert "model" not in text


def test_wizard_rejects_an_agent_that_is_not_built_in(tmp_path: Path, capsys):
    code = init.run(tmp_path, assume_yes=False, confirm=lambda p: "gemini")
    assert code == 1
    assert "not a built-in agent" in capsys.readouterr().err.lower()
    assert not (tmp_path / ".whyline" / "relay").exists()


def test_flags_still_skip_the_agent_prompts_but_not_the_model_prompt(tmp_path: Path):
    # --implementer/--reviewer (as cli.py passes them) already answer the agent
    # questions; the wizard still offers a model for each, since a flag never
    # existed for that before this piece.
    answers = iter(["opus", "", "y"])
    seen = []

    def confirm(prompt):
        seen.append(prompt)
        return next(answers)

    code = init.run(
        tmp_path, assume_yes=False, confirm=confirm, implementer="claude", reviewer="codex"
    )
    assert code == 0
    assert seen == [
        "Model for claude (blank for default): ",
        "Model for codex (blank for default): ",
        "Write these? [Y/n] ",
    ]


def test_yes_never_prompts_even_with_no_flags(tmp_path: Path):
    def explode(prompt):
        raise AssertionError(f"assume_yes=True must never prompt: {prompt!r}")

    assert init.run(tmp_path, assume_yes=True, confirm=explode) == 0
    text = (tmp_path / ".whyline" / "relay" / "config.toml").read_text()
    assert "[roles]" not in text  # exactly today's plain-default shape
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init.py -v`
Expected: the four new wizard tests FAIL (no agent/model questions exist yet, so the recorded `seen` prompts and the resulting `config.toml` don't match); `test_declining_writes_nothing` also FAILs against its own new answer sequence (today's code only ever asks one question, so the second `next(answers)` call — `""` intended as the reviewer-agent answer — never happens, and the real y/n question receives `""` instead of `"n"`, writing the files instead of refusing).

- [ ] **Step 3: Implement**

In `src/whyline_relay/init.py`, add near the top (after the imports, before `detect_stack`):

```python
import json
import sys
from pathlib import Path

from whyline_relay import adapters, config, invocation, prompts
from whyline_relay.adapters.claude import BASE_ALLOW, DENY, PRESETS, allowlist


def _ask_agent(confirm, role: str, default: str) -> str | None:
    """Returns None for an answer that isn't a built-in agent name."""
    try:
        answer = confirm(f"{role.capitalize()} agent [{default}]: ").strip()
    except EOFError:  # no terminal to prompt on: keep the default, same as --yes
        return default
    if not answer:
        return default
    return answer if answer in adapters.BUILTIN else None


def _ask_model(confirm, agent: str) -> str | None:
    try:
        answer = confirm(f"Model for {agent} (blank for default): ").strip()
    except EOFError:
        return None
    return answer or None
```

(only the `import sys` line is new among the imports; everything else already there is unchanged — the module previously had no `sys` import.)

Then, in `run()`, find:

```python
    roles_given = implementer is not None or reviewer is not None
    implementer = implementer or "codex"
    reviewer = reviewer or "claude"
    agents_in_use = list(dict.fromkeys((implementer, reviewer)))
    stack = detect_stack(root)
```

Replace it with:

```python
    interactive = not assume_yes
    models: dict[str, str] = {}
    if interactive and implementer is None:
        implementer = _ask_agent(confirm, "implementer", "codex")
        if implementer is None:
            builtins = ", ".join(sorted(adapters.BUILTIN))
            print(f"Not a built-in agent ({builtins}).", file=sys.stderr)
            return 1
    if interactive and reviewer is None:
        reviewer = _ask_agent(confirm, "reviewer", "claude")
        if reviewer is None:
            builtins = ", ".join(sorted(adapters.BUILTIN))
            print(f"Not a built-in agent ({builtins}).", file=sys.stderr)
            return 1

    roles_given = implementer is not None or reviewer is not None
    implementer = implementer or "codex"
    reviewer = reviewer or "claude"
    agents_in_use = list(dict.fromkeys((implementer, reviewer)))

    if interactive:
        for name in agents_in_use:
            model = _ask_model(confirm, name)
            if model:
                models[name] = model

    stack = detect_stack(root)
```

Finally, find the `[agents.<name>]` block builder inside the `if roles_given:` branch:

```python
        for name in agents_in_use:
            command = config.DEFAULTS["agents"][name]
            config_text += (
                f"[agents.{name}]\n"
                f"command = {json.dumps(command)}\n"
            )
            if name != agents_in_use[-1]:
                config_text += "\n"
```

Replace it with:

```python
        for name in agents_in_use:
            command = config.DEFAULTS["agents"][name]
            config_text += (
                f"[agents.{name}]\n"
                f"command = {json.dumps(command)}\n"
            )
            if name in models:
                config_text += f'model = "{models[name]}"\n'
            if name != agents_in_use[-1]:
                config_text += "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_init.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — every test that calls `init.run(..., assume_yes=True)` (the overwhelming majority of `test_init.py`, plus `test_init_roles.py` and any acceptance test that runs `whyline-relay init --yes`) must be byte-for-byte unaffected, since `interactive = not assume_yes` is `False` for every one of them and no new code path is reached.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/init.py tests/test_init.py
git commit -m "feat: whyline-relay init asks each role's agent and model interactively"
```

---

### Task 2: README — document the interactive wizard

**Files:**
- Modify: `README.md` (the "Choosing which agent fills each role" / "Choosing a model" sections, and the `init --implementer/--reviewer` reference)

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find where `init --implementer claude --reviewer codex` is described (in "Choosing which agent fills each role"):

```markdown
- **A built-in agent**, `codex` or `claude`, in either role. `init --implementer claude --reviewer codex` sets both up, writing only the permission file the agents in use need (here, still `claude-settings.json`, since Claude fills a role either way). The same agent can fill both roles (`implementer = "claude"` and `reviewer = "claude"`); `doctor` then warns that the review is not independent, but does not stop you.
```

Add, right after that paragraph:

```markdown
Run `init` with neither flag, in a real terminal, and it asks instead: which agent for implementer and reviewer (blank keeps `codex`/`claude`), then, since 0.2.12, an optional model for each — the same interactive wizard `roles set` already gave you for changing a role later. `init --yes` (used by every scripted or CI setup) never asks anything and keeps producing exactly what it always has.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document init's interactive agent/model wizard"
```

## Not in this plan

- Reading an *existing* `config.toml`'s `[pipeline]` table to ask about a configured pipeline's own roles — `init` has never read an existing config file at all (it only ever generates one from scratch or, with `--overwrite`, replaces it outright); teaching it to read one first is a separate, larger change with its own design questions, not a small addition to this piece.
- Any change to `--overwrite`'s existing "discard every edit, including a hand-written `[pipeline]`" behavior — that is already correct, already documented, and already has test coverage confirming it is deliberate.
- A CLI flag for model selection during `init` (an `--implementer-model`/`--reviewer-model` pair or similar) — the interactive wizard is the only way to set a model at `init` time in this piece; a non-interactive equivalent, if wanted, is a separate small addition later.
