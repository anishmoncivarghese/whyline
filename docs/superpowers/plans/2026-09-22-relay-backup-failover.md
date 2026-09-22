# whyline-relay backup agents and failover (relay 0.2.4) Implementation Plan

> **For agentic workers:** this plan is run by whyline-relay itself, on its own repository: Codex implements each task, Claude reviews and commits it. The tasks in "The tasks" are the run's `plan.md`, copied verbatim into a sandbox clone. Each task is handed to a fresh agent with no memory of the others, so each one stands alone: the "Rules for every task" line under each title repeats the Global Constraints for that reason.

**Goal:** A role (`implementer` or `reviewer`) can name one backup agent. When the role's active agent hits a detected usage limit or loses authentication, the relay switches to the backup automatically and keeps going in the same run — sticky until the owner changes it by hand.

**Architecture:** A new `failover.py` module holds the two detection functions (reusing `agents.rate_limited` for quota, and an adapter's existing `login_argv` for auth — never new text-guessing), the persisted override (`.whyline/relay/active-roles.json`), and the one resolution point every other module reads a role's agent through. `config.py` gains `[roles.backup]`. `loop.py`'s only change is at the point it already checks for a rate limit, plus reading agents through the resolver instead of `settings.roles.*` directly. `preflight.py` checks a configured backup the same way it checks a primary. A new `roles.py` gives `roles status`/`roles reset`.

**Tech Stack:** Python 3.11+, standard library only, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-22-relay-backup-failover-design.md`. Section 5 has the full design; section 3 maps it onto exact files as they exist today (relay 0.2.3).

## Global Constraints

Every task's requirements include these.

- No new dependencies. Do not touch `pyproject.toml`, `uv.lock`, or the version.
- The sandbox has no network: run tests with `uv run --frozen pytest -q`.
- With no `[roles.backup]` configured, every existing behaviour, message, and file is exactly what relay 0.2.3 produced. The existing 313 tests, unedited, are the proof.
- The relay never passes a permission-bypass flag, never runs `git push`, and never writes a handoff on an agent's behalf.
- One backup per role, no chain, no automatic reversion to the primary (the owner reverts by hand). A generic agent (`login_argv is None`) can never trigger the auth path — there is no structured way to check its login, and the relay never guesses.
- `cli.main(argv=None, prog="whyline-relay")` keeps its signature. No hard-coded command name `whyline-relay` in `src/` (use `invocation.command`).

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/whyline_relay/config.py` | `[roles.backup]` parsing and validation; `Config.backups` | 1 |
| `src/whyline_relay/failover.py` (new) | `ActiveOverride`, persistence, `effective_agent`, `still_logged_in`, `failover_reason`, `pause_message` | 2 |
| `src/whyline_relay/gitcheck.py` | `active-roles.json` added to `RELAY_IGNORE` | 2 |
| `src/whyline_relay/loop.py` | reads agents through `effective_agent`; the switch-and-continue check on `NO_HANDOFF` | 3 |
| `src/whyline_relay/cli.py` | `start --dry-run` uses `effective_agent`; `roles` wired to the new module | 3, 4 |
| `src/whyline_relay/preflight.py` | `_agents_in_use` includes each role's backup, labelled as such | 4 |
| `src/whyline_relay/roles.py` (new) | `status(root, settings) -> str`; `reset(root, role) -> int` | 4 |
| `tests/` | new test files per task | all |

## Not in this plan

Everything in the design's section 8 roadmap (more than two roles, subscription-aware setup, first-run interactive setup, planner, tester, documentation/security-review roles). This plan is exactly the design's sections 1-7.

## How this is run and checked

1. Independent acceptance tests, written before the run, from this plan's requirements. They must fail on 0.2.3 and be validated against a fake-agent reference the way every earlier round in this project was.
2. A sandbox clone of the relay (remotes removed) holds the tasks below as `plan.md`. `whyline-relay start` runs them.
3. After the run: the full existing suite (unedited), the existing acceptance suites (unedited), the new acceptance tests, and tripwires confirming no real agent or `osascript` binary is ever invoked.
4. Cherry-pick into the real repository, release notes (written by hand from measured behaviour), pre-flight, then stop for an explicit go before pushing or tagging `v0.2.4`.

## Release

Relay **0.2.4**. whyline's pin (`whyline-relay>=0.2.1,<0.3`) already admits it.

---

## The tasks

Run order matters: each task builds on the commits before it.

- [ ] FBO-1: `[roles.backup]` configuration
  Rules for every task: run the tests with `uv run --frozen pytest -q` (there is no network). Add no dependencies and do not touch `pyproject.toml`, `uv.lock` or the version. With no `[roles.backup]` in a config, every existing test, unedited, must still pass. Never pass or write a permission-bypass flag, never run `git push`, and never write a handoff on an agent's behalf.

  Add `[roles.backup]` to `config.py`, alongside the existing `[roles]`. Change nothing else.

  **`config.py`:**
  - `Config` gains one new field, at the end, with a default: `backups: dict[str, str] = field(default_factory=dict)` (role name → backup agent name; a role absent from this dict has no backup).
  - In `load()`, the existing loop `for key in role_values: if key not in ("implementer", "reviewer"): raise ConfigError(...)` must also accept a key named `backup` (whose value is a nested table, not a string) without raising. Everything else about that loop (rejecting any other unknown key) is unchanged.
  - New validation, run after the existing per-role validation (so `role_names` and `configured_adapters` already exist): read `backup_values = role_values.get("backup") or {}`. For each `key` in `backup_values`:
    - `key not in ("implementer", "reviewer")` → `ConfigError(f"[roles.backup] has an unknown key '{key}' (use implementer or reviewer)")`.
    - the value is not a string → `ConfigError(f"[roles.backup] {key} must be a string")`.
    - the value equals `role_names[key]` (the backup names the same agent already filling that role) → `ConfigError(f"[roles.backup] {key} cannot be the same as its own agent")`.
    - the value is not in `adapters.BUILTIN` and not in `configured_adapters` → `ConfigError(f"[roles.backup] {key} names '{value}', which is not a built-in agent ({builtins}) or a configured generic agent")`, with `builtins` the same sorted, comma-joined list the existing role-validation error already builds.
  - `Config(..., backups=dict(backup_values))` is returned. When `[roles.backup]` is absent entirely, `backups == {}`.

  **Tests first**, added to `tests/test_config.py`:

  ```python
  def write(root, text):  # already exists in this file; reuse it
      ...

  def test_no_backup_table_means_no_backups(tmp_path):
      write(tmp_path, "")
      assert config.load(tmp_path).backups == {}

  def test_a_role_backup_is_parsed(tmp_path):
      write(tmp_path, '[roles.backup]\nimplementer = "claude"\n')
      loaded = config.load(tmp_path)
      assert loaded.backups == {"implementer": "claude"}
      assert loaded.roles.implementer == "codex"  # the primary is untouched

  def test_a_backup_may_be_a_configured_generic_agent(tmp_path):
      write(tmp_path, '[roles.backup]\nreviewer = "aider"\n[agents.aider]\nadapter = "generic"\ncommand = ["aider"]\n')
      assert config.load(tmp_path).backups == {"reviewer": "aider"}

  def test_a_backup_naming_the_same_agent_as_its_role_is_refused(tmp_path):
      write(tmp_path, '[roles.backup]\nimplementer = "codex"\n')
      with pytest.raises(config.ConfigError, match="cannot be the same as its own agent"):
          config.load(tmp_path)

  def test_a_backup_naming_an_unknown_agent_is_refused(tmp_path):
      write(tmp_path, '[roles.backup]\nimplementer = "gemini"\n')
      with pytest.raises(config.ConfigError, match="not a built-in agent .* or a configured generic agent"):
          config.load(tmp_path)

  def test_an_unknown_key_under_roles_backup_is_refused(tmp_path):
      write(tmp_path, '[roles.backup]\nplanner = "claude"\n')
      with pytest.raises(config.ConfigError, match="\\[roles.backup\\] has an unknown key 'planner'"):
          config.load(tmp_path)

  def test_a_non_string_backup_is_refused(tmp_path):
      write(tmp_path, "[roles.backup]\nimplementer = 3\n")
      with pytest.raises(config.ConfigError, match="\\[roles.backup\\] implementer must be a string"):
          config.load(tmp_path)

  def test_config_built_by_hand_still_works_without_backups():
      cfg = config.Config(plan="plan.md", max_rounds=3, timeout_minutes=30, branch_prefix="relay/", agents={}, status_map={})
      assert cfg.backups == {}
  ```

  Run `uv run --frozen pytest -q`: all existing tests pass unedited, plus these new ones. Change nothing else.

- [ ] FBO-2: the `failover` module
  Rules for every task: run the tests with `uv run --frozen pytest -q` (there is no network). Add no dependencies and do not touch `pyproject.toml`, `uv.lock` or the version. With no `[roles.backup]` in a config, every existing test, unedited, must still pass. Never pass or write a permission-bypass flag, never run `git push`, and never write a handoff on an agent's behalf.

  Add `src/whyline_relay/failover.py`: the persisted override, the two detection functions, and the resolver every later task reads a role's agent through. Add `.whyline/relay/active-roles.json` to `gitcheck.RELAY_IGNORE`. Change nothing else — this task does not change `loop.py`, `preflight.py`, or `cli.py`.

  **Create** `src/whyline_relay/failover.py`:

  ```python
  """Backup agents: detecting a usage limit or a lost login, and the sticky switch to a backup."""

  from __future__ import annotations

  import json
  import subprocess
  from dataclasses import asdict, dataclass
  from pathlib import Path
  from typing import Callable

  from whyline_relay import agents, config
  from whyline_relay.adapters.base import Adapter

  Runner = Callable[..., subprocess.CompletedProcess]

  # (verb, suffix) — the plain pause message is "{agent} {verb}; {suffix}", which for
  # "rate-limit" reproduces relay 0.2.3's message byte for byte.
  REASON_TEXT: dict[str, tuple[str, str]] = {
      "rate-limit": ("hit a usage or rate limit", "try again when it resets"),
      "auth": ("is no longer logged in", "try again once you've signed back in"),
  }


  @dataclass(frozen=True)
  class ActiveOverride:
      agent: str
      backup_for: str
      reason: str  # "rate-limit" | "auth"
      since: str   # ISO timestamp


  def path(root: Path) -> Path:
      return config.relay_dir(root) / "active-roles.json"


  def read_overrides(root: Path) -> dict[str, ActiveOverride]:
      try:
          raw = json.loads(path(root).read_text(encoding="utf-8"))
      except (OSError, json.JSONDecodeError):
          return {}
      if not isinstance(raw, dict):
          return {}
      fields = ("agent", "backup_for", "reason", "since")
      result: dict[str, ActiveOverride] = {}
      for role, record in raw.items():
          if isinstance(record, dict) and all(
              isinstance(record.get(f), str) for f in fields
          ):
              result[role] = ActiveOverride(**{f: record[f] for f in fields})
      return result


  def _write_all(root: Path, overrides: dict[str, ActiveOverride]) -> None:
      target = path(root)
      if not overrides:
          target.unlink(missing_ok=True)
          return
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(
          json.dumps({r: asdict(o) for r, o in overrides.items()}, indent=2) + "\n",
          encoding="utf-8",
      )


  def write_override(root: Path, role: str, override: ActiveOverride) -> None:
      overrides = read_overrides(root)
      overrides[role] = override
      _write_all(root, overrides)


  def clear_overrides(root: Path, role: str | None = None) -> int:
      """Remove the override for `role`, or every override if `role` is None. Returns the count removed."""
      overrides = read_overrides(root)
      if role is None:
          removed = len(overrides)
          overrides = {}
      elif role in overrides:
          del overrides[role]
          removed = 1
      else:
          removed = 0
      _write_all(root, overrides)
      return removed


  def effective_agent(root: Path, settings: config.Config, role: str) -> str:
      """The agent actually filling `role` right now: its backup if switched, else its configured agent."""
      override = read_overrides(root).get(role)
      return override.agent if override is not None else getattr(settings.roles, role)


  def still_logged_in(adapter: Adapter, runner: Runner = subprocess.run) -> bool:
      """True when the adapter has no login check, or the check says it's fine.

      Never guesses a "no" from an error or a timeout: those mean the check was
      inconclusive, not that the agent is logged out.
      """
      if adapter.login_argv is None:
          return True
      try:
          result = runner(list(adapter.login_argv), capture_output=True, text=True, timeout=20)
      except (OSError, subprocess.TimeoutExpired):
          return True
      return result.returncode == 0


  def failover_reason(
      adapter: Adapter, text: str, command: list[str], runner: Runner = subprocess.run
  ) -> str | None:
      """'rate-limit', 'auth', or None. Checked only when a turn produced no handoff.

      The auth check runs only when `command` is actually the adapter's own binary —
      the same restriction preflight._logins already applies, and for the same reason:
      a stand-in command (a test fixture, or a deliberately different wrapper) must never
      have someone else's login checked against it.
      """
      if agents.rate_limited(text):
          return "rate-limit"
      checkable = adapter.login_argv is not None and Path(command[0]).name == adapter.binary
      if checkable and not still_logged_in(adapter, runner):
          return "auth"
      return None


  def pause_message(agent: str, role: str, reason: str, override: ActiveOverride | None) -> str:
      verb, suffix = REASON_TEXT[reason]
      if override is not None and override.agent == agent:
          other_verb, _ = REASON_TEXT[override.reason]
          return (
              f"{agent} (backup for {role}; {override.backup_for} was already out: "
              f"it {other_verb}) also {verb}; {suffix}"
          )
      return f"{agent} {verb}; {suffix}"
  ```

  **`gitcheck.py`:** add `".whyline/relay/active-roles.json"` as a new entry in the `RELAY_IGNORE` tuple.

  **Tests first**, new `tests/test_failover.py`:

  ```python
  import subprocess
  from whyline_relay import failover
  from whyline_relay.adapters import codex as codex_adapter

  def test_no_override_means_the_configured_agent(tmp_path):
      from whyline_relay.config import Config, Roles
      settings = Config(plan="p", max_rounds=3, timeout_minutes=30, branch_prefix="r/",
                         agents={}, status_map={}, roles=Roles("codex", "claude"))
      assert failover.effective_agent(tmp_path, settings, "implementer") == "codex"

  def test_a_written_override_is_the_effective_agent(tmp_path):
      from whyline_relay.config import Config, Roles
      settings = Config(plan="p", max_rounds=3, timeout_minutes=30, branch_prefix="r/",
                         agents={}, status_map={}, roles=Roles("codex", "claude"))
      failover.write_override(tmp_path, "implementer",
          failover.ActiveOverride("antigravity", "codex", "rate-limit", "2026-01-01T00:00:00"))
      assert failover.effective_agent(tmp_path, settings, "implementer") == "antigravity"

  def test_clear_overrides_one_role(tmp_path):
      failover.write_override(tmp_path, "implementer", failover.ActiveOverride("a", "b", "rate-limit", "t"))
      failover.write_override(tmp_path, "reviewer", failover.ActiveOverride("c", "d", "auth", "t"))
      assert failover.clear_overrides(tmp_path, "implementer") == 1
      remaining = failover.read_overrides(tmp_path)
      assert set(remaining) == {"reviewer"}

  def test_clear_overrides_all(tmp_path):
      failover.write_override(tmp_path, "implementer", failover.ActiveOverride("a", "b", "rate-limit", "t"))
      assert failover.clear_overrides(tmp_path) == 1
      assert failover.read_overrides(tmp_path) == {}
      assert failover.clear_overrides(tmp_path) == 0

  def test_still_logged_in_true_for_a_generic_adapter():
      from whyline_relay.adapters.generic import ADAPTER
      assert failover.still_logged_in(ADAPTER) is True

  def test_still_logged_in_reads_the_login_check_exit_code():
      ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
      bad = lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "")
      assert failover.still_logged_in(codex_adapter.ADAPTER, runner=ok) is True
      assert failover.still_logged_in(codex_adapter.ADAPTER, runner=bad) is False

  def test_still_logged_in_never_guesses_logged_out_on_a_broken_check():
      def explode(*a, **k): raise OSError("no such program")
      def hang(*a, **k): raise subprocess.TimeoutExpired(cmd="x", timeout=20)
      assert failover.still_logged_in(codex_adapter.ADAPTER, runner=explode) is True
      assert failover.still_logged_in(codex_adapter.ADAPTER, runner=hang) is True

  def test_failover_reason_prefers_rate_limit_over_auth():
      bad = lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "")
      assert failover.failover_reason(codex_adapter.ADAPTER, "you hit your usage limit", ["codex"], runner=bad) == "rate-limit"

  def test_failover_reason_is_none_when_all_clear():
      ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
      assert failover.failover_reason(codex_adapter.ADAPTER, "ordinary output", ["codex"], runner=ok) is None

  def test_failover_reason_generic_agent_never_reports_auth():
      from whyline_relay.adapters.generic import ADAPTER
      assert failover.failover_reason(ADAPTER, "totally ordinary text", ["aider"]) is None

  def test_failover_reason_never_login_checks_a_stand_in_command():
      # command[0] is not literally "codex", so the auth check must never run, matching
      # preflight._logins's own rule for the same situation.
      def explode(*a, **k): raise AssertionError("must not run a login check on a stand-in")
      assert failover.failover_reason(codex_adapter.ADAPTER, "ordinary output", ["python3", "fake.py"], runner=explode) is None

  def test_pause_message_matches_0_2_3_exactly_with_no_override():
      assert failover.pause_message("codex", "implementer", "rate-limit", None) == (
          "codex hit a usage or rate limit; try again when it resets"
      )

  def test_pause_message_for_auth_with_no_override():
      assert failover.pause_message("claude", "reviewer", "auth", None) == (
          "claude is no longer logged in; try again once you've signed back in"
      )

  def test_pause_message_when_the_backup_also_failed():
      override = failover.ActiveOverride("antigravity", "codex", "rate-limit", "t")
      message = failover.pause_message("antigravity", "implementer", "rate-limit", override)
      assert "backup for implementer" in message
      assert "codex was already out" in message
      assert "hit a usage or rate limit" in message

  def test_active_roles_json_is_locally_excluded(tmp_path):
      from whyline_relay import gitcheck
      assert ".whyline/relay/active-roles.json" in gitcheck.RELAY_IGNORE
  ```

  Run `uv run --frozen pytest -q`: all existing tests still pass, unedited, plus these new ones. Change nothing else.

- [ ] FBO-3: the loop switches to a backup instead of pausing
  Rules for every task: run the tests with `uv run --frozen pytest -q` (there is no network). Add no dependencies and do not touch `pyproject.toml`, `uv.lock` or the version. With no `[roles.backup]` in a config, every existing test, unedited, must still pass. Never pass or write a permission-bypass flag, never run `git push`, and never write a handoff on an agent's behalf.

  Make `loop.py` read a role's agent through `failover.effective_agent`, and switch to a configured backup instead of pausing when `failover.failover_reason` finds one. Fix `cli.py`'s `--dry-run` to use the same resolver. Change nothing else.

  **`loop.py`:**
  - Import `failover`; import `datetime` from `datetime` (for the override's `since` field).
  - `_run_agent`, `run_task`, `_run_task`, `run_plan`, `_run_plan` each gain one new keyword-only parameter: `runner: failover.Runner = subprocess.run` (import `subprocess` at module level), threaded through exactly like `echo` already is: `run_plan` passes it to `_run_plan`, which passes it to `run_task`, which passes it to `_run_task`. `_run_agent` does not need it (nothing in `_run_agent` calls `failover_reason`); only `_run_task`'s `NO_HANDOFF` branch does, so `_run_task` is the only function whose *body* uses the new parameter, but every function between the public entry points and it must still accept and forward it.
  - In `_run_task`, replace the two lines `implementer = settings.roles.implementer` and `reviewer = settings.roles.reviewer` (both before the `while True:` loop and inside it, everywhere they are read) so that the agent for a role is always `failover.effective_agent(root, settings, role)`, resolved fresh at the point it's needed — specifically: the `whylinecmd.claim(root, task.task_id, implementer, "implementer")` call, the `resume` branch's `routing.decide(..., implementer=implementer, reviewer=reviewer)` call, and inside the `while True:` loop where `agent = implementer if role == "implementer" else reviewer` is computed and where `routing.decide` is called again. Concretely: replace the two variables computed once before the loop with two computed fresh each time they're needed via `failover.effective_agent(root, settings, "implementer")` / `"reviewer"`. The simplest correct change: compute `implementer` and `reviewer` this way at the **top of the `while True:` block**, on every iteration, instead of once before it; also compute them this way for the one use before the loop (the `resume` branch and the initial `claim` call).
  - Remove `_hit_a_limit` entirely (its job moves into `failover.failover_reason`).
  - Replace the `NO_HANDOFF` branch:

    ```python
    if move == routing.NO_HANDOFF:
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        adapter = config.adapter_for(settings, agent)
        reason = failover.failover_reason(adapter, text, settings.agents[agent], runner=runner)
        if reason is not None:
            backup = settings.backups.get(role)
            if backup is not None and backup != agent:
                verb, _ = failover.REASON_TEXT[reason]
                failover.write_override(
                    root, role,
                    failover.ActiveOverride(
                        agent=backup, backup_for=agent, reason=reason,
                        since=datetime.now().astimezone().isoformat(),
                    ),
                )
                if echo:
                    agents.print_status(
                        f"==> relay: {role} switched from {agent} to {backup} "
                        f"({agent} {verb})"
                    )
                continue
            existing = failover.read_overrides(root).get(role)
            raise Paused(failover.pause_message(agent, role, reason, existing), target)
        raise Paused(
            f"{agent} exited without handing off"
            f"{_no_handoff_detail(target, adapter)}; nothing was routed",
            target,
        )
    ```

    (`continue` re-enters the `while True:` loop on the same `next_move`/`round_`, so the next iteration recomputes `agent` — via the new top-of-loop resolution — as the backup, and the round is retried with it. This is why the round counter must not be touched here.)

  **`cli.py`:** in `cmd_start`'s `--dry-run` branch, replace `settings.roles.implementer` (both the `implementer=` keyword to `prompts.render` and the `settings.agents[settings.roles.implementer]` lookup) with `failover.effective_agent(root, settings, "implementer")`, imported the same way other relay modules are.

  **Tests first**, new `tests/test_loop_failover.py`, using `fake_role_agent.py` and a new tiny fake that can report a rate-limit or a bad login check on demand:

  ```python
  import json, subprocess, sys
  from dataclasses import replace
  from pathlib import Path
  import pytest
  from whyline_relay import config, failover, loop, plan

  FAKE = str(Path(__file__).parent / "fake_role_agent.py")
  TASK = plan.Task(task_id="T-1", text="T-1: Work", checked=False, line_index=0)

  @pytest.fixture
  def repo(tmp_path, monkeypatch):
      def git(*a): subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
      git("init", "-b", "relay/plan"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
      (tmp_path / "README.md").write_text("x\n"); git("add", "-A"); git("commit", "-m", "initial")
      (tmp_path / ".whyline").mkdir()
      monkeypatch.setattr(loop.whylinecmd, "sync", lambda *a, **k: "PACKET")
      return tmp_path

  RATE_LIMITED = '''#!/usr/bin/env python3
  import sys
  print("You have exceeded your usage limit.")
  sys.exit(1)
  '''

  def settings_with_backup(root, implementer_command, backup_agent, backup_command, backups):
      base = config.load(root)
      return config.Config(
          plan=base.plan, max_rounds=base.max_rounds, timeout_minutes=base.timeout_minutes,
          branch_prefix=base.branch_prefix,
          agents={"codex": implementer_command, "claude": [sys.executable, FAKE, str(root), "claude", "claude", "approved", "yes"], backup_agent: backup_command},
          status_map=base.status_map, backups=backups,
      )

  def test_a_rate_limited_implementer_switches_to_its_backup_and_the_task_completes(repo, tmp_path):
      limited = tmp_path / "limited.py"; limited.write_text(RATE_LIMITED)
      settings = settings_with_backup(repo, [sys.executable, str(limited)], "aider",
          [sys.executable, FAKE, str(repo), "aider", "claude", "ready-for-review", "no"], {"implementer": "aider"})
      base = loop.gitcheck.head_commit(repo)
      outcome = loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
      assert outcome.committed
      assert failover.read_overrides(repo)["implementer"].agent == "aider"
      assert failover.read_overrides(repo)["implementer"].reason == "rate-limit"

  def test_an_unauthenticated_implementer_switches_to_its_backup(repo, tmp_path, monkeypatch):
      # Exercising a real "codex login status" failure would need a binary literally named
      # "codex" on PATH (failover_reason's guard, FBO-2, refuses to check anything else) —
      # so this tests loop.py's handling of an "auth" verdict directly, the same way FBO-2's own
      # tests exercise failover_reason's detection logic directly. The real detection is FBO-2's job.
      silent = tmp_path / "silent.py"; silent.write_text("import sys
sys.exit(0)
")
      settings = settings_with_backup(repo, [sys.executable, str(silent)], "aider",
          [sys.executable, FAKE, str(repo), "aider", "claude", "ready-for-review", "no"], {"implementer": "aider"})
      monkeypatch.setattr(
          loop.failover, "failover_reason",
          lambda adapter, text, command, runner=None: "auth",
      )
      base = loop.gitcheck.head_commit(repo)
      outcome = loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
      assert outcome.committed
      assert failover.read_overrides(repo)["implementer"].reason == "auth"

  def test_a_switch_does_not_consume_a_review_round(repo, tmp_path):
      limited = tmp_path / "limited.py"; limited.write_text(RATE_LIMITED)
      settings = settings_with_backup(repo, [sys.executable, str(limited)], "aider",
          [sys.executable, FAKE, str(repo), "aider", "claude", "ready-for-review", "no"], {"implementer": "aider"})
      settings = replace(settings, max_rounds=1)
      base = loop.gitcheck.head_commit(repo)
      outcome = loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
      assert outcome.committed and outcome.rounds == 1

  def test_no_backup_configured_pauses_exactly_as_0_2_3(repo, tmp_path):
      limited = tmp_path / "limited.py"; limited.write_text(RATE_LIMITED)
      base_settings = config.load(repo)
      settings = replace(base_settings, agents={**base_settings.agents, "codex": [sys.executable, str(limited)]})
      base = loop.gitcheck.head_commit(repo)
      with pytest.raises(loop.Paused) as raised:
          loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
      assert raised.value.reason == "codex hit a usage or rate limit; try again when it resets"

  def test_the_backup_also_failing_pauses_and_names_both(repo, tmp_path):
      limited = tmp_path / "limited.py"; limited.write_text(RATE_LIMITED)
      settings = settings_with_backup(repo, [sys.executable, str(limited)], "aider",
          [sys.executable, str(limited)], {"implementer": "aider"})
      base = loop.gitcheck.head_commit(repo)
      with pytest.raises(loop.Paused) as raised:
          loop.run_task(repo, settings, TASK, base_commit=base, echo=False)
      assert "backup for implementer" in raised.value.reason
      assert "codex was already out" in raised.value.reason

  def test_dry_run_shows_the_effective_backup_agent(tmp_path, monkeypatch, capsys):
      from whyline_relay import cli
      (tmp_path / ".whyline").mkdir()
      (tmp_path / "plan.md").write_text("- [ ] T-1: x\n  y\n")
      monkeypatch.setattr(cli.whylinecmd, "sync", lambda root, task, runner=None: "PACKET")
      import json as _json
      relay = tmp_path / ".whyline" / "relay"; relay.mkdir()
      (relay / "config.toml").write_text('[roles.backup]\nimplementer = "claude"\n')
      failover.write_override(tmp_path, "implementer", failover.ActiveOverride("claude", "codex", "rate-limit", "t"))
      code = cli.main(["start", "--repo", str(tmp_path), "--dry-run"])
      assert code == 0
      assert "claude" in capsys.readouterr().out.split("Would run:")[1].splitlines()[0]
  ```

  Run `uv run --frozen pytest -q`: all existing tests still pass, unedited (with no `[roles.backup]` configured, `failover.effective_agent` returns exactly `settings.roles.*`, so nothing observable changes), plus these new ones. Change nothing else.

- [ ] FBO-4: preflight checks a backup, and `roles status`/`roles reset`
  Rules for every task: run the tests with `uv run --frozen pytest -q` (there is no network). Add no dependencies and do not touch `pyproject.toml`, `uv.lock` or the version. With no `[roles.backup]` in a config, every existing test, unedited, must still pass. Never pass or write a permission-bypass flag, never run `git push`, and never write a handoff on an agent's behalf.

  Make `doctor`/`start`/`resume` check a configured backup the same way they check a primary, labelled as a backup. Add `whyline-relay roles status` and `whyline-relay roles reset [ROLE]`.

  **`preflight.py`:** `_agents_in_use(settings)` currently returns `{name: command}` for the two role agents. Change its return type to `dict[str, tuple[list[str], str | None]]`, mapping an agent name to `(command, backup_for)`, where `backup_for` is `None` for a primary and the role name (`"implementer"`/`"reviewer"`) when the entry came from `settings.backups`. Build it as: for each of `("implementer", "reviewer")`, add the primary (`backup_for=None`) if not already present; then, for each `(role, name)` in `settings.backups.items()`, add it (`backup_for=role`) if not already present under that name. (An agent that is both someone's primary and someone else's backup keeps its first-seen `backup_for`, i.e. `None` — it is already fully checked either way.) Update every caller inside this module (`_relay_setup`, `_programs`, `_logins`) to iterate `.items()` and unpack `(command, backup_for)`, using `command` exactly as before. In `_logins`, when a login check fails and `backup_for is not None`, the message names it: `f"{program} (backup for {backup_for}) is not logged in"` instead of `f"{program} is not logged in"`; same pattern for the "not on PATH" message in `_programs`. `_role_checks` and `_relay_setup`'s `--settings` scan are unaffected beyond the unpacking change — they don't need to know which agents are backups.

  **Create** `src/whyline_relay/roles.py`:

  ```python
  """Inspecting and clearing a sticky backup switch."""

  from __future__ import annotations

  from pathlib import Path

  from whyline_relay import config, failover


  def status(root: Path, settings: config.Config) -> str:
      lines = []
      for role in ("implementer", "reviewer"):
          configured = getattr(settings.roles, role)
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
  ```

  **`cli.py`:** add a `roles` subparser with its own nested subparsers, `status` and `reset`:

  ```python
  roles_parser = subparsers.add_parser("roles", help="Inspect or reset a backup switch")
  roles_parser.add_argument(
      "--repo", default=".", help="Use this repository root (default: current directory)."
  )
  roles_sub = roles_parser.add_subparsers(dest="roles_command", required=True)
  roles_sub.add_parser("status", help="Show each role's configured and active agent")
  roles_reset = roles_sub.add_parser("reset", help="Clear a sticky backup switch")
  roles_reset.add_argument(
      "role", nargs="?", default=None, choices=("implementer", "reviewer"),
      help="Reset only this role (default: every role).",
  )
  ```

  Add `cmd_roles(args) -> int`:

  ```python
  def cmd_roles(args: argparse.Namespace) -> int:
      root = Path(args.repo).resolve()
      settings = config.load(root)
      if args.roles_command == "status":
          print(roles.status(root, settings))
      else:
          print(roles.reset(root, args.role))
      return EXIT_OK
  ```

  Import `roles` alongside the other relay modules at the top of `cli.py`, and add `"roles": cmd_roles` to the `commands` dict in `main`.

  **Tests first:**

  In `tests/test_preflight.py`: a config with `[roles.backup] implementer = "aider"` (a configured generic agent whose command is a missing binary) reports a `FAIL` naming it `"aider (backup for implementer) is not on PATH"`; with a stand-in `codex`/`claude` pair where the backup binary is a script that fails a stubbed login runner returning exit 1, the message is `"... (backup for implementer) is not logged in"`; a default config with no backups produces the identical list of `(status, message)` pairs as relay 0.2.3 (captured as a literal list in the test, as the ADPT-7 preflight test already does).

  New `tests/test_roles_cli.py`:

  ```python
  from pathlib import Path
  from whyline_relay import cli, config, failover

  def make_repo(tmp_path: Path) -> Path:
      (tmp_path / ".whyline" / "relay").mkdir(parents=True)
      (tmp_path / ".whyline" / "relay" / "config.toml").write_text("")
      return tmp_path

  def test_status_with_no_override_shows_only_configured_agents(tmp_path, capsys):
      repo = make_repo(tmp_path)
      assert cli.main(["roles", "status", "--repo", str(repo)]) == 0
      out = capsys.readouterr().out
      assert "implementer: codex" in out and "reviewer: claude" in out
      assert "currently" not in out

  def test_status_shows_an_active_override(tmp_path, capsys):
      repo = make_repo(tmp_path)
      failover.write_override(repo, "implementer",
          failover.ActiveOverride("antigravity", "codex", "rate-limit", "2026-01-01T00:00:00"))
      cli.main(["roles", "status", "--repo", str(repo)])
      out = capsys.readouterr().out
      assert "currently antigravity" in out and "rate-limit" in out

  def test_reset_one_role(tmp_path, capsys):
      repo = make_repo(tmp_path)
      failover.write_override(repo, "implementer", failover.ActiveOverride("a", "b", "rate-limit", "t"))
      assert cli.main(["roles", "reset", "implementer", "--repo", str(repo)]) == 0
      assert failover.read_overrides(repo) == {}
      assert "reset" in capsys.readouterr().out.lower()

  def test_reset_all(tmp_path, capsys):
      repo = make_repo(tmp_path)
      failover.write_override(repo, "implementer", failover.ActiveOverride("a", "b", "rate-limit", "t"))
      failover.write_override(repo, "reviewer", failover.ActiveOverride("c", "d", "auth", "t"))
      assert cli.main(["roles", "reset", "--repo", str(repo)]) == 0
      assert failover.read_overrides(repo) == {}

  def test_reset_with_nothing_to_reset_says_so(tmp_path, capsys):
      repo = make_repo(tmp_path)
      cli.main(["roles", "reset", "--repo", str(repo)])
      assert "nothing to reset" in capsys.readouterr().out.lower()
  ```

  Run `uv run --frozen pytest -q`: all existing tests still pass unedited, plus these new ones. Change nothing else.

---

## Self-review against the spec

**Spec coverage.** 5.1 configuration: FBO-1. 5.2 preflight checking a backup: FBO-4. 5.3 the two triggers: FBO-2 (`failover_reason`, reusing `agents.rate_limited` and `login_argv`, never text-guessing auth). 5.4 switching, persistence, and the resolver threaded everywhere: FBO-2 (persistence) and FBO-3 (the loop and dry-run). 5.5 `roles status`/`roles reset`: FBO-4. Decisions D1-D6 are each reflected: D1/D2 in `failover.py`'s shape (one override, no chain, no auto-revert path exists at all), D3 in the `continue`-not-`Paused` switch, D4/D5 in `failover_reason`, D6 in FBO-4's preflight change.

**Placeholders.** None. Every message, field name, and function signature used across tasks is spelled out where it is first introduced and used identically afterward: `ActiveOverride(agent, backup_for, reason, since)`, `failover.effective_agent`, `failover.failover_reason`, `failover.pause_message`, `failover.REASON_TEXT`, `roles.status`, `roles.reset`.

**Type/name consistency.** `Config.backups: dict[str, str]` (FBO-1) is read by `failover.py` (FBO-2, via `settings.backups.get(role)` inside `loop.py`) and by `roles.py` (FBO-4, via `getattr(settings.roles, role)` for the configured half and `failover.read_overrides` for the active half) with the same shape throughout.

**Known soft spot to watch in review.** FBO-3's "resolve `implementer`/`reviewer` fresh at the top of the loop instead of once before it" is described in prose rather than as a literal diff, because the exact surrounding lines depend on how the implementer chooses to restructure the existing `while True:` block; the tests (especially `test_a_rate_limited_implementer_switches_to_its_backup_and_the_task_completes`, which fails if the resolver is only read once) are the actual contract, not the prose.
