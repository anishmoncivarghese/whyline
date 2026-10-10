# Brainstorm: In chat therr is hardocded limit of 300s after which its timeout, relay has configurable and same wityh brainstoprm, I want an option to remove the limit first or put o[tion on top  somewhere kimnd of a drop down like agent where its drop down , user can select say timeout 15, 30 , 45 or no limit, simiallry in relay dezfult is 30 mins here its self we can remove the limit as well. Think about it

## Final Synthesis

Add configurable timeouts to Chat, Brainstorm, and Relay while preserving their intentionally different defaults: **5 minutes for Chat, 15 minutes per Brainstorm attempt, and 30 minutes per Relay turn**. Treat every timeout as a limit for one provider process attempt, not the whole visible turn or brainstorm; failovers, Grok resumes, review passes, and synthesis each receive the selected budget again.

### Product behavior

- **Chat:** add a `Timeout` select beside Agent in the top context bar with `5m`, `15m`, `30m`, `45m`, `60m`, and eventually `none`. The choice is captured when Send starts, disabled while the turn runs, and applies to the next Chat dispatch. It is session-only in the first release, does not dirty Save, and never writes Relay config. Add `/timeout`, `/timeout 30`, and `/timeout none` for keyboard parity. Keep the control and Save reachable at 80 columns by using abbreviated labels and narrower closed controls with wider overlays.
- **Brainstorm:** add `none` to its existing dialog and keyboard prompt, but keep its independent 15-minute default. Do not inherit the Chat selection. The chosen value applies separately to research, review, and synthesis attempts and remains stored with the topic.
- **Relay:** keep the 30-minute repository default. Support `timeout_minutes = 0`, `--timeout 0`, and optionally `--timeout none` as explicit unlimited forms, reject negatives, and warn once that an unattended hung process has no automatic cutoff. Store the effective timeout on `RelayState`/`PlanState` so pause and Resume preserve one-shot overrides; do not write a one-shot CLI value back to `config.toml`.
- **Scheduled Agents:** make no change. Their existing 1–240 minute validation remains finite.

### Safety gate for `none`

Ship finite Chat choices first if desired, but do not expose `none` anywhere until Stop authoritatively cancels the running process. Today the TUI cancels result presentation while the vendor CLI can continue running, spending tokens and modifying the workspace. The runner must accept a per-dispatch cancellation event, terminate the entire process group with `SIGTERM`, escalate to `SIGKILL` after the existing grace period, reap the child, and raise a distinct `AgentCancelled` before any commit path runs. Chat failover, Grok resume, and Brainstorm model loops must check cancellation before starting another attempt. Timeout, cancellation, Ctrl+C, and normal completion should share idempotent cleanup so close races cannot leak threads or double-signal the process group.

### Timeout contract and persistence

At the lowest runner layer, a positive integer arms the watchdog, `None` means no watchdog is created, and zero or negative values are rejected before spawning. The 30-second silence heartbeat remains active for uncapped runs; `none` removes only the kill timer, not provider-side limits or progress reporting.

Do not redefine existing higher-level `None` values as unlimited. In the current code, `None` also means omitted Chat timeout, invalid Brainstorm input, missing/corrupt Brainstorm metadata, or a fallback to a finite default. Introduce an explicit `NO_LIMIT` sentinel at those layers and convert it to runner-level `None` only at the final boundary. For Brainstorm persistence, write explicit unlimited as JSON `null`, but distinguish that from a missing or unreadable file, which must still fall back to 15 minutes. Audit falsey checks so Relay `0` and Brainstorm unlimited are forwarded rather than silently becoming Chat's 300-second fallback.

### Delivery order

1. In `whyline-relay`, add cancellation, process-group cleanup, `AgentCancelled`, optional-watchdog behavior, and checks that suppress failover, resumes, and later Brainstorm models. Keep all defaults finite.
2. Thread explicit finite/unlimited values through Chat, Brainstorm, Relay, persistence, and Relay resume state. Add tests for cancel-before-start, cancellation during execution, timeout/cancel/completion races, SIGTERM-resistant children, exception cleanup, and suppression of subsequent attempts.
3. Release the new relay version and raise the console dependency floor. Until then, the Chat UI may ship only the finite `5m`–`60m` choices because older relay code interprets `None` as the 300-second default.
4. Expose `none` in Chat, Brainstorm, and Relay; add the 80-column layout and isolation tests; document per-attempt semantics and the unchanged Scheduled Agents constraint.

### Acceptance criteria

