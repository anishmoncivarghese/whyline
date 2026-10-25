> Design note for `plans/personal-assistant.plan.md`. Where they differ, the plan wins: CLI commands are `whyline idea …`, files live under `~/.whyline/ideas/`, and the PA-*/MB-* task lists below became ASST-1..23.

# Personal assistant for whyline: recommendation (2026-10-26)

A research-only side session wrote this. It changed no code, plans or `.whyline/` files. It ran `whyline sync`: the active handoff is SUBS-FIX-1 (grok → codex, passed) on `relay/console-provider-settings.plan`. It read `job-search-agent-recommendation.md` too.

## TL;DR

- **"Clawbot" is Clawdbot.** Peter Steinberger's open-source self-hosted assistant was renamed Moltbot on 27 Jan 2026 and OpenClaw on 30 Jan 2026. It does a great deal, and it is a security cautionary tale.
- **whyline is closer than it looks.** The Idea Inbox already reads messages with a deterministic keyword router (`ideas/intent.py`) and passes the rest to an AI assistant (`ideas/assistant.py`). The assistant only *proposes* a card from an allowlist of actions, and the user taps Confirm, Edit or Cancel. Email intake (`ideas/email_in.py`) confirms with `yes <code>` replies. That is the hybrid design I'd recommend. Today it covers only the idea pipeline: capture → score → brainstorm → plan → relay.
- **Recommendation: generalise that hybrid into an "Assistant" with a fixed action registry.** The new actions are: run a saved agent, ask a question about a repo, reminders, summarise forwarded mail, status, and memory notes. Keywords run at once when they're read-only. Anything that writes or costs a long run needs a confirmation that is bound to a nonce. Do not copy OpenClaw's model of arbitrary shell, browser and skills.
- **Fix before widening email:** the email check accepts *any* `Authentication-Results: dkim=pass` header, and the `yes <code>` value is an unkeyed hash that anyone can compute (details in section 2.4).

---

## 1. Clawdbot → Moltbot → OpenClaw

**Identity.** It started as Clawdbot (Nov 2025). Anthropic raised a trademark concern over "Clawd", so it became Moltbot on 27 Jan 2026 and OpenClaw on 30 Jan 2026. During the rename, scammers grabbed the old X handle and GitHub organisation within seconds. It has well over 100k GitHub stars.

**What it does.** It's a self-hosted assistant that you message from chat apps. It acts for you: email, calendar, web browsing, shell, files, and device control. The pitch is that "state, memory and credentials stay on your hardware".

**How it runs.** One **Gateway** daemon, written in Node 24+/26 and installed with `openclaw onboard --install-daemon`, is the control plane for sessions, routing, tools and channels. It has a CLI, a web Control UI on 127.0.0.1:18789, a macOS app, and iOS and Android "nodes" (camera, screen, voice, device actions). Model providers and agent harnesses are plugins. Config lives in `~/.openclaw/openclaw.json`.

**Channels.** WhatsApp, Telegram, Slack, Discord, Signal, iMessage, Teams, Google Chat, Matrix, WebChat and 20+ more, all served by one Gateway. DMs share a main session by default, and each group gets its own session.

**Tools.**
- `exec`, `process`, `terminal`, `code_execution`
- `read`, `write`, `edit`, `apply_patch`
- `web_search`, `web_fetch`, `browser`
- `message`, which can send across conversations and providers by default
- sub-agents and sessions
- `automations`/`cron`, `nodes`, `plugins`, media generation, `ask_user`, `secrets`

**Skills and plugins.** Skills are repeatable procedures loaded on demand. Plugins (channel, provider and tool) are shared through the **ClawHub** marketplace.

**Memory.** Plain Markdown in the workspace (`~/.openclaw/workspace`):
- `MEMORY.md`: curated facts, loaded every session
- `memory/YYYY-MM-DD.md`: daily notes, searchable
- `USER.md`: preferences
- optional "dreaming", which promotes notes into MEMORY.md

