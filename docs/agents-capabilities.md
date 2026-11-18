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

## Schedules

A saved agent has one schedule kind. In **When** (New agent) or on the command
line:

| Kind | Example | Command |
|------|---------|---------|
| Once | on 17 Nov at 10:00 | `--once 2026-11-17 --at 10:00` |
| Daily | every day at 09:00 and 13:00 | `--daily --at "09:00, 13:00"` |
| Weekdays | Monday to Friday at 08:30 | `--weekdays --at 08:30` |
| Weekly | Mon and Thu at 09:00 | `--weekly mon,thu --at 09:00` |
| Every | every 30 minutes, 2 hours or 3 days | `--every 30m`, `2h`, `3d` |
| Manual | only when you press Run | `--manual` |

A day may list one to six times. The shortest interval is 5 minutes.

**From** and **Until** are dates (both days are included). Nothing runs
before From or after Until. **Stop after (runs)** is the run limit: after that
many runs the agent stops. They are not offered for Manual or Once.

### Finished, and Start again

An agent is **finished** when its Once moment has passed, Until has passed, or
its run limit is reached. It shows `finished: <reason>` in the Agents list and
is not run again by itself. A Once moment missed by more than a day is
recorded as missed and finishes the agent, and you get the failure alert once.
**Start again** (or `whyline agents start-again <name>`) makes it active and
starts the run count at zero. It refuses with `Change the date first.` when
the Once date or Until date is still in the past.

## Watching a web page

A **watch** is a check-in whose gate is the `page` gate. whyline fetches the
page itself, with no model, and starts an agent only when the rule fires.
Watch agents are personal: they are saved in `~/.whyline/agents` and do not
depend on the repository selected in the console.

The page gate takes one to three addresses and one of four rules:

| Rule (**Tell me when**) | Fires when |
|------|------------|
| `changed` (the page changes) | the text differs from the last check; the added and removed lines (up to 40) are the items |
| `appears` (this text appears) | the text is on the page now and was not last time |
| `gone` (this text is gone) | the text was there last time and is not now |
| `always` (let the agent decide) | every check, so the agent reads the page and decides |

The first successful read of an address only records it, and finds nothing,
except for `appears` with the text already there, and `always`. Text is
compared without case and with spaces collapsed.

**Only between** takes a start text and an end text. Only the page text
between their first occurrences is checked, so a menu or footer cannot cause
a hit. If either text is missing from the page, the check counts as failed.

Page text is data. It is cleaned, cut to 200,000 characters and given to the
agent as the files `page.md`, `before.md`, `found.md` and `last.md` in the
run folder. It is never put in the instructions.

### A watch with no instructions

With rule `changed`, `appears` or `gone`, no number, and the Instructions
box empty, whyline sends the message itself: the agent's name, one line for
the rule (`The text "Round 2 result" is now on the page.`), up to 10 changed
lines and each address. No agent runs, so it costs nothing.

### A number watch

Set **A number goes** below or above a limit, and write instructions telling
the agent which number to find. The agent ends its answer with a line:

    VALUE: 3799

Currency signs, letters, spaces and thousands separators are dropped
(`₹3,799.00` is 3799). **whyline does the comparison, not the agent.** The
agent's words never decide a hit; only the number and the limit do. A hit is
sent when the value crosses the limit, and again only on a further drop (for
`below`; a rise for `above`), or after the value has gone back over the limit
and crossed it again. The message starts `3,799, down from 4,999. Your limit is
4,000.` and is followed by the agent's answer. If there is no `VALUE:` line,
the check counts as failed and nothing is sent.

An agent may also end with `REMEMBER: <one line>` (up to 500 characters). It
is kept for the next run, and shown to the agent as part of `last.md` with the
last message and the last 10 values. `VALUE:` and `REMEMBER:` lines are removed
from what is sent. An answer of `NOTHING` sends nothing.

### Stop, the daily cap and a broken check

- **Stop after the first time** finishes the agent after its first hit
  (`found on <date>`). **Start again** turns it back on.
- **Agent runs per day, at most** (default 24, 1 to 200) limits how many
  times the agent starts for one watch in a day. At the cap the run is
  skipped and one notice is sent that day.
- **Tell me even outside active hours** sends a hit at once; otherwise it is
  held with the rest (see Check-ins).
- **A broken check:** a page that cannot be read is never reported as a
  change. After three failed checks in a row you get one message,
  `couldn't read <address>: <reason>`, not three. When the page can be read
  again you get `<address> can be read again`.

### Test

**Test** in the Watch section (or `whyline agents watch test <name>`) fetches
the page now and shows, for each address, `read`, `blocked` or `failed` with
the reason, the text whyline read, whether the watch would fire and why, and
the message it would send. It starts no agent, sends nothing and changes no
saved state. A page with almost no text gets a note that it may need a
browser.

```bash
whyline agents watch shop --url https://example.com/item --rule always \
  --below 4000 --urgent --cap 6
whyline agents watch results --url https://example.com/results \
  --rule appears --text "Round 2 result" --stop-first
whyline agents watch test results
whyline agents watch off results
```

### Limits

- A page is fetched at most once in 5 minutes, and a site that asks to slow
  down is left alone until it says to retry. The shortest check is every 5
  minutes.
- whyline cannot log in. A page that asks for a login is reported as blocked.
- whyline reads the page the way a plain fetch does and runs no browser. A
  page built by JavaScript shows almost nothing.
- whyline does not get past a robot check. A site that blocks automated
  checks (large shops often do) is reported as blocked.
- Addresses on a private network are refused.
- The Mac has to be on and awake. A check due while it sleeps runs when it
  wakes.
