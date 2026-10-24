# whyline

## Build software from idea to release-ready code with the AI subscriptions you already have.

Whyline coordinates Claude Code, Codex, Grok, and Antigravity through a
review-gated software-delivery workflow. It can capture an idea, run a
multi-agent brainstorm, create the specification and implementation plan,
assign agents to build and review the work, verify the result, and preserve
why every important decision was made.

```text
idea
  → score and multi-agent brainstorm
  → reviewed specification and implementation plan
  → preflight and role assignment
  → implement → test → review → verify
  → approved commit
  → human-controlled release
```

Whyline uses the agent CLIs already installed and signed in on your computer.
The work runs through the Claude, ChatGPT/Codex, Grok, or Antigravity account
you already use—without requiring separate model API keys or a Whyline
subscription.

### What Whyline gives you

- **A complete path from idea to implementation.** Start in the console, from
  Telegram, or by authenticated email; finish with reviewed, verified code.
- **Multi-agent brainstorming and planning.** Let several agents research an
  idea, synthesize the findings, and produce reviewed planning documents.
- **Controlled autonomous execution.** Relay can progress through safe stages
  on its own while pausing for questions, unsafe recovery, manual checks, and
  release work.
- **The best agent for each role.** Choose different agents and models for
  planning, implementation, testing, review, and verification, with ordered
  backups when a provider is unavailable or out of quota.
- **Reusable Agents.** Create accepted, read-only agents for recurring work;
  run them now, on a schedule, or from a local event.
- **Decision memory.** Record the reasoning and rejected alternatives behind
  a change so the next agent understands the code instead of starting over.

Whyline is free and Apache-2.0 licensed. It has no hosted Whyline account,
telemetry service, paid tier, or model API key of its own.

## Install

You need Python 3.11 or newer, Git, and at least one supported agent CLI that
is already installed and authenticated.

```bash
uv tool install whyline@latest
cd your-project
whyline init
whyline
```

That one installation includes Whyline's console and Relay. You do not need to
install `whyline-relay` separately.

`whyline init` creates the repository's `.whyline/` directory and offers to
install project instructions and hooks. It is safe to run again after an
upgrade: Whyline updates its managed instruction blocks without replacing the
rest of your files.

Bare `whyline` opens the full-screen console when its UI is available.
`whyline console` opens the keyboard console, and `whyline console --ui`
explicitly requests the full-screen interface.

## One console, four connected workflows

The console starts with three modes. Ideas and Inbox live inside Agents mode.

| Mode | Use it for |
|---|---|
| **Chat** | Talk to the selected agent CLI with repository, model, backup, timeout, and attachment controls. |
| **Relay** | Brainstorm or open a plan, assign roles, check readiness, run the work, and resolve pauses. |
| **Agents** | Create and run reusable read-only agents; open the Ideas backlog and Inbox settings. |

The workflows connect rather than living as separate tools:

1. **Ideas** captures and develops the work.
2. **Relay** plans, implements, tests, reviews, and verifies it.
3. **Saved Agents** handle repeatable analysis and monitoring.
4. **Decision memory** carries the reasoning into every future session.

## From idea to reviewed implementation

Enter an idea in the console, send it from Telegram, or email it from an
allowed address. Whyline can score and refine it before any repository work
begins.

### Brainstorm with multiple subscriptions

A brainstorm can use several available agents, multiple review passes, a
chosen final writer, a backup agent, and a timeout. Each agent researches
independently before Whyline merges the work and asks the final writer for a
synthesis.

The result is saved as a durable Markdown document. Idea Inbox workflows can
also deliver reports and plans as Word and PDF documents, with an Excel export
of the idea backlog.

### Create the specification and plan

Choose an allowed repository and its saved setup. Whyline drafts a reviewed
specification and implementation plan, routes any planner questions back to
you, and keeps the documents attached to the idea that produced them.

Nothing starts merely because a plan exists. Whyline shows the repository,
agents, models, timeout, and other run settings for final confirmation, then
reruns preflight before Relay begins.

### Run the plan with Relay

Relay turns a Markdown plan into a controlled multi-agent run:

- Assign a different agent and model to each role.
- Configure an ordered backup chain for supported failover conditions.
- Use **Check** to validate agent access, attachments, configuration,
  repository state, and the plan without starting work.
- Use **Run** after the exact checked configuration is ready.
- Use **Auto** to advance through safe planning and delivery stages.
- Use **Resolve** when a pause needs a constrained decision based on evidence.
- Use **Resume** to continue checkpointed work and **Stop** to interrupt the
  current attempt.
- Use **Files** to follow files changed by the active Chat, brainstorm, or
  Relay run from inside the console.

Relay coordinates implementation, tests, review, verification, and the
approved commit. It pauses instead of guessing when a question, dangerous
recovery step, manual verification, or release task needs a person.

For terminal-first operation:

```bash
whyline relay init
whyline relay doctor
whyline relay setup
whyline relay status
```

## Saved Agents: reusable work, not one-off prompts

A Relay role collaborates on one repository plan. A saved Agent is a reusable
instruction set for read-only work, with a primary CLI, backup chain, timeout,
schedule or trigger, run history, and delivery settings.

Create one from **Agents → New agent**, or keep a repository definition such
as `.whyline/agents/dependency-watch.toml`:

```toml
name = "dependency-watch"
instructions = """
Review this repository's dependencies and report important security or
compatibility changes. Do not edit files.
"""
runner = "codex"
backup = ["claude", "grok"]
timeout_minutes = 30

[trigger]
kind = "weekdays"
at = "09:00"
```

Before a repository Agent can run unattended on a Mac, its current definition
must be accepted on that computer:

```bash
whyline agents accept dependency-watch
whyline agents run dependency-watch
whyline agents history dependency-watch
```

Changing the definition invalidates acceptance and prevents another
unattended run until you review it again. Results can remain in local history
or be delivered through email, Telegram, or an advanced after-run command.
Delivery failure is recorded separately from the agent's result.

Claude Code, Codex, and Grok have verified read-only launch modes for saved
Agents. Antigravity can participate in Chat, brainstorms, and Relay, but is
excluded from unattended saved Agents because its CLI has no verified
read-only mode.

On-demand Agents work wherever the supported CLI runs. Scheduling, folder
watches, Mail rules, and the background heartbeat use macOS services. See the
[verified agent capabilities](docs/agents-capabilities.md) and
[Mail trigger recipe](docs/agents-mail-recipe.md).

## Idea Inbox: start work away from the terminal

Idea Inbox gives you a local backlog and three ways to add or control work:

- **Console:** use **Agents → Ideas** to score, brainstorm, refine, reopen,
  drop, export, or plan an idea. Use **Agents → Inbox** to configure chats,
  senders, agents, document formats, repositories, and the background service.
- **Telegram:** connect a bot to an allowlisted private chat. Its cards expose
  only actions valid for the idea's current state, including confirmation,
  status, Resolve, and Stop while Relay is running.
- **Email:** allow a sender, then email an idea with optional brainstorm
  settings in the body. Consequential steps require the six-character code
  Whyline sends back, tied to that exact idea revision.

Ideas run in their own workspace, not in arbitrary repositories. Planning is
limited to repositories you explicitly allow, and Relay starts only after the
final confirmation.

The SQLite database under `~/.whyline/ideas/` is authoritative;
`ideas.xlsx` is a rebuilt export. Telegram is not end-to-end encrypted, and
email intake requires both an allowed sender and a DKIM or SPF pass. The
background inbox, Mail integration, and native PDF conversion are currently
macOS features.

See [Idea Inbox setup and troubleshooting](docs/idea-inbox.md).

## Decision memory: preserve why, not hidden conversations

Agent sessions do not share their private conversation history. Whyline gives
the next agent a small, explicit record of what was chosen, why it was chosen,
what was rejected, which files were involved, and what remains risky.

```text
$ whyline explain src/whyline/runner.py:46

src/whyline/runner.py:46

Last touched by   anish
Commit            bc677e4  ·  2026-08-17

Decision          Resolve runner injection points at call time, not in the signature
Because           default arguments bind at import time, so monkeypatching runner.shutil.which had no effect and a test exec'd the real codex binary, replacing the pytest process
Rejected          patch the default argument tuple in tests
                  couples every test to CPython internals

Confidence        High — a recorded decision matches the commit for this line.
                  one recorded decision matches the commit that wrote this line
```

