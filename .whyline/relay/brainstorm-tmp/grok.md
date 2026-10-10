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
