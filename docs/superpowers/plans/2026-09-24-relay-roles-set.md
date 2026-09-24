# `roles set` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `whyline-relay roles set <ROLE> [--agent NAME] [--model NAME]` permanently points a role at an agent, editing `config.toml` itself — distinct from `roles reset`, which only clears a temporary failover override. Called with no `--agent`/`--model`, it prompts interactively. Along the way, fix a real pre-existing gap: `roles status` and `roles reset` are both hardcoded to the fixed `implementer`/`reviewer` pair and silently don't work for a configured `[pipeline]`'s own role names.

**Architecture:** `roles.current_roles(settings)` is the one place that decides which role names exist right now — a configured pipeline's own roles when `[pipeline]` is set, else the legacy pair — and both `status()` and the new `set_role()` build on it, closing the same kind of gap `_agents_in_use` had before piece B fixed it. `set_role()` validates exactly the way `config.load()` already does (a named agent must be a built-in or an already-configured generic one), then makes a minimal, targeted text edit to `config.toml` — the project has zero runtime dependencies, so this is not a TOML round-trip through a library, only the one `[roles]` line (and, if `--model` is given for a built-in, one `[agents.<name>]` line) that actually changes.

**Tech Stack:** Python 3.11+, stdlib only (`tomllib` for reading, verified against the hand-written edits; no TOML-writing dependency added).

**Spec:** `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md`, D11 and §5.10. This plan implements the `roles set` half of D11 only — `init` asking about every role's agent and model interactively when setting up a new repository is a separate, later piece (deliberately narrower scope; see "Not in this plan").

## Global Constraints

