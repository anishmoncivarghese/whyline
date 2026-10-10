# Brainstorm: In chat therr is hardocded limit of 300s after which its timeout, relay has configurable and same wityh brainstoprm, I want an option to remove the limit first or put o[tion on top  somewhere kimnd of a drop down like agent where its drop down , user can select say timeout 15, 30 , 45 or no limit, simiallry in relay dezfult is 30 mins here its self we can remove the limit as well. Think about it

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

Independent pass on this request: the chat turn dies at a hardcoded 300 seconds, relay and brainstorm already expose a timeout, and the console should let someone pick 15, 30, or 45 minutes, or no limit, from a top dropdown like the agent menu. Relay's own 30 minute default should be removable in the same way.

The limits are real, they do not share one setting, and "no limit" is not safe to turn on until Stop actually kills the child. A finite dropdown can be wired through the API that already exists. Unlimited cannot.

## What each surface does today

### Chat is fixed at 5 minutes, and `None` already means that

`whyline_relay/chat.py` sets `CHAT_TIMEOUT_SECONDS = 300`. `_execute_agent_call` passes that value whenever the caller omits `timeout_seconds`:

```python
timeout_seconds=(
    CHAT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
),
```

So `None` is the default, not "unlimited". The chat REPL design (`docs/superpowers/specs/2026-09-26-chat-repl-design.md`) says this was deliberate and temporary: shorter than the relay because a person is waiting, "not user-configurable in v1 — YAGNI until someone hits it." Long turns now hit it. The constant is the thing to replace.

The console never passes a timeout. `adapters.run_chat_turn` calls `chat.run_turn` with agent, prompt, and attachments only. Every TUI chat turn and every keyboard-console chat turn therefore gets 300 seconds. `run_turn` already accepts `timeout_seconds` and forwards it through failover, so 15, 30, or 45 minutes can be selected from the console without changing the runner. Only "no limit" needs a new runner contract.

Grok may spend that budget more than once. A cancelled headless Grok turn is resumed up to `RESUMES = 2` extra times (`adapters/grok.py`), and each attempt calls `agents.run` with the same `timeout_seconds`. A 5 minute selection can occupy the console for about 15 minutes of Grok resumes before it is reported as a timeout. The dropdown should be described as the limit of one process attempt.

### Relay is 30 minutes, stored, and overridable

`whyline_relay/config.py` defaults `timeout_minutes` to 30. `config.load` does `int(raw.get("timeout_minutes", 30))` and does not check the range. `whyline relay start --timeout MIN` (`cli.py`) replaces that integer for one invocation. `loop.py` always does `timeout_seconds=settings.timeout_minutes * 60` for each agent turn.

`0` and negatives are not a hidden unlimited mode:

- `threading.Timer(0, ...)` runs the callback on its next chance, so the agent is killed immediately.
- A negative interval makes `threading.Event.wait` raise `ValueError`.
- `relay_ops.plan_from_brainstorm` and `revise_synthesis` only forward the timeout when `timeout_minutes` is truthy. `0` is dropped, the brainstorm helper then passes `None`, and chat turns that into 300 seconds.

The relay default should stay 30 minutes. Unattended runs are why that number exists. Removing the cap is an explicit choice on top of it.

### Brainstorm already has a menu, and it is not the chat menu

Two copies of the same list:

- Console: `BRAINSTORM_TIMEOUT_OPTIONS = (15, 30, 45, 60)` in `src/whyline/console/tui.py`, default 15, widget `#bs-timeout`. `collect_brainstorm` rejects anything else.
- Relay's own prompt: `TIMEOUT_OPTIONS = (15, 30, 45, 60)` and `DEFAULT_TIMEOUT_MINUTES = 15` in `whyline_relay/brainstorm.py`. `parse_timeout_selection` accepts those minutes or menu numbers 1–4.

The keyboard console does not ask. `_brainstorm_prompts` in `repl.py` calls `adapters.run_brainstorm` without `timeout_minutes`, and that function's default is 15.

The comment above the console tuple says the bound exists so one stalled provider cannot hold the console for the whole multi-model run. A brainstorm is sequential: pass zero, then each review pass, then synthesis. Four models and one review pass is nine process attempts. The menu is a per-attempt cap, not a cap on the whole brainstorm.