The tools are `memory_search` (hybrid vector + keyword search over SQLite or Postgres, with OpenAI embeddings by default) and `memory_get`. The docs say: "no hidden state; the model only remembers what is saved to disk."

**Scheduled jobs.** Automations (alias `cron`) cover schedules, condition watchers and event triggers such as webhooks and Gmail Pub/Sub. Each job runs in the main session or an isolated one, and its output goes to a channel, a webhook or nowhere. Jobs are stored persistently with run history. The older "heartbeat" is deprecated in favour of jobs.

**Security model.**
- The Gateway binds to loopback.
- Unknown DM senders get a **pairing code** (`openclaw pairing approve <channel> <code>`). `dmPolicy` is one of pairing, allowlist, open or disabled.
- Groups are allowlisted and gated on a mention.
- Tool profiles range from full host access to read-only to no shell.
- Sandboxing is **opt-in**: by default, tools run on the host for the main session.
- Host commands go through exec approvals, with an "elevated" mode on top.
- `openclaw security audit` checks for drift from the defaults.
- The docs say plainly that it is "one trust boundary per gateway" and not built for mutually hostile users.

**Known risks** (vendor figures vary, so treat them as approximate):
- **Prompt injection is unsolved.** OpenClaw's own guidance is to use a strong model and wrap external content. Inbound messages, email and web pages all reach a model that holds shell and messaging tools.
- **Malicious skills.** Koi Security found 341 malicious skills out of 2,857 on ClawHub, and a later count passed 800. Snyk reported 283 skills leaking API keys. Skills run with the agent's full access.
- **Exposed Gateways.** Container images bind publicly by default. Scans counted 30k to 135k+ exposed instances, and SecurityScorecard flagged about a third of them as vulnerable, many to remote code execution.
- **Broad blast radius.** One injected email can make the agent send messages, run shell commands or exfiltrate files.

**Lesson for whyline.** Copy the ergonomics: chat-first, memory you can read as Markdown, scheduled jobs, run history. Do not copy the capability model. whyline's strengths are a small fixed action set, read-only unattended runs, confirmation cards, and no third-party skill marketplace. Keep them.

---

## 2. What whyline has today

### 2.1 Idea Inbox (`src/whyline/ideas/`)

| Piece | Today |
|---|---|
| Telegram intake | `telegram_in.py` polls getUpdates from **allowed private chats only** (kv `telegram_allow`, cursor kept in kv), with no webhook. One bot token per Mac, kept in the Keychain. |
| Routing | `intent.py`: deterministic, with no model. Commands (`new list status excel brainstorm plan stop drop help`) are fuzzy-matched, plus `key: value` settings, agent aliases, and detection of "plainly a new idea". Any other free text goes to the assistant. |
| AI router | `assistant.py`: one **read-only** turn, plus a backup, that returns an `inbox-proposal` block. It is validated against `ACTIONS` (brainstorm, score, stop, resolve, status, drop, start, plan, excel, refine, resume…). Unknown agents, repos, actions or ideas are rejected by name. Confirm, Edit and Cancel are buttons, and "nothing in this module … changes an idea". |
| Cards and outbox | `bot.py` (2.7k lines) builds cards and buttons and holds the only sender. The outbox retries at 1, 5, 15 and 60 min, up to 8 attempts. |
| Jobs | `worker.py run_once` is one tick: poll, handle, reclaim expired leases, start at most **one** queued job (kinds `score`, `brainstorm`, `plan`, `start`), flush the outbox. A job runs detached as `whyline idea work <id>`. Lease = timeout + 30 min. A dead pid means "the Mac slept". |
| Ledger | `store.py` is sqlite schema 5. Ideas move through a state machine (`captured → scoring → scored → brainstorming → … → ready → running → done`) with an explicit `ALLOWED` table, events, a kv store, and an xlsx view (`xlsx.py`). |
| Work | `analyse.py` (score), `brainstorm.py` (multi-agent), `planning.py` (spec and plan with questions over Telegram), `run.py` (**starts the relay on a confirmed tap**, with caffeinate), and `watch.py` (status, pause alerts, Resolve buttons, Stop). All of them run in the inbox workspace, except the relay, which runs in the chosen repo. |
| Email | `email_in.py` (IDEA-21) has an allowlist of senders (kv `email_allow`) and a DKIM/SPF check. A subject of "idea" or an empty subject captures an idea. Body `key: value` lines become settings. `yes <code>` confirms. Documents go back as Word and PDF. Mail arrives through a Mail.app rule script → `whyline agents trigger idea <file>` (service.py) → `email_in.handle`. |
| Console | `inbox_screen.py` covers the bot token, allowed chats, allowed email senders, and service on/off. `ideas_screen.py` lists ideas. |