- Existing users retain the 5m/15m/30m defaults unless they explicitly choose another value.
- Finite selections reach every provider attempt unchanged and still kill and reap the complete process group on expiry.
- `none` creates no watchdog, retains heartbeat output, and never produces a fabricated timeout.
- Stop kills and reaps the active Chat or Brainstorm child, prevents commits and later attempts, and reports cancellation only after cleanup finishes.
- Missing or corrupt Brainstorm state means 15 minutes; explicit JSON `null` alone means unlimited.
- Relay unlimited survives pause/Resume, while one-shot overrides do not mutate repository config.
- Chat timeout changes do not dirty Save, affect Brainstorm defaults, or alter Relay policy.
- Both the timeout selector and Save remain usable at 80 columns, and Scheduled Agents still reject unlimited.

**Recommendation:** ship the finite Chat selector immediately against the current relay contract, then ship honest unlimited operation only as one coordinated release containing authoritative Stop cancellation, the explicit sentinel migration, and Relay run-state persistence.

## Codex

# Configurable timeouts without weakening Stop

## Revised recommendation

Add a compact timeout selector to Chat's top context bar with **5m, 15m, 30m, 45m, 60m, and No limit**. Preserve the existing **5-minute Chat default**; the request is for choice, not an implicit behavior change. Keep Brainstorm's 15-minute and Relay's 30-minute defaults, while adding No limit to each surface separately.

The important prerequisite is unchanged: **No limit must not ship until Stop actually terminates the active agent process group**. Today the TUI's Chat/Brainstorm Stop path cancels presentation of the result but not the worker thread or vendor CLI. With the watchdog removed, a supposedly stopped job could continue spending tokens, changing files, committing, entering failover, or advancing to another brainstorm model.

## Current behavior and the real boundary

- Chat's `CHAT_TIMEOUT_SECONDS = 300` is used whenever the console omits `timeout_seconds`; the adapter currently omits it.
- Relay persists an integer `timeout_minutes`, defaults to 30, and accepts a finite `--timeout` override.
- Brainstorm already exposes 15/30/45/60 minutes and defaults to 15. Its value is a cap for each research, review, or synthesis agent invocation, not for the whole brainstorm.
- `agents.run` owns the common watchdog. It launches a separate process group and unconditionally arms a `threading.Timer`, so it is also the right layer for both genuine unlimited operation and authoritative cancellation.
- Scheduled Agents mode uses the same runner but is unattended and validates 1–240 minutes. Leave it finite and out of this feature.

The displayed timeout should be documented as **per agent attempt**. Failover and Grok resume behavior can cause one visible turn to contain multiple attempts, each receiving the same limit. Changing that into a whole-turn wall-clock budget would be a separate behavioral change.

## Product behavior

### Chat

Place `Timeout [5m ▾]` beside Agent in the context bar. The selector should apply immediately to the next Send and should not dirty or depend on the existing Agent/Model/Repo Save button. Capture its value when dispatch begins and disable it while the turn is running so a mid-turn change is not mistaken for altering an already-armed watchdog.

The selector is a Chat run preference, not Relay policy. It must never rewrite `.whyline/relay/config.toml`. Session-only behavior is sufficient for the first release; if it is persisted, put it in console/user preferences and fall back to 5m for missing or invalid data. A casual `No limit` Chat choice must not uncap a future unattended Relay.

Add keyboard parity with `/timeout`, `/timeout 30`, and `/timeout none`. `/timeout` reports the effective choice. Keep `5m` in the menu even though the request names 15/30/45, because removing it silently raises the current default.

The context bar already has an 80-column invariant. In narrow mode abbreviate the label to `T` or hide only the label, shrink the agent/model fields, and use a narrow closed select with a wider overlay. Extend the existing layout test to prove both the timeout control and Save remain reachable at 80 columns.

### Brainstorm

Add **No limit** to the existing dialog and text prompt, but keep the 15-minute default. The choice applies independently to every research, review, and synthesis invocation. Stop must kill the current process and prevent failover, resumes, or the next model from starting.

Brainstorm persistence needs three distinct states: missing/unset, a finite number, and explicit unlimited. Store unlimited as JSON `null` and use a sentinel for missing data; otherwise a missing timeout file can accidentally change from today's 300-second fallback to unlimited.

### Relay

Keep the repository's 30-minute default. Add No limit to the guided Relay setup/run control and to CLI/config parsing. Because the existing field is numeric, `timeout_minutes = 0` is a reasonable canonical config spelling; accept `--timeout 0` and optionally `--timeout none`, reject negatives, then normalize to `None` before calling the runner. Print a concise warning that a hung unattended turn has no automatic cutoff.

Persist Relay's effective choice in Relay state/config so pause and Resume do not silently restore 30 minutes. Do not reuse the Chat selector as a global timeout control: the three modes deliberately have different defaults and persistence risk.

## Engine contract

At the lowest layer:

- positive integer seconds arms the watchdog;
- `None` means no watchdog is created;
- zero or negative values are rejected before spawning the child.