Chosen values are written to `.whyline/relay/brainstorm-tmp/.timeout-<slug>.json` as integer seconds. `_load_timeout` does `int(...)`. `_save_timeout` does `timeout_seconds // 60`. If the file is missing, `run_pass_zero` leaves `timeout_seconds` as `None`, and its docstring says the turn then keeps chat's current limit, which is 300 seconds. A stored "no limit" that fails `int()` takes the same path. Unlimited has to be a real stored value, or a resumed brainstorm silently becomes a 5 minute turn.

### One watchdog, four callers

`whyline_relay/agents.py` `run()` starts the child in its own session (`start_new_session=True`) and arms `threading.Timer(timeout_seconds, kill_group)`. On fire, the timer SIGTERMs the process group and SIGKILLs it `KILL_GRACE_SECONDS` (5) later, then raises `AgentTimeout`. The same kill runs if the parent is unwound by `BaseException`, which is how Ctrl+C stops a foreground turn: the child is in another session, so SIGINT never reaches it unless this handler runs.

Scheduled Agents mode is a fourth caller and should stay out of this control. `src/whyline/agents/definitions.py` requires `timeout_minutes` between 1 and 240, default 15, and `src/whyline/agents/runner.py` passes `defn.timeout_minutes * 60` into the same `run()`. Those jobs are unattended. A hung nightly agent with no watchdog never releases its lock. Leave that validator as it is.

## Stop does not mean the same thing in every mode

The Stop button in `tui.py` (`on_button_pressed`, around the `stop` id):

- A relay this console started gets `RelayProcess.interrupt()`, which sends SIGINT to the relay process. `agents.run` catches that as `BaseException` and kills the agent process group. The run pauses and Resume continues it.
- A relay started somewhere else gets `relay_ops.interrupt_live_run`, same SIGINT, or a `STOP` file on Windows. The `STOP` file is only noticed between turns. The in-turn kill is the signal.
- Anything else, including chat and brainstorm, calls `_stop()`.

`_stop` replaces `_dispatch_token`, calls `worker.cancel()`, and clears the busy flag. Its own comment says the worker still runs to completion because Python cannot interrupt it, and the token check only drops the result so `render_event` is not called. `worker.cancel()` does not see the child. The child pid lives on the stack inside `agents.run`, in the `whyline-relay` package, and the console never receives it.

Consequences if the watchdog is removed first:

- Stop makes the transcript look idle while Claude, Codex, Grok, or Antigravity keeps running, spending the session and holding the repo.
- The turn still commits when it finishes. Chat commits the whole dirty tree (`commit_all`) unless the caller passed `commit_paths`. Brainstorm commits its owned paths as each model returns. The user sees those commits after Stop.
- A brainstorm continues into the next model. `_brainstorm_in_thread` is one worker for the whole sequence. Dropping the token does not break the loop.
- Failover can still start the backup agent after the user pressed Stop.
- The keyboard console is in better shape for a single turn. Dispatch is synchronous, Ctrl+C enters `agents.run`'s `BaseException` handler, and the group is killed. `/stop` there only prints "Nothing in flight to stop." because nothing is in the background. Keyboard brainstorm is also on the main thread, so Ctrl+C aborts the sequence (`except Exception` in `run_pass_zero` does not swallow `KeyboardInterrupt`). The TUI has no equivalent.

Relay "no limit" is a different risk. The console can already cut off the current agent. A relay started from a terminal and then left alone cannot. The 30 minute timer is the only hang protection for that run. Keep it as the default, and say so when a run is started with the cap off.

## `None` must not be reused

Three layers already use "missing" for three different defaults:

| Call | Omitted timeout means |
| --- | --- |
| `agents.run` | Required `int`. `None` is not part of the contract. `Timer`'s wait happens to treat `None` as "wait until cancelled", which would skip the kill only by accident of `Event.wait`, and the type and the error string both assume a number. |
| `chat.run_turn` / `_execute_agent_call` | `None` becomes 300 seconds. |
| `brainstorm.run_pass_zero` and the review/synthesis helpers | `None` loads the per-topic file, and a missing file stays `None`, which chat turns into 300 seconds. |
| `relay_ops` plan/revise helpers | `timeout_minutes` of `0` or `None` omits the argument, so the same 300 second fallback applies. |

