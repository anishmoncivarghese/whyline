# Watch agents: check something on a schedule and tell me only when it matters

Status: draft for review, 2026-11-17. Builds on saved agents (`whyline.agents`), check-ins (`plans/assistant-checkins.plan.md`, CKN) and agent models (`plans/agent-setup.plan.md`, AMD). One plan, `watch-agents`, to be written after this is approved.

Two examples this must handle, in the user's words:
- "On 17 November, check whether the MCC round 2 results are published. If yes, send a Telegram or an email."
- "Check the price of a product, and when it goes below a certain amount send an email or a Telegram."

## Where whyline stands

- **Schedules.** `agents/definitions.py` `Trigger` has `manual`, `daily`, `weekdays`, `every` (1 to 168 hours, aligned to midnight) and `folder`. `agents/schedule.py` works out due times, and `agents/tick.py` runs every 120 seconds from launchd. A run missed while the Mac slept is run on wake if it is still fresh, else recorded as missed.
- **Delivery.** `agents/deliveries.py` sends every run's answer by email, Telegram or a command, with a failure alert.
- **Pages.** `tools/knowledge.fetch_pages` downloads http and https pages (2 MB limit, timeout) and `html_to_text` turns them into text. It is used for knowledge only, and has no guard against private addresses.
- **Planned, not built.** CKN-1 adds gates: checks that use no model and decide whether the agent runs at all (mail, calendar, CI, reminders, changed files). CKN-2 adds `every_minutes` (5 to 720). CKN-3 adds active hours, an hourly message limit, and a silent agent whose answer `NOTHING` sends nothing. AMD-1..4 make the model per CLI selectable for the main agent and each backup, and make the run apply it.

## Problems

1. **A run can't be tied to a date.** There is no "once on 17 November", no "only between these dates", no "every Monday", and no end.
2. **Nothing can look at a web page.** No gate fetches one, so a watch means a full agent run every time, and a message every time.
3. **A watch never finishes.** Once the results are out, the agent keeps running and keeps saying so.
4. **Nothing is remembered between runs.** An agent can't say "down from 4,999 to 3,799" or know it already told you.
5. **A broken check is silent.** If the page moves or blocks the fetch, the user hears nothing and assumes "no news".

## Part 1: When it runs

`Trigger` gains:
- **`once`**: a date and a time. It runs one time and the agent is then marked finished.
- **`weekly`**: chosen days (`mon`..`sun`, at least one) and a time.
- **`every`** in minutes as well as hours. One number and a unit in the console (minutes, hours, days), stored as `every_minutes` (CKN-2). The floor is 5 minutes and the ceiling 7 days. `every_hours` in old files still loads.
- **`at` may list up to six times** for `daily`, `weekdays` and `weekly` (`09:00, 13:00, 18:00`).
- **`starts` and `ends`**: optional dates on any kind. Before `starts` nothing is due. After `ends` the agent is marked finished with `ended on <date>`.
- **`max_runs`**: optional. The agent is marked finished after that many runs.

Rules:
- All times are local wall-clock time, as now.
- A `once` run missed because the Mac was asleep or off runs when it wakes, if that is within 24 hours. After that it is recorded as missed and the user is told once.
- **Finished** is a new activation status beside active and paused. A finished agent is kept, shows why it finished, and can be started again from the console. It is stored as status `finished` with the reason in the existing reason column, and `tick` skips it like a paused agent.

## Part 2: A page check that uses no model

A new gate, `page`, in CKN-1's gate list. A gate decides whether the agent runs, and a gate that finds nothing starts nothing and sends nothing.

Arguments:
- `url`: one to three http or https addresses.
- `rule`, one of:
  - `changed`: the page's text is different from last time.
  - `appears`: a given text is on the page now and was not before.
  - `gone`: a given text is no longer on the page.
  - `always`: every check passes, so the agent decides (for pages too noisy for `changed`).
- `between` (optional): a start text and an end text. Only the part of the page between them is compared. This is how clocks, adverts and counters are kept out of `changed`.

How it works:
- The page is fetched with the existing downloader, turned into text, cleaned through `ideas.guard.clean`, and cut to 200,000 characters. The gate keeps a hash and the text of the last good fetch per address in the agent's gate state.
- The first check only records the page and finds nothing, unless the rule is `appears` and the text is already there.
- On a hit, the gate writes `page.md` (the current text), `before.md` (the last text) and `found.md` (up to 40 changed lines) in the run folder for the agent to read as data.

What it refuses or reports instead of guessing:
- An address that resolves to a private, loopback or link-local address is refused, on every fetch and after every redirect.
- A 403, 429 or 503 answer, or a page that is a robot check, is a **blocked** result, never a change. The same for a page that needs a login.
- Three failed or blocked checks in a row send one message: `<agent> couldn't read <address>: <reason>`. One more is sent when it works again. Nothing else until then.
- A 429 with `Retry-After` is honoured. One address is fetched at most once per 5 minutes across all agents.
- The request says who it is (`User-Agent: whyline-watch/<version>`) and sends no cookies.

Limits to say plainly in the console and docs:
- Pages that build their content with JavaScript show little or nothing to a plain fetch. **Test** shows the text whyline sees, so the user knows before turning it on.
- Large shops, Amazon among them, usually answer an automated fetch with a robot check. whyline does not try to get past it. A price watch works on shops with plain pages or a public API address.

