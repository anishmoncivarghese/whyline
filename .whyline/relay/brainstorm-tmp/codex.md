# Configurable agent-turn timeouts

## Recommendation

Replace Chat's hidden five-minute cutoff with a visible per-agent-turn timeout control, and support the same explicit **No limit** choice in Chat, Brainstorm, and Relay. Keep finite defaults: **30 minutes for Chat and Relay, 15 minutes for Brainstorm**. “No limit” should mean no automatic deadline, not an unstoppable process: the user must always be able to press Stop and actually terminate the agent process group.

Do not implement No limit as an enormous number. Make unlimited a real value in the process API, and first fix cancellation so Stop kills the underlying process. Otherwise an unlimited Chat or Brainstorm can remain alive invisibly after the UI says it stopped.

## What exists now

- Chat is hard-coded in `whyline_relay.chat` as `CHAT_TIMEOUT_SECONDS = 300`. The console adapter calls `chat.run_turn()` without its optional `timeout_seconds`, so every Chat turn is killed after five minutes.
- The engine is already close to supporting a console choice: `chat.run_turn(..., timeout_seconds=...)` forwards an override to the agent call.
- The lowest-level runner, `whyline_relay.agents.run`, still requires an integer and unconditionally starts a `threading.Timer`. It cannot currently express unlimited execution.
- Relay reads `timeout_minutes` from `.whyline/relay/config.toml`, defaults to 30 minutes, and supports a finite `start --timeout MIN` override. There is no No limit representation.
- Brainstorm already has a visible 15/30/45/60-minute dropdown and passes that duration through every phase. It has no No limit option.
- The TUI's Stop behavior differs by mode. Relay interruption sends SIGINT to the relay, whose runner terminates the child process group. Chat and Brainstorm run inside a Textual worker thread; cancelling that worker only suppresses the eventual UI result. It does not interrupt the Python thread or kill the agent child. The existing finite timeout eventually cleans it up; No limit would remove that last safety net.

This is therefore a two-repository change. `whyline-relay` owns process supervision and timeout semantics; `whyline` owns the console controls and preference UX.

## Product design

### Chat

Add a compact **Timeout** select to the top context bar beside Agent, visible in Chat mode:

`Timeout [30 min ▾]`

Options should be:

- 5 minutes
- 15 minutes
- 30 minutes
- 45 minutes
- 60 minutes
- No limit

Thirty minutes is a better default than five for coding-agent work and matches Relay, while preserving five minutes as an option for quick questions. The label or help text should say **per agent turn** so users do not mistake it for a whole-session limit. For No limit, show concise explanatory copy such as “Runs until the agent finishes or you press Stop.”

Capture the selected value when Send is pressed. Disable the selector while that turn is running, because changing it cannot alter a watchdog that has already started. Re-enable it when the turn finishes or is stopped.

Remember the user's last Chat choice in the existing personal console preferences, rather than committing it to the repository. Timeout tolerance is primarily a user/machine preference, while Relay's unattended policy belongs to the repository. Use an unambiguous serialized value such as `"unlimited"`; do not use zero, which is easy to interpret as an immediate timeout. Missing or invalid data should fall back to 30 minutes.

The 80-column layout is already deliberately tight and tested. At narrow widths shorten `Timeout` to `T`, give its select a compact width, and let Repo surrender space. Add an 80-column regression test proving Save remains reachable.

The keyboard console should have parity through a command such as `/timeout 30` and `/timeout none`; `/timeout` alone reports the current choice. This also gives a precise, scriptable alternative when the full-screen select is unavailable.

### Brainstorm

Extend the existing dropdown to include **No limit**. Keep 15 minutes as its default because a brainstorm runs many agent turns and a finite per-agent bound prevents one provider from holding the entire multi-phase job indefinitely.

No limit applies separately to each research, review, and synthesis turn. The UI should state this. Brainstorm Stop must terminate the currently running agent before this option ships; merely discarding the result is insufficient.

### Relay

Keep Relay's 30-minute default. Add **Per-agent timeout** to the guided Run/Set up screen, using the same choices plus No limit. Persist the selection in relay configuration so Resume uses the same policy; a start-only command-line override can otherwise silently revert after a pause.

