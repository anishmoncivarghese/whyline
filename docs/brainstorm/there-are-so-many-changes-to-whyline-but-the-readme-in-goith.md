# Brainstorm: There are so many changes to Whyline but the readme in goithub is old I am thunking about updating the readme , go through teh repo and produce a good readme

## Codex

# Independent research: updating the Whyline README

## Bottom line

The README should be rewritten around the product Whyline is now, rather than extended with another paragraph under “Also in the box.” The current README still presents decision provenance and manual handoffs as the product, with relay, console, saved agents, and automation as secondary extras. At v0.3.49, Whyline is better described as a local, console-first workspace for coordinating existing agent CLIs across four connected workflows:

1. Record why code changed and hand work between agents.
2. Chat, brainstorm, draft a spec and plan, and run implementation through review.
3. Save read-only agents that run on demand, on a schedule, or from an event.
4. Capture an idea by console, Telegram, or email and carry it through scoring, research, planning, and a confirmed relay run.

Keep the existing tagline, “Records why your code exists, and tells the next agent,” because it is sharp and still true. Follow it immediately with a broader sentence such as:

> Whyline is a local control console for Claude Code, Codex, Grok, and Antigravity. It preserves decisions, coordinates reviewed work across agents, runs accepted read-only agents, and can take an idea from your phone to a plan and implementation in your repository.

“Local” must be qualified: Whyline has no hosted account or telemetry service, but the agent CLIs send work to their providers, Telegram uses the Bot API, and Mail uses the user’s configured mail account. The accurate promise is “locally controlled,” not “nothing leaves this machine.”

## Why the current README now feels old

The latest README change is commit `b21ac7f` from 2026-10-10. It is contained in v0.3.38 and later tags, while the repository is now v0.3.49. The missing work is not one small feature; it spans the product’s main workflows.

| Current README | Current repository |
|---|---|
| Says the console has Command, Chat, and Relay | Command mode was removed. The primary modes are Chat, Relay, and Agents; Ideas and Inbox are screens in Agents mode. |
| Calls both `whyline` and `whyline console` the full-screen app | Bare `whyline` opens the Textual UI when available. `whyline console` is the keyboard-only console; `whyline console --ui` explicitly opens the full-screen UI. |
| Describes relay mainly as `init`, `doctor`, `start`, and `status` | Relay now has a guided Run flow, brainstorm/spec/plan creation, optional test planning, role assignment, preflight, Auto execution, manual verification and release gates, Resume, and Resolve. |
| Gives saved agents one short paragraph | Agents now have repo or personal definitions, local acceptance, read-only enforcement, backups, schedules, folder/event triggers, run history, failure handling, and email/Telegram/command delivery. |
| Does not mention Idea Inbox | Ideas can be captured locally, scored, refined, dropped/reopened, exported to Excel, brainstormed into Word/PDF, and received and controlled through Telegram or authenticated email. |
| Does not mention modern console affordances | The console has agent/model/repository/backup/timeout controls, attachments, live file following, one-step repository setup, update detection, Stop, Awake, and guided recovery. |
| Presents `whyline-relay` as an optional box beside Whyline | Relay is still opt-in at the repository/workflow level, but `whyline-relay` and both console front ends are required package dependencies. “Optional workflow, included installation” is clearer. |
| Says Codex implements and stops because its sandbox cannot write `.git` | That is true for a direct Codex session, but the relay can commit approved work through Whyline’s host-side committer. The distinction should be explained where roles and trust boundaries are documented. |
| Leads with the measured 3-of-7 read rate | This is valuable evidence, but it is too specific and stale-looking for the main product path. Keep a short honest caveat and link to `docs/measurement.md`. |

The README should not enumerate every release. It should explain the stable mental model produced by those releases.

## The product story the README should tell

### 1. Whyline remembers the reason

This remains the foundation and should retain the real `whyline explain` example. Decisions are committed as readable Markdown, while the active handoff, ownership claims, and activity ledger stay local. `sync`, `brief`, `explain`, `note`, `handoff`, and `claim` are the compact CLI vocabulary for this layer.

Explain why this matters before showing syntax: a new agent session does not inherit another agent’s hidden conversation. Whyline gives it an explicit, bounded handoff and the decisions relevant to the files it is about to touch.

