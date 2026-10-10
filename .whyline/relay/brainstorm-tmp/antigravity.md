# Research & Architecture Plan: Configurable & Unlimited Timeouts Across Chat, Relay, and Brainstorm

## Executive Summary

When using complex reasoning agents (such as Codex Plus deep analysis, Antigravity multi-step tool calls, or Claude full-repo reviews), Whyline Chat currently cuts off turns at a hardcoded **300 seconds (5 minutes)**, aborting with `AgentTimeout: codex exceeded 300s and was terminated`. In contrast, Relay allows setting `timeout_minutes` in `config.toml` (defaulting to 30 minutes) or via `--timeout`, while Brainstorm prompts for 15, 30, 45, or 60 minutes.

The user's request is twofold:
1. Provide an option to **remove the timeout limit** entirely ("No limit") or select timeouts such as 15m, 30m, 45m across Chat and Relay.
2. Place a **dropdown on top** in the console (similar to the Agent selector) so the user can easily select the turn timeout or choose "No limit".

### The Critical Architectural Insight
Removing the timeout limit or raising it to 45m+ introduces an immediate, severe hazard into the current console codebase:
**The Console's `Stop` button currently does not terminate child processes.**

As documented in `src/whyline/console/tui.py:1707-1716`:
> *"whatever `_dispatch_in_thread` is running right now will still run to completion — Python cannot forcibly interrupt it — but its result will no longer match `self._dispatch_token` when it finally returns, so `render_event` is never called for it."*

Currently, the **only** safeguard preventing a runaway or looping background agent process from running indefinitely and burning tokens/credits is the hardcoded watchdog timer (300s in Chat, 15m in Brainstorm). If "No limit" is introduced without first making `Stop` kill the active process group:
- Clicking `Stop` will clear the UI "thinking" spinner, but the underlying vendor CLI (`codex`, `claude`, `agy`) will silently run forever in the background.
- Subsequent chat turns will collide with the hidden background process over workspace files, Git locks, and API rate limits.

**Core Recommendation:**
Implement configurable timeouts (`5m`, `15m`, `30m`, `45m`, `No limit`) across Chat, Brainstorm, and Relay, placing a dedicated dropdown on the top context bar. However, this must be gated on **authoritative process group cancellation** so that clicking `Stop` immediately sends `SIGTERM`/`SIGKILL` to the running agent process group.

---

## 1. Codebase Audit: Current State

### A. Chat Timeout Architecture
- **Hardcoded Constant**: In `whyline_relay/chat.py:125`:
  ```python
  CHAT_TIMEOUT_SECONDS = 300
  ```
- **Fallback Logic**: In `whyline_relay/chat.py:191-193`:
  ```python
  timeout_seconds=(
      CHAT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
  )
  ```
  Note that passing `timeout_seconds=None` is currently interpreted as *"fallback to 300s"*, which prevents `None` from meaning "unlimited".
- **Console Dispatch**: In `src/whyline/console/adapters.py:run_chat_turn`, `chat.run_turn()` is called with no `timeout_seconds` argument, so every chat turn is bound to 300s.
- **Error Handling**: When the watchdog fires, `whyline_relay/agents.py` sets `timed_out` and raises `AgentTimeout(f"{argv[0]} exceeded {timeout_seconds}s and was terminated")`, which `adapters.py` formats as an error event.

### B. Relay Timeout Architecture
- **Configuration Defaults**: In `whyline_relay/config.py:16`:
  ```python
  DEFAULTS = {"timeout_minutes": 30, ...}
  ```
- **Execution**: In `whyline_relay/loop.py:167`:
  ```python
  timeout_seconds=settings.timeout_minutes * 60
  ```
- **CLI Flag**: `whyline-relay --timeout <minutes>` overrides config.
- **Limitations**: `Config.timeout_minutes` is typed as `int` and expects positive values. There is currently no syntax to specify "unlimited" (e.g. `timeout_minutes = 0` or `"none"`).

