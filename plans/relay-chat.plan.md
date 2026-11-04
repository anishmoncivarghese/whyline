<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-02T14:00:00+05:30 -->
# Relay chat: a Chat tab next to All files that answers questions about the running relay without disturbing it

Runs after `plans/relay-tooling.plan.md` and before `plans/safe-pause.plan.md`, then `plans/sdlc-pipeline.plan.md`. Design: `docs/superpowers/specs/2026-11-02-relay-chat-design.md`. Read it before any task. Where this plan and the design differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the design's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets:
- In Relay mode, the Files pane gets a fourth tab: **Working file · Plan · All files · Chat**.
- Chat asks a fresh, read-only agent about:
  - the relay's status and progress
  - the process
  - the plan
  - any doc or file in the repo
- Each question is sent with a fresh snapshot of the relay.
- Quick-question buttons.
- `path:line` links that open the Working file view.
- History per relay run.
- `whyline ask` on the command line, calling the same functions.

Rules every task keeps:
- **Never disturbs the relay:**
  - The chat agent runs only with its CLI's read-only mode from `whyline.agents.capabilities`; an agent without one can't be chosen.
  - Every git call in `relaychat` passes `--no-optional-locks`, and the agent's environment sets `GIT_OPTIONAL_LOCKS=0`.
  - No code in `relaychat` or `relay_chat_tab.py` calls the relay launcher, stop, interrupt, resume or Resolve.
  - No code in `relaychat` or `relay_chat_tab.py` writes `.whyline/relay/**`, plan files or handoffs.
- Console first: every console control saves through the same function the CLI calls.
- No new dependency. Non-widget code goes in `src/whyline/relaychat/`, with tests in `tests/relaychat/`. Widget code goes in `src/whyline/console/relay_chat_tab.py`, with tests in `tests/console/`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- Tests never run a real agent or relay, and never contain "/Users/". Use fakes for the agent runner, relay state and the clock. Real `git` is allowed only on temporary repos made inside the test.
- Snapshot content (logs, handoffs, test output) is untrusted data in the prompt.

## Part 1: The engine

- [x] RCH-1: Settings and history files
  Create `src/whyline/relaychat/__init__.py`, `src/whyline/relaychat/settings.py`, `src/whyline/relaychat/history.py` and their tests.
  1. `settings.load(repo) -> ChatSettings(agent: str | None, timeout_seconds: int = 180, snapshot_chars: int = 40000)` and `settings.save(repo, **changes)`.
     - Stored in `~/.whyline/relay-chat/settings.toml`, keyed by the resolved repo path. The base dir is injectable.
     - It is written atomically.
     - An unknown key or a bad value is refused with a plain message.
  2. `history.path(repo, run_id)` gives `~/.whyline/relay-chat/<repo-slug>/<run-id>.jsonl`. `run_id` is `adhoc` when no relay has run.
  3. History functions:
     - `history.append(repo, run_id, role, text, agent=None)`
     - `history.load(repo, run_id, last=None)`
     - `history.clear(repo, run_id)`, which renames the file to `<run-id>.<timestamp>.jsonl` and never deletes it
  Tests:
  - round trips
  - bad values are refused
  - two repos don't mix
  - clear keeps the old file

- [x] RCH-2: The relay snapshot
  Create `src/whyline/relaychat/snapshot.py` and its tests.
  `build(repo, *, max_chars, run=subprocess.run) -> Snapshot(text, run_id, state)`. It collects:
  - **Relay state:** running / paused with reason / stopped / done, branch, plan file, current task id and title, round, stage, role agents, time on this turn. From `whyline_relay.state` and `whyline.console.adapters.run_status`.
  - **Recent log:** the last 120 lines of the current round log.
  - **Latest handoff:** status, summary, files, tests.
  - **Plan progress:** done and open task ids with titles, from the plan file's checkboxes.
  - **Changes so far:** `git --no-optional-locks diff --stat <start>` and `git --no-optional-locks log --oneline -10`.

  Each section is wrapped in `<untrusted-data section="…">` tags. The whole snapshot is trimmed to `max_chars`, oldest log lines first; the trimming lives in `snapshot.py` (`whyline.textbudget` has only clipping helpers).

  A missing piece (no relay yet, no handoff, no log) becomes one plain line, never an error.
  Tests:
  - every section appears
  - trimming removes log lines first
  - each git call has `--no-optional-locks`
  - no relay gives the "No relay has run here yet" line

