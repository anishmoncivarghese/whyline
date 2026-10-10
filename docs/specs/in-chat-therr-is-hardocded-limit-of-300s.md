# Configurable per-attempt timeouts

## Why

Chat is capped at 300 seconds because `adapters.run_chat_turn` never passes `timeout_seconds`, and `whyline_relay.chat._execute_agent_call` substitutes `CHAT_TIMEOUT_SECONDS` whenever the argument is omitted. Long analysis dies at that cap. Brainstorm already offers 15, 30, 45, and 60 minutes and defaults to 15. Relay stores `timeout_minutes` and defaults to 30. The three numbers are intentional: Chat is an attended wait, Brainstorm is one model in a sequence, and Relay is an unattended loop. This design lets each surface pick a longer cap, or no whyline kill timer, without collapsing those defaults into one setting.

`none` is unsafe on today's console. `WhylineConsoleApp._stop` replaces `_dispatch_token` and calls `worker.cancel()`. The vendor CLI keeps running, and a normal return from `agents.run` still reaches `gitcheck.commit_all` or `commit_paths`. Removing the watchdog before Stop kills that process would leave a background agent spending tokens and writing the tree. Finite choices can ship first, because `chat.run_turn` already forwards an explicit positive integer. Unlimited waits for one relay release that can cancel the process group, tell missing data from unlimited, and remember a one-shot Relay override across pause and Resume.

## Decisions

- Ship the Chat menu of 5, 15, 30, 45, and 60 minutes against `whyline-relay>=0.2.32,<0.3`. Show `none` only after the console depends on the relay release that implements cancellation, the sentinel, and run-state timeout.
- Keep the Chat choice in `ConsoleSession` for the life of the process. It does not dirty `#cb-save`, does not write `.whyline/model.json`, and does not write `.whyline/relay/config.toml`.
- Do not copy the Chat selection into Brainstorm. Brainstorm still opens on 15 minutes, or on the value stored for that topic. A missing or unreadable topic file is 15 minutes. Only JSON `{"timeout_seconds": null}` is unlimited.
- Spell Relay unlimited as `timeout_minutes = 0`. `--timeout 0`, `--timeout none`, and `--timeout unlimited` set that value for the current process and do not rewrite `config.toml`. Resume reads the effective value from `RelayState` and `PlanState`.
- The closed Chat label for unlimited is `none`. The widget value is the string `"none"`. Python `None` remains "omitted, use the finite default" at every existing call site.
- Convert unlimited to runner-level `timeout_seconds=None` only in the statement that calls `agents.run`. `agents.run` creates no `threading.Timer` when that argument is `None`, and raises `ValueError` before `Popen` when it is zero or negative.
- `whyline relay stop` cancels the in-flight agent. The STOP file, which today is checked only before the next task, sets the same cancel event the runner already uses. Console Stop for a Relay process stays `RelayProcess.interrupt()` (SIGINT). Both paths reap the child.
- `RelaySetupScreen` is the only console control that writes Relay's `timeout_minutes`. It uses a new `setup.write_timeout_minutes`, which commits like `write_release`. The Chat control never calls it.
- Scheduled Agents stay on the existing check in `whyline.agents.definitions`: `timeout_minutes` must be an integer from 1 to 240. Zero remains a `DefinitionError`.

## Design

### 1. Per-attempt contract

A timeout bounds one provider process: one `agents.run` call. It is not a budget for the visible turn.

- Chat failover in `chat.run_turn` gives the backup a fresh budget.
- Grok's permission-policy resume (`adapters.grok.RESUMES`, which is 2) gives each resume a fresh budget. The loop in `chat._execute_agent_call` and the loop in `loop.py` both check the cancel event before `grok.resume_command`. A SIGTERM that still exits 0 with `stopReason` `"cancelled"` must not resume after Stop.
- Brainstorm research, each review pass, and synthesis are separate attempts. `adapters.run_brainstorm`, `brainstorm.run_pass_zero`, `run_review_pass`, and `run_final_synthesis` each pass the same selected limit. Stop between models does not start the next model. Models that already committed stay committed.
- Provider CLIs can still end a turn on their own. This design removes whyline's kill timer only. The 30-second silence heartbeat (`agents.HEARTBEAT_SECONDS`) still starts when `echo=True`, including when no watchdog exists. It prints `... {name} still running ({duration})` and does not kill the child.