### C. Brainstorm Timeout Architecture
- **Options**: `TIMEOUT_OPTIONS = (15, 30, 45, 60)` in `whyline_relay/brainstorm.py:497` and `src/whyline/console/tui.py:94`.
- **UI Screen**: Textual dialog `BrainstormScreen` renders:
  ```python
  Select([(f"{m} minutes", m) for m in BRAINSTORM_TIMEOUT_OPTIONS], value=15, id="bs-timeout")
  ```
  It has no option for 5 minutes or "No limit".

### D. Process Execution & Watchdog
- In `whyline_relay/agents.py:run`:
  ```python
  process = subprocess.Popen(
      argv,
      cwd=str(cwd),
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      ...,
      start_new_session=True,  # Creates a new POSIX session / process group
  )
  ...
  watchdog = threading.Timer(timeout_seconds, kill_group)
  watchdog.start()
  ```
  `timeout_seconds` is passed directly to `threading.Timer`. If `timeout_seconds` is `None` or non-numeric, it raises a TypeError.
- **Heartbeat Reporting**:
  `agents.py` already includes an excellent background heartbeat thread reporting every 30s:
  `... codex still running (12m30s)`.
  This heartbeat is ideal for long or unlimited runs, keeping the user informed of elapsed time.

---

## 2. Safety Prerequisite: Authoritative Process Cancellation

Before enabling "No limit" or long timeouts (30m+), the console's `_stop()` routine must be upgraded from passive token invalidation to active process termination.

### Why Passive Cancellation Fails
Currently, in `src/whyline/console/tui.py:1706`:
```python
def _stop(self) -> None:
    self._dispatch_token = object()
    for worker in self.workers:
        worker.cancel()
    self._set_busy(False)
```
Textual workers running synchronous blocking code (like `subprocess.Popen.wait()` or reading stdout in `agents.run`) cannot be interrupted by `worker.cancel()`. The thread continues to run until the child process terminates on its own or the watchdog kills it.

### Required Architecture Fix
1. **Runner Cancellation Handle / Callback**:
   `agents.run()` can accept an optional cancellation registration callback or `threading.Event`, or register the active process handle in a session context:
   ```python
   # In agents.py or console adapter:
   def cancel_current_turn():
       if active_process and active_process.poll() is None:
           signal_group(signal.SIGTERM)
           threading.Timer(KILL_GRACE_SECONDS, signal_group, args=(signal.SIGKILL,)).start()
   ```
2. **Hooking into `tui.py:_stop()`**:
   When the user clicks `Stop`, `self._stop()` should invoke `cancel_current_turn()`.
   This ensures that clicking `Stop` actively terminates the agent's process tree within 5 seconds, making "No limit" completely safe.

---

## 3. UI/UX Design: Top Context Bar Dropdown

The user requested:
> *"put option on top somewhere kind of a drop down like agent where its drop down, user can select say timeout 15, 30, 45 or no limit"*

### A. Context Bar Placement
In `src/whyline/console/tui.py:1370`, the context bar is composed as:
```python
yield Horizontal(
    Label("Agent", id="cb-agent-label"),
    Select(options, allow_blank=False, id="cb-agent"),
    Label("Model", id="cb-model-label"),
    Input(placeholder="default", id="cb-model"),
    Label("Timeout", id="cb-timeout-label"),              # NEW
    Select(TIMEOUT_OPTIONS, allow_blank=False, id="cb-timeout"),  # NEW
    Label("Repo", id="cb-repo-label"),
    Input(id="cb-repo"),
    Checkbox("all repos", id="cb-global"),
    Button("Save", id="cb-save", disabled=True),
    id="context-bar",
)
```

