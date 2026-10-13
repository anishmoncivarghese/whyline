## Independent research: Telegram/email idea-analyzer bot, feeding an Excel ledger, wired into whyline

### 1. Does something like this already exist (in this repo or elsewhere)?

Partially — and more than a little. I read the actual `whyline`/`whyline-relay` source
in this repo (`/Users/anish/agentdock`), not just the idea text, and found three
pieces of existing infrastructure that cover large chunks of what's being asked for:

- **A multi-model "brainstorm" engine already ships** (`whyline_relay/brainstorm.py`,
  design doc `docs/superpowers/specs/2026-09-27-chat-brainstorm-design.md`). It runs
  `/brainstorm` inside `whyline chat` with exactly the shape described in the idea:
  pick models from `{claude, codex, antigravity, grok, all}`, pick a number of review
  passes, pick a final-synthesis model, and it does independent research (each model
  writes to its own private temp file so passes are *structurally* blind to each
  other, not just told to behave), then N combined review passes, then a synthesis.
  Availability/backup substitution already exists (`check_availability` against
  `resolve_command`, with a "proceed without them?" prompt). This literal document
  you're reading (`.whyline/relay/brainstorm-tmp/grok.md`) is one of those temp files
  — I am, right now, an instance of the exact mechanism the idea is asking to have
  built. The design doc's own "Non-goals" section explicitly defers "Relay's 'create
  a plan' via brainstorming" and a chat-triggered equivalent to "a separate,
  subsequent design that reuses this engine" — i.e., the repo's own maintainers
  already scoped the next step this idea wants, and deferred it.
- **Agent definitions already have `runner` + `backup` + `model`**
  (`src/whyline/agents/definitions.py`): one TOML file names a primary CLI
  (`claude`/`codex`/`grok`/`antigravity`), an ordered backup list, and an optional
  model string. Triggers already support `manual`, `daily`, `weekdays`, `every N
  hours`, and `folder`-watch (new/changed files in a watched folder kick off a run).
  This is most of "set up the brainstorming automatically" — just not reachable from
  a chat message yet, and not a committee-of-N-with-passes, just one runner + ordered
  fallbacks.
- **Telegram and Mail.app integration already exist, but only outbound / as a
  trigger-from-OS-rule, not as an inbound conversational bot.** `telegram.py` sends
  text/documents via the Bot API and stores the token in Keychain; `find_chats()`
  calls `getUpdates` once, at setup time, purely to let the user discover their chat
  ID — there is no polling loop or webhook listener that watches for new incoming
  messages while whyline is running. `mail.py` only *generates and installs* an
  AppleScript Mail rule that shells out to `whyline agents trigger <name>` when a
  matching email arrives — it doesn't parse the email's content into structured
  fields itself; the *agent's own* instructions text would have to do that.

So this is not "build from scratch" — it's "wire a new front door (Telegram inbound
+ Excel) onto an existing engine room (agent runner, brainstorm orchestrator,
delivery/report pipeline)." That changes the complexity and build-vs-buy answer
substantially versus treating it as greenfield.

Outside this repo, the generic shape (chat bot → LLM triage → spreadsheet log) is
a well-worn pattern (n8n/Zapier + GPT + Google Sheets, or Notion-based idea trackers)
— nothing exotic, no novel algorithm, no reason to build an LLM-routing layer from
scratch if Telegram+Excel is all that's wanted independent of whyline. The reason to
still do it *inside* whyline specifically is the brainstorm engine and agent/runner
plumbing already existing here and nowhere else.

### 2. Rating

- **Usefulness (1–9): 6.** Genuinely useful as a personal-ops tool (idea capture +
  triage is a real, recurring friction point), but the value is concentrated in the
  Telegram capture + Excel ledger half; the "compare against existing
  tools/code" step is exactly the kind of open-ended web-research task LLMs are
  mediocre and inconsistent at — expect it to need a human sanity-check pass before
  the 1–9 rating/complexity/yes-no verdict is trusted, which caps how much time it
  actually saves versus a human skimming for 2 minutes.
- **Complexity (1–9): 6** for a Telegram-capture → Excel-ledger → manual
  plan-or-drop MVP reusing existing agent/runner plumbing. **8** if "integrate into
  whyline" means wiring it to the full multi-model brainstorm-with-passes-and-backup
  engine end-to-end from a Telegram message, because that requires a new stateful
  conversation layer (see §4) that doesn't exist today, plus resolving the
  Antigravity unattended-mode gap (see §3).
- **Should you work on it: Conditional yes, scoped down first.** Build the
  capture → analyze → Excel → plan-or-drop loop with a *single* default model first
  (reusing the existing agent/report/delivery pipeline almost unchanged); treat
  "auto-configure a 4-model brainstorm committee from one Telegram line" as a
  distinct phase 2, because it's the part with real open design questions, not just
  implementation work.

### 3. Where to deploy / run