If `chat.run_turn(..., timeout_seconds=None)` starts meaning unlimited, every brainstorm path that forgets the file, and every plan synthesis that passes a false timeout, becomes an unbounded turn. That is the wrong migration.

Recommended contract:

- `agents.run` takes `timeout_seconds: int | None`. `None` does not start the timer. `<= 0` raises `ValueError` in the parent, before any child is spawned. The success path is unchanged. The timeout error string stays `"exceeded {n}s"` and is only raised when a timer was armed.
- Add `AgentCancelled`, raised on the same SIGTERM-then-SIGKILL path when a cancel event fires. The console can say "Stopped." `AgentTimeout` stays the wording for a real cap.
- `chat.run_turn` keeps `None` as "use `CHAT_TIMEOUT_SECONDS`" until every caller passes an explicit value. Add a single sentinel, for example `chat.NO_LIMIT`, that is not `None`, and pass `timeout_seconds=None` into `run_fn` only for that sentinel. Finite integers pass through as they do now.
- Do not encode unlimited as a huge integer. It still fires, the message claims the agent "exceeded" a number the user never chose, and some platforms reject very large timer intervals.

Relay config can use `0` as the human-facing spelling, because TOML and `--timeout` are integers and the user asked to remove the limit on the setting they already have. Translate `0` to "do not arm the timer" inside `cmd_start` / the loop, after validation. Reject negatives with `ConfigError`. Fix the two `if timeout_minutes` sites so `0` is forwarded as `NO_LIMIT` rather than dropped. Default remains 30. `--timeout 0` is the one-shot form. Print one line when a relay run actually starts with no cap: Stop or Ctrl+C is the only thing that ends a hung agent.

Brainstorm's JSON should store `{"timeout_seconds": null}` for no limit. `_load_timeout` returns `None` for that payload and a missing file stays "unset". Callers must distinguish the two. `_save_timeout` must accept null. `parse_timeout_selection` should accept `none`, `no limit`, `unlimited`, and `0`.

## The dropdown

Put a Textual `Select` in `#context-bar`, the same row as `#cb-agent`, because that is the control the request points at. Suggested id `#cb-timeout`.

Options, short enough for an 80-column terminal:

- `5m` — current chat behavior, the initial value
- `15m`
- `30m`
- `45m`
- `60m` — brainstorm already offers this; dropping it would be a regression for that dialog
- `none` — no watchdog

The request lists 15, 30, 45, and no limit as examples. Starting the list at 15 would also raise today's default from 5 minutes to 15. Keep 5 minutes as the default so an unchanged console behaves as it does now.

Behavior, which should differ from the agent menu:

- Apply on change. The agent menu dirties Save and writes `.whyline/model.json` only when Save is pressed. A timeout chosen and then forgotten until after Send would still die at 300 seconds. This control is a run parameter, not a repo default, so it must not toggle `#cb-save` and must not be part of `_cb_current` / `_cb_saved`.
- Persist immediately per repo, in a file that relay config does not read. Something like `.whyline/chat-timeout.json` with `{"seconds": 300}` or `{"seconds": null}` is enough. Reload it on repo switch. A chat selection of `none` must not write `timeout_minutes = 0` into `.whyline/relay/config.toml`.
- Scope it to chat. In Relay mode the bar can show the relay's configured minutes as a separate label, or a relay-only override that becomes `--timeout` for the next `start` in this console. It should not rewrite the toml. Chat's 5 minute preference and the relay's 30 minute policy are different numbers on purpose.
- Add `/timeout` for the keyboard console and for a narrow terminal: `/timeout`, `/timeout 30`, `/timeout none`. `/stop` in the keyboard REPL can stay as it is; Ctrl+C is already the kill. The TUI slash hint (`_SLASH_HINT`) should mention `/timeout`.

Layout is the part most likely to break. The context-bar spec and `tests/console/test_context_bar.py::test_the_bar_fits_80_columns` require `#cb-save` to end at or before column 80. Below 100 columns, `_cb_fit` already shrinks labels to `A`, `M`, and `R`. Widths that do not shrink: agent select 14, model input 18, the "all repos" checkbox, Save. The repo field is the only `1fr`. A new select of width 10 plus a label probably pushes Save past 80.

