# whyline-relay Model Pre-fill Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `whyline-relay init`'s wizard and `roles set`'s interactive prompt read whyline's `.whyline/model.json` (shipped in the companion whyline plan) as a pre-filled default for their own "Model for `<agent>`" question, and `doctor`'s generic-agent warning gets Antigravity-specific, actionable text instead of the generic message.

**Architecture:** A single new, tiny, read-only module (`whyline_model.py`) reads the plain JSON file directly — whyline-relay never imports whyline as a library, matching how `whylinecmd.py` already only ever shells out to the `whyline` binary rather than importing it. whyline-relay never writes to this file; `whyline model` (the companion plan) is its only writer, so ownership never contends.

**Tech Stack:** Python 3.11+, stdlib only (`json`, `pathlib`). No new dependency (`dependencies = []` unchanged).

**Spec:** `docs/superpowers/specs/2026-09-25-account-and-model-selector-design.md`, section 5.4 (this plan's scope) and M6, M10. Depends on `2026-09-26-whyline-account-and-model.md` (the whyline-side plan) having shipped first, since this reads the exact `.whyline/model.json` shape that plan defines.

## Global Constraints

- No new runtime dependency — stdlib only.
- whyline-relay never writes to `.whyline/model.json` — read-only, one writer only (M6).
- A missing, corrupt, or malformed `.whyline/model.json` is treated as absent — never a crash, and the prompt behaves exactly as it does today (M8, consistent with `state.py`'s existing convention).
- An agent name in `.whyline/model.json` that whyline-relay doesn't itself know about is silently ignored — only keys matching whyline-relay's own known agent names are ever read.
- Every existing test must still pass after every task.

---

### Task 1: `whyline_model.py` — read-only access to whyline's model file

**Files:**
- Create: `src/whyline_relay/whyline_model.py`
- Test: `tests/test_whyline_model.py`

**Interfaces:**
- Produces: `whyline_model.read(root: Path) -> dict`. Task 2 is the only caller.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_whyline_model.py`:

```python
import json
from pathlib import Path

from whyline_relay import whyline_model


def test_read_returns_empty_dict_when_absent(tmp_path: Path):
    assert whyline_model.read(tmp_path) == {}


def test_read_returns_the_file_contents(tmp_path: Path):
    target = tmp_path / ".whyline" / "model.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"codex": "gpt-5-codex", "claude": "opus"}))
    assert whyline_model.read(tmp_path) == {"codex": "gpt-5-codex", "claude": "opus"}


def test_read_corrupt_file_is_treated_as_absent(tmp_path: Path):
    target = tmp_path / ".whyline" / "model.json"
    target.parent.mkdir(parents=True)
    target.write_text("{broken")
    assert whyline_model.read(tmp_path) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_whyline_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'whyline_relay.whyline_model'`.

- [ ] **Step 3: Implement**

Create `src/whyline_relay/whyline_model.py`:

```python
"""Reading whyline's own per-repo model choice (.whyline/model.json), read-only.

whyline-relay never writes to this file -- `whyline model` is its only writer
-- and never imports whyline as a library, matching how whylinecmd.py already
only ever shells out to the `whyline` binary. This reads a plain JSON file
whyline owns the shape of directly, since there is nothing to invoke a command
for; a missing or corrupt file reads as absent, never a crash, matching
state.py's own established convention for every other file this project reads.
"""

from __future__ import annotations

import json
from pathlib import Path


def read(root: Path) -> dict:
    try:
        return json.loads((root / ".whyline" / "model.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_whyline_model.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/whyline_model.py tests/test_whyline_model.py
git commit -m "feat: whyline_model.py reads whyline's per-repo model choice, read-only"
```

---

### Task 2: `init.py` and `roles.py` — pre-fill the model prompt

**Files:**
- Modify: `src/whyline_relay/init.py`
- Modify: `src/whyline_relay/roles.py`
- Test: `tests/test_init.py`, `tests/test_roles.py`

**Interfaces:**
- Consumes: `whyline_model.read` (Task 1).
- Produces: no new public interface — `_ask_model`'s signature changes from `(confirm, agent)` to `(confirm, root, agent)`; `set_role`'s existing model-prompt block gains the same pre-fill.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_init.py`:

```python
def test_ask_model_prefills_from_whyline_model_json(tmp_path):
    from whyline_relay import init

    target = tmp_path / ".whyline" / "model.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"codex": "gpt-5-codex"}')
    answers = iter([""])
    result = init._ask_model(lambda prompt: next(answers), tmp_path, "codex")
    assert result == "gpt-5-codex"


def test_ask_model_with_a_preset_can_still_be_overridden(tmp_path):
    from whyline_relay import init

    target = tmp_path / ".whyline" / "model.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"codex": "gpt-5-codex"}')
    answers = iter(["haiku"])
    result = init._ask_model(lambda prompt: next(answers), tmp_path, "codex")
    assert result == "haiku"


def test_ask_model_with_no_preset_behaves_exactly_as_before(tmp_path):
    from whyline_relay import init

    answers = iter([""])
    result = init._ask_model(lambda prompt: next(answers), tmp_path, "codex")
    assert result is None


def test_ask_model_eof_with_a_preset_falls_back_to_it(tmp_path):
    from whyline_relay import init

    target = tmp_path / ".whyline" / "model.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"codex": "gpt-5-codex"}')

    def raise_eof(prompt):
        raise EOFError

    result = init._ask_model(raise_eof, tmp_path, "codex")
    assert result == "gpt-5-codex"
```

Add to `tests/test_roles.py`:

```python
def test_set_role_prefills_the_model_prompt_from_whyline_model_json(tmp_path):
    from whyline_relay import config, roles

    target = tmp_path / ".whyline" / "model.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"codex": "gpt-5-codex"}')
    (tmp_path / ".whyline" / "relay").mkdir(parents=True)
    config_path = tmp_path / ".whyline" / "relay" / "config.toml"
    config_path.write_text("")
    settings = config.load(tmp_path)
    answers = iter(["codex", ""])
    result = roles.set_role(
        tmp_path, settings, "implementer", agent=None, model=None,
        confirm=lambda prompt: next(answers),
    )
    assert "gpt-5-codex" in config_path.read_text()
    assert result == "implementer set to codex (model gpt-5-codex)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init.py -k ask_model -v tests/test_roles.py -k prefill -v`
Expected: FAIL — `init._ask_model` still takes only `(confirm, agent)`, so calling it with `(confirm, tmp_path, "codex")` raises `TypeError`; `roles.set_role`'s prompt is not yet pre-filled, so the interactive answer sequence in the new test does not produce a model.

- [ ] **Step 3: Implement**

In `src/whyline_relay/init.py`, add the import and change `_ask_model`:

```python
from whyline_relay import adapters, config, invocation, prompts, whyline_model
```

```python
def _ask_model(confirm, root: Path, agent: str) -> str | None:
    preset = whyline_model.read(root).get(agent)
    prompt = (
        f"Model for {agent} [{preset}] (blank to accept, or type another): "
        if preset
        else f"Model for {agent} (blank for default): "
    )
    try:
        answer = confirm(prompt).strip()
    except EOFError:
        return preset
    return answer or preset
```

Update its one call site inside `run()`:

```python
            model = _ask_model(confirm, root, name)
```

In `src/whyline_relay/roles.py`, add the import:

```python
from whyline_relay import adapters, config, failover, whyline_model
```

Change the model-prompt block inside `set_role`:

```python
    if interactive and model is None and agent in adapters.BUILTIN:
        preset = whyline_model.read(root).get(agent)
        prompt = (
            f"Model for {agent} [{preset}] (blank to accept, or type another): "
            if preset
            else f"Model for {agent} (blank for default): "
        )
        try:
            answer = confirm(prompt).strip()
        except EOFError:
            answer = ""
        model = answer or preset
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_init.py tests/test_roles.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — every existing `_ask_model`/`set_role` test runs in a `tmp_path` with no `.whyline/model.json` present, so `whyline_model.read` returns `{}`, `preset` is `None`, and both functions behave byte-for-byte as before.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/init.py src/whyline_relay/roles.py tests/test_init.py tests/test_roles.py
git commit -m "feat: init/roles set pre-fill the model prompt from whyline's model.json"
```

---

### Task 3: `preflight.py` — Antigravity-specific warning, and README

**Files:**
- Modify: `src/whyline_relay/preflight.py`
- Modify: `README.md`
- Test: `tests/test_preflight.py`

**Interfaces:**
- None new — `preflight.run`'s existing generic-agent warning check gains one more branch.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preflight.py`:

```python
def test_antigravity_as_a_generic_agent_gets_a_specific_warning(
    ready_repo: Path, monkeypatch
):
    target = ready_repo / ".whyline" / "relay" / "config.toml"
    target.write_text(
        '[roles]\nreviewer = "antigravity"\n'
        f'[agents.codex]\ncommand = ["{sys.executable}", "codex-role"]\n'
        '[agents.antigravity]\nadapter = "generic"\ncommand = ["agy", "-p"]\n'
    )
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: f"/bin/{name}" if name == "agy" else name,
    )
    checks = preflight.run(ready_repo, allow_dirty=True, runner=successful_runner())
    matches = [c for c in checks if "antigravity" in c.message and c.status == "warn"]
    assert len(matches) == 1
    assert "548" in matches[0].message or "headless" in matches[0].message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_preflight.py -k antigravity_specific -v`
Expected: FAIL — the current generic message ("antigravity is a generic agent: the relay does not manage its permissions, login or denials") contains neither "548" nor "headless".

- [ ] **Step 3: Implement**

In `src/whyline_relay/preflight.py`, find the existing block:

```python
        if adapter.name == "generic":
            checks.append(
                _result(
                    "warn",
                    f"{agent} is a generic agent: the relay does not manage its "
                    "permissions, login or denials",
                )
            )
```

Replace it with:

```python
        if adapter.name == "generic" and agent == "antigravity":
            checks.append(
                _result(
                    "warn",
                    "antigravity is a generic agent, and its headless permission "
                    "enforcement is known to be unreliable -- see README, 'Using "
                    "Antigravity today', and "
                    "github.com/google-antigravity/antigravity-cli#548. The relay "
                    "does not manage its permissions, login or denials",
                )
            )
        elif adapter.name == "generic":
            checks.append(
                _result(
                    "warn",
                    f"{agent} is a generic agent: the relay does not manage its "
                    "permissions, login or denials",
                )
            )
```

In `README.md`, find the existing Antigravity section's opening paragraph (starting "Google's Antigravity CLI (`agy`) works headlessly...") and add one sentence at its end, right before "Configure it like this:":

```markdown
This is also tracked upstream at [google-antigravity/antigravity-cli#548](https://github.com/google-antigravity/antigravity-cli/issues/548) — headless mode's own permission enforcement is known to be unreliable; `doctor` links here directly if you configure Antigravity this way.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: PASS, all of them — including the existing `test_generic_agent_is_checked_and_warned_without_login` (using "aider"), unaffected since it takes the unchanged `elif` branch.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/preflight.py README.md tests/test_preflight.py
git commit -m "feat: doctor gives antigravity a specific, actionable warning; link issue #548"
```

## Not in this plan

- **Promoting Antigravity to a genuine managed built-in adapter** (`adapters.BUILTIN`) — that would need the open questions in `docs/antigravity-adapter-consultation.md` resolved first (scoped permissions, a stricter commit-blocking mode, per-command denial detail), none of which this plan touches.
- **Any change to `whyline-relay`'s own `[roles]`/`roles set` validation to special-case Antigravity** — it already correctly requires the deliberate, hand-written `adapter = "generic"` step before Antigravity can fill any role at all; that existing safeguard needs no change.
- **The whyline-side `whyline account`/`whyline model` commands themselves** — shipped by the companion plan, `2026-09-26-whyline-account-and-model.md`, which this plan depends on.