### 2. Runner cancellation and the watchdog

`agents.run` gains `cancel_event: threading.Event | None = None`. `timeout_seconds` becomes `int | None`.

- A positive `int` arms the existing `threading.Timer`. On fire it SIGTERMs the process group (`start_new_session=True` is unchanged) and SIGKILLs it `KILL_GRACE_SECONDS` (5) later, then raises `AgentTimeout` with the current text `{argv[0]} exceeded {n}s and was terminated`.
- `None` does not construct a timer and does not call `Timer(None)`, `Timer(0)`, or a stand-in large interval. The heartbeat still starts when `echo=True`.
- Zero, a negative number, or a `bool` raises `ValueError` before `Popen`.
- If `cancel_event` is already set after the binary lookup and before `Popen`, `run` raises `AgentCancelled` and does not spawn.
- Otherwise a listener thread waits on `cancel_event` and on a private `stop_listener` event. The wait slice is 50 milliseconds, so Stop is not blocked on the heartbeat. When `cancel_event` is set, the listener uses the same kill path as the watchdog. `finally` sets `stop_listener` and joins the listener, the heartbeat thread, and cancels any timer.
- `begin_kill()` is guarded by a lock and a one-shot flag. Timeout, cancel, and the existing `BaseException` path (Ctrl+C in the foreground REPL, and SIGINT delivered to a Relay process) share that flag, so a timer firing as Stop is pressed sends one SIGTERM and arms one SIGKILL.
- After `process.wait` returns, if `cancel_event` is set, raise `AgentCancelled(f"{argv[0]} cancelled by user")`. Else if the watchdog fired, raise `AgentTimeout`. Else return `RunResult`. Cancel wins when both fire. `KeyboardInterrupt` is re-raised, not turned into `AgentCancelled`.
- `AgentCancelled` is a `RuntimeError` sibling of `AgentTimeout`. The child has been reaped before either exception leaves `run`.

`chat._execute_agent_call` checks `cancel_event` at the start of each Grok resume iteration and again immediately before `commit_paths` / `commit_all`. On a set event it raises `AgentCancelled` and does not commit that attempt. The earlier `ensure_permission_files` commit is unchanged: it happens before the child starts and only covers generated permission files. `chat.run_turn` lets `AgentCancelled` propagate. It does not treat cancellation as a failover reason, does not write another backup override, and does not call `chatlog.append`.

`adapters.run_chat_turn` catches `AgentCancelled` and returns `SessionEvent(kind="error", text="Stopped.")`. `AgentTimeout` keeps the current wording `{error} -- try again, or /model another agent.`

The TUI holds one `threading.Event` on the app for the active Chat or Brainstorm dispatch, created in `_dispatch_text` before `run_worker` and passed through `dispatch` into `run_chat_turn` or `run_brainstorm`. `_stop` sets that event, writes `Stopping…` to the transcript, then replaces `_dispatch_token` so a successful result cannot render. It does not call `_set_busy(False)` yet. The worker, after `AgentCancelled`, uses `call_from_thread` to render `Stopped.` and clear busy only when the app's event is still that same object. A newer dispatch replaces the event, so a late cancel cannot clear the new turn. `_send` already refuses a second Chat send while busy, so the user cannot start that newer dispatch until Stop finishes. `#cb-timeout` is disabled for that same busy interval and enabled when busy clears. A Relay run does not disable it and does not read it.

Brainstorm's model loops (`run_pass_zero`, `run_review_pass`, `run_final_synthesis`, `generate_plan_from_synthesis`, `revise_synthesis`) take the same event and return before the next model when it is set. `adapters.run_brainstorm` checks it between research, review, and synthesis. The transcript line is `Stopped.` plus which phase did not start. Work already committed by an earlier model stays committed.

