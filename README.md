# whyline

Records why your code exists, and tells the next agent.

Whyline is a locally controlled workspace for Claude Code, Codex, Grok, and
Antigravity. It preserves why code changed, coordinates reviewed work, runs
reusable read-only agents, and turns captured ideas into plans and
implementation.

Whyline adds the continuity that a direct agent session does not have:

- **Explain** a line from the decisions and commits that created it.
- **Build with Relay** through implementation, testing, review, and verification.
- **Run saved Agents** now, on a schedule, or from a local event.
- **Capture Ideas** in the console, from Telegram, or by authenticated email.

It is free, Apache-2.0, and has no Whyline account, telemetry service, paid
tier, or API key. It launches agent CLIs you already installed and signed in
to, so prompts and selected context still go to those providers. Telegram and
email use their own networks.

## Install and open the console

You need Python 3.11 or newer, Git, and at least one supported agent CLI that
is already installed and authenticated.

```bash
uv tool install whyline@latest
cd your-project
whyline init
whyline
```

`whyline init` creates the repository's `.whyline/` directory and offers to
install project instructions and hooks. It is safe to run again when Whyline
changes: managed instruction blocks are upgraded in place and the rest of
your files are left alone.

On first launch Whyline detects the agent CLIs available on this machine. The
full-screen console has three modes:

| Mode | What it does |
|---|---|
| **Chat** | Talks to the selected CLI with repository, model, backup, timeout, and attachment controls. |
| **Relay** | Creates or opens a plan, assigns roles, checks readiness, runs it, and guides pauses or recovery. |
| **Agents** | Creates and runs reusable read-only agents, and opens the Ideas and Inbox screens. |

Bare `whyline` opens the full-screen console when its UI is available.
`whyline console` opens the keyboard console, and `whyline console --ui`
explicitly requests the full-screen version. The CLI remains available for
scripts and explicit terminal workflows.

## Decision memory

Agents do not share their hidden conversations. Whyline gives the next one a
small, explicit record of the choices that matter: what was chosen, why, what
was rejected, which files were involved, and what remains risky.

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

That output is from this repository. An empty record produces an empty answer,
and `explain` says when it is making an inference.

### What is shared and what stays local

| Data | Location | Shared? |
|---|---|---:|
| Decisions and rejected alternatives | `.whyline/decisions.md` | Committed |
| Active handoff, claims, and activity ledger | `.whyline/` runtime files | Local |
| Repository saved-agent definitions | `.whyline/agents/` | May be committed |
| Accepted-agent state, run history, and delivery settings | `~/.whyline/agents/` | Local |
| Ideas, reports, documents, and workbook | `~/.whyline/ideas/` | Local unless delivered |

`whyline sync` compresses the active handoff, Git state, ownership warnings,
and relevant decisions into a bounded context block. Raw prompt text is not
included. See [how recording works](docs/recording.md) for the full layout.

The core commands are intentionally small:

```bash
whyline sync                         # active task context for this repository
whyline brief --file src/a.py        # bounded history for the next agent
whyline explain src/a.py:14          # why this line exists
whyline note "chose X" --because "Y" --rejected "Z: too slow" \
  --file src/a.py --actor codex --role implementer --task WL-42
whyline status                       # whether recording is healthy here
```

### Manual handoff

You can keep coordination completely explicit from the shell:

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
record, not a transfer of the previous agent's private conversation.

## Relay: reviewed delivery from request to release

Relay is included with Whyline but does nothing until you configure and start
it. It turns a Markdown plan into a controlled, multi-agent workflow:

```text
request
  → brainstorm and synthesis
  → reviewed spec and implementation plan
  → optional test plan
  → preflight and role assignment
  → implement → test → review → verify
  → approved commit
  → human release work
```

Open **Relay**, choose **Plan**, and start from a brainstorm, a description, an
existing plan, or **Auto**. Auto can carry one request through research, a
reviewed spec and plan, preflight, and the relay run.

Relay's controls make that automation bounded:

- Assign a different agent and model to implementation, testing, review, and
  other planning roles.
- Use an ordered backup chain when a provider is unavailable, logged out, or
  out of quota and failover is supported.
- **Check** validates the exact configuration, attachments, agent access,
  repository state, and plan without starting work.
- **Run** is enabled only for the configuration and repository state that
  passed Check; changing either invalidates the check.
- **Auto** advances safe stages but pauses for open questions, dangerous
  recovery, manual verification, and release tasks.
- **Resolve** shows the evidence and constrained fixes. Potentially destructive
  recovery still waits for you.
- **Resume** continues checkpointed work; **Stop** interrupts the current
  attempt rather than waiting for it to finish.
- **Files** opens a read-only pane that follows files changed by the active
  Chat, brainstorm, or Relay run.