That output comes from this repository. An empty record produces an empty
answer, and `explain` says when it is making an inference.

| Data | Location | Shared? |
|---|---|---:|
| Decisions and rejected alternatives | `.whyline/decisions.md` | Committed |
| Active handoff, claims, and activity ledger | `.whyline/` runtime files | Local |
| Repository saved-Agent definitions | `.whyline/agents/` | May be committed |
| Accepted-Agent state, run history, and delivery settings | `~/.whyline/agents/` | Local |
| Ideas, reports, documents, and workbook | `~/.whyline/ideas/` | Local unless delivered |

`whyline sync` turns the active handoff, Git state, ownership warnings, and
relevant decisions into a bounded context block. It does not include raw
prompt text. See [how recording works](docs/recording.md) for the full model.

The core commands remain available for scripts and explicit workflows:

```bash
whyline sync                         # bounded context for this repository
whyline brief --file src/a.py        # focused history for the next agent
whyline explain src/a.py:14          # why this line exists
whyline note "chose X" --because "Y" --rejected "Z: too slow" \
  --file src/a.py --actor codex --role implementer --task WL-42
whyline status                       # whether recording is healthy here
```

### Manual handoff

```bash
whyline claim WL-42 --actor codex --role implementer --file src/cache.py
whyline run codex "implement bounded cache invalidation" --task-id WL-42

whyline handoff WL-42 --from codex --to claude --status ready-for-review \
  --summary "bounded invalidation implemented" \
  --file src/cache.py --test "pytest -q: passed" \
  --risk "large repositories not benchmarked"

whyline run claude "review the cache change" --task-id WL-42
```

Claims are advisory warnings, not locks. A handoff is an explicit project
record, not a transfer of the previous agent's hidden conversation.

## Subscriptions, privacy, and control

Whyline does not proxy model traffic or require model API credentials:

- It launches the agent CLI you selected using the authentication already
  active in that CLI. A CLI authenticated with a subscription or its own API
  key still works; Whyline does not ask for, store, or forward that credential.
- Prompts and selected context still go to the chosen agent provider under
  that provider's terms and data-handling policy.
- Whyline has no hosted account, telemetry service, or paid orchestration
  tier. Project and workflow state are controlled from your machine.
- Saved unattended Agents use tested read-only CLI modes and locally accepted
  definitions. This is not a promise that an underlying CLI is isolated from
  every source or tool it can access.
- Telegram and email use their own networks and credentials. Telegram chats
  are allowlisted but not end-to-end encrypted.
- Relay pauses at dangerous recovery, manual verification, and release
  boundaries.

`whyline account detect` can refresh Claude and Codex subscription labels.
Grok and Antigravity are shown as installed or missing because their CLIs do
not expose the same plan check.

### Supported agents

| Agent | Chat, brainstorm, and Relay | Saved unattended Agent |
|---|---:|---:|
| Claude Code | Yes | Yes, verified plan/read-only mode |
| Codex | Yes | Yes, read-only sandbox |
| Grok | Yes | Yes, edit and write denied |
| Antigravity | Yes, after repository trust approval | No verified read-only mode |

### Platform support

| Platform | Support |
|---|---|
| macOS | Full console, Relay, saved Agents, scheduling, Mail integration, background Inbox service, and native PDF conversion. |
| Linux | Core CLI and console, interactive agents, Relay, and on-demand workflows; no macOS service or Mail integration. |
| Windows | Experimental and not a release gate. Some core paths are tested; do not assume full workflow parity. |

## Learn more

- Run `whyline --help`, `whyline relay --help`, `whyline agents --help`, or
  `whyline idea --help` for the current command surface.
- Read [recording and repository state](docs/recording.md),
  [attachment compatibility](docs/attachments-capabilities.md),
  [measurement notes](docs/measurement.md), and
  [performance measurements](docs/performance.md).
- Browse the [release notes](https://github.com/anishmoncivarghese/whyline/releases)
  or [open an issue](https://github.com/anishmoncivarghese/whyline/issues).

## Licence

Apache-2.0.