### 2.2 Saved Agents (`src/whyline/agents/`)

- **Definitions** are TOML files, per repo (`.whyline/agents/`) or personal (`~/.whyline/agents/`). Triggers are `manual | daily | weekdays | every N h | folder`. A launchd tick drives them (`tick.py`, `launchd.py`).
- **Read-only argv** comes from `capabilities.py`:
  - codex: `-s read-only`
  - claude: `--permission-mode plan` (needs `USER` set)
  - grok: the write `--allow` flags are dropped, plus `dontAsk --deny Edit --deny Write`
  - Antigravity is **excluded**, because it has no read-only mode. The spike evidence is in `docs/agents-capabilities.md`.
- **Runner** (`runner.py`) tries the main runner and then the backup. It skips any CLI where `_cli_permitted` is false or that isn't `can_run_unattended`. `build_prompt` labels sources and event files as data.
- **Delivery** (`deliver.py`): email via `mail_send`, Telegram as a message or document, or a **shell command** (`/bin/sh -c`). The result goes out as final.md or a .docx.
- **Mail trigger.** `mail.py` installs the Mail.app AppleScript rule (`whyline agents mail-script <name>`, and `whyline idea email mail-script` for the inbox). **Neither has a console counterpart**, which breaks console first.
- **No web access.** Read-only runs probably can't fetch the web (see the job-search note), so whyline fetches data itself and the agents only read files.

### 2.3 Enabled-provider rules

`account.enabled_agents()` is set in Settings and enforced in:
- the runner (`_cli_permitted`)
- the worker
- Relay Set up (SUBS-4)
- saved Agents and Idea Inbox choices (SUBS-5)

When no account file exists, everything is allowed, so older installs keep working. Unattended runs also need `can_run_unattended`, which excludes Antigravity.

### 2.4 Relay

Relay runs `plans/` tasks with **write access**: Grok implements and Codex reviews, with round caps. The inbox already starts it from Telegram (`run.py`), but only after a confirmed tap on a planned idea. Pauses alert with Resolve buttons (`watch.py`). It is the only writing path an assistant should reach, and it must always need a confirmation.

### Security findings in today's email path (worth fixing first)

1. **`is_authenticated` trusts any `Authentication-Results` header** that contains `dkim=pass` or `spf=pass`.
   - A sender can add such a header to their own message, and some receivers don't strip it.
   - A real `dkim=pass` for the *attacker's own domain* also passes, because nothing checks that `header.d` aligns with the From domain.
   - SPF checks the envelope sender, not From.
   - The From allowlist is the only real gate, and From is easy to spoof.
   - **Fix:** read only the topmost `Authentication-Results` header written by the user's own provider (a configured authserv-id such as `mx.google.com` or `icloud.com`), and require `dkim=pass` with `header.d` equal to the From domain, or DMARC pass.
2. **`code_for` is `sha256("whyline-email:{id}:{rev}")[:6]`, with no secret.** Anyone who knows the idea id and revision can compute it. Spoofed mail still has to pass check 1 and match the originating sender, so this is defence in depth, but it is cheap to fix: use an HMAC with a per-install secret kept in the Keychain, or a random nonce stored in kv, plus an expiry.

---

## 3. Recommended design: "Assistant" on top of the inbox

### 3.1 Keywords vs an AI router: use a hybrid, as the inbox already does

