# Relay plan flow, automatic agents and failure reasons: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** grok and antigravity work in every repository without setup, failed agent turns say why, and making a plan becomes a background job in the console's main window that can ask the user questions and saves named plans that Set up picks from.

**Architecture:** Four releases. Part A (whyline-relay 0.2.28) adds built-in recipes for grok and antigravity, Antigravity's trust helpers and failure reasons. Part B (whyline 0.3.31) lists every installed relay agent and asks once per repository before trusting Antigravity. Part C (whyline-relay 0.2.29) adds planner questions, named plan files and config writers. Part D (whyline 0.3.32) moves planning into the main window, adds question answering, gives Set up a plan dropdown, and adds Run: one guided path through plan, roles, checks and start.

**Tech Stack:** Python 3.11+, Textual 0.89.1, pytest + pytest-asyncio (Textual `run_test` pilot), `uv`, git, GitHub Actions trusted publishing to PyPI.

**Spec:** `docs/superpowers/specs/2026-10-04-relay-plan-flow-design.md`

## Global Constraints

- Python `>=3.11`; read TOML with `tomllib`. Add no new dependencies to either package.
- Repositories: whyline-relay is `~/whyline-relay` (Parts A and C). whyline is `~/agentdock` (Parts B and D).
- Branches: Part A works on `relay/agents-and-failures`, cut from whyline-relay `origin/main` (b5e7d98, v0.2.27). Part C works on `relay/plan-flow`, cut from `origin/main` after Part A is released. Parts B and D work on whyline branch `relay/plan-flow` (already exists, holds the spec).
- whyline requires `whyline-relay>=0.2.28,<0.3` after Part B and `whyline-relay>=0.2.29,<0.3` after Part D, in **both** places it appears in `pyproject.toml`.
- Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `git add -A`.
- Console code imports `whyline_relay` lazily inside functions (the pattern in `src/whyline/console/adapters.py` and `relay_ops.py`).
- Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one`.
- Background work follows the existing token pattern: a new `object()` in `self._dispatch_token`, results dropped when the token no longer matches.
- Plan files: `plans/<slug>.plan.md`, slug lower-case `[a-z0-9-]`, at most 40 characters, first line exactly `<!-- whyline-plan v1 | source: <draft|paste|brainstorm> | drafted-by: <who> | created: <ISO-8601 with offset> -->`.
- The Antigravity settings file is `~/.gemini/antigravity-cli/settings.json`. Only `trust()` writes it, and only after the user chose "Trust it".
- After each task, record the decision per `AGENTS.md`: `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task RPF-<task number>`.
- Commit messages end with a blank line and your harness's `Co-Authored-By:` line if it adds one. Push and tag only in Tasks 4, 7, 10 and 17.

## Review Focus

- **A repository whose config still names antigravity `[agents.agy]`.** The old alias must keep winning over the new recipe; otherwise the user's customised command is silently replaced. Pinned in Task 1.
- **A malformed `~/.gemini/antigravity-cli/settings.json`** (invalid JSON, or `trustedWorkspaces` not a list). `trust()` must refuse with a clear error rather than overwrite the user's file. Pinned in Task 2.
- **An agent that prints a multi-kilobyte error or control characters.** The progress line must stay one printable line of at most 160 characters of detail. Pinned in Task 3.
- **Typing in the main prompt while a draft waits for review.** The text must go to the plan, not to chat, and slash commands must still work. Pinned in Task 14.
- **Set up in a repository whose `config.toml` has no `[pipeline]` yet but already has `plan =` and `[planner]` from Plan.** Saving roles must not drop them. Pinned in Task 9.

---

# Part A — whyline-relay 0.2.28 (repo `~/whyline-relay`)

Before Task 1:

```bash
cd ~/whyline-relay && git fetch origin && git switch -c relay/agents-and-failures origin/main
uv sync && uv run pytest -q
```

Expected: all tests pass on a clean tree.

### Task 1: Built-in recipes for grok and antigravity

**Files:**
- Create: `src/whyline_relay/recipes.py`
- Modify: `src/whyline_relay/config.py` (in `load`, after the `for name, table in (raw.get("agents") or {}).items():` loop)
- Test: `tests/test_recipes.py` (create)

**Interfaces:**
- Produces: `whyline_relay.recipes.RECIPES: dict[str, tuple[str, ...]]` with keys `"antigravity"` and `"grok"`. `config.load(root)` returns these as generic agents (`settings.agents[name]`, `settings.adapters[name] == "generic"`) whenever the repo's config doesn't define the name (or, for antigravity, its alias `agy`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recipes.py`:

```python
from pathlib import Path

from whyline_relay import chat, config, recipes


def _write(root: Path, text: str) -> None:
    path = root / ".whyline" / "relay" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_with_no_config_grok_and_antigravity_are_generic_agents(tmp_path):
    settings = config.load(tmp_path)
    assert settings.agents["grok"] == list(recipes.RECIPES["grok"])
    assert settings.agents["antigravity"] == list(recipes.RECIPES["antigravity"])
    assert settings.adapters["grok"] == "generic"
    assert settings.adapters["antigravity"] == "generic"


def test_recipes_end_with_the_prompt_flag(tmp_path):
    for command in recipes.RECIPES.values():
        assert command[-1] == "-p"


def test_a_repos_own_agent_table_wins(tmp_path):
    _write(tmp_path, '[agents.grok]\nadapter = "generic"\ncommand = ["grok", "-p"]\n')
    assert config.load(tmp_path).agents["grok"] == ["grok", "-p"]


def test_the_old_agy_alias_keeps_its_own_command(tmp_path):
    _write(tmp_path, '[agents.agy]\nadapter = "generic"\ncommand = ["agy", "mine", "-p"]\n')
    settings = config.load(tmp_path)
    assert "antigravity" not in settings.agents
    assert chat.resolve_command(settings, "antigravity") == ["agy", "mine", "-p"]


def test_grok_can_take_a_relay_role_with_no_agent_table(tmp_path):
    _write(tmp_path, '[roles]\nimplementer = "grok"\nreviewer = "antigravity"\n')
    settings = config.load(tmp_path)
    assert settings.roles.implementer == "grok"
    assert settings.roles.reviewer == "antigravity"


def test_chat_resolves_grok_with_no_config(tmp_path):
    assert chat.resolve_command(config.load(tmp_path), "grok")[0] == "grok"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_recipes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'whyline_relay.recipes'`.

- [ ] **Step 3: Write the recipes module**

Create `src/whyline_relay/recipes.py`:

```python
"""Default commands for the agents the relay runs through the generic
adapter. They are the README's verified recipes ("Using Antigravity today",
"Using Grok today"), so grok and antigravity work in any repository with no
hand-written config. A repository's own [agents.<name>] always wins."""
from __future__ import annotations

# `-p` must stay last: the relay appends the prompt as the final argument,
# and both CLIs' `-p` swallows whatever token follows it.
RECIPES: dict[str, tuple[str, ...]] = {
    "antigravity": (
        "agy", "--output-format", "json", "--mode", "accept-edits",
        "--add-dir", ".", "--new-project", "-p",
    ),
    "grok": (
        "grok", "--output-format", "json", "--permission-mode", "dontAsk",
        "--deny", "Bash(git push:*)", "--deny", "Bash(rm -rf:*)",
        "--allow", "Edit", "--allow", "Bash(git add:*)", "--allow", "Bash(git commit:*)",
        "--allow", "Bash(git diff:*)", "--allow", "Bash(git status:*)",
        "--allow", "Bash(git log:*)", "--allow", "Bash(whyline:*)",
        "--allow", "Bash(python3:*)", "--allow", "Bash(uv run:*)", "--allow", "Bash(uv:*)",
        "--allow", "Bash(mkdir:*)", "--allow", "Bash(ls:*)", "--allow", "Bash(find:*)",
        "--allow", "Bash(touch:*)", "--allow", "Bash(cat:*)",
        "-p",
    ),
}

# A recipe is skipped when the config already names the agent under one of
# these older keys (chat.AGENT_ALIASES maps agy -> antigravity).
ALIASES: dict[str, tuple[str, ...]] = {"antigravity": ("agy",)}
```

- [ ] **Step 4: Apply the recipes in `config.load`**

In `src/whyline_relay/config.py`, add `recipes` to the `from whyline_relay import ...` line. Directly after the `for name, table in (raw.get("agents") or {}).items():` loop ends (before `role_values = raw.get("roles") or {}`), insert:

```python
    for name, command in recipes.RECIPES.items():
        spellings = (name, *recipes.ALIASES.get(name, ()))
        if any(spelling in agents for spelling in spellings):
            continue
        agents[name] = list(command)
        configured_adapters[name] = "generic"
```

- [ ] **Step 5: Run the new tests, then the whole suite**

Run: `uv run pytest tests/test_recipes.py -q && uv run pytest -q`
Expected: the new tests pass. If an existing test asserted the exact set of `settings.agents` keys, update that assertion to include `"antigravity"` and `"grok"`. Don't change behaviour to satisfy it.

- [ ] **Step 6: Update the README**

In `README.md`, under both "Using Antigravity today" and "Using Grok (`grok`, "Grok Build") today", add this paragraph directly below the heading:

```markdown
Since 0.2.28 the relay uses the recipe below automatically when the repository's config has no `[agents.<name>]` table of its own, so you only need the TOML when you want to change the command.
```

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/recipes.py src/whyline_relay/config.py tests/test_recipes.py README.md
git commit -m "feat: run grok and antigravity from built-in recipes (RPF-1)"
whyline note "grok and antigravity default to the README recipes as generic agents" --because "a repository with no relay config skipped them in chat and brainstorm; the recipes are already verified" --rejected "Probe PATH inside config.load: loading would depend on the machine and tests would flake" --rejected "Make them built-in adapters: they still lack login checks and denial details, the reason they are generic" --file src/whyline_relay/recipes.py --file src/whyline_relay/config.py --actor <agent> --role implementer --task RPF-1
```

### Task 2: Antigravity trust helpers

**Files:**
- Create: `src/whyline_relay/antigravity.py`
- Modify: `src/whyline_relay/gitcheck.py` (`RELAY_IGNORE`)
- Test: `tests/test_antigravity_trust.py` (create)

**Interfaces:**
- Produces: `antigravity.settings_path() -> Path`; `antigravity.is_trusted(root: Path) -> bool`; `antigravity.trust(root: Path) -> Path` (raises `antigravity.SettingsUnreadable` for a file it can't safely edit); `antigravity.declined_path(root) -> Path`; `antigravity.is_declined(root) -> bool`; `antigravity.decline(root) -> None`; `antigravity.forget_decline(root) -> None`; `antigravity.ALLOW: tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_antigravity_trust.py`:

```python
import json
from pathlib import Path

import pytest

from whyline_relay import antigravity, gitcheck


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _settings(home: Path) -> dict:
    return json.loads((home / ".gemini" / "antigravity-cli" / "settings.json").read_text())


def test_trust_creates_the_file_with_the_repo_and_tools(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert not antigravity.is_trusted(repo)
    antigravity.trust(repo)
    data = _settings(home)
    assert data["trustedWorkspaces"] == [str(repo.resolve())]
    assert data["permissions"]["allow"] == list(antigravity.ALLOW)
    assert antigravity.is_trusted(repo)


def test_trust_keeps_other_keys_and_adds_the_repo_once(home, tmp_path):
    path = home / ".gemini" / "antigravity-cli" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "theme": "dark",
        "trustedWorkspaces": ["/elsewhere"],
        "permissions": {"allow": ["read_file(*)"], "deny": ["command(rm)"]},
    }))
    repo = tmp_path / "repo"
    repo.mkdir()
    antigravity.trust(repo)
    antigravity.trust(repo)
    data = _settings(home)
    assert data["theme"] == "dark"
    assert data["trustedWorkspaces"] == ["/elsewhere", str(repo.resolve())]
    assert data["permissions"]["deny"] == ["command(rm)"]
    assert data["permissions"]["allow"] == [
        "read_file(*)", "write_file(*)", "edit_file(*)", "command(*)",
    ]


@pytest.mark.parametrize("text", ["{not json", '{"trustedWorkspaces": "x"}'])
def test_trust_refuses_a_file_it_cannot_edit_safely(home, tmp_path, text):
    path = home / ".gemini" / "antigravity-cli" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    with pytest.raises(antigravity.SettingsUnreadable):
        antigravity.trust(tmp_path)
    assert path.read_text() == text
    assert antigravity.is_trusted(tmp_path) is False


def test_decline_is_remembered_and_forgettable(tmp_path):
    assert not antigravity.is_declined(tmp_path)
    antigravity.decline(tmp_path)
    assert antigravity.is_declined(tmp_path)
    antigravity.forget_decline(tmp_path)
    assert not antigravity.is_declined(tmp_path)


def test_the_decline_file_is_git_ignored():
    assert ".whyline/relay/antigravity-declined" in gitcheck.RELAY_IGNORE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_antigravity_trust.py -q`
Expected: FAIL with `ImportError: cannot import name 'antigravity'`.

- [ ] **Step 3: Write the module**

Create `src/whyline_relay/antigravity.py`:

```python
"""Antigravity's trust setting. `agy` refuses even to read files outside
the folders listed in trustedWorkspaces, in one settings file for the whole
machine, so a repository has to be added there before it can take part.
Only trust() writes that file, and only when a person said yes."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from whyline_relay import config

# The README's verified set; narrower patterns did not work.
ALLOW = ("read_file(*)", "write_file(*)", "edit_file(*)", "command(*)")


class SettingsUnreadable(RuntimeError):
    """The settings file exists but isn't a JSON object of the expected shape."""


def settings_path() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli" / "settings.json"


def _load() -> dict:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SettingsUnreadable(f"{path} is not valid JSON ({error}); fix it by hand") from error
    workspaces = data.get("trustedWorkspaces", []) if isinstance(data, dict) else None
    permissions = data.get("permissions", {}) if isinstance(data, dict) else None
    allow = permissions.get("allow", []) if isinstance(permissions, dict) else None
    if not all(isinstance(value, list) for value in (workspaces, allow)):
        raise SettingsUnreadable(
            f"{path} has an unexpected shape (trustedWorkspaces and permissions.allow "
            "must be lists); fix it by hand"
        )
    return data


def is_trusted(root: Path) -> bool:
    try:
        data = _load()
    except SettingsUnreadable:
        return False
    return str(Path(root).resolve()) in data.get("trustedWorkspaces", [])


def trust(root: Path) -> Path:
    data = _load()
    workspaces = data.setdefault("trustedWorkspaces", [])
    repo = str(Path(root).resolve())
    if repo not in workspaces:
        workspaces.append(repo)
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    allow.extend(rule for rule in ALLOW if rule not in allow)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(data, out, indent=2)
        out.write("\n")
    os.replace(temp, path)
    return path


def declined_path(root: Path) -> Path:
    return config.relay_dir(root) / "antigravity-declined"


def is_declined(root: Path) -> bool:
    return declined_path(root).exists()


def decline(root: Path) -> None:
    path = declined_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("The user chose not to trust this repository for Antigravity.\n")


def forget_decline(root: Path) -> None:
    declined_path(root).unlink(missing_ok=True)
```

- [ ] **Step 4: Ignore the decline file**

In `src/whyline_relay/gitcheck.py`, add `".whyline/relay/antigravity-declined",` as the last entry of the `RELAY_IGNORE` tuple.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_antigravity_trust.py -q && uv run pytest -q`
Expected: PASS. If a test pins `RELAY_IGNORE`'s exact contents, add the new entry to its expected value.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/antigravity.py src/whyline_relay/gitcheck.py tests/test_antigravity_trust.py
git commit -m "feat: add Antigravity trust helpers (RPF-2)"
whyline note "Antigravity trust is written only by antigravity.trust, after a person agrees" --because "the settings file covers the whole machine, so trusting a repo loosens every agy session" --rejected "Trust automatically on first use: silently widens a machine-wide permission" --file src/whyline_relay/antigravity.py --actor <agent> --role implementer --task RPF-2
```

### Task 3: Failures say why

**Files:**
- Modify: `src/whyline_relay/agents.py:31-37` (`RATE_LIMIT_MARKERS`)
- Modify: `src/whyline_relay/brainstorm.py` (`_emit_outcome`, pass zero's `if not record["ok"]` branch, the three `except Exception` branches that call `classify_failure(error=error)`)
- Test: `tests/test_brainstorm_failure_reason.py` (create)

**Interfaces:**
- Produces: `brainstorm.failure_reason(record: dict | None = None, error: BaseException | None = None) -> str` returning `"<category>"` or `"<category> — <detail>"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_brainstorm_failure_reason.py`:

```python
from whyline_relay import agents, brainstorm


def _record(response="", raw=""):
    return {"ok": False, "response": response, "raw": raw}


def test_claudes_limit_wording_is_a_rate_limit():
    assert agents.rate_limited("You've hit your limit · resets 3pm")
    reason = brainstorm.failure_reason(record=_record(
        raw='{"type":"result","is_error":true,"result":"You\'ve hit your limit · resets 3pm"}'
    ))
    assert reason.startswith("quota/rate-limit — ")
    assert "hit your limit" in reason


def test_an_unknown_failure_shows_the_agents_last_line():
    reason = brainstorm.failure_reason(record=_record(raw="starting\nError: model not found\n"))
    assert reason == "generic non-zero failure — Error: model not found"


def test_the_detail_is_one_printable_line_of_at_most_160_characters():
    reason = brainstorm.failure_reason(record=_record(raw="x" * 5000 + "\x1b[31m\x07"))
    detail = reason.split(" — ", 1)[1]
    assert len(detail) <= 160 and detail.isprintable()