Do not rely on `Timer(None)`, `Timer(0)`, or an enormous fake duration. Unlimited should mean no timer exists.

At higher layers, do not immediately redefine every existing `None`. `chat.run_turn(timeout_seconds=None)` currently means “use 300 seconds,” and Brainstorm also uses missing `None` values as fallback signals. Introduce an omitted-value or `NO_LIMIT` sentinel, migrate every caller explicitly, and only then consider simplifying the public signature. This prevents missing Brainstorm metadata or a falsey Relay value from silently becoming unlimited.

Add a per-dispatch cancellation event/handle to `agents.run`. When set, it should reuse the existing process-group termination path, escalate after the grace period, reap the child, and report a distinct `AgentCancelled` result. Timeout, cancellation, Ctrl+C, and normal completion should converge on idempotent cleanup so close races cannot double-signal or leak watchdog/cancellation threads.

The TUI holds one cancellation handle for the active dispatch. Stop sets it and still invalidates the dispatch token as protection against late rendering. Chat failover and Grok resume loops, plus Brainstorm's model loop, must check cancellation before starting another attempt. Stop should not claim completion until child cleanup is observed.

## Delivery order

1. Add cancellation and optional-watchdog semantics in `whyline-relay`, with race and process-tree tests. Keep all existing defaults finite.
2. Thread explicit finite/unlimited values through Chat, Brainstorm, Relay, failover, and resume paths. Preserve missing-versus-unlimited distinctions and publish a relay release.
3. Raise the console dependency floor, then add the Chat selector and `/timeout`, Brainstorm's No limit option, and Relay's own setting. The console must not show No limit against an older relay package that interprets it as the 300-second default.
4. Document that limits are per attempt, provider-side limits still apply, and scheduled Agents remain finite.

## Acceptance criteria

- Existing users still get 5m Chat, 15m Brainstorm, and 30m Relay unless they choose otherwise.
- Every finite Chat option reaches every provider attempt as the selected number of seconds and kills/reaps the full process group at expiry.
- No limit creates no watchdog and never reports a fabricated timeout.
- TUI Stop kills and reaps Chat/Brainstorm children, prevents subsequent attempts, and reports cancellation rather than timeout.
- Relay's No limit survives pause/Resume; `0` never becomes an immediate timer or falls back to Chat's 300 seconds.
- Missing Brainstorm timeout state stays distinct from explicit unlimited.
- Chat timeout changes do not dirty Save or alter Relay/Brainstorm defaults.
- The context bar still fits at 80 columns.
- Tests cover completion-versus-cancel and timeout-versus-cancel races, SIGTERM-resistant children, exception cleanup, failover/resume suppression, and the existing scheduled-Agent validation.

## Decision

Ship configurable finite values and honest No limit, with current defaults preserved. The implementation gate is authoritative cancellation: removing the watchdog before Stop controls the process would turn a usability improvement into an invisible runaway-process bug.

## Antigravity

# Revised Architecture Plan: Configurable & Unlimited Timeouts Across Chat, Relay, and Brainstorm

## 1. Executive Summary & Cross-Review Synthesis

Cross-review of initial passes from Codex, Grok, and Antigravity demonstrates complete consensus on the core hazard:
**"No limit" cannot be safely enabled until the TUI `Stop` button actively terminates child process groups.**
Today, `_stop()` only invalidates `_dispatch_token` in the UI thread; the underlying vendor CLI (`codex`, `claude`, `agy`) continues running to completion in the background. Without the watchdog timer, an uncapped agent would run indefinitely, spending tokens, modifying files, and locking git workspaces.

Furthermore, cross-review surfaces critical boundary corrections:
1. **Three Distinct Surfaces & Defaults**: Chat defaults to 5 minutes (interactive waiting), Brainstorm defaults to 15 minutes (sequential multi-model passes), and Relay defaults to 30 minutes (unattended loop). These intentional defaults must remain separate rather than collapsed into one global setting.
2. **Context Bar Isolation**: The Chat timeout dropdown must **never** dirty `#cb-save` or overwrite Relay's `.whyline/relay/config.toml`. It is a runtime execution preference for the interactive session, not a repository-wide Relay policy.
3. **Per-Attempt Semantics**: Timeouts apply **per agent attempt**, not to the entire multi-attempt turn or multi-model brainstorm. Grok resumes (`RESUMES = 2`), provider failovers, and Brainstorm sequential stages each receive their own attempt budget.
4. **The `None` Fallback Trap**: In today's codebase, `None` already signifies *"fallback to default (300s)"* in `chat.run_turn` and Brainstorm fallback paths. Passing `None` cannot casually become "unlimited" without an explicit sentinel migration, or missing metadata will silently uncap runs.
5. **Multi-Step Cancellation**: When `Stop` is pressed, cancellation must not only terminate the active process group, but also suppress subsequent failover attempts, Grok resumes, and downstream Brainstorm models.

