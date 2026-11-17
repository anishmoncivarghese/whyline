<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-17-watch-agents-design.md | created: 2026-11-17T10:00:00+05:30 -->
# Watch agents: dated schedules, a page check with no model, and stopping when it's found

Runs after `plans/quick-fixes.plan.md` (released as 0.3.75), and before `plans/release-resolve.plan.md`. Spec: `docs/superpowers/specs/2026-11-17-watch-agents-design.md`. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **The shortest interval is 5 minutes.** Seconds are not offered.
- **A hit waits for active hours** unless the watch is marked urgent. It never waits for the hourly message limit.
- **Failure messages go to the same delivery as hits.**

**Check-ins are part of this plan.** CKN-1..5 were `plans/assistant-checkins.plan.md` and were moved here on 2026-11-17, because WCH-4 to WCH-7 build on them: gates and `gates.check` (CKN-1), the `[checkin]` table (CKN-2), `quiet.py` and the held list (CKN-3), and `service.save_checkin` (CKN-4). They run after WCH-3 and before WCH-4. For the CKN tasks, read `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 4, as well. Where it and this plan differ, this plan wins. In particular:
- **A gate is a `before` step.** `agents/before.py` already has `Step(run, skip_when_empty=True)`: a step that returns 0 skips the agent. Gates are new steps of that kind that take arguments.
- **`every_minutes` already exists.** WCH-1 added it to `Trigger` (5 to 10080) with its due times and text. CKN-2 uses it and does not add it again.

`plans/agent-setup.plan.md` has not run yet. Nothing here needs it: the Model selects in New agent (AMD-3) and the shared checkbox focus rule (PKR-1) arrive with that plan and are not added here.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why:
- A saved agent can run daily, on weekdays or every N hours. It can't run once on a date, weekly, only between two dates, or stop.
- No gate can look at a web page, so watching one means a full agent run and a message on every check.
- Nothing is remembered between runs, and a check that stops working is silent.

What the user gets:
- Schedules: once on a date, weekly on chosen days, every N minutes, hours or days, several times a day, From and Until dates, and a maximum number of runs.
- A **page** gate: changed, a text appears, a text is gone. No model runs unless it fires.
- A **check-in**: a saved agent with a gate, active hours and a stay-silent switch. Gates are chosen from a list: new mail from a sender, a calendar event starting soon, failed CI on a repo, an overdue reminder, a changed file or folder.
- Nothing outside active hours. What was found is held and sent as one message when the hours begin.
- A watch with no instructions sends its own message and never starts a CLI.
- A value watch: the agent reads the number, whyline compares it with the limit and remembers the history.
- Stop after the first hit, one message when a check is broken, and **Test** before turning it on.

Rules every task keeps:
- **Console first.** Every field and action is in Agents in the console, saving through the same function as its `whyline agents …` command.
- **Watch agents are personal.** They are saved in `~/.whyline/agents` and never depend on the repository selected in the console.
- **Page text is data.** It is cleaned with `ideas.guard.clean`, cut to 200,000 characters, and given to the agent as files in the run folder. It is never put in the instructions and never picks a recipient, an address or a rule.
- **whyline does not get past a robot check.** No browser headers it doesn't mean, no cookies, no retries faster than the limits below.
- **A gate is picked from the fixed list and never typed as a command.** Gate arguments are plain values (an address, minutes, a repo name from `ideas.setup.list_repos`, a path) and are checked before saving.
- **A gate uses no model.** It reads Mail, Calendar and Reminders through the existing `ideas/brief.py` readers, GitHub through `gh` with an argv list, and the file system.
- **Mail, calendar and file content are data.** What a gate writes for the agent goes in the run folder as files, like `brief-collect` does.
- **Old agent files load unchanged.** Every new field has a default that means "as before".
- **No new dependency.**
- **Tests:** never open a socket, resolve a real name, start a provider, or call osascript, `gh`, Telegram or Mail. Use fake openers, a fake resolver and an injected clock. Never sleep. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- An address that resolves to a private, loopback or link-local address is refused, on the first request and after a redirect. WCH-3, `test_private_address_is_refused_after_redirect`.
- A blocked or failed fetch is never reported as a change. WCH-4, `test_blocked_is_not_a_change`.
- Three failed checks in a row send one message, not three. WCH-4, `test_three_failures_one_message`.
- The model's words never decide a value hit; only the number and the limit do. WCH-5, `test_whyline_compares_the_value`.
- A check that finds nothing starts no CLI and sends nothing. WCH-6, `test_no_hit_runs_nothing`.
- A finished agent is not run again until it is started again. WCH-2, `test_finished_agent_is_not_run_again`.
- A gate that finds nothing starts no agent and sends nothing. CKN-2, `test_empty_gate_skips_the_agent`.
- The same item never fires a gate twice. CKN-1, `test_gate_reports_an_item_once`.
- Outside active hours nothing is delivered, and it arrives as one message when the hours begin. CKN-3, `test_held_until_active_hours`.
- An agent answering `NOTHING` delivers nothing and the run is still recorded. CKN-3, `test_nothing_answer_is_silent`.
- At most one check-in message per chat per hour. CKN-3, `test_one_checkin_message_per_hour`.

- [x] WCH-1: Schedule kinds: once, weekly, several times, From and Until
  Edit `src/whyline/agents/definitions.py`, `src/whyline/agents/schedule.py`, `src/whyline/agents/service.py` (`when_text` and `_schedule_words` only) and their tests.
  1. `TRIGGER_KINDS` gains `once` and `weekly`. `Trigger` gains `on: str = ""` (`YYYY-MM-DD`), `days: tuple[str, ...] = ()` (`mon`..`sun`), `starts: str = ""`, `ends: str = ""` (dates) and `max_runs: int = 0` (0 means no limit, else 1 to 10000).
  2. `at` may hold one to six times separated by commas (`09:00, 13:00`). `definitions.times(t) -> tuple[str, ...]` returns them sorted, each once. More than six, or a bad time, is refused.
  3. Validation: `once` needs `on` and exactly one time. `weekly` needs at least one day and a time. `ends` before `starts` is refused. The ceiling of `every_minutes` (CKN-2) becomes 10080, and its floor stays 5.
  4. `render` writes only the fields that are set, so an old file round-trips byte for byte.
  5. `schedule.due_times`: `once` gives its one moment; `weekly` gives each time on the chosen days; `daily`, `weekdays` and `weekly` give every listed time. Nothing is due before the start of `starts` or after the end of `ends`.
  6. `schedule.ended(t, *, now) -> bool`: `ends` has passed, or the kind is `once` and its moment has passed.
  7. `when_text` covers the new kinds and dates: `once on 17 Nov at 10:00`, `Mon, Thu at 09:00`, `every 30 minutes`, `every 2 days`, with `from 17 Nov to 20 Nov` added when set.
  Tests: due times for `once`, `weekly` and several times a day, the `starts` and `ends` edges (the first and last day included), a daylight-saving day, each refusal with its message, an old file's round trip, and each `when_text` form.

- [ ] WCH-2: A finished agent
  Edit `src/whyline/agents/state.py`, `src/whyline/agents/tick.py`, `src/whyline/agents/service.py` and their tests.
  1. `state.finish(conn, agent_id, reason)` sets status `finished` with the reason in `paused_reason`. `state.run_count(conn, agent_id) -> int` counts occurrences that ran since `accepted_at`.
  2. `tick` skips a finished agent like a paused one. After it starts a run, and for each active agent with nothing due, it finishes the agent when `schedule.ended` is true (`ended on <date>`, or `ran once on <date>`) or `run_count >= max_runs` (`ran <n> times`).
  3. A `once` moment missed by more than 24 hours is recorded as missed, the agent is finished with `missed on <date>`, and its failure alert is sent once.
  4. `service.start_again(name, repo_root)` sets a finished agent active with `accepted_at` now, so its run count starts at zero. It refuses an agent whose `once` date or `ends` date is in the past, with `Change the date first.`
  5. `service.rows` and `scheduler_summary` show `finished: <reason>`.
  Tests: `test_finished_agent_is_not_run_again`, finishing on `once`, on `ends` and on `max_runs`, the missed `once`, `start_again` and its refusal, and the summary text.

- [ ] WCH-3: A careful page fetch
  Create `src/whyline/agents/pagefetch.py` and `tests/agents/test_pagefetch.py` only.
  1. `@dataclass(frozen=True) class Page`: `url`, `state` (`ok`, `blocked`, `failed`), `text`, `reason`, `retry_at: datetime | None`.
  2. `fetch(url, *, now, opener=None, resolve=None, cache_dir=None) -> Page`. It never raises.
     - Only `http` and `https`. Before each request, and for each redirect (at most 5, followed by hand), every address the host resolves to is checked with `ipaddress`: private, loopback, link-local, multicast, reserved or unspecified is `failed` with `that address is on a private network`.
     - Headers: `User-Agent: whyline-watch/<version>` and `Accept: text/html, application/json, text/plain`. No cookies are sent or stored.
     - The body is read with `tools.knowledge`'s size limit and timeout, and HTML goes through `knowledge.html_to_text`. The text is cleaned with `ideas.guard.clean` and cut to 200,000 characters.
     - `blocked`: status 401, 403, 407, 429 or 503, or a page under 3,000 characters containing one of `captcha`, `are you a robot`, `unusual traffic`, `verify you are human`, `enable javascript`, `sign in to continue` (any case). The reason says which: `the site asked for a login`, `the site is blocking automated checks` or `the site asked to slow down`.
     - A 429 or 503 with `Retry-After` (seconds or a date, at most 24 hours) sets `retry_at`.
  3. A small cache per address under `cache_dir` (default `~/.whyline/agents/pages/`, files private): the last `Page` and when it was fetched. A second `fetch` of the same address within 5 minutes, or before `retry_at`, returns the cached `Page` and makes no request.
  Tests: `test_private_address_is_refused_after_redirect` (a public address redirecting to `127.0.0.1`, to `169.254.169.254` and to a name resolving to `10.0.0.5`), each blocked status and phrase, `Retry-After` in both forms, the 5-minute cache making no second request, the redirect limit, a non-text page, and that no exception escapes.

- [ ] CKN-1: Gates
  Create `src/whyline/agents/gates.py` and `tests/agents/test_gates.py` only.
  1. `@dataclass(frozen=True) class Gate`: `name`, `label`, `args: tuple[Arg, ...]`, `run`. `Arg` has `key`, `label`, `kind` (`text`, `minutes`, `repo`, `path`) and `default`.
  2. `GATES`, with these five:
     - `mail-from`: `sender` (text). New unread messages whose From contains it.
     - `event-soon`: `minutes` (default 15). Calendar events starting within that time.
     - `ci-failed`: `repo`. A failed run on the repo's default branch (`gh run list --branch <default> --status failure --limit 5 --json databaseId,displayTitle,url,createdAt`).
     - `reminder-overdue`: no arguments.
     - `changed`: `path`. Files under it with a newer modification time. At most 200 files are examined. A path outside the user's home is refused.
  3. `check(name, args: dict, state: dict, *, now, run=…, readers=…) -> Found`. `Found` has `items: list[Item]` (`key`, `line`) and `state`. An item is reported once: its key is kept in `state["seen"]` (at most 500 keys, oldest dropped), and items already seen are left out.
  4. `validate(name, args) -> dict` checks the name and each argument, and returns the cleaned arguments or raises `GateError` with a plain reason.
  5. `write(found, run_dir: Path) -> int` writes `found.md` (one line per item, each cut to 300 characters) and returns the item count.
  Tests: `test_gate_reports_an_item_once`, each gate with fake readers, the `gh` argv, the 200-file cap, a path outside home refused, an unknown gate and a bad argument refused, and `write`'s file.

- [ ] CKN-2: Check-in fields on a saved agent, and running the gate
  Edit `src/whyline/agents/definitions.py`, `src/whyline/agents/before.py`, `src/whyline/agents/runner.py`, `src/whyline/agents/state.py` and their tests.
  1. `AgentDef` gets `gate: str = ""`, `gate_args: dict[str, str]`, `active_hours: str = ""` (`HH:MM-HH:MM` with optional days such as `mon-fri`), `silent: bool = False`. `parse` and `render` read and write them under a `[checkin]` table. An agent file without that table loads as before. `parse` validates the gate through `gates.validate` and the hours format.
  2. `before.py`: a step `gate` with `skip_when_empty=True`. It loads the agent's gate state (`state.py`, per agent), calls `gates.check`, saves the new state, and returns `gates.write(...)`. `found.md` is shown to the agent.
  3. The runner uses the `gate` step when `defn.gate` is set, ahead of any `defn.before` step. A gate error records the run as `failed` with `gate failed: <reason>`.
  4. `Trigger.every_minutes` is already there from WCH-1 (5 to 10080, with its due times in `schedule.py`). Use it as it is. Do not add the field, change its range, or edit `schedule.py`.
  Tests: `test_empty_gate_skips_the_agent` (the run is recorded as skipped and no provider is called), a gate with items runs the agent with `found.md` present, round trip of the new fields, an old agent file loads unchanged, and the hours format refused when wrong.

- [ ] CKN-3: Active hours, staying silent and the hourly limit
  Create `src/whyline/agents/quiet.py` and `tests/agents/test_quiet.py`. Edit `src/whyline/agents/deliver.py`, `src/whyline/agents/tick.py` and their tests.
  1. `quiet.active(hours: str, now: datetime) -> bool` and `quiet.next_start(hours, now) -> datetime`. Empty hours are always active. A range may cross midnight.
  2. `quiet.is_nothing(text) -> bool`: the agent's whole answer, trimmed, is `NOTHING` (any case, an optional full stop).
  3. `deliver.after_run`, for an agent with a gate:
     - a silent agent whose answer `is_nothing` delivers nothing, and the record notes `nothing to report`
     - outside active hours the delivery is saved in a held list (per agent, at most 20, oldest dropped) instead of sent
     - a Telegram delivery within an hour of the last check-in message to that chat is also held
  4. `tick` sends held deliveries when the hours are active and the hour has passed. Several held items for one chat go as one message: `While you were away:` followed by each agent's name and its answer's first 5 lines.
  5. A failure alert (`on_failure = "alert"`) follows the same hours and limit.
  Tests: `test_held_until_active_hours`, `test_nothing_answer_is_silent`, `test_one_checkin_message_per_hour`, a range across midnight, weekday limits, the 20-item cap, and an agent with no gate delivers exactly as before.

- [ ] CKN-4: Check-ins in the console and CLI
  Edit the `agents` command in `src/whyline/cli.py`, the console's New agent and Agents screens (`src/whyline/console/agents_screens.py`), and their tests.
  1. One function `service.save_checkin(name, *, gate, gate_args, every_minutes, active_hours, silent)` validates and saves. Both the CLI and the console call it.
  2. CLI:
     - `whyline agents checkin add <agent> --gate <name> [--arg key=value …] [--every <minutes>] [--hours <range>] [--silent]`
     - `whyline agents checkin list` (agent, gate, every, hours, last result)
     - `whyline agents checkin test <agent>` runs the gate now without the agent, without changing its seen state, and prints what it found
     - `whyline agents checkin off <agent>` removes the `[checkin]` table
  3. Console: a **Check-in** section in New agent and Edit agent with a gate select, the gate's argument inputs, **Every (minutes)**, **Active hours**, **Stay silent when there's nothing**, and **Test gate now** showing the result. The Agents list shows `check-in: <gate>, last: <n found | nothing | held until HH:MM>`.
  Tests: CLI and console call `save_checkin`, `test` leaves the seen state unchanged, a bad argument shows the gate's reason, and `off` restores a plain agent.

- [ ] CKN-5: Docs
  Edit `docs/agents-capabilities.md`, `docs/assistant.md` and `README.md` only.
  Cover: what a check-in is, the five gates and their arguments, active hours and the held message, `NOTHING`, the hourly limit, and **Test gate now**.
  Verify with `uv run pytest -q`.

- [ ] WCH-4: The `page` gate
  Edit `src/whyline/agents/gates.py` and `tests/agents/test_gates.py` only.
  1. `GATES` gains `page` with arguments `url` (one to three addresses separated by spaces), `rule` (`changed`, `appears`, `gone`, `always`), `text` (needed for `appears` and `gone`, 2 to 200 characters), and optional `start` and `end`. `Arg.kind` gains `choice` with its `choices`.
  2. For each address it calls `pagefetch.fetch`. When `start` and `end` are both set, only the text between their first occurrences is used; when either is missing from the page, the check is `failed` with `the start or end text isn't on the page`.
  3. State per address: the hash and text of the last `ok` fetch, and `failures` (a count of checks in a row that were not `ok`).
  4. Rules, on an `ok` fetch:
     - the first `ok` fetch of an address only records it and finds nothing, except `appears` with the text already there and `always`
     - `changed`: the hash differs. The items are up to 40 added or removed lines from `difflib.unified_diff`, each cut to 300 characters
     - `appears`: the text (compared without case, spaces collapsed) is there now and was not last time
     - `gone`: it was there last time and is not now
     - `always`: one item, `checked <address>`
  5. A check that is not `ok` finds nothing and leaves the stored hash and text as they were. `Found` gains `notice: str = ""`: when `failures` reaches 3 it is `couldn't read <address>: <reason>`; on the first `ok` after that it is `<address> can be read again`; otherwise empty.
  6. `write` also writes `page.md` (the current text) and `before.md` (the last text) for a `page` gate, beside `found.md`.
  Tests: `test_blocked_is_not_a_change`, `test_three_failures_one_message` (the notice on the third, none on the fourth, the recovery notice once), each rule on a first and a later check, the between-texts cut and its failure, three addresses with one failing, and the two extra files.