def test_no_output_gives_the_category_alone():
    assert brainstorm.failure_reason(record=_record()) == "generic non-zero failure"


def test_an_exception_keeps_its_message():
    reason = brainstorm.failure_reason(error=RuntimeError("boom: socket closed"))
    assert reason == "generic non-zero failure — boom: socket closed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_brainstorm_failure_reason.py -q`
Expected: FAIL with `AttributeError: module 'whyline_relay.brainstorm' has no attribute 'failure_reason'` (and the first assertion fails on `rate_limited`).

- [ ] **Step 3: Add the markers**

In `src/whyline_relay/agents.py`, make `RATE_LIMIT_MARKERS`:

```python
RATE_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "rate_limit",
    "quota exceeded",
    "too many requests",
    "hit your limit",
    "limit reached",
    "session limit",
    "weekly limit",
    "out of credits",
)
```

- [ ] **Step 4: Add `failure_reason`**

In `src/whyline_relay/brainstorm.py`, directly after `classify_failure`, add:

```python
def _one_line(text: str) -> str:
    """The detail worth showing: a JSON result's text, else the last
    non-blank line; printable characters only, at most 160."""
    from whyline_relay.adapters.base import json_object

    parsed = json_object(text)
    if isinstance(parsed, dict):
        for key in ("result", "error", "message"):
            if isinstance(parsed.get(key), str) and parsed[key].strip():
                text = parsed[key]
                break
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "".join(ch for ch in lines[-1].strip() if ch.isprintable())[:160].strip()


def failure_reason(
    record: dict | None = None,
    error: BaseException | None = None,
) -> str:
    """classify_failure's category plus the agent's own words, so a usage
    limit or a crash reads as itself instead of "generic non-zero failure"."""
    category = classify_failure(record=record, error=error)
    if error is not None:
        detail = _one_line(str(error))
    else:
        detail = _one_line(str((record or {}).get("response") or "")) or _one_line(
            str((record or {}).get("raw") or "")
        )
    return f"{category} — {detail}" if detail and detail != category else category
```

Check first that `json_object` is the name exported by `src/whyline_relay/adapters/base.py` (it is used by `extract_or_fallback` there). If it has a different name, import that name instead.

- [ ] **Step 5: Use it everywhere a failed turn is reported**

In `src/whyline_relay/brainstorm.py`:

1. `_emit_outcome`: replace `reason = classify_failure(record=record)` with `reason = failure_reason(record=record)`.
2. Pass zero's `if not record["ok"]:` branch: replace its body's first two lines and the print with:

```python
        if not record["ok"]:
            reason = failure_reason(record=record)
            watch.emit("failed", reason=reason)
            print_fn(f"{label} could not research this pass: {reason}")
            status_map[agent_key] = AgentStatus(
                status="failed", reason=classify_failure(record=record)
            )
            continue
```

3. Pass zero's `except Exception as error:` branch: replace the `msg = (...)` block and `watch.emit(status, reason=category)` with:

```python
            reason = failure_reason(error=error)
            watch.emit(status, reason=reason)
            print_fn(f"{label} could not research this pass: {reason}")
```

   Keep `category = classify_failure(error=error)` for `status_map`, and delete the now-unused `detail` variable.
4. Review pass `except Exception as error:` branch: `watch.emit("failed", reason=failure_reason(error=error))` and `print_fn(f"{label} could not review this pass: {failure_reason(error=error)}")`.
5. Final synthesis `except Exception as error:` branch: `watch.emit("failed", reason=failure_reason(error=error))`.

`AgentStatus.reason` keeps the bare category, because other code compares it with the `FAILURE_*` constants.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_brainstorm_failure_reason.py -q && uv run pytest -q`
Expected: PASS. If an existing progress test asserts an exact line such as `"... failed pass-zero (4s): generic non-zero failure"` for a record with output, update it to the new `" — <detail>"` form.

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/agents.py src/whyline_relay/brainstorm.py tests/test_brainstorm_failure_reason.py
git commit -m "fix: say why a brainstorm turn failed (RPF-3)"
whyline note "Failed brainstorm turns report the category plus the agent's own last line" --because "a usage limit was shown as 'generic non-zero failure' with the agent's message dropped" --rejected "Only add more limit markers: unknown failures would still say nothing" --file src/whyline_relay/brainstorm.py --actor <agent> --role implementer --task RPF-3
```

### Task 4: Release whyline-relay 0.2.28

**Files:**
- Modify: `pyproject.toml` (`version`), `src/whyline_relay/__init__.py` (`__version__`), `uv.lock`
- Create: `docs/releases/v0.2.28.md`

- [ ] **Step 1: Bump and write notes**

```bash
sed -i '' 's/^version = "0.2.27"/version = "0.2.28"/' pyproject.toml
sed -i '' 's/__version__ = "0.2.27"/__version__ = "0.2.28"/' src/whyline_relay/__init__.py
uv lock
```

Create `docs/releases/v0.2.28.md`:

```markdown
# whyline-relay 0.2.28

grok and antigravity work in every repository, and failed turns say why.

## What's changed

- grok and antigravity run from the README's verified recipes when a
  repository's config doesn't define them, in chat, brainstorm and every
  relay role. A repository's own `[agents.<name>]` (or the older
  `[agents.agy]`) still wins.
- `antigravity.trust`, `is_trusted` and `decline` manage Antigravity's
  machine-wide `trustedWorkspaces` setting. Nothing calls `trust` without a
  person agreeing; whyline's console asks once per repository.
- A failed brainstorm turn now says why, in the agent's own words, e.g.
  `quota/rate-limit — You've hit your limit · resets 3pm`. Claude's newer
  limit wording is recognised as a usage limit.

## Upgrading

```bash
uv tool upgrade whyline
```
```

- [ ] **Step 2: Test, merge and tag**

```bash
uv run pytest -q
git add pyproject.toml uv.lock src/whyline_relay/__init__.py docs/releases/v0.2.28.md .whyline/decisions.md
git commit -m "chore: release whyline-relay 0.2.28 (RPF-4)"
git push origin HEAD:main
git tag v0.2.28 && git push origin v0.2.28
gh run watch "$(gh run list --workflow release.yml -L1 --json databaseId -q '.[0].databaseId')" --exit-status
```

Expected: all tests pass, the push fast-forwards `main`, and the release workflow succeeds. `curl -s https://pypi.org/pypi/whyline-relay/json | python3 -c "import sys,json;print(json.load(sys.stdin)['info']['version'])"` prints `0.2.28` (it can take a minute).

---

# Part B — whyline 0.3.31 (repo `~/agentdock`, branch `relay/plan-flow`)

### Task 5: Every installed relay agent is offered

**Files:**
- Modify: `pyproject.toml` (both `whyline-relay>=0.2.26,<0.3` → `whyline-relay>=0.2.28,<0.3`), `uv.lock`
- Modify: `src/whyline/console/relay_ops.py` (`relay_agents`, `current_roles`)
- Modify: `src/whyline/console/relay_screens.py` (`RelaySetupScreen.__init__`)
- Modify: `src/whyline/console/adapters.py:293-298` (the skip message)
- Test: `tests/console/test_relay_ops.py`

**Interfaces:**
- Produces: `relay_ops.relay_agents(root: Path, which=shutil.which) -> list[str]` — names in the loaded relay config whose binary is on PATH, sorted. `antigravity`'s binary is `agy` (`whyline_relay.chat.agent_binary`). Falls back to the built-ins when the config can't be loaded.

- [ ] **Step 1: Bump the dependency**

```bash
cd ~/agentdock
sed -i '' 's/whyline-relay>=0.2.26,<0.3/whyline-relay>=0.2.28,<0.3/g' pyproject.toml
uv lock --upgrade-package whyline-relay && uv sync
uv run python -c "import whyline_relay; print(whyline_relay.__version__)"
```

Expected: `0.2.28`.

- [ ] **Step 2: Write the failing tests**

In `tests/console/test_relay_ops.py`, replace `test_relay_agents_are_the_relay_builtins` with:

```python
def test_relay_agents_lists_installed_agents_including_recipes(repo):
    on_path = {"claude", "codex", "agy", "grok"}
    which = lambda binary: f"/bin/{binary}" if binary in on_path else None
    assert relay_ops.relay_agents(repo, which=which) == ["antigravity", "claude", "codex", "grok"]


def test_relay_agents_leaves_out_what_is_not_installed(repo):
    which = lambda binary: "/bin/x" if binary in ("claude", "grok") else None
    assert relay_ops.relay_agents(repo, which=which) == ["claude", "grok"]


def test_current_roles_accepts_grok(repo, monkeypatch):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root, which=None: ["claude", "codex", "grok"])
    relay_ops.save_roles(repo, "grok", "claude", "codex", ["grok"])
    assert relay_ops.current_roles(repo) == {
        "implementer": "grok", "tester": "claude", "reviewer": "codex", "backup": ["grok"],
    }
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/console/test_relay_ops.py -q`
Expected: FAIL with `TypeError: relay_agents() got an unexpected keyword argument 'which'`.

- [ ] **Step 4: Implement**

In `src/whyline/console/relay_ops.py`, add `import shutil` and replace `relay_agents`:

```python
def relay_agents(root: Path | None = None, which=shutil.which) -> list[str]:
    """Agents the relay can run here that are installed: its built-ins plus
    the configured or recipe generic agents (grok, antigravity)."""
    from whyline_relay import adapters as relay_adapters, chat, config

    names = set(relay_adapters.BUILTIN)
    if root is not None:
        try:
            names |= set(config.load(root).agents)
        except Exception:  # an unreadable config: offer the built-ins only
            pass
    names = {chat.canonical_agent(name) for name in names}
    return sorted(name for name in names if which(chat.agent_binary(name)))
```

In `current_roles`, change `agents = relay_agents()` to `agents = relay_agents(root)`. In `RelaySetupScreen.__init__` (`src/whyline/console/relay_screens.py`), change `self._agents = relay_ops.relay_agents()` to `self._agents = relay_ops.relay_agents(root)`.

In `src/whyline/console/adapters.py`, replace the skip message with:

```python
        progress(
            "Skipping (no command configured here): "
            + ", ".join(l for _, l in skipped)
            + " -- see `whyline relay doctor`"
        )
```

- [ ] **Step 5: Run the console tests**

Run: `uv run pytest tests/console -q`
Expected: PASS. The setup-screen tests stub `relay_agents` with `lambda: [...]`; change those stubs to `lambda root=None, which=None: [...]`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/whyline/console/relay_ops.py src/whyline/console/relay_screens.py src/whyline/console/adapters.py tests/console
git commit -m "feat: offer every installed relay agent, including grok and antigravity (RPF-5)"
whyline note "Console relay roles list installed agents from the loaded relay config" --because "relay 0.2.28 runs grok and antigravity from recipes, so limiting roles to built-ins hid working agents" --file src/whyline/console/relay_ops.py --actor <agent> --role implementer --task RPF-5
```

### Task 6: Ask once per repository before trusting Antigravity

**Files:**
- Modify: `src/whyline/console/relay_ops.py` (trust wrappers)
- Modify: `src/whyline/console/tui.py` (`ConfirmScreen` cancel label; `_start_brainstorm`, `_dispatch_text`, `_launch_relay`; new `_needs_antigravity`/`_with_antigravity` helpers)
- Test: `tests/console/test_antigravity_trust.py` (create)

**Interfaces:**
- Consumes: `whyline_relay.antigravity.is_trusted/trust/is_declined/decline/forget_decline` (Task 2).
- Produces: `relay_ops.antigravity_state(root) -> str` (`"trusted"`, `"declined"` or `"ask"`); `relay_ops.trust_antigravity(root) -> None`; `relay_ops.decline_antigravity(root) -> None`; `relay_ops.forget_antigravity_decline(root) -> None`; `ConfirmScreen(message, confirm_label, cancel_label="Cancel")`; `WhylineConsoleApp._with_antigravity(uses: bool, proceed: Callable[[bool], None])`, which calls `proceed(True)` when antigravity may run and `proceed(False)` when it must be left out.

- [ ] **Step 1: Write the failing tests**

Create `tests/console/test_antigravity_trust.py`:

```python
import pytest

from whyline.console import relay_ops, tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture
def trust(monkeypatch):
    calls = {"state": "ask", "trusted": 0, "declined": 0}
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: calls["state"])

    def do_trust(root):
        calls["trusted"] += 1
        calls["state"] = "trusted"

    def do_decline(root):
        calls["declined"] += 1
        calls["state"] = "declined"

    monkeypatch.setattr(relay_ops, "trust_antigravity", do_trust)
    monkeypatch.setattr(relay_ops, "decline_antigravity", do_decline)
    return calls


def _lines(app):
    return [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]


async def test_trust_it_trusts_and_proceeds_with_antigravity(tmp_path, trust):
    seen = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._with_antigravity(True, seen.append)
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert trust["trusted"] == 1 and seen == [True]


async def test_not_now_declines_proceeds_without_and_never_asks_again(tmp_path, trust):
    seen = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._with_antigravity(True, seen.append)
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        app._with_antigravity(True, seen.append)
        await pilot.pause()
        assert not isinstance(app.screen, tui.ConfirmScreen)
        assert any("isn't trusted" in line for line in _lines(app))
    assert trust["declined"] == 1 and seen == [False, False]


async def test_nothing_is_asked_when_antigravity_is_not_used(tmp_path, trust):
    seen = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._with_antigravity(False, seen.append)
        await pilot.pause()
        assert not isinstance(app.screen, tui.ConfirmScreen)
    assert seen == [True]


async def test_a_brainstorm_drops_antigravity_when_declined(tmp_path, trust, monkeypatch):
    trust["state"] = "declined"
    started = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_run_brainstorm_choice", lambda choice: started.append(choice))
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_brainstorm({
            "topic": "t", "agents": ["claude", "antigravity"], "passes": 1,
            "final_agent": "antigravity", "timeout_minutes": 15,
        })
        await pilot.pause()
    assert started[0]["agents"] == ["claude"]
    assert started[0]["final_agent"] == "claude"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/console/test_antigravity_trust.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'antigravity_state'`.

- [ ] **Step 3: Add the relay_ops wrappers**

Append to `src/whyline/console/relay_ops.py`:

```python
def antigravity_state(root: Path) -> str:
    from whyline_relay import antigravity

    if antigravity.is_trusted(root):
        return "trusted"
    return "declined" if antigravity.is_declined(root) else "ask"


def trust_antigravity(root: Path) -> None:
    from whyline_relay import antigravity

    antigravity.trust(root)
    antigravity.forget_decline(root)


def decline_antigravity(root: Path) -> None:
    from whyline_relay import antigravity

    antigravity.decline(root)


def forget_antigravity_decline(root: Path) -> None:
    from whyline_relay import antigravity

    antigravity.forget_decline(root)
```

- [ ] **Step 4: Give `ConfirmScreen` a cancel label**

In `src/whyline/console/tui.py`, change `ConfirmScreen.__init__` to `def __init__(self, message: str, confirm_label: str, cancel_label: str = "Cancel") -> None:`, store `self._cancel_label = cancel_label`, and use `Button(self._cancel_label, id="cancel")` in `compose`.

- [ ] **Step 5: Add the gate to the app**

In `WhylineConsoleApp`, add:

```python
    _ANTIGRAVITY_SKIP = (
        "Skipping Antigravity: this repo isn't trusted in its settings "
        "(Model → Antigravity to ask again)."
    )

    def _with_antigravity(self, uses: bool, proceed) -> None:
        """Before anything runs antigravity: trusted, go; declined for this
        repo, go without it; otherwise ask once (spec section 8)."""
        if not uses:
            proceed(True)
            return
        try:
            state = relay_ops.antigravity_state(self.session.root)
        except Exception:  # relay missing: let the run report it
            state = "trusted"
        if state == "trusted":
            proceed(True)
            return
        if state == "declined":
            self.render_event(SessionEvent(kind="output", text=self._ANTIGRAVITY_SKIP))
            proceed(False)
            return
        from whyline_relay import antigravity

        message = (
            "Antigravity can only read and edit files in folders listed in "
            f"{antigravity.settings_path()}, a setting for the whole machine. Add "
            f"{self.session.root} to it, and allow Antigravity's file and command tools?"
        )

        def answered(trusted: bool) -> None:
            if trusted:
                try:
                    relay_ops.trust_antigravity(self.session.root)
                except Exception as error:  # e.g. SettingsUnreadable
                    self.render_event(SessionEvent(kind="error", text=str(error)))
                    proceed(False)
                    return
                proceed(True)
                return
            relay_ops.decline_antigravity(self.session.root)
            self.render_event(SessionEvent(kind="output", text=self._ANTIGRAVITY_SKIP))
            proceed(False)

        self.push_screen(ConfirmScreen(message, "Trust it", "Not now"), answered)
```

Split `_start_brainstorm` so the gate runs first. Rename the existing body after the `if choice is None: return` check to `_run_brainstorm_choice(self, choice: dict) -> None`, and make `_start_brainstorm`:

```python
    def _start_brainstorm(self, choice: "dict | None") -> None:
        if choice is None:
            return

        def proceed(allowed: bool) -> None:
            if not allowed:
                agents = [a for a in choice["agents"] if a != "antigravity"]
                if not agents:
                    self.render_event(SessionEvent(
                        kind="error", text="No model is left to brainstorm with."))
                    return
                final = choice["final_agent"]
                choice.update(agents=agents, final_agent=final if final in agents else agents[0])
            self._run_brainstorm_choice(choice)

        self._with_antigravity("antigravity" in choice["agents"], proceed)