---

## 2. Current State & Subsystem Analysis

### A. Chat: 300s Hardcoded Watchdog
- `whyline_relay/chat.py:125`: `CHAT_TIMEOUT_SECONDS = 300`.
- In `_execute_agent_call`: `timeout_seconds = CHAT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds`. Thus `None` currently triggers the 300s default.
- `src/whyline/console/adapters.py:run_chat_turn` omits `timeout_seconds`, binding all chat turns to 300s.
- Failover (`_attempt_call_with_fallback`) and Grok resumes (`RESUMES = 2` in `adapters/grok.py`) re-arm the same timeout for each attempt.

### B. Relay: 30m Unattended Default
- `whyline_relay/config.py:16`: `timeout_minutes: int = 30`.
- `whyline_relay/loop.py:167`: Multiplies `settings.timeout_minutes * 60` for each agent turn.
- CLI flag `whyline-relay --timeout <minutes>` overrides config for one run.
- `0` and negative values are currently invalid: `threading.Timer(0)` fires immediately, negative numbers raise `ValueError`, and truthy checks in `relay_ops` drop `0`, falling back to 300s.

### C. Brainstorm: 15m Per-Model Default
- `BRAINSTORM_TIMEOUT_OPTIONS = (15, 30, 45, 60)` in both `tui.py:94` and `brainstorm.py:497`.
- Persisted in `.whyline/relay/brainstorm-tmp/.timeout-<slug>.json`.
- Missing timeout file currently falls back to `None`, which `chat.py` converts to 300s. Unlimited must be serialized explicitly (as JSON `null`), distinct from missing state.
- Sequential execution: 4 models + review + synthesis = up to 9 separate attempts. The timeout applies to each individual model invocation.

### D. Process Runner & Cancellation Gap
- `whyline_relay/agents.py:run`: Spawns process with `start_new_session=True` and arms `threading.Timer(timeout_seconds, kill_group)`.
- In `src/whyline/console/tui.py:1706`: `_stop()` only sets `self._dispatch_token = object()` and calls `worker.cancel()`. As documented in `tui.py`, Python cannot interrupt blocking child process execution in worker threads; the child continues running until normal exit or watchdog termination.
- Scheduled Agents mode (`src/whyline/agents/definitions.py`): Requires 1–240 minutes. This unattended subsystem must remain strictly finite and excluded from "No limit".

---

## 3. Core Architecture & Safety Contract

### A. Authoritative Process Group Termination
Before exposing "No limit", `whyline_relay/agents.py` must support an explicit cancellation handle:
1. `agents.run` accepts an optional `cancel_event: threading.Event | None = None`.
2. A listener thread or poll check monitors `cancel_event`. If set before or during execution:
   - Immediately send `SIGTERM` to the process group (`-process.pid`).
   - If not terminated after `KILL_GRACE_SECONDS` (5s), escalate to `SIGKILL`.
   - Reap child process and raise `AgentCancelled(f"{argv[0]} cancelled by user")`.
3. Stop, timeout, and natural completion must converge idempotently so race conditions cannot leak threads or double-kill process groups.

### B. Cascading Cancellation Protection
In the console and runner layers:
- The active dispatch holds the `cancel_event`.
- `_stop()` in `tui.py` sets the event immediately, then bumps `_dispatch_token` to block late rendering.
- **Failover / Resumes**: `chat.py`'s failover loop and Grok's resume loop must check `cancel_event.is_set()` before launching any secondary attempt.
- **Brainstorm Loop**: `_brainstorm_in_thread` must abort immediately between passes if `cancel_event.is_set()`, preventing subsequent models from starting. Models that already committed remain committed.

### C. The Contract for Finite vs. Unlimited (Avoiding the `None` Trap)
To prevent unconfigured calls from silently becoming unlimited:
- **Low-level runner (`agents.run`)**:
  - `timeout_seconds: int | None`
  - Positive integer: arms `threading.Timer`.
  - `None`: no watchdog is armed (heartbeat still logs every 30s).
  - `<= 0`: raises `ValueError` immediately before spawning child.
- **Chat layer (`chat.run_turn`)**:
  - Introduce sentinel `NO_LIMIT = object()` (or `chat.UNLIMITED`).
  - `timeout_seconds=None` retains existing backward-compatible fallback to `CHAT_TIMEOUT_SECONDS` (300s).
  - `timeout_seconds=NO_LIMIT` explicitly forwards `timeout_seconds=None` to `agents.run`.
  - Positive integers forward as numeric seconds.