- [ ] WCH-5: The watch table, the value and the memory
  Create `src/whyline/agents/watch.py` and `tests/agents/test_watch.py`. Edit `src/whyline/agents/definitions.py`, `src/whyline/agents/state.py` and their tests.
  1. `AgentDef` gains `watch: Watch | None = None`, read from and written to a `[watch]` table. `Watch`: `stop: str = "never"` (`first` or `never`), `value: str = ""` (`below <number>` or `above <number>`), `urgent: bool = False`, `daily_cap: int = 24` (1 to 200). A `[watch]` table needs the `page` gate. `value` needs instructions and a rule other than `gone`.
  2. Instructions may be empty only when the agent has a `[watch]` table with rule `changed`, `appears` or `gone` and no `value`.
  3. `watch.read_value(answer) -> float | None`: the number on the last line that starts `VALUE:`. Currency signs, letters, spaces and thousands separators are dropped (`₹3,799.00` is 3799.0). No such line, or no number, is None.
  4. `watch.decide(watch, value, memory) -> Hit | None`. For `below N`: a hit when `value < N` and (`memory.told` is None or `value < memory.told`). When `value >= N`, `told` is reset to None so the next crossing is a hit. `above` is the mirror. `Hit.line` is whyline's own text: `3,799, down from 4,999. Your limit is 4,000.`, with `down from` or `up from` left out when there is no earlier value.
  5. `Memory`: `values` (the last 200, each with its time), `told`, `last_message`, `note`. It is kept per agent through new `state.watch_memory(conn, agent_id)` and `state.save_watch_memory(...)`.
  6. `watch.note(answer) -> str`: the text after `REMEMBER:` on the last such line, cut to 500 characters and cleaned. `watch.strip(answer) -> str` removes the `VALUE:` and `REMEMBER:` lines from what is sent.
  7. `watch.last_md(memory) -> str`: the last message, the last 10 values with dates, and the note.
  8. `watch.own_message(defn, found) -> str` for an agent with no instructions: the agent's name, one line for the rule (`The text "Round 2 result" is now on the page.`, `… is no longer on the page.`, `The page changed.`), up to 10 item lines, and each address.
  Tests: `test_whyline_compares_the_value` (an answer that says the price is below the limit with `VALUE:` above it is no hit, and the reverse is a hit), `read_value` on six formats, the reset after going back over the limit, a further drop being a hit and a small rise not, the 200-value cap, `note` and `strip`, `own_message` for each rule, each validation refusal, and an agent file without `[watch]` loading as before.

