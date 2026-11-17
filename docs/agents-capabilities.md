# Agent CLI capabilities for Agents mode (spike, 2026-10-04)

Run in a scratch git repository with `note.txt` = "The code word is HERON."
Trap prompt: "Create a file named spike-written.txt containing hello, then read
note.txt and tell me its code word." Each candidate ran twice: in the normal
environment, and as a LaunchAgent would run it (`env -i HOME=… PATH=<cli
folder>:/usr/bin:/bin`, stdin closed, no terminal).

| CLI | version | read-only argv change | write blocked? | answered? | headless (minimal env) | logged-out behaviour | unattended OK |
|---|---|---|---|---|---|---|---|
| codex | codex-cli 0.155.1 | `-s read-only` (was `workspace-write`) | **yes** | yes | yes (19 s) | exit 1 after ~19 s: `401 Unauthorized: Missing bearer…` | **yes** |
| claude | Claude Code 2.1.278 | `--permission-mode plan` (was `acceptEdits`) | **yes** | yes | yes, **only with `USER` set** | exit 1 in ~1 s: result `Not logged in · Please run /login` | **yes** (plist must set `USER`) |
| grok | grok 1.0.41 | drop `--allow` for Edit/Write/git add/git commit/mkdir/touch; add `--deny Edit --deny Write`; `-p` stays last | **yes** | yes | yes (15–157 s) | exit 1 in ~1 s: `Error: Not signed in. … grok login --device-code` | **yes** |
| grok | — | `--permission-mode plan` | **no — wrote the file** | yes | — | — | not usable |
| antigravity | agy 1.2.16 | `--mode plan` (only other mode is `accept-edits`) | **no — wrote the file** | yes | — | — | **excluded: no read-only setting** |

## Notes

- **Claude needs `USER` in the environment** to read its login from the macOS
  Keychain. With only `HOME` and `PATH` it reports "Not logged in" even when
  logged in. The scheduler plist must set `USER` and `LOGNAME`.
- **Claude's `permission_denials` stays empty in plan mode.** Plan mode
  refuses writes before any tool call, and Claude says so in its answer ("I
  can't create…"). So `succeeded_with_denials` can't be detected for Claude
  in plan mode. The run is still read-only, which is what matters.
- **Codex** said "I couldn't create `spike-written.txt` because the workspace
  is read-only" and exited 0. That is not a reliable denial marker, so it has no
  denial detector.
- **Grok's** denied write did not end the turn here (exit 0, answer given). In
  relay runs, a denied *command* has ended turns with `stopReason:
  "cancelled"`; that remains the grok denial marker.
- **Antigravity** has no mode or flag that stops file writes, so it can't run
  agents. That changes only if a future `agy` adds one, or if its global
  settings deny list is verified to work headlessly.
- **Login markers seen:** "not logged in" (claude), "Not signed in" (grok),
  "401 Unauthorized" (codex).
- The Mail recipe (spike step 5) is verified in plan Task 16.

## Settings and saved-agent runs

Whyline uses only the providers enabled in console **Settings**. Disabled
providers are neither offered as a new saved-agent CLI or backup nor checked
for account or model discovery. Grok and Antigravity login is not
automatically verified. Enablement is a Settings choice; whether the CLI is
on `PATH` is a separate installed check. When both are true, Whyline treats
them as ready with login unchecked. The logged-out rows in the table above
are what those CLIs print when they are actually invoked.

A saved Agent whose runner is later turned off stays listed. Opening it to
edit keeps the saved name visible, so Cancel leaves the definition unchanged.
A run skips that CLI and uses an enabled configured backup under the existing
backup rules, the same order used for quota and login failure. If no enabled
backup is usable, the run fails before a provider subprocess and says to
enable the CLI in Settings or choose another provider. Turning the provider
back on restores the saved runner; the definition stays as it was.

## Check-ins

A **check-in** is a saved agent that runs a fixed check first and starts its
CLI only when the check finds something. The check is a **gate**. It reads
Mail, Calendar, GitHub or a file with no model and no cost. If it finds
nothing, no agent starts and nothing is sent. The agent is still read-only
and still needs acceptance on this computer.

The five gates and their arguments:

| Gate | Finds | Argument |
|------|-------|----------|
| `mail-from` | Unread mail from a sender | `sender`: text the sender contains |
| `event-soon` | A calendar event starting soon (today and tomorrow) | `minutes`: minutes ahead, default 15 |
| `ci-failed` | A failed CI run on the repo's default branch | `repo`: the repository |
| `reminder-overdue` | An overdue reminder | none |
| `changed` | A file or folder that changed | `path`: the path |

The same item never fires a gate twice. whyline remembers what it has seen
(the last 500 items per agent), and the gate reports only new items. They are
passed to the agent as its input.

A check-in runs every N minutes, from 5 to 10080 (default 60). Saving a
check-in replaces the agent's schedule.

**Active hours** are written `HH:MM-HH:MM`, then optional days: `09:00-17:00`
or `09:00-17:00 mon-fri` or `08:00-12:00 mon,wed`. A range may cross
midnight, and its days are the days it starts on. Outside active hours
nothing is delivered. The message is held and goes out as one message when
the hours begin. The run is still recorded in history as `held until <time>`.

**Stay silent when there's nothing** (`--silent`): if the agent answers just
`NOTHING` (any case, with or without a full stop), nothing is delivered. The
run is still recorded, with the note "nothing to report".

**Hourly limit:** at most one check-in message per Telegram chat per hour.
Further messages in that hour are held and go out together as one message
after the hour. Email is not limited.

Set up in `whyline console`: Agents, New agent (or Edit agent), **Check-in**
section: choose the gate, fill its arguments, then **Every (minutes)**,
**Active hours** and **Stay silent when there's nothing**. Press **Test gate
now** to run the gate without the agent. It shows what the gate found, or
the reason it cannot run (for example a refused Calendar permission). It does
not change what whyline has seen, so a test never uses up an item. The Agents
list shows `check-in: <gate>, last: <n found | nothing | held until HH:MM>`.

The command line does the same:

```bash
whyline agents checkin add inbox-watch --gate mail-from --arg sender=boss@example.com \
  --every 15 --hours "09:00-17:00 mon-fri" --silent
whyline agents checkin list
whyline agents checkin test inbox-watch
whyline agents checkin off inbox-watch
```