- **Brainstorm persistence**:
  - Serialized JSON: `{"timeout_seconds": null}` for No limit; `{"timeout_seconds": 1800}` for finite.
  - Missing file / corrupt JSON falls back to default sentinel (not No limit).
- **Relay config**:
  - TOML representation: `timeout_minutes = 0` denotes No limit (`timeout_minutes = 30` default).
  - CLI: `whyline-relay --timeout 0` or `--timeout none`.
  - Negative values rejected with `ConfigError`.
  - Relay prints a prominent warning at startup when running uncapped: *"Watchdog disabled: hung agent will run until stopped manually."*

---

## 4. UI/UX Design: Context Bar Dropdown & 80-Column Invariant

### A. Placement & Options
Add `#cb-timeout` to the top context bar in `src/whyline/console/tui.py`:
```python
yield Horizontal(
    Label("Agent", id="cb-agent-label"),
    Select(options, allow_blank=False, id="cb-agent"),
    Label("Model", id="cb-model-label"),
    Input(placeholder="default", id="cb-model"),
    Label("Timeout", id="cb-timeout-label"),
    Select(CHAT_TIMEOUT_OPTIONS, allow_blank=False, id="cb-timeout"),
    Label("Repo", id="cb-repo-label"),
    Input(id="cb-repo"),
    Checkbox("all repos", id="cb-global"),
    Button("Save", id="cb-save", disabled=True),
    id="context-bar",
)
```

**Options**:
- `5m` (300s) — **Default**, preserves existing behavior.
- `15m` (900s)
- `30m` (1800s)
- `45m` (2700s)
- `60m` (3600s) — Matches Brainstorm parity.
- `No limit` (`NO_LIMIT`)

### B. Strict State Isolation (No `#cb-save` Coupling)
- Selecting an option in `#cb-timeout` takes effect **immediately** on the next chat turn.
- Changing `#cb-timeout` does **not** dirty `#cb-save` and does **not** touch `.whyline/model.json`.
- `#cb-timeout` must **never** write to `.whyline/relay/config.toml`. A user picking "No limit" during interactive chat must never uncap a future unattended Relay run.
- Session persistence: keep in memory or in a dedicated local console preference (e.g. `.whyline/chat-timeout.json`), reloading per repo.
- During an active turn, `#cb-timeout` is disabled to prevent confusion over modifying an in-flight watchdog.

### C. Responsive Layout (80-Column Invariant)
The context bar must pass `tests/console/test_context_bar.py::test_the_bar_fits_80_columns`.
To fit the new selector:
- In `DEFAULT_CSS`:
  - Set `#cb-timeout { width: 8; }` and `#cb-timeout > SelectOverlay { width: 14; }`.
  - Reduce `#cb-model` default width from 18 to 12.
- In `_cb_fit()`:
  - Width >= 110: labels `Agent`, `Model`, `Timeout`, `Repo`.
  - Width < 110 (narrow): labels `A`, `M`, `T`, `R`; `#cb-agent` width 10; `#cb-timeout` width 8.
  - Width < 90 (compact): hide `#cb-timeout-label` completely; `#cb-timeout` displays compact values (`5m`, `15m`, `30m`, `45m`, `60m`, `None`).

### D. Keyboard & Brainstorm Dialog Parity
- **REPL / Slash Command**: Add `/timeout` (`/timeout`, `/timeout 30`, `/timeout none`) to both keyboard console and TUI input.
- **Brainstorm Dialog**: Update `#bs-timeout` in `BrainstormScreen` to include `("No limit", NO_LIMIT)`. If the context bar has a valid selection, pre-select it in the dialog.

---

## 5. Delivery Phasing & Implementation Order

Because `whyline-relay` is a separate package dependency, rollout must be sequenced cleanly:

1. **Phase 1: Cancellation & Runner Contract (`whyline-relay`)**
   - Add `cancel_event` support to `agents.run`. Implement `SIGTERM` -> grace period -> `SIGKILL` child process cleanup.
   - Introduce `AgentCancelled` exception.
   - Update `agents.run` to accept `timeout_seconds=None` as no timer, rejecting `<= 0`.
   - Add race-condition tests: cancel before start, cancel during run, cancel vs timeout expiry, cancel vs natural exit.

2. **Phase 2: Subsystem Contract Updates (`whyline-relay`)**
   - Implement `NO_LIMIT` sentinel in `chat.py`. Propagate `cancel_event` through failover and Grok resumes.
   - Add `timeout_minutes = 0` / `--timeout 0` support in `relay/config.py`, `loop.py`, and `cli.py` with unattended warning.
   - Update `brainstorm.py` to support `null` timeout serialization and abort model loop on cancellation.
   - Release new `whyline-relay` version.