- No new dependency. `config.toml` is edited as text, touching only the specific line(s) a call actually changes — every other line, comment, and table's ordering is preserved exactly.
- `set_role`'s validation matches `config.load()`'s existing rule exactly: a named agent must be in `adapters.BUILTIN` or already present in `settings.adapters` (the loaded config's configured generic/aliased agents). `set_role` never invents a new aliased agent name from whole cloth.
- `--model` only applies when the named agent is a literal built-in (`codex` or `claude`) — an already-configured alias (for example `claude-opus`) carries its own model already, and a generic agent has nowhere to put one (matching 0.2.6's existing rule).
- `set_role` only changes an *existing* role's agent — it does not add a new role or a new pipeline stage. Naming a role that isn't currently configured is refused, listing the roles that are.
- Every existing test must still pass, including every existing `roles`/`cli` test exercising the legacy `implementer`/`reviewer` pair.

---

### Task 1: `roles.py` — `current_roles`, pipeline-aware `status`, and `set_role`

**Files:**
- Modify: `src/whyline_relay/roles.py` (generalize `status` at line 10; add `current_roles`, `RoleSetError`, `_upsert_role`, `_upsert_agent_model`, `set_role`)
- Test: `tests/test_roles.py` (create if it doesn't already exist — check first with `ls tests/test_roles.py`; if it exists, add to it)

**Interfaces:**
- Produces: `roles.current_roles(settings) -> dict[str, str]` (role name -> configured agent, whichever shape is active). `roles.RoleSetError(ValueError)`. `roles.set_role(root, settings, role, *, agent, model, confirm=input) -> str`. Task 2 is the only caller of `set_role`/`current_roles` outside this module's own tests.

- [ ] **Step 1: Write the failing tests**

Create or add to `tests/test_roles.py`. First, check whether `roles.status`/`roles.reset` already have tests elsewhere (search `grep -rn "roles\.status\|roles\.reset" tests/`) and follow whatever fixture style they already use for building a repo with a `config.toml`; if none exists, use this shape:

```python
import json
from pathlib import Path

import pytest

from whyline_relay import config, pipeline as pipeline_module, roles


def _write(root: Path, text: str) -> None:
    relay = root / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text(text)


def test_current_roles_is_the_legacy_pair_without_a_pipeline(tmp_path):
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\n')
    settings = config.load(tmp_path)
    assert roles.current_roles(settings) == {"implementer": "codex", "reviewer": "claude"}


def test_current_roles_is_the_pipelines_own_roles_when_configured(tmp_path):
    _write(
        tmp_path,
        '[roles]\nimplementer = "codex"\ntester = "claude"\nreviewer = "claude"\n'
        '[pipeline]\ndefault_profile = "full"\n'
        '[pipeline.profiles]\nfull = ["only"]\n'
        '[pipeline.stages.only]\nrole = "implementer"\nprompt = "implement"\n'
        '[pipeline.stages.only.on]\nready = "@complete"\n',
    )
    settings = config.load(tmp_path)
    assert roles.current_roles(settings) == {
        "implementer": "codex", "tester": "claude", "reviewer": "claude",
    }


def test_set_role_changes_the_agent_and_preserves_everything_else(tmp_path):
    _write(
        tmp_path,
        '# a comment\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n\n'
        '[agents.codex]\ncommand = ["codex"]\n\n[agents.claude]\ncommand = ["claude"]\n',
    )
    settings = config.load(tmp_path)
    message = roles.set_role(tmp_path, settings, "reviewer", agent="codex", model=None)
    assert message == "reviewer set to codex"
    reloaded = config.load(tmp_path)
    assert roles.current_roles(reloaded) == {"implementer": "codex", "reviewer": "codex"}
    text = config.config_path(tmp_path).read_text()
    assert "# a comment" in text
    assert text.count("[agents.codex]") == 1 and text.count("[agents.claude]") == 1


def test_set_role_with_a_model_writes_the_agents_block(tmp_path):
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\n')
    settings = config.load(tmp_path)
    message = roles.set_role(tmp_path, settings, "implementer", agent="claude", model="opus")
    assert message == "implementer set to claude (model opus)"
    reloaded = config.load(tmp_path)
    assert reloaded.agents["claude"] == ["claude", "-p", "--permission-mode", "acceptEdits",
                                          "--output-format", "json", "--settings",
                                          ".whyline/relay/claude-settings.json", "--model", "opus"]


def test_set_role_refuses_an_unknown_role(tmp_path):
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\n')
    settings = config.load(tmp_path)
    with pytest.raises(roles.RoleSetError, match="not a configured role"):
        roles.set_role(tmp_path, settings, "nonexistent", agent="codex", model=None)


def test_set_role_refuses_an_unknown_agent(tmp_path):
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\n')
    settings = config.load(tmp_path)
    with pytest.raises(roles.RoleSetError, match="not a built-in agent"):
        roles.set_role(tmp_path, settings, "implementer", agent="nonexistent-thing", model=None)


def test_set_role_refuses_a_model_on_a_non_builtin_agent(tmp_path):
    _write(
        tmp_path,
        '[roles]\nimplementer = "codex"\nreviewer = "claude"\n'
        '[agents.aider]\nadapter = "generic"\ncommand = ["aider"]\n',
    )
    settings = config.load(tmp_path)
    with pytest.raises(roles.RoleSetError, match="only applies to a built-in"):
        roles.set_role(tmp_path, settings, "implementer", agent="aider", model="sonnet")


def test_set_role_prompts_interactively_when_agent_and_model_are_omitted(tmp_path):
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\n')
    settings = config.load(tmp_path)
    answers = iter(["claude", "haiku"])
    message = roles.set_role(
        tmp_path, settings, "implementer", agent=None, model=None,
        confirm=lambda _prompt: next(answers),
    )
    assert message == "implementer set to claude (model haiku)"


def test_set_role_keeps_the_current_agent_on_a_blank_answer(tmp_path):
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\n')
    settings = config.load(tmp_path)
    message = roles.set_role(
        tmp_path, settings, "implementer", agent=None, model=None, confirm=lambda _prompt: "",
    )
    assert message == "implementer set to codex"


def test_set_role_with_agent_given_and_no_model_never_prompts(tmp_path):
    # Regression case: --agent alone (no --model) must not also prompt for a
    # model just because the agent happens to be a built-in -- that would hang
    # or fail a non-interactive/scripted call that only meant to change the
    # agent. `confirm` raising proves it is never called at all.
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\n')
    settings = config.load(tmp_path)

    def confirm_must_not_be_called(_prompt):
        raise AssertionError("set_role prompted when --agent was already given")

    message = roles.set_role(
        tmp_path, settings, "implementer", agent="codex", model=None,
        confirm=confirm_must_not_be_called,
    )
    assert message == "implementer set to codex"
```

Adjust `test_set_role_with_a_model_writes_the_agents_block`'s expected command list if `config.DEFAULTS["agents"]["claude"]` differs from what's shown — read it directly from `config.py` first (`config.DEFAULTS["agents"]["claude"]`) rather than guessing, since it must match exactly for the assertion to be meaningful.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_roles.py -v`
Expected: FAIL — `roles.current_roles`, `roles.RoleSetError`, and `roles.set_role` don't exist yet (`AttributeError`).

- [ ] **Step 3: Implement**

Replace `src/whyline_relay/roles.py` in full:

```python
"""Inspecting a role's agent, clearing a sticky backup switch, and setting it permanently."""

from __future__ import annotations

import re
from pathlib import Path

from whyline_relay import adapters, config, failover


class RoleSetError(ValueError):
    """A `roles set` request cannot be honored as given."""


def current_roles(settings: config.Config) -> dict[str, str]:
    """Every role name -> its configured agent, whichever shape is active."""
    if settings.pipeline is not None:
        return {name: role.agent for name, role in settings.pipeline.roles.items()}
    return {"implementer": settings.roles.implementer, "reviewer": settings.roles.reviewer}


def status(root: Path, settings: config.Config) -> str:
    lines = []
    for role, configured in current_roles(settings).items():
        override = failover.read_overrides(root).get(role)
        if override is None:
            lines.append(f"{role}: {configured}")
        else:
            verb, _ = failover.REASON_TEXT[override.reason]
            lines.append(
                f"{role}: {configured}, currently {override.agent} "
                f"({override.reason}: {configured} {verb}, since {override.since})"
            )
    return "\n".join(lines)


def reset(root: Path, role: str | None) -> str:
    removed = failover.clear_overrides(root, role)
    if removed == 0:
        return "Nothing to reset." if role is None else f"{role} was not on a backup."
    if role is None:
        return f"Reset {removed} role(s) to their configured agent."
    return f"{role} reset to its configured agent."


def _upsert_role(text: str, role: str, agent: str) -> str:
    """Set `role = "agent"` under [roles], creating the table if it doesn't exist.

    A minimal, targeted text edit, not a real TOML round-trip: the project has
    no runtime dependencies, so there is no TOML-writing library available.
    Touches only the one line this role owns (or adds one), leaving comments,
    ordering, and every other key exactly as they were.
    """
    lines = text.splitlines(keepends=True)
    table_start = None
    table_end = len(lines)
    for i, line in enumerate(lines):
        if table_start is None and line.strip() == "[roles]":
            table_start = i
            continue
        if table_start is not None and i > table_start and re.match(r"^\[", line.strip()):
            table_end = i
            break
    key_pattern = re.compile(rf"^{re.escape(role)}\s*=")
    if table_start is not None:
        for i in range(table_start + 1, table_end):
            if key_pattern.match(lines[i].strip()):
                lines[i] = f'{role} = "{agent}"\n'
                return "".join(lines)
        lines.insert(table_end, f'{role} = "{agent}"\n')
        return "".join(lines)
    suffix = "" if (not text or text.endswith("\n")) else "\n"
    return text + suffix + f'\n[roles]\n{role} = "{agent}"\n'


def _upsert_agent_model(text: str, name: str, model: str) -> str:
    """Set `model = "..."` under [agents.<name>], creating the block if absent."""
    header = f"[agents.{name}]"
    lines = text.splitlines(keepends=True)
    table_start = None
    table_end = len(lines)
    for i, line in enumerate(lines):
        if table_start is None and line.strip() == header:
            table_start = i
            continue
        if table_start is not None and i > table_start and re.match(r"^\[", line.strip()):
            table_end = i
            break
    if table_start is not None:
        for i in range(table_start + 1, table_end):
            if re.match(r"^model\s*=", lines[i].strip()):
                lines[i] = f'model = "{model}"\n'
                return "".join(lines)
        lines.insert(table_end, f'model = "{model}"\n')
        return "".join(lines)
    suffix = "" if (not text or text.endswith("\n")) else "\n"
    return text + suffix + f'\n{header}\nmodel = "{model}"\n'


def set_role(
    root: Path,
    settings: config.Config,
    role: str,
    *,
    agent: str | None,
    model: str | None,
    confirm=input,
) -> str:
    """Permanently point `role` at `agent` (and, for a built-in, optionally `model`).

    Distinct from a failover override (roles.reset, roles status): this edits
    config.toml itself, the same file `init` wrote, not a temporary sticky
    switch that reverts on its own. Called with no `--agent`/`--model`, it
    prompts interactively instead of requiring the exact TOML shape by hand.
    """
    current = current_roles(settings)
    if role not in current:
        raise RoleSetError(f"{role!r} is not a configured role ({', '.join(sorted(current))})")

    # Only a fully-interactive call (no --agent at all) also prompts for a
    # model: `--agent codex` alone must mean "just change the agent," not
    # "and also ask me something else on stdin" -- the shape a script or CI
    # invocation relies on.
    interactive = agent is None
    if agent is None:
        try:
            answer = confirm(f"Agent for {role} [{current[role]}]: ").strip()
        except EOFError:
            raise RoleSetError("no terminal to prompt on; pass --agent") from None
        agent = answer or current[role]

    if agent not in adapters.BUILTIN and agent not in settings.adapters:
        builtins = ", ".join(sorted(adapters.BUILTIN))
        raise RoleSetError(
            f"{agent!r} is not a built-in agent ({builtins}) or a configured generic agent"
        )

    if interactive and model is None and agent in adapters.BUILTIN:
        try:
            answer = confirm(f"Model for {agent} (blank for default): ").strip()
        except EOFError:
            answer = ""
        model = answer or None

    if model is not None and agent not in adapters.BUILTIN:
        builtins = ", ".join(sorted(adapters.BUILTIN))
        raise RoleSetError(
            f"--model only applies to a built-in agent name ({builtins}); {agent!r} "
            "already carries its own model if it's an alias"
        )

    target = config.config_path(root)
    text = target.read_text(encoding="utf-8")
    text = _upsert_role(text, role, agent)
    if model is not None:
        text = _upsert_agent_model(text, agent, model)
    target.write_text(text, encoding="utf-8")

    summary = f"{role} set to {agent}"
    return summary if model is None else f"{summary} (model {model})"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_roles.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — `status`'s output is unchanged for the legacy pair (`current_roles` returns the identical dict `status` used to build inline), and `reset` is untouched.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/roles.py tests/test_roles.py
git commit -m "feat: roles.set_role() permanently points a role at an agent; roles are pipeline-aware"
```

---

### Task 2: `cli.py` — wire `roles set`, make `roles reset`'s role dynamic

**Files:**
- Modify: `src/whyline_relay/cli.py` (the `roles_sub` parser block around line 195, `cmd_roles` at line 361)
- Test: `tests/test_roles_cli.py` (add to the existing file — it already covers `roles status`/`roles reset` with a `make_repo(tmp_path)` helper that writes an empty `config.toml`, relying on `config.DEFAULTS` for the legacy `implementer=codex`/`reviewer=claude` pair)

**Interfaces:**
- Consumes: `roles.current_roles`, `roles.set_role`, `roles.RoleSetError` (Task 1).
- Produces: `whyline-relay roles set <ROLE> [--agent NAME] [--model NAME]` on the command line. `whyline-relay roles reset <ROLE>` now accepts any role the current config actually defines, not only `implementer`/`reviewer`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_roles_cli.py`, reusing its existing `make_repo(tmp_path)` helper:

```python
def test_set_changes_the_agent_and_reports_it(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert cli.main(["roles", "set", "reviewer", "--agent", "codex", "--repo", str(repo)]) == 0
    assert "reviewer set to codex" in capsys.readouterr().out
    capsys.readouterr()
    cli.main(["roles", "status", "--repo", str(repo)])
    assert "reviewer: codex" in capsys.readouterr().out


def test_set_with_a_model_reports_it_too(tmp_path, capsys):
    repo = make_repo(tmp_path)
    code = cli.main(
        ["roles", "set", "implementer", "--agent", "claude", "--model", "opus", "--repo", str(repo)]
    )
    assert code == 0
    assert "implementer set to claude (model opus)" in capsys.readouterr().out


def test_set_reports_an_error_and_exits_nonzero_on_an_unknown_agent(tmp_path, capsys):
    repo = make_repo(tmp_path)
    code = cli.main(
        ["roles", "set", "implementer", "--agent", "nonexistent-thing", "--repo", str(repo)]
    )
    assert code == 1
    assert "not a built-in agent" in capsys.readouterr().err


def test_reset_accepts_a_role_a_configured_pipeline_actually_defines(tmp_path, capsys):
    # A pipeline's own role name (here, "tester") -- reset could not accept
    # anything but "implementer"/"reviewer" before this task.
    repo = make_repo(tmp_path)
    (repo / ".whyline" / "relay" / "config.toml").write_text(
        '[roles]\nimplementer = "codex"\ntester = "claude"\nreviewer = "claude"\n'
        '[pipeline]\ndefault_profile = "full"\n'
        '[pipeline.profiles]\nfull = ["only"]\n'
        '[pipeline.stages.only]\nrole = "implementer"\nprompt = "implement"\n'
        '[pipeline.stages.only.on]\nready = "@complete"\n'
    )
    code = cli.main(["roles", "reset", "tester", "--repo", str(repo)])
    assert code == 0
    assert "was not on a backup" in capsys.readouterr().out


def test_reset_rejects_a_role_the_current_config_does_not_define(tmp_path, capsys):
    repo = make_repo(tmp_path)
    code = cli.main(["roles", "reset", "nonexistent", "--repo", str(repo)])
    assert code == 1
    assert "not a configured role" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_roles_cli.py -v`
Expected: FAIL — there is no `roles set` subcommand yet (argparse exits with "invalid choice"), and `roles reset`'s `choices=("implementer", "reviewer")` rejects `tester`/`nonexistent` before ever reaching `cmd_roles`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/cli.py`, find the `roles_reset` parser block:

```python
    roles_reset = roles_sub.add_parser(
        "reset", help="Clear a sticky backup switch"
    )
    roles_reset.add_argument(
        "role",
        nargs="?",
        default=None,
        choices=("implementer", "reviewer"),
        help="Reset only this role (default: every role).",
    )
    roles_reset.add_argument(
        "--repo", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )
```

Replace it with (drop `choices=`, since valid role names now depend on the config loaded at runtime, not a fixed pair — validated in `cmd_roles` below), and add the new `roles_set` parser right after it:

```python
    roles_reset = roles_sub.add_parser(
        "reset", help="Clear a sticky backup switch"
    )
    roles_reset.add_argument(
        "role",
        nargs="?",
        default=None,
        help="Reset only this role (default: every role).",
    )
    roles_reset.add_argument(
        "--repo", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )
    roles_set = roles_sub.add_parser(
        "set", help="Permanently point a role at an agent"
    )
    roles_set.add_argument(
        "role", help="The role to change (implementer, reviewer, or a configured pipeline role)"
    )
    roles_set.add_argument(
        "--agent", default=None, help="The agent name to use"
    )
    roles_set.add_argument(
        "--model", default=None,
        help="Optional model, for a built-in agent name (codex or claude)",
    )
    roles_set.add_argument(
        "--repo", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )
```

Then replace `cmd_roles` in full:

```python
def cmd_roles(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    settings = config.load(root)
    if args.roles_command == "status":
        print(roles.status(root, settings))
        return EXIT_OK
    if args.roles_command == "set":
        try:
            print(
                roles.set_role(
                    root, settings, args.role, agent=args.agent, model=args.model
                )
            )
        except roles.RoleSetError as error:
            print(f"Error: {error}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_OK
    if args.role is not None and args.role not in roles.current_roles(settings):
        valid = ", ".join(sorted(roles.current_roles(settings)))
        print(f"Error: {args.role!r} is not a configured role ({valid})", file=sys.stderr)
        return EXIT_ERROR
    print(roles.reset(root, args.role))
    return EXIT_OK
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_roles_cli.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — every existing `roles status`/`roles reset` CLI test (using the legacy `implementer`/`reviewer` pair) must be unaffected, since `current_roles` returns that exact pair when no `[pipeline]` is configured.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/cli.py tests/test_roles_cli.py
git commit -m "feat: wire whyline-relay roles set; roles reset accepts a configured pipeline's own role names"
```

---

### Task 3: README — document `roles set`

**Files:**
- Modify: `README.md` (the "Backup agents" or "Choosing which agent fills each role" section — find where `roles status`/`roles reset` are currently documented, if at all, via `grep -n "roles status\|roles reset" README.md`, and add this alongside)

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find where the README documents `roles status`/`roles reset` (search for `roles status` in `README.md` — likely in "Backup agents" or "Command reference"). Add, right after that existing documentation:

```markdown
**`whyline-relay roles set <ROLE> [--agent NAME] [--model NAME]`** permanently points a role at an agent — a real edit to `config.toml`, unlike `roles reset`, which only clears a temporary failover switch. Works for any role the current config defines: `implementer`/`reviewer` normally, or a configured `[pipeline]`'s own role names. Called with no `--agent`/`--model`, it prompts for both interactively (blank keeps the current agent; a model prompt only appears for a built-in agent name). Refuses an agent name that isn't a built-in or an already-configured one, the same validation `config.toml` itself is held to.
```

If `README.md` doesn't currently document `roles status`/`roles reset` at all, add this paragraph to the "Backup agents" section instead, right after the existing description of `roles status`/`roles reset` behavior (the sentence mentioning "`whyline-relay roles status` shows whether a role is currently on its backup").

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document whyline-relay roles set"
```

## Not in this plan

- `init` asking about every role's agent and model interactively when setting up a new repository (spec D11, §5.10's other half) — a separate, later piece with its own UX design questions (exact prompt flow, defaults, how it interacts with `--implementer`/`--reviewer` flags already accepted today).
- Adding a genuinely new role or pipeline stage via the CLI — `set_role` only repoints an *existing* role's agent; authoring a new `[pipeline.stages.*]` entry is still done by hand in `config.toml`.
- A general TOML-writing library or AST-based config editor — deliberately out of scope (Global Constraints); the targeted text edits here are sufficient for the one or two lines `roles set` ever needs to change.