```

In `_dispatch_text`, wrap the existing body:

```python
    def _dispatch_text(self, text: str) -> None:
        uses = self.session.mode == "chat" and (self.session.agent or "claude") == "antigravity"

        def proceed(allowed: bool) -> None:
            if not allowed:
                self.render_event(SessionEvent(
                    kind="error", text="Antigravity can't run here until this repo is trusted."))
                return
            token = object()
            self._dispatch_token = token
            self._set_busy(True)
            self.run_worker(lambda: self._dispatch_in_thread(text, token), thread=True)

        self._with_antigravity(uses, proceed)
```

In `_launch_relay`, after the `_refuse_in_home` check, gate on the roles:

```python
        roles = relay_ops.current_roles(self.session.root)
        uses = "antigravity" in (
            roles["implementer"], roles["tester"], roles["reviewer"], *roles["backup"]
        )
        if uses and not getattr(self, "_antigravity_ok", False):
            def proceed(allowed: bool) -> None:
                if allowed:
                    self._antigravity_ok = True
                    self._launch_relay(args)
                else:
                    self.render_event(SessionEvent(
                        kind="error",
                        text="The relay gives Antigravity a role, but this repo isn't "
                             "trusted for it. Change the role in Set up, or choose it "
                             "there again to be asked."))

            self._with_antigravity(True, proceed)
            return
        self._antigravity_ok = False
```

The `_antigravity_ok` flag lets the re-entrant call continue past the gate once. Initialise `self._antigravity_ok = False` in `__init__`.

Where the Model picker sets the chat agent to `antigravity` (the `/model` handling in `repl.py`, `handle_slash_command`), and when Set up saves a role of `antigravity`, call `relay_ops.forget_antigravity_decline(root)` so the next run asks again. In Set up, do it in `_check`'s thread right before `save_roles`, when `"antigravity"` is one of the chosen names.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/console -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline/console/relay_ops.py src/whyline/console/tui.py src/whyline/console/relay_screens.py src/whyline/console/repl.py tests/console/test_antigravity_trust.py
git commit -m "feat: ask once per repo before trusting Antigravity (RPF-6)"
whyline note "Console asks once per repo before adding it to Antigravity's machine-wide trust" --because "agy cannot read an untrusted repo, and the setting loosens every agy session on the machine" --rejected "Only print the manual instructions: every new repo would need hand-editing JSON" --file src/whyline/console/tui.py --actor <agent> --role implementer --task RPF-6
```

### Task 7: Release whyline 0.3.31

**Files:**
- Modify: `pyproject.toml` (`version = "0.3.31"`), `src/whyline/__init__.py` (`__version__ = "0.3.31"`), `uv.lock`
- Create: `docs/releases/v0.3.31.md`

- [ ] **Step 1: Bump and write notes**

```bash
sed -i '' 's/^version = "0.3.30"/version = "0.3.31"/' pyproject.toml
sed -i '' 's/"0.3.30"/"0.3.31"/' src/whyline/__init__.py
grep -n "0.3.31" pyproject.toml src/whyline/__init__.py
uv lock
```

Create `docs/releases/v0.3.31.md`:

```markdown
# whyline 0.3.31

grok and antigravity work in every repository.

## What's changed

- Chat, brainstorm and the relay's roles now offer grok and antigravity in
  any repository where they're installed, with no setup (needs
  whyline-relay 0.2.28).
- The first time something would run Antigravity in a repository, the
  console asks whether to add that repository to Antigravity's machine-wide
  trust setting. "Not now" is remembered for that repository.
- A failed brainstorm turn says why, e.g. `quota/rate-limit — You've hit
  your limit · resets 3pm`.

## Upgrading

```bash
uv tool upgrade whyline
```
```

- [ ] **Step 2: Test, merge, tag, verify**

```bash
uv run pytest -q
git add pyproject.toml uv.lock src/whyline/__init__.py docs/releases/v0.3.31.md .whyline/decisions.md
git commit -m "chore: release whyline 0.3.31 (RPF-7)"
git push origin HEAD:main
git tag v0.3.31 && git push origin v0.3.31
gh run watch "$(gh run list --workflow release.yml -L1 --json databaseId -q '.[0].databaseId')" --exit-status
uv tool upgrade whyline && whyline --version
```

Expected: tests pass, the workflow succeeds, and `whyline --version` prints `0.3.31`. If `git push origin HEAD:main` is rejected as non-fast-forward, stop and report; don't force.

---

# Part C — whyline-relay 0.2.29 (repo `~/whyline-relay`)

Before Task 8:

```bash
cd ~/whyline-relay && git fetch origin && git switch -c relay/plan-flow origin/main
uv run pytest -q
```

### Task 8: The planner asks questions and takes answers

**Files:**
- Modify: `src/whyline_relay/planner.py` (new `PlanQuestions`, `_blocked`, `answer_feedback`, `answer`; the two `blocked` raises in `_run_pipeline`)
- Modify: `src/whyline_relay/prompts.py` (`PLAN_DRAFT`, `PLAN_REVIEW`)
- Modify: `src/whyline_relay/brainstorm.py` (`PLAN_GENERATION_PROMPT`)
- Modify: `tests/fake_pipeline_agent.py` (questions after `#`)
- Test: `tests/test_planner_questions.py` (create)

**Interfaces:**
- Produces: `planner.PlanQuestions(loop.Paused)` with attributes `questions: tuple[str, ...]`, `stage: str`, `agent: str`; `planner.answer(root, settings, answers: str, *, print_fn=None, runner=subprocess.run) -> Path` (the draft path; can raise `PlanQuestions` again); `planner.answer_feedback(questions: Sequence[str], answers: str) -> str`.

- [ ] **Step 1: Teach the fake agent to ask**

In `tests/fake_pipeline_agent.py`, after `spec = sys.argv[1]`, split off questions, and add them to the handoff record:

```python
    spec, _, asked = spec.partition("#")
    questions = [q for q in asked.split("|") if q]
```

Add `"questions": questions,` to the dict passed to `json.dumps(...)`, and update the module docstring: `argv[1] is "to_actor:status", optionally "#q1|q2" for a handoff's questions`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_planner_questions.py`:

```python
import pytest

from whyline_relay import brainstorm, loop, planner, prompts, state
from tests.test_planner import DESCRIPTION, _scripted_run, repo, settings_with_planner  # noqa: F401


def test_a_blocked_handoff_with_questions_raises_plan_questions(repo, monkeypatch):
    settings = settings_with_planner(repo)
    monkeypatch.setattr(loop.agents, "run", _scripted_run(
        ["codex:blocked#Which broker? (a) Kite (b) Upstox|Paper trading in V1?"]
    ))
    with pytest.raises(planner.PlanQuestions) as raised:
        planner.draft(repo, settings, DESCRIPTION)
    assert raised.value.questions == ("Which broker? (a) Kite (b) Upstox", "Paper trading in V1?")
    assert raised.value.stage == "draft" and raised.value.agent == "codex"
    assert state.load_plan(repo).stage == "draft"


def test_blocked_without_questions_is_still_a_plain_pause(repo, monkeypatch):
    settings = settings_with_planner(repo)
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["codex:blocked"]))
    with pytest.raises(loop.Paused) as raised:
        planner.draft(repo, settings, DESCRIPTION)
    assert not isinstance(raised.value, planner.PlanQuestions)


def test_answer_reruns_the_stage_that_asked_with_the_answers(repo, monkeypatch):
    settings = settings_with_planner(repo)
    prompts_seen = []
    scripted = _scripted_run(["claude:ready", "claude:blocked#Which broker?", "claude:approved"])

    def run(command, prompt, **kwargs):
        prompts_seen.append(prompt)
        return scripted(command, prompt, **kwargs)

    monkeypatch.setattr(loop.agents, "run", run)
    with pytest.raises(planner.PlanQuestions):
        planner.draft(repo, settings, DESCRIPTION)
    assert state.load_plan(repo).stage == "review"
    path = planner.answer(repo, settings, "Kite")
    assert path == planner.draft_path(repo)
    assert len(prompts_seen) == 3
    assert "You asked:\n1. Which broker?\nThe human answered:\nKite" in prompts_seen[2]
    assert state.load_plan(repo).stage == "@complete"


def test_resume_shows_the_questions_again(repo, monkeypatch):
    settings = settings_with_planner(repo)
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["codex:blocked#Which broker?"]))
    with pytest.raises(planner.PlanQuestions):
        planner.draft(repo, settings, DESCRIPTION)
    with pytest.raises(planner.PlanQuestions) as raised:
        planner.resume_draft(repo, settings)
    assert raised.value.questions == ("Which broker?",)


def test_answer_feedback_without_recorded_questions():
    assert planner.answer_feedback((), "use Kite") == (
        "The human answered your questions:\nuse Kite"
    )


def test_prompts_ask_for_choices_inside_questions():
    for text in (prompts.PLAN_DRAFT, prompts.PLAN_REVIEW, brainstorm.PLAN_GENERATION_PROMPT):
        assert "(a)" in text and "(b)" in text
    assert "## Open questions" in brainstorm.PLAN_GENERATION_PROMPT
```

Check before running: `_scripted_run` in `tests/test_planner.py` calls the fake with `[sys.executable, FAKE, spec, str(cwd), prompt]`. The third test wraps it to capture each prompt. If the import of a fixture from another test module is refused by the suite's pytest config, move `repo`, `settings_with_planner` and `_scripted_run` into `tests/conftest.py` unchanged and import nothing.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_planner_questions.py -q`
Expected: FAIL with `AttributeError: module 'whyline_relay.planner' has no attribute 'PlanQuestions'`.

- [ ] **Step 4: Implement questions in the planner**

In `src/whyline_relay/planner.py`, add `from collections.abc import Sequence` to the imports, then after `NoPlanInProgress`:

```python
class PlanQuestions(loop.Paused):
    """A plan stage stopped to ask a person something. The checkpoint keeps
    the stage, so answer() re-runs exactly that stage."""

    def __init__(self, reason, log_path, *, questions, stage: str, agent: str):
        super().__init__(reason, log_path)
        self.questions = tuple(questions)
        self.stage = stage
        self.agent = agent


def _blocked(record: handoff.Handoff, stage: str, agent: str, target) -> loop.Paused:
    if record.questions:
        return PlanQuestions(
            _blocked_reason(record), target,
            questions=record.questions, stage=stage, agent=agent,
        )
    return loop.Paused(_blocked_reason(record), target)


def answer_feedback(questions: Sequence[str], answers: str) -> str:
    if not questions:
        return f"The human answered your questions:\n{answers.strip()}"
    asked = "\n".join(f"{number}. {q}" for number, q in enumerate(questions, 1))
    return f"You asked:\n{asked}\nThe human answered:\n{answers.strip()}"
```

`PlanQuestions` must be defined after `NoPlanInProgress` (line ~345), which is below `_run_pipeline`. That is fine at runtime because `_run_pipeline` only looks the name up when it runs.

In `_run_pipeline`, replace the consult-handoff branch's `raise loop.Paused(_blocked_reason(previous), None)` with:

```python
                stage_agent = pipe.roles[pipe.stages[current_stage_id].role].agent
                raise _blocked(previous, current_stage_id, stage_agent, None)
```

In the main loop, replace `raise loop.Paused(_blocked_reason(record), target)` with `raise _blocked(record, current_stage_id, agent, target)`.

Add `answer` after `resume_draft`:

```python
def answer(
    root: Path,
    settings: config.Config,
    answers: str,
    *,
    print_fn=None,
    runner: failover.Runner = subprocess.run,
) -> Path:
    """Re-runs the stage that asked, with the person's answers as its
    feedback. Raises PlanQuestions again if it still needs something."""
    saved = state.load_plan(root)
    if saved is None:
        raise NoPlanInProgress("no plan draft is in progress")
    record = handoff.read(root)
    asked = record.questions if record is not None and record.task == PLAN_TASK_ID else ()
    _run_pipeline(
        root,
        settings,
        saved.description,
        current_stage_id=saved.stage,
        round_=saved.round,
        stage_visits=saved.stage_visits,
        feedback=answer_feedback(asked, answers),
        echo=False,
        runner=runner,
        on_stage=_announcer(print_fn),
    )
    return draft_path(root)
```

- [ ] **Step 5: Add the prompt sentences**

In `src/whyline_relay/prompts.py`, in both `PLAN_DRAFT` and `PLAN_REVIEW`, insert this paragraph directly above the `## How to finish` line:

```
If a decision the description and reference documents don't settle blocks the
plan, hand off blocked with one --question per decision, and put the choices in
the question itself, e.g. "Which broker? (a) Kite (b) Upstox". Don't ask about
anything you can reasonably decide yourself.

```

`PLAN_REVIEW` has no `{review_feedback}` placeholder today (only `PLAN_DRAFT` does), so answers to a reviewer's question would never reach it. In `PLAN_REVIEW`, directly below the `{task_text}` line, add:

```

{review_feedback}
```

`prompts.render` already fills `review_feedback` for every stage, and passes an empty string when there is none. Check that the plan-draft golden or snapshot tests, if any, still pass.

In `src/whyline_relay/brainstorm.py`, extend `PLAN_GENERATION_PROMPT` by appending these string pieces before its closing parenthesis:

```python
    " If a decision the brainstorm does not settle blocks part of the plan, "
    'list it as a numbered item under an "## Open questions" heading at the '
    "top of the file, with the choices in the question itself, e.g. "
    '"1. Which broker? (a) Kite (b) Upstox"; still write every task you can.'
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_planner_questions.py -q && uv run pytest -q`
Expected: PASS. `test_a_blocked_outcome_pauses_instead_of_completing` still passes, because `PlanQuestions` is a `Paused` and a handoff without questions raises a plain `Paused`.

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/planner.py src/whyline_relay/prompts.py src/whyline_relay/brainstorm.py tests/fake_pipeline_agent.py tests/test_planner_questions.py
git commit -m "feat: planner questions and answers (RPF-8)"
whyline note "Planner questions raise PlanQuestions; answer() re-runs the saved stage with the answers" --because "the user chose stop-and-resume (option A); the stage that asked is the one that needs the answer" --rejected "Restart from the draft stage: discards a review stage's work" --file src/whyline_relay/planner.py --actor <agent> --role implementer --task RPF-8
```

### Task 9: Named plan files and config writers

**Files:**
- Modify: `src/whyline_relay/planner.py` (`approve`)
- Modify: `src/whyline_relay/setup.py` (new `_set_top_level`, `write_plan`, `write_planner`; `write_roles` keeps `plan` and `[planner]`)
- Test: `tests/test_plan_files.py` (create)

**Interfaces:**
- Produces: `planner.approve(root, settings, draft_path, *, drafted_by, replace=False, clear_checkpoint=False, target: Path | None = None) -> Path`; `setup.write_plan(root, plan: str, *, commit=True) -> Path`; `setup.write_planner(root, draft: str, review: str, *, commit=True) -> Path`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plan_files.py`:

```python
import subprocess
from pathlib import Path

import pytest

from whyline_relay import config, planner, setup


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def _config(root: Path) -> Path:
    return root / ".whyline" / "relay" / "config.toml"


def test_approve_to_a_named_file_commits_only_it(repo):
    draft = repo / "d.md"
    draft.write_text("<!-- whyline-plan v1 | source: paste -->\n- [ ] T-1: x\n  y.\n")
    target = repo / "plans" / "first.plan.md"
    result = planner.approve(repo, config.load(repo), draft, drafted_by="hand", target=target)
    assert result == target and target.read_text() == draft.read_text()
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["plans/first.plan.md"]
    assert _git(repo, "log", "-1", "--format=%s").strip() == (
        "docs: add plan plans/first.plan.md drafted by hand"
    )
    assert not (repo / "plan.md").exists()


def test_approve_without_target_still_writes_plan_md(repo):
    draft = repo / "d.md"
    draft.write_text("- [ ] T-1: x\n")
    assert planner.approve(repo, config.load(repo), draft, drafted_by="codex") == repo / "plan.md"
    assert _git(repo, "log", "-1", "--format=%s").strip() == "docs: add plan drafted by codex"


def test_write_plan_sets_only_the_top_level_key(repo):
    _config(repo).parent.mkdir(parents=True)
    _config(repo).write_text('# mine\nmax_rounds = 4\n\n[roles]\nimplementer = "codex"\n')
    setup.write_plan(repo, "plans/first.plan.md")
    text = _config(repo).read_text()
    assert text.startswith('# mine\nmax_rounds = 4\nplan = "plans/first.plan.md"\n')
    assert config.load(repo).plan == "plans/first.plan.md"
    setup.write_plan(repo, "plans/second.plan.md")
    assert config.load(repo).plan == "plans/second.plan.md"
    assert _config(repo).read_text().count("plan =") == 1


def test_write_plan_creates_a_missing_config(repo):
    setup.write_plan(repo, "plans/a.plan.md")
    assert config.load(repo).plan == "plans/a.plan.md"
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == [
        ".whyline/relay/config.toml"
    ]


def test_write_planner_sets_draft_and_review(repo):
    setup.write_planner(repo, "claude", "codex")
    loaded = config.load(repo)
    assert (loaded.planner.draft, loaded.planner.review) == ("claude", "codex")


def test_write_roles_on_an_old_config_keeps_every_other_setting(repo):
    _config(repo).parent.mkdir(parents=True)
    _config(repo).write_text(
        '# mine\nplan = "plan.md"\nmax_rounds = 6\ntimeout_minutes = 45\n'
        'branch_prefix = "work/"\n\n'
        '[roles]\nimplementer = "antigravity"\nreviewer = "codex"\n\n'
        '[status_map]\nready-for-review = "review"\n\n'
        '[agents.grok]\nadapter = "generic"\ncommand = [\n  "grok", "--mine",\n  "-p"\n]\n\n'
        '[planner]\ndraft = "claude"\n\n'
        '[backup]\nchain = ["claude"]\n'
    )
    setup.write_roles(repo, "antigravity", "claude", "codex", ["grok"])
    text = _config(repo).read_text()
    loaded = config.load(repo)
    assert loaded.pipeline is not None
    assert (loaded.max_rounds, loaded.timeout_minutes, loaded.branch_prefix) == (6, 45, "work/")
    assert loaded.agents["grok"] == ["grok", "--mine", "-p"]
    assert loaded.planner.draft == "claude"
    assert loaded.backup_chain == ["grok"]
    assert "[status_map]" not in text and text.startswith("# mine\n")
    assert text.count("[roles]") == 1


def test_write_roles_keeps_plan_and_planner_written_before_setup(repo):
    setup.write_planner(repo, "grok", "claude")
    setup.write_plan(repo, "plans/a.plan.md")
    setup.write_roles(repo, "codex", "claude", "claude")
    loaded = config.load(repo)
    assert loaded.pipeline is not None
    assert loaded.plan == "plans/a.plan.md"
    assert (loaded.planner.draft, loaded.planner.review) == ("grok", "claude")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_plan_files.py -q`