Fit it by shrinking, not by hiding the control at the width people actually use (the spec calls 80 the standard). Drop the model input to 12 and the narrow agent select to 10, use a label `T` under 110 columns and no label under 90, and give `#cb-timeout` a width of about 8 with a wider overlay, the same pattern as `#cb-agent > SelectOverlay`. Extend the 80-column test to cover the new widget. If Save still overflows, the checkbox label is the next thing to shorten. Do not ship the dropdown on a row that fails that test.

Brainstorm keeps its own field inside the dialog. A brainstorm is many attempts, and the dialog comment is right that the bound should stay visible there. Add `("No limit", None)` or a dedicated sentinel to `BRAINSTORM_TIMEOUT_OPTIONS`, and initialize `#bs-timeout` from the bar when the bar's value is one of those options. The relay text prompt and `parse_timeout_selection` grow the same choice. The keyboard console should ask the same question, defaulting to the persisted chat value, instead of silently using 15.

## Order of work

The watchdog is the only thing that ends a TUI chat or brainstorm child. Ship the kill path before `none` does anything.

1. **Cancellation handle in `whyline-relay`.** `agents.run` takes an optional `threading.Event`. When it is set, run the existing `kill_group` path and raise `AgentCancelled`. Plumb the event through `chat.run_turn` and the brainstorm runners. The console holds one event for the active dispatch token. `_stop` sets it, then still bumps the token so a late result cannot render. Between brainstorm models, check the event and do not start the next one. Models that already committed stay committed; the transcript should say that Stop cut off the run from this model onward. This is useful even while the cap is still 300 seconds, because Stop currently lies.

2. **Finite chat choices in the console only.** After step 1, or in parallel if `none` stays disabled, pass an explicit `timeout_seconds` from the bar through `run_chat_turn`. 15, 30, 45, and 60 minutes work against today's `whyline-relay`. The package floor in `pyproject.toml` is `whyline-relay>=0.2.32,<0.3`. Unlimited and the cancel event are a relay release; the console cannot invent them by passing `None`.

3. **Unlimited, relay `0`, and brainstorm `none`.** Land these in the same relay release as the cancel event. Gate the `none` option in the console on a relay version that understands the sentinel. Until then the option can be absent, not present-and-ignored. Ignoring it would look like a successful selection and then die at 300 seconds.

4. **Leave Agents-mode definitions alone.** Same runner, different product. Positive 1–240 stays required.

## What I would not do

- Only edit `CHAT_TIMEOUT_SECONDS` to 900 or 1800. The next long turn hits the new constant, and there is still no per-turn choice.
- One global number for chat, relay, and brainstorm. The interactive default is 5 minutes, the brainstorm default is 15, the relay default is 30. The bar remembers a chat preference. Relay keeps `config.toml`. Brainstorm shows the per-attempt cap in its own dialog and may default from the bar.
- Make `none` the default. The request is for an option to remove the limit.
- Rely on `Timer(None)` as the implementation of unlimited. Skip the `watchdog.start()` call.
- Let the chat bar write relay config. A person who picks `none` while chatting would otherwise uncapped the next unattended relay run.
- Treat scheduled Agents `timeout_minutes = 0` as legal while doing this. That cap protects jobs with nobody at the keyboard.

## Verification when this is implemented

- A chat turn with `5m` still fails at 300 seconds through `AgentTimeout`, and the console text stays the current "try again, or /model another agent."
- `15m`, `30m`, `45m`, and `60m` are the integers `run_turn` receives. Failover and each Grok resume receive the same integer.
- `none` calls `agents.run` with no timer. A process that exits on its own still returns a normal `RunResult`. A process that ignores the work is killed only by Stop.
- Stop during chat and during the second model of a brainstorm SIGTERMs the group, SIGKILLs after 5 seconds if needed, renders a cancelled result, and does not start another model. The keyboard Ctrl+C path still kills the group.
- Relay `timeout_minutes = 30` is unchanged for existing toml. `timeout_minutes = 0` and `--timeout 0` skip the timer and print the one-line warning. A negative value is a config error. `timeout_minutes = 0` used by plan synthesis does not collapse to 300 seconds.
- Brainstorm persistence round-trips null. A missing file does not become unlimited.
- `#cb-save`'s right edge is still at or before column 80, and changing the timeout does not enable Save.
- Agents-mode toml with `timeout_minutes = 0` is still a `DefinitionError`.