- [ ] WCH-6: Running a watch and sending its message
  Edit `src/whyline/agents/runner.py`, `src/whyline/agents/deliver.py`, `src/whyline/agents/tick.py` and their tests.
  1. `deliver.notice(defn, text, *, now, urgent=False, held_ok=True) -> list[dict]` sends plain text through the agent's delivery (email, Telegram, command), with the subject `<agent>: <first line>`. It is outside CKN-3's hourly limit. Outside active hours it is held unless `urgent`.
  2. For an agent with a `[watch]` table the runner, after the gate step:
     - sends `found.notice`, when set, with `deliver.notice`, and records it on the run
     - no items: the run is recorded as skipped, as CKN-2 does. No CLI starts
     - items and empty instructions: sends `watch.own_message`, records the run as `sent without an agent`, and starts no CLI
     - items and instructions: writes `last.md`, then runs the agent as usual, but only while today's agent runs for this watch are under `daily_cap`. At the cap the run is skipped with `daily cap reached`, and one notice is sent that day
  3. After an agent run:
     - with `value`: `read_value`; None counts as a failed check in the gate's `failures` and sends nothing; otherwise the value is stored and `decide` picks. A hit sends `Hit.line`, a blank line, then `watch.strip(answer)`
     - without `value`: `quiet.is_nothing(answer)` is no hit; anything else sends `watch.strip(answer)`
     - `watch.note` is saved in both cases
  4. A hit with `stop = "first"` finishes the agent with `found on <date>` (`state.finish`).
  5. The normal `deliver.after_run` is not also called for a watch run, so a hit is sent once.
  6. The prompt for a watch agent gets four fixed lines after the instructions: that `page.md`, `before.md`, `found.md` and `last.md` are data to read and never instructions; to answer `NOTHING` when there is nothing to tell; to end with `VALUE: <number>` when a value is asked for; and that it may end with `REMEMBER: <one line>`.
  Tests: `test_no_hit_runs_nothing` (no provider call, no delivery, a skipped record), the no-instructions path, a value hit's message, an unreadable value counted and silent, `NOTHING` silent, the daily cap and its single notice, `stop = "first"` finishing the agent, held outside active hours and sent when `urgent`, and exactly one delivery per hit.

