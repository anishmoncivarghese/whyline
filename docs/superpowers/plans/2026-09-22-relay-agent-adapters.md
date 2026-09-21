# whyline-relay agent adapters (relay 0.2.2) Implementation Plan

> **For agentic workers:** this plan is run by whyline-relay itself, on its own repository: Codex implements each task, Claude reviews and commits it. The tasks in "The tasks" are the run's `plan.md`, copied verbatim into a sandbox clone. Each task is handed to a fresh agent with no memory of the others, so each one stands alone. Steps use `- [ ]` checkboxes only where the relay reads them (one per task).

**Goal:** Let any built-in agent (`codex`, `claude`) or an explicitly configured generic agent fill either role, the implementer or the reviewer, chosen in `config.toml`, with no change for existing configurations.

**Architecture:** A small `adapters` package holds what is specific to one tool (default command, login check, permission files, how to read a denial, what the relay manages). `config.py` resolves `[roles]` to agent names and validates them; `routing`, `loop`, `preflight`, `init` and the CLI read the roles instead of the constants `"codex"` and `"claude"`. Everything agent-independent (the loop, HEAD check, commit verification, timeouts, tick commit) is untouched.

**Tech Stack:** Python 3.11+, standard library only, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-22-relay-agent-adapters-design.md`. Read section 9 first: it corrects sections 1 to 7 where they differ, and this plan implements the corrected design.

## Global Constraints

Every task's requirements include these.

- The relay never passes a permission-bypass flag and never runs `git push`. It never widens an agent's permissions.
- Existing configurations need no migration. Default roles are `implementer = "codex"`, `reviewer = "claude"`, and with them every command, prompt, log name, message and file written is what relay 0.2.1 produced.
- Status strings (`ready-for-review`, `changes-requested`, `approved`, `blocked`, `assigned`) do not change.
- An agent named `codex` or `claude` uses its built-in adapter. Any other agent name must set `adapter = "generic"` and a `command`, or configuration loading fails. There is no silent fallback.
- Handoffs and notes record the agent's own name as the actor (`--from gemini --to claude`).
- The same agent may fill both roles, with a visible warning.
- The relay never writes handoffs on an agent's behalf.
- No new dependencies. Do not touch `pyproject.toml`, `uv.lock` or the version. The sandbox has no network: run tests with `uv run --frozen pytest -q`.
- `cli.main(argv=None, prog="whyline-relay")` keeps its signature. No hard-coded command name `whyline-relay` in `src/` (use `invocation.command`).
- Python floor is 3.11.

## Corrections to the spec that this plan builds in

See spec section 9 (C1 to C14). The ones a task implementer must know: the running marker rejects any agent but `codex` and `claude` (C1, task ADPT-4); bypass flags live only in `adapters/bypass.py` and the loop refuses them too (C2 and C3, ADPT-9); the from-actor check needs a fixture edit (C4, ADPT-6); two existing prompt assertions change (C5, ADPT-3); preflight checks only agents in use (C6, ADPT-7); default output stays byte-identical (C11).

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/whyline_relay/adapters/__init__.py` (new) | registry: `BUILTIN`, `get()`, `describe()` | 1, 7 |
| `src/whyline_relay/adapters/base.py` (new) | `Adapter`, `Manages`, shared `last_line_detail()` | 1 |
| `src/whyline_relay/adapters/codex.py`, `claude.py`, `generic.py` (new) | one adapter each; `claude.py` also holds the allowlist moved out of `init.py` | 1 |
| `src/whyline_relay/adapters/bypass.py` (new) | the only file that names refused flags; `find()` | 9 |
| `src/whyline_relay/config.py` | `Roles`, `[roles]` parsing, generic-agent validation, `adapter_for()` | 1 |
| `src/whyline_relay/routing.py`, `handoff.py` | role-aware `decide`; `Handoff.from_actor` | 2 |
| `src/whyline_relay/prompts.py` | `{implementer}` and `{reviewer}` placeholders | 3 |
| `src/whyline_relay/running.py`, `cli.py` (status, dry-run) | marker accepts any agent, gains `role` | 4 |
| `src/whyline_relay/loop.py` | roles, adapters, log names, HEAD check by role, from-actor check, bypass refusal | 5, 6, 9 |
| `src/whyline_relay/preflight.py` | in-use agents only, adapter logins, role warnings, templates, bypass | 7, 9 |
| `src/whyline_relay/init.py`, `cli.py` (init) | `--implementer`, `--reviewer`, files only for agents in use | 8 |
| `tests/` | new test files per task; `tests/fake_role_agent.py` (new helper, ADPT-5) | all |

## Permitted edits to existing tests

The 237 existing tests must pass unchanged **except** these, each named in its task. Any other edit to an existing test means the change is not backward compatible: stop and say so in the handoff.

| Test | Edit | Task |
|---|---|---|
| `tests/test_prompts.py::test_implement_template_names_the_exact_handoff_command` (line 39) | assert the `{implementer}`/`{reviewer}` form | ADPT-3 |
| `tests/test_prompts.py`, the assertion `"--to codex --status changes-requested" in prompts.REVIEW` (line 46) | assert `"--to {implementer} --status changes-requested"` | ADPT-3 |
| `tests/fake_agent.py`, `"from_actor": "fake"` | `os.environ.get("FAKE_ACTOR", "")` | ADPT-6 |
| `tests/test_no_bypass.py::test_no_source_file_mentions_a_bypass_flag` | exempt `adapters/bypass.py`; add `bypassPermissions` | ADPT-9 |

