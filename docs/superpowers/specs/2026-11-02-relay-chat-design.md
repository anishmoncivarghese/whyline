# Relay chat: ask about the running relay without disturbing it

Date: 2026-11-02. Plan: `plans/relay-chat.plan.md` (RCH-1..10).

## Problem

While a relay runs, the user watches the log in Relay mode and wonders:
- what is it doing now?
- is it on track?
- why did the last round fail?
- what does LIVE-3 need?

Today the only way to ask is to leave the relay screen and use Chat mode. Chat mode isn't safe while the relay works on the same checkout, because chat agents may edit files.

The user asked for a Chat tab in the Files pane, next to **All files**. They can stay on the relay and ask about:
- its status and progress
- the process
- the plan
- any doc or file in the repo

The agent behind it is a fresh one and must never disturb the running relay.

## What the user gets

1. **A fourth tab in the Files pane:** **Working file · Plan · All files · Chat**.
   - It appears only in Relay mode, like the other three tabs.
   - It works while the relay runs, is paused, or is stopped.
2. **The Chat tab contains:**
   - A header line: `Ask about this relay · agent <name> ▾ · read-only`. The agent menu lists only agents that can run read-only.
   - Quick-question buttons: **What's it doing?** · **Why did it stop?** · **Plan progress** · **What's changed?**
     - **Why did it stop?** shows only when the relay is paused or stopped.
   - The conversation, newest at the bottom. The user's questions are marked `you`, and answers are marked with the agent's name.
   - An input line with **Send** and **Stop**. Stop cuts off only the chat agent.
   - **Clear** starts a new conversation. The old one stays in history.
3. **Clickable file references.** An answer that names `path:line` makes that a link. Clicking it opens the file at that line in the Working file view, and the tab switches to Working file.
4. **Answers come from a fresh snapshot.** Each question is sent with the relay's current state (below), so "what's it doing now?" is current, not what it was at the first question.
5. **History per relay run.** History is kept per relay run and survives a console restart. It is saved under `~/.whyline/relay-chat/`, never in the repo.
6. **CLI counterpart (console first):**
   - `whyline ask "<question>" [--agent X]` answers with the same snapshot and the same function.
   - `whyline ask --history` prints the current run's conversation.
   - `whyline ask --set-agent X --set-timeout N` saves the defaults through the same function the tab's controls use.

## What the snapshot holds

Built fresh for every question, capped at a size limit (default 40,000 characters, trimmed oldest-log-first):
- **Relay state:** running / paused (with reason) / stopped / done, branch, plan file, current task id and title, round, stage, role agents, time on this turn. This comes from `whyline_relay.state` and `adapters.run_status`.
- **Recent log:** the last 120 lines of the current round log.
- **Latest handoff:** status, summary, files, tests.
- **Plan progress:** done and open task ids with titles, read from the plan file's checkboxes.
- **Changes so far:** `git diff --stat` from the relay's start commit to the working tree, plus the last 10 commits on the branch.

Everything in the snapshot is wrapped as untrusted data in the prompt. The agent may read any file in the repo itself to answer questions about plans, docs or code.

## How it stays out of the relay's way

These are the requirements this feature exists for:
1. **Read-only by the CLI's own mode only.**
   - The chat agent runs with its read-only mode from `whyline.agents.capabilities` (Codex `--sandbox read-only`, Claude limited to read tools, and so on).
   - An agent without a read-only mode can't be chosen.
   - Resolve's "Ask agent" also checks for edits afterwards by comparing the tree before and after. That doesn't work here: the relay is editing the same tree at the same time, so the chat can't tell its own edits from the relay's. The read-only mode is the guard.
2. **No git locks.**
   - Every git call made by the chat code passes `--no-optional-locks`.
   - The agent's environment sets `GIT_OPTIONAL_LOCKS=0`.
   - This way a `git status` from the chat never takes `index.lock` while the relay commits.
3. **No relay control.** The chat code never:
   - calls the relay launcher, `stop`, `interrupt`, `resume` or Resolve
   - writes `.whyline/relay/**`, the plan file or the handoff
   - sends anything to the relay's input

   A test checks this.
4. **A separate process.**
   - It runs on its own console worker thread with its own cancel event.
   - The relay's Stop button and the chat's Stop button never affect each other.
5. **Its own quota by default.**
   - The default chat agent is the first read-only-capable agent in the backup chain that isn't the agent of the role now working.
   - If none qualifies, it uses the relay's reviewer agent, and the header says `shares quota with the relay`.
   - The user can pick any read-only agent from the menu.
6. **Limits:**
   - a time limit per question (default 3 minutes, 0 means none)
   - the snapshot size limit above
   - the last 6 exchanges of the conversation sent as context

## Decisions (my calls)

- **Reuse the read-only command builder.** Build the command as `whyline.agents.runner` does and make it read-only with `capabilities.read_only_command`. Don't use `adapters.run_chat_turn`. Chat mode's `chat.run_turn` allows edits and reports a diff stat, which is wrong here.
- **Code layout:**
  - non-widget code in `src/whyline/relaychat/`: `snapshot.py`, `ask.py`, `history.py`, `settings.py`
  - widget code in `src/whyline/console/relay_chat_tab.py`
  - `tui.py` changes only to mount the tab and route buttons
- **Settings location.** Settings are saved per repo in `~/.whyline/relay-chat/settings.toml`, keyed by repo path. They are not in `.whyline/relay/config.toml`, because that file is committed and the relay reads it.
- **History location.** History is saved as `~/.whyline/relay-chat/<repo-slug>/<run-id>.jsonl`. The run id comes from relay state, or `adhoc` when no relay has run.
- **Placement in the Settings screen.** The Chat tab's own header holds its settings. The console Settings screen gets a short **Relay chat** section with the same three controls (agent, time limit, snapshot size), saved through `relaychat.settings.save`.

## Later, not in this plan

- **Pass to relay:** a button on an answer that queues it as a note for the next agent turn, only on the user's tap. It depends on the live-agents work (LIVE-1..4), and it deliberately crosses the "never disturbs" line, so it needs its own design.
- Chat in Agents and Workflows modes.

## Out of scope

- Answering for a relay in another repo than the console's current one.
- Running tests or commands that change anything.

## Testing

- Unit tests use a fake agent runner and fake relay state on temporary repos.
- A guard test runs `ask` while a fake relay is "running", and checks that:
  - the repo and `.git` are byte-identical apart from the fake relay's own writes
  - no `index.lock` was taken
  - every subprocess git call has `--no-optional-locks`
  - the relay launcher and stop fakes were never called
- A Textual pilot test covers the tab: it appears only in Relay mode, quick buttons send their questions, a `path:line` link opens the Working file view, and the chat's Stop doesn't touch the relay's Stop.
