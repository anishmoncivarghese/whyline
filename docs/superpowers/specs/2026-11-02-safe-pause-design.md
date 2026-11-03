# Safe pause: pause a running relay without losing work

Date: 2026-11-02. Plans:
- whyline-relay: `~/whyline-relay/plans/safe-pause.plan.md` (RPZ-1..5), released first
- agentdock: `plans/safe-pause.plan.md` (PZ-1..9)

## Problem

The user wants to pause a running relay on purpose and continue later. For example, they're about to close the lid or the battery is low.

Today the only control is **Stop**. Stop sends Ctrl+C, or writes `.whyline/relay/STOP`, which a watcher acts on within about 0.1 s. Either way it kills the working agent mid-turn:
- The agent's edits stay on disk.
- The turn's handoff is never written.
- On Resume the turn starts again from scratch, and the new agent isn't told about the half-done edits.

What the user asked for, in their words:
- A **Pause** button while the relay runs.
- Once pressed, the relay pauses and a **Resume** button appears in its place. Resume continues the relay.
- Pausing must be "a proper pause so that nothing is lost".
- Where progress % is shown, it should say the pause is in progress ("pausing work so nothing is lost"), then "paused". That way the user knows what is happening and why there is a delay.

## What the user gets

1. **The Pause button.** While a relay runs, the relay controls show **Pause** next to Stop. The button then moves through these states:

   | State | Buttons | Status line (replaces the progress text, % stays) |
   |---|---|---|
   | Running | **Pause** · Stop | `RCH-3 · round 2 · reviewer codex · 45%` (today's line) |
   | Pausing | **Pausing…** (disabled) · **Pause now** · **Keep going** | `⏸ Pausing — letting codex finish its turn so nothing is lost (1m 20s so far)` |
   | Paused by you | **Resume** · Stop | `⏸ Paused by you at RCH-3, round 2 — press Resume to continue` |

   - **Keep going** withdraws the pause request; the relay just carries on.
   - **Pause now** cuts the turn off, as Stop does today, after a one-line confirm. It also records which files that turn changed (see 3).
   - **Resume** is the existing Resume. After a safe pause it starts the *next* turn, from the handoff that was just written, so nothing is redone.
2. **A safe point.** A pause takes effect only between agent turns: after the working agent finishes, its handoff is saved and its stage's result is recorded, and before the next agent starts. The relay then saves its state with the reason `paused by you` and exits with the normal pause code.
   - A pause requested between tasks takes effect after the task's tick commit.
   - If the relay pauses for another reason first (a limit, a failed check, a release task), that pause wins and the request is cleared. Every pause clears it, and so does Resume.
3. **Nothing lost on a cut-off turn.** Pause now and Stop both record the files the cut-off turn left changed (from `git status --porcelain`) in the saved state. On Resume, the next agent's prompt says: "The previous turn (implementer codex) was cut off before it handed off. It left changes in: … Continue from them; don't start over and don't discard them."
4. **Safeguards** (agentdock, all on by default, all in Settings):
   - **Battery.** While a relay runs on battery at or below 15%, the console asks for a safe pause and says why. A notice shows: `Battery at 14% — pausing safely so nothing is lost. Plug in and press Resume.` The threshold can be set, or turned off.
   - **Sleep.** When the console sees the Mac woke from sleep while a relay was running (wall clock jumped well past the monotonic clock), it shows: `The Mac slept for 42m while codex was working; its turn may time out. [Pause safely] [Keep going]`.
   - **Awake hint.** Starting a relay on battery with Awake off adds one line: `On battery: press Awake to keep the Mac from sleeping mid-turn.`
   - **Quitting.** Quitting the console while a relay runs asks: **Pause safely and quit** (waits through Pausing…, then quits) / **Leave it running** / **Cancel**.
5. **Command line:**
   - whyline-relay: `whyline-relay pause [--now | --cancel]`, with the state shown in `whyline-relay status`.
   - whyline: `whyline relay-safety [--battery N|off] [--on-wake ask|pause|off] [--on-quit ask|pause|leave]` saves the safeguards through the same function the Settings controls use.

## How it works

**whyline-relay:**
- **The pause request** is a new file, `.whyline/relay/PAUSE`, holding JSON `{requested_at, now: bool}`. It is separate from `STOP` on purpose: the STOP watcher kills the agent, and the PAUSE file is only read at safe points.
- **Safe points:**
  - the top of the configured-pipeline stage loop, after the previous stage's record is saved and the next stage is chosen, before the next agent runs
  - the same place in the legacy implementer/reviewer loop
  - the top of `run_plan`'s task loop, after the tick commit

  At a safe point the relay raises `Paused(PAUSED_BY_USER)`.
- **Saved state:**
  - `RelayState` gains `paused_by: str = ""`, which is `"user"` for a safe pause.
  - It also gains `cut_off: dict | None`, holding stage, role, agent and changed_files, for a cut-off turn.
  - The saved stage is the *next* one, so Resume runs the next turn.
- **Pause now** writes `PAUSE` with `now: true` and then writes `STOP`. The KeyboardInterrupt/STOP pause path:
  - reads the PAUSE file to choose its reason (`paused now by you; codex's turn was cut off`, or today's Ctrl+C text)
  - records `cut_off`
  - deletes both files
- **Status:** `status.pause_state(root) -> PauseState(kind, since, agent, task_id, round, stage, reason)`. `kind` is one of none / pausing / paused_by_user / paused / cut_off. The console reads it, and `whyline-relay status` prints it.

**agentdock:**
- `relay_ops` wraps `request_pause`, `cancel_pause`, `pause_now` and `pause_state`. This works the same for a relay the console started and for one started elsewhere, because the request is a file.
- The status line from RST-1 shows the pausing and paused text.
- A 1-second console timer drives the elapsed time and the battery and wake checks. Battery is read through `pmset -g batt` on an injectable `run`. Wake is detected by comparing `time.time()` with `time.monotonic()` jumps of more than 2 minutes.

## Decisions (my calls)

- **Pause is a request, not a signal.** It never kills a process, so it can't corrupt a turn. The cost is the wait for the current turn, which the status line explains with an elapsed counter.
- **No timeout on Pausing.** The turn's own time limit bounds the wait. Pause now is the user's way out.
- **Stop is kept** as the "stop now" control, and gains the `cut_off` record. Pause now and Stop differ only in the reason text.
- **Settings location.** Safeguard settings are per Mac, in `~/.whyline/relay-safety.toml`, not in the committed relay config.
- **Release order.** whyline-relay ships first (RPZ-5). The agentdock plan's first task checks that version, like SDLC-1 does.

## Out of scope

- Pausing in the middle of an agent's turn and continuing that same turn later. CLIs can't freeze and restore a turn reliably; `kill -STOP` would hold the agent's network session open and usually fails on wake.
- Pausing Plan-mode drafting (`plan-state.json`) and the Agents and Workflows runners.

## Testing

- **whyline-relay:**
  - a fake agent runner and a temporary repo
  - a PAUSE written mid-turn lets the turn finish, saves the handoff, and pauses before the next agent
  - Resume starts the next stage and the finished one isn't rerun
  - Pause now records `cut_off`, and the resume prompt names the files
  - every other pause clears the request
- **agentdock:**
  - Textual pilot tests with fake `relay_ops` cover the button states, the status text, Keep going, Pause now's confirm, and the quit dialog
  - the battery and wake checks use a fake `run` and a fake clock