### 2. The console is the main door

The project instruction is “console first,” and the README should follow it. After installation and `whyline init`, the primary next command should be:

```bash
whyline
```

Then briefly orient the user:

- Chat: talk to the selected CLI, attach files or screenshots, choose a model, backup chain, timeout, and repository.
- Relay: brainstorm, create or select a plan, assign roles, check readiness, run, resume, and resolve pauses.
- Agents: create reusable read-only agents, inspect runs and schedules, and open Inbox or Ideas.
- Any normal Whyline command remains reachable as a slash command, such as `/status` or `/relay doctor`.

This is a better first-run story than leading with a long shell-only handoff example. Keep that example later for automation and expert use.

### 3. Relay is a reviewed workflow, not merely a loop

Describe the current guided flow in one compact sequence:

```text
idea or request
  -> multi-agent brainstorm and synthesis
  -> reviewed spec
  -> implementation plan and optional test plan
  -> preflight and role assignment
  -> implement -> test -> review -> verify
  -> Whyline commits approved work
  -> human release tasks
```

The important selling points are the controls around the loop:

- Each role can use a different agent and model.
- A shared ordered backup chain handles missing CLIs, login failures, quota, and supported failover cases.
- Check validates the exact form and repository state before Run is enabled.
- Auto can carry the work from brainstorm to relay, but open questions, unsafe recovery, manual checks, and release tasks still pause for the user.
- Resolve presents evidence and constrained recovery choices instead of silently rewriting or discarding work.
- Stop interrupts the active attempt; Resume continues from saved state.
- The Files pane shows the files being changed without turning the console into a full editor.

This is much more distinctive than “run a Markdown plan,” and it should get a main README section.

### 4. Saved Agents are a separate concept

Avoid blurring Relay roles with saved Agents. Relay roles work on a repository plan. A saved agent is a reusable instruction set that runs read-only, either personally or from a definition committed in a repository.

The README should say:

- A definition names its instructions, primary CLI, backups, timeout, and optional schedule or trigger.
- A repo definition changed by a pull does not run unattended until it is accepted on that Mac.
- Codex, Claude, and Grok have verified read-only launch modes. Antigravity is available for interactive and relay work but is excluded from saved unattended agents because its CLI has no verified read-only mode.
- Runs keep an answer and log. Results can be sent by email, Telegram, or an advanced after-run command; delivery failure does not change the run result.
- Scheduling, folder watches, Mail rules, and the background heartbeat are currently macOS features. “Run now” remains useful without scheduling.

A tiny example agent is worth more than a command inventory. For example, a “dependency-watch” agent that checks release notes weekly and delivers a Word report demonstrates instructions, schedule, read-only operation, backup, and delivery in one story. Create it through the console first; show CLI equivalents afterward.

### 5. Idea Inbox deserves a first-class section

Idea Inbox is the largest omission. Its story is unusually concrete:

> Send an idea from your phone, score or brainstorm it, receive the documents, turn the approved result into a spec and plan for an allowed repository, and start the relay only after a final confirmation.

The section should cover three entry points without drowning in commands:

- Console: Agents -> Ideas and Agents -> Inbox.
- Telegram: one BotFather bot, private allowlisted chats, cards and confirmation taps, Word/PDF results, status/resolve/stop controls.
- Email: Mail.app intake from allowlisted senders, DKIM or SPF pass required, revision-bound confirmation codes, and document attachments in replies.

Also mention the local data model: ideas live under `~/.whyline/ideas`, the SQLite database is authoritative, and `ideas.xlsx` is rebuilt as an export. The Telegram workflow runs in the inbox’s own workspace rather than in arbitrary repositories, and repository planning is limited to configured repositories.

Do not present future MCP/API tools as implemented. The current repository has no per-agent tool approval or `tool-exec` boundary. That belongs in a future roadmap after it exists.

## Recommended README structure

1. **Hero**
   - Name, existing tagline, expanded one-sentence description.
   - Badges only if they are accurate; do not use a green aggregate CI badge to imply Windows is supported while Windows is non-gating.
   - One current screenshot of the Textual console showing the three modes and context bar. There are no image assets in the repository now, so this must be captured before the rewrite lands. Redact home paths, repository names, emails, and Telegram details.

