<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-07T18:45:00+05:30 -->
# Relay live models: change an agent's model from "Agents for this run" while the relay runs

Runs after `plans/console-restart.plan.md`, and before `plans/assistant-scheduled-access.plan.md`. It needs whyline-relay 0.2.43 or later (RLY-18: `roles model`, `.whyline/relay/model-overrides.json`), which is on PyPI since 2026-11-12.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.

Why: on 2026-11-07, while release-button ran, the user opened Set up ("Agents for this run · CHF-3") and wanted to move claude from `sonnet` to `opus`. The screen can switch a role's agent (LIVE-1..4) but only lists models read-only in its summary ("Models: antigravity gemini-3.8-flash-high, claude sonnet, grok grok-4.6").

What the user gets:
- Each role row in "Agents for this run" gets a Model dropdown next to the agent dropdown, with the same options as Set up's model pickers.
- Save applies the model from that agent's next turn, never the current one. The row says "now opus · applies from its next turn".
- A model belongs to an agent, so changing claude's model on one row changes it on every row claude plays, and the screen says so.
- "Keep for future runs" also saves the model to `config.toml`, as it does for agents.

Rules every task keeps:
- The console never signals or restarts the relay for a model change. It only calls whyline-relay's `roles.switch_model`, the same function `whyline-relay roles model` calls.
- The model options come from `relay_ops.model_options_for_agent` and `cached_model_options`, the functions Set up uses. No new model list.
- Nothing in this plan changes Set up for a stopped relay.

- [ ] LMD-1: Console functions for a live model switch
  Edit `src/whyline/console/relay_ops.py` and `pyproject.toml` (and `uv.lock`), with tests in `tests/console/test_relay_ops_live_models.py`.
  1. Raise the `whyline-relay` floor in both places in `pyproject.toml` to the release with RLY-18 (`>=0.2.43,<0.3` if that is its version) and refresh `uv.lock`.
  2. Add `switch_model_live(root: Path, agent: str, model: str, *, keep: bool) -> str`, calling `whyline_relay.roles.switch_model` with the run's settings, the way `switch_live` calls `roles.switch`. It returns the relay's message, and lets `RoleSetError` through.
  3. Add `@dataclass(frozen=True) RunModel` with `agent`, `current`, `configured` and `pending: bool`, and `run_models(root: Path) -> dict[str, RunModel]`, from `config.toml` and `model-overrides.json`. `pending` is true while the running turn's model (from `running.json`'s `model`) differs from `current` for that agent.
  4. `RunRole` (from `run_roles`) is unchanged.
  Tests:
  - `switch_model_live` writes `model-overrides.json` and returns "claude → opus from its next turn."
  - `keep=True` also changes `[agents.claude] model` in `config.toml`
  - `run_models` shows `current="opus"`, `configured="sonnet"` after a switch, and `pending` while `running.json` says claude runs `sonnet`
  - an agent without `model_flag` raises with the relay's message

- [ ] LMD-2: Model dropdowns in "Agents for this run"
  Edit `src/whyline/console/relay_screens.py` (`RunAgentsScreen`), with tests in `tests/console/test_relay_screens.py`.
  1. Each role row gets a Model `Select` (`id="ra-model-<role>"`, width 26) after the agent `Select`, holding the options for the row's selected agent from `cached_model_options`, else `model_options_for_agent` in a worker, else the current model alone. "Default" means the CLI's own default (an empty model). Changing the agent dropdown refills the model dropdown for the new agent with that agent's current model selected.
  2. The model dropdown starts at `run_models(root)[agent].current`. Two rows with the same agent show the same model, and changing one updates the other.
  3. Save applies agent switches as today, then `switch_model_live` once per agent whose model changed, with the Keep checkbox's value. Errors go to `#ra-error` with the relay's message, and the other changes still apply.
  4. The row's reason line adds "model now opus · applies from its next turn" while `pending` is true, and the 2-second refresh keeps it current.
  5. The summary's "Models:" line shows a switched model as "claude opus (was sonnet)".
  6. The screen still fits 80x24. The `READ_ONLY` text becomes "The plan and other settings stay as they are while the relay runs. Stop the relay to change them."
  7. Console first: no new CLI is added here; `whyline-relay roles model` is the CLI counterpart.
  Tests (fake functions, no real relay):
  - choosing opus for the implementer row (claude) and Save calls `switch_model_live(root, "claude", "opus", keep=True)`
  - with Keep unticked the call has `keep=False`
  - the reviewer row, also claude, shows opus after the change on the implementer row
  - switching the tester row from antigravity to claude fills its model dropdown with claude's options and claude's current model
  - an agent error shows in `#ra-error` and the other row's model switch still applies
  - the pending line appears while `pending` is true and goes on the refresh after it turns false
  - the screen fits 80x24 with three rows of two dropdowns

## Release