3. **Phase 3: Console TUI & Integration (`whyline`)**
   - Bump `whyline-relay` dependency floor in `pyproject.toml`.
   - Add `#cb-timeout` dropdown to context bar, update `_cb_fit()`, verify 80-column layout test.
   - Connect TUI `_stop()` to set the active `cancel_event`.
   - Add `/timeout` slash command to REPL.
   - Add "No limit" to `BrainstormScreen`.

---

## 6. Acceptance Criteria

1. **Default Preservation**: Default timeout remains 5m in Chat, 15m in Brainstorm, and 30m in Relay unless explicitly changed.
2. **Authoritative Stop**: Clicking `Stop` in Chat or Brainstorm immediately terminates the child process group (verified by checking process table), raises `AgentCancelled`, and prevents subsequent model or failover execution.
3. **True Unlimited**: Selecting "No limit" does not arm a watchdog timer, does not raise fabricated timeouts, and logs periodic 30s heartbeats.
4. **Isolated Settings**: Chat timeout changes apply per turn, do not enable `#cb-save`, and never alter Relay's `config.toml`.
5. **Relay Zero Support**: Relay `timeout_minutes = 0` and `--timeout 0` run uncapped with startup warning; negatives raise `ConfigError`.
6. **Robust Brainstorm Serialization**: Stored `null` round-trips as No limit; missing files fall back to default, not unlimited.
7. **80-Column Layout Compliance**: The context bar with `#cb-timeout` and `#cb-save` renders cleanly within 80 columns across all terminal resize breakpoints.
8. **Scheduled Agents Safety**: Unattended scheduled agents remain bounded by 1–240 minutes and reject No limit.

## Grok

# Timeouts for chat, relay, and brainstorm

Chat gets a timeout menu on the top context bar: 5m, 15m, 30m, 45m, 60m, and none. Brainstorm and relay each gain none on the controls they already have. Defaults stay 5 minutes for chat, 15 for brainstorm, and 30 for relay. The number is the limit of one agent process, so failover and a Grok resume each spend it again. None stays off the menu until Stop kills that process group, reaps it, and refuses the next attempt.

## What the tree does now

Chat is 300 seconds because the console never passes a timeout. `CHAT_TIMEOUT_SECONDS` is 300, and `_execute_agent_call` substitutes it whenever `timeout_seconds` is omitted. `adapters.run_chat_turn` omits it. `run_turn` already forwards an explicit integer through failover, so the finite menu needs no runner change.

Grok can spend that budget more than once. A headless turn whose payload says `stopReason` `"cancelled"` — a permission-policy cancellation, not a timeout — is resumed up to `RESUMES = 2` extra times, and each call to `agents.run` receives the same `timeout_seconds`. The loop in `chat.py` already breaks when `exit_code != 0`, so a SIGKILL usually stops it. A SIGTERM that still exits 0 with a cancelled payload looks resumable. The loop has to check the cancel event before `resume_command`.

Relay stores an integer `timeout_minutes`, default 30. `start --timeout` is `type=int` and replaces it for that process only (`cmd_start` uses `if args.timeout is not None`, so `0` would be applied). `cmd_resume` loads config again and has no `--timeout` flag. `RelayState` and `PlanState` do not store a timeout, so a one-shot override disappears on Resume. `0` is not unlimited today: `threading.Timer(0, ...)` fires on its next turn, a negative interval makes `Event.wait` raise `ValueError`, and `relay_ops.plan_from_brainstorm` / `revise_synthesis` forward the timeout only when `timeout_minutes` is truthy. `0` is dropped, and chat turns the omission into 300 seconds.

Brainstorm's menu is `(15, 30, 45, 60)`, default 15, on `#bs-timeout` and in `parse_timeout_selection`. The keyboard console does not ask; `run_brainstorm` defaults to 15. The value is per attempt. Pass zero, each review, and synthesis are separate processes. It is stored as integer seconds in `.whyline/relay/brainstorm-tmp/.timeout-<slug>.json`.

`agents.run` requires an `int`, starts the child in its own session, and always calls `watchdog.start()`. The timer SIGTERMs the group and SIGKILLs it `KILL_GRACE_SECONDS` (5) later, then raises `AgentTimeout`. The `BaseException` path does the same kill and re-raises, which is how Ctrl+C in the keyboard console stops a foreground child. A silence heartbeat (`HEARTBEAT_SECONDS = 30`) starts separately whenever `echo=True`, including chat. It prints "still running" after output has been quiet for that long. It does not kill the child.

Scheduled Agents uses the same runner and rejects timeouts outside 1–240 minutes. That check stays.

Stop on a chat or brainstorm turn does not reach the kill. `_stop` replaces `_dispatch_token` and calls `worker.cancel()`. The worker runs on, and the token only drops the rendered result. The child pid stays inside `agents.run`. If the watchdog is removed first, Stop looks idle while the vendor CLI keeps running, and a normal return from `run` still reaches `commit_all` (or `commit_paths` for brainstorm) at the bottom of `_execute_agent_call`.