### B. Dropdown Values & Display Options
```python
CHAT_TIMEOUT_OPTIONS = [
    ("5m", 300),
    ("15m", 900),
    ("30m", 1800),
    ("45m", 2700),
    ("No limit", None),
]
```
- **Default for Chat**: `5m` (300 seconds), preserving existing responsiveness while making higher tiers 1 click away.
- **Semantic Meaning of `None`**: Represents unlimited / watchdog disabled.
- **Immediate Effect vs Save**:
  - Selecting an option in `#cb-timeout` immediately updates `session.timeout_seconds` for subsequent chat turns in the current session.
  - Clicking `Save` (`#cb-save`) persists the choice to `.whyline/relay/config.toml` under `chat_timeout_minutes` (or `chat_timeout_seconds`).

### C. Responsive Width & Space Management (`_cb_fit()`)
The context bar already implements screen width adaptation in `_cb_fit()`:
```python
def _cb_fit(self) -> None:
    narrow = self.size.width < 110
    compact = self.size.width < 90
    self._main("#cb-agent-label", Label).update("A" if narrow else "Agent")
    self._main("#cb-model-label", Label).update("M" if narrow else "Model")
    self._main("#cb-timeout-label", Label).update("T" if narrow else "Timeout")
    self._main("#cb-repo-label", Label).update("R" if narrow else "Repo")
    self._main("#cb-timeout", Select).styles.width = 10 if narrow else 14
```
Styling in `DEFAULT_CSS`:
```css
#cb-timeout { width: 14; }
#cb-timeout > SelectOverlay { width: 18; }
```
On screens under 90 columns, `#cb-timeout-label` collapses to `"T"` and the dropdown displays short tokens (`"5m"`, `"15m"`, `"30m"`, `"45m"`, `"∞"` or `"None"`), preventing layout overflow.

### D. Keyboard / CLI Accessibility
In addition to the dropdown, provide a fast slash command in Chat:
- `/timeout 15` -> Sets session timeout to 15 minutes.
- `/timeout none` or `/timeout 0` -> Sets session timeout to No limit.
- `/timeout` -> Prints current timeout setting.

---

## 4. Subsystem Contract Updates

### A. Core Runner: `whyline_relay/agents.py`
Update `run()` signature and watchdog logic:
```python
def run(
    command: list[str],
    prompt: str,
    *,
    cwd: Path,
    log_path: Path,
    timeout_seconds: int | None = None,  # None means unlimited
    ...
) -> RunResult:
```
Watchdog arming:
```python
watchdog = None
if timeout_seconds is not None and timeout_seconds > 0:
    watchdog = threading.Timer(timeout_seconds, kill_group)
    watchdog.start()
```
And cleanup in `finally`:
```python
if watchdog is not None:
    watchdog.cancel()
```
If `timeout_seconds is None`, no timer fires, but the heartbeat thread continues reporting every 30 seconds (`... codex still running (7m30s)`), giving the user visibility.

### B. Chat Layer: `whyline_relay/chat.py`
Define a sentinel for unconfigured vs explicitly unlimited:
```python
_DEFAULT_TIMEOUT = object()

def run_turn(
    ...,
    timeout_seconds: int | None | object = _DEFAULT_TIMEOUT,
    ...
):
    if timeout_seconds is _DEFAULT_TIMEOUT:
        effective_timeout = CHAT_TIMEOUT_SECONDS  # 300
    else:
        effective_timeout = timeout_seconds  # May be None for No limit, or custom int
```
When `effective_timeout is None`, it is forwarded to `agents.run(timeout_seconds=None)`.

### C. Relay Layer: `whyline_relay/config.py` & `loop.py`
In `config.py`:
- Allow `timeout_minutes` to be parsed from TOML as `int | None`.
- Support `timeout_minutes = 0` or `timeout_minutes = "none"` in TOML to mean unlimited.
In `loop.py`:
```python
timeout_seconds = (
    settings.timeout_minutes * 60
    if settings.timeout_minutes and settings.timeout_minutes > 0
    else None
)
```
In `cli.py`:
- `whyline-relay --timeout 0` or `--timeout none` sets `timeout_minutes = None`.