## Not in this plan

Pipeline stages, a planner stage, quota fallback, and the Gemini adapter. The Gemini adapter needs a real signed-in run first (spec 5.6, the spike) and gets its own plan. When it arrives it adds: `gemini` in `BUILTIN`, its flags in `bypass.py`, a policy file in `permission_files`, a `--policy` existence check next to the `--settings` one, its quota wording, and a `quota_markers` field on `Adapter`. Nothing in this plan should make that harder, and nothing here should guess at it.

## How this is run and checked

1. Independent acceptance tests for the new behaviour are written first, outside the run, from this plan's requirements. They must fail on 0.2.1 and be validated against a reference.
2. A sandbox clone of the relay (`~/relay-test/relay-022`, remotes removed) holds the tasks below as `plan.md`. `whyline-relay start` runs them: Codex, then Claude, per task.
3. After the run: the 237-test suite (with the four edits above), the 97 existing acceptance tests **unchanged**, the new acceptance tests, tripwires on `osascript` and real agent binaries, and a real `doctor` and `start --dry-run` against stand-ins.
4. Cherry-pick into the real repository, release notes and README (written by hand from measured behaviour, not by the run), pre-flight, then **stop for an explicit go** before pushing or tagging `v0.2.2`.

## Release

Relay **0.2.2**. whyline 0.3.0 pins `whyline-relay>=0.2.1,<0.3`, which already admits it, so no whyline release is needed. `whyline[relay]` users get it on upgrade.

---

## The tasks

Run order matters: each task builds on the commits before it. Golden files in tasks 3 and 8 are captured from the **unmodified** code before any edit to it.