### 3. Sentinel versus omitted None

`None` already means a finite fallback. Those sites keep that meaning.

| Site | `None` means |
| --- | --- |
| `chat.run_turn` / `_execute_agent_call` | 300 seconds |
| Brainstorm pass helpers when the argument is omitted | load the topic file |
| `_load_timeout` on a missing or corrupt file | missing, which callers turn into 900 seconds |
| `parse_timeout_selection` | invalid input; the prompt asks again. Empty input returns the default, not `None` |
| `setup.py` `if timeout_seconds is not None` | drop the argument so the callee default applies |
| `relay_ops.plan_from_brainstorm` and `revise_synthesis` | omit `timeout_seconds` so Brainstorm loads the topic file |

`chat.NO_LIMIT` is a module-level sentinel object. It is not `None`. Callers pass it through `setup.py`, the Brainstorm helpers, and `chat.run_turn`. The line that calls `agents.run` maps it:

- argument omitted (`None`) at `chat._execute_agent_call` becomes `CHAT_TIMEOUT_SECONDS` (300)
- `NO_LIMIT` becomes `None` (no timer)
- a positive `int` is forwarded
- zero or negative raises `ValueError` before the child, including inside Chat. Chat does not treat 0 as unlimited. Only Relay config does, and Relay converts 0 to `None` before `agents.run`

`/brainstorm`'s status line prints `no limit` for the sentinel and does not divide it by 60.

The falsey drops that would turn 0 into Chat's 300 seconds are rewritten:

- `relay_ops.plan_from_brainstorm` and `revise_synthesis`: `timeout_minutes is None` still omits the keyword. A positive int still passes `timeout_minutes * 60`. `0` passes `timeout_seconds=chat.NO_LIMIT`.
- `loop.py` passes `None` when `settings.timeout_minutes == 0`, otherwise `timeout_minutes * 60`. It never passes 0 into `agents.run`.

### 4. Chat selector and `/timeout`

Add `#cb-timeout-label` and `#cb-timeout` to `#context-bar`, immediately after `#cb-model` and before the Repo label. `#cb-timeout` is a Textual `Select` with `allow_blank=False`.

Finite options, which are the widget values:

