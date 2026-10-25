<!-- whyline-plan v1 | source: design | drafted-by: codex | spec: docs/superpowers/specs/2026-10-25-console-provider-settings-design.md | created: 2026-10-25T02:01:57+05:30 -->
# Console provider settings and non-blocking checks

Spec: `docs/superpowers/specs/2026-10-25-console-provider-settings-design.md`.
Read it before every task. Where a symbol name has moved, follow the current
repository while preserving the spec's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item.
Detail lines stay indented. Do not add another checkbox line anywhere in this
file. Do not implement from this plan until Relay starts the task.

The selection is global; repository role/model settings remain per repo. No
whyline-relay repository edit. No new dependency. No version bump, tag, push,
GitHub release, or PyPI publication. Tests never invoke a real provider, use a
real home directory, access the network, or sleep for a fixed duration.

- [x] SUBS-1: Separate enabled subscriptions from detected readiness
  Edit `src/whyline/account.py`, `src/whyline/cli.py`, `tests/test_account.py`, and `tests/test_account_cli.py` only.
  Add an `enabled` field to the per-provider global account record and helpers `enabled_agents()`, pure `check_provider(agent)`, plus an atomic global writer used by `set_enabled(agent, enabled)` and `set_enabled_many(values, results=None)`. Preserve every unrelated field and merge supplied completed check results. Write a sibling temporary file and replace the target; clean up the temporary path on failure.
  A record with no `enabled` reads `enabled = bool(available)`. A legacy `manual` record follows the same rule. Reading does not rewrite it. `set_enabled_many` writes explicit booleans for Claude, Codex, Grok, and Antigravity in one replacement.
  The global record is the enablement authority even when `.whyline/account.json` exists. Repo data may still provide its old cached account detail, but cannot turn a globally disabled provider back on.
  `agent_status(root)` returns all four providers with `enabled`, `installed`, effective `available`, `label`, and `hint`. Effective availability is enabled AND detected ready. For Grok and Antigravity, enabled plus PATH-installed is ready but the label remains `installed (login not checked)`. For Claude and Codex, keep the existing detected plan/API-key semantics. A disabled row is unavailable, labelled `off in Settings`, and hinted `Open Settings or run: whyline account enable <agent>`.
  `available_agents(root)` remains the compatibility helper and returns only effectively available providers. It must not silently default to Claude when the set is empty.
  Refactor refresh so an enabled-name set can be supplied and no disabled provider's detector or subprocess is called. `check_provider` never writes. A disabled record retains its last detected fields. `whyline account detect` checks and persists enabled providers only. `ensure_detected` no longer launches all providers when no explicit enabled set exists. `account enable/disable` call `set_enabled` and say `enabled in Whyline` / `disabled in Whyline`.
  Tests: legacy migration without write; repo data cannot override global enablement; enabled+missing binary is unavailable; Grok/Antigravity login wording is honest; all disabled yields an empty available set; disabled Claude detector is not called; multi-save preserves plan/auth fields; replacement failure preserves the old JSON; CLI wording and enabled-only detect.
  Verify with `uv run pytest -q tests/test_account.py tests/test_account_cli.py`. Change nothing else.

