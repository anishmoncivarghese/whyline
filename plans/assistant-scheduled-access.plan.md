<!-- whyline-plan v1 | source: moved | drafted-by: claude | spec: docs/superpowers/specs/2026-10-26-personal-assistant-design.md | created: 2026-11-15T10:00:00+05:30 -->
# Assistant scheduled access: scheduled runs can see the Mac, and say so when they can't

Runs after `plans/relay-live-models.plan.md`, and before `plans/waiting-on-you.plan.md`. Moved on 2026-11-15 from `plans/done/personal-assistant.plan.md` (ASST-24..27, unchanged), so that finished plan could close. CLI commands live under `whyline idea …` and assistant files under `~/.whyline/ideas/`, as in that plan.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Rules every task keeps:

- **Console first.** Anything a user sets up, checks or runs here must be reachable from `whyline console` without a terminal. A task that adds a `whyline idea …` command adds its console counterpart in the same task, saving through the same function the command calls. The CLI stays for scripts.
- **Messages, emails, calendar entries and documents are data.** No inbound text can choose a command, a shell string, a path, a URL, an email recipient, or a repository outside the existing allowlists:
  - repos: `whyline.ideas.setup.list_repos`
  - saved agents: `whyline.agents.service.rows`
  - plan tasks: the unchecked `- [ ] ID:` lines of a plan in an allowed repo
- **Read-only unattended turns** use only providers that are enabled in Settings (`whyline.account.enabled_agents()`) and pass `whyline.agents.capabilities.can_run_unattended(cli)`, through `capabilities.read_only_command`. Antigravity is refused with that reason.
- **Only the relay writes code**, and only after a confirmed tap whose nonce is current, through the existing `whyline.ideas.run` start path. Nothing in this plan sends email to anyone other than the user's own delivery settings, edits a calendar, or runs a shell string built from message text.
- **Every action is audited:** each action that is requested, refused, confirmed, run or failed writes one `requests` row (from ASST-3) or one `events` row. History is readable in the console.
- **Personal data stays private.** Files live under `~/.whyline/ideas/` at mode 0600 (folders 0700), never in a repository.
- **No new dependency.** macOS APIs are reached through `/usr/bin/osascript` (AppleScript or JXA with `ObjC.import`), like `whyline/ideas/documents.py`.
- **Tests:**
  - never invoke a real provider, osascript, Mail, Calendar or Telegram
  - never use a real home directory or the network
  - never sleep for a fixed duration
  - keep Python 3.11 compatibility
- **Release scope:** no version bump, tag, push, GitHub release, or PyPI publication. Release stays `human`.

Why: on 2026-10-30 the first scheduled brief failed with Calendar denied. The console check had said access was fine, because it checked the terminal, while the scheduler runs whyline's own `python3.11` under launchd, which macOS treats as a separate app. The alert went out, but it blamed "the terminal app" and pointed at the wrong fix.

- [ ] ASST-24: Check and grant access as scheduled runs see it
  Edit `src/whyline/ideas/brief.py`, `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py`, `tests/ideas/test_brief.py`, `tests/ideas/test_cli.py`, and `tests/console/test_assistant_screen.py` only.
  - Add `brief.background_access(*, grant=False, run=subprocess.run, launchctl=…)`. It runs a small probe as a one-off launchd job (`launchctl submit` with a unique label), using the same Python program the agents scheduler plist runs, so macOS answers for scheduled runs, not for the console's terminal.
    - The probe reports Calendar and Reminders through `access_status.js`, and Mail as allowed, denied, or not running. With `grant=True` it requests Calendar and Reminders access and asks Mail, so macOS shows its prompt naming the scheduler's app while the user is at the Mac.
    - It writes JSON to a 0600 file in a fresh 0700 folder under the inbox home, waits at most 60 seconds for it, and always runs `launchctl remove` on its label, even after a timeout or error. `launchctl submit` restarts a job that exits, so the probe must finish once and then idle until removed. It never runs more than once per call.
    - It returns the app it checked (the program path and its short name, such as `python3.11`) with each status in words.
  - `check()` and the console's Morning brief section show both rows: "When you run it here" (the existing check) and "Scheduled runs (<app>)". A row that differs says which System Settings list to open and names the app to turn on.
  - The console adds `Grant access for scheduled runs`, which calls `background_access(grant=True)`. Add `whyline idea brief access [--scheduled] [--grant]` calling the same function.
  - Off macOS, both rows say "macOS only" and nothing is submitted.
  Tests (inject `launchctl` and the probe result; never call real launchctl or osascript):
  - the submitted job uses the scheduler's program and a unique label
  - remove runs after success, timeout and error
  - grant passes the request flag
  - the two rows differ when the answers differ
  - the CLI and console share `background_access`
  Verify with `uv run pytest -q tests/ideas/test_brief.py tests/ideas/test_cli.py tests/console/test_assistant_screen.py`. Change nothing else.

