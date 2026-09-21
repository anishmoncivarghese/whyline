# whyline-relay — design

**Date:** 2026-09-20  
**Status:** Awaiting owner review  
**Target:** `whyline-relay` 0.1.0 (separate repository and distribution)  
**Depends on:** whyline >= 0.2.2 on PATH  
**Source PRD:** whyline-relay PRD v0.1 (Anish, 2026-09-20)

## 1. Goal

Run a planned sequence of tasks through the Codex/Claude pair without a human
acting as the scheduler. Codex implements, Claude reviews and commits, and the
relay decides whose turn it is by reading whyline's own handoff record.

whyline stops at making each handoff explicit; the human still switches
terminals and retypes prompts for every task. The relay closes that gap and
nothing more. It runs no model, holds no credentials, and never judges whether
code is correct or a command is safe. It routes, verifies, and pauses.

## 2. Positioning

whyline's published claim is that it does not orchestrate, recorded in the
v0.2.0 decision: a scheduler "would add credential, supervision, and
vendor-output coupling outside Whyline's purpose". That claim stays true.

The relay ships as a separate repository and a separate PyPI distribution. It
depends on the `whyline`, `codex`, and `claude` executables being on PATH and
never imports whyline as a library. A user who wants whyline's recording
without orchestration installs only whyline and is unaffected by this work.

The relay calls `codex` and `claude` directly rather than `whyline run`, because
`whyline run` uses `os.execvp` to replace the calling process — running it would
terminate the relay.

## 3. Decisions

### 3.1 The agent writes the handoff; the relay verifies it

The relay reads `.whyline/active-handoff.json`, which carries a fresh `uuid`
per event (`events.new_event`). Before launching an agent the relay records the
current event `id`. After the agent exits it re-reads:

- **Same `id`** — the agent finished without handing off. Pause. Never infer a
  verdict from exit status or output.
- **New `id`** — route on `(to_actor, status)`.

Rejected: having the agent write a simpler `verdict.json` that the relay
translates into `whyline handoff`. It would route more reliably, but the
handoff record would then be written by the relay rather than by the agent,
which destroys the measurement in §9 — whether agents under automation still
record their own handoffs and decisions is the open question this tool exists to
answer. A relay that writes the records cannot measure whether agents would.

Rejected: accepting either protocol, preferring a real handoff. Two protocols to
document and test, and a muddier metric, for a failure mode that a clear pause
already handles.

### 3.2 Statuses need no change to whyline

`whyline handoff --status` is a free-form string with no `choices=` constraint
(`src/whyline/cli.py`). `assigned`, `ready-for-review`, `changes-requested`,
`approved`, and `blocked` all work against whyline 0.2.2 unmodified. This
closes PRD open question 4: no whyline change is required.

The `[status_map]` config table is kept anyway, so a user who prefers different
strings changes config rather than code.

### 3.3 Fresh session per round

Each agent turn is a new process with no vendor-side session resumption — no
`claude --resume`, no `codex exec resume`. Context is reconstructed from
`whyline sync --task <id>`, which is the mechanism whyline exists to provide.

This closes PRD open question 3. A crashed or timed-out round therefore costs
nothing beyond its own work, and `resume` never needs to recover a vendor
session id.

### 3.4 Vendor commands are configuration, not code

The PRD's commands are already stale against the installed toolchain:
`codex-cli 0.155.1` has no `--full-auto` anywhere, and `codex exec` has no
`--ask-for-approval`. Sandboxing is now `-s/--sandbox` with values
`read-only`, `workspace-write`, `danger-full-access`.

Defaults as of this design:

| Agent | Command |
|---|---|
| Codex | `codex exec -s workspace-write --color never <prompt>` |
| Claude | `claude -p --permission-mode acceptEdits --output-format json --settings .whyline/relay/claude-settings.json <prompt>` |

Both are overridable in `config.toml`. The prompt is appended as the final
argument. Verified present on `codex-cli 0.155.1` and `claude 2.1.277`.

### 3.5 Never bypass, never widen

The relay never passes `--dangerously-skip-permissions`,
`--dangerously-bypass-approvals-and-sandbox`, or
`--dangerously-bypass-hook-trust`. Permission is declared once, up front, in a
reviewable allowlist committed to the repository (§6). When an agent reports a
denied action, the relay pauses and prints it; it does not retry with broader
permission.

## 4. Architecture

Package `whyline_relay`, entry point `whyline-relay`, Python 3.11+, standard
library only (`subprocess`, `json`, `tomllib`, `pathlib`, `signal`), matching
whyline's zero-dependency rule. macOS and Linux; Windows untested.