## None is already taken

`None` cannot become the spelling of unlimited. These sites already use it:

| Site | `None` means |
| --- | --- |
| `chat.run_turn` / `_execute_agent_call` | 300 seconds |
| `run_pass_zero` and the review/synthesis helpers | load the topic file; a missing file stays `None`, which chat turns into 300 seconds |
| `_load_timeout` | a missing file, corrupt JSON, and `"timeout_seconds": null` all return `None`, because `int(None)` is caught |
| `parse_timeout_selection` | invalid input. Empty input returns the 15 minute default, not `None` |
| `ask_brainstorm_setup` | the prompt loops `while timeout_seconds is None` |
| `chat.py` `/brainstorm` | replaces `None` with `DEFAULT_TIMEOUT_SECONDS` (15 minutes), then divides by 60 for the status line |
| `setup.py` | `if timeout_seconds is not None` drops it, so the caller default applies |
| `relay_ops` plan/revise | a falsey `timeout_minutes`, including `0`, is omitted and becomes 300 seconds |
| `agents.run` | not part of the contract. `Timer(None)` would sit forever only because `Event.wait(None)` blocks until cancelled |

Unlimited is a sentinel, `chat.NO_LIMIT`, and it is not `None`. Callers pass the sentinel through. The conversion to "do not start the timer" happens inside `agents.run`, at the `watchdog.start()` call. Converting any earlier makes `setup.py` drop it, and makes `/brainstorm` announce 15 minutes and run for 15 minutes.

`parse_timeout_selection` returns the sentinel for `none`, `no limit`, `unlimited`, and `0`. Its `None` stays "ask again". The `/brainstorm` status line prints `no limit` for the sentinel and does not divide it by 60.

A missing or unreadable brainstorm timeout file means 15 minutes, `DEFAULT_TIMEOUT_SECONDS`. It does not inherit the chat menu, and it does not become unlimited. The 300 second result today is only chat's omitted-argument fallback. Explicit unlimited is stored JSON `null`, and `_load_timeout` returns the sentinel for that payload, on a path that does not share the `except` used for corrupt files.

## Runner contract

`agents.run` takes `timeout_seconds: int | None` and an optional `threading.Event`.

- A positive integer arms the existing watchdog.
- `None` skips `watchdog.start()` and does not create a timer. The silence heartbeat still starts when `echo=True`.
- Zero and negative values raise `ValueError` before the child is spawned.
- The cancel event runs the existing SIGTERM-then-SIGKILL path and raises `AgentCancelled`. `AgentTimeout` stays the wording for a real cap, including `"exceeded {n}s"`.
- The `finally` block that already cancels both timers and joins the heartbeat also stops the cancel listener. Timeout, cancel, Ctrl+C, and a normal exit share that cleanup, so a timer firing as Stop is pressed does not leave a thread behind.
- `AgentCancelled` propagates out of `_execute_agent_call` before `commit_all` / `commit_paths`. A killed turn that returns a `RunResult` would still be committed.

The console holds one event for the active dispatch. `_stop` sets it, then bumps the token so a late result cannot render. The transcript says the turn is stopping during the grace period, and says Stopped only after `process.wait` returns. Failover, the Grok resume loop, and the brainstorm model loop check the event before the next attempt. Models that already committed stay committed; the transcript says the run was cut off from this model onward.

Provider CLIs can still end a turn on their own. This removes whyline's watchdog only.

## Chat menu

`#cb-timeout` is a Textual `Select` on `#context-bar`, beside Agent.

- `5m` is the initial value, and it is today's behavior
- `15m`, `30m`, `45m`, `60m`
- `none`, the sentinel

The closed label is `none`. The word `None` reads as an empty selection and collides with the fallbacks above.

Dispatch captures the value when Send starts. The select is disabled while that turn runs. It does not dirty `#cb-save`, and it is not part of `_cb_current` / `_cb_saved`. Save still means agent, model, and repo. The menu never writes `.whyline/relay/config.toml`.

The first release keeps the choice in session memory. A later file, if one is added, is a console preference, and missing or invalid data falls back to 5 minutes.

`/timeout` prints the effective choice. `/timeout 30` and `/timeout none` set it. Add `/timeout` to `_SLASH_HINT`. Keyboard `/stop` can stay as it is; Ctrl+C already enters the `BaseException` kill on a foreground turn.

