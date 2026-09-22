# whyline-relay model selection (relay 0.2.6) Implementation Plan

> **For agentic workers:** this plan is run by whyline-relay itself, on its own repository: Codex implements the task, Claude reviews and commits it.

**Goal:** An agent name can declare `adapter = "codex"` or `adapter = "claude"` (not only `"generic"`), plus an optional `model`, so a named agent variant (e.g. `claude-opus`, `claude-haiku`) gets the real adapter's full managed behavior — login check, bypass-flag refusal, denial parsing — while running a different model of the same tool.

**Architecture:** All three CLIs already support `--model` (confirmed against real `--help` output: `codex exec -m/--model`, `claude --model`, and `agy --model` for the future Antigravity work). `Adapter` gains a `model_flag` field; `config.py` bakes `[*model_flag, model]` directly into the stored command list at load time. Nothing downstream (`loop.py`, `agents.py`, `preflight.py`, `cli.py`) needs to change: they already treat `settings.agents[name]` as a complete, ready-to-run command list, and `config.adapter_for` already resolves a custom name's adapter through `settings.adapters`, which this task extends to hold a built-in adapter's own name instead of only `"generic"`.

**Tech Stack:** Python 3.11+, standard library only, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md`, section 5.9 and decision D10. This plan is build-order phase 0 from that design's section 6 — independent of every other phase, no dependency on the state-machine work.

## Global Constraints

- No new dependencies. Do not touch `pyproject.toml`, `uv.lock`, or the version.
- The sandbox has no network: run tests with `uv run --frozen pytest -q`.
- A `config.toml` with no `model` key and no non-`generic` `adapter` value on a custom name behaves identically to relay 0.2.5. The existing suite, unedited except where this task names an edit, is the proof.
- No model string is validated against what an account can actually use — an invalid or unavailable model fails at run time, the same as any other agent failure. Do not add any such validation.
- The relay never passes a permission-bypass flag, never runs `git push`, and never writes a handoff on an agent's behalf.

## File structure

| File | Responsibility |
|---|---|
| `src/whyline_relay/adapters/base.py` | `Adapter` gains `model_flag: tuple[str, ...] \| None` |
| `src/whyline_relay/adapters/codex.py` | `model_flag=("--model",)` |
| `src/whyline_relay/adapters/claude.py` | `model_flag=("--model",)` |
| `src/whyline_relay/adapters/generic.py` | `model_flag=None` |
| `src/whyline_relay/config.py` | The `[agents.*]` validation loop: a non-built-in name may set `adapter` to `"generic"` or a name in `adapters.BUILTIN`; a `model` key is baked into the stored command via the resolved adapter's `model_flag` |
| `tests/test_adapters.py` | `model_flag` present on `codex.ADAPTER`/`claude.ADAPTER`, absent on `generic.ADAPTER` |
| `tests/test_config.py` | New tests for the relaxed validation and model-baking; one existing parametrized case updated (see below) |

## Permitted edit to an existing test

`tests/test_config.py::test_role_and_agent_config_errors_are_precise` has a parametrized case asserting that `[agents.aider]\nadapter = "claude"\ncommand = ["aider"]\n` is an error (`'[agents.aider] adapter must be "generic", not \'claude\''`, line 81). That is exactly the configuration this task makes valid. Replace that one tuple with a case that is still genuinely invalid under the new rules — an adapter value that is neither `"generic"` nor a built-in agent, for example `'[agents.aider]\nadapter = "mystery"\ncommand = ["aider"]\n'` expecting `'[agents.aider] adapter must be "generic" or a built-in agent (claude, codex), not \'mystery\''`. No other case in that parametrized list changes. Any other edit to an existing test means the change is not backward compatible: stop and say so in the handoff.

## The task

- [ ] MDL-1: agent variants: a custom name may alias a built-in adapter, plus a `model` override
  Rules: run the tests with `uv run --frozen pytest -q` (there is no network). Add no dependencies and do not touch `pyproject.toml`, `uv.lock` or the version. A config with no `model` key and no non-generic `adapter` on a custom name must behave exactly as relay 0.2.5; the existing suite, unedited except for the one named case, is the proof. Never pass or write a permission-bypass flag, never run `git push`, and never write a handoff on an agent's behalf.

  **`adapters/base.py`:** add one field to `Adapter`, after `manages` (it is the last field, so every existing keyword-argument construction elsewhere keeps working once the three adapter files below are updated — there are no other construction sites in `src/` or `tests/`):

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

  **`adapters/codex.py`:** add `model_flag=("--model",)` to `ADAPTER`'s construction (confirmed real: `codex exec -m, --model <MODEL>`).

  **`adapters/claude.py`:** add `model_flag=("--model",)` to `ADAPTER`'s construction (confirmed real: `claude --model <model>`, accepting an alias like `opus`/`sonnet`/`haiku` or a full model name).

  **`adapters/generic.py`:** add `model_flag=None` to `ADAPTER`'s construction — a generic agent's command is opaque; if its model needs pinning, that goes directly in `command`, exactly as today.

  **`config.py`:** replace the `for name, table in (raw.get("agents") or {}).items():` loop's body with:

  ```python
  for name, table in (raw.get("agents") or {}).items():
      if name in adapters.BUILTIN:
          if "adapter" in table:
              raise ConfigError(f"agent '{name}' is built in and cannot set adapter")
          resolved_adapter = adapters.get(name)
      else:
          if "adapter" not in table:
              raise ConfigError(
                  f"agent '{name}' is not built in: set adapter = \"generic\" "
                  f"and a command under [agents.{name}]"
              )
          adapter_name = table["adapter"]
          if adapter_name == "generic":
              resolved_adapter = adapters.GENERIC
              configured_adapters[name] = "generic"
          elif adapter_name in adapters.BUILTIN:
              resolved_adapter = adapters.get(adapter_name)
              configured_adapters[name] = adapter_name
          else:
              builtins = ", ".join(sorted(adapters.BUILTIN))
              raise ConfigError(
                  f'[agents.{name}] adapter must be "generic" or a built-in agent '
                  f'({builtins}), not {adapter_name!r}'
              )
          if resolved_adapter.default_command is None:
              command = table.get("command")
              if not isinstance(command, list) or not command:
                  raise ConfigError(f"[agents.{name}] needs a non-empty command")

      command = table.get("command")
      if command is not None:
          if not isinstance(command, list) or not command:
              raise ConfigError(f"[agents.{name}] needs a non-empty command")
          agents[name] = list(command)
      elif name not in agents:
          agents[name] = list(resolved_adapter.default_command)

      model = table.get("model")
      if model is not None:
          if not isinstance(model, str) or not model:
              raise ConfigError(f"[agents.{name}] model must be a non-empty string")
          if resolved_adapter.model_flag is None:
              raise ConfigError(
                  f"[agents.{name}] cannot set model: the {resolved_adapter.name} "
                  "adapter has no way to apply it"
              )
          agents[name] = [*agents[name], *resolved_adapter.model_flag, model]
  ```

  This is a straight replacement of the existing loop body (today's loop only handles the `"generic"` branch and the plain `command` override; `configured_adapters`, `agents`, and `ConfigError` are already imported/defined in this module, nothing else changes). Do not change anything above or below this loop in `load()`.

  **Tests first**, added to `tests/test_adapters.py`:

  ```python
  def test_codex_and_claude_declare_the_real_model_flag():
      assert codex.ADAPTER.model_flag == ("--model",)
      assert claude.ADAPTER.model_flag == ("--model",)

  def test_generic_has_no_model_flag():
      from whyline_relay.adapters import generic
      assert generic.ADAPTER.model_flag is None
  ```

  And to `tests/test_config.py`:

  ```python
  def test_a_custom_name_may_alias_the_claude_adapter(tmp_path: Path):
      write(
          tmp_path,
          '[agents.claude-opus]\nadapter = "claude"\n',
      )
      loaded = config.load(tmp_path)
      assert loaded.agents["claude-opus"] == config.DEFAULTS["agents"]["claude"]
      assert config.adapter_for(loaded, "claude-opus").name == "claude"

  def test_a_claude_variant_can_override_command_and_add_a_model(tmp_path: Path):
      write(
          tmp_path,
          '[agents.claude-opus]\nadapter = "claude"\n'
          'command = ["claude", "-p"]\nmodel = "opus"\n',
      )
      loaded = config.load(tmp_path)
      assert loaded.agents["claude-opus"] == ["claude", "-p", "--model", "opus"]
      assert config.adapter_for(loaded, "claude-opus").name == "claude"

  def test_a_codex_variant_with_no_command_gets_the_default_plus_the_model(tmp_path: Path):
      write(tmp_path, '[agents.codex-fast]\nadapter = "codex"\nmodel = "gpt-5-mini"\n')
      loaded = config.load(tmp_path)
      assert loaded.agents["codex-fast"] == [
          *config.DEFAULTS["agents"]["codex"],
          "--model",
          "gpt-5-mini",
      ]

  def test_the_literal_built_in_name_can_also_take_a_model(tmp_path: Path):
      write(tmp_path, '[agents.claude]\nmodel = "haiku"\n')
      loaded = config.load(tmp_path)
      assert loaded.agents["claude"] == [
          *config.DEFAULTS["agents"]["claude"],
          "--model",
          "haiku",
      ]

  def test_model_on_a_generic_agent_is_refused(tmp_path: Path):
      write(
          tmp_path,
          '[agents.aider]\nadapter = "generic"\ncommand = ["aider"]\nmodel = "x"\n',
      )
      with pytest.raises(
          config.ConfigError, match="cannot set model: the generic adapter"
      ):
          config.load(tmp_path)

  def test_a_non_string_model_is_refused(tmp_path: Path):
      write(tmp_path, "[agents.claude]\nmodel = 3\n")
      with pytest.raises(config.ConfigError, match="model must be a non-empty string"):
          config.load(tmp_path)

  def test_an_empty_model_is_refused(tmp_path: Path):
      write(tmp_path, '[agents.claude]\nmodel = ""\n')
      with pytest.raises(config.ConfigError, match="model must be a non-empty string"):
          config.load(tmp_path)

  def test_an_unrecognised_adapter_value_still_names_both_valid_options(tmp_path: Path):
      write(tmp_path, '[agents.aider]\nadapter = "mystery"\ncommand = ["aider"]\n')
      with pytest.raises(
          config.ConfigError,
          match=r'adapter must be "generic" or a built-in agent \(claude, codex\)',
      ):
          config.load(tmp_path)

  def test_a_claude_variant_is_login_checked_and_bypass_checked_like_claude_itself(tmp_path: Path):
      from whyline_relay import preflight
      from whyline_relay.adapters.base import Manages
      write(
          tmp_path,
          '[roles]\nreviewer = "claude-opus"\n'
          '[agents.claude-opus]\nadapter = "claude"\nmodel = "opus"\n',
      )
      loaded = config.load(tmp_path)
      in_use = preflight._agents_in_use(loaded)
      assert "claude-opus" in in_use
      command, backup_for = in_use["claude-opus"]
      assert command[0] == "claude" and backup_for is None
      adapter = config.adapter_for(loaded, "claude-opus")
      assert adapter.login_argv == ("claude", "auth", "status")
      assert adapter.manages == Manages(True, True, True)
  ```

  Then update `tests/test_config.py::test_role_and_agent_config_errors_are_precise`'s parametrized
  case exactly as described in "Permitted edit to an existing test" above — this is the only
  existing test this task may change.

  Run `uv run --frozen pytest -q`: every existing test passes unedited except that one named case,
  plus all of the above pass. Change nothing else.

## How this is run and checked

1. Independent acceptance tests, written before the run, from this plan's requirements. They must fail on 0.2.5 and be validated the way every earlier round in this project was.
2. A sandbox clone of the relay (remotes removed) holds the task above as `plan.md`. `whyline-relay start` runs it.
3. After the run: the full existing suite (unedited except the one named case), the existing acceptance suites (unedited), the new acceptance tests, and tripwires confirming no real agent or `osascript` binary is ever invoked.
4. Cherry-pick into the real repository, release notes and a README section (written by hand from measured behaviour), pre-flight, then stop for an explicit go before pushing or tagging `v0.2.6`.

## Release

Relay **0.2.6**. whyline's pin (`whyline-relay>=0.2.1,<0.3`) already admits it.

---

## Self-review against the spec

**Spec coverage.** Section 5.9 and decision D10 in full: the `model_flag` field, the real flags for codex and claude (verified against actual `--help` output, not guessed), the adapter-decoupling validation change, and the explicit non-goal that no model string is checked against what an account can use (stated in Global Constraints and enforced by having no such check anywhere in the task). Section 5.9's note that `generic`'s model, if wanted, "goes directly in `command`" is reflected in `generic.py`'s `model_flag=None` and the refusal test.

**Placeholders.** None. Every message, field name, and function call is spelled out exactly, using names already confirmed to exist in the current source (`adapters.BUILTIN`, `adapters.GENERIC`, `adapters.get`, `config.adapter_for`, `preflight._agents_in_use`).

**Type/name consistency.** `Adapter.model_flag: tuple[str, ...] | None` is the one new symbol this task introduces; every test and every adapter file uses it identically.

**Why this needed only one task, not several.** The command-baking happens once, at config-load time, into the plain `list[str]` that every other module already treats as a complete command — `loop.py`, `agents.py`, `cli.py`'s dry-run, and `preflight.py` all read `settings.agents[name]` as-is today and need no changes at all. `preflight._logins` and `_role_checks` already key on `adapter.binary` and `adapter.name`, not on the registry key, so a variant name is automatically login-checked and bypass-checked as the real adapter it aliases with no changes there either — traced through the actual current source, not assumed, and covered by the last new test above.