- [ ] ADPT-1: adapter registry and role-aware configuration
  Add the `adapters` package and make `config.py` understand `[roles]` and generic agents. Change nothing else except moving the allowlist code out of `init.py` as described.

  **Create** `src/whyline_relay/adapters/base.py`:

  ```python
  @dataclass(frozen=True)
  class Manages:
      permissions: bool
      login: bool
      denials: bool

  @dataclass(frozen=True)
  class Adapter:
      name: str                                    # "codex" | "claude" | "generic"
      default_command: tuple[str, ...] | None      # None: the command must come from config
      binary: str | None                           # the program the login check applies to
      login_argv: tuple[str, ...] | None           # e.g. ("codex", "login", "status")
      login_fix: str | None                        # e.g. "codex login"
      permission_files: Callable[[str], dict[str, str]]   # stack -> {path under .whyline/relay/: text}
      diagnose: Callable[[str], str]               # a run's log text -> "" or "; <detail>"
      manages: Manages

  def last_line_detail(text: str) -> str:
      """'; its last output was: "<last non-blank line, printable characters only, at most 160>"' or ''."""
  ```

  `last_line_detail` is the last-line half of `loop._no_handoff_detail` moved here unchanged (same filter, same 160 limit, same wording). Do not remove `_no_handoff_detail` from `loop.py` in this task.

  **Create** the three adapters:
  - `codex.py`: `default_command = ("codex", "exec", "-s", "workspace-write", "--color", "never")`, `binary = "codex"`, `login_argv = ("codex", "login", "status")`, `login_fix = "codex login"`, `permission_files = lambda stack: {}`, `diagnose = last_line_detail`, `Manages(True, True, True)`.
  - `claude.py`: `default_command` is exactly the list in `config.DEFAULTS["agents"]["claude"]` today (`claude -p --permission-mode acceptEdits --output-format json --settings .whyline/relay/claude-settings.json`), `binary = "claude"`, `login_argv = ("claude", "auth", "status")`, `login_fix = "claude auth login"`, `Manages(True, True, True)`. Move `BASE_ALLOW`, `DENY`, `PRESETS` and `allowlist(stack)` here from `init.py`, unchanged. `permission_files(stack)` returns `{"claude-settings.json": json.dumps(allowlist(stack), indent=2) + "\n"}`. `diagnose(text)`: the denial half of `loop._no_handoff_detail` (parse the last line as JSON, list `permission_denials` commands, return `"; it was denied permission to run: <cmds>. Check .whyline/relay/claude-settings.json"` when there are any), else `last_line_detail(text)`. Same 60-character clip per command as today.
  - `generic.py`: `default_command = None`, `binary = None`, `login_argv = None`, `login_fix = None`, `permission_files = lambda stack: {}`, `diagnose = last_line_detail`, `Manages(False, False, False)`.

  **Create** `adapters/__init__.py`: `BUILTIN: dict[str, Adapter]` with keys `"codex"` and `"claude"`; `GENERIC`; `get(name: str) -> Adapter` returning a built-in or `GENERIC` for `"generic"` and raising `KeyError(name)` otherwise.

  **Edit `init.py`:** replace the moved definitions with `from whyline_relay.adapters.claude import BASE_ALLOW, DENY, PRESETS, allowlist` so `init.allowlist`, `init.BASE_ALLOW`, `init.DENY` and `init.PRESETS` still resolve. `detect_stack` stays. Behaviour is identical.

  **Edit `config.py`:**
  - `DEFAULTS["agents"]` is built from the adapters: `{name: list(a.default_command) for name, a in adapters.BUILTIN.items()}`. It must equal what it is today, element for element.
  - `@dataclass(frozen=True) class Roles: implementer: str = "codex"; reviewer: str = "claude"`.
  - `Config` gains two fields **at the end, with defaults**: `roles: Roles = field(default_factory=Roles)` and `adapters: dict[str, str] = field(default_factory=dict)` (agent name -> adapter name, filled only for generic agents). Tests build `Config(...)` by hand without them.
  - `def adapter_for(settings: Config, agent: str) -> adapters.Adapter`: `adapters.get(settings.adapters.get(agent, agent))`.
  - `load()` additionally: (a) reads `[roles]`; keys are `implementer` and `reviewer`, both optional, strings; (b) for each `[agents.NAME]` table: a built-in name may override `command` and must not set `adapter`; any other name must have `adapter = "generic"` and a non-empty list `command`, and is recorded in `adapters`; (c) each role must name a built-in agent or a configured generic one. Every failure raises `ConfigError` with these exact messages:
    - `[roles] has an unknown key 'x' (use implementer or reviewer)`
    - `[roles] implementer must be a string`
    - `agent 'aider' is not built in: set adapter = "generic" and a command under [agents.aider]`
    - `agent 'codex' is built in and cannot set adapter`
    - `[agents.aider] adapter must be "generic", not 'x'`
    - `[agents.aider] needs a non-empty command`
    - `role 'implementer' names 'gemini', which is not a built-in agent (claude, codex) or a configured generic agent`
    (the built-in list in the last message is sorted.)

  **Tests first (they must fail before the code).** New `tests/test_adapters.py` and additions to `tests/test_config.py`:

  ```python
  def test_defaults_are_the_0_2_1_commands():
      assert config.DEFAULTS["agents"]["codex"] == ["codex", "exec", "-s", "workspace-write", "--color", "never"]
      assert config.DEFAULTS["agents"]["claude"] == ["claude", "-p", "--permission-mode", "acceptEdits",
          "--output-format", "json", "--settings", ".whyline/relay/claude-settings.json"]

  def test_no_config_file_means_the_default_roles(tmp_path):
      assert config.load(tmp_path).roles == config.Roles("codex", "claude")

  def test_a_generic_agent_needs_adapter_and_command(tmp_path):
      write(tmp_path, '[agents.aider]\ncommand = ["aider", "--message"]\n')
      with pytest.raises(config.ConfigError, match=r"agent 'aider' is not built in"):
          config.load(tmp_path)

  def test_roles_may_name_a_configured_generic_agent(tmp_path):
      write(tmp_path, '[roles]\nreviewer = "aider"\n[agents.aider]\nadapter = "generic"\ncommand = ["aider", "--message"]\n')
      loaded = config.load(tmp_path)
      assert loaded.roles == config.Roles("codex", "aider")
      assert loaded.agents["aider"] == ["aider", "--message"]
      assert config.adapter_for(loaded, "aider").name == "generic"
      assert config.adapter_for(loaded, "codex").name == "codex"
  ```

  Also test each error message above once (`pytest.raises(..., match=re.escape(...))`), that `Config(...)` built by hand without `roles` and `adapters` still works, that the claude adapter's `permission_files("python")` equals `{"claude-settings.json": json.dumps(init.allowlist("python"), indent=2) + "\n"}`, that `claude.diagnose` on the `denied` output shape (last line `{"type": "result", "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}]}`) names `git commit -m x` and `claude-settings.json`, and that `codex.diagnose("a\nb\n")` returns `'; its last output was: "b"'`.

  Run `uv run --frozen pytest -q`: all 237 existing tests still pass, unedited. Change nothing else.

- [ ] ADPT-2: routing and the handoff record know the roles
  Make `routing.decide` take the role names, and make `handoff.Handoff` carry who sent the record. Change nothing else.

  **`routing.py`:** keep the constants `IMPLEMENTER = "codex"` and `REVIEWER = "claude"` as the defaults. New signature:

  ```python
  def decide(record, previous_id, status_map, implementer: str = IMPLEMENTER, reviewer: str = REVIEWER) -> str:
  ```

  The body compares `record.to_actor` with `reviewer` and `implementer` instead of the constants. Everything else is identical. When `implementer == reviewer` the routing is by status alone, which already works: `ready-for-review` goes to the reviewer, `changes-requested` and `assigned` to the implementer.

  **`handoff.py`:** add `from_actor: str = ""` as the **last** field of `Handoff`, and fill it in `read()` with `_text(record, "from_actor")` (so a missing or non-string value is `""`). Existing positional and keyword construction keeps working.

  **Tests first:** in `tests/test_routing.py` and `tests/test_handoff.py`:

  ```python
  def test_roles_other_than_the_defaults_route_by_name():
      ready = record(to_actor="gemini", status="ready-for-review")
      assert routing.decide(ready, "e1", STATUS, implementer="aider", reviewer="gemini") == routing.REVIEW
      back = record(to_actor="aider", status="changes-requested")
      assert routing.decide(back, "e1", STATUS, implementer="aider", reviewer="gemini") == routing.IMPLEMENT

  def test_the_default_reviewer_name_is_not_special_once_roles_change():
      ready = record(to_actor="claude", status="ready-for-review")
      assert routing.decide(ready, "e1", STATUS, implementer="aider", reviewer="gemini") == routing.UNKNOWN

  def test_one_agent_in_both_roles_routes_by_status():
      solo = dict(implementer="claude", reviewer="claude")
      assert routing.decide(record(to_actor="claude", status="ready-for-review"), "e1", STATUS, **solo) == routing.REVIEW
      assert routing.decide(record(to_actor="claude", status="changes-requested"), "e1", STATUS, **solo) == routing.IMPLEMENT
  ```

  and for `read`: `from_actor` is returned when present, `""` when the key is missing, `""` when it is not a string. Existing tests unchanged. Change nothing else.

