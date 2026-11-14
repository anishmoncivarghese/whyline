<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-assistant-2-design.md | created: 2026-11-14T17:00:00+05:30 -->
# Assistant check-ins: gates, active hours and staying silent

Spec: `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 4. Task ids are CKN (CHK is used by the job search plans). Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **A gate is a `before` step.** `agents/before.py` already has `Step(run, skip_when_empty=True)`: a step that returns 0 skips the agent. Gates are new steps of that kind that take arguments.

Runs after `plans/assistant-memory.plan.md`, and before `plans/assistant-research.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: a saved agent runs on a clock and always delivers. There is no way to say "look every 15 minutes, start an agent only if something changed, and don't message me at night or when there's nothing to say".

What the user gets:
- A **check-in**: a saved agent with a gate, active hours and a stay-silent switch.
- Gates chosen from a list: new mail from a sender, a calendar event starting soon, failed CI on a repo, an overdue reminder, a changed file or folder.
- Nothing outside active hours. What was found is held and sent as one message when the hours begin.

Rules every task keeps:
- **Console first.** Everything here is set up in Agents in the console, saving through the same functions as `whyline agents checkin …`.
- **A gate is picked from the fixed list and never typed as a command.** Gate arguments are plain values (an address, minutes, a repo name from `ideas.setup.list_repos`, a path) and are checked before saving.
- **A gate uses no model.** It reads Mail, Calendar and Reminders through the existing `ideas/brief.py` readers, GitHub through `gh` with an argv list, and the file system.
- **Mail, calendar and file content are data.** What a gate writes for the agent goes in the run folder as files, like `brief-collect` does.
- **No new dependency.**
- **Tests:** never call osascript, `gh`, Telegram or a provider. Use fakes, temporary folders and an injected clock. Never sleep. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A gate that finds nothing starts no agent and sends nothing. CKN-2, `test_empty_gate_skips_the_agent`.
- The same item never fires a gate twice. CKN-1, `test_gate_reports_an_item_once`.
- Outside active hours nothing is delivered, and it arrives as one message when the hours begin. CKN-3, `test_held_until_active_hours`.
- An agent answering `NOTHING` delivers nothing and the run is still recorded. CKN-3, `test_nothing_answer_is_silent`.
- At most one check-in message per chat per hour. CKN-3, `test_one_checkin_message_per_hour`.

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
  4. `Trigger` gets `every_minutes: int = 0` (5 to 720), handled by `schedule.py` beside `every_hours`.
  Tests: `test_empty_gate_skips_the_agent` (the run is recorded as skipped and no provider is called), a gate with items runs the agent with `found.md` present, round trip of the new fields, an old agent file loads unchanged, the hours format refused when wrong, and `every_minutes` due times.

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
  Edit `src/whyline/agents/cli.py`, the console's New agent and Agents screens (`src/whyline/console/agents_screens.py` or the file that holds them), and their tests.
  1. One function `service.save_checkin(name, *, gate, gate_args, every_minutes, active_hours, silent)` validates and saves. Both the CLI and the console call it.
  2. CLI:
     - `whyline agents checkin add <agent> --gate <name> [--arg key=value …] [--every <minutes>] [--hours <range>] [--silent]`
     - `whyline agents checkin list` (agent, gate, every, hours, last result)
     - `whyline agents checkin test <agent>` runs the gate now without the agent, without changing its seen state, and prints what it found
     - `whyline agents checkin off <agent>` removes the `[checkin]` table
  3. Console: a **Check-in** section in New agent and Edit agent with a gate select, the gate's argument inputs, **Every (minutes)**, **Active hours**, **Stay silent when there's nothing**, and **Test gate now** showing the result. The Agents list shows `check-in: <gate>, last: <n found | nothing | held until HH:MM>`.
  Tests: CLI and console call `save_checkin`, `test` leaves the seen state unchanged, a bad argument shows the gate's reason, and `off` restores a plain agent.

- [ ] CKN-5: Docs
  Edit `docs/agents.md` (or the page that documents saved agents), `docs/assistant.md` and `README.md` only.
  Cover: what a check-in is, the five gates and their arguments, active hours and the held message, `NOTHING`, the hourly limit, and **Test gate now**.
  Verify with `uv run pytest -q`.
