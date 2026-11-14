<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-14T23:30:00+05:30 -->
# Quick fixes: console restart, release notes review, live models and scheduled access

Runs after `plans/agent-tools.plan.md`, and before `plans/telegram-daily-use.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

This plan joins four small plans so they run in one relay and ship in one release. They were `console-restart`, `release-notes-review`, `relay-live-models` and `assistant-scheduled-access`. The tasks and their ids are unchanged. The four parts don't depend on each other; they run in the order below.

There is no publish task. When the relay finishes, press **Release** once for all four parts.

How to read this plan:
- **A task belongs to the part its id names:** CRS to Part 1, NOTE to Part 2, LMD to Part 3, ASST to Part 4.
- **A task keeps the rules of its own part, plus the rules for every part below.** Another part's rules and review focus do not apply to it.
- **A reviewer's bar is the task's own tests plus its own part's review focus list.** Parts 3 and 4 have no review focus list: their bar is the task's own tests. A gap outside the bar is recorded with `whyline handoff <task> --issue "follow-up: <gap>"` and the task is approved, never rejected for it.

Rules for every part:
- **Console first.** Every setting and action has a console counterpart saving through the same function as its CLI command.
- **No new dependency.** Keep Python 3.11 compatibility.
- **Tests never use a real provider, `gh`, a remote, the network or a real home directory.** Use fakes and temporary folders.
- **Edit only the files a task names, plus their tests.**
- **Release scope:** no version bump, tag, push or publish.

## Part 1: Console restart notice, crash log and a patient Ready check (CRS-1..4)

No separate design: the problem and the decisions are below.

Why: on 2026-11-13 a console started on 2026-11-12 before whyline 0.3.72 was installed kept running 0.3.71 in memory, and crashed on a bug 0.3.72 had already fixed (a `gh` timeout message shown as markup). Nothing told the user the console was out of date, the crash left only a long traceback in the terminal, and the Ready check that failed was a single 30-second `gh auth status` timeout that answered in 0.6 seconds a minute later.

What the user gets:
- When the whyline installed on disk is newer than the running console, the title says `whyline 0.3.73 is installed · restart to use it` and the existing **Restart** button appears. It is checked every 5 minutes and right after a release of whyline itself finishes.
- When the console crashes, the error is saved to `~/.whyline/crash.log` and the terminal shows one short message saying where. **Help** and `whyline doctor` show the last crash.
- A slow `gh` or git reply in the Ready check is tried once more before it counts as not ready.

Rules every task keeps:
- Console first: every console action calls the same function as its CLI command.
- No new dependency. Tests use temporary folders and fakes, never the network, a real `gh` or a real crash of the test process.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.

Review focus, each one pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- The installed version newer than the running one shows the notice; equal or older shows nothing. CRS-1, `test_notice_only_when_installed_is_newer`.
- Restart while a relay runs leaves the relay running and doesn't ask to pause it. CRS-1, `test_restart_leaves_relay_running`.
- A crash writes the log and the short message; the log keeps only the last 5 crashes. CRS-2, `test_crash_log_written_and_trimmed`.
- No secret reaches the crash log: values in the traceback's locals are not written. CRS-2, `test_crash_log_has_no_locals`.
- One `gh auth status` timeout, then success: the item is ready. Two timeouts: not ready, saying GitHub didn't answer. CRS-3, `test_ready_retries_a_timeout_once`.

## Part 2: Release notes review: a fixed check, a second agent, and a readable fallback (NOTE-1..6)

Spec: `docs/superpowers/specs/2026-11-15-release-hardening-design.md`, Part 1. Read it before every NOTE task. Where this plan and the spec differ, this plan wins. In particular:
- **The Telegram go-ahead's notes summary** is added by `plans/telegram-daily-use.plan.md` (WAIT-5), which runs later. This part only makes the summary line available as `notes.Checked.summary`.

Why: the release notes for 0.3.70, 0.3.71 and 0.3.72 each carried the writing agent's own chatter ("here are the release notes I created, please review") and were cleaned by hand. The `<notes>` markers cut text outside them, but nothing checks the text inside. When an answer is unusable the fallback is the raw commit list, which is how v0.3.73's notes came to list `chore: tick RCR-6 in the plan`.

What the user gets:
- Notes are checked by fixed rules, reviewed by a second agent that can only remove and reword, and checked again.
- The confirm window says who wrote them, who checked them and how many lines were removed, with a before and after.
- When notes can't be used, a grouped, readable commit list instead of the raw one.

Rules every task keeps:
- **Console first.** Every setting and action has a console counterpart saving through the same function as its CLI command.
- **A release never blocks on notes.** Any failure in the check or the review ends in the fallback, never in a stopped release.
- **The reviewer never adds.** Code enforces it by comparing the reviewer's output with the draft and the commit subjects. The reviewer's word is not trusted.
- **Both agent turns are read-only**, through `release.plan.default_ask_agent`'s path, in an empty temporary folder. Commit subjects and the draft are data inside labelled blocks.
- **No secret's value in a log, a dialog or a problem list.** A flagged secret is shown as its rule name and line number.
- **No new dependency.**
- **Tests:** never invoke a real provider, `gh` or a remote. Use fakes. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- The chatter lines that reached 0.3.70 to 0.3.72 are flagged. NOTE-1, `test_known_chatter_is_flagged`.
- An ordinary notes line that happens to contain "review" or "I/O" is not flagged. NOTE-1, `test_ordinary_lines_pass`.
- A line the reviewer invented is removed. NOTE-3, `test_reviewer_cannot_add`.
- Every failure path ends in notes, never in an exception that stops the release. NOTE-4, `test_notes_never_block_a_release`.
- A release with only process commits gets `Maintenance release.`, not an empty file. NOTE-2, `test_only_process_commits`.

## Part 3: Relay live models: change an agent's model from "Agents for this run" while the relay runs (LMD-1..2)

It needs whyline-relay 0.2.43 or later (RLY-18: `roles model`, `.whyline/relay/model-overrides.json`), which is on PyPI since 2026-11-12.

Why: on 2026-11-07, while release-button ran, the user opened Set up ("Agents for this run · CHF-3") and wanted to move claude from `sonnet` to `opus`. The screen can switch a role's agent (LIVE-1..4) but only lists models read-only in its summary ("Models: antigravity gemini-3.8-flash-high, claude sonnet, grok grok-4.6").

What the user gets:
- Each role row in "Agents for this run" gets a Model dropdown next to the agent dropdown, with the same options as Set up's model pickers.
- Save applies the model from that agent's next turn, never the current one. The row says "now opus · applies from its next turn".
- A model belongs to an agent, so changing claude's model on one row changes it on every row claude plays, and the screen says so.
- "Keep for future runs" also saves the model to `config.toml`, as it does for agents.

Rules every task keeps:
- The console never signals or restarts the relay for a model change. It only calls whyline-relay's `roles.switch_model`, the same function `whyline-relay roles model` calls.
- The model options come from `relay_ops.model_options_for_agent` and `cached_model_options`, the functions Set up uses. No new model list.
- Nothing in this part changes Set up for a stopped relay.

## Part 4: Assistant scheduled access: scheduled runs can see the Mac, and say so when they can't (ASST-24..27)

Spec: `docs/superpowers/specs/2026-10-26-personal-assistant-design.md`. These tasks were moved on 2026-11-15 from `plans/done/personal-assistant.plan.md`, unchanged. CLI commands live under `whyline idea …` and assistant files under `~/.whyline/ideas/`, as in that plan.

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

## Tasks

- [ ] CRS-1: Notice when a newer whyline is installed
  Edit `src/whyline/console/update.py`, `src/whyline/console/tui.py` and their tests only.
  1. `update.installed_version() -> str | None`: the `whyline` version installed on disk now, read fresh each call (`importlib.invalidate_caches()`, then `importlib.metadata.version("whyline")`); None on any error.
  2. The console compares it with `whyline.__version__` (the running code) at start, every 5 minutes, and when a release step `after` finishes in a repository whose `pyproject.toml` project name is `whyline`. When the installed one is newer (`update._newer`), it sets the title to `whyline <installed> is installed · restart to use it`, shows the existing `#update-restart` button and writes one log line `whyline <installed> is installed; this console is <running>. Press Restart to use it.` once per version. It hides **Update…** for that version or older.
  3. **Restart** keeps its current behaviour (`_restart_console`, `update.RESTART`). While a relay runs in this checkout the quit safeguard is skipped for this exit: the relay keeps running and the restarted console finds it, as it does today after a quit with **Leave it running**.
  Tests: `test_notice_only_when_installed_is_newer` (newer, equal, older, None), the 5-minute timer and the release trigger with fakes, one log line per version, **Update…** hidden, and `test_restart_leaves_relay_running`.