- [ ] ADPT-3: prompt templates use the role names
  Replace the literal agent names in the two built-in templates with placeholders, and prove the default output did not change. Change nothing else.

  **Step 1, before editing `prompts.py`:** capture golden files from the unmodified code. Run exactly:

  ```bash
  mkdir -p tests/golden && uv run --frozen python - <<'EOF'
  from whyline_relay import prompts
  kw = dict(task_id="T-1", task_text="T-1: Do it\nwith detail", sync_packet="PACKET", round_=2, review_feedback="fix the edge")
  open("tests/golden/prompt_implement_0.2.1.txt", "w", encoding="utf-8").write(prompts.render(prompts.IMPLEMENT, **kw))
  open("tests/golden/prompt_review_0.2.1.txt", "w", encoding="utf-8").write(prompts.render(prompts.REVIEW, **kw))
  EOF
  ```

  Commit-ready: these two files are part of the task.

  **Step 2, `prompts.py`:**
  - `PLACEHOLDERS` gains `"implementer"` and `"reviewer"`.
  - In `IMPLEMENT`: `--actor codex` becomes `--actor {implementer}`; `--from codex --to claude` becomes `--from {implementer} --to {reviewer}`.
  - In `REVIEW`: every `--actor claude` becomes `--actor {reviewer}`; both `--from claude --to claude` become `--from {reviewer} --to {reviewer}`; `--from claude --to codex` becomes `--from {reviewer} --to {implementer}`. No other word changes.
  - `render(template, *, task_id, task_text, sync_packet, round_, review_feedback, implementer: str = "codex", reviewer: str = "claude")`. Substitute `{implementer}` and `{reviewer}` **first**, on the template alone, before any user content is inserted, so a task text that contains the text `{implementer}` is left exactly as written. The other five placeholders behave as today.
  - `init.py` keeps writing `prompts.IMPLEMENT` and `prompts.REVIEW` verbatim (placeholders included). Do not change `init.py` in this task.

  **Step 3, tests.** New `tests/test_prompts_roles.py`:

  ```python
  GOLDEN = Path(__file__).parent / "golden"
  KW = dict(task_id="T-1", task_text="T-1: Do it\nwith detail", sync_packet="PACKET", round_=2, review_feedback="fix the edge")

  def test_default_roles_render_the_0_2_1_prompts_byte_for_byte():
      assert prompts.render(prompts.IMPLEMENT, **KW) == (GOLDEN / "prompt_implement_0.2.1.txt").read_text(encoding="utf-8")
      assert prompts.render(prompts.REVIEW, **KW) == (GOLDEN / "prompt_review_0.2.1.txt").read_text(encoding="utf-8")

  def test_other_roles_change_only_the_names():
      implement = prompts.render(prompts.IMPLEMENT, implementer="aider", reviewer="gemini", **KW)
      assert "--from aider --to gemini --status ready-for-review" in implement
      assert "--actor aider --role implementer" in implement
      review = prompts.render(prompts.REVIEW, implementer="aider", reviewer="gemini", **KW)
      assert "--from gemini --to aider --status changes-requested" in review
      assert review.count("--from gemini --to gemini") == 2
      assert "codex" not in implement and "claude" not in review

  def test_role_placeholders_in_task_text_are_not_rewritten():
      text = prompts.render(prompts.IMPLEMENT, **{**KW, "task_text": "uses {implementer} literally"})
      assert "uses {implementer} literally" in text
  ```

  **The only permitted edits to existing tests** are `tests/test_prompts.py` line 39 (`"whyline handoff {task_id} --from {implementer} --to {reviewer}" in prompts.IMPLEMENT`) and line 46 (`"--to {implementer} --status changes-requested" in prompts.REVIEW`). Everything else in the suite passes unedited. Change nothing else.