| | Keyword commands | AI router |
|---|---|---|
| Predictable, zero tokens, works when models are rate-limited | yes | no |
| Natural ("can you check if the nightly agent failed?") | no | yes |
| Prompt-injection surface | none (a parser) | the model reads attacker text |
| Cost per message | 0 | one read-only turn (about 5–30 s on a subscription) |

**Hybrid rule:**
1. **The first word is a verb from a fixed list** (`idea`, `brainstorm`, `do`, `run`, `ask`, `remind`, `status`, `summarise`, `remember`, `forget`, `cancel`, `help`; extend `intent.COMMANDS`, with fuzzy matching kept). It is parsed deterministically. Read-only verbs run at once. Writing or long verbs show a confirm card.
2. **Anything else** goes to the existing assistant turn, extended with the new actions. It is still *proposal only*: the model outputs `{action, args}` and whyline validates it against the registry. The user always sees a card and taps Confirm before anything runs, *even read-only actions*, because an AI-proposed action cost tokens to guess and might be wrong. A user setting may later auto-run proposals of read-only actions.
3. **Forwarded email or message bodies are never routed by AI.** The *sender's own words* (the email subject, or the first lines above the forwarded block) choose the verb. The forwarded content is only the action's *payload*, given to the agent as a data file.

This keeps the zero-token, injection-free path for power users, while ordinary language still works.

### 3.2 Action registry

Add an `assistant/actions.py` registry (or extend `ideas/assistant.ACTIONS`). Each entry holds: `name`, `verb`, `args schema`, `writes: bool`, `approval: none|tap|tap+code`, `runner: unattended-readonly | relay`, `cost: instant|turn|long`, and `audit`. Every action, whether it runs or is refused, writes an `events` row (`actor=chat:<id>|email:<addr>`, `action`, `args`, `proposal_by=keyword|assistant`, `approved_at`, `result`), plus the existing agent run record or relay log where one applies.