- [ ] CRS-2: Crash log
  Create `src/whyline/console/crashlog.py` and `tests/console/test_crashlog.py`. Edit `src/whyline/console/tui.py` (`launch`), `src/whyline/doctor.py`, the console Help text and their tests.
  1. `crashlog.record(error: BaseException, *, version: str, path: Path | None = None) -> Path` appends `--- <ISO time> · whyline <version> · <type>: <message>` and the plain traceback (`traceback.format_exception`, no locals, at most 200 lines) to `~/.whyline/crash.log` (0600), keeping the last 5 entries. `crashlog.last(path=None) -> tuple[str, str] | None` returns the last entry's header and text.
  2. `launch` records a crash whether Textual raises it out of `app.run()` or returns with the error stored (in textual 2.1.2, `app._exception` with a nonzero `app.return_code`), then prints `The console crashed: <type>: <first line of message>. Details are saved in ~/.whyline/crash.log. Start it again with: whyline console`. Textual's own traceback is still printed above it. `KeyboardInterrupt` and a normal exit write nothing.
  3. `whyline doctor` adds a line `Last console crash: <time> · <type> (~/.whyline/crash.log)` when there is one in the last 7 days. The console **Help** shows the same line, with **Copy** copying that entry.
  Tests: `test_crash_log_written_and_trimmed`, `test_crash_log_has_no_locals` (a local named `token = "secret-value"` in the failing frame is not in the file), both Textual paths with a fake app, nothing written on Ctrl-C, file mode 0600, the doctor line, and the Help line.