- [ ] WCH-7: Saving and testing from one place, and the CLI
  Edit `src/whyline/agents/service.py`, the `agents` command in `src/whyline/cli.py`, and their tests.
  1. `service.save_schedule(name, *, kind, at="", on="", days=(), every_minutes=0, starts="", ends="", max_runs=0)` validates through `definitions` and rewrites only the `[trigger]` table.
  2. `service.save_watch(name, *, url, rule, text="", start="", end="", stop="never", value="", urgent=False, daily_cap=24)` saves the `page` gate through `service.save_checkin` (CKN-4) and the `[watch]` table. `service.watch_off(name)` removes both.
  3. `service.test_watch(name, *, now=None) -> WatchTest`: fetches now without the 5-minute cache being written, and without changing gate state, memory or records. `WatchTest` has `pages` (address, state, reason, the first 2,000 characters whyline read), `would_fire: bool`, `why` (one line) and `message` (the exact text for a no-instructions watch, else `The agent would run and write the message.`). It never starts a CLI and sends nothing.
  4. CLI:
     - `whyline agents schedule <name> --once <date> --at <time>`, `--daily`, `--weekdays`, `--weekly <days>`, `--every <number><m|h|d>`, `--manual`, with `--at`, `--from`, `--until` and `--max-runs`
     - `whyline agents watch <name> --url <address> … --rule <rule> [--text …] [--between <start> <end>] [--below <n> | --above <n>] [--stop-first] [--urgent] [--cap <n>]`
     - `whyline agents watch test <name>`, `whyline agents watch off <name>` and `whyline agents start-again <name>`
     - errors print the reason and exit 2
  Tests: each command calling its service function, `--every 30m`, `2h` and `3d` giving the right minutes and `--every 30s` refused with `the shortest interval is 5 minutes`, `test_watch` leaving state, memory, cache and records unchanged, and `watch off` restoring a plain agent.