- [x] SUBS-2: Add the transactional Settings screen
  Add `src/whyline/console/settings_screen.py` and `tests/console/test_settings_screen.py`. Edit no other file.
  Implement `ProviderSettingsScreen`, a modal with title `Settings`, section `AI subscriptions`, four provider checkboxes in the stable order Claude, Codex, Grok, Antigravity, a plain-text status per row, the exact explanatory sentence `Disabled providers are not checked or shown in agent choices.`, and `Check selected`, `Save`, and `Cancel` buttons.
  The constructor receives the current records plus injected callables for checking one provider and atomically saving the four staged booleans with completed staged results. This module must not import the main app to call its methods.
  Compose from cached/local data and paint before starting work. On mount, use Textual thread workers to check only providers currently staged on. Checking a previously off provider starts only that provider. Unchecking prevents a queued check and makes the row say `Not used by Whyline`; an already-running result may be cached but cannot overwrite that row. `Check selected` starts a new token and ignores results from an older token.
  Claude/Codex result labels use the account result. Grok/Antigravity say `Installed · login not automatically verified` when PATH-present. Errors are one plain-text line and do not dismiss. No provider check runs in `__init__`, `compose`, or synchronously in `on_mount`.
  Save calls the one batch writer with the staged choices and completed results, disables itself during the write, and dismisses with the saved enabled set only on success. Cancel dismisses `None` and writes nothing, including check results. A save error leaves the screen open and old settings intact.
  At 80x24 and 120x40, the provider body may scroll but the error/status line and three buttons remain reachable.
  Tests use events, not sleep: screen appears while a fake check is blocked; only staged-on providers are called; enabling starts that provider; unchecking suppresses its late row update; a second refresh ignores the first token; Cancel writes nothing; Save passes all four booleans once; save failure stays open; both sizes keep buttons on-screen.
  Verify with `uv run pytest -q tests/console/test_settings_screen.py`. Change nothing else.

- [ ] SUBS-3: Wire Settings into the console and filter Chat and Brainstorm choices
  Edit `src/whyline/console/tui.py`, `src/whyline/console/repl.py`, `tests/console/test_tui.py`, and `tests/console/test_repl.py` only.
  Add `Settings` (`#settings`) to the shared bottom controls, visible in Chat, Relay, and Agents. Pressing it builds `ProviderSettingsScreen` from account data and injected account functions. On a saved result, refresh the context agent options, backup options, and mode state without restarting or changing mode. On Cancel, change nothing.
  If the saved chat default is now disabled, select the first usable enabled provider for the current session, print `The saved agent is off in Settings; using <agent> for this session.`, and leave the repository/global default untouched until the existing context-bar Save. With no usable enabled provider, never fall back to Claude; show the exact no-subscriptions message from spec P8 and block an agent turn.
  `_cb_options` includes enabled providers only. An enabled but unusable provider keeps the existing `!` value and actionable label. Backup choices and automatic backup staging exclude disabled providers. A stale saved backup name remains described as stale, not silently written away.
  Brainstorm fields render checkboxes only for enabled providers; enabled-but-unusable rows are disabled with their reason. Final writer and test-planner options use that same set. If none are enabled, the screen presents the P8 message and an `Open Settings` action rather than four disabled checkboxes. `collect_brainstorm` must not query widget ids that were not rendered.
  The `/model` path and keyboard REPL list enabled providers only and use the same no-subscriptions wording. Direct `/model refresh` refreshes enabled providers only.
  Tests: Settings appears in all modes; Cancel leaves menus unchanged; Save immediately removes disabled providers; disabled Antigravity is absent from Chat/backup/Brainstorm and no provider runner is invoked; stale default session fallback is not persisted; all-off never launches Claude; Brainstorm final/test selects cannot name a disabled provider; narrow and wide button rows keep Settings reachable.
  Verify with `uv run pytest -q tests/console/test_tui.py tests/console/test_repl.py`. Change nothing else.