- [ ] CRS-3: Ready check tries a slow reply once more
  Edit `src/whyline/release/ready.py` and its tests only.
  1. An item whose check raised `subprocess.TimeoutExpired`, or that hit the overall time limit (`not checked (time limit)`), is run once more, alone, with the same 30-second command timeout, before it is reported. A second timeout reports `<item>: GitHub didn't answer in time; press Check again` for `gh` items and `git didn't answer in time; press Check again` for git items.
  2. The retry happens inside `check`, so the console **Check**, the release's Check ready step and `whyline release check` all get it.
  Tests: `test_ready_retries_a_timeout_once`, a non-timeout failure not retried, the time-limit case, and the message for a git item.

- [ ] CRS-4: Docs
  Edit `README.md` and the `docs/` pages on the console and releasing.
  Cover: restarting after an upgrade and the notice, `~/.whyline/crash.log` and what to send when reporting a crash, `whyline doctor`'s crash line, and Ready retrying a slow reply.
  Verify with `uv run pytest -q`.

- [ ] NOTE-1: The fixed check
  Edit `src/whyline/release/notes.py` and `tests/release/test_notes.py` only.
  1. `@dataclass(frozen=True) class Problem`: `line: int`, `text: str` (cut to 120 characters, a secret replaced by its rule name), `reason: str`, `removable: bool`.
  2. `lint(text: str, *, version: str, allowed_emails: frozenset[str] = frozenset()) -> list[Problem]`. A line is flagged, with these reasons:
     - `talks to the reader`: it matches, case-insensitively, at the start of the line or after a list marker: `here are`, `here is`, `here's`, `below are`, `below is`, `i have`, `i've`, `i created`, `i wrote`, `as requested`, `let me know`, `please review`, `please let`, `hope this helps`, `feel free`, `happy to`, or it ends with a question mark
     - `first person`: the words `I`, `I'm`, `I'll`, `my` or `me` as whole words, outside inline code (`` `…` ``)
     - `process noise`: after an optional list marker it starts with `chore: tick`, `chore: release`, `chore: record`, `chore: move finished plans`, `setup:`, `merge:` or `plan:`
     - `repeats the title`: a second `# v<version>` heading
     - `code fence around everything`: the first and last non-empty lines are fences (both are flagged, removable)
     - `secret`: a `security.secrets.scan_text` match (not removable by itself: the whole line is removed)
     - `home path`: `/Users/<name>`, `/home/<name>` or `C:\Users\<name>`
     - `email address`: one not in `allowed_emails`
     Every flagged line can be removed. A heading left with no bullets under it after removal is removed too.
  3. `clean(text, problems) -> str` removes the flagged lines and empty headings, and collapses runs of blank lines.
  4. `usable(text) -> bool`: at least one bullet or sentence remains besides headings.
  Tests: `test_known_chatter_is_flagged` (six real lines from the 0.3.70 to 0.3.72 drafts, written into the test), `test_ordinary_lines_pass` (`Review rounds now show…`, `Fixed I/O errors…`, `my-package` in code, `Improved the "I have a plan already" form`), each reason, a secret shown as its rule name, the empty-heading removal, and `usable`.