2. **What you can do**
   - Four short cards or bullets: Explain, Build with Relay, Run saved Agents, Capture Ideas.
   - Link each to its fuller section.

3. **Install and five-minute start**
   - Requirements: Python 3.11+, Git, `uv`, and at least one supported CLI already installed and signed in.
   - Install: `uv tool install whyline@latest`.
   - Existing repository: `cd ...`, `whyline init`, `whyline`.
   - State that first run detects available agents; `whyline account detect` refreshes detection.
   - Existing users: `uv tool upgrade whyline` or the console’s Update action.

4. **The console**
   - Chat, Relay, Agents; Inbox and Ideas under Agents.
   - Context bar, attachments, Files, Stop, timeouts, backup chain, slash commands.

5. **Four workflows**
   - Preserve decisions and hand off work.
   - Take a change from brainstorm to reviewed release.
   - Create and run a read-only saved agent.
   - Capture and develop an idea remotely.

6. **How data and trust work**
   - A concise storage table.
   - Provider/network boundaries.
   - Unattended-agent acceptance and read-only matrix.
   - Remote input allowlists and confirmation gates.

7. **Compatibility and limits**
   - Feature-by-platform and feature-by-agent tables.
   - Honest experimental Windows status.
   - macOS-only scheduler, Mail integration, and native PDF behavior.

8. **CLI and deeper documentation**
   - A small command map, not every flag.
   - Links to recording, measurement, performance, Idea Inbox, Mail recipe, attachment capability, agent capability, releases, issues, and licence.

This order lets a new visitor understand the product before reading implementation details, while experienced users still get exact commands and design evidence.

## Proposed quick start

The README’s shortest successful path should be console-first:

```bash
uv tool install whyline@latest
cd your-project
whyline init
whyline
```

Then say, in prose:

1. Choose Chat, Relay, or Agents.
2. Pick an installed agent and model from the top bar.
3. In Relay, choose Run to brainstorm or select a plan; Check must pass before work starts.
4. In Agents, choose New for a reusable read-only agent, or Inbox to connect Telegram/email intake.

Follow this with the existing shell handoff example for users who want explicit multi-terminal control. The README should show both interfaces calling the same underlying functions, not imply that the console and CLI are different products.

## Trust, privacy, and security wording

This needs a dedicated section because the product now accepts remote input and launches unattended processes.

Accurate claims:

- Whyline has no hosted account, paid tier, or telemetry service of its own.
- Project decisions are readable Markdown. Active state, run logs, accepted definitions, ideas, and delivery settings are stored locally.
- Whyline launches CLIs the user already installed and authenticated. Their provider terms and data handling still apply.
- Saved unattended agents use verified read-only modes and locally accepted definitions; Antigravity is excluded from this feature today.
- Telegram inbox reads private chats that the user explicitly allows. Telegram bot chats are not end-to-end encrypted.
- On macOS the Telegram bot token is stored in Keychain; elsewhere it is stored in a mode-0600 local file.
- Email idea intake requires an allowlisted sender plus a DKIM or SPF pass, and consequential steps use revision-bound confirmation codes.
- Relay preflight fingerprints the selected configuration and repository state; dangerous recovery, manual verification, and release actions wait for the user.

Claims to avoid:

- “Everything stays on your machine.” Prompts and selected files can go to model providers; Telegram and email necessarily use their networks.
- “No secrets are exposed.” The current Telegram Keychain write invokes the macOS `security` command with the token in its argument vector. Until that implementation is changed, the README should claim storage location and hidden input, not perfect process-level secrecy.
- “Unattended agents are sandboxed from all user data.” They are launched in read-only modes, but the exact visibility and inherited configuration come from the underlying CLI. Current agent and relay launches can inherit normal provider configuration, including configured tools. State the verified guarantee narrowly: Whyline blocks repository writes through the tested launch mode.
- “All four agents work everywhere.” Capability varies by workflow, and platform support varies too.

## Compatibility tables the README needs

An agent table should make the asymmetry obvious:

| Agent | Chat / brainstorm / relay | Saved unattended Agent |
|---|---:|---:|
| Claude Code | Yes | Yes, read-only plan mode |
| Codex | Yes | Yes, read-only sandbox |
| Grok | Yes | Yes, edit/write denied |
| Antigravity | Yes, after repository trust approval | No verified read-only mode |