- [ ] ADPT-4: the running marker, `status` and `--dry-run` follow the roles
  Fix the one-relay guard for agents other than `codex` and `claude`, and stop `status` and `--dry-run` naming `codex`. Change nothing else. This is a safety fix: today a marker written for any other agent reads as "no relay running", so a second relay would start.

  **`running.py`:**
  - `Running` gains `role: str = ""` as the **last** field. `asdict` then writes it; old markers without it still load.
  - `read()`: replace `marker.agent not in ("codex", "claude")` with `not isinstance(marker.agent, str) or not marker.agent.strip()`; also return `None` when `role` is not a string.
  - `start_turn(root, agent, task, round_, role: str = "")` stores `role`.

  **`cli.py`:**
  - `cmd_status`: the verb is `"reviewing"` when `active.role == "reviewer"`, `"implementing"` when `active.role == "implementer"`, and when `active.role` is empty the old rule (`"implementing" if active.agent == "codex" else "reviewing"`). The printed line format is unchanged.
  - the `--dry-run` branch of `cmd_start` (around `settings.agents["codex"]`): use `settings.agents[settings.roles.implementer]` and pass `implementer=settings.roles.implementer, reviewer=settings.roles.reviewer` to `prompts.render`. Its output for the default config is unchanged.

  **Tests first:**

  ```python
  def test_a_live_marker_for_any_agent_name_blocks_a_second_relay(tmp_path):
      write_marker(tmp_path, agent="gemini", pid=os.getppid())   # a live pid that is not this process
      assert running.live(tmp_path).agent == "gemini"
      with pytest.raises(running.AlreadyRunning):
          running.start_turn(tmp_path, "aider", "T-1", 1)
  ```

  Also test: an empty agent name is still rejected; a marker with no `role` key loads with `role == ""`; `start_turn(..., role="reviewer")` writes `"role": "reviewer"`; `status` prints `Running: gemini reviewing T-1` for a live marker `{agent: gemini, role: reviewer}`, `implementing` for role `implementer`, and for an old marker `{agent: claude}` without role still prints `reviewing` (the acceptance suite writes such markers); `start --dry-run` with a config whose `[roles]` has `implementer = "claude"` prints the claude command after `Would run:`. Existing tests unchanged. Change nothing else.

- [ ] ADPT-5: the loop runs the configured roles
  Make `loop.py` take the implementer and reviewer from `settings.roles` and their tools from the adapters. Default behaviour, output and log names must not change. Change nothing else.

  **Create the test helper** `tests/fake_role_agent.py`, used by the new tests here and in ADPT-6 and ADPT-9:

  ```python
  """A fake agent that hands off under exactly the names it is told.

  argv: root from_actor to_actor status commit(yes|no) <prompt>   (the relay appends the prompt last)
  """
  import json, re, subprocess, sys
  from pathlib import Path

  def main() -> int:
      root, from_actor, to_actor, status, commit = sys.argv[1:6]
      prompt = sys.argv[-1]
      task = re.search(r"^## Task (\S+)", prompt, re.M).group(1)
      if commit == "yes":
          subprocess.run(["git", "commit", "--allow-empty", "-m", f"feat: work ({task})"],
                         cwd=root, check=True, capture_output=True)
      target = Path(root) / ".whyline" / "active-handoff.json"
      target.parent.mkdir(exist_ok=True)
      previous = json.loads(target.read_text()) if target.exists() else {}
      counter = int(previous.get("counter", 0)) + 1
      target.write_text(json.dumps({"v": 1, "id": f"role{counter}", "counter": counter, "type": "Handoff",
          "task": task, "from_actor": from_actor, "to_actor": to_actor, "status": status, "summary": "fake"}))
      print(f"fake-role-agent {from_actor} -> {to_actor} {status}")
      return 0

  if __name__ == "__main__":
      raise SystemExit(main())
  ```

  **`loop.py`:**
  - In `_run_task`: `implementer = settings.roles.implementer`, `reviewer = settings.roles.reviewer`; `role = "implementer" if next_move == routing.IMPLEMENT else "reviewer"`; `agent` is the agent for that role; `template = "implement"` for the implementer role, `"review"` otherwise. `whylinecmd.claim(root, task.task_id, implementer, "implementer")`. Pass `implementer=` and `reviewer=` to `routing.decide`.
  - The check that the implementer did not commit runs when `role == "implementer"` (not when the agent is named `codex`). Message: `f"{agent} made a commit, which the relay forbids (only the reviewer commits). Undo it with `git reset {head_before[:12]}` (your files stay), then resume"`. For `codex` it reads exactly as today.
  - `_run_agent(root, settings, agent, role, template, task, round_, review_feedback, echo)`: the progress verb is by role (`"implementing"` or `"reviewing"`); `running.start_turn(..., role=role)`; `prompts.render(..., implementer=..., reviewer=...)`; the log file is `<task>-<round>-<agent>.log` **unless** `settings.roles.implementer == settings.roles.reviewer`, in which case it is `<task>-<round>-<agent>-<role>.log`. `log_path()` gains an optional `role: str = ""` argument that appends `-<role>` when non-empty.
  - `_no_handoff_detail(target)` becomes `_no_handoff_detail(target, adapter)` and returns `adapter.diagnose(text)` (empty string when the log cannot be read). The adapter comes from `config.adapter_for(settings, agent)`. Remove the now-duplicated parsing from `loop.py`; the behaviour is the adapters' (ADPT-1).

  **Tests first**, in a new `tests/test_loop_roles.py`, using `fake_role_agent.py` through `config.Config(..., roles=config.Roles(...))`:
  1. **Swapped roles complete.** `roles=Roles("claude", "codex")`; agent `claude` runs `fake_role_agent.py <root> claude codex ready-for-review no`; agent `codex` runs `... codex codex approved yes`. `run_task` returns an `Outcome` with `committed=True`. Spy `whylinecmd.claim`: it was called with actor `claude`.
  2. **The commit check follows the implementer.** Same roles; the `claude` fake commits (`yes`): `Paused`, reason contains `claude made a commit, which the relay forbids`.
  3. **Log names.** Default roles: the logs are `T-1-1-codex.log` and `T-1-1-claude.log`. `roles=Roles("claude", "claude")` with one fake per turn: `T-1-1-claude-implementer.log` and `T-1-1-claude-reviewer.log` both exist and differ.
  4. **The progress verb follows the role** (`echo=True`, `capsys`): swapped roles print `==> claude: implementing T-1 (round 1 of 3)` and `==> codex: reviewing T-1`.
  5. **A generic agent's silence is explained by its adapter:** roles `("codex", "aider")`, `adapters={"aider": "generic"}`, `agents["aider"]` a command that prints two lines and exits 0: the pause reason contains `its last output was` and the second line.

  Existing tests unchanged (they build `Config` without roles). Change nothing else.