- [ ] NOTE-2: A readable fallback
  Edit `src/whyline/release/notes.py` and its tests only.
  1. `fallback(version, commits)` becomes grouped:
     - `## New` for subjects starting `feat:` or `feat(`
     - `## Fixed` for `fix:`
     - `## Docs` for `docs:`
     - `## Other` for the rest
     - process-noise subjects (NOTE-1's list) are dropped
     - each bullet is the subject without its prefix, without a trailing task id in brackets such as `(RCR-6)`, and with its first letter capitalised
     - an empty group is left out
  2. With nothing left, the body is `Maintenance release.`
  3. The result always passes `lint`.
  Tests: `test_only_process_commits`, each group, the prefix and task id stripped, a `feat(scope):` subject, and the fallback passing `lint` for a list holding every kind of subject.

- [ ] NOTE-3: The second-agent review
  Edit `src/whyline/release/notes.py`, `src/whyline/release/plan.py`, `src/whyline/relaychat/agent_choice.py` and their tests only.
  1. `agent_choice.pick_other(root, not_agent) -> str | None`: an enabled agent with a verified read-only mode other than `not_agent`, else None.
  2. `plan.default_ask_agent(root, *, agent: str | None = None)` takes the agent to use. With None it behaves as today. The function it returns exposes the agent's name as `.agent`.
  3. `notes.build_review_prompt(version, commits, draft, problems) -> str`: the commit subjects and the draft in labelled data blocks, the problems as `line <n>: <reason>`, and the instruction: remove lines that talk to the reader, are in the first person or are process noise; tighten wording; keep every real change; add nothing; return the notes between the same markers.
  4. `notes.review(version, commits, draft, problems, *, ask_agent) -> Reviewed` (`text`, `added: tuple[str, ...]`). After `extract`, each bullet of the result is kept only when it shares at least two words of four or more letters with some draft line or commit subject. A bullet that doesn't is removed and listed in `added`. A failed turn or an answer without markers returns the draft unchanged.
  Tests: `test_reviewer_cannot_add`, a reworded bullet kept, a removed line staying removed, an unmarked answer returning the draft, `pick_other` with one and with two agents, and `default_ask_agent` using the named agent.

- [ ] NOTE-4: Draft, check, review, check again
  Edit `src/whyline/release/notes.py`, `src/whyline/release/config.py`, `src/whyline/release/plan.py` and their tests only.
  1. `ReleaseConfig` gains `notes_review: bool = True` and `notes_reviewer: str = ""` (empty means any agent other than the writer), read and written like the other fields.
  2. `@dataclass(frozen=True) class Checked`: `text`, `writer`, `reviewer`, `removed: tuple[str, ...]`, `before: str`, `used_fallback: bool`, `summary: str`.
  3. `notes.checked(root, cfg, version, *, ask_agent, ask_reviewer=None, run, say=None) -> Checked`:
     - draft as today
     - `lint` and `clean` the draft
     - with `notes_review` on and a reviewer available, `review`, then `lint` and `clean` again
     - when the result is not `usable`, use `fallback`
     - `removed` is the lines taken out at any step. `before` is the first draft.
     - `summary` is one of: `Written by <writer>, checked by <reviewer>. <n> lines removed.`, `Written and checked by <writer> (only one agent is enabled). <n> lines removed.`, `Written by <writer>, checked by fixed rules only.`, or `The agent's notes couldn't be used; this is the commit list.`
     - any exception at any step is caught, and the result is the fallback with the last summary
  4. The release's notes step (`release/plan.py`) uses `checked`, writes `text`, and passes the `Checked` to the confirm function. `say` gets the summary, so it is in the release log in every mode.
  Tests: `test_notes_never_block_a_release` (the writer raising, the reviewer raising, lint raising through a patched rule), each summary, review off, one agent, the fallback when nothing usable is left, and round trip of the two settings.

- [ ] NOTE-5: The confirm window, settings and CLI
  Edit `src/whyline/console/release_screens.py`, `src/whyline/release/cli.py` and their tests only.
  1. The notes confirm window shows the summary line above the notes, and adds:
     - **See what was removed**: the first draft and the final text side by side, with the removed lines marked
     - **Use the commit list instead**: replaces the text with `notes.fallback`
     - **Edit** and **Approve**, as today. Edited text is linted on Approve, and problems are listed with **Approve anyway** and **Remove these lines**.
  2. All text in the window is shown with `markup=False`.
  3. Release → Set up: **Check release notes with a second agent** (checkbox) and **Reviewer** (a select of enabled agents plus `Any other agent`). CLI: `whyline release settings notes-review on|off` and `whyline release settings notes-reviewer <agent|any>`.
  4. CLI: `whyline release notes --check <file>` prints `lint`'s problems as `line <n>: <reason>` and exits 1 when there are any. The terminal confirm (`_confirmers`) prints the summary line and offers `[a]pprove, [e]dit, [c]ommit list, [s]top`.
  Tests: the summary shown, the before and after, the commit list button, an edited text with a problem offering both choices, text with square brackets shown as plain text, settings saved through one function, and `--check` exit codes.

- [ ] NOTE-6: Docs
  Edit `docs/release.md` and `README.md` only.
  Cover: the three steps, what the fixed check flags, that the reviewer can only remove and reword, the summary line and its four forms, the fallback groups, the two settings, and `whyline release notes --check`.
  Verify with `uv run pytest -q`.

- [ ] LMD-1: Console functions for a live model switch
  Edit `src/whyline/console/relay_ops.py` and `pyproject.toml` (and `uv.lock`), with tests in `tests/console/test_relay_ops_live_models.py`.
  1. Raise the `whyline-relay` floor in both places in `pyproject.toml` to the release with RLY-18 (`>=0.2.43,<0.3` if that is its version) and refresh `uv.lock`.
  2. Add `switch_model_live(root: Path, agent: str, model: str, *, keep: bool) -> str`, calling `whyline_relay.roles.switch_model` with the run's settings, the way `switch_live` calls `roles.switch`. It returns the relay's message, and lets `RoleSetError` through.
  3. Add `@dataclass(frozen=True) RunModel` with `agent`, `current`, `configured` and `pending: bool`, and `run_models(root: Path) -> dict[str, RunModel]`, from `config.toml` and `model-overrides.json`. `pending` is true while the running turn's model (from `running.json`'s `model`) differs from `current` for that agent.
  4. `RunRole` (from `run_roles`) is unchanged.
  Tests:
  - `switch_model_live` writes `model-overrides.json` and returns "claude → opus from its next turn."
  - `keep=True` also changes `[agents.claude] model` in `config.toml`
  - `run_models` shows `current="opus"`, `configured="sonnet"` after a switch, and `pending` while `running.json` says claude runs `sonnet`
  - an agent without `model_flag` raises with the relay's message