| Module | Responsibility |
|---|---|
| `plan.py` | Parse the Markdown checklist into tasks; tick one checkbox by rewriting one line |
| `config.py` | Load `.whyline/relay/config.toml` over built-in defaults |
| `handoff.py` | Read `.whyline/active-handoff.json`; expose `(id, to_actor, status, summary)` |
| `agents.py` | Launch one agent, tee output to terminal and log, enforce timeout, return exit code |
| `prompts.py` | Render `implement.md` / `review.md` templates |
| `gitcheck.py` | Branch guard, dirty guard, HEAD-moved and task-id-in-message verification |
| `loop.py` | The state machine — the only module that decides anything |
| `notify.py` | Best-effort desktop notification |
| `cli.py` | `init`, `start`, `resume`, `status`, `stop` |

Every module except `loop.py` is a pure function of its inputs or a thin
subprocess wrapper. Routing lives in exactly one file.

## 5. Behaviour

### 5.1 Plan file

Tasks are Markdown checklist items, default `plan.md`, run in file order;
checked items are skipped:

```markdown
- [ ] WL-1: Add bounded cache invalidation
      Cache must evict on write, not on a timer.
- [x] WL-0: Scaffold module
```

The task id is the leading token before the first colon. Indented lines beneath
a checkbox are the task's detail block and are passed to the implementer
verbatim. Only the relay ticks a checkbox, and only after the verification in
§5.4 passes.

### 5.2 Loop

For each unchecked task, starting at round 1:

1. Check for `.whyline/relay/STOP`; if present, exit cleanly.
2. `whyline claim <task> --actor codex --role implementer`.
3. Run Codex with the implement prompt.
4. Re-read the handoff and route:

| `to_actor` | `status` | Action |
|---|---|---|
| `codex` | `assigned` / `changes-requested` | Run Codex with the implement prompt |
| `claude` | `ready-for-review` | Run Claude with the review prompt |
| any | `approved` | Verify the commit (§5.4), tick the box, advance |
| any | `blocked` | Pause |
| any | unchanged `id` | Pause: agent exited without handing off |
| any | anything else | Pause: unrecognised status |

A `changes-requested` handoff increments the round and carries its `summary`
into the next implement prompt as `{review_feedback}`.

### 5.3 Prompts

`init` writes `.whyline/relay/prompts/implement.md` and `review.md`.
Placeholders are `{task_id}`, `{task_text}`, `{sync_packet}`, `{round}`,
`{review_feedback}`, substituted by `str.replace` — not `str.format`, because
the prompts contain JSON and shell braces that `.format` would reject.

Each prompt is assembled as: the output of `whyline sync --task <id>`, then the
task block, then the role instruction, then a fixed closing paragraph naming
the exact `whyline note` and `whyline handoff` commands to run with their
`--to` and `--status` values written out literally. An agent that has to invent
an argument value is an agent that pauses the run.

Codex's closer names `--to claude --status ready-for-review` and forbids
committing. Claude's names the two permitted outcomes: commit with the task id
in the message then `--status approved`, or `--to codex --status
changes-requested` with concrete, actionable feedback.

### 5.4 Commit verification

On an `approved` handoff, before ticking the checkbox the relay confirms that
`HEAD` differs from the commit recorded when the task started and that the new
commit's message contains the task id. If either check fails, it pauses. A
ticked box in `plan.md` therefore always corresponds to a real commit.

### 5.5 Output and logs

Agent stdout and stderr stream to the user's terminal as they arrive and are
written to `.whyline/relay/logs/<task>-<round>-<agent>.log`. Output is never
parsed for routing. It is scanned for known vendor rate-limit phrases only to
give a pause a useful reason; an unrecognised failure still pauses.

### 5.6 Pause, stop, resume

`.whyline/relay/state.json` holds `{plan, branch, task_id, round,
last_handoff_id, paused_reason, log_path}` and is written before every exit,
including SIGINT and timeout. Every pause prints the reason, the log path, and
the resume command.

- `stop` writes the `STOP` file; the current agent finishes and nothing new starts.
- SIGINT terminates the running agent's process group and saves state.
- `resume` reloads state and re-enters the loop at the same decision point.

### 5.7 Guards

Refuse to start on `main` or `master` without `--allow-main`; the default is to
create or switch to `relay/<plan-name>`. Refuse to start with a dirty working
tree without `--allow-dirty`. Cap review rounds per task (default 3). Each
agent run has a timeout (default 30 minutes) after which its process group is
killed and the relay pauses. The relay never pushes to a remote.

## 6. Permissions

`whyline-relay init` prints the proposed allowlist and asks before writing it,
following `whyline init`'s confirmation style. It is written to
`.whyline/relay/claude-settings.json`, stored in the repository so it is
reviewable and diffable, and passed to Claude with `--settings`. It is
deliberately **not** `.claude/settings.json`: measured on claude 2.1.278, Claude
Code ignores a project's `permissions.allow` under `claude -p` until the
workspace has been trusted interactively (`Ignoring 7 permissions.allow entries
… this workspace has not been trusted`), so a fresh checkout would silently get
no permissions and every Bash command, including `git commit` and
`whyline handoff`, would be denied. Flag-supplied settings are honored
regardless.