- [ ] ADPT-6: the handoff must come from the agent that just ran
  A handoff recorded under a different name than the agent that ran pauses the run, so provenance in the record is trustworthy (D2). Change nothing else.

  **`loop.py`:** in `_run_task`, right after the existing check that `record.task == task.task_id`, and before the `BLOCKED` and `UNKNOWN` handling:

  ```python
  if record.from_actor and record.from_actor.strip().lower() != agent.lower():
      raise Paused(
          f"{agent} recorded its handoff as from {record.from_actor!r}, not {agent!r}. "
          "Check the prompt templates in .whyline/relay/prompts; after changing "
          f"[roles], run `{invocation.command('init')} --overwrite`",
          target,
      )
  ```

  Import `invocation`. An empty `from_actor` is not checked (whyline always writes one; an unreadable record is already `NO_HANDOFF`). `resume` does not run this check, because no agent has just run.

  **The one permitted fixture edit:** in `tests/fake_agent.py` change `"from_actor": "fake"` to `"from_actor": os.environ.get("FAKE_ACTOR", "")` (add `import os`). No other existing test changes.

  **Tests first**, in `tests/test_loop_roles.py`, with `fake_role_agent.py`:
  1. The implementer (`codex`) hands off `--from claude`: `Paused`, reason contains `'claude'` and `not 'codex'` and `init --overwrite`.
  2. `--from CODEX` (upper case) for agent `codex` is accepted.
  3. A record with an empty `from_actor` is accepted (use `tests/fake_agent.py` in a default mode).
  4. A mismatch on the reviewer's `approved` pauses too, and the plan is not ticked.
  5. `FAKE_ACTOR=someone` with `tests/fake_agent.py` pauses; unset it passes.
  6. Resuming a task whose record already says `from_actor: "x"` (as `write_handoff` in `test_loop_single.py` writes) still routes normally.

  Run the whole suite; it passes with only the one fixture line edited. Change nothing else.

- [ ] ADPT-7: preflight checks the agents that fill the roles
  `doctor`, `start` and `resume` must check only the agents in use, use the adapters for logins, and warn about weak setups. Default output must be byte-identical. Change nothing else.

  **`preflight.py`:**
  - Add `_agents_in_use(settings) -> dict[str, list[str]]`: agent name to command, for `settings.roles.implementer` then `settings.roles.reviewer` (each once), skipping a name absent from `settings.agents`.
  - `_relay_setup`, `_programs`: iterate `_agents_in_use(settings).values()` instead of `settings.agents.values()`. Everything else about them is unchanged (the `--settings` scan, the empty-command failure, the PATH check and its messages).
  - `_logins(root, settings, runner)`: for each in-use `(agent, command)`, `adapter = config.adapter_for(settings, agent)`; check only when `adapter.login_argv is not None` and `Path(command[0]).name == adapter.binary` (so a stand-in command is not login-checked, as today); run `list(adapter.login_argv)` with the same 20-second timeout; messages and `fix` are today's, built from `adapter.binary` and `adapter.login_fix`. One check per binary.
  - New `_role_checks(root, settings) -> list[Check]`, called from `run()` right after the logins (only when `settings is not None`):
    1. When implementer and reviewer are the same agent: `warn`, `"<agent> is both the implementer and the reviewer, so the review is not independent"`.
    2. For each in-use agent whose adapter is generic: `warn`, `"<agent> is a generic agent: the relay does not manage its permissions, login or denials"`.
    3. When the roles are not the defaults (`Roles("codex", "claude")`): for each of `implement.md` and `review.md` that **exists** under `.whyline/relay/prompts`, `FAIL` if the file text lacks `{implementer}` or lacks `{reviewer}`: `"prompt template .whyline/relay/prompts/<name> does not use {implementer} and {reviewer}, so an agent would be told the wrong names"`, fix `"<invocation.command('init')> --overwrite"`. A template that is missing from disk is fine (the built-in one is used).
    4. When the roles are not the defaults, for each in-use non-generic agent one `ok` row summarising it, from `adapters.describe(adapter, role, agent)`: `"<role>: <agent>  permissions: managed|not managed  login: checked|not verified  denials: reported|not reported"` derived from `adapter.manages`.
  - `adapters/__init__.py` gains `describe(adapter, role, agent) -> str` as in row 4.
  - With the default roles and no generic agent, `_role_checks` returns `[]`, so `doctor` output is unchanged.

  **Tests first**, in `tests/test_preflight.py` with the injectable `runner` (no real agent is launched):
  - roles `("claude", "claude")` and a config without `codex` on PATH: no `codex is not on PATH` failure appears; the same-agent warning does.
  - roles `("codex", "aider")` with a generic `aider`: one `warn` naming `aider`; `aider`'s program is checked on PATH; no login is attempted for it.
  - non-default roles with a stale template (a copy of the 0.2.1 one) fails, naming the file, with the `init --overwrite` fix; with a fresh template (`prompts.IMPLEMENT`) it passes; with no template file it passes.
  - default roles: the list of `(status, message)` pairs equals what the same test produced before this task (assert against a literal list captured from the unmodified code).
  - a stand-in codex command (`sys.executable`) is not login-checked, as today.

  Existing tests unchanged. Change nothing else.