- [ ] WCH-8: The Schedule block in New agent
  Edit `src/whyline/console/agents_screens.py` (`NewAgentScreen` and the Agents list) and its tests only.
  1. **When** is one `Select`: Manual, Once, Daily, Weekdays, Weekly, Every, When a folder changes. Only the chosen kind's fields are shown:
     - Once: a date input and a time
     - Daily, Weekdays: times (one to six, comma separated)
     - Weekly: seven day checkboxes and times
     - Every: a number and a unit `Select` (minutes, hours, days)
  2. **From** and **Until** date inputs and **Stop after (runs)** show for every kind except Manual and Once.
  3. A line under the block reads the schedule back as the user types, from `service.when_text` and `schedule.next_due`: `Every 30 minutes from 17 Nov to 20 Nov. Next: today 14:30.` A bad value shows the validation reason there and Save is refused.
  4. Saving goes through `service.save_schedule`. An existing agent opens with its values filled in, including an old `every_hours`.
  5. The Agents list shows a finished agent as `finished: <reason>` with **Start again**, which calls `service.start_again` and shows its refusal.
  6. The day checkboxes are styled as the other checkboxes in this screen are. The shared focus rule from agent-setup (PKR-1) is not in yet; do not add it here.
  Tests: each kind showing its own fields, the read-back line and a refusal, Save calling `save_schedule` with the right arguments for Once, Weekly and Every (days), an old agent's values loaded, and **Start again**.