```json
{
  "permissions": {
    "allow": [
      "Edit",
      "Bash(pytest:*)",
      "Bash(uv run pytest:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(git diff:*)",
      "Bash(git status:*)",
      "Bash(git log:*)",
      "Bash(whyline:*)"
    ],
    "deny": ["Bash(git push:*)", "Bash(rm -rf:*)"]
  }
}
```

Two presets, chosen by sniffing for `pyproject.toml` or `package.json`: Python/uv
and Node/npm. They differ only in the test-runner entries.

Codex runs under `-s workspace-write` with network disabled. That sandbox does
**not** stop it running `git commit`: measured on codex-cli 0.155.1, asked to
commit, it did. "Codex never commits" is therefore enforced by the relay, not
the sandbox: after every Codex turn `loop.py` checks that HEAD did not move and
pauses, with the undo command, if it did.

Codex hooks are not needed: every prompt embeds the `whyline sync` output
itself, and in the measured run the hooks fired under `codex exec` regardless.
`init` therefore does not check hook trust.

## 7. CLI and configuration

```
whyline-relay init                  # allowlist + prompt templates, asks first
whyline-relay start --plan plan.md  # begin at the first unchecked task
whyline-relay resume                # continue after a pause or Ctrl+C
whyline-relay status                # task, round, whose turn, last pause reason
whyline-relay stop                  # write the STOP file
```

Flags: `--max-rounds N`, `--timeout MIN`, `--branch NAME`, `--only <task-id>`,
`--allow-main`, `--allow-dirty`, `--dry-run`.

`.whyline/relay/config.toml`, all keys optional:

```toml
plan = "plan.md"
max_rounds = 3
timeout_minutes = 30
branch_prefix = "relay/"

[agents.codex]
command = ["codex", "exec", "-s", "workspace-write", "--color", "never"]

[agents.claude]
command = ["claude", "-p", "--permission-mode", "acceptEdits", "--output-format", "json", "--settings", ".whyline/relay/claude-settings.json"]

[status_map]
review = "ready-for-review"
changes = "changes-requested"
approved = "approved"
blocked = "blocked"
```

`.whyline/relay/` is gitignored except `config.toml` and `prompts/`, which the
user may commit.

## 8. Testing

`agents.py` resolves the agent binary through a lookup function called at
invocation time, never captured at import time or bound as a default argument.
whyline's `runner.py` carries comments from two incidents where a cached
`shutil.which` caused a test run to exec the real Claude Code (2026-08-17 and
2026-08-18). The same discipline applies here, and a test asserts it.

The full loop is tested against fake agent scripts — a few lines of Python that
write a handoff and exit — covering: single task, multi-task, `changes-requested`
round, round cap, timeout, STOP file mid-run, agent exiting without a handoff,
unrecognised status, `approved` without a commit, and resume after each pause
kind. No vendor process is launched by the test suite, and no subscription quota
is spent.

`--dry-run` prints the rendered prompts and the exact argv for each step without
launching anything.

## 9. Success metrics

Measured the way whyline's `m0/` study was, with thresholds fixed before
collection:

| Metric | Target |
|---|---|
| Plans completed with no human intervention beyond intended pauses | >= 70% |
| Agent turns that ended in a valid handoff | >= 90% |
| Decisions recorded per non-trivial task under relay | Not below the direct-session baseline |
| Reviewer rulings reaching `decisions.md` | Above the current near-zero baseline |
| Unsafe actions executed outside the allowlist | 0 |

The third and fourth matter most. whyline's own data shows dispatched agents
recorded no decisions, because they followed the dispatcher's prompt rather than
`AGENTS.md`. Headless runs still load `AGENTS.md` and `CLAUDE.md`, and §5.3
restates the instruction in every prompt, but this must be measured rather than
assumed.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Vendor CLI flags change | Commands are configuration; `--dry-run`; fake-agent suite. Already realised: `--full-auto` is gone |
| Agent exits without handing off | Handoff `id` comparison; pause |
| Agents loop on disagreement | Round cap |
| Allowlist too narrow, runs keep pausing | Presets per stack; the denied action is printed; user edits and resumes |
| Allowlist too broad | Explicit deny list; no push; branch isolation; the relay pauses if Codex moves HEAD (its sandbox does not block commits) |
| Decision recording drops under automation | Measured in §9; instruction restated per prompt |
| Subscription rate limits | Known limit phrases produce a clear pause reason |

## 11. Delivery

1. **M1 — dry run.** Parse the plan, read the handoff, render prompts, print the
   commands. No agent launched.
2. **M2 — single task.** One task through implement, review, and commit against
   the real CLIs. **Owner watches this before M3 begins.**
3. **M3 — full loop.** Multi-task plans, rounds, pause, resume, stop, logs.
4. **M4 — init and presets.** Allowlist writer, templates,
   notifications.
5. **M5 — measurement.** A real project run reported against §9, failures
   included. Out of scope for 0.1.0.

## 12. Out of scope

Planning (`plan.md` stays hand-written; PRD open question 2 is deferred),
parallel agents, pushing to remotes, terminal or UI driving, any permission
bypass, and any change to whyline itself.