- [ ] SUBS-4: Make Relay Set up provider-aware and model discovery non-blocking
  Edit `src/whyline/console/relay_ops.py`, `src/whyline/console/relay_screens.py`, `src/whyline/console/tui.py`, `tests/console/test_relay_ops.py`, and `tests/console/test_relay_setup_screen.py` only.
  Split model options into a non-blocking cached/static read and an explicit dynamic fetch. Claude, Codex, and Grok keep their built-in lists. Antigravity's fetch runs `agy models` with the existing timeout only from a thread worker. Cache success for the console session. Cache failure/empty with an injected-clock 60-second negative TTL. Do not overload `None` to mean both never tried and failed; tests must distinguish those states.
  Relay Set up derives new choices from enabled providers intersected with installed/configured relay agents. It does not call a provider subprocess in its constructor, `compose`, synchronous `on_mount`, or button handler. It renders immediately from static/cached options. An enabled Antigravity row with no cache shows its saved/manual value and `Checking models…`, starts one worker after paint, and replaces the options when it finishes. Failure leaves manual entry usable and shows `Could not refresh models; using the saved/default value.` as plain text.
  A disabled provider has no role, release, backup, or model choice and starts no worker. A saved role or chain member that is now disabled appears in one stale-configuration warning; Check fails with a Settings hint until roles are changed to enabled providers. Opening and cancelling must not rewrite the config.
  With no enabled usable relay agent, clicking Set up opens an actionable no-subscriptions state with `Open Settings`; it must not use the old installed-agent-only early return.
  Tests pin the regression: block fake `agy models`, click Set up, and assert the screen plus `Checking models…` are visible before releasing the event; then assert the dropdown updates. Add disabled-no-call, success-cache, negative-cache/clock-expiry, late-result-after-close, stale-config, no-provider, 80x24, and 120x40 cases. No fixed sleep and no real `agy`.
  Verify with `uv run pytest -q tests/console/test_relay_ops.py tests/console/test_relay_setup_screen.py tests/console/test_tui.py`. Change nothing else.

- [ ] SUBS-5: Apply enabled providers to saved Agents and the Idea Inbox
  Edit `src/whyline/console/agents_screens.py`, `src/whyline/console/inbox_screen.py`, `src/whyline/console/tui.py`, `src/whyline/agents/runner.py`, `src/whyline/ideas/cli.py`, `tests/console/test_new_agent_deliveries.py`, `tests/console/test_inbox_screen.py`, `tests/console/test_tui.py`, and the closest existing saved-agent/idea runtime test files only.
  New Agent main and backup choices are the enabled usable providers that also pass the existing `capabilities.can_run` / `can_run_unattended` rules. Do not weaken unattended safety. Editing an existing agent whose runner or backup is now disabled keeps that saved name visible as unavailable so Cancel is lossless; Save refuses it with `Enable <agent> in Settings or choose another provider.`
  Running a saved agent checks enablement at execution time before launching. A disabled runner may use an enabled configured backup under the existing backup rules; if none is usable, fail before a provider subprocess with the same Settings guidance. Agent list/history remain available.
  Idea Inbox score/brainstorm chain, assistant, and backup choices use enabled providers intersected with the existing unattended-safe set. Saved disabled names remain visible in the blocked explanation until the user changes and saves them. Inbox doctor reports them. Email/Telegram settings naming a disabled provider are rejected before invocation; do not silently substitute another provider unless the already-configured backup rules do so.
  Tests: disabled provider absent for a new agent and inbox choice; existing disabled definitions/config remain inspectable; Cancel is lossless; Save/runtime refuses disabled; an enabled backup is used only by the existing backup path; no disabled provider subprocess runs; enabling restores eligibility.
  Verify the named focused tests, then `uv run pytest -q tests/console/test_new_agent_deliveries.py tests/console/test_inbox_screen.py`. Change nothing else.

- [ ] SUBS-6: Document the Settings workflow and run the complete regression gate
  Edit `README.md`, `docs/agents-capabilities.md`, and tests only if a full-suite failure proves a test expectation must change for this spec. Do not change application code in this task.
  Add a concise README section: Whyline uses the user's existing Claude, Codex, Grok, or Antigravity CLI subscription; open console Settings to choose which providers Whyline may use; disabled providers are neither offered nor checked; Grok/Antigravity login is not automatically verified. Keep existing API-key wording truthful where already documented.
  Document saved-agent behaviour when a provider is disabled and how an enabled backup is handled. Mention the CLI counterparts `whyline account status|enable|disable|detect` without making terminal use the primary workflow.
  Run `git diff --check` and `uv run pytest -q`. If a failure requires application-code changes, leave this task unapproved with the exact failing test and request a new implementation task; do not expand this docs-only task.