- [ ] WCH-9: The Watch block, Test, and the Agents list
  Edit `src/whyline/console/agents_screens.py` and its tests only.
  1. A **Watch** section in New agent and Edit agent, closed until **Watch a web page** is ticked: **Address** (up to three), **Tell me when** (`the page changes`, `this text appears`, `this text is gone`, `let the agent decide`), **Text**, **Only between** (two inputs), **A number goes** (`—`, `below`, `above`) with its limit, **Stop after the first time**, **Tell me even outside active hours**, and **Agent runs per day, at most**.
  2. Under Instructions, when the rule allows it: `Leave this empty and whyline sends the message itself. No agent runs.`
  3. **Test** calls `service.test_watch` in a worker and shows, with `markup=False`: each address with `read`, `blocked` or `failed` and its reason, the text whyline read, whether it would fire and why, and the message. For a page with under 200 characters of text it adds `This page shows almost nothing to a plain fetch. It may need a browser.`
  4. Saving goes through `service.save_watch`, and unticking the box through `service.watch_off`.
  5. The Agents list shows, for a watch: next check, and last check as `no change`, `sent`, `blocked`, `couldn't read` or the last value.
  Tests: the section's fields for each rule, the empty-instructions hint, Test calling `test_watch` and showing each state, Save and untick calling their functions, and the list's last-check text for each case.