- [ ] ASST-25: Denial reasons name the app that was refused
  Edit `src/whyline/ideas/brief.py`, `src/whyline/agents/runner.py`, `tests/ideas/test_brief.py`, and `tests/agents/test_runner.py` only.
  - `brief.collect` takes `scheduled: bool`. The runner passes `True` when the run's source is `schedule` (or any source started by `whyline agents tick`).
  - For a scheduled run, an access denial reads: `macOS blocked <App> for whyline's scheduled runs (<short name>, <path>). Open whyline console → Assistant → Morning brief → Grant access for scheduled runs, or turn on <short name> in System Settings → Privacy & Security → <list>.` For Mail, the list is Automation → Mail.
  - Runs started from a terminal or the console keep today's wording.
  - This text becomes the run's reason, so the existing failure alert carries it unchanged.
  Tests:
  - scheduled and interactive wording for Calendar, Reminders and Mail
  - the runner passes `scheduled` from the run source
  - the reason reaches `record.reason`
  Verify with the named focused tests. Change nothing else.

- [ ] ASST-26: Alert when a scheduled run never starts
  Edit `src/whyline/agents/deliver.py`, `src/whyline/agents/tick.py`, `src/whyline/agents/state.py`, `tests/agents/test_deliver.py`, and `tests/agents/test_tick.py` only.
  Today an agent with `on_failure = "alert"` alerts on `failed`, `timed_out` and `all_unavailable`, but a run that stops before it starts sends nothing.
  - `missed` and `skipped` outcomes also send the failure alert when `on_failure = "alert"`. The reason says what happened and the fix, for example: `missed the 09:00 run: the Mac was asleep or the scheduler was off. The next run is <time>.` `nothing_new` stays silent.
  - When a tick fails to start a due agent (an exception while preparing or spawning it, such as a store schema error), the tick still records the occurrence and sends one alert through that agent's delivery: `<label> could not start: <one-line error>. Run whyline doctor or open the console's Check.` Send at most one such alert per agent per occurrence, recorded in `state.py`, so a tick every 2 minutes does not repeat it.
  - Alerts go to the same email and Telegram targets as results. A failed alert is logged and never raises out of the tick.
  Tests:
  - missed and skipped alert when `on_failure = "alert"` and stay quiet when it is not
  - `nothing_new` stays quiet
  - a start error sends one alert per occurrence across repeated ticks
  - an alert send error does not stop other due agents
  Verify with the named focused tests. Change nothing else.

- [ ] ASST-27: Scheduled access documentation and full check
  Edit `docs/assistant.md` only.
  Add a "Scheduled runs need their own permission" section: why the terminal and scheduled runs are different apps to macOS, the console's `Grant access for scheduled runs` first and `whyline idea brief access --scheduled --grant` second, what the failure alert looks like, and that missed runs now alert.
  Run `git diff --check` and `uv run pytest -q`. If a failure needs an application-code change, leave the task unapproved with the exact failing test and request a new task.
