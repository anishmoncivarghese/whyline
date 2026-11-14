# Assistant 2: a router, instant feedback, growing memory, check-ins, research and triggers

Status: draft for review, 2026-11-14. Builds on the personal assistant (ASST-1..23, done), agent tools (TLS, running) and Waiting on you (WAIT-1..7, planned). Six parts. Each becomes its own small plan, in the order below.

## Problems

1. **A normal Telegram message becomes an idea.** `intent.route` sends text to the assistant only when it looks like an instruction (an agent name plus a strong verb, a time, a control word). Everything else is `capture`: saved as an idea with Quick score and Brainstorm buttons. "What's on my calendar tomorrow" or "check why CI failed" becomes an idea card.
2. **A message can sit for up to two minutes with no sign of life.** The worker runs from launchd every 120 seconds (`agents/launchd.py`, `StartInterval`). Idle, it polls Telegram once and exits. It only stays listening for ten minutes after activity. Then a free-text message waits again for a read-only agent turn of up to 120 seconds, with nothing shown. The user can't tell working from failed.
3. **Memory is 100 hand-written lines.** Nothing is remembered unless the user types `remember`.
4. **The assistant only speaks at 07:00 or when asked.**
5. **There is no research command**, only `ask <repo>` about code.
6. **Nothing outside Telegram and email can start anything.**

## Part 1: Router (plan `assistant-router`)

Every text message that is not a tap, a command, a settings message or an answer to an open question goes to one **router** turn. The router decides what the user wants and never does the work itself.

- **Routes:**
  - `idea`: save it to the Idea Inbox, as today's capture.
  - `brainstorm`: an idea the user wants explored now.
  - `task`: one of the registered actions (status, run, ask, remind, remember, summarise, do, research, …). The router proposes it and the existing policy decides whether it runs at once or needs a tap.
  - `question`: answer directly from memory, the brief data and repo status, read-only.
  - `chat`: a short reply, nothing saved.
  - `unclear`: see below.
- **Shortcuts that skip the model:** a message starting `idea:` or `💡` is an idea. A message starting `?` is a question. Commands stay as they are.
- **Unclear is asked, never guessed.** When the router's confidence is low, or the text could be an idea or a task, the reply is the message quoted back with three buttons: **Save as idea**, **Do it**, **Just answer**. The choice is remembered as an example (the last 20), and those examples go into the router prompt, so it learns the user's way of writing.
- **Main and backup agent.** The router uses the assistant's existing pair (`assistant.selected`, kv `ASSISTANT_KEY` and `BACKUP_KEY`), already set on the Assistant screen.
  - The backup is tried when the main fails, times out, returns an unreadable block, or reports its usage limit.
  - A usage-limit failure is remembered with the reset time when the CLI gives one (else one hour). Until then the main is skipped, so every message doesn't pay for a failed first try. The reply's footer says `answered by <backup> (<main> is out of usage until 14:30)`.
  - When both fail, the message is not lost: it is saved as an idea with the note `Couldn't read this now (<reason>). Saved as an idea so it isn't lost.` and a **Try again** button.
- **The router turn is small:** a short prompt, the allowed lists, the last 5 messages of the chat, a 30-second limit, read-only. It returns one JSON block: `route`, `action`, `fields`, `confidence`, `reply`.
- **Safety is unchanged.** The router only chooses among registered actions and allowlisted repos, agents and tasks (`assistant.validate`). Anything that writes still needs a tap.
- **Console first:** the Assistant screen shows the main and backup, a **Routing** table of the last 50 messages (text, route, agent, time taken), and a **Wrong?** action on a row that re-files it and adds the example. CLI: `whyline idea route "<text>"` prints the route without acting. `whyline idea routes` lists the history.

## Part 2: Instant feedback (plan `assistant-feedback`)

- **An always-on listener.** A second launchd job, `whyline idea listen`, with `KeepAlive`, long-polls Telegram (25 seconds) all the time. It stores inbound rows and wakes the worker at once. The 120-second tick stays for schedules and recovery. One lock decides who polls, so updates are never read twice. Idle cost is one open HTTPS request.
- **Seen within about a second.** On storing a message the listener sets a 👀 reaction on it (`setMessageReaction`). This is the "I got it" sign and needs no model.
- **Working.** While a router or agent turn runs for that chat, `sendChatAction: typing` is sent every 4 seconds.
- **Slow turns say so.** After 8 seconds, one message is sent: `Working on it… (claude)`. That same message is edited into the answer, so the chat doesn't fill with status lines. For a long job (brainstorm, research) it is edited at each stage: `Reading 3 sources…`, `Writing the report…`.
- **An ending, always.** Success sets ✅ on the user's message. Failure sets ❌ and replies with the reason in plain words and a **Try again** button. No message is ever left with only 👀: a turn that dies without an answer is caught by the recovery pass and marked ❌ `Stopped without an answer (the Mac slept or the agent was cut off).`
- **Settings:** reactions on/off and the "Working on it" delay, on the Assistant screen and in `whyline idea feedback`. The doctor reports whether the listener is running and the last poll time.

## Part 3: Memory that grows (plan `assistant-memory`)