A platform table should distinguish the portable core from Mac automation. Before publishing exact cells, rerun the supported-platform tests and validate them on clean installs. The repository currently supports this broad statement:

- macOS is the full experience.
- Linux supports the core CLI, console, interactive work, relay, and on-demand features, but not LaunchAgent/Mail automation or native macOS PDF conversion.
- Windows is experimental: it is present in CI with `continue-on-error`, and the current README correctly says it is not supported/tested as a release guarantee.

Do not let “Telegram works on every system” imply that the always-on incoming Idea service does: the documented Idea service uses the agents scheduler and currently requires macOS.

## What to keep from the existing README

- The concise title and tagline.
- The real `whyline explain` output. It proves the product is dogfooded and makes an abstract feature tangible.
- The “What gets written down” table, expanded to include personal agents, runs, ideas, and per-Mac settings.
- The manual handoff example and compact core-command list.
- The statements that claims are advisory, hidden conversations are not transferred, and an empty record produces an empty answer.
- Links to measurement and performance rather than marketing over those limits.
- Apache-2.0 and the no-Whyline-account/no-telemetry positioning, with the network qualification above.

## What to cut or move

- Move the 3-of-7 prompt-compliance statistic out of the main flow and keep it in the linked measurement document.
- Replace the long explanation of Codex hook approval in Install with a shorter setup note plus `whyline status`/`whyline doctor` troubleshooting.
- Do not list every `idea`, `agents`, or `relay` subcommand in the README. Link `--help` and focused docs.
- Do not narrate release history. Write the stable workflow and leave versions in `docs/releases/`.
- Do not call features “optional” when they install by default; say whether the workflow is disabled until configured.
- Avoid an enormous feature checklist at the top. Four workflows are enough.

## Documentation gaps to fix alongside the README

The README rewrite will expose several navigation gaps:

1. There is no single user guide for the full guided Relay/Auto/Resolve flow. The behavior is spread across release notes and design specs. Add a stable `docs/relay.md` before linking to it.
2. There is no stable saved-Agents overview covering creation, acceptance, scheduling, triggers, and delivery together. `docs/agents-mail-recipe.md` and capability spikes are supporting documents, not an entry guide. Add `docs/agents.md`.
3. `docs/idea-inbox.md` covers Telegram well but should gain an email section or link to a new email-intake guide.
4. The console has no screenshot or short visual tour. Add one maintained screenshot, not a gallery likely to become stale.
5. Security and data boundaries are currently distributed across specs and source comments. Add a short stable `docs/security.md` or keep a carefully maintained README section.
6. Release notes recommend a mixture of `uv tool upgrade`, `uv tool install ...@latest`, and pinned installs. Pick one install/update convention in the README and use it consistently going forward.

These docs should be linked from the README, not duplicated into it.

## Suggested implementation order

1. Confirm the positioning sentence and four-workflow information architecture.
2. Add or update the stable Relay, Agents, Idea/email, and security docs needed as link targets.
3. Capture a redacted v0.3.49 console screenshot at a narrow but readable size.
4. Rewrite the README in one pass, preserving the real Explain example and the useful storage/handoff material.
5. Verify every command from a clean tool installation and a fresh temporary Git repository.
6. Test the README on GitHub rendering: relative links, table width, screenshot size, and mobile readability.
7. Have a reviewer compare every support/security statement against source and tests, not only release notes.
8. Add a release checklist item: every feature that adds a console-visible top-level workflow must update the README or explicitly record why it does not.

## Definition of done

The README update is complete when a first-time visitor can answer, without opening release notes:

- What is Whyline, and why would I use it instead of launching one agent CLI directly?
- Which agent CLIs and operating systems work for the workflow I want?
- How do I install it and reach the full console?
- What is the difference between Chat, Relay, a saved Agent, and Idea Inbox?
- What will be committed to my repository, what stays local, and what is sent to external providers?
- Where are human confirmation and release gates?
- How do I troubleshoot or learn the detailed commands?

The rewrite should remain compact enough to scan. A target of roughly 200–300 lines plus one screenshot is reasonable; deeper operational detail belongs in focused docs.
