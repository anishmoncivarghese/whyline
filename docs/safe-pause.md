# Pausing a relay safely

Use **Pause** when you want to close the lid, unplug, or step away and carry on
later without losing work.

## Pause, Pause now and Stop

| Control | What happens | Resume then |
| --- | --- | --- |
| **Pause** | Asks the relay to stop at the next safe point, after the current agent turn finishes and hands off. | Starts the *next* turn from the handoff just written. Nothing is redone. |
| **Pause now** | Cuts the current turn off after a one-line confirm. | Starts the cut-off turn again. The agent is told which files the cut-off turn left changed, and to continue from them rather than start over. |
| **Stop** | Cuts the current turn off immediately, as before. | Same as Pause now. Only the reason shown differs. |

### Why Pausing… can take a while

An agent's turn cannot be frozen and restored, so Pause waits for the turn to
finish. The button shows **Pausing…** with the agent and the time so far. The
turn's own time limit bounds the wait. If you can't wait, press **Pause now**.
Press **Keep going** to withdraw the request.

If the relay pauses for another reason first (a usage limit, a failed check,
a release task), that pause wins and the request is cleared.

## Safeguards

Set these in **Settings → Relay safety**, or with `whyline relay-safety`.

- **Battery limit.** On battery at or below the limit (default 15%), the
  console asks for a safe pause. Choose off, 10, 15, 20, 25 or any number
  from 1 to 99.
- **When the Mac wakes.** After sleep during a relay: `ask`, `pause` or `off`.
- **When quitting.** Quitting the console during a relay: `ask` (Pause safely
  and quit / Leave it running / Cancel), `pause`, or `leave`.
- **Awake hint.** Starting a relay on battery with Awake off suggests pressing
  Awake.

## From a terminal

```text
whyline-relay pause            # ask a running relay to pause at the next safe point
whyline relay-safety           # show the safeguards
whyline relay-safety --battery 20 --on-wake pause --on-quit ask
whyline relay-safety --battery off
```

`whyline relay-safety` saves through the same function as the Settings screen,
to `~/.whyline/relay-safety.toml`.