Expected: FAIL with `TypeError: approve() got an unexpected keyword argument 'target'`.

- [ ] **Step 3: Implement `approve(target=)`**

In `planner.approve`, add the keyword parameter `target: Path | None = None` and replace the body from `target = root / settings.plan` to the commit with:

```python
    named = target is not None
    target = target if named else root / settings.plan
    if target.exists() and not replace:
        raise PlanExists(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    if named:
        shown = target.relative_to(root).as_posix() if target.is_relative_to(root) else str(target)
        message = f"docs: add plan {shown} drafted by {drafted_by}"
    else:
        message = f"docs: add plan drafted by {drafted_by}"
    gitcheck.commit_paths(root, [target], message)
```

- [ ] **Step 4: Implement the config writers**

In `src/whyline_relay/setup.py`, after `_set_backup`, add:

```python
def _set_top_level(text: str, key: str, value: str) -> str:
    """Sets `key = "value"` above the first table, keeping everything else."""
    lines = text.splitlines()
    first_table = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines)
    )
    for index in range(first_table):
        match = re.match(rf"^(\s*{key}\s*=\s*).*$", lines[index])
        if match:
            lines[index] = f'{match.group(1)}"{value}"'
            return "\n".join(lines).rstrip("\n") + "\n"
    insert_at = first_table
    while insert_at > 0 and not lines[insert_at - 1].strip():
        insert_at -= 1
    new = [f'{key} = "{value}"']
    if first_table < len(lines):
        new.append("")
    lines[insert_at:first_table] = new
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_config(root: Path, change, message: str, commit: bool) -> Path:
    config_file = role_paths(root)[0]
    config_file.parent.mkdir(parents=True, exist_ok=True)
    existing = config_file.read_text(encoding="utf-8") if config_file.exists() else ""
    config_file.write_text(change(existing).lstrip("\n"), encoding="utf-8")
    if commit:
        gitcheck.commit_paths(root, [config_file], message)
    return config_file


def write_plan(root: Path, plan: str, *, commit: bool = True) -> Path:
    """Points the relay at `plan` (a path relative to the repository)."""
    return _write_config(
        root, lambda text: _set_top_level(text, "plan", plan), f"setup: run {plan}", commit
    )


def write_planner(root: Path, draft: str, review: str, *, commit: bool = True) -> Path:
    """Who drafts and who reviews plans ([planner] draft / review)."""
    return _write_config(
        root,
        lambda text: _set_keys(text, "planner", {"draft": draft, "review": review}),
        f"setup: plans drafted by {draft}, reviewed by {review}",
        commit,
    )
```