### D. Brainstorm Layer: `whyline_relay/brainstorm.py` & `tui.py`
Update `BRAINSTORM_TIMEOUT_OPTIONS`:
```python
BRAINSTORM_TIMEOUT_OPTIONS = (15, 30, 45, 60, None)
```
- In UI Select options: `[(f"{m} minutes", m) if m else ("No limit", None) for m in BRAINSTORM_TIMEOUT_OPTIONS]`.
- In `_load_timeout` and `_save_timeout`: serialize `None` or `0` cleanly.

---

## 5. Comparative Trade-off Analysis

| Timeout Model | Pros | Cons / Risks | Recommended Decision |
|---|---|---|---|
| **Status Quo (Fixed 300s)** | Prevents hanging processes, predictable cost | Aborts legitimate complex tasks (Codex Plus, Antigravity, deep refactors) | **Reject:** Actively breaks user workflows on complex prompts |
| **Global Blanket Bump (e.g. 15m for all)** | Simple to change in 1 line | Still arbitrary; does not let user choose No limit or preserve fast failure | **Reject:** Fails user's explicit request for choice and No limit |
| **Config-only (TOML setting)** | No UI space required | Inflexible per-turn; forces user to edit TOML file to run one long task | **Reject:** Poor UX for interactive chat |
| **Context Bar Dropdown + Stop Process Kill (Proposed)** | Instant per-turn control, clean visual feedback, supports both fast turns & unlimited deep reasoning safely | Requires responsive styling in context bar and process group cancellation plumbing | **Adopt:** Fully satisfies user request while resolving underlying safety gap |

---

## 6. Implementation Plan & File Touchpoints

### Phase 1: Safety & Process Termination Plumbing
- `src/whyline_relay/agents.py`:
  - Update `run()` to accept `timeout_seconds: int | None`. Only start `watchdog` if `timeout_seconds > 0`.
  - Provide process registration / cancellation callback for active turn.
- `src/whyline/console/adapters.py` & `repl.py`:
  - Hook active child process tracking into session.
- `src/whyline/console/tui.py`:
  - In `_stop()`, invoke process group cancellation before resetting UI state.

### Phase 2: Engine & Contracts Update
- `src/whyline_relay/chat.py`:
  - Support `timeout_seconds: int | None = None` where `None` means unlimited, without forcing 300s fallback when explicitly passed.
- `src/whyline_relay/config.py`, `cli.py`, `loop.py`:
  - Support `timeout_minutes = 0` / `"none"` for Relay.
- `src/whyline_relay/brainstorm.py`:
  - Add `None` ("No limit") to brainstorm timeout options.

### Phase 3: Console TUI Context Bar & UX
- `src/whyline/console/session.py`:
  - Add `timeout_seconds: int | None = 300` to `ConsoleSession`.
- `src/whyline/console/tui.py`:
  - Add `#cb-timeout-label` and `#cb-timeout` Select dropdown to `#context-bar`.
  - Add options: `("5m", 300)`, `("15m", 900)`, `("30m", 1800)`, `("45m", 2700)`, `("No limit", None)`.
  - Update `_cb_fit()` for narrow terminal layout.
  - Wire `on_select_changed` to update `session.timeout_seconds`.
  - Wire `#cb-save` to persist `chat_timeout_seconds` in `.whyline/relay/config.toml`.
  - Add `BrainstormScreen` support for `"No limit"`.
- `src/whyline/console/repl.py`:
  - Add `/timeout` slash command.

### Phase 4: Automated Verification & Testing
- Unit test in `tests/agents/test_runner.py`: verify `agents.run(..., timeout_seconds=None)` runs to completion without arming watchdog.
- Unit test in `tests/console/test_adapters_whyline.py`: verify `run_chat_turn` forwards `timeout_seconds` (including `None`) to `chat.run_turn`.
- TUI integration test in `tests/console/test_tui.py`: verify `#cb-timeout` renders, selection updates session timeout, and `_cb_fit()` handles narrow columns without crashing.
- Process cancellation test: verify clicking `Stop` terminates a running child process within grace period.
