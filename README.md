# whyline

### Put every AI subscription you already pay for to work, together.

Whyline turns **Claude Code, Codex, Grok and Antigravity** into one team on
your own computer. Ask all of them the same hard question at once. Have one
write the code while another tests it and a third reviews it. Run agents on a
schedule while you're away. Send work from Telegram or email and approve it
with a tap.

It drives the official CLIs you're already signed in to, so it runs on the
**Claude, ChatGPT, Grok and Google accounts you already have**.
**No API keys. No per-token bill. No Whyline account.**

[![PyPI](https://img.shields.io/pypi/v/whyline)](https://pypi.org/project/whyline/)
[![Python](https://img.shields.io/pypi/pyversions/whyline)](https://pypi.org/project/whyline/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

```bash
uv tool install whyline@latest
cd your-project && whyline init
whyline
```

---

## Why whyline

Many developers now pay for two or three AI plans. Each plan lives in its own
terminal, knows nothing about the others, and stops when it hits its usage
limit. Wiring models together usually means API keys and a second bill on top
of the subscriptions you already have.

Whyline puts them to work together:

| Without whyline | With whyline |
|---|---|
| One model's opinion | Several models research on their own, critique each other, and one writes the final answer |
| You copy output between Claude and Codex | One agent writes, another tests, another reviews, in one run |
| Work stops when a plan hits its limit | An ordered backup chain takes over |
| AI only works while you sit at the terminal | Saved agents run on a schedule and deliver results by email or Telegram |
| Ideas wait until you're back at your desk | Send an idea from your phone and get a scored report, a brainstorm and a plan back |
| Each new session starts blind | Decisions, rejected options and risks are recorded for the next agent |

## What you can do with it

### 🧠 Ask the whole panel

Type `/brainstorm` and choose which models take part. Each one researches the
topic **on its own**. The drafts are merged, the models review each other for
as many passes as you choose, and the model you pick writes the final
synthesis. The result is saved to `docs/brainstorm/`.

It works for anything you'd want several expert opinions on, not just code:

- *"Should we move this service from Postgres to DynamoDB?"*
- *"Review this PRD and list what's missing"* (attach the PDF or screenshots)
- *"Plan a launch strategy for this project"*
- *"What are the failure modes of this trading strategy?"*

### 🛠️ Turn a request into reviewed, tested code

**Relay** runs a Markdown plan task by task with a team you choose:

```text
idea → brainstorm → spec and plan → implement → test → review → verify → commit → you release
```

- **A different agent and model for each role**, for example Grok writes the
  code, Grok runs the tests and Codex reviews.
- **Auto** starts from a one-line request: it researches, drafts the spec and
  plan, runs a full preflight check, and launches the run. Any pause stops it
  for you rather than guessing.
- **It pauses instead of guessing** when it hits a question, a risky recovery
  step, a manual check, or a release.
- **Resolve** explains why it paused and offers safe options. **Ask agent**
  lets an AI read the logs and propose the fix.
- **Files** shows the agent's current output, the live plan, and the whole
  repository in a side pane.

### 🔁 Keep going when a plan runs out

Each role can have an **ordered backup chain**. When one agent reports a usage
limit, the next one takes over. Resolve names the model that ran out, offers
another, and offers to switch back once the original is signed in again. On a
Mac, **Awake** keeps the computer from sleeping through a long run.

### 🤖 Agents that work while you don't

A **saved Agent** is a reusable, **read-only** job with its own instructions,
main CLI, backups and timeout:

- **Triggers:** run it now, daily, on weekdays, every few hours, when files
  land in a folder, or from a Mail rule.
- **Delivery:** results arrive by **email or Telegram**, as text or a Word
  document, and every run is kept in history.
- **Unattended safety:** each Agent must be accepted on this computer before
  it runs unattended, and editing it requires a fresh acceptance. It pauses
  itself after repeated failures, or when a CLI is logged out.

Examples: a weekday dependency and security watch, a nightly summary of what
changed in a repository, or a weekly review of open issues.

### 📱 Run it from your phone

The **Idea Inbox** connects a private Telegram bot, and authenticated email,
to your Mac:

1. Message an idea and get a card back with buttons: **Brainstorm**, **Quick
   score** or **Cancel**.
2. Scores and brainstorms come back as **Word and PDF** documents, and the
   backlog stays in an **Excel** workbook.
3. Ask for a spec and plan for one of your allowed repositories. If the
   planner has questions, they come to the chat.
4. Tap **Start** to launch Relay. You can check status any time. Pauses
   arrive with **Resolve** options as buttons, and **Stop** is always one
   confirmed tap away.

Reply in plain words instead of tapping a button, and an assistant proposes
the matching card. Nothing changes until you tap **Confirm**.

### 📝 Remember why the code is the way it is

Agents don't share their private conversations. Whyline keeps a small,
committed record of each decision: why it was made, which options were
rejected, and which tests and risks go with it. `whyline init` offers to
install instructions and hooks that point each agent at it, and
`whyline sync` hands the next agent a short summary.

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
```

`git blame` tells you who changed a line. `whyline explain` tells you why.

---

## How it works

```text
              your computer                                  providers
┌─────────────────────────────────────────────┐
│ whyline console  (Chat · Relay · Agents)    │
│        │                                    │
│        ├── claude ── your Claude account ───┼──▶ Anthropic
│        ├── codex  ── your ChatGPT account ──┼──▶ OpenAI
│        ├── grok   ── your Grok account ─────┼──▶ xAI
│        └── agy    ── your Google account ───┼──▶ Google
│                                             │
│ .whyline/    decisions (committed), relay state, repo agents
│ ~/.whyline/  ideas, run history, settings (private)
└─────────────────────────────────────────────┘
```

Whyline starts each agent's own command-line tool, signed in the way you set
it up. It never asks for, stores or forwards your credentials, and there is
no Whyline server for model traffic to pass through.

## Quick start

You need **Python 3.11+**, **Git**, and at least one of these CLIs installed
and signed in: [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
[Codex](https://github.com/openai/codex), Grok, or Antigravity (`agy`).

```bash
uv tool install whyline@latest     # includes the console and Relay
cd your-project
whyline init                       # creates .whyline/ and offers project instructions and hooks
whyline                            # opens the console
```

Then:

1. Press **Settings** and tick the subscriptions Whyline may use.
2. In **Chat**, talk to any agent. Switch agent and model from the bar at the
   top. You can attach images and PDFs.
3. Type `/brainstorm` and ask the panel something.
4. Open **Relay → Set up**, choose a plan and the role for each agent, press
   **Check**, then **Start**.
5. Open **Agents → New agent** to schedule your first read-only job.

Whyline checks PyPI once a day and offers **Update** inside the console.

## The console

| Mode | What it's for |
|---|---|
| **Chat** | Talk to any enabled agent, with model, backup chain, timeout, repository and attachments. `/brainstorm` asks several models at once. |
| **Relay** | Plan, Set up, Check, Run, Auto, Resolve, Resume, Stop, Files, and Awake on a Mac. |
| **Agents** | Saved Agents with schedules, history and delivery, plus the **Ideas** backlog and **Inbox** settings for Telegram and email. |

Everything you set up or run is available in the console without a terminal.
The CLI (`whyline --help`) exposes the same functions for scripts.

## Saved Agents in a file

Create Agents in the console, or commit a definition with the repository:

```toml
# .whyline/agents/dependency-watch.toml
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

```bash
whyline agents accept dependency-watch    # approve this exact definition on this computer
whyline agents run dependency-watch
whyline agents history dependency-watch
```

See [verified read-only modes](docs/agents-capabilities.md) and the
[Mail trigger recipe](docs/agents-mail-recipe.md).

## Decision memory for agents

| Command | What it does |
|---|---|
| `whyline sync` | Gives the next agent a short summary: the active handoff, Git state and relevant decisions |
| `whyline note "…" --because "…" --rejected "…"` | Records a decision and the options it beat |
| `whyline explain path:line` | Explains why a line exists |
| `whyline handoff TASK --from codex --to claude …` | Hands work over with changed files, tests and open risks |
| `whyline brief --file src/a.py` | Gives the history behind a file to the next agent |

Decisions live in `.whyline/decisions.md` and are committed with your code.
See [how recording works](docs/recording.md).

## Supported agents and platforms

| Agent | Chat, brainstorm and Relay | Unattended saved Agents | Attachments |
|---|:---:|:---:|---|
| Claude Code | ✅ | ✅ read-only plan mode | images, PDF, RTF |
| Codex | ✅ | ✅ read-only sandbox | images, PDF, RTF |
| Grok | ✅ | ✅ edits and writes denied | images, PDF |
| Antigravity | ✅ after you trust the repository | — no verified read-only mode | images, PDF, RTF |

| Platform | Support |
|---|---|
| **macOS** | Everything: console, Relay, saved Agents, schedules, folder and Mail triggers, the background Inbox, Awake, and Word and PDF documents. |
| **Linux** | Console, Chat, brainstorm, Relay and on-demand Agents. No macOS services. |
| **Windows** | Experimental. |

## Privacy and safety

- **Your plans, your limits.** Whyline runs the official CLIs with your own
  login. Usage counts against your plan's limits and follows each provider's
  terms.
- **Prompts still go to the providers you choose.** Whyline adds no server,
  telemetry or account in between.
- **Unattended means read-only.** Saved Agents and inbox turns use tested
  read-only modes. Only Relay writes code, only in the repository you choose,
  and it stops for you before anything risky or any release.
- **Messages are data, not commands.** Telegram and email are restricted to
  chats and senders you allow. Anything with consequences needs a confirmed
  tap or a reply code. Telegram bot chats are not end-to-end encrypted.
- **Local state.** Ideas, run history and settings stay in `~/.whyline/`.
  Only `.whyline/decisions.md` and any repository Agent definitions are meant
  to be committed.

## FAQ

**Do I need API keys?** No. Whyline uses the CLIs' own sign-in. A CLI that
you've set up with its own API key also works, and Whyline never sees the key.

**Does it cost anything?** No. Whyline is free and Apache-2.0. You pay only
for the AI plans you already have.

**Is one subscription enough?** Yes. Chat, Relay and saved Agents all work
with one. Brainstorms and cross-model review get better with each plan you
add.

**Can it run while I'm away?** Yes, on a Mac that is on, logged in and awake.
A scheduled run that falls while the Mac sleeps is recorded as missed, and
the next one runs on time. Telegram keeps undelivered messages for about a
day, so the Inbox catches up when the Mac wakes.

**Does it change my code without asking?** Only Relay writes, only after you
start it, and it commits only work that passed review. Releases stay with you.

## Learn more

- `whyline --help`, `whyline relay --help`, `whyline agents --help`,
  `whyline idea --help`
- [Idea Inbox setup](docs/idea-inbox.md) ·
  [Attachments](docs/attachments-capabilities.md) ·
  [Recording](docs/recording.md) ·
  [Measurements](docs/measurement.md)
- [Release notes](https://github.com/anishmoncivarghese/whyline/releases) ·
  [Issues](https://github.com/anishmoncivarghese/whyline/issues)

## License

Apache-2.0.