For scripts and terminal-first operation, start with:

```bash
whyline relay init
whyline relay doctor
whyline relay setup
whyline relay status
```

The host-side Whyline committer may commit work after the configured review
and verification gates pass. Release steps remain human-owned and pause the
run until you mark them done or skip them.

## Saved Agents: reusable, accepted, and read-only

A Relay role collaborates on a repository plan. A saved Agent is different:
it is a reusable instruction set for read-only work, with a primary CLI,
backup chain, timeout, schedule or trigger, run history, and delivery settings.

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
must be accepted there:

```bash
whyline agents accept dependency-watch
whyline agents run dependency-watch
whyline agents history dependency-watch
```

Changing the definition invalidates that acceptance and stops unattended
runs until it is reviewed again. Claude Code, Codex, and Grok have verified
read-only launch modes. Antigravity supports interactive Chat and Relay work,
but saved unattended Agents exclude it because its CLI has no verified
read-only mode.

Results can stay in local history or be delivered by email, Telegram, or an
advanced after-run command, optionally with Markdown or Word attached.
Delivery failure is recorded separately and does not rewrite a successful run
as an agent failure.

On-demand Agents are useful anywhere the CLI runs. Scheduling, folder watches,
Mail rules, and the background heartbeat use macOS services. See the
[verified agent capabilities](docs/agents-capabilities.md) and
[Mail trigger recipe](docs/agents-mail-recipe.md).

## Idea Inbox: from a thought to reviewed work

Enter or send an idea, score and refine it, receive the brainstorm documents,
choose an allowed repository, and start Relay only after final confirmation.

```text
console, Telegram, or authenticated email
  → local idea backlog
  → quick score or multi-agent brainstorm
  → Word / PDF / Excel exports
  → reviewed spec and plan in an allowed repository
  → final confirmation
  → Relay
```

There are three entry points:

- **Console:** open **Agents → Ideas** for the backlog and **Agents → Inbox**
  for chats, senders, default agents, document formats, repositories, and the
  service.
- **Telegram:** `whyline idea telegram setup` connects a bot, finds private
  chats, lets you allow one, and offers to start the inbox. Cards expose only
  actions valid for the idea's current state, including status, Resolve, and
  confirmed Stop while Relay runs.
- **Email:** allow senders in the Inbox screen or with `whyline idea email
  allow person@example.com`, then install the Mail rule with `whyline idea
  email mail-script`. Mail is accepted only when the sender is allowed and
  its authentication results show DKIM or SPF pass. Consequential actions
  require a six-character confirmation code tied to the current idea revision.

Telegram intake uses private allowlisted bot chats; it is not end-to-end
encrypted. Email and the background inbox service currently rely on macOS
Mail and scheduling integration. Telegram keeps bot updates only for a limited
time, so the Mac must come back online to catch them.

Ideas run in their own workspace, not in arbitrary repositories. Planning is
limited to repositories you explicitly allow. The SQLite database under
`~/.whyline/ideas/` is authoritative; `ideas.xlsx` is a rebuilt export.

See [Idea Inbox setup and troubleshooting](docs/idea-inbox.md).

## Trust, privacy, and compatibility

Whyline is locally controlled, not isolated from every external service:

- Whyline has no hosted account, telemetry service, paid tier, or API key of
  its own.
- Agent CLIs use their existing authentication, provider terms, and provider
  data handling. Whyline never asks for or stores their API keys.
- Saved unattended Agents use tested read-only CLI modes and locally accepted
  definitions. This does not promise isolation from every source or tool an
  underlying CLI can read.
- Telegram chats are allowlisted but are not end-to-end encrypted.
- Email intake requires both an allowed sender and a DKIM or SPF pass; action
  codes expire when the idea revision changes.
- Relay pauses at dangerous recovery, manual verification, and release
  boundaries.

### Agent support

| Agent | Chat, brainstorm, and Relay | Saved unattended Agent |
|---|---:|---:|
| Claude Code | Yes | Yes, verified plan/read-only mode |
| Codex | Yes | Yes, read-only sandbox |
| Grok | Yes | Yes, edit and write denied |
| Antigravity | Yes, after repository trust approval | No verified read-only mode |

Whyline uses the subscription or account already active in each CLI.
`whyline account detect` refreshes Claude and Codex plan labels. Grok and
Antigravity are reported as installed or missing because their CLIs do not
expose the same plan check.

### Platform support

| Platform | Support |
|---|---|
| macOS | Full console, Relay, saved Agents, scheduling, Mail integration, background inbox service, and native PDF conversion. |
| Linux | Core CLI and console, interactive agents, Relay, and on-demand workflows; no macOS service or Mail integration. |
| Windows | Experimental and not a release gate. Some core paths are tested, but do not assume full workflow parity. |

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