Also accept an explicit CLI/config representation, preferably:

- `whyline relay start --timeout 45`
- `whyline relay start --timeout none`
- `timeout_minutes = 45`
- `timeout_minutes = "none"`

Normalize these at the configuration boundary to `int | None`. The UI can display `None` as No limit. Relay is often unattended, so selecting No limit should show an inline caution, not a blocking confirmation: “No automatic cutoff; this run waits until the agent finishes or you stop it.” Heartbeats and elapsed time should continue normally.

Do not put one global timeout selector across all modes. Chat, Brainstorm, and Relay have different risk and persistence semantics. Reusing the same option labels and internal value contract provides consistency without letting a casual Chat preference silently change an unattended Relay.

## Engine contract

Use one meaning throughout the engine:

- positive integer seconds: install an automatic watchdog;
- `None`: install no watchdog;
- zero or negative: reject at validation boundaries.

At present `chat.run_turn(timeout_seconds=None)` means “use the five-minute default,” which conflicts with the desired meaning of `None`. Remove that ambiguity. For example, make the omitted Chat default an integer (`timeout_seconds=1800`) and reserve explicit `None` for unlimited, or use a private sentinel to distinguish omitted from explicitly unlimited. A sentinel is safer if backward compatibility matters for third-party callers.

Update `agents.run` so it creates, starts, cancels, and joins a watchdog only for a finite timeout. Do not approximate unlimited with a multi-year timer; that produces misleading errors and can hit platform timer limits.

Add a real cancellation channel to the runner, such as a thread-safe event watched by a small cancellation thread. When signalled, it should terminate the same process group used by timeout handling, escalate to SIGKILL after the existing grace period, reap the child, and raise a distinct `AgentCancelled` outcome rather than `AgentTimeout`. On Windows, use the runner's existing platform-safe termination path. Timeout, manual cancellation, Ctrl+C, and normal completion must converge on one idempotent cleanup routine so races do not double-signal or leak threads.

The console should create one cancellation token per Chat/Brainstorm job and pass it all the way to `agents.run`. Stop sets the token, waits for or observes cleanup, and only then reports the job stopped. Continue invalidating the dispatch token as a defense against late UI callbacks, but do not treat that as process cancellation.

## Delivery sequence

1. **Fix process supervision in whyline-relay.** Add unlimited timeout semantics, real cancellation, idempotent cleanup, and tests. Keep the public default behavior finite during this step.
2. **Thread the value through relay workflows.** Update Chat, Brainstorm, Relay config, CLI parsing, start/resume state, and every agent-run call. Publish a new `whyline-relay` release.
3. **Add whyline console UX.** Raise the dependency floor, add the Chat context-bar selector and `/timeout`, add No limit to Brainstorm, and add Relay's setting to the guided screen.
4. **Document and release.** Explain that all values are per agent turn, defaults remain finite, and Stop remains available under No limit. Mention that provider-side limits and subscription limits still apply even when Whyline's own deadline is disabled.

## Acceptance criteria

- A Chat turn can run beyond 300 seconds when 15, 30, 45, 60, or No limit is selected.
- Finite choices terminate the whole child process group at the selected duration and report the actual duration.
- No limit creates no watchdog timer and never emits an artificial timeout.
- Stop during an unlimited Chat or Brainstorm kills and reaps the actual agent process; no hidden child or worker remains.
- Relay No limit survives pause, console exit, and Resume; finite overrides also resume with the same effective value.
- Chat's preference survives console restart, while changing it does not alter Relay or Brainstorm defaults.
- Existing malformed preference/config files fall back safely with a clear message.
- The Chat context bar and open selector remain usable at 80 columns.
- Automated tests cover completion-versus-cancel and timeout-versus-cancel races, a child that ignores SIGTERM, Windows fallback behavior, failover attempts, and cleanup after exceptions.

## Decision

Ship the dropdowns and No limit, but gate them on genuine cancellation. The strongest version of this feature is not simply “replace 300 with a larger number”; it is a consistent supervision model in which automatic deadlines are user-configurable, unlimited is honest, and manual Stop always remains authoritative.