In `write_roles`, the `else:` branch must keep every setting the old file had (spec 6b): custom `[agents.*]`, `max_rounds`, `timeout_minutes`, `branch_prefix`, `plan`, `[planner]`, comments. Only `[roles]`, `[backup]` (rewritten by `_set_backup` right after) and `[status_map]` (can't be combined with `[pipeline]`) are dropped. Add this helper next to `_set_backup`:

```python
_TABLE_HEADER = re.compile(r"^\s*\[\[?([^\]]+)\]\]?\s*(#.*)?$")


def _without_tables(text: str, names: set[str]) -> str:
    """Drops the named top-level tables (header line through the line before
    the next header), keeping every other line exactly as it was."""
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        header = _TABLE_HEADER.match(line)
        if header:
            skipping = header.group(1).strip() in names
        if not skipping:
            kept.append(line)
    return "\n".join(kept).strip("\n")
```

and replace the `else:` branch with:

```python
    else:
        template = PIPELINE_CONFIG_TEMPLATE.format(
            implementer=implementer, tester=tester, reviewer=reviewer
        )
        kept = _without_tables(existing, {"roles", "backup", "status_map"})
        content = f"{kept}\n\n{template}" if kept else template
```

A multi-line array such as `command = [` … `]` is safe: its continuation lines never match `_TABLE_HEADER`, because they don't start with `[`. If a repository's config does have a continuation line starting with `[`, `config.load` in the test above will fail loudly rather than silently lose data.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_plan_files.py -q && uv run pytest -q`
Expected: PASS. `_set_keys` on an empty string returns text that starts with blank lines; `_write_config` strips them.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/planner.py src/whyline_relay/setup.py tests/test_plan_files.py
git commit -m "feat: named plan files and plan/planner config writers (RPF-9)"
whyline note "write_roles keeps every setting of an old config except roles, backup and status_map" --because "the template used to replace the whole file, silently dropping custom agent commands, max_rounds, plan and [planner]" --rejected "Carry over a list of known keys: any key not on the list would still be lost" --file src/whyline_relay/setup.py --actor <agent> --role implementer --task RPF-9
```

### Task 10: Release whyline-relay 0.2.29

Same steps as Task 4, with `0.2.28` → `0.2.29` in the `sed` lines, the tag `v0.2.29`, the commit `chore: release whyline-relay 0.2.29 (RPF-10)`, and `docs/releases/v0.2.29.md`:

```markdown
# whyline-relay 0.2.29

Plans can ask questions and live under any name.

## What's changed

- A plan stage that needs a decision hands off with questions and the
  planner raises `PlanQuestions`; `planner.answer` re-runs that stage with
  the person's answers. Plan prompts ask for the choices inside each
  question, e.g. "(a) Kite (b) Upstox".
- `planner.approve(target=...)` saves a plan anywhere in the repository
  (whyline uses `plans/<name>.plan.md`), committing only that file.
- `setup.write_plan` and `setup.write_planner` change one setting each and
  keep the rest of `config.toml`.
- Assigning roles on an older two-role config no longer throws the rest of
  the file away: custom agent commands, `max_rounds`, `timeout_minutes`,
  `branch_prefix`, the plan and `[planner]` are all kept.

## Upgrading

```bash
uv tool upgrade whyline
```
```

---

# Part D — whyline 0.3.32 (repo `~/agentdock`, branch `relay/plan-flow`)

### Task 11: relay_ops for plan files and questions

**Files:**
- Modify: `pyproject.toml` (both `>=0.2.28` → `>=0.2.29`), `uv.lock`
- Modify: `src/whyline/console/relay_ops.py`
- Test: `tests/console/test_relay_ops.py`

**Interfaces:**
- Consumes: Task 8's `planner.PlanQuestions`, `planner.answer`; Task 9's `approve(target=)`, `setup.write_plan`, `setup.write_planner`.
- Produces (all in `whyline.console.relay_ops`):
  - `PLANS_DIR = "plans"`
  - `@dataclass(frozen=True) class PlanInfo: path: Path; name: str; source: str; created: str; done: int; total: int`
  - `plan_slug(text: str) -> str`
  - `plan_path(root: Path, name: str) -> Path`
  - `with_marker(text: str, *, source: str, drafted_by: str, now: datetime | None = None) -> str`
  - `list_plans(root: Path) -> list[PlanInfo]`
  - `save_pasted_plan(root: Path, text: str, name: str, *, replace: bool = False) -> Path` (signature change)
  - `approve_plan(root: Path, draft: Draft, name: str, *, replace: bool = False) -> Path` (signature change)
  - `configured_plan(root: Path) -> Path | None`
  - `select_plan(root: Path, path: Path) -> None`
  - `planner_agents(root: Path) -> tuple[str, str]`
  - `save_planner(root: Path, draft: str, review: str) -> None`
  - `plan_questions_error()` → `whyline_relay.planner.PlanQuestions`
  - `answer_plan(root: Path, answers: str, *, progress) -> Draft`
  - `open_questions(text: str) -> list[str]`
  - `question_feedback(questions: Sequence[str], answers: str) -> str`
  - `Draft.drafted_by` for planner drafts becomes `"<draft> (reviewed by <review>)"`.

- [ ] **Step 1: Bump the dependency**

```bash
sed -i '' 's/whyline-relay>=0.2.28,<0.3/whyline-relay>=0.2.29,<0.3/g' pyproject.toml
uv lock --upgrade-package whyline-relay && uv sync
```

- [ ] **Step 2: Write the failing tests**

In `tests/console/test_relay_ops.py`, replace `test_save_pasted_plan_commits_plan_md` and `test_save_pasted_plan_asks_before_replacing`, and add the rest:

```python
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def test_plan_slug():
    assert relay_ops.plan_slug("Build the PRD: Trading Platform v1!") == "build-the-prd-trading-platform-v1"
    assert relay_ops.plan_slug("x" * 60) == "x" * 40
    assert relay_ops.plan_slug("!!!") == "plan"


def test_with_marker_puts_one_marker_on_line_one():
    now = datetime(2026, 10, 4, 10, 12, tzinfo=IST)
    text = relay_ops.with_marker("- [ ] T-1: x\n", source="paste", drafted_by="hand", now=now)
    assert text == (
        "<!-- whyline-plan v1 | source: paste | drafted-by: hand | "
        "created: 2026-10-04T10:12:00+05:30 -->\n- [ ] T-1: x\n"
    )
    again = relay_ops.with_marker(text, source="draft", drafted_by="codex", now=now)
    assert again.count("whyline-plan v1") == 1 and "source: draft" in again


def test_save_pasted_plan_writes_a_named_plan(repo):
    path = relay_ops.save_pasted_plan(repo, "- [ ] T-1: build it", "My Plan")
    assert path == repo / "plans" / "my-plan.plan.md"
    assert path.read_text().splitlines()[0].startswith("<!-- whyline-plan v1 | source: paste")
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["plans/my-plan.plan.md"]


def test_save_pasted_plan_asks_before_replacing(repo):
    relay_ops.save_pasted_plan(repo, "- [ ] OLD-1: old\n", "p")
    with pytest.raises(relay_ops.plan_exists_error()):
        relay_ops.save_pasted_plan(repo, "- [ ] T-1: new\n", "p")
    relay_ops.save_pasted_plan(repo, "- [ ] T-1: new\n", "p", replace=True)
    assert "T-1: new" in (repo / "plans" / "p.plan.md").read_text()


def test_list_plans_reads_markers_counts_and_the_legacy_plan(repo):
    plans = repo / "plans"
    plans.mkdir()
    (plans / "old.plan.md").write_text(
        "<!-- whyline-plan v1 | source: draft | drafted-by: codex | created: 2026-10-01T09:00:00+05:30 -->\n"
        "- [x] A-1: done\n- [ ] A-2: todo\n")
    (plans / "new.plan.md").write_text(
        "<!-- whyline-plan v1 | source: brainstorm | drafted-by: claude | created: 2026-10-03T09:00:00+05:30 -->\n"
        "- [ ] B-1: todo\n")
    (plans / "no-marker.plan.md").write_text("- [ ] C-1: x\n")
    (plans / "no-tasks.plan.md").write_text(
        "<!-- whyline-plan v1 | source: paste | drafted-by: hand | created: 2026-10-02T00:00:00+05:30 -->\nprose\n")
    (repo / "plan.md").write_text("- [ ] L-1: legacy\n")
    found = relay_ops.list_plans(repo)
    assert [(p.name, p.source, p.done, p.total) for p in found] == [
        ("new", "brainstorm", 0, 1),
        ("old", "draft", 1, 2),
        ("plan.md (older format)", "hand", 0, 1),
    ]


def test_select_plan_and_configured_plan(repo):
    path = relay_ops.save_pasted_plan(repo, "- [ ] T-1: x\n", "a")
    relay_ops.select_plan(repo, path)
    assert relay_ops.configured_plan(repo) == path


def test_planner_agents_default_and_saved(repo):
    assert relay_ops.planner_agents(repo) == ("codex", "claude")
    relay_ops.save_planner(repo, "claude", "codex")
    assert relay_ops.planner_agents(repo) == ("claude", "codex")


def test_open_questions_reads_only_that_section():
    text = (
        "# Plan\n\n## Open questions\n1. Which broker? (a) Kite (b) Upstox\n"
        "- Paper trading in V1?\n\n## Phase 1\n- [ ] T-1: x\n"
    )
    assert relay_ops.open_questions(text) == [
        "Which broker? (a) Kite (b) Upstox", "Paper trading in V1?",
    ]
    assert relay_ops.open_questions("- [ ] T-1: x\n") == []


def test_question_feedback():
    assert relay_ops.question_feedback(["Which broker?"], "Kite") == (
        "You listed these open questions:\n1. Which broker?\nThe human answered:\nKite\n"
        "Rewrite the whole plan with these decisions, and remove the answered "
        "questions from ## Open questions."
    )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/console/test_relay_ops.py -q`
Expected: FAIL with `AttributeError: module 'whyline.console.relay_ops' has no attribute 'plan_slug'`.

- [ ] **Step 4: Implement**

In `src/whyline/console/relay_ops.py`, add `import re`, `from collections.abc import Sequence` and `from datetime import datetime`, then add:

```python
PLANS_DIR = "plans"
_MARKER = "<!-- whyline-plan v1"
_SOURCE_LABELS = {"planner": "draft"}


@dataclass(frozen=True)
class PlanInfo:
    path: Path
    name: str
    source: str
    created: str
    done: int
    total: int


def plan_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].rstrip("-")
    return slug or "plan"


def plan_path(root: Path, name: str) -> Path:
    return root / PLANS_DIR / f"{plan_slug(name)}.plan.md"


def with_marker(text: str, *, source: str, drafted_by: str, now: datetime | None = None) -> str:
    created = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    lines = text.splitlines()
    if lines and lines[0].startswith(_MARKER):
        lines = lines[1:]
    body = "\n".join(lines).strip("\n")
    return (
        f"{_MARKER} | source: {source} | drafted-by: {drafted_by} | "
        f"created: {created} -->\n{body}\n"
    )


def _marker_fields(first_line: str) -> dict | None:
    if not first_line.startswith(_MARKER):
        return None
    fields = {}
    for part in first_line.strip().removesuffix("-->").split("|")[1:]:
        key, _, value = part.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _counts(text: str) -> tuple[int, int] | None:
    from whyline_relay import plan

    try:
        tasks = plan.parse(text)
    except plan.PlanError:
        return None
    if not tasks:
        return None
    return sum(task.checked for task in tasks), len(tasks)


def list_plans(root: Path) -> list[PlanInfo]:
    """Every saved plan, newest first; a valid legacy plan.md last."""
    found: list[PlanInfo] = []
    folder = root / PLANS_DIR
    for path in sorted(folder.glob("*.plan.md")) if folder.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        fields = _marker_fields(text.split("\n", 1)[0])
        counts = _counts(text)
        if fields is None or counts is None:
            continue
        found.append(PlanInfo(
            path, path.name.removesuffix(".plan.md"), fields.get("source", ""),
            fields.get("created", ""), *counts,
        ))
    found.sort(key=lambda info: info.created, reverse=True)
    legacy = root / "plan.md"
    if legacy.is_file():
        counts = _counts(legacy.read_text(encoding="utf-8"))
        if counts:
            found.append(PlanInfo(legacy, "plan.md (older format)", "hand", "", *counts))
    return found


def _approve_marked(
    root: Path, text: str, *, name: str, source: str, drafted_by: str,
    replace: bool, clear_checkpoint: bool = False,
) -> Path:
    from whyline_relay import config, planner

    staged = config.relay_dir(root) / "approved-plan.md"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(with_marker(text, source=source, drafted_by=drafted_by), encoding="utf-8")
    try:
        return planner.approve(
            root, _settings(root), staged, drafted_by=drafted_by, replace=replace,
            clear_checkpoint=clear_checkpoint, target=plan_path(root, name),
        )
    finally:
        staged.unlink(missing_ok=True)


def configured_plan(root: Path) -> Path | None:
    try:
        return root / _settings(root).plan
    except Exception:  # unreadable config
        return None


def select_plan(root: Path, path: Path) -> None:
    from whyline_relay import setup

    setup.write_plan(root, path.relative_to(root).as_posix())


def planner_agents(root: Path) -> tuple[str, str]:
    try:
        planner_cfg = _settings(root).planner
    except Exception:
        return ("codex", "claude")
    return planner_cfg.draft, planner_cfg.review


def save_planner(root: Path, draft: str, review: str) -> None:
    from whyline_relay import setup

    setup.write_planner(root, draft, review)


def plan_questions_error():
    from whyline_relay import planner

    return planner.PlanQuestions


def answer_plan(root: Path, answers: str, *, progress) -> Draft:
    from whyline_relay import planner

    return _planner_draft(
        root, planner.answer(root, _settings(root), answers, print_fn=progress)
    )


def open_questions(text: str) -> list[str]:
    found: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lower() == "open questions"
            continue
        if inside:
            match = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)", line)
            if match:
                found.append(match.group(1))
    return found


def question_feedback(questions: Sequence[str], answers: str) -> str:
    asked = "\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1))
    return (
        f"You listed these open questions:\n{asked}\nThe human answered:\n"
        f"{answers.strip()}\nRewrite the whole plan with these decisions, and "
        "remove the answered questions from ## Open questions."
    )
```

Replace `save_pasted_plan` and `approve_plan`:

```python
def save_pasted_plan(root: Path, text: str, name: str, *, replace: bool = False) -> Path:
    problems = validate_plan(text)
    if problems:
        raise ValueError("\n".join(problems))
    return _approve_marked(
        root, text, name=name, source="paste", drafted_by="hand", replace=replace
    )


def approve_plan(root: Path, draft: Draft, name: str, *, replace: bool = False) -> Path:
    return _approve_marked(
        root,
        draft.path.read_text(encoding="utf-8"),
        name=name,
        source=_SOURCE_LABELS.get(draft.source, draft.source),
        drafted_by=draft.drafted_by,
        replace=replace,
        clear_checkpoint=draft.source == "planner",
    )
```

In `_planner_draft`, set `drafted_by=f"{cfg.draft} (reviewed by {cfg.review})"`, where `cfg = _settings(root).planner`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/console/test_relay_ops.py -q`
Expected: PASS. Other console tests that stub `save_pasted_plan` / `approve_plan` with the old signature are fixed in Tasks 13 and 14. Don't touch them here; if they fail now, note it and continue.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/whyline/console/relay_ops.py tests/console/test_relay_ops.py
git commit -m "feat: named plan files, plan list and question helpers (RPF-11)"
whyline note "Plans are plans/<slug>.plan.md with a whyline-plan v1 marker on line 1" --because "Set up must find every plan automatically, and the relay parser ignores non-task lines" --rejected "Keep one plan.md: users keep several plans" --file src/whyline/console/relay_ops.py --actor <agent> --role implementer --task RPF-11
```

### Task 12: The plan job (no widgets)

**Files:**
- Create: `src/whyline/console/plan_job.py`
- Test: `tests/console/test_plan_job.py` (create)

**Interfaces:**
- Consumes: Task 11's relay_ops functions; `relay_ops.draft_plan`, `resume_draft`, `revise_plan`, `plan_from_brainstorm`, `in_progress_error`; `adapters.run_brainstorm`.
- Produces: `PlanRequest` (frozen dataclass: `source: str` in `"draft" | "brainstorm" | "existing" | "resume"`, `name: str`, `replace: bool = False`, `description: str = ""`, `refs: tuple[str, ...] = ()`, `drafter: str = ""`, `reviewer: str = ""`, `brainstorm: dict | None = None`, `topic: str = ""`, `writer: str = ""`); `Outcome` (frozen: `kind: str` in `"draft" | "questions"`, `draft: Draft | None = None`, `questions: tuple[str, ...] = ()`, `asker: str = ""`); `run_request(root, request, progress) -> Outcome`; `run_revision(root, draft, feedback, progress) -> Outcome`; `run_answer(root, outcome, answers, progress) -> Outcome`; `summary(draft, name) -> str`; `questions_text(outcome) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/console/test_plan_job.py`:

```python
from pathlib import Path

import pytest

from whyline.console import plan_job, relay_ops


class Asked(Exception):
    def __init__(self, questions, agent):
        super().__init__("asked")
        self.questions, self.agent = questions, agent


@pytest.fixture(autouse=True)
def errors(monkeypatch):
    monkeypatch.setattr(relay_ops, "plan_questions_error", lambda: Asked)


def _draft(tmp_path, text="- [ ] T-1: build it\n  do it\n", source="planner", agent=""):
    path = tmp_path / "draft.md"
    path.write_text(text)
    return relay_ops.Draft(path=path, text=text, drafted_by="codex", source=source, agent=agent)


def test_a_draft_request_saves_the_agents_then_drafts(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda root, d, r: calls.append(("planner", d, r)))
    monkeypatch.setattr(relay_ops, "draft_plan",
                        lambda root, desc, refs, progress: calls.append(("draft", desc, refs)) or _draft(tmp_path))
    request = plan_job.PlanRequest("draft", "p", description="Build", refs=("PRD.md",),
                                   drafter="claude", reviewer="codex")
    outcome = plan_job.run_request(tmp_path, request, lambda line: None)
    assert calls == [("planner", "claude", "codex"), ("draft", "Build", ["PRD.md"])]
    assert outcome.kind == "draft"


def test_planner_questions_become_a_questions_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "save_planner", lambda *a: None)

    def ask(*a, **k):
        raise Asked(("Which broker?",), "claude")

    monkeypatch.setattr(relay_ops, "draft_plan", ask)
    outcome = plan_job.run_request(
        tmp_path, plan_job.PlanRequest("draft", "p", description="x", drafter="codex", reviewer="claude"),
        lambda line: None)
    assert outcome == plan_job.Outcome("questions", None, ("Which broker?",), "claude")


def test_open_questions_in_a_brainstorm_draft_are_questions(tmp_path, monkeypatch):
    text = "## Open questions\n1. Paper trading?\n\n- [ ] T-1: x\n"
    monkeypatch.setattr(relay_ops, "plan_from_brainstorm",
                        lambda root, topic, agent, progress: _draft(tmp_path, text, "brainstorm", "codex"))
    outcome = plan_job.run_request(
        tmp_path, plan_job.PlanRequest("existing", "p", topic="t", writer="codex"), lambda l: None)
    assert outcome.kind == "questions" and outcome.questions == ("Paper trading?",)
    assert outcome.draft is not None and outcome.asker == "codex"


def test_answers_go_to_the_planner_when_it_stopped_to_ask(tmp_path, monkeypatch):
    got = []
    monkeypatch.setattr(relay_ops, "answer_plan",
                        lambda root, answers, progress: got.append(answers) or _draft(tmp_path))
    outcome = plan_job.run_answer(
        tmp_path, plan_job.Outcome("questions", None, ("Q?",), "claude"), "1a", lambda l: None)
    assert got == ["1a"] and outcome.kind == "draft"


def test_answers_to_open_questions_revise_the_draft(tmp_path, monkeypatch):
    got = []
    draft = _draft(tmp_path, source="brainstorm", agent="codex")
    monkeypatch.setattr(relay_ops, "revise_plan",
                        lambda root, d, feedback, progress: got.append(feedback) or _draft(tmp_path))
    plan_job.run_answer(tmp_path, plan_job.Outcome("questions", draft, ("Q?",), "codex"),
                        "yes", lambda l: None)
    assert got == [relay_ops.question_feedback(("Q?",), "yes")]


def test_summary_lists_tasks_and_how_to_approve(tmp_path):
    text = "".join(f"- [ ] T-{n}: task {n}\n  do it\n" for n in range(1, 18))
    shown = plan_job.summary(_draft(tmp_path, text), "My Plan")
    assert "17 tasks" in shown and "T-15: task 15" in shown and "T-16" not in shown
    assert "and 2 more" in shown and "plans/my-plan.plan.md" in shown and '"approve"' in shown


def test_summary_of_an_unusable_draft_says_so(tmp_path):
    assert "no usable tasks" in plan_job.summary(_draft(tmp_path, "prose\n"), "p")


def test_questions_text_numbers_them():
    text = plan_job.questions_text(plan_job.Outcome("questions", None, ("A?", "B?"), "claude"))
    assert text.splitlines()[:3] == [
        "claude needs answers before the plan can continue:", "  1. A?", "  2. B?",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/console/test_plan_job.py -q`
Expected: FAIL with `ImportError: cannot import name 'plan_job'`.

- [ ] **Step 3: Implement**

Create `src/whyline/console/plan_job.py`:

```python
"""The plan job the main window runs. It turns what the Plan popup collected
(a PlanRequest) into a draft or a set of questions, and carries answers and
change requests back. No widgets here; tui.py owns presentation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whyline.console import relay_ops


@dataclass(frozen=True)
class PlanRequest:
    source: str  # "draft" | "brainstorm" | "existing" | "resume"
    name: str
    replace: bool = False
    description: str = ""
    refs: tuple[str, ...] = ()
    drafter: str = ""
    reviewer: str = ""
    brainstorm: dict | None = None  # collect_brainstorm()'s choice, for a new one
    topic: str = ""  # an existing brainstorm doc's stem
    writer: str = ""


@dataclass(frozen=True)
class Outcome:
    kind: str  # "draft" | "questions"
    draft: relay_ops.Draft | None = None
    questions: tuple[str, ...] = ()
    asker: str = ""


def _from_draft(draft: relay_ops.Draft) -> Outcome:
    asked = relay_ops.open_questions(draft.text)
    if asked:
        return Outcome("questions", draft, tuple(asked), draft.agent or draft.drafted_by)
    return Outcome("draft", draft)


def _guarded(work) -> Outcome:
    try:
        return _from_draft(work())
    except relay_ops.plan_questions_error() as asked:
        return Outcome("questions", None, tuple(asked.questions), asked.agent)


def run_request(root: Path, request: PlanRequest, progress) -> Outcome:
    if request.source == "draft":
        relay_ops.save_planner(root, request.drafter, request.reviewer)

        def draft():
            try:
                return relay_ops.draft_plan(
                    root, request.description, list(request.refs), progress=progress
                )
            except relay_ops.in_progress_error() as error:
                raise RuntimeError(
                    "A plan draft is already unfinished -- open Plan to resume or discard it."
                ) from error

        return _guarded(draft)
    if request.source == "resume":
        return _guarded(lambda: relay_ops.resume_draft(root, progress=progress))
    if request.source == "existing":
        return _guarded(lambda: relay_ops.plan_from_brainstorm(
            root, request.topic, request.writer, progress=progress
        ))
    choice = request.brainstorm

    def brainstorm_then_plan():
        from whyline.console import adapters

        result = adapters.run_brainstorm(root, progress=progress, **choice)
        if result.kind == "error":
            raise RuntimeError(result.text)
        return relay_ops.plan_from_brainstorm(
            root, choice["topic"], choice["final_agent"], progress=progress,
            timeout_minutes=choice["timeout_minutes"],
        )

    return _guarded(brainstorm_then_plan)


def run_revision(root: Path, draft: relay_ops.Draft, feedback: str, progress) -> Outcome:
    return _guarded(lambda: relay_ops.revise_plan(root, draft, feedback, progress=progress))


def run_answer(root: Path, outcome: Outcome, answers: str, progress) -> Outcome:
    if outcome.draft is None:  # the planner stopped mid-pipeline to ask
        return _guarded(lambda: relay_ops.answer_plan(root, answers, progress=progress))
    feedback = relay_ops.question_feedback(outcome.questions, answers)
    return run_revision(root, outcome.draft, feedback, progress)


def summary(draft: relay_ops.Draft, name: str) -> str:
    from whyline_relay import plan

    try:
        tasks = plan.parse(draft.text)
    except plan.PlanError as error:
        tasks, problem = [], str(error)
    else:
        problem = "" if tasks else "no tasks found"
    if problem:
        return (
            f'The draft for "{name}" has no usable tasks yet ({problem}). '
            f"It is at {draft.path}. Say what to change."
        )
    listing = "\n".join(f"  {task.text.splitlines()[0]}" for task in tasks[:15])
    more = f"\n  … and {len(tasks) - 15} more" if len(tasks) > 15 else ""
    return (
        f'Draft plan "{name}" is ready: {len(tasks)} tasks, by {draft.drafted_by}.\n'
        f"{listing}{more}\nFull draft: {draft.path}\n"
        f'Type "approve" to save it as {relay_ops.PLANS_DIR}/{relay_ops.plan_slug(name)}.plan.md, '
        "or say what to change."
    )


def questions_text(outcome: Outcome) -> str:
    lines = [f"{outcome.asker or 'The agent'} needs answers before the plan can continue:"]
    lines += [f"  {number}. {q}" for number, q in enumerate(outcome.questions, 1)]
    lines.append('Answer in the prompt below, e.g. "1a, 2: yes but only for the pilot".')
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/console/test_plan_job.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/whyline/console/plan_job.py tests/console/test_plan_job.py
git commit -m "feat: plan job model for the main window (RPF-12)"
whyline note "Plan job logic lives in plan_job.py with no widgets" --because "tui.py is already 850+ lines; the request/outcome rules are testable without Textual" --file src/whyline/console/plan_job.py --actor <agent> --role implementer --task RPF-12
```

### Task 13: Plan popup becomes a form

**Files:**
- Modify: `src/whyline/console/relay_screens.py` (`RelayPlanScreen`; new `PlanDraftScreen`)
- Test: `tests/console/test_relay_plan_screen.py`

**Interfaces:**
- Consumes: `plan_job.PlanRequest`; `relay_ops.relay_agents(root)`, `planner_agents`, `plan_path`, `save_pasted_plan(root, text, name, replace=)`.
- Produces: `RelayPlanScreen` dismisses with `None` (Cancel), a `Path` (a pasted plan saved) or a `PlanRequest`. `PlanDraftScreen(text: str)` is a read-only scrollable view with a Close button (`#pd-close`).

- [ ] **Step 1: Update and write the failing tests**

In `tests/console/test_relay_plan_screen.py`:

1. Delete these tests; their behaviour moves to the main window (Task 14): `test_draft_reviews_then_approves`, `test_an_agent_failure_returns_to_the_form_with_inputs_kept`, `test_request_changes_sends_feedback_and_shows_the_new_draft`, `test_approving_over_an_existing_plan_asks_first`, `test_an_existing_brainstorm_doc_becomes_a_plan`, `test_a_new_brainstorm_runs_then_becomes_a_plan`, `test_a_failed_brainstorm_is_shown_and_no_plan_is_made`, `test_an_unfinished_draft_can_be_resumed`. Also delete the now-unused `_draft` helper.
2. In `quiet_ops`, add:
   ```python
   monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok"])
   monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude"))
   ```
3. Change every `save_pasted_plan` stub to the signature `lambda root, text, name, replace=False: ...`. In `test_paste_saves_a_valid_plan`, expect `saved == [("- [ ] T-1: build it\n", False)]` unchanged, and `results == [tmp_path / "plans" / "plan.plan.md"]` with the stub returning that path.
4. Add:

```python
from whyline.console import plan_job


async def test_draft_dismisses_with_a_request_carrying_the_agents(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-name", tui.Input).value = "Trading v1"
        screen.query_one("#rp-description").load_text("Build the PRD")
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [plan_job.PlanRequest(
        "draft", "Trading v1", description="Build the PRD", drafter="grok", reviewer="claude",
    )]


async def test_an_empty_name_comes_from_the_description(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-description").load_text("Build the trading platform")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results[0].name == "Build the trading platform"


async def test_an_existing_plan_name_asks_before_replacing(tmp_path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "p.plan.md").write_text("x")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-name", tui.Input).value = "p"
        screen.query_one("#rp-description").load_text("x")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert results[0].replace is True


async def test_an_existing_brainstorm_becomes_a_request(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: ["topic-a"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        screen.query_one("#rp-from", tui.Select).value = "topic-a"
        await pilot.pause()
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [plan_job.PlanRequest("existing", "topic-a", topic="topic-a", writer="claude")]


async def test_resume_dismisses_with_a_resume_request(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build the PRD")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        await pilot.click("#rp-resume-draft")
        await pilot.pause()
    assert results == [plan_job.PlanRequest("resume", "Build the PRD")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/console/test_relay_plan_screen.py -q`
Expected: FAIL with `NoMatches: No nodes match '#rp-name'`.

- [ ] **Step 3: Rewrite `RelayPlanScreen`**

In `src/whyline/console/relay_screens.py`, add `from dataclasses import replace as dc_replace` and `from whyline.console.plan_job import PlanRequest`, delete `_STATE_BUTTONS`, and replace the whole `RelayPlanScreen` class with:

```python
class RelayPlanScreen(ModalScreen):
    """Collects what to plan, then dismisses with a PlanRequest; the main
    window runs it, shows progress and the draft, and asks the questions.
    Pasting is instant, so a pasted plan is still saved here."""

    DEFAULT_CSS = """
    RelayPlanScreen { align: center middle; }
    RelayPlanScreen > Vertical {
        width: 96; max-width: 100%; height: auto; max-height: 100%; padding: 0 2;
        border: thick $accent; background: $surface;
    }
    RelayPlanScreen #rp-form { height: auto; max-height: 1fr; }
    RelayPlanScreen Vertical, RelayPlanScreen Horizontal { height: auto; }
    RelayPlanScreen .field-label { width: 18; padding: 1 1 0 0; }
    RelayPlanScreen TextArea { height: 8; }
    RelayPlanScreen #rp-refs { height: 4; }
    RelayPlanScreen #rp-source, RelayPlanScreen #rp-drafter, RelayPlanScreen #rp-reviewer { width: 40; }
    RelayPlanScreen #rp-name { width: 1fr; }
    RelayPlanScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
    RelayPlanScreen Checkbox:focus { border: none; }
    RelayPlanScreen #rp-error { color: $error; height: auto; }
    RelayPlanScreen #rp-error.-empty { display: none; }
    RelayPlanScreen #rp-buttons { margin-top: 1; }
    RelayPlanScreen #rp-buttons Button { margin-right: 1; }
    """

    def __init__(self, root: Path, status: dict, active: str) -> None:
        super().__init__()
        self._root = root
        self._status = status
        self._active = active
        self._agents = relay_ops.relay_agents(root) or ["claude", "codex"]
        self._planner = relay_ops.planner_agents(root)

    def _agent_select(self, wanted: str, select_id: str) -> Select:
        value = wanted if wanted in self._agents else self._agents[0]
        return Select([(a, a) for a in self._agents], value=value, allow_blank=False, id=select_id)

    def compose(self) -> ComposeResult:
        drafter, reviewer = self._planner
        form = VerticalScroll(
            Label("Plan: make a plan the relay works through, saved under plans/."),
            Horizontal(
                Label("Plan name:", classes="field-label"),
                Input(placeholder="leave empty to name it from the description", id="rp-name"),
            ),
            Horizontal(
                Label("Source:", classes="field-label"),
                Select(_SOURCES, value="draft", allow_blank=False, id="rp-source"),
            ),
            Vertical(
                Label("Paste the plan (each task as `- [ ] ID: title`):"),
                TextArea(id="rp-paste"),
                id="rp-paste-group",
            ),
            Vertical(
                Label("What should the plan build?"),
                TextArea(id="rp-description"),
                Label("Reference documents, one path per line (e.g. PRD.md):"),
                TextArea(id="rp-refs"),
                Horizontal(Label("Drafter:", classes="field-label"),
                           self._agent_select(drafter, "rp-drafter")),
                Horizontal(Label("Reviewer:", classes="field-label"),
                           self._agent_select(reviewer, "rp-reviewer")),
                id="rp-draft-group",
            ),
            Vertical(*self._brainstorm_widgets(), id="rp-brainstorm-group"),
            id="rp-form",
        )
        yield Vertical(
            form,
            Static("", id="rp-error", classes="-empty"),
            Horizontal(
                Button("Make the plan", id="rp-go", variant="success"),
                Button("Resume draft", id="rp-resume-draft", variant="primary"),
                Button("Discard it", id="rp-discard-draft", variant="warning"),
                Button("Cancel", id="rp-cancel"),
                id="rp-buttons",
            ),
        )
```

Keep `_brainstorm_widgets` exactly as it is today. Then add the remaining methods:

```python
    def on_mount(self) -> None:
        self._show_source("draft")
        self.query_one("#rp-writer-row").display = False
        pending = relay_ops.pending_draft(self._root)
        self.query_one("#rp-resume-draft").display = bool(pending)
        self.query_one("#rp-discard-draft").display = bool(pending)
        if pending:
            self._error(f'A plan draft for "{pending}" was left unfinished.')

    def _source(self) -> str:
        return self.query_one("#rp-source", Select).value

    def _show_source(self, source: str) -> None:
        for name in ("paste", "draft", "brainstorm"):
            self.query_one(f"#rp-{name}-group").display = name == source
        self.query_one("#rp-go", Button).label = "Save" if source == "paste" else "Make the plan"

    def on_select_changed(self, event: "Select.Changed") -> None:
        if event.select.id == "rp-source":
            self._show_source(event.value)
        elif event.select.id == "rp-from":
            new = event.value == "new"
            self.query_one("#rp-new-group").display = new
            self.query_one("#rp-writer-row").display = not new

    def _error(self, text: str) -> None:
        error = self.query_one("#rp-error", Static)
        error.update(text)
        error.set_class(not text, "-empty")

    def _name(self, fallback: str) -> str:
        return self.query_one("#rp-name", Input).value.strip() or fallback.strip() or "plan"

    def _confirm_replace(self, path: Path, retry) -> None:
        from whyline.console.tui import ConfirmScreen

        shown = path.relative_to(self._root) if path.is_relative_to(self._root) else path
        self.app.push_screen(
            ConfirmScreen(f"{shown} already exists. Replace it?", "Replace"),
            lambda confirmed: confirmed and retry(),
        )

    def _submit(self, request: PlanRequest) -> None:
        path = relay_ops.plan_path(self._root, request.name)
        if path.exists() and not request.replace:
            self._confirm_replace(path, lambda: self.dismiss(dc_replace(request, replace=True)))
            return
        self.dismiss(request)

    def _save_paste(self, replace: bool = False) -> None:
        text = self.query_one("#rp-paste", TextArea).text
        heading = next(
            (line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")), ""
        )
        name = self._name(heading)
        try:
            path = relay_ops.save_pasted_plan(self._root, text, name, replace=replace)
        except relay_ops.plan_exists_error():
            self._confirm_replace(relay_ops.plan_path(self._root, name),
                                  lambda: self._save_paste(replace=True))
            return
        except ValueError as error:
            self._error(str(error))
            return
        self.dismiss(path)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        handler = getattr(self, f"_on_{event.button.id.replace('-', '_')}", None)
        if handler is not None:
            handler()

    def _on_rp_cancel(self) -> None:
        self.dismiss(None)

    def _on_rp_go(self) -> None:
        source = self._source()
        if source == "paste":
            self._save_paste()
            return
        request = self._draft_request() if source == "draft" else self._brainstorm_request()
        if request is not None:
            self._submit(request)

    def _draft_request(self) -> PlanRequest | None:
        description = self.query_one("#rp-description", TextArea).text.strip()
        if not description:
            self._error("Describe what the plan should build.")
            return None
        refs = [
            line.strip()
            for line in self.query_one("#rp-refs", TextArea).text.splitlines()
            if line.strip()
        ]
        missing = relay_ops.missing_references(self._root, refs)
        if missing:
            self._error("Can't find: " + ", ".join(missing))
            return None
        return PlanRequest(
            "draft", self._name(description), description=description, refs=tuple(refs),
            drafter=self.query_one("#rp-drafter", Select).value,
            reviewer=self.query_one("#rp-reviewer", Select).value,
        )

    def _brainstorm_request(self) -> PlanRequest | None:
        from whyline.console.tui import collect_brainstorm

        chosen = self.query_one("#rp-from", Select).value
        if chosen != "new":
            return PlanRequest("existing", self._name(chosen), topic=chosen,
                               writer=self.query_one("#rp-writer", Select).value)
        choice = collect_brainstorm(self.query_one)
        if isinstance(choice, str):
            self._error(choice)
            return None
        return PlanRequest("brainstorm", self._name(choice["topic"]), brainstorm=choice)

    def _on_rp_resume_draft(self) -> None:
        pending = relay_ops.pending_draft(self._root) or "plan"
        self._submit(PlanRequest("resume", self._name(pending)))

    def _on_rp_discard_draft(self) -> None:
        relay_ops.discard_draft(self._root, None)
        self._error("")
        self.query_one("#rp-resume-draft").display = False
        self.query_one("#rp-discard-draft").display = False


class PlanDraftScreen(ModalScreen):
    """The full draft, read-only."""

    DEFAULT_CSS = """
    PlanDraftScreen { align: center middle; }
    PlanDraftScreen > Vertical {
        width: 110; max-width: 100%; height: 90%; padding: 0 2;
        border: thick $accent; background: $surface;
    }
    PlanDraftScreen VerticalScroll { height: 1fr; }
    PlanDraftScreen Horizontal { height: auto; margin-top: 1; }
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        yield Vertical(
            VerticalScroll(Static(self._text, markup=False)),
            Horizontal(Button("Close", id="pd-close", variant="primary")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss(None)
```

If Textual 0.89.1's `Path.is_relative_to` usage looks odd to a reviewer: it is the standard-library `pathlib` method (Python 3.9+), not Textual.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/console/test_relay_plan_screen.py -q`
Expected: PASS. `test_plan_button_opens_the_popup_and_reports_the_saved_plan` passes once Task 14 updates `_plan_saved`'s wording. If it fails only on the message text, change its assertion to `any("Saved plans/" in line and "Set up" in line ...)` and its stub to return `root / "plans" / "plan.plan.md"`.

- [ ] **Step 5: Commit**

```bash
git add src/whyline/console/relay_screens.py tests/console/test_relay_plan_screen.py
git commit -m "feat: Plan popup collects a request and closes (RPF-13)"
whyline note "Plan popup only collects a PlanRequest; drafting, review and questions move to the main window" --because "a minutes-long modal blocked the console and hid progress and questions" --file src/whyline/console/relay_screens.py --actor <agent> --role implementer --task RPF-13
```

### Task 14: The plan job in the main window

**Files:**
- Modify: `src/whyline/console/tui.py`
- Test: `tests/console/test_plan_in_main_window.py` (create)

**Interfaces:**
- Consumes: `plan_job.*` (Task 12); `RelayPlanScreen`, `PlanDraftScreen` (Task 13); `relay_ops.approve_plan(root, draft, name, replace=)`, `discard_draft`, `plan_path`, `plan_exists_error`, `list_plans`.
- Produces: `WhylineConsoleApp._plan_state: str` (`""`, `"working"`, `"review"` or `"answering"`); `_start_plan_job(request)`; buttons `#plan-approve`, `#plan-view`, `#plan-discard` in a `#plan-actions` row; the Escape key leaves review/answering.

- [ ] **Step 1: Write the failing tests**

Create `tests/console/test_plan_in_main_window.py`:

```python
import pytest

from whyline.console import plan_job, relay_ops, tui

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

REQUEST = plan_job.PlanRequest("draft", "My Plan", description="x", drafter="codex", reviewer="claude")


def _lines(app):
    return [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]


async def _wait_for(pilot, condition, what):
    for _ in range(100):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


def _draft(tmp_path, text="- [ ] T-1: build it\n  do it\n"):
    path = tmp_path / "draft.md"
    path.write_text(text)
    return relay_ops.Draft(path=path, text=text, drafted_by="codex", source="planner")


@pytest.fixture(autouse=True)
def no_trust_question(monkeypatch):
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted")


async def _type(app, pilot, text):
    app.query_one("#prompt", tui.Input).value = text
    await pilot.press("enter")
    await pilot.pause()


async def test_progress_streams_then_review_then_approve(tmp_path, monkeypatch):
    def run(root, request, progress):
        progress("codex is drafting the plan")
        return plan_job.Outcome("draft", _draft(tmp_path))

    monkeypatch.setattr(plan_job, "run_request", run)
    approved = []
    monkeypatch.setattr(relay_ops, "approve_plan",
                        lambda root, d, name, replace=False: approved.append(name)
                        or root / "plans" / "my-plan.plan.md")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        assert any("plan · codex is drafting the plan" in l for l in _lines(app))
        assert any("1 tasks" in l or "T-1: build it" in l for l in _lines(app))
        assert app.query_one("#plan-actions").display
        await _type(app, pilot, "approve")
        assert approved == ["My Plan"] and app._plan_state == ""
        assert any("Saved plans/my-plan.plan.md" in l for l in _lines(app))


async def test_other_text_in_review_requests_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    revised = []
    monkeypatch.setattr(plan_job, "run_revision",
                        lambda root, d, feedback, progress: revised.append(feedback)
                        or plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await _type(app, pilot, "split T-1 into two tasks")
        await _wait_for(pilot, lambda: revised, "revision")
    assert revised == ["split T-1 into two tasks"]


async def test_questions_are_numbered_and_answers_reach_the_job(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, progress: plan_job.Outcome(
        "questions", None, ("Which broker? (a) Kite (b) Upstox", "Paper trading?"), "claude"))
    answered = []
    monkeypatch.setattr(plan_job, "run_answer",
                        lambda root, outcome, answers, progress: answered.append(answers)
                        or plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "answering", "answering state")
        assert any("1. Which broker? (a) Kite (b) Upstox" in l for l in _lines(app))
        assert "answering" in app.sub_title
        await _type(app, pilot, "1a, 2: yes but only for the pilot")
        await _wait_for(pilot, lambda: app._plan_state == "review", "review after answers")
    assert answered == ["1a, 2: yes but only for the pilot"]


async def test_slash_commands_still_work_while_reviewing(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    revised = []
    monkeypatch.setattr(plan_job, "run_revision", lambda *a: revised.append(a))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await _type(app, pilot, "/help")
        assert revised == [] and app._plan_state == "review"


async def test_a_failure_is_reported_and_leaves_the_state(tmp_path, monkeypatch):
    def fail(root, req, progress):
        raise RuntimeError("codex timed out")

    monkeypatch.setattr(plan_job, "run_request", fail)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: any("codex timed out" in l for l in _lines(app)), "error")
        assert app._plan_state == ""


async def test_discard_drops_the_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    dropped = []
    monkeypatch.setattr(relay_ops, "discard_draft", lambda root, d: dropped.append(d))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await pilot.click("#plan-discard")
        await pilot.pause()
        assert app._plan_state == "" and len(dropped) == 1


async def test_approving_over_an_existing_plan_asks_first(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    calls = []

    class Exists(RuntimeError):
        pass

    def approve(root, d, name, replace=False):
        calls.append(replace)
        if not replace:
            raise Exists()
        return root / "plans" / "my-plan.plan.md"

    monkeypatch.setattr(relay_ops, "plan_exists_error", lambda: Exists)
    monkeypatch.setattr(relay_ops, "approve_plan", approve)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await pilot.click("#plan-approve")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert calls == [False, True]


async def test_view_draft_opens_the_full_text(tmp_path, monkeypatch):
    from whyline.console.relay_screens import PlanDraftScreen

    monkeypatch.setattr(plan_job, "run_request",
                        lambda root, req, progress: plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "review state")
        await pilot.click("#plan-view")
        await pilot.pause()
        assert isinstance(app.screen, PlanDraftScreen)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/console/test_plan_in_main_window.py -q`
Expected: FAIL with `AttributeError: 'WhylineConsoleApp' object has no attribute '_start_plan_job'`.

- [ ] **Step 3: Add the state, the row and the bindings**

In `src/whyline/console/tui.py`:

1. Add `from whyline.console import plan_job` next to the other `whyline.console` imports.
2. Add to `WhylineConsoleApp`: `BINDINGS = [("escape", "leave_plan", "Leave plan")]`. If the class already defines `BINDINGS`, append this tuple to it instead.
3. Add to `DEFAULT_CSS`: `#plan-actions { height: auto; display: none; }`.
4. In `__init__`, add:
   ```python
           self._plan_state = ""  # "", "working", "review", "answering"
           self._plan_request: plan_job.PlanRequest | None = None
           self._plan_outcome: plan_job.Outcome | None = None
   ```
5. In `compose`, between `yield Static("", id="thinking")` and the `#input-row` Horizontal, add:
   ```python
           yield Horizontal(
               Button("Approve", id="plan-approve", variant="success"),
               Button("View draft", id="plan-view"),
               Button("Discard", id="plan-discard", variant="warning"),
               id="plan-actions",
           )
   ```
6. In `_sync_mode_indicator`, replace `self.sub_title = f"mode: {mode}"` with:
   ```python
           suffix = {"review": " · plan review", "answering": " · answering"}.get(self._plan_state, "")
           self.sub_title = f"mode: {mode}{suffix}"
   ```
   and replace the placeholder line with:
   ```python
           self._main("#prompt", Input).placeholder = {
               "review": 'Type "approve", or say what to change (Enter to send)',
               "answering": "Type your answers (Enter to send)",
           }.get(self._plan_state, self._placeholder(mode))
   ```

- [ ] **Step 4: Add the plan job methods**

Add to `WhylineConsoleApp`:

```python
    # -- the plan job (spec section 4) ------------------------------------
    def _set_plan_state(self, state: str) -> None:
        self._plan_state = state
        self._main("#plan-actions").display = state == "review"
        self._sync_mode_indicator()

    def _start_plan_job(self, request: plan_job.PlanRequest) -> None:
        def proceed(allowed: bool) -> None:
            if not allowed:
                self.render_event(SessionEvent(
                    kind="error",
                    text="This plan needs Antigravity, which isn't trusted here. "
                         "Pick other agents in Plan."))
                return
            self._plan_request = request
            self._plan_outcome = None
            self.render_event(SessionEvent(
                kind="output", text=f'Planning "{request.name}". Progress follows.'))
            root = self.session.root
            self._run_plan(lambda progress: plan_job.run_request(root, request, progress))

        agents = {request.drafter, request.reviewer, request.writer}
        if request.brainstorm:
            agents |= set(request.brainstorm["agents"])
        self._with_antigravity("antigravity" in agents, proceed)

    def _run_plan(self, work) -> None:
        token = object()
        self._dispatch_token = token
        self._set_plan_state("working")
        self._set_busy(True, "planning")

        def in_thread() -> None:
            def progress(line: str) -> None:
                self.call_from_thread(self._plan_progress, line, token)

            try:
                outcome = work(progress)
            except Exception as error:  # agent missing, timeout, relay pause...
                self.call_from_thread(self._plan_failed, error, token)
                return
            self.call_from_thread(self._plan_done, outcome, token)

        self.run_worker(in_thread, thread=True)

    def _plan_progress(self, line: str, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self.render_event(SessionEvent(kind="output", text=f"plan · {line}"))
        self._busy_text = f"planning: {line}"

    def _plan_failed(self, error: Exception, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self._set_plan_state("")
        self.render_event(SessionEvent(
            kind="error",
            text=f"Planning stopped: {error or error.__class__.__name__}. Anything drafted "
                 "so far is kept -- open Plan and choose Resume draft to try again.",
        ))

    def _plan_done(self, outcome: plan_job.Outcome, token: object) -> None:
        if token is not self._dispatch_token:
            return
        self._set_busy(False)
        self._plan_outcome = outcome
        if outcome.kind == "questions":
            self.render_event(SessionEvent(kind="output", text=plan_job.questions_text(outcome)))
            self._set_plan_state("answering")
        else:
            self.render_event(SessionEvent(
                kind="output", text=plan_job.summary(outcome.draft, self._plan_request.name)))
            self._set_plan_state("review")
        self._main("#prompt", Input).focus()

    def _plan_reply(self, text: str) -> None:
        root, outcome = self.session.root, self._plan_outcome
        if self._plan_state == "review":
            if text.strip().lower() == "approve":
                self._approve_plan()
                return
            self._run_plan(lambda progress: plan_job.run_revision(root, outcome.draft, text, progress))
            return
        self._run_plan(lambda progress: plan_job.run_answer(root, outcome, text, progress))

    def _approve_plan(self, replace: bool = False) -> None:
        root, request = self.session.root, self._plan_request
        draft = self._plan_outcome.draft
        try:
            path = relay_ops.approve_plan(root, draft, request.name,
                                          replace=replace or request.replace)
        except relay_ops.plan_exists_error():
            shown = relay_ops.plan_path(root, request.name).relative_to(root)
            self.push_screen(
                ConfirmScreen(f"{shown} already exists. Replace it?", "Replace"),
                lambda confirmed: confirmed and self._approve_plan(replace=True),
            )
            return
        except ValueError as error:  # plan.PlanError: the draft isn't usable yet
            self.render_event(SessionEvent(
                kind="error", text=f"{error}. The draft is still at {draft.path}."))
            return
        self._leave_plan()
        self._plan_saved(path)

    def _discard_plan(self) -> None:
        if self._plan_outcome is not None:
            relay_ops.discard_draft(self.session.root, self._plan_outcome.draft)
        self._leave_plan()
        self.render_event(SessionEvent(kind="output", text="Draft discarded."))

    def _leave_plan(self) -> None:
        self._plan_request = None
        self._plan_outcome = None
        self._set_plan_state("")

    def action_leave_plan(self) -> None:
        if self._plan_state not in ("review", "answering"):
            return
        draft = self._plan_outcome.draft if self._plan_outcome else None
        self._leave_plan()
        where = f"It is still at {draft.path}." if draft else "Open Plan and choose Resume draft to come back."
        self.render_event(SessionEvent(kind="output", text=f"Left the plan. {where}"))
```

- [ ] **Step 5: Route typed text, buttons and the popup result**

1. In `_send`, directly after `self.render_event(SessionEvent(kind="input", text=text))`, add:
   ```python
           if self._plan_state in ("review", "answering") and not text.startswith("/"):
               self._plan_reply(text)
               return
   ```
2. In `on_button_pressed`, add before the final `elif button_id in (...)` branch:
   ```python
           elif button_id == "plan-approve":
               self._approve_plan()
           elif button_id == "plan-view":
               from whyline.console.relay_screens import PlanDraftScreen

               if self._plan_outcome and self._plan_outcome.draft:
                   self.push_screen(PlanDraftScreen(self._plan_outcome.draft.text))
           elif button_id == "plan-discard":
               self._discard_plan()
   ```
3. In `_stop`, after `self._dispatch_token = object()`, add `if self._plan_state == "working": self._set_plan_state("")`.
4. In `_open_relay_plan`, after the home check, refuse while a plan is active:
   ```python
           if self._plan_state:
               self.render_event(SessionEvent(
                   kind="error",
                   text="A plan is already in progress: approve it, Discard it, or press Esc."))
               return
   ```
   and change the callback from `self._plan_saved` to `self._plan_chosen`, defined as:
   ```python
       def _plan_chosen(self, result) -> None:
           if result is None:
               return
           if isinstance(result, plan_job.PlanRequest):
               self._start_plan_job(result)
           else:
               self._plan_saved(result)
   ```
5. Change `_plan_saved`'s message to show the repository-relative path:
   ```python
           shown = path.relative_to(self.session.root) if path.is_relative_to(self.session.root) else path
           self.render_event(SessionEvent(
               kind="output",
               text=f"Saved {shown} and committed it. Next: Set up, to pick the plan and who "
                    "implements, tests and reviews."))
   ```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/console -q`
Expected: PASS.

- [ ] **Step 7: Check it by hand**

Run `whyline` in a scratch git repository, switch to Relay, open Plan, choose "Draft from a description" with a one-line description, and press Make the plan. Expected: the popup closes, `plan ·` lines appear, the draft summary ends with the "approve" hint, and the Approve/View draft/Discard row is visible. Typing `approve` creates `plans/<name>.plan.md` with the marker on line 1.

- [ ] **Step 8: Commit**

```bash
git add src/whyline/console/tui.py tests/console/test_plan_in_main_window.py
git commit -m "feat: run planning in the main window with review and questions (RPF-14)"
whyline note "While a draft or questions are open, typed text goes to the plan job; slash commands still run" --because "the user answers in the normal prompt (option A) and must still reach Help, Copy and Stop" --file src/whyline/console/tui.py --actor <agent> --role implementer --task RPF-14
```

### Task 15: Set up chooses the plan

**Files:**
- Modify: `src/whyline/console/relay_screens.py` (`RelaySetupScreen`)
- Modify: `src/whyline/console/tui.py` (`_setup_done`, `_launch_relay`)
- Test: `tests/console/test_relay_setup_screen.py`, `tests/console/test_tui_relay_run.py`

**Interfaces:**
- Consumes: `relay_ops.list_plans`, `configured_plan`, `select_plan`, `PlanInfo`.
- Produces: `RelaySetupScreen` dismisses with `"start"`, `"plan"` (open Plan) or `None`.

- [ ] **Step 1: Write the failing tests**

In `tests/console/test_relay_setup_screen.py`, extend the `ops` fixture (before `return saved`):

```python
    plans = [
        relay_ops.PlanInfo(Path("/r/plans/new.plan.md"), "new", "draft", "2026-10-04T10:00:00+05:30", 0, 3),
        relay_ops.PlanInfo(Path("/r/plans/old.plan.md"), "old", "paste", "2026-10-01T10:00:00+05:30", 2, 2),
    ]
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: plans)
    monkeypatch.setattr(relay_ops, "configured_plan", lambda root: None)
    monkeypatch.setattr(relay_ops, "select_plan", lambda root, path: saved.append(("plan", path)))