- [ ] ADPT-8: `init --implementer` and `--reviewer`
  Let `init` set the roles and write only what the agents in use need. Without the new options, everything it writes is byte-identical to 0.2.1. Change nothing else.

  **Step 1, before editing `init.py`:** capture goldens from the unmodified code. In a temporary git repository with a `pyproject.toml` (stack `python`), run `init --yes` and copy `.whyline/relay/config.toml`, `.whyline/relay/claude-settings.json` and the command's stdout into `tests/golden/init_default_0.2.1.config.toml`, `init_default_0.2.1.claude-settings.json` and `init_default_0.2.1.stdout` (the temp repo path in the stdout replaced by `{ROOT}`). These are part of the task.

  **Step 2, `init.run(root, *, assume_yes, overwrite=False, confirm=input, implementer: str | None = None, reviewer: str | None = None)`:**
  - `roles_given = implementer is not None or reviewer is not None`; the roles are `implementer or "codex"` and `reviewer or "claude"`. They are built-in names (the CLI restricts them, below).
  - The agents in use are those two (each once). The permission files are the union of `adapter.permission_files(stack)` over their adapters, each written at `.whyline/relay/<key>`. For the default roles that is exactly `claude-settings.json` as today. Print `Proposed <path>:` and the file text for each such file, as today; print none when the files dict is empty. The `Detected stack` line, the `Also writing prompt templates and config` line, the confirmation and everything after it are unchanged.
  - `config.toml`: when `roles_given` is false, the text is exactly what it is today (no `[roles]`, both `[agents.*]` blocks). When true: the same header keys, then `[roles]` with both keys, then an `[agents.NAME]` block (with the built-in default command) for each agent in use only.
  - The closing explanation about `--settings` and `.claude/settings.json`, and the allowlist-is-a-convenience note, are printed only when `claude` is in use.
  - The prompt templates and `.gitignore` are written as today.

  **Step 3, `cli.py`:** `init` gains `--implementer NAME` and `--reviewer NAME`, each with `choices=sorted(adapters.BUILTIN)`, default `None`, passed to `init.run`. Help text: `Which built-in agent implements (default: codex)` and `Which built-in agent reviews and commits (default: claude)`. Generic agents cannot be chosen here; they are added by hand in `config.toml` (a README matter, not this task).

  **Tests first**, new `tests/test_init_roles.py`:
  - default `init --yes` produces the three golden files and stdout byte for byte.
  - `--implementer claude --reviewer codex`: `config.load(root).roles == Roles("claude", "codex")`; both `[agents.*]` blocks and `claude-settings.json` exist.
  - `--implementer claude --reviewer claude`: no `[agents.codex]` block, `claude-settings.json` written, no `Proposed` for anything else.
  - `--implementer codex --reviewer codex`: no `claude-settings.json` written; `config.toml` has no `--settings`; `preflight.run` (with a stub runner) reports no missing-settings failure; `remove` afterwards succeeds and leaves nothing under `.whyline/relay/` that `init` wrote.
  - `--implementer aider` exits 2 (argparse invalid choice) and writes nothing.
  - only `--reviewer codex` given: implementer stays `codex`, so roles are `("codex", "codex")` and `[roles]` is written.

  Existing tests unchanged. Change nothing else.