## Part 3: What happens on a hit

A saved agent gets a `[watch]` table. An agent without it behaves as today.

- **No instructions, no model.** For `changed`, `appears` and `gone`, an agent with empty instructions never starts a CLI. whyline sends the message itself: the agent's name, what happened (`The text "Round 2 result" is now on the page`), up to 10 changed lines, and the address. This costs nothing per check. Empty instructions are accepted only for an agent with one of these three rules; every other agent still needs them.
- **With instructions.** The agent runs with the three files and answers. `NOTHING` means no hit (CKN-3). Anything else is the message.
- **A value to compare.** `value = "below 4000"` or `"above 50"`. The agent is asked to end its answer with `VALUE: <number>`. whyline, not the model, does the comparison:
  - a hit when the value crosses the limit, and after that only when it goes further past the last value it told you about
  - the message is whyline's own line (`3,799, down from 4,999. Your limit is 4,000.`) followed by the agent's answer
  - an answer with no readable `VALUE` line is a failed read, counted with the failed checks above, never a hit
- **Memory.** The last 200 values with their times, the last message sent, and a note of up to 500 characters that the agent may leave by ending with `REMEMBER: <text>`. They are given to the next run as `last.md`.
- **When to stop.** `stop = "first"` marks the agent finished after its first hit, with `found on <date>`. `stop = "never"` keeps watching. The template for "tell me when a page says…" defaults to `first`, and the price template to `never`.
- **Straight away.** A watch hit is sent at once, outside CKN-3's hourly limit. Active hours still hold it unless the watch has `urgent = true`.
- **Daily cap.** At most 24 agent runs a day per watch by default (1 to 200). Checks with no model are not counted. When the cap is reached the user is told once that day.

## Part 4: In the console

- **New agent → Schedule** becomes one block: **When** (Manual, Once, Daily, Weekdays, Weekly, Every, When a folder changes), the fields that kind needs, **From** and **Until**, and a line that reads the schedule back: `Every 30 minutes from 17 Nov to 20 Nov. Next: today 14:30.`
- **New agent → Watch**: address, rule, the text or the limit, optional between-texts, Stop after the first hit, Tell me even outside active hours, and the daily cap.
- **Two templates** in the template list: `Tell me when a page changes or says something` and `Tell me when a number goes below or above a limit`.
- **Test** runs the check once now. It shows the text whyline read, whether the rule would fire, and the exact message that would be sent. It sends nothing and records nothing.
- **Agents list**: next check, last check and its result (`no change`, `blocked`, `3,799`), and finished agents with their reason and **Start again**.
- **Agent, model and backups** are the Model selects AMD-3 adds. The watch templates add one line: `Reading one page is a small job. A small model is enough.`
- **CLI**, through the same functions: `whyline agents schedule <name> …`, `whyline agents watch <name> …`, `whyline agents watch test <name>`.

Watch agents are personal agents in `~/.whyline/agents`. They do not depend on the repository selected in the console.

## Goals

- Both examples at the top can be set up in the console in under two minutes, without writing instructions.
- A watch that finds nothing costs no model run and sends nothing.
- The user always knows the difference between "no news" and "the check is broken".
- Every watch has an end the user chose, or an explicit "keep watching".

## Non-goals

- Pages behind a login, and pages that need a browser to render. A browser connector is the later answer (`plans/agent-setup.plan.md`, CON).
- Buying, booking or filling a form when a watch fires. A watch only tells you.
- Creating a watch by sending the assistant a sentence. `plans/agent-draft.plan.md` drafts agents from a description and can learn the watch fields later.
- Intervals under 5 minutes.

## Anti-goals

- Getting past a robot check, rotating addresses, or pretending to be a browser.
- A message on every check.
- A watch that keeps running an agent on a page that never settles, with no cap.
- The model deciding whether a number is under the limit.

## Constraints

- Console first: every field and action above has its console place and a CLI command over the same function.
- Page text is data. It reaches the agent as files in the run folder, never as part of the instructions.
- No new dependency. Python 3.11 compatible. Tests never touch the network.
- Old agent files load unchanged.

## Calls I made

- The page check is a CKN gate, so the plan runs after `assistant-checkins`.
- 5 minutes is the shortest interval, and seconds are not offered.
- whyline sends the message itself when there are no instructions.
- The comparison of a value is done by whyline; the model only reads the number.
- A watch hit skips the hourly message limit but respects active hours unless marked urgent.
- 24 agent runs a day per watch by default.
- Amazon and similar shops are described as usually blocked, not supported.

## Questions

Answered 2026-11-17: question 1 is yes. Check-ins and `plans/watch-agents.plan.md` run straight after agent-setup (group 1c in `plans/RUN-ORDER.md`). Questions 2 to 4 were not answered; the plan uses the choices in "Calls I made", and failure messages go to the same delivery as hits.

1. **Run order.** Check-ins sit in group 5 today, far down the list. Should check-ins and this plan move up to run straight after agent-setup?
2. **Seconds.** You asked for seconds. I left them out for cost and because sites block it. Is a 5-minute floor acceptable?
3. **Urgent by default.** Should a hit wait for active hours by default (my choice), or always come through?
4. **Email as well as Telegram for one watch.** Delivery already allows both at once. Is that enough, or do you want a different channel for failures than for hits?
