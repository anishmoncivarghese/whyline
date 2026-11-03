# Resolve: talk it through, fix, check, continue

When a relay pauses, **Resolve** in `whyline console` (Relay mode) explains why
and offers safe buttons. **Ask agent** lets an AI read the logs and propose a
fix. Fix mode lets that conversation go further: the agent can edit files and
run checks, whyline checks the result, and the relay continues, all without
leaving the console.

Fix mode runs only while the relay is paused or stopped, never while it runs.

## The conversation

After **Ask agent** answers, the Resolve panel shows a reply box. Each reply
goes to the same agent together with the pause's original context and the
earlier turns, so follow-ups such as "why?", "try another way" or "run the
tests" keep what was said before. The transcript shows `you ›` and
`<agent> ›` lines.

- At Suggest level the agent is read-only. An answer may end with a proposal,
  which appears with **Apply** buttons.
- Typing `fix`, or pressing **Fix it**, switches this pause to Fix mode at the
  level you have set.
- A new pause starts a new conversation. The old one is kept.

## The three levels

Set the **Fix level** next to Resolve's Ask/Auto setting. It can also be
switched for one pause. The default is Fix with approval.

| Level | What happens |
|-------|--------------|
| **Suggest** | The agent only reads and proposes. Nothing is changed. |
| **Fix with approval** | The agent edits files and runs checks. You review the diff, then press **Approve and continue**. |
| **Auto fix** | The same, and whyline continues on its own when the checks pass. Only in Auto mode, and only inside the guard rails below. |

## What the agent may and may not do

May:
- edit files
- run tests and other checks
- run read-only git commands
- change relay config

May not:
- commit, push, reset, clean, rebase, stash or tag
- switch or delete branches
- edit the lines of ticked plan tasks
- edit the installed whyline tools, or write outside the repository

Commits stay whyline's own, made through catalog actions such as
`commit-task` and `config-commit`.

**whyline enforces this; it does not just ask.** The agent is started with its
CLI's own restrictions (for Claude, accept-edits mode with the git commands
above denied; for Codex, a workspace-write sandbox without network). An agent
whose CLI has no such guard is not offered Fix mode, and the next agent in the
chain is used. After every turn whyline then checks that HEAD, branches, tags,
`.git/config`, `.git/hooks`, ticked plan tasks and paths outside the repository
are unchanged. Any violation is undone and reported in plain words. If a remote
branch moved, whyline says the agent may have pushed; it cannot undo that. The
guard is a tripwire behind the CLI's sandbox, not a proof.

## Undo fix

Before the agent touches anything, whyline takes a snapshot of the whole
working tree: tracked changes, untracked files that are not ignored, and what
was staged. It is kept as `refs/whyline/fix/<id>`, and your HEAD, index and
files are not touched by taking it.

**Undo fix** puts the working tree back exactly as the snapshot had it:
modified and deleted files return, files the agent added are removed, ignored
files are left alone, and the same files are staged again. It refuses, and says
why, if HEAD or the branch has moved since the snapshot. The newest 20
snapshots are kept.

## Check, then continue

**Approve and continue** (or Auto fix) does not continue straight away. First
whyline runs:

1. `whyline-relay doctor`
2. the task's own `Verify with` commands from the plan, or the relay config's
   test command when the task has none

When everything passes, whyline applies the proposal's steps, and a final
`resume` or `start` launches the relay in the console, as the Resume button
does. The transcript says, for example,
`Fix checked (doctor ✓, tests ✓); resuming JOB-24.`

When a check fails, nothing continues. The failing output is added to the
conversation as the next turn, and the snapshot stays so you can still **Undo
fix**.

## Auto fix guard rails

Auto fix runs only when no rule-based fix applies, or one already failed on
this pause. Then:

- one fix attempt per pause
- a second pause with the same reason after an applied fix stops for you,
  naming the fix and its files
- a 20-minute cap on each fix turn
- the main agent first, then the backup chain on a limit or timeout
- steps outside the safe set stop and show the proposal. The safe set is Auto's
  usual one plus `run-check`, `config-commit`, `report-bug` and `undo-fix`.
- `commit-task` is automatic only after the task's handoff was approved

Every attempt (agent, diagnosis, files, checks, result) is recorded in
`recovery.json` and `.git/whyline-fix/attempts.json`. When Auto stops, the
panel says why and keeps the conversation open.

## Bugs in whyline itself

If the cause is a bug in whyline or whyline-relay, the agent does not edit the
installed tool. It proposes `report-bug` and, where there is one, a workaround.
`report-bug` adds an idea to the **Idea Inbox**, tagged `bug:whyline` or
`bug:whyline-relay`, with the pause reason, both versions and the agent's
diagnosis, ready to be fixed from the Inbox. See [idea-inbox.md](idea-inbox.md).

## Check a running relay

The **Check** button in the Relay row (Relay mode; enabled while a relay is
running or paused) asks the main agent, read-only, for a short health note:
stuck, going round in circles, quota risk, or fine. It sees the live marker,
elapsed turn time against the timeout, the last 200 transcript lines, quota
evidence, stage visits and send-backs, and plan progress. The answer appears as
`check › …`. Nothing is applied while the relay runs. If the answer has a
proposal, **Apply when paused** stores it and offers it at the next pause.

## Worked example: the WF-13 index.lock pause

WF-13 was approved by the reviewer, but the relay's own commit failed with a
`.git/index.lock` error, so the finished work sat uncommitted and the relay
paused.

1. Open Resolve and press **Ask agent**. The agent reads the log and the git
   state, and replies that WF-13's last handoff is approved, the lock file is
   stale (no git process is running), and the work was never committed. Its
   proposal has two steps: `run-check` to confirm no git process is running,
   then `commit-task WF-13`, then `resume`.
2. Press **Apply**. `commit-task` works only because WF-13's last handoff is
   approved. It commits the dirty files as `feat: <task title> (WF-13)`, ticks
   WF-13 in the plan, and commits `chore: tick WF-13 in the plan`: the same two
   commits the relay would have made.
3. whyline runs the checks, then the final step `resume` launches the relay in
   the console, which carries on with WF-14.

No screenshots to another chat, no commands to copy. If a step had gone wrong,
**Undo fix** would have restored the tree from the snapshot.