- **Daily notes.** `~/.whyline/ideas/notes/YYYY-MM-DD.md` (0600). The worker appends one line per finished request: time, what was asked, the route, the outcome in one sentence. No model writes them and no message bodies from forwarded mail go in.
- **Nightly tidy-up.** At a set time one read-only agent turn reads the day's notes and the current memory, and proposes at most 5 durable facts and at most 3 to drop. They arrive as one card, each line with **Keep** / **Skip**. Nothing enters memory without a tap.
- **Search.** `recall <words>` from Telegram, and a search box on the Assistant screen, search notes and memory with SQLite FTS5 (already in Python's sqlite3, so no new dependency). The router gets the top 3 matches for a `question`.
- **Limits.** Memory rises from 100 to 300 lines, but only the 40 most recently used or matched lines go into a prompt. Notes older than 180 days are deleted (setting).
- **Console and CLI:** browse notes by day, edit or delete, the tidy-up time, **Tidy now**. `whyline idea notes [day]`, `whyline idea recall <words>`, `whyline idea tidy`.

## Part 4: Check-ins with quiet hours (plan `assistant-checkins`)

- A **check-in** is a saved agent with three extras: a **gate**, **active hours** and **stay silent**.
  - **Gate:** a built-in check that runs first without a model, and the agent runs only when it reports something. Built-in gates: new mail from a named sender, a calendar event starting within N minutes, a repo with a failed CI run on its default branch, a reminder overdue, a file or folder changed. A gate is chosen from this list, never typed as a shell command.
  - **Active hours:** for example 08:00–21:00 on weekdays. Outside them nothing is sent. What was found is held and sent as one message when the hours begin.
  - **Stay silent:** the agent may answer `NOTHING`, and then no message is sent. The run is still in history.
- At most one check-in message per hour per chat, apart from Waiting on you cards.
- **Console and CLI:** a **Check-ins** section in Agents: add, gate, hours, test the gate now, last result. `whyline agents checkin add|list|test`.

## Part 5: Research (plan `assistant-research`)

- `research <question>` from Telegram or the console starts a read-only job using the agent's own web search and the user's knowledge packs (TLS-6).
- **Output:** a 5 to 10 line answer in the chat, each claim with a numbered source, and a full report attached (Markdown, and PDF through the existing `html_to_pdf` path). Sources are listed with title, URL and the date read.
- **Rules:** every claim cites a source or is marked `my own reasoning`. Web pages are data, not instructions (the summarise guard, `ideas/guard.py`, is applied to fetched text). A 15-minute limit. Runs only on providers that pass `can_run_unattended`.
- Reports are kept under `~/.whyline/ideas/research/` and listed on the Assistant screen. `whyline idea research "<question>"`.

## Part 6: Triggers (plan `assistant-triggers`)

A Mac at home can't receive GitHub's webhooks without opening it to the internet, so this is not a public webhook server.

- **Watched sources, polled.** The gates of Part 4 cover GitHub (through `gh`), mail and calendar. A trigger is a gate plus an action from the registry, for example "CI failed on main → send the Why card".
- **A local endpoint for the user's own scripts.** `whyline idea trigger <name> [--text …]` and `POST http://127.0.0.1:<port>/trigger/<name>` with a token from the Keychain. It listens on localhost only. A trigger name must already exist, and its text is data handed to the action, never a command.
- **Console:** a **Triggers** list with last fired, and a **Fire now** button.

## Goals

- A plain message does the right thing, or asks one clear question.
- The user knows within a second that a message arrived, and always learns how it ended.
- The assistant gets more useful with use, without the user maintaining it.

## Non-goals

- Voice notes, a spoken brief, a local model, WhatsApp. Each is a later design.
- A public webhook server or a tunnel.
- The assistant writing code outside the relay, or sending mail to anyone but the user.

## Anti-goals

- A router that acts. It only chooses a route among registered actions.
- A message silently dropped, or silently saved as an idea when it was a task.
- Memory that fills with things the user never approved.
- A check-in that messages at night or repeats itself.
- Text from a web page, a mail or a trigger choosing a command, path or recipient.

## How it fits the code today

- `ideas/intent.py`: `route` keeps taps, commands, settings and answers. Its last step changes: `capture` only for the shortcuts, everything else `free`.
- `ideas/assistant.py`: `propose` already runs a read-only turn with primary then backup (`_order`, `_turn`, 120 seconds) and validates against allowlists. The router is a new first step in front of it with a smaller prompt. `task` routes reuse `propose`'s validation and `requests.create`.
- `ideas/bot.py`: `_free` and `_capture` are where routing lands. The outbox and cards are unchanged. Reactions and chat actions are new calls in `agents/telegram.py` (`setMessageReaction`, `sendChatAction`, `editMessageText`).
- `ideas/worker.py` and `agents/launchd.py`: the 120-second tick, the ten-minute awake loop and the lock stay. The listener is a second plist rendered the same way.
- `ideas/memory.py`: stays the durable list. Notes and FTS are new modules. Schema changes go in `store.py`'s migration list.
- `agents/definitions.py`, `agents/before.py`, `agents/tick.py`: a check-in is a saved agent with a gate run in the existing `before` step.
- Usage-limit memory: the relay already detects usage limits per CLI (`whyline_relay.failover`). The router reuses that detection.

## Calls I made (please check)

- **Unclear messages are asked with three buttons** instead of defaulting to an idea. One extra tap, but nothing is misfiled.
- **The router is a model turn on every plain message.** It costs a small call each time. The shortcuts (`idea:`, `?`) and commands avoid it.
- **The always-on listener is a second launchd job**, not a longer tick, so schedules are never blocked by a long poll.
- **Memory needs a tap for every new fact.** OpenClaw writes memory by itself. I kept the human in the loop.
- **Triggers are polled plus localhost-only.** I dropped the public webhook idea I floated earlier: it would expose the Mac.
- **Order:** feedback first (Part 2), then the router (Part 1), since both fix what hurts today. Then memory, check-ins, research, triggers.