- [ ] LMD-2: Model dropdowns in "Agents for this run"
  Edit `src/whyline/console/relay_screens.py` (`RunAgentsScreen`), with tests in `tests/console/test_relay_screens.py`.
  1. Each role row gets a Model `Select` (`id="ra-model-<role>"`, width 26) after the agent `Select`, holding the options for the row's selected agent from `cached_model_options`, else `model_options_for_agent` in a worker, else the current model alone. "Default" means the CLI's own default (an empty model). Changing the agent dropdown refills the model dropdown for the new agent with that agent's current model selected.
  2. The model dropdown starts at `run_models(root)[agent].current`. Two rows with the same agent show the same model, and changing one updates the other.
  3. Save applies agent switches as today, then `switch_model_live` once per agent whose model changed, with the Keep checkbox's value. Errors go to `#ra-error` with the relay's message, and the other changes still apply.
  4. The row's reason line adds "model now opus · applies from its next turn" while `pending` is true, and the 2-second refresh keeps it current.
  5. The summary's "Models:" line shows a switched model as "claude opus (was sonnet)".
  6. The screen still fits 80x24. The `READ_ONLY` text becomes "The plan and other settings stay as they are while the relay runs. Stop the relay to change them."
  7. Console first: no new CLI is added here; `whyline-relay roles model` is the CLI counterpart.
  Tests (fake functions, no real relay):
  - choosing opus for the implementer row (claude) and Save calls `switch_model_live(root, "claude", "opus", keep=True)`
  - with Keep unticked the call has `keep=False`
  - the reviewer row, also claude, shows opus after the change on the implementer row
  - switching the tester row from antigravity to claude fills its model dropdown with claude's options and claude's current model
  - an agent error shows in `#ra-error` and the other row's model switch still applies
  - the pending line appears while `pending` is true and goes on the refresh after it turns false
  - the screen fits 80x24 with three rows of two dropdowns

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