- [ ] ADPT-9: bypass flags are refused, in one place
  The relay must refuse to run an agent whose command carries a permission-bypass flag, in `doctor`, `start` and `resume`, and also when the preflight is skipped. Change nothing else.

  **Create** `src/whyline_relay/adapters/bypass.py`: the **only** file that may contain the refused strings.

  ```python
  """Flags that switch an agent's permission checks off. The relay refuses them; it never passes them.

  This module is the single place that names them, and the guard test exempts it by name.
  """
  FLAGS = {
      "codex": ("--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust"),
      "claude": ("--dangerously-skip-permissions",),
  }
  SANDBOX_OFF = "danger-full-access"       # a value of codex's -s / --sandbox
  MODE_OFF = "bypassPermissions"           # a value of claude's --permission-mode

  def find(adapter_name: str, command: Sequence[str]) -> list[str]:
      """The refused flags present in `command`, in order; empty for a generic agent (not inspectable)."""
  ```

  `find` matches a flag when an argument equals it or starts with `FLAG=`. For `codex` it also reports `--sandbox danger-full-access`, `-s danger-full-access` and `--sandbox=danger-full-access` (returns the text `-s danger-full-access` or the form found). For `claude` it also reports `--permission-mode bypassPermissions` and `--permission-mode=bypassPermissions`. It returns `[]` for any adapter name not in `FLAGS`, including `generic`.

  **`loop._run_agent`:** before launching, `found = bypass.find(adapter.name, command)`; if not empty raise `Paused(f"refusing to run {agent}: its command contains a permission-bypass flag ({', '.join(found)}). The relay never runs an agent that way; remove it from .whyline/relay/config.toml", None)`. This holds with `--skip-checks`.

  **`preflight._role_checks`:** for each in-use built-in agent with a non-empty `bypass.find(...)`, a `FAIL` with the same wording as the loop's (no `Paused`), fix `remove it from .whyline/relay/config.toml`.

  **The one permitted edit to an existing test**, `tests/test_no_bypass.py::test_no_source_file_mentions_a_bypass_flag`: add `"bypassPermissions"` to `FORBIDDEN`, and skip exactly the file `adapters/bypass.py` in that scan (compare `path.relative_to(SOURCE).as_posix()`). Add new tests there:
  - `test_only_bypass_py_is_exempt`: the exempt set is exactly `{"adapters/bypass.py"}`, hard-coded in the test, so widening it needs an edit here and a reviewer.
  - `test_no_default_command_or_generated_config_carries_a_bypass_flag`: for every built-in adapter, `bypass.find(name, default_command) == []`, and so is every command in `config.DEFAULTS["agents"]` and in a `config.toml` written by `init.run` for every pair of built-in roles.
  - `test_the_git_push_guard_is_untouched` is the existing second test and stays as is.

  **Tests first** in `tests/test_bypass.py`: each refused form is found for its adapter and only that adapter (`--dangerously-skip-permissions` is not found for `codex`); `[..., "-s", "danger-full-access"]`, `["--sandbox=danger-full-access"]` and `["--permission-mode", "bypassPermissions"]` are found; the defaults are clean; `generic` returns `[]`; `loop.run_task` with a config whose `codex` command contains the codex bypass flag raises `Paused` **without launching anything** (patch `agents.run` to fail the test if called); `preflight.run` with the same config returns a `FAIL`; and `start --skip-checks` on it exits non-zero without launching an agent.

  Existing tests unchanged apart from the edit named above. Change nothing else.

---

## Self-review against the spec

**Spec coverage.** 5.1 config and roles: ADPT-1 (`[roles]`, generic validation, defaults), ADPT-3 (placeholders, stale-template rule in ADPT-7). 5.2 adapter interface: ADPT-1 (with C12). 5.3 per-module: `config` 1, `adapters` 1, `routing` 2, `loop` 5/6/9, `handoff` 2, `preflight` 7/9, `prompts` 3, `init` 8, `cli` 4/8; `running` 4 (C1). 5.4 safety: bypass 9 (C2, C3), from-actor 6, honest summary 7. 5.5 `init` and `doctor`: 8, 7. D1 to D5: all honoured (agent's own name in prompts, generic adapter with the warning, same-agent warning, code adapters). 5.6 and build steps 0 and 2 (Gemini): deliberately **out**, stated above. Build step 3's README and release notes: written by hand at release time. Risks: old templates (ADPT-7 rule 3), sandbox reporting (Gemini plan), release coordination (decided: 0.2.2).

**Placeholders.** None. Every value the tasks name (messages, field names, file names, defaults) is spelled out. The two goldens are captured by a command the task gives.

**Types and names used across tasks.** `Roles(implementer, reviewer)`, `config.adapter_for(settings, agent)`, `Adapter.{name, default_command, binary, login_argv, login_fix, permission_files, diagnose, manages}`, `adapters.get`, `adapters.describe`, `adapters.BUILTIN`, `handoff.Handoff.from_actor`, `routing.decide(..., implementer=, reviewer=)`, `prompts.render(..., implementer=, reviewer=)`, `running.Running.role`, `running.start_turn(..., role=)`, `loop.log_path(..., role=)`, `bypass.find(adapter_name, command)` are defined in the task that first produces them and used with the same spelling afterwards.

**Known soft spots to watch in review.** (1) ADPT-7's "byte-identical default doctor output" is asserted from a literal captured before the change: if the implementer captures it after, the test proves nothing. (2) ADPT-8's goldens likewise. (3) ADPT-5 touches the busiest file; the suite plus the 97 acceptance tests are the net. (4) Codex will be tempted to widen the guard exemption in ADPT-9; the pinned set is there to stop that.