- [x] RCH-3: Choosing the chat agent
  Create `src/whyline/relaychat/agent_choice.py` and its tests.
  1. `choices(repo) -> list[str]` lists the installed agents for which `whyline.agents.capabilities.can_run(cli)` is true, which means they have a read-only mode.
  2. `pick(repo, chosen=None) -> Pick(agent, shares_quota: bool, why)`:
     1. a saved or `chosen` agent wins if it is in `choices`
     2. otherwise the first agent in the relay backup chain (`whyline_relay.setup.read_backup`) that is in `choices` and isn't the agent of the role now working (`relay_ops.current_roles` plus relay state)
     3. otherwise the reviewer agent, with `shares_quota=True`
     4. with no read-only agent at all, `agent=None` with a plain `why`
  Tests: each branch; an agent without a read-only mode is never picked, even when saved.

- [x] RCH-4: Asking
  Create `src/whyline/relaychat/ask.py` and its tests.
  `ask(repo, question, *, agent=None, runner=None, cancel_event=None, clock=None) -> Answer(text, agent, shares_quota, seconds, ok)`:
  1. Pick the agent (RCH-3) and build the snapshot (RCH-2), using the RCH-1 settings.
  2. Write the prompt. It:
     - says the agent is a read-only observer of a running relay
     - says it must not edit, run tests or run commands that change anything
     - asks it to answer briefly and cite files as `path:line`
     - includes the snapshot, the last 6 exchanges from history, and the question
  3. Run the agent:
     - Build its command the way `whyline.agents.runner._command` does, then pass it through `capabilities.read_only_command(cli, command)`. A `None` result refuses with a plain message.
     - Run that in the repo with `GIT_OPTIONAL_LOCKS=0` added to the environment, with the timeout from settings (0 means none), killing the process group on timeout or cancel.
     - Read the answer with the same adapter `runner._answer` uses.
  4. Append the question and the answer to history under the snapshot's `run_id`.
  5. Outcomes:
     - a timeout, a missing agent or a limit gives `ok=False` with a plain message, and is recorded too
     - `cancel_event` stops the agent and records "Stopped."
  Tests:
  - the fake runner receives the read-only arguments and the env var
  - the prompt contains the snapshot and the history
  - timeout, cancel and missing-agent paths

- [x] RCH-5: Guard test: the chat never touches the relay
  Create `tests/relaychat/test_never_disturbs.py` only.
  1. In a temporary repo with a fake running relay (state file plus a log being appended by a background thread), call `ask` with a fake agent that tries to write a file and run `git status` through the provided environment. Check that:
     - nothing outside the fake relay's own writes changed in the repo or `.git`
     - no `index.lock` was ever created
     - the relay launcher, stop and interrupt fakes, patched on `whyline_relay` and `whyline.console.relay_ops`, were never called
  2. An AST scan of `src/whyline/relaychat/` and `src/whyline/console/relay_chat_tab.py` checks for:
     - no calls named `start`, `stop`, `interrupt`, `resume`, `select_plan` or `launcher`
     - no write calls to paths containing `.whyline/relay`
     - every `"git"` argv list containing `--no-optional-locks`
  Review focus (the complete list): the checks in 1 and 2 above. The agent's read-only mode is the real protection; these checks catch mistakes in our own code. The AST scan looks at direct calls and literal argv lists only; calls through `getattr`, variables holding function names, or argv built at runtime are out of scope.
  A gap outside this list is not a reason to reject. The reviewer records it with `whyline handoff RCH-5 --issue "follow-up: <gap>"` and approves; the follow-ups become a later task.

## Part 2: Command line