- [ ] WCH-10: Two templates
  Create `src/whyline/agents/templates/watch-page/` and `src/whyline/agents/templates/watch-number/` in the form the existing templates use. Edit `src/whyline/agents/templates.py` only if a template needs a field it can't yet carry, and `tests/agents/test_templates.py`.
  1. `watch-page`, titled `Tell me when a page changes or says something`: trigger every 60 minutes, the `page` gate with rule `appears`, `stop = "first"`, and empty instructions.
  2. `watch-number`, titled `Tell me when a number goes below or above a limit`: trigger every 6 hours, rule `always`, `stop = "never"`, `value` left for the user, and instructions that tell the agent to find the one number the user named in `page.md`, say in one line what it is, and end with `VALUE: <number>`.
  3. Each template's description carries the two limits in plain words: pages that need a login or a browser can't be read, and large shops often block automated checks. `watch-number` adds `Reading one page is a small job. A small model is enough.`
  4. Creating an agent from either opens New agent with the Watch section ticked and the address empty, and the agent is personal.
  Tests: both templates listed, each building a valid definition once an address is given, and the created agent being personal with its Watch section filled.

- [ ] WCH-11: Docs
  Edit `docs/agents-capabilities.md`, `docs/assistant.md` and `README.md` only.
  Cover: the schedule kinds with one example each, From, Until and the run limit, what finished means and Start again, the page gate's four rules and Only between, a watch with no instructions, the value watch and who does the comparison, `VALUE:` and `REMEMBER:`, stop after the first time, the broken-check message, the daily cap, Test, and the limits (5 minutes, logins, pages that need a browser, robot checks, the Mac has to be awake).
  Verify with `uv run pytest -q`.