```

Add `from pathlib import Path` at the top. In `test_a_clean_check_saves_roles_and_enables_start`, the expected `saved` list gains a second entry, `("plan", Path("/r/plans/new.plan.md"))`. Then add:

```python
async def test_the_plan_dropdown_lists_plans_newest_first(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        select = screen.query_one("#rs-plan", tui.Select)
        assert select.value == "/r/plans/new.plan.md"
        labels = [str(prompt) for prompt, _ in select._options if _ is not tui.Select.BLANK]
        assert labels[0].startswith("new · 0/3 done · draft · 2026-10-04")


async def test_with_no_plan_setup_offers_to_make_one(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        assert screen.query_one("#rs-check", tui.Button).disabled
        assert "No plan yet" in str(screen.query_one("#rs-no-plan", tui.Static).renderable)
        await pilot.click("#rs-make-plan")
        await pilot.pause()
    assert results == ["plan"]


async def test_changing_the_plan_after_a_check_disables_start(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rs-check")
        await _wait_for(pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start")
        screen.query_one("#rs-plan", tui.Select).value = "/r/plans/old.plan.md"
        await pilot.pause()
        assert screen.query_one("#rs-start", tui.Button).disabled
```

If `Select._options` is not available in Textual 0.89.1, read the labels from the rendered dropdown instead: open it with `await pilot.click("#rs-plan")` and collect the `SelectOverlay` option prompts.

In `tests/console/test_tui_relay_run.py`, add `monkeypatch.setattr(relay_ops, "list_plans", lambda root: ["x"])` to the `fake_relay` fixture, and add:

```python
async def test_typed_start_without_any_plan_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        app.query_one("#prompt", tui.Input).value = "start"
        await pilot.press("enter")
        await pilot.pause()
        assert FakeProcess.instances == []
        assert any("No plan yet. Use Plan first." in line for line in _lines(app))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/console/test_relay_setup_screen.py tests/console/test_tui_relay_run.py -q`
Expected: FAIL with `NoMatches: No nodes match '#rs-plan'`.

- [ ] **Step 3: Implement the Set up changes**

In `RelaySetupScreen`:

1. CSS: add `RelaySetupScreen #rs-plan { width: 70; }` and `RelaySetupScreen #rs-no-plan { color: $warning; padding: 1 0 0 0; }`.
2. `__init__`: add
   ```python
           self._plans = relay_ops.list_plans(root)
           current = relay_ops.configured_plan(root)
           listed = [str(info.path) for info in self._plans]
           self._plan_default = str(current) if current and str(current) in listed else (
               listed[0] if listed else None)
   ```
3. Add a label helper:
   ```python
       @staticmethod
       def _plan_label(info: "relay_ops.PlanInfo") -> str:
           parts = [info.name, f"{info.done}/{info.total} done", info.source, info.created[:10]]
           return " · ".join(part for part in parts if part)
   ```
4. In `compose`, before `*rows`, insert:
   ```python
               (
                   Horizontal(
                       Label("Plan:", classes="field-label"),
                       Select([(self._plan_label(p), str(p.path)) for p in self._plans],
                              value=self._plan_default, allow_blank=False, id="rs-plan"),
                   )
                   if self._plans
                   else Static("No plan yet. Make one first.", id="rs-no-plan")
               ),
   ```
   Change the buttons row to:
   ```python
               Horizontal(
                   Button("Make a plan", id="rs-make-plan", variant="primary"),
                   Button("Check", id="rs-check", variant="primary", disabled=not self._plans),
                   Button("Start", id="rs-start", variant="success", disabled=True),
                   Button("Cancel", id="rs-cancel"),
                   id="rs-buttons",
               ),
   ```
5. In `on_mount`, add `self.query_one("#rs-make-plan").display = not self._plans`.
6. In `on_button_pressed`, add `elif event.button.id == "rs-make-plan": self.dismiss("plan")`.
7. In `_check`, read the plan before starting the thread:
   ```python
           plan = Path(self.query_one("#rs-plan", Select).value)
   ```
   and inside `in_thread`, after `relay_ops.save_roles(root, *chosen)`, call `relay_ops.select_plan(root, plan)`.

`on_select_changed` already calls `_invalidate()` for every Select, so changing the plan clears the check.

- [ ] **Step 4: Implement the app changes**

In `tui.py`:

1. `_setup_done`:
   ```python
       def _setup_done(self, choice: str | None) -> None:
           if choice == "start":
               self._launch_relay(["start"])
           elif choice == "plan":
               self._open_relay_plan()
   ```
2. `_launch_relay`, right after the `_refuse_in_home` check:
   ```python
           if args and args[0] == "start" and "--plan" not in args:
               try:
                   has_plan = bool(relay_ops.list_plans(self.session.root))
               except Exception:
                   has_plan = True  # let the relay itself report the problem
               if not has_plan:
                   self.render_event(SessionEvent(kind="error", text="No plan yet. Use Plan first."))
                   return
   ```

- [ ] **Step 4b: Check the chosen plan, and clear a finished paused run (spec 6b)**

Tests first. In `tests/console/test_relay_setup_screen.py`, change the `_checks` helper to accept the plan (`return lambda root, plan=None: [...]`), and add:

```python
async def test_check_runs_against_the_chosen_plan(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(relay_ops, "run_checks",
                        lambda root, plan=None: seen.append(plan) or [relay_ops.CheckLine("ok", "fine")])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rs-plan", tui.Select).value = "/r/plans/old.plan.md"
        await pilot.pause()
        await pilot.click("#rs-check")
        await _wait_for(pilot, lambda: seen, "check")
    assert seen == [Path("/r/plans/old.plan.md")]
```

In `tests/console/test_relay_ops.py`, add:

```python
def test_a_paused_run_whose_task_is_ticked_is_stale(repo):
    from whyline_relay import state

    plan_file = repo / "p.md"
    plan_file.write_text("- [x] CRS-4: release\n")
    state.save(repo, state.RelayState(
        plan=str(plan_file), branch="b", task_id="CRS-4", round=1,
        base_commit="", paused_reason="blocked", log_path="",
    ))
    assert relay_ops.stale_pause(repo) == "CRS-4"
    relay_ops.clear_pause(repo)
    assert state.load(repo) is None


def test_a_paused_run_with_work_left_is_not_stale(repo):
    from whyline_relay import state

    plan_file = repo / "p.md"
    plan_file.write_text("- [ ] CRS-4: release\n")
    state.save(repo, state.RelayState(
        plan=str(plan_file), branch="b", task_id="CRS-4", round=1,
        base_commit="", paused_reason="blocked", log_path="",
    ))
    assert relay_ops.stale_pause(repo) is None
```

If `state.RelayState` needs more fields than shown, copy the field list from `whyline_relay/state.py` and pass empty values for the rest.

In `tests/console/test_tui_relay_run.py`, add:

```python
async def test_a_stale_paused_run_offers_clear_instead_of_resume(tmp_path, monkeypatch):
    cleared = []
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
    monkeypatch.setattr(relay_ops, "stale_pause", lambda root: "CRS-4")
    monkeypatch.setattr(relay_ops, "clear_pause", lambda root: cleared.append(root))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await _relay_mode(app, pilot)
        button = app.query_one("#relay-resume", tui.Button)
        assert str(button.label) == "Clear old run" and not button.disabled
        await pilot.click("#relay-resume")
        await pilot.pause()
        assert cleared == [tmp_path] and FakeProcess.instances == []
        assert any("Cleared the finished run CRS-4." in line for line in _lines(app))
```

Then implement. In `relay_ops.py`:

```python
def run_checks(root: Path, plan: Path | None = None) -> list[CheckLine]:
    from whyline_relay import preflight

    return [CheckLine(c.status, c.message, c.hint) for c in preflight.run(root, plan)]


def stale_pause(root: Path) -> str | None:
    """The task id of a paused run that has nothing left to resume: its task
    is already ticked, or its plan file is gone. None otherwise."""
    from whyline_relay import plan as relay_plan, state

    saved = state.load(root)
    if saved is None:
        return None
    path = Path(saved.plan)
    if not path.is_file():
        return saved.task_id or "an old run"
    try:
        tasks = relay_plan.parse(path.read_text(encoding="utf-8"))
    except relay_plan.PlanError:
        return None
    done = {task.task_id for task in tasks if task.checked}
    return saved.task_id if saved.task_id in done else None


def clear_pause(root: Path) -> None:
    from whyline_relay import state

    state.clear(root)
```

In `RelaySetupScreen._check`, call `relay_ops.run_checks(root, plan)` instead of `relay_ops.run_checks(root)`.

In `tui.py`:

1. `_sync_relay_buttons`: after computing `paused`, compute
   ```python
           try:
               stale = relay_ops.stale_pause(self.session.root) if paused else None
           except Exception:
               stale = None
           resume = self._main("#relay-resume", Button)
           resume.label = "Clear old run" if stale else "Resume"
           self._stale_pause = stale
   ```
   Keep the existing `disabled` rule. A stale run counts as paused, so the button is enabled.
2. `on_button_pressed`, `relay-resume` branch:
   ```python
           elif button_id == "relay-resume":
               if getattr(self, "_stale_pause", None):
                   task = self._stale_pause
                   relay_ops.clear_pause(self.session.root)
                   self.render_event(SessionEvent(
                       kind="output", text=f"Cleared the finished run {task}."))
                   self._sync_relay_buttons()
               else:
                   self._launch_relay(["resume"])
   ```
3. Initialise `self._stale_pause = None` in `__init__`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/console -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline/console/relay_screens.py src/whyline/console/tui.py tests/console
git commit -m "feat: Set up picks the plan; no plan, no start (RPF-15)"
whyline note "Set up writes the chosen plan into config.toml rather than passing --plan" --because "a terminal 'whyline relay start' should run the same plan the console chose" --rejected "Pass --plan on Start only: the CLI and the console would disagree" --file src/whyline/console/relay_screens.py --actor <agent> --role implementer --task RPF-15
```

### Task 16: Run, one guided path

**Files:**
- Modify: `src/whyline/console/relay_ops.py` (new `roles_configured`)
- Modify: `src/whyline/console/relay_screens.py` (new `RunChoiceScreen`; `RelaySetupScreen(root, *, guided=False, plan=None)`)
- Modify: `src/whyline/console/tui.py` (Run button, typed `run`, `_run_flow` state)
- Test: `tests/console/test_run_flow.py` (create)

**Interfaces:**
- Consumes: Task 14's `_plan_chosen`, `_plan_saved`, `_plan_failed`, `_discard_plan`, `action_leave_plan`; Task 15's plan dropdown, `#rs-make-plan` and `_setup_done`.
- Produces: `relay_ops.roles_configured(root) -> bool`; `RunChoiceScreen` (dismisses with `"new"`, `"existing"` or `None`); `RelaySetupScreen(root, *, guided: bool = False, plan: Path | None = None)` with `#rs-summary`, `#rs-looks-good`, `#rs-change` and a `#rs-roles` container in guided mode; `WhylineConsoleApp._run_flow_start()`; the `#relay-run` button.

- [ ] **Step 1: Write the failing tests**

Create `tests/console/test_run_flow.py`:

```python
from pathlib import Path

import pytest

from whyline.console import relay_ops, tui
from whyline.console.relay_screens import RelayPlanScreen, RelaySetupScreen, RunChoiceScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "antigravity", "grok")}
PLAN = relay_ops.PlanInfo(Path("/r/plans/a.plan.md"), "a", "draft", "2026-10-04T10:00:00+05:30", 0, 3)


@pytest.fixture(autouse=True)
def ops(monkeypatch):
    from whyline import account

    calls = {"checks": 0}
    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [PLAN])
    monkeypatch.setattr(relay_ops, "configured_plan", lambda root: None)
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["antigravity", "claude", "codex"])
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude"))
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    monkeypatch.setattr(relay_ops, "current_roles", lambda root: {
        "implementer": "antigravity", "tester": "claude", "reviewer": "codex",
        "backup": ["claude", "codex"],
    })
    monkeypatch.setattr(relay_ops, "live_run", lambda root: None)
    monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
    monkeypatch.setattr(relay_ops, "save_roles", lambda *a: None)
    monkeypatch.setattr(relay_ops, "select_plan", lambda *a: None)
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted")

    def checks(root):
        calls["checks"] += 1
        return [relay_ops.CheckLine("ok", "fine")]

    monkeypatch.setattr(relay_ops, "run_checks", checks)
    return calls


def _lines(app):
    return [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]


async def _relay(app, pilot):
    app.session.mode = "relay"
    app._sync_mode_indicator()
    await pilot.pause()


async def test_run_with_no_plan_opens_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        await pilot.click("#relay-run")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        assert any("No plan yet -- let's make one." in l for l in _lines(app))


async def test_typed_run_offers_new_or_existing_and_existing_opens_guided_setup(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        app.query_one("#prompt", tui.Input).value = "run"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RunChoiceScreen)
        await pilot.click("#run-existing")
        await pilot.pause()
        assert isinstance(app.screen, RelaySetupScreen) and app.screen._guided


async def test_a_saved_plan_continues_to_guided_setup_with_it_selected(tmp_path, monkeypatch):
    saved = relay_ops.PlanInfo(tmp_path / "plans" / "new.plan.md", "new", "paste", "2026-10-05T00:00:00+05:30", 0, 1)
    monkeypatch.setattr(relay_ops, "list_plans", lambda root: [saved, PLAN])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        await pilot.click("#relay-run")
        await pilot.pause()
        await pilot.click("#run-new")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        app.screen.dismiss(saved.path)  # what a pasted plan does
        await pilot.pause()
        assert isinstance(app.screen, RelaySetupScreen)
        assert app.screen.query_one("#rs-plan", tui.Select).value == str(saved.path)


async def test_cancelling_the_plan_form_ends_the_run(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        await _relay(app, pilot)
        await pilot.click("#relay-run")
        await pilot.pause()
        await pilot.click("#run-new")
        await pilot.pause()
        await pilot.click("#rp-cancel")
        await pilot.pause()
        assert app._run_flow is False
        assert any("Run cancelled" in l for l in _lines(app))


async def test_guided_setup_summarises_roles_and_looks_good_runs_the_check(tmp_path, ops):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        screen = app.screen
        summary = str(screen.query_one("#rs-summary", tui.Static).renderable)
        assert summary == (
            "Implementer: antigravity · Tester: claude · Reviewer: codex · Backup: claude → codex"
        )
        assert not screen.query_one("#rs-roles").display
        await pilot.click("#rs-looks-good")
        for _ in range(100):
            if not screen.query_one("#rs-start", tui.Button).disabled:
                break
            await pilot.pause(0.05)
        assert ops["checks"] == 1
        assert not screen.query_one("#rs-start", tui.Button).disabled


async def test_change_reveals_the_role_pickers(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        await pilot.click("#rs-change")
        await pilot.pause()
        assert app.screen.query_one("#rs-roles").display
        assert not app.screen.query_one("#rs-summary-row").display


async def test_with_no_roles_yet_guided_setup_shows_the_pickers(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        assert app.screen.query_one("#rs-roles").display
        assert not app.screen.query("#rs-summary-row")


async def test_the_run_button_fits_an_80_column_terminal(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.query_one("#relay-run", tui.Button).region.right <= 80
```

Add `roles_configured` tests to `tests/console/test_relay_ops.py`:

```python
def test_roles_configured(repo):
    assert relay_ops.roles_configured(repo) is False
    relay_ops.save_roles(repo, "codex", "claude", "claude", [])
    assert relay_ops.roles_configured(repo) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/console/test_run_flow.py tests/console/test_relay_ops.py -q`
Expected: FAIL with `ImportError: cannot import name 'RunChoiceScreen'`.

- [ ] **Step 3: `roles_configured`**

Append to `src/whyline/console/relay_ops.py`:

```python
def roles_configured(root: Path) -> bool:
    """Whether this repository's relay config already assigns roles."""
    from whyline_relay import config

    path = config.config_path(root)
    if not path.exists():
        return False
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return False
    return bool(raw.get("roles"))
```

- [ ] **Step 4: `RunChoiceScreen` and guided Set up**

In `src/whyline/console/relay_screens.py`, add:

```python
class RunChoiceScreen(ModalScreen):
    """Run, step 1: a new plan or a saved one."""

    DEFAULT_CSS = """
    RunChoiceScreen { align: center middle; }
    RunChoiceScreen > Vertical {
        width: 70; height: auto; padding: 1 2;
        border: thick $accent; background: $surface;
    }
    RunChoiceScreen Horizontal { height: auto; margin-top: 1; }
    RunChoiceScreen Button { margin-right: 2; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Run the relay. Which plan should it work through?"),
            Horizontal(
                Button("Make a new plan", id="run-new", variant="primary"),
                Button("Use an existing plan", id="run-existing", variant="success"),
                Button("Cancel", id="run-cancel"),
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss({"run-new": "new", "run-existing": "existing"}.get(event.button.id))
```

Change `RelaySetupScreen`:

1. `__init__(self, root: Path, *, guided: bool = False, plan: Path | None = None)`. Store `self._guided = guided` and `self._summary = guided and relay_ops.roles_configured(root)`. When choosing `self._plan_default` (Task 15), prefer `str(plan)` when `plan` is given and listed, then `configured_plan`, then the newest.
2. Add:
   ```python
       def _roles_line(self) -> str:
           r = self._roles
           backup = " → ".join(r.get("backup", [])) or "none"
           return (f"Implementer: {r['implementer']} · Tester: {r['tester']} · "
                   f"Reviewer: {r['reviewer']} · Backup: {backup}")
   ```
3. In `compose`:
   - The title label becomes `"Run: check who does what, then start."` when `self._guided`, and stays as it is otherwise.
   - Wrap the three role rows, the "Backup, used when an agent fails:" label and the backup checkboxes in `Vertical(..., id="rs-roles")`.
   - When `self._summary`, put this between the plan row and `#rs-roles`:
     ```python
             Horizontal(
                 Static(self._roles_line(), id="rs-summary"),
                 Button("Looks good", id="rs-looks-good", variant="success"),
                 Button("Change", id="rs-change"),
                 id="rs-summary-row",
             )
     ```
   - CSS: `RelaySetupScreen #rs-roles { height: auto; }` and `RelaySetupScreen #rs-summary { width: 1fr; padding: 1 1 0 0; }`.
4. In `on_mount`, when `self._summary`: hide `#rs-roles` and `#rs-check`.
5. In `on_button_pressed`:
   ```python
           elif event.button.id == "rs-looks-good":
               self._check()
           elif event.button.id == "rs-change":
               self.query_one("#rs-summary-row").display = False
               self.query_one("#rs-roles").display = True
               self.query_one("#rs-check").display = True
   ```

- [ ] **Step 5: Run in the app**

In `src/whyline/console/tui.py`:

1. `compose`: add `Button("Run", id="relay-run", disabled=True)` right before `Button("Plan", id="relay-plan", ...)`.
2. `_sync_relay_buttons`: add `self._main("#relay-run", Button).disabled = not in_relay or running`.
3. `__init__`: add `self._run_flow = False`.
4. `on_button_pressed`: add `elif button_id == "relay-run": self._run_flow_start()`.
5. `_send`: next to the `start`/`resume` check, add:
   ```python
           if self.session.mode == "relay" and text.strip() == "run":
               self._run_flow_start()
               return
   ```
6. `_placeholder("relay")` returns `"Relay: run (guided), doctor, status, start, resume (Enter to run)"`.
7. Add:
   ```python
       def _run_flow_start(self) -> None:
           """Run (spec 6a): which plan, then who does what, then check and start."""
           if self._refuse_in_home():
               return
           if self._relay_running():
               self.render_event(SessionEvent(kind="error", text="The relay is already running."))
               return
           if self._plan_state:
               self.render_event(SessionEvent(
                   kind="error",
                   text="A plan is already in progress: approve it, Discard it, or press Esc."))
               return
           self._run_flow = True
           if not relay_ops.list_plans(self.session.root):
               self.render_event(SessionEvent(kind="output", text="No plan yet -- let's make one."))
               self._open_relay_plan()
               return
           from whyline.console.relay_screens import RunChoiceScreen

           self.push_screen(RunChoiceScreen(), self._run_choice)

       def _run_choice(self, choice: str | None) -> None:
           if choice == "new":
               self._open_relay_plan()
           elif choice == "existing":
               self._open_relay_setup(guided=True)
           else:
               self._end_run_flow("Run cancelled.")

       def _end_run_flow(self, text: str) -> None:
           if self._run_flow:
               self._run_flow = False
               self.render_event(SessionEvent(kind="output", text=text))
   ```
8. `_open_relay_setup(self, guided: bool = False, plan: Path | None = None)`: pass them through, `RelaySetupScreen(self.session.root, guided=guided, plan=plan)`.
9. `_plan_chosen`: when `result is None`, call `self._end_run_flow("Run cancelled.")` before returning.
10. `_plan_saved(path)`: after rendering its message, add:
    ```python
            if self._run_flow:
                self._open_relay_setup(guided=True, plan=path)
    ```
11. `_plan_failed`, `_discard_plan` and `action_leave_plan`: at the end of each, call `self._end_run_flow("Run stopped: no plan was saved.")`.
12. `_setup_done`: start with `self._run_flow = False` for `"start"` and `None`. For `"plan"`, set `self._run_flow = True` before `self._open_relay_plan()`, so a plan made from Set up returns to Set up.

- [ ] **Step 5b: Recommended roles and what they mean (spec 6b)**

Tests first. Add to `tests/console/test_relay_ops.py`:

```python
@pytest.mark.parametrize("usable, expected", [
    (["antigravity", "claude", "codex", "grok"],
     {"implementer": "codex", "tester": "claude", "reviewer": "grok", "backup": ["antigravity"]}),
    (["claude", "codex"],
     {"implementer": "codex", "tester": "claude", "reviewer": "claude", "backup": []}),
    (["grok"],
     {"implementer": "grok", "tester": "grok", "reviewer": "grok", "backup": []}),
])
def test_recommend_roles(usable, expected):
    assert relay_ops.recommend_roles(usable) == expected


def test_role_meaning():
    assert relay_ops.role_meaning("antigravity", "claude", "codex") == (
        "antigravity writes the code → claude runs the tests → codex reviews and commits."
    )
```

The second case shows the reuse rule: with two agents, the reviewer reuses the first agent in its preference list (claude), because codex already implements.

Add to `tests/console/test_run_flow.py`:

```python
async def test_with_no_roles_the_pickers_hold_the_recommendation(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: False)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#rs-implementer", tui.Select).value == "codex"
        assert screen.query_one("#rs-reviewer", tui.Select).value == "antigravity"
        assert "Recommended for the agents you have" in str(
            screen.query_one("#rs-recommended", tui.Static).renderable)
        assert str(screen.query_one("#rs-meaning", tui.Static).renderable) == (
            "codex writes the code → claude runs the tests → antigravity reviews and commits."
        )


async def test_a_configured_agent_that_is_not_usable_is_flagged(tmp_path, monkeypatch):
    from whyline import account

    status = {a: {"available": a != "antigravity", "label": "x"} for a in STATUS}
    monkeypatch.setattr(account, "agent_status", lambda root: status)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        app.push_screen(RelaySetupScreen(tmp_path, guided=True))
        await pilot.pause()
        screen = app.screen
        assert "⚠ antigravity isn't logged in" in str(
            screen.query_one("#rs-summary", tui.Static).renderable)
        assert screen.query_one("#rs-roles").display
        assert screen.query_one("#rs-implementer", tui.Select).value == "codex"
```

In this file's fixture, `relay_agents` returns `["antigravity", "claude", "codex"]` and `STATUS` marks all four available. So the recommendation is implementer codex, tester claude, reviewer antigravity, and no backup. The reviewer list is claude, codex, grok, antigravity: claude and codex are taken and grok isn't installed, so antigravity is next.

Then implement. In `relay_ops.py`:

```python
_PREFERENCE = {
    "implementer": ("codex", "claude", "antigravity", "grok"),
    "tester": ("claude", "codex", "grok", "antigravity"),
    "reviewer": ("claude", "codex", "grok", "antigravity"),
}


def recommend_roles(usable: list[str]) -> dict:
    """A different agent per role where possible (spec 6b); the rest back up."""
    roles: dict = {}
    used: set[str] = set()
    for role in ("implementer", "tester", "reviewer"):
        order = [a for a in _PREFERENCE[role] if a in usable] + [
            a for a in usable if a not in _PREFERENCE[role]
        ]
        fresh = [a for a in order if a not in used]
        roles[role] = (fresh or order or ["claude"])[0]
        used.add(roles[role])
    roles["backup"] = [a for a in _PREFERENCE["implementer"] if a in usable and a not in used]
    return roles


def usable_agents(root: Path, status: dict) -> list[str]:
    """Installed relay agents that are also logged in."""
    return [a for a in relay_agents(root) if status.get(a, {}).get("available")]


def role_meaning(implementer: str, tester: str, reviewer: str) -> str:
    return (f"{implementer} writes the code → {tester} runs the tests → "
            f"{reviewer} reviews and commits.")
```

In `RelaySetupScreen`:

1. `__init__`: compute
   ```python
           from whyline import account

           self._usable = relay_ops.usable_agents(root, account.agent_status(root))
           self._recommended = relay_ops.recommend_roles(self._usable)
           configured = relay_ops.roles_configured(root)
           in_use = [self._roles[r] for r in ("implementer", "tester", "reviewer")]
           self._unusable = [a for a in dict.fromkeys(in_use) if a not in self._usable]
           if not configured or self._unusable:
               self._roles = {**self._recommended} if not configured else {
                   **self._roles,
                   **{r: self._recommended[r] for r in ("implementer", "tester", "reviewer")
                      if self._roles[r] in self._unusable},
               }
   ```
   Do this before the Select widgets are built in `compose`, so they start with these values. Keep `self._summary = guided and configured`. The summary line keeps showing the configured roles and adds the warning.
2. `_roles_line()`: append `"   ⚠ " + ", ".join(f"{a} isn't logged in" for a in self._unusable)` when `self._unusable` is non-empty. Build the line from the configured roles: keep a copy as `self._configured_roles = dict(relay_ops.current_roles(root))` before step 1 changes `self._roles`.
3. In `compose`, inside `#rs-roles`, put first `Static("Recommended for the agents you have.", id="rs-recommended")`, shown only when the roles were not configured, and last `Static("", id="rs-meaning")`.
4. `on_mount`: when `self._summary and self._unusable`, show `#rs-roles` and keep `#rs-summary-row` visible, so the user sees both the warning and the fix. Then call `self._update_meaning()`.
5. Add:
   ```python
       def _update_meaning(self) -> None:
           i, t, r, _ = self._chosen()
           self.query_one("#rs-meaning", Static).update(relay_ops.role_meaning(i, t, r))
   ```
   and call it from `on_select_changed`, next to `_invalidate()`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/console -q`
Expected: PASS.

- [ ] **Step 7: Check it by hand**

In a scratch repository, with `whyline` in Relay mode, type `run`. With no plans, the Plan form opens. Paste `- [ ] T-1: x`, Save. Guided Set up opens with that plan selected. Press Looks good (or Change, then Check). Start becomes enabled.

- [ ] **Step 8: Commit**

```bash
git add src/whyline/console/relay_ops.py src/whyline/console/relay_screens.py src/whyline/console/tui.py tests/console/test_run_flow.py tests/console/test_relay_ops.py
git commit -m "feat: Run walks through plan, roles, checks and start (RPF-16)"
whyline note "Run is one guided path: plan (new or existing), roles summary with Looks good/Change, check, start" --because "users should not need to know Plan comes before Set up before Start" --rejected "Remove Plan and Set up buttons: they stay as shortcuts for experienced users" --rejected "Machine-wide default backup: the user chose per-repository backup (option B)" --file src/whyline/console/tui.py --actor <agent> --role implementer --task RPF-16
```

### Task 17: Release whyline 0.3.32

Same steps as Task 7, with `0.3.31` → `0.3.32`, the tag `v0.3.32`, the commit `chore: release whyline 0.3.32 (RPF-17)`, and `docs/releases/v0.3.32.md`:

```markdown
# whyline 0.3.32

Planning happens in the main window, can ask you questions, and Set up
picks which plan to run.

## What's changed

- "Make the plan" closes the Plan popup; progress, the draft and the
  agent's questions appear in the main window. Type "approve", say what
  to change, or answer the numbered questions in the normal prompt. The
  Approve / View draft / Discard buttons do the same.
- Plan lets you choose who drafts and who reviews.
- Plans are saved as `plans/<name>.plan.md`, so you can keep several.
  Set up starts with a Plan dropdown, and Start (or a typed `start`) needs
  a plan first.
- **Run** (a button, or type `run` in Relay mode) walks you through it:
  make a new plan or pick a saved one, confirm or change who implements,
  tests, reviews and backs up, check, then start.

Needs whyline-relay 0.2.29.

## Upgrading

```bash
uv tool upgrade whyline
```
```

After the release, run `whyline` in TradingPlatform and confirm: the brainstorm runs grok and antigravity (after the one trust question), and Plan → Set up → Start works end to end.