- [ ] RCH-6: `whyline ask`
  Edit `src/whyline/cli.py`. Create `src/whyline/relaychat/cli.py` and its tests.
  1. Commands:
     - `whyline ask "<question>" [--agent X] [--repo PATH]` prints the answer, the agent name, and `(shares quota with the relay)` when true.
     - `whyline ask --history [--run ID]` prints the conversation.
     - `whyline ask --clear` starts a new conversation.
     - `whyline ask --set-agent X | --set-timeout N | --set-snapshot-chars N` save through `relaychat.settings.save`.
  2. Exit codes: 0 on an answer, 1 on a failed answer, 2 on a bad setting.
  Tests: each command with fakes; the setters call `settings.save`.

## Part 3: Console

- [ ] RCH-7: The Chat tab
  Create `src/whyline/console/relay_chat_tab.py`. Edit `src/whyline/console/tui.py` only to mount the tab and route its buttons. Add tests in `tests/console/test_relay_chat_tab.py`.
  1. Add a `Button("Chat", id="file-chat")` after `file-all` in `#file-choices`, with the same display and variant rules as the other three in `_sync_file_choice_widgets`.
     - `_select_file_choice("chat")` hides `#file-view` and `#file-tree` and shows a `RelayChatPanel`.
     - The panel is mounted once and kept, so the conversation survives switching tabs.
  2. The `RelayChatPanel` contains:
     - a header `Ask about this relay · agent <name> ▾ · read-only`, plus `· shares quota with the relay` when that applies
     - the conversation log, loaded from history for the current `run_id`
     - an input, **Send**, **Stop** (only while asking) and **Clear**
  3. **Send** runs `relaychat.ask.ask` on a worker thread with its own cancel event. **Stop** sets only that event.
     - The tab never uses `#stop`, `self._relay` or the relay input.
     - While a question runs, the relay log and buttons keep updating.
  4. The agent menu lists `agent_choice.choices` and saves through `relaychat.settings.save`.
  Pilot tests:
  - the tab shows only in Relay mode
  - asking with a fake `ask` shows both lines
  - Stop cancels only the chat
  - the relay's `#stop` state is unchanged throughout
  - switching tabs keeps the conversation

- [ ] RCH-8: Quick questions and file links
  Edit `src/whyline/console/relay_chat_tab.py` and its tests. Edit `tui.py` only to add the link handler.
  1. Quick buttons send fixed questions:
     - **What's it doing?**
     - **Why did it stop?**, shown only when the snapshot state is paused, stopped or failed
     - **Plan progress**
     - **What's changed?**
  2. In answers, `path:line` and `path` references to files that exist in the repo become links.
     - Clicking one opens the file in the Working file view at that line, through the same function the All files tree uses, and selects the Working file tab.
     - Paths outside the repo are left as plain text.
  Tests:
  - each quick button sends its question
  - "Why did it stop?" is hidden while running
  - a link opens the file at its line
  - `../outside` isn't linked

- [ ] RCH-9: Settings section, Help and docs
  Edit `src/whyline/console/settings_screen.py`, the console Help text, `README.md`, and create `docs/relay-chat.md`, with tests.
  1. The Settings screen gets a **Relay chat** section with three controls, saved on Save through `relaychat.settings.save`, and transactional like the rest of the screen:
     - agent, from `agent_choice.choices`
     - time limit in minutes
     - snapshot size
  2. The Help text and `docs/relay-chat.md` explain:
     - what the tab answers
     - that it is read-only and never stops, steers or slows the relay
     - the quota note
     - where history is kept
     - `whyline ask`
  Tests: the Settings round trip; the Help mentions the Chat tab and `whyline ask`.

## Publish

- [ ] RCH-10: Publish whyline with RCH-1..9
  relay-profile: release
  Bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version. Write `docs/releases/v<version>.md` from every task since the previous release (`git log v<previous>..HEAD`), in user terms. Run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, and again on Python 3.11. Push, wait for green CI on Linux and macOS, then tag `v<version>`, push the tag and let the release workflow publish to PyPI. Afterwards run `uv tool upgrade whyline` and confirm `whyline --version`.