`_cb_fit` switches labels to `A`, `M`, and `R` below 100 columns. The agent select is 24, or 14 when narrow. The model input is 18 and does not shrink. `#cb-repo` is the only `1fr`. `test_the_bar_fits_80_columns` only asserts `#cb-save`'s right edge. Make room inside that helper: a `T` label under the same 100-column break, a narrower model field, and a narrow closed select with a wider overlay, the same pattern as `#cb-agent > SelectOverlay`. Keep the control visible at 80 columns. Extend the test so `#cb-timeout` and `#cb-save` both end at or before column 80, and take the widths from that measurement.

In Relay mode the bar does not stand in for relay policy. Relay's number lives on its own screen and in its config.

## Brainstorm

Add `none` to `#bs-timeout`, to `ask_brainstorm_setup`, and to the keyboard prompt, which today skips the question and uses 15. All three still open on 15 minutes, or on the last brainstorm choice stored for that topic.

The dialog does not copy `#cb-timeout`. Chat's `5m` or `none` would change the per-attempt cap of a multi-model run from a different control. Stop during a brainstorm kills the current group and does not start the next model.

`_save_timeout` writes `{"timeout_seconds": null}` for the sentinel. It does not evaluate `timeout_seconds // 60` on that value.

## Relay

The config default stays 30 minutes. `timeout_minutes = 0` means unlimited. `--timeout 0` is the one-shot form. `--timeout none` needs a custom argparse type, because the flag is `type=int` today. Negatives are a `ConfigError`. After `config.load`, `0` means skip the timer. The two truthy checks in `relay_ops` forward the sentinel.

`cmd_start` will carry `0` into settings. `cmd_resume` will not, unless the effective value is on the run. Write it onto `RelayState` and `PlanState` at start, and have resume read that field. A one-shot override stays out of `config.toml`. A permanent change is an edit in relay setup or in the toml.

`RelaySetupScreen` sets roles, plan, release, and backup. It has no timeout field. Add one there, default 30, including none. That screen may write relay config. The chat menu may not.

A run that starts with no cap prints one line: a hung agent ends only by Stop or Ctrl+C.

Scheduled Agents stay on the 1–240 check. `timeout_minutes = 0` there remains a `DefinitionError`.

## Order

1. Cancellation and the optional watchdog in `whyline-relay`, with the sentinel carried through chat, failover, Grok resume, and brainstorm. Defaults stay finite. Tests cover cancel-before-start, cancel-during-run, timeout racing cancel, a child that ignores SIGTERM, exception cleanup, and resume/failover suppression.
2. Finite chat choices in the console against the current floor, `whyline-relay>=0.2.32,<0.3`. Pass an explicit `timeout_seconds`. Offer `5m` through `60m`. Leave `none` off the widget. On today's package, `None` still means 300 seconds, so a visible `none` would look selected and then die at the old cap.
3. Unlimited, relay `0`, brainstorm `null`, and the run-state field, in that same relay release. Raise the console floor, then show `none`.
4. Leave Agents-mode definitions alone.

## What I would not do

- Raise `CHAT_TIMEOUT_SECONDS` and stop there.
- Use one number for chat, relay, and brainstorm.
- Make `none` the default.
- Let the chat menu write relay config, or let `--timeout 0` write it either.
- Persist the chat selection in the first release.
- Copy the chat menu into the brainstorm dialog.
- Treat missing brainstorm state, invalid menu input, or a falsey relay value as unlimited.
- Implement unlimited as `Timer(None)`, `Timer(0)`, or a huge interval.
- Turn off the silence heartbeat. Unlimited skips `watchdog.start()` only.
- Treat scheduled Agents `timeout_minutes = 0` as legal.

## Verification

- `5m` still raises `AgentTimeout` at 300 seconds, with the current console wording.
- `15m`, `30m`, `45m`, and `60m` arrive as those integers, including on failover and on each Grok resume.
- `none` starts no watchdog. A process that exits on its own returns a normal result. A process that hangs dies only by Stop. The silence heartbeat still prints.
- Stop during chat, and during a later brainstorm model, SIGTERMs the group, SIGKILLs after 5 seconds if it is still alive, waits until the child is reaped, raises `AgentCancelled`, does not commit that attempt, and does not start another one.
- Existing relay toml at 30 minutes is unchanged. `0` and `--timeout none` skip the timer, warn once, and survive pause/Resume through run state. A negative value is a config error. Plan synthesis with `0` does not become 300 seconds.
- Brainstorm `null` round-trips as the sentinel. A missing or corrupt file runs at 15 minutes.
- Changing the chat timeout does not enable Save. At 80 columns, `#cb-timeout` and `#cb-save` both end at or before column 80.
- Agents-mode toml with `timeout_minutes = 0` is still a `DefinitionError`.

## Decision

Ship the finite chat menu on the current relay. Ship none only together with the cancel handle, the sentinel, and relay run-state. Keep the three defaults in three stores: session memory for chat, the topic file for brainstorm, and config plus the run record for relay.