| Action | Verb | Reads or writes | Approval in chat | Runs unattended under today's rules? | Audit |
|---|---|---|---|---|---|
| **Capture idea** | `idea …` (or plain text) | writes the ledger only | none | yes, no model | idea + event (exists) |
| **Brainstorm** | `brainstorm …` | read-only agents in the inbox workspace | settings card → Start (exists) | yes | brainstorm job + event (exists) |
| **Status** | `status [agent\|idea\|relay]` | read | none | yes, no model | event |
| **Run saved agent** | `run <agent>` | read-only agent run; its delivery may send mail or Telegram, or run a command | **tap** when the agent has a `command` delivery or a run longer than 15 min, otherwise none | yes: it's the existing `runner` with the same gating. **Never allow arguments or ad-hoc prompts.** Only a named, already-saved definition runs. | agent run record + event |
| **Ask about a repo** | `ask [repo] <question>` | read-only turn in a *registered* repo (claude plan / codex read-only / grok deny) | none for keywords; a tap when the assistant proposes it | yes, within the repo allowlist that Set up already keeps. The answer comes back as text or a .docx. | event with the question and the answer's path |
| **Summarise mail** | forward with subject `summarise`, or `summarise` in Telegram with the text attached | read-only turn; the email is a data file | none | yes. The body goes through a guard that strips hidden HTML and flags instruction-like lines. **No tools, no repo.** It runs in the inbox workspace. | event + stored summary |
| **Remind** | `remind <when> <text>` | writes a reminders table; the tick sends to Telegram | none (it only messages you) | yes, no model. Parse `in 2h`, `tomorrow 9`, `fri 17:00` deterministically. | reminders row + event on send |
| **Remember / forget** | `remember <fact>`, `forget <n>` | writes memory.md | none (it's your own words) | yes, no model | event + the file diff in history |
| **Do / start a relay task** | `do <plan-task-id>` or `do <repo> <task>` | **writes code** (relay) | **tap + fresh nonce** on Telegram; `yes <HMAC code>` by email, expiring in 30 min. Show the repo, branch, plan, task and roles on the card. | **No.** It needs a confirmation each time. `do <free text>` becomes a captured idea → plan → relay through the existing pipeline. It never goes straight to writing. | relay log + whyline decisions + event |
| **Cancel / stop** | `cancel`, `stop <job>` | writes state | a tap for a running relay (exists) | yes | event |

**Out of scope on purpose:**
- arbitrary shell
- browser control
- sending mail *to other people*
- calendar edits
- installing skills or plugins
- any action whose target comes from message content (a URL, an address, a path)

Each would need its own reviewed action later.

### 3.3 What runs unattended vs what needs new approval

- **Already safe unattended:** capture, brainstorm, score, status, run saved agent (it's the existing runner), ask a repo read-only, summarise, remind, remember. All of them use claude, codex or grok in read-only mode, and enabled-provider gating applies.
- **Needs new approval work:**
  - `do` / relay start from a keyword, which today is reachable only from an idea's card
  - `run <agent>` when that agent's delivery is a shell command
  - a generic nonce/HMAC confirmation shared by Telegram and email, replacing the per-idea revision code
- **Never unattended:** writing code, sending to third parties, anything Antigravity runs.

### 3.4 Where memory lives

- `~/.whyline/assistant/memory.md` (0600): facts you tell it with `remember`. It is human-readable, editable in the console, and shown in full in the console.
- The `events` table in the inbox sqlite is the conversation and action history. `status history` shows the last N entries.
- Agent run records and relay logs stay where they are now.
- **What gets injected:** only memory.md, size-capped, labelled "user's notes, data". Recent chat history goes into the *assistant router* turn only. Agents get it only when an action passes it explicitly.
- **No embeddings and no vector database.** It's a single user with small data, and grep is enough.
- Personal data stays out of repo folders and git.

### 3.5 Prompt injection from forwarded email

1. **The gate comes before any model.** The sender must be allowlisted and authenticated with the fixed check from section 2.4. Anything else is logged and dropped, as it is today.
2. **Verb selection is deterministic.** It comes from the subject or the sender's own top lines, never from the forwarded body. The AI router never sees forwarded content.
3. **Content is data.** The body is written to a file, passed as an event file in a "data, not instructions" block (the `build_prompt` pattern), and run through a guard that strips hidden text, HTML comments and zero-width characters and flags imperative lines (as job-search JS-6 proposes).
4. **Read-only agents only.** The summarise and ask turns run in plan, read-only or deny mode. Even a fully hijacked model can only produce text.
5. **Output is checked, never executed.** A summary that "proposes" an action becomes a card the user must tap, validated against the registry. Its targets can be only registered agents, repos and plan tasks, never free URLs or addresses.
6. **Confirmations are bound and expire.** The nonce or HMAC covers the action, args, revision and sender. The code is consumed on use.

### 3.6 Console first: every setup step and check

New **Assistant** section under Agents → Inbox (or a sibling screen):
- **Channels:** the Telegram token and allowed chats (exists), allowed email senders (exists), plus **Install Mail rule**, which calls the same function as `whyline idea email mail-script` and `whyline agents mail-script`. Today those exist only in the CLI.
- **Email authentication:** pick your provider's authserv-id and run a **Test with a sample email**: pick a saved .eml and see pass or fail with the reason.
- **Actions:** one row per registry action, with an on/off switch and an approval level. A row that writes can't drop below "tap". This calls the same `set_action_policy()` as `whyline assistant actions set`.
- **Memory:** view and edit memory.md, plus "forget all".
- **Reminders:** list and cancel.
- **History:** the events log with a filter.
- **Doctor:** Check runs `whyline idea doctor` + `assistant doctor`. It covers the token, webhook conflicts, the scheduler, enabled providers that are cleared for unattended runs, Mail rule installed, last email seen, and that the Mac stays awake when set.

---

## 4. Limits

- **Mac asleep or off.** The tick needs a logged-in, awake Mac. Reminders fire late, and the existing "Mac slept" messaging should cover them too. Keep Awake (AWK-1) helps only while plugged in. A hosted queue stays in "Later" in the plan.
- **Telegram's 24-hour retention.** getUpdates keeps undelivered updates for about 24 h, so messages are lost if the Mac is off longer. Mail does not have that problem, since it waits in the mailbox for the Mail rule, though Mail.app must be running.
- **Provider terms.** Running the official CLIs on your own subscription for your own tasks is the intended use. Avoid making whyline a multi-user service on one subscription, and keep the bot to private chats. Usage limits apply, and the runner's backoff and backup already handle them.
- **Personal data.** Forwarded email, memory and repo questions all go to the chosen provider. Say so on setup. Keep files at 0600 under `~/.whyline/`, and never in repo folders. Telegram bot chats aren't end-to-end encrypted, so summaries pass through Telegram's servers.
- **Side effects.**
  - Only the relay writes code, and only after a bound confirmation.
  - Agent `command` deliveries are a shell path, so a remote `run` needs a tap.
  - No sending to third parties.
- **Single user.** As with OpenClaw's "one trust boundary", allowlisted chats and senders are treated as *you*. Don't allow a group or shared mailbox.
- **No web access** in read-only runs, so "look this up" needs deterministic fetchers (as in the job-search note) or a later spike (JS-0).

---

## 5. Relay-sized tasks (each with a CLI command, a console counterpart and one save function)

- **PA-1 Email auth hardening.** Check only the trusted authserv-id, require DKIM `header.d` aligned with From (or DMARC pass), and add tests with forged-header fixtures. Add a console "authserv-id" field on the Inbox screen. *Do first.*
- **PA-2 Keyed confirmation codes.** Replace `code_for` with an HMAC from a Keychain secret, or a random kv nonce with a 30-min expiry that's consumed on use, bound to the action and args. Add tests.
- **PA-3 Mail rule from the console.** Add an "Install Mail rule" button for the inbox and for each agent, calling the same function as the two `mail-script` CLI commands. This fixes an existing console-first gap.
- **PA-4 Action registry module.** Add `assistant/actions.py` with the table from section 3.2 and a `policy` saved in kv. Add `whyline assistant actions list/set`, and a console Actions list with switches. No new behaviour yet.
- **PA-5 Keyword verbs: status and help.** Extend `intent.py` with `status agent|relay|idea`. It is deterministic and needs no model.
- **PA-6 `run <agent>` from Telegram/email.** Run a named saved agent through `runner`. A command delivery or a run over 15 min needs a tap. Record the event.
- **PA-7 `ask <repo> <question>`.** One read-only turn in a registered repo, with the reply as text or a .docx. Add tests for an unregistered repo and for a provider that's turned off.
- **PA-8 Reminders.** A deterministic time parser, a reminders table, and a send on the tick. Add `whyline assistant remind list/cancel` and a console Reminders list.
- **PA-9 Memory.** `remember`/`forget`, memory.md at 0600, injected into the router turn only. Add a console Memory editor.
- **PA-10 Summarise forwarded mail.** A guard that strips hidden text and flags imperatives, plus a read-only summary turn. The verb comes from the subject only. Add injection fixtures.
- **PA-11 Assistant router actions.** Extend the `assistant.ACTIONS` validation with run, ask, remind, remember and summarise. A proposal always becomes a confirm card.
- **PA-12 `do <task>`.** A plan-task id goes to the existing `run.py` start, behind a PA-2 nonce card. Free text becomes an idea capture. Add tests that no relay starts without a confirmation.
- **PA-13 Assistant doctor + docs.** A console Check plus `whyline assistant doctor`, and a `docs/assistant.md` page covering limits and privacy.

**Order:** PA-1 → PA-2 → PA-3 (safety and the console gap) → PA-4 → PA-5 → PA-6 → PA-7 (a usable v1) → PA-8 → PA-9 → PA-10 → PA-11 → PA-12 → PA-13. Each task touches one or two modules plus tests, small enough to stay under the round cap.

## Sources

- AlternativeTo, [Clawdbot rebrands to Moltbot](https://alternativeto.net/news/2026/1/trending-open-source-ai-agent-clawdbot-rebrands-to-moltbot-after-pressure-from-anthropic/) and [rebrands a third time](https://alternativeto.net/news/2026/1/the-viral-ai-agent-clawdbot-rebrands-a-third-time-and-now-has-a-social-network-for-bots/)
- [abvx substack on the renames](https://abvx.substack.com/p/clawdbot-moltbot-openclaw-the-ai)
- [OpenClaw GitHub](https://github.com/openclaw/openclaw)
- OpenClaw docs: [overview](https://docs.openclaw.ai), [memory](https://docs.openclaw.ai/concepts/memory), [security](https://docs.openclaw.ai/gateway/security), [automations](https://docs.openclaw.ai/automation/cron-jobs), [tools](https://docs.openclaw.ai/tools)
- [TechRadar: OpenClaw security risks](https://www.techradar.com/pro/here-are-the-openclaw-security-risks-you-should-know-about)
- [Morph: is OpenClaw safe](https://www.morphllm.com/openclaw-security)
- [clawdocs security overview](https://clawdocs.org/security/overview)

---

## 6. Add-on: morning brief (calendar + email → plan for the day)

PA-1..13 don't include this. It fits the existing pattern: **whyline collects the data with deterministic local code, and a read-only saved agent only reads files.**

- **Calendar:** read Calendar.app locally (EventKit via a small Swift or PyObjC helper, or AppleScript). That covers iCloud, Google and Exchange calendars already added to macOS. No OAuth, and nothing leaves the Mac until the agent runs. Output is `today.md` with events, times, locations and free blocks.
- **Email:** read Mail.app locally through AppleScript: unread and flagged messages from the last 24 h in the chosen mailboxes. Write sender, subject, date and the first ~40 lines (stripped by the PA-10 guard) to `mail.md`. IMAP with an app password is a later option. Prefer Mail.app, because it needs no stored credentials.
- **Tasks (optional):** open reminders from Reminders.app, whyline reminders (PA-8), memory.md, and whyline status (paused relay, failed agents).
- **Agent:** a built-in `morning-brief` template (this needs the template loader from job-search JS-1). It's a personal agent with a weekdays 07:00 trigger. Sources are the files above, and the instructions are "plan my day: schedule, top 3 priorities, emails needing a reply (draft suggested replies as text only), conflicts, prep needed". Delivery is Telegram (and/or email).
- **Follow-ups from the brief:** buttons go to *existing* registry actions only: `remind`, `remember`, `run <agent>`. Suggested replies are text to copy. **They are never sent.** Calendar edits stay out of scope (writes).
- **Injection:** email bodies are data, the agent is read-only, and the output is text. Buttons are validated against the registry.
- **Limits:**
  - macOS privacy prompts (Calendar, Reminders, Automation for Mail) must be granted once, from the console while the user is present, because launchd can't show them.
  - Mail.app must be running.
  - At 07:00 the Mac may be asleep. The run happens at wake (missed-run handling) unless the user schedules a wake (Energy settings / `pmset repeat`, which needs admin and is the user's choice).
  - Every brief sends calendar and email excerpts to the chosen provider and through Telegram. Mailbox and calendar choices let the user exclude sensitive ones.

**Tasks:**
- **MB-1 Calendar export.** A `whyline brief calendar` that writes today.md. A console button grants access and previews the output.
- **MB-2 Mail export.** Unread and flagged messages from chosen mailboxes go to mail.md through the guard. In the console: pick mailboxes, grant Automation, preview.
- **MB-3 `before = "brief-collect"` on the trigger.** A built-in step that runs MB-1/MB-2 before the agent. It shares the mechanism with job-search JS-7.
- **MB-4 Morning-brief template.** Instructions and output format, with tests that build_prompt labels the sources as data.
- **MB-5 Brief buttons.** remind, remember and run, wired to PA-8, PA-9 and PA-6.
- **MB-6 Setup Check.** Covers permissions granted, Mail running, a sample brief, delivery, and an optional wake-time hint.

Depends on: JS-1/JS-2 (templates), PA-8, PA-9 and PA-10.