- `5m` → `300` (initial value; today's behavior)
- `15m` → `900`
- `30m` → `1800`
- `45m` → `2700`
- `60m` → `3600`

The later release adds `none` → the string `"none"`. The closed label is `none`.

`ConsoleSession.chat_timeout_seconds` stores the widget value (`int` or `"none"`) and starts at `300`. Changing the select writes that field immediately. Send captures the field into the worker closure, so a change after Send does not rewrite an armed watchdog. The select is not part of `_cb_current` or `_cb_saved`. `_cb_dirty` stays agent, model, repo, and the "all repos" checkbox. Save still writes only those.

`adapters.run_chat_turn` gains `timeout_seconds`. The TUI and `repl._dispatch` pass the session value. The adapter maps `"none"` to `chat.NO_LIMIT` and an `int` through as seconds. Any other stored value is treated as `300`. The mapping of `"none"` exists only in the console release that depends on the relay release. Until that floor moves, the select has no `"none"` row, and `/timeout none` does not call the relay.

`/timeout` is handled in `repl.handle_slash_command`, so the TUI and the keyboard console share it. Add it to `_SLASH_HINT`, `SLASH_COMMANDS`, and `_COMMAND_HELP`.

- `/timeout` prints `Chat timeout: 5m. Each attempt gets this limit.` or `Chat timeout: none. Each attempt has no whyline kill timer.`
- `/timeout 5`, `5m`, and the same forms for 15, 30, 45, and 60 set that choice and move `#cb-timeout` when it is mounted.
- `/timeout none`, `unlimited`, `0`, and `no limit` set `"none"` once the row exists. Before that, they reply `No limit is not available yet. Choose 5, 15, 30, 45, or 60 minutes.` and leave the previous value.
- Any other argument replies `Usage: /timeout [5|15|30|45|60|none]` and leaves the previous value.

Keyboard `/stop` stays as it is. A foreground REPL turn is interrupted by Ctrl+C, which already enters the `BaseException` kill in `agents.run`. The user cannot type `/stop` while that turn blocks the prompt.

In Relay mode the bar is still the Chat preference for the next Chat send. Relay's number is the setup screen, `config.toml`, and the run record.

### 5. Brainstorm

`BRAINSTORM_TIMEOUT_OPTIONS` stays `(15, 30, 45, 60)` until the `none` release, then the select `#bs-timeout` gains `("none", "none")`. `collect_brainstorm` accepts that value. A finite choice still returns `timeout_minutes` as that integer and `timeout_unlimited: False`. `none` returns `timeout_unlimited: True` and omits a fake minute count. The dialog does not read `#cb-timeout`.

The keyboard prompt in `repl._brainstorm_prompts` asks, which it does not today. The question is `Per-agent timeout: 15 (default), 30, 45, 60 minutes, or none [15]: `. Empty input is 15, or the stored topic value when one exists. `parse_timeout_selection` returns `chat.NO_LIMIT` for `none`, `no limit`, `unlimited`, and `0`. Its `None` still means "ask again". Menu numbers 1–4 and the minute values 15, 30, 45, and 60 stay. `ask_brainstorm_setup` uses the same parser. The `while timeout_seconds is None` loop remains valid because invalid input is still `None` and the sentinel is not.

`_save_timeout` writes `{"timeout_seconds": null}` for the sentinel and does not add `timeout_minutes`. A positive int still writes `{"timeout_seconds": N, "timeout_minutes": N // 60}`.

`_load_timeout` distinguishes three outcomes:

- missing file, unreadable file, invalid JSON, a non-object payload, a missing `timeout_seconds` key, or a `timeout_seconds` that is not a positive int and not JSON `null`: missing. Callers substitute `DEFAULT_TIMEOUT_SECONDS` (900) before `chat.run_turn`. They do not pass `None` through to Chat's 300-second fallback.
- `timeout_seconds` JSON `null`: `chat.NO_LIMIT`
- a positive integer: that many seconds

The dialog and the keyboard prompt pre-select 15 when the load is missing, the stored minute value when it is 15, 30, 45, or 60, and `none` when the load is the sentinel. A stored positive value outside that menu, such as 300, pre-selects 15 and does not grow a one-off row.

`adapters.run_brainstorm` gains `timeout_unlimited: bool = False`. When true, every attempt gets `chat.NO_LIMIT` and the topic file stores null. When false, it passes `timeout_minutes * 60` as it does now. `plan_job` forwards `timeout_unlimited` from the brainstorm choice into `plan_from_brainstorm` and `revise_synthesis`.

### 6. Relay config, CLI, setup, and resume

`config.load` keeps the default `timeout_minutes` of 30. The loaded value must be an `int` and not a `bool`, and it must be `>= 0`. Zero means unlimited. Anything else raises `ConfigError` with `timeout_minutes must be 0 (no limit) or a positive number of minutes`. A missing key stays 30.

`--timeout` uses a custom argparse type. `none` and `unlimited` (any case) and an integer `>= 0` are accepted. A negative value is an argparse error. `cmd_start` already applies the flag with `if args.timeout is not None`, so `0` is kept. That replacement is not written to `config.toml`.

When the effective value is 0, `cmd_start` and `cmd_resume` print one stderr line before the first task: `Watchdog disabled: a hung agent runs until you stop it.` Chat sends do not print it.

`RelayState` and `PlanState` gain `timeout_minutes: int | None = None`. Old state files omit the key and still load. `None` means "this record predates the field; Resume uses `config.load`." A stored `0` or a stored positive int is the effective cap. `_save_pause` and the planner's `_checkpoint` write `settings.timeout_minutes`, including 0. `cmd_resume` and `planner.resume` do `replace(settings, timeout_minutes=saved.timeout_minutes)` when the saved field is not `None`.

`RelaySetupScreen` gains `#rs-timeout`, a `Select` defaulting to the loaded config. The rows are 15, 30, 45, and 60 minutes, plus `none`. If the file holds some other positive integer, that integer is an extra selected row so opening the screen does not snap 20 to 30. Start writes the choice only when it differs from the file, through `setup.write_timeout_minutes(root, minutes)`, which replaces a top-level `timeout_minutes = …` line or inserts one, then commits through the existing `_write_config` helper. `none` writes `0`. Cancel does not write. `relay_ops.save_timeout` is the console wrapper.

The in-flight Relay attempt watches `.whyline/relay/STOP`. When the file appears, the turn's `cancel_event` is set. `AgentCancelled` becomes `loop.Paused` with the cancellation text, and `_save_pause` records the effective timeout. Resume continues from that record. `whyline relay stop`'s help text becomes `Stop the current agent and do not start another.` The check before the next task stays, so a STOP file also prevents a later task if the current one already finished. Console Stop keeps calling `interrupt()` and does not depend on the file.

### 7. Scheduled Agents

No change. `definitions.load` still raises `DefinitionError("timeout_minutes must be between 1 and 240")` for 0, negatives, and values above 240. The Agents screens keep a finite integer field. They do not gain `none`.

### 8. Eighty-column context bar

`_cb_fit` keeps its 100-column break.

Below 100 columns the labels are `A`, `M`, `T`, and `R`. `#cb-agent` is 10 (it is 14 today). `#cb-model` is 12 (it is 18 today). `#cb-timeout` is 8. At 100 columns and above the labels are `Agent`, `Model`, `Timeout`, and `Repo`, `#cb-agent` stays 24, `#cb-model` stays 18, and `#cb-timeout` is 10.

`#cb-timeout > SelectOverlay` is 14, the same pattern as `#cb-agent > SelectOverlay`. The closed control stays narrow. The timeout control is not removed at 80 columns. `#cb-repo` stays `width: 1fr`.

`tests/console/test_context_bar.py::test_the_bar_fits_80_columns` asserts both `#cb-timeout` and `#cb-save` have `region.right <= 80`.

## Error handling

- `agents.run` rejects a non-positive `timeout_seconds` with `ValueError` before the child exists. Callers are not expected to catch this and retry; it is a programming error. Relay never passes 0 through.
- A bad `timeout_minutes` in `config.toml` fails `config.load` with `ConfigError` before a task starts. The existing doctor and start paths already surface `ConfigError` text.
- `--timeout -1` fails argparse. The process does not start and the file is unchanged.
- `AgentTimeout` and `AgentCancelled` stay distinct. The console timeout sentence is only for `AgentTimeout`. Stop says `Stopping…` and then `Stopped.`
- A cancel that arrives after the child has exited but before `commit_all` still skips the commit, because `_execute_agent_call` checks the event immediately before committing.
- A cancel during the five-second grace period does not render `Stopped.` until `process.wait` has returned. The listener, heartbeat, and timers are joined in `finally` on the success path, the timeout path, the cancel path, and the `BaseException` path.
- Failover, a Grok resume, and the next Brainstorm model do not start once the event is set. An attempt that already committed is left committed.
- A missing or corrupt Brainstorm timeout file runs that topic at 900 seconds. It does not become unlimited and it does not inherit the Chat menu.
- An old `state.json` or `plan-state.json` without `timeout_minutes` resumes at the repository config value, which is 30 unless the file says otherwise.
- A paused run written by the new relay and then resumed by an older relay fails `RelayState(**record)` on the unknown key. `state.load` already turns that `TypeError` into `None`, so the old relay reports nothing to resume. The console floor moves forward with the relay release so a current console does not pause a run that its own relay cannot read.
- Scheduled Agents `timeout_minutes = 0` remains `DefinitionError`, not an uncapped run.

## Testing

Relay package tests, next to the existing `agents.run` coverage:

- Cancel before `Popen` does not spawn and raises `AgentCancelled`.
- Cancel during `readline` SIGTERMs the group, SIGKILLs a child that ignores SIGTERM after 5 seconds, reaps it, and raises `AgentCancelled`.
- A timeout and a cancel in the same grace period produce one SIGTERM, one SIGKILL timer, `AgentCancelled`, and no leftover threads.
- A normal exit racing a cancel either returns `RunResult` with no kill, or raises `AgentCancelled` after reap, and does not raise both.
- `timeout_seconds=None` starts no `Timer`. A process that exits returns `RunResult`. The heartbeat still prints when `echo=True`. Zero and `-1` raise `ValueError` and do not spawn.
- `chat.run_turn(timeout_seconds=None)` still uses 300. An explicit 900, 1800, 2700, and 3600 reach every failover attempt and each Grok resume. `NO_LIMIT` reaches `agents.run` as `None`. `AgentCancelled` from the first attempt does not call the backup and does not commit.
- Brainstorm `{"timeout_seconds": null}` round-trips as `NO_LIMIT`. A missing file and a truncated JSON file yield 900. `_save_timeout` of the sentinel does not write a minutes field derived by division.
- `timeout_minutes = 0` loads. A negative and a boolean fail `ConfigError`. `--timeout none` sets 0 and does not change the toml. `loop` passes `None` to `agents.run`. Plan synthesis with `0` passes `NO_LIMIT`, not an omitted argument.
- A start with `--timeout 0` pauses, and Resume without the flag still passes `None` to `agents.run`. A start with no flag pauses, and Resume keeps 30. A state file without the new key resumes at the config value.
- Creating the STOP file during `agents.run` cancels that child and pauses with the timeout field stored.
- An Agents definition with `timeout_minutes = 0` still raises `DefinitionError`.

Console tests in this repo:

- `test_the_bar_fits_80_columns` covers `#cb-timeout` and `#cb-save` at 80×24.
- Changing `#cb-timeout` leaves `#cb-save` disabled when agent, model, and repo are unchanged, and does not write `config.toml` or `.whyline/model.json`.
- Send passes 300, 900, 1800, 2700, or 3600 into `run_chat_turn`. The select disables while the worker runs. A value captured at Send is the one passed, even if the select changes before the fake run returns.
- `/timeout`, `/timeout 30`, and `/timeout 45m` update the session and the select. An unknown value does not. Before the `none` release, `/timeout none` leaves 300 and returns the "not available yet" error.
- After the floor bump, `/timeout none` and the `none` row pass `chat.NO_LIMIT`. A Brainstorm dialog choice of `none` sets `timeout_unlimited` and does not read the Chat select. The keyboard prompt defaults to 15 when the Chat session is `none`.
- TUI Stop during a fake in-flight `agents.run` sets the event, and the rendered success from the old token is dropped. The `Stopped.` line is recorded once the cancel path finishes.
- `RelaySetupScreen` writes `timeout_minutes = 0` only for `none`, writes a positive integer for a finite row, and does not write on Cancel.

## Releases

1. **whyline-relay, defaults still finite.** Add `cancel_event`, `AgentCancelled`, optional watchdog, `chat.NO_LIMIT`, Brainstorm null-versus-missing, Relay `0` and `--timeout none`, the run-state field, and STOP-file cancellation of the in-flight child. Publish this as the next `0.2.x` release. The console floor stays `whyline-relay>=0.2.32,<0.3`.

2. **Console finite Chat menu, on that same floor.** Add `#cb-timeout` with `5m` through `60m`, `/timeout` without a working `none`, the 80-column assertion, and Save isolation. `/timeout none` returns the not-available error. Brainstorm's dialog and Relay's setup screen do not gain `none` in this release.

3. **Console unlimited, after the floor moves.** Raise both `whyline-relay` bounds in `pyproject.toml` (the project dependency and the `dev` group) to `>=` the release from step 1, still `<0.3`, and refresh `uv.lock`. Then show `none` on `#cb-timeout`, `#bs-timeout`, the keyboard Brainstorm prompt, and `#rs-timeout`. `/help` states that the limit is per attempt, that provider limits still apply, and that Scheduled Agents accept only 1–240 minutes.