Everything here is built around **launchd on a single Mac** (`src/whyline/agents/launchd.py`):
one `LaunchAgent` plist runs `whyline agents tick` every 120 seconds and `RunAtLoad`
at login. This directly answers the idea's own question ("how can it run if whyline
is not running / computer is off"):

- It is **not** "whyline scans on start and catches up forever" — it's closer to
  cron. `RunAtLoad: true` means a tick fires right when the user logs in (so it
  does "catch up" on login), and `schedule.plan_tick`/`CATCH_UP_AFTER` (5 min) in
  `tick.py` distinguish a late-but-recent run (still executes, tagged
  `catch_up`) from a stale one (recorded as `missed`, not silently skipped and not
  silently run either). But **if the Mac is off or asleep, nothing runs, full stop**
  — launchd is scoped to the logged-in GUI session (`gui/<uid>` domain in
  `_domain()`), there is no cloud or always-on component anywhere in this codebase.
- For a Telegram bot that must react in real time (not just "whenever the Mac is
  next awake"), this is the actual deployment decision to make explicitly, not
  assume: either (a) accept Mac-must-be-awake as the model (fine for a personal
  single-user tool, consistent with everything else in whyline, zero extra
  infrastructure), or (b) run Telegram's inbound side somewhere always-on (a small
  cloud function or server, or a Mac left running with power-nap/caffeinate) that
  just queues/writes into whyline's existing per-Mac state, with whyline's tick
  picking the queued items up next time it's awake. Don't conflate these two — the
  idea's phrasing suggests the person hasn't decided yet, and the deployment answer
  changes the complexity rating materially (option b adds a second deployable thing
  to maintain).

### 4. The real missing piece: a stateful Telegram conversation, not a trigger

Every existing trigger in this codebase (manual, scheduled, folder-watch, Mail
rule) is **fire-and-forget**: something happens, an agent runs once, a report gets
delivered. Nothing in `src/whyline/agents/` models a multi-turn exchange where
whyline sends a report, waits for a reply ("create plan" vs "drop"), and routes that
reply back to the specific idea it belongs to. That conversational state machine —
"this incoming Telegram message is a reply to idea #47, which is awaiting a
plan/drop decision" — has to be built new. Concretely it needs:

- An inbound listener (poll `getUpdates` with an `offset`, or set a webhook) that
  doesn't exist today — `telegram.py` has no polling loop.
- A persistence layer mapping `chat_id` (+ maybe `reply_to_message_id`) → idea
  record → pending-decision state, so a bare "create plan" typed days later still
  lands on the right row. The existing `state.py`/SQLite activation-tracking
  (referenced throughout `tick.py`) is the right pattern to extend, not a new
  mechanism.
- Free-text parsing with typo tolerance ("teklegram", "analayser" throughout the
  idea's own phrasing is a good stress-test) for both the plan/drop decision and the
  "Plan Model Claude, Codex, Antigravity Grok backup Claude pass 1" syntax — fuzzy
  string matching (e.g. Levenshtein-ish) against the known model names
  (`definitions.CLIS = ("claude", "codex", "grok", "antigravity")`) is cheap and
  local; don't round-trip to an LLM just to fix "calude" → "claude".

### 5. Excel ledger

No spreadsheet dependency exists anywhere in `pyproject.toml` today (checked: no
`openpyxl`, `pandas`, or `xlsxwriter`). Options, cheapest first:
1. **CSV, not XLSX**, if "Excel file" really just means "something Excel can open" —
   zero new dependencies, trivially appendable, diffable. Loses conditional
   formatting/multiple sheets.
2. **`openpyxl`** (new dependency) if real `.xlsx` features (formatting, a
   ratings column with conditional color, multiple sheets for active vs dropped
   ideas) are wanted. This is the natural choice if "send the Excel file over
   Telegram" literally means a `.xlsx` attachment — `telegram.send_document`
   already exists and takes any file path, so wiring an openpyxl-written file
   into it is a small, mechanical step once the ledger itself exists.
Either way, the ledger is a new, separate artifact from whyline's existing
`ledger.jsonl`/`decisions.md` — those are append-only event/decision logs with a
different shape and purpose (git-committed audit trail for *code* decisions), not a
mutable, user-facing idea tracker; don't try to repurpose them.

### 6. Scope check against the idea's own framing

The idea actually describes two sequential systems that got merged into one ask:
(1) a general idea-capture/triage/Excel bot, and (2) a whyline-specific
"auto-configure and launch a multi-model brainstorm from one Telegram line" feature.
System 2 only makes sense bolted onto *this* repo, because it's reusing a real,
already-built engine (§1). System 1 has no dependency on whyline at all and could be
built and validated completely standalone (even with a throwaway script) before
deciding it's worth the integration work in §4. Validating capture+triage+Excel in
isolation first is the lower-risk order — it tests the actually-uncertain part (is
the LLM triage good enough to trust) before investing in the harder-but-mechanical
integration work.
