# Brainstorm: Now I am thinking of creating an analayser say I send an email out, or an telegram bot now when the i type somthing the bot picks up and then anlayse the idea and thn say tell me is there any existing applictaion or code that performs the same task, compares it wih avaiable resource and is it useful to create the this, where to deploy and rate the idea 1-9 with 1 being lowest and 9 hightes., complexity 1-9, should I work on it Yes, No , and so on , .Alsoall the idea needs to be say saved in Excel file on my computer . now once the initial nalysis is completed by brainstorming then send initial report based on the reposne user can then tell creat plan or drop , plan dropped it updated in excel plan is dropped and it has all the information, create plan then it starts brainstorming and work on the specs and plan, now before brainstorming say now user send messge in teklegram create plan and then add say models to be used for brainstorming like Claude, Codex, Antigravity and grok  and back up Claude  and pass 1 somthing like that so it automatcially sets the brainstorming set up and add the prompts . Now we need to integrated into whylien so understand how do to it, so the rsponse should be Plan  Model  Claude, Codex, Antigravity Grok back up Claude pass 1, now when you send message by teleagram give placholders which can help useers another thing, is now use the default model to catch it so that in case of any slight change or spelling mistake model can make the correction, Also anotehr thing is if say whyline is not runnning in terminal or say computer is off, how cna it run then is it when whyline starts it scans and does it or any other method, another things excel keeps on updating with the idea, i can sayt send an email and excel file is sent to telegram , updated excel with all the idea,

## Codex

# Revised assessment: build an Idea Inbox around Whyline’s existing brainstorm engine

## Verdict

**Should this be built? Yes, in stages.**

- **Usefulness: 7/9.** Capturing an idea from a phone, checking prior art, preserving the evidence, and turning an accepted idea directly into a Whyline plan removes real friction. A generic “AI startup idea scorer” is not differentiated; the valuable part is the durable path from message → evidence → decision → reviewed plan.
- **MVP complexity: 6/9.** Telegram intake, one-model analysis, a local ledger, `.xlsx` export, and Plan/Drop actions are moderate work because Whyline already has runners, delivery, Mail.app integration, launchd scheduling, and report generation.
- **Full workflow complexity: 8/9.** Reliable multi-turn Telegram state, source-backed research, multi-model planning, crash recovery, trusted-repository gates, and optional processing while the Mac is off make the complete system substantially harder.
- **Recommendation: WORK ON IT, but validate the small loop first.** Ship capture → analyse → Excel → Plan/Drop before adding an always-on cloud inbox or native app.

The combined review changes one important emphasis from my first pass: this is not mainly a new brainstorming system. Whyline already implements the requested Claude/Codex/Antigravity/Grok independent research, review passes, final synthesis, and plan generation. The net-new product is the **Idea Inbox and conversation controller** that safely feeds that engine.

## What already exists, and what does not

### Reuse directly

- `whyline_relay/brainstorm.py` and the current `/brainstorm` flow already implement independent model passes, combined review passes, final synthesis, availability checks, and plan generation. This document is itself evidence that the committee workflow works.
- `src/whyline/console/adapters.py`, `plan_job.py`, and `auto_run.py` already cover brainstorm invocation, checkpointed spec/plan work, questions, review, approval, and fallback behavior.
- `src/whyline/agents/definitions.py` already models a primary runner plus ordered backups. That is useful for stage-level failover, although it is not the same as a committee of models.
- `src/whyline/agents/telegram.py` already stores the bot token safely and sends messages/documents. Its setup-time `getUpdates` call discovers chats, but it is **not** a persistent inbound listener.
- `src/whyline/agents/mail.py` already supports a Mail.app rule that invokes Whyline with email content as untrusted input.
- The agents LaunchAgent already runs at login and ticks periodically, so work does not require an open Terminal window.

### Build new

- a persistent Telegram `getUpdates` listener, update cursor, sender allowlist, callback handling, and reply correlation;
- a first-class idea record and state machine rather than a sequence of unrelated agent runs;
- source-backed web/GitHub comparison with evidence coverage and confidence;
- a deterministic score rubric and structured report contract;
- a local database plus safe `.xlsx` projection;
- a router for `Create plan`, `Drop`, `Refine`, `Excel`, answers to planner questions, and plan approval;
- background job leases, retries, idempotency, and an outbound message queue;
- optionally, a hosted queue if messages must be accepted while the Mac is powered off.

Do not force the whole workflow into one `AgentDef`. Saved agents are useful execution primitives, but this feature is a long-lived domain workflow with decisions and pauses. It needs its own idea state and should call the existing runner, delivery, and brainstorm services.

## Recommended user flow

### 1. Capture and confirm

An ordinary private Telegram message, or an allowed email, creates an immutable idea event. The bot acknowledges it immediately and shows the normalized interpretation:

```text
IDEA-0042 captured

Title: Voice notes to reviewed engineering plans
Problem: ideas are lost before alternatives are checked
Target user: solo technical founders

[Analyse] [Edit] [Cancel]
```

If the idea lacks a clear user, problem, or outcome, ask at most three short questions before spending money on research. Preserve the original text even when a model corrects spelling or rewrites the brief.

### 2. Analyse

The first useful version can use one default model, but its output must be derived from a structured evidence packet rather than the model’s memory alone. Search, when relevant:

- general web/product sites;
- GitHub repositories, including license and recent activity;
- package registries or app stores;
- Product Hunt or similar sources only when their API terms permit it;
- allowed local repositories and prior ideas for reusable work or duplicates.

Store search queries, URLs, observed dates, connector failures, and coverage. “No result found” must never be presented as proof that no competitor exists.

Return a compact Telegram card and save a full Markdown report:

```text
IDEA-0042 · Analysis complete

Usefulness: 7/9
Complexity: 5/9
Should I work on it? YES
Confidence: Medium

Closest products: …
Closest reusable code: …
Best deployment: local Mac worker; optional hosted inbox

[Full report] [Create plan] [Refine] [Drop] [Excel]
```

### 3. Decide

- **Drop** marks the idea dropped with an optional reason. It never deletes the idea, sources, or prior analysis.
- **Refine** adds context and creates a new analysis version; it does not overwrite history.
- **Create plan** first shows the resolved model configuration and requires confirmation.
- **Excel** rebuilds the current workbook and sends that exact revision as a Telegram document.

### 4. Configure and create the plan

Normalize the user’s compact request into explicit roles:

```text
Plan · IDEA-0042

Research models: Claude, Codex, Antigravity, Grok
Review passes: 1
Final synthesis: Claude
Spec drafter: Codex
Spec reviewer: Claude
Plan drafter: Codex
Plan reviewer: Claude
Fallback chain: Claude → Codex → Grok
Repository: <choose repository>
Auto-start implementation: No

[Start] [Models] [Passes] [Roles] [Repository] [Cancel]
```

The bot may also show a copyable placeholder:

```text
create plan
models: claude, codex, antigravity, grok
passes: 1
final: claude
backup: codex, grok
repository: <name>
```

Resolve each requested CLI/model before starting. A fallback must be distinct from the primary stage model. Antigravity must retain Whyline’s existing unattended/trust restrictions; the Telegram feature must not bypass them.

Planning should reuse the existing brainstorm → synthesis → spec → plan pipeline and its checkpoints. Material questions are sent to Telegram and the job resumes from the saved phase after an answer. “Create plan” stops at a reviewed plan. **Starting relay/implementation is a separate, explicit approval.**

## Spelling tolerance and intent routing

Use two layers:

1. A deterministic parser handles buttons, slash commands, idea IDs, known aliases, case/whitespace normalization, and conservative fuzzy matching of command/model names.
2. Only unresolved free text goes to the default model, which returns a constrained intent object such as `submit_idea`, `create_plan`, `drop`, `refine`, `export_excel`, `answer`, or `unknown` plus confidence and extracted fields.

The model classifies; it does not mutate state. The service validates the intended idea, expected state revision, authorization, and required confirmation. This catches “creat paln” and “Cladue” without letting a probabilistic guess drop or approve the wrong idea.

Buttons should carry an opaque action token tied to the idea and state revision. Free-text consequential actions without an explicit `IDEA-nnnn` may suggest the most recent active idea, but must ask for confirmation.

## Storage and Excel

Use SQLite as the source of truth and `.xlsx` as a user-facing projection. Excel alone is unsafe for concurrent updates, history, deduplication, job leasing, and crash recovery.

Minimum records:

- ideas and immutable inbound events;
- versioned analyses, component scores, reports, and evidence;
- candidates/competitors and reusable-code findings;
- lifecycle transitions and user decisions;
- jobs, checkpoints, retries, and fallbacks;
- conversation context and pending questions;
- outbound messages/documents and delivery status.

Suggested lifecycle:

```text
captured → needs_clarification → analysing → analysed
                                      ├→ dropped
                                      ├→ refining → analysing
                                      └→ plan_configuring → planning
                                                           ├→ waiting_for_answer
                                                           └→ plan_review → approved/discarded
```

Generate the workbook with `openpyxl` only if a real `.xlsx` is required; otherwise CSV is a useful prototype. For `.xlsx`, recommended sheets are `Ideas`, `Scores`, `Competitors`, `Evidence`, `Workflow`, and `Runs`.

Write a temporary sibling, reopen it to validate sheets and row counts, then atomically replace the target. If Excel has the file locked, keep the database update, mark export pending, and retry after the file closes. Escape user/source text that begins with `=`, `+`, `-`, or `@` so it cannot become a spreadsheet formula.

## What happens when Whyline or the Mac is not running

These are different cases:

| State | Local-only design |
|---|---|
| Terminal/Whyline UI closed, Mac awake and logged in | Works through launchd |
| Mac asleep | No intake or analysis until wake; then reconcile pending work |
| Mac powered off | Nothing local can run |
| Mac off longer than Telegram retains updates | An update may be lost |

For the local MVP, install a launchd-supervised long-poll listener for prompt Telegram acknowledgement and keep the periodic Whyline tick as a reconciliation path. On startup it should recover expired job leases, read the last committed Telegram update ID, ingest/deduplicate pending updates, refresh stale workbook projections, retry the outbox, and then resume long polling.

Telegram retains unconsumed bot updates for a limited period (currently no longer than 24 hours), so “scan when Whyline starts” is not enough for indefinite powered-off reliability. If that is a hard requirement, add a small hosted webhook/queue later. It should authenticate Telegram’s webhook, allowlist the sender/chat, durably store an encrypted event, acknowledge quickly, and let the Mac pull it later. Keep model credentials, repositories, analysis, and the authoritative ledger on the Mac.

## Scoring contract

Do not ask a model for an unexplained number. Store a versioned rubric and evidence-linked rationales.

Suggested usefulness/viability dimensions:

- problem value;
- evidence of demand;
- differentiation;
- fit with the user’s skills/resources;
- technical feasibility;
- distribution;
- monetization or strategic value;
- timing, legal, and platform risk.

Suggested complexity dimensions:

- engineering breadth/novelty;
- integrations and external dependencies;
- security/privacy/compliance;
- operations/reliability;
- data acquisition/migration;
- go-to-market or organizational burden.

Return the requested 1–9 headline scores, but also show confidence and evidence coverage. The recommendation should internally be three-valued: `work_on_it`, `do_not_work_on_it`, or `need_more_evidence`. Display that as **YES**, **NO**, or **NOT YET — VALIDATE FIRST** rather than inventing certainty.

## Security boundaries

- Accept only configured private Telegram user/chat IDs and allowlisted email senders.
- Treat idea text, email, web pages, READMEs, and attachments as untrusted data, never instructions.
- The classifier can return typed intent only; it cannot execute commands.
- Analysis is read-only with respect to user repositories.
- Repository choice must come from an allowlist; do not accept arbitrary paths from Telegram.
- Require separate confirmations for Create plan, plan approval, and Start relay.
- Preserve current trust/dirty-tree/preflight gates, especially for Antigravity.
- Deduplicate by Telegram `update_id` or email Message-ID/content hash.
- Never place bot tokens, secrets, raw prompts, or private paths in the workbook or callback payloads.
- Block research fetches to localhost, private/link-local networks, file URLs, and cloud metadata endpoints.

## Delivery plan

### Phase 0 — prove the contracts

Define the idea state machine, score/report schemas, command grammar, workbook layout, and a stable service adapter around the current brainstorm engine. Prototype one Telegram update and one validated workbook export.

### Phase 1 — local ledger and CLI

Add SQLite migrations and `whyline ideas add/list/show/analyse/drop/reopen/export/doctor`. Use fixture evidence first. Verify lifecycle transitions, analysis versioning, crash safety, and workbook replacement.

### Phase 2 — Telegram inbox

Add long polling, cursor persistence, sender authorization, buttons, conversation context, deterministic/fallback intent routing, the outbox, `/status`, and `/excel`. Supervise it with launchd and reconcile on startup.

### Phase 3 — real research

Add general-web, GitHub, and allowed-local-repository connectors; canonicalize candidates; validate citations; track freshness, partial failure, and evidence coverage. Do not make Product Hunt or other restricted APIs hard dependencies.

### Phase 4 — existing brainstorm/plan integration

Add the normalized model/role/pass card, invoke the current brainstorm and checkpointed spec/plan services, route questions through Telegram, enforce fallbacks and trust gates, and stop at plan review.

### Phase 5 — email, then optional hosted queue

Route the existing Mail.app rule into the idea service with deduplication and Telegram confirmation for consequential actions. Add a hosted inbox only if real usage proves powered-off capture is worth its cost and privacy surface.

## Acceptance tests that matter most

1. A misspelled idea/command is interpreted, confirmed, analysed once, and appears once in SQLite and Excel.
2. A duplicated Telegram update produces one idea, one job, and one response.
3. A stale Drop/Approve button is rejected after the idea revision changes.
4. A crash between saving analysis and replying retries delivery without rerunning analysis.
5. A planner question answered in Telegram resumes the same checkpoint.
6. An unavailable model uses only an approved distinct fallback and records the substitution.
7. An open/locked workbook delays export without losing the idea.
8. A malicious idea, README, or web page cannot run a shell command or redirect the workflow.
9. `Create plan` never starts implementation without the separate Start relay approval.
10. Startup after sleep/offline time reconciles provider updates, job leases, workbook revision, and outbound delivery.

## Bottom line

Build a **local-first Idea Inbox for Whyline**, not a standalone scoring bot and not a new brainstorm engine. The strongest first release is Telegram text capture on an awake Mac, a durable SQLite ledger, source-backed one-model triage, versioned 1–9 usefulness and complexity scores, safe Excel export, and explicit Plan/Drop actions. Once that loop proves useful, connect Create plan to Whyline’s already-working multi-model brainstorm/spec/plan pipeline. Add cloud queuing only if powered-off capture is truly required.

## Claude

# Idea Analyzer: independent research pass (antigravity)

Scope as I read it: an intake channel (Telegram message or email) captures a raw
idea; a first pass ("brainstorm triage") checks for prior art, scores novelty
(1-9), complexity (1-9), and gives a yes/no/maybe recommendation; everything is
logged to an Excel workbook on the user's Mac; the user replies "create plan" or
"drop" to advance or close the idea; "create plan" kicks off a deeper, multi-model
brainstorm (Claude, Codex, Antigravity, Grok, with a backup model and a "pass"
count) that produces a spec and plan; all of this should live inside Whyline,
run even when no terminal is open, and be able to push the Excel file back out
over Telegram on request.

## 1. What already exists in this repo that this idea should reuse

Whyline already has ~80% of the mechanics this idea is asking for, under
`src/whyline/agents/`. Building a parallel system would duplicate a lot of
hard-won, tested infrastructure. Concretely:

- **`definitions.py`** — an `AgentDef` is already "runner (claude/codex/grok/
  antigravity) + backup list + model + sources + trigger + timeout" as a TOML
  file. The idea's "Plan · Model Claude, Codex, Antigravity, Grok · backup
  Claude · pass 1" is almost exactly this schema already, minus a "pass count"
  field and minus the idea of *multiple* runners cooperating on one occurrence
  (today one `AgentDef` has one `runner` plus backups that substitute for it on
  failure — it's a failover chain, not a panel of simultaneous reviewers).
- **`telegram.py`** — Bot API send/receive already implemented, token stored in
  Keychain (0600 file elsewhere), `send_document` (so the Excel file could be
  pushed over Telegram) and `send_message` already exist.
- **`mail.py` / `mail_send.py`** — a Mail.app rule AppleScript pipes an incoming
  email's body into `whyline agents trigger`, and outbound mail delivery exists
  separately. So "send an idea by email" is close to solved on the ingestion
  side.
- **`launchd.py`** — the "what if Whyline isn't running / computer restarted"
  question is already answered for macOS: a single LaunchAgent
  (`com.whyline.agents`) runs `whyline agents tick` every 120s and `RunAtLoad`.
  That's the scan-based model the user half-guessed at ("is it when whyline
  starts it scans"). It is explicitly **not** always-on/event-driven — it's a
  poll every ~2 minutes, and `scheduler_summary()` in `service.py` says outright:
  "Runs need this Mac on and you logged in. If it's asleep or off at a
  scheduled time, that agent runs once when it wakes or you log in." Any
  promise of instant Telegram responsiveness has to be scoped around that
  2-minute ceiling, not promised as real-time.
- **`folders.py`** — folder-watch triggers already debounce by `min_gap_minutes`
  and snapshot file state; the same pattern (poll, diff, debounce, copy into a
  stable payload dir) is the right template for an inbox-watch trigger, rather
  than inventing a new polling mechanism.
- **`capabilities.py`** — this is the single most important file to read before
  committing to "Claude, Codex, Antigravity, Grok" as a four-way panel.
  `UNATTENDED_OK = frozenset({"claude", "codex", "grok"})` — **Antigravity is
  not in this set.** The comment says literally: `# "antigravity": only once the
  spike verifies a read-only --mode.` And `agents.trigger()` in `service.py`
  already enforces this: it refuses to trigger an agent unless at least one of
  `runner`/`backup` is unattended-capable. If the idea genuinely wants
  Antigravity in the brainstorming rotation, triggered from Telegram with nobody
  watching, that's currently a hard block, not a config choice. Either (a) the
  rotation only runs unattended-capable CLIs and Antigravity is added for
  human-supervised "create plan" sessions only, or (b) someone has to do the
  read-only-mode spike for Antigravity first. This is worth surfacing to the
  user as a real constraint, not a detail to gloss over.
- **`deliver.py` / `deliveries.py` / `convert.py`** — delivery already supports
  attaching `.docx` (falls back to `.md` if conversion isn't available) over
  email or Telegram. There is **no Excel/xlsx path today** — no `openpyxl` (or
  similar) in `pyproject.toml` dependencies. Excel-as-ledger is new work, not an
  extension of an existing capability.

**Net:** this is not a greenfield feature. It's "add an idea-intake agent type
on top of the existing agent framework," plus "add an Excel-backed ledger," plus
"close the gap where an inbound message maps to a *running conversation*
(triage -> user reply -> plan) rather than one-shot read + report." That third
piece — stateful, multi-turn interaction over Telegram — does not exist yet;
every current agent run is fire-and-forget (trigger -> run -> deliver report).
Building a conversational loop out of a system designed around discrete,
isolated runs is the main architectural stretch here, not the AI/scoring part.

## 2. Does something like this already exist? (the idea's own first question)

The idea asks the bot to check, for *every submitted idea*, whether a
comparable tool already exists. It's worth turning that lens on the idea
itself:

- **Idea-capture-to-spreadsheet bots**: common as weekend projects (IFTTT/Zapier
  "Telegram message -> Google Sheets row," various "idea inbox" GPT wrappers).
  None of the public ones do prior-art research or scoring — they're dumb
  capture-and-log tools.
- **AI research/scoring layer ("is this worth building, what exists already,
  score it")**: this is the genuinely less-common part. It overlaps with
  "AI co-scientist" / "startup idea validator" SaaS products (there are a
  handful, e.g. idea-validation GPTs, and YC's internal tools are rumored to do
  something similar) but those are hosted web products, not something that
  plugs into a local dev workflow or a CLI agent runner.
- **Multi-model brainstorming with automatic model failover**: this is the part
  that's genuinely novel relative to what's publicly available, *and* it's the
  part this repo already has the most infrastructure for (the `backup` chain in
  `definitions.py`, the failover already observed in production use — see the
  Oct 13 incident where Codex rate-limited and Antigravity auto-substituted as
  reviewer in a relay run). So the differentiated, defensible part of this idea
  is exactly the part Whyline is best positioned to build, because the hard
  parts (CLI orchestration, failover, read-only enforcement) are already solved
  for a *different* feature (the relay/review pipeline) and can be reused.

Conclusion on "does this exist": the capture+Excel part is commodity; the
scoring/rating part is a thin wrapper around a single LLM call (not defensible
on its own); the multi-model brainstorm-with-failover part is the genuine
differentiator, and it's differentiated specifically *because* it would live
inside Whyline rather than as a standalone bot.

## 3. Proposed shape of the workflow, mapped onto what exists

1. **Capture.** Telegram message or forwarded email -> a new trigger kind
   (`inbox`, sibling to `folder`) appends the raw text as a payload file and
   claims an occurrence, same as `folders.check()` does today. Deliberately
   *not* a new transport: reuse the Telegram bot and Mail.app rule that already
   exist.
2. **Triage run.** A dedicated `AgentDef` (e.g. `idea-triage`), `runner` drawn
   from the unattended-capable set, read-only, single pass. Its instructions:
   search for prior art (needs either a read-only web-search capable CLI mode or
   an MCP web-search tool — check which of claude/codex/grok can do this
   read-only under `capabilities.py`'s rewrite rules before promising it),
   produce novelty score /9, complexity /9, recommendation, and a short report.
3. **Ledger write.** Append a row to the Excel workbook. This has to be a
   *library* write (e.g. `openpyxl`), not "have the LLM edit the xlsx" — xlsx is
   a zipped XML format; letting a model open/edit/save it directly is how people
   end up with corrupted workbooks. The agent should emit structured data (JSON)
   and a small, separate, deterministic Python function should own all xlsx
   writes. Keep the LLM out of the file I/O path entirely.
4. **Report back.** Reuse `deliver.py`'s existing Telegram/email send path to
   message the user with the triage summary and a `create plan` / `drop`
   prompt.
5. **Reply handling.** This is the new piece: the *reply* to a triage message
   has to route back to the same idea record, not start a new occurrence blind.
   Telegram gives you `reply_to_message_id` in the update payload — the ledger
   needs to track "last outbound message ID for idea N" so an incoming reply
   can be matched to it. (`telegram.py` today only sends; there's no inbound
   polling/webhook handler yet — `find_chats()` uses `getUpdates` for setup, but
   nothing listens continuously. That's new work: either long-poll
   `getUpdates` from the tick loop, or stand up a webhook, which needs a public
   endpoint — much bigger scope than anything else here, so long-poll is the
   pragmatic choice for a single-user Mac tool.)
6. **Drop.** Mark the ledger row `dropped`, done — no agent run needed, this is
   pure bookkeeping on the existing row.
7. **Create plan.** This spawns the heavier multi-model brainstorm. Here the
   "Plan · Model Claude, Codex, Antigravity, Grok · backup Claude · pass 1"
   syntax the user describes is a per-idea override of a default panel
   definition — model it as a small, parseable command grammar (similar to
   slash-command parsing already in `src/whyline/console` for `/relay` etc.),
   not free text parsed by an LLM every time. Use "default model catches typos"
   only as a fallback *after* a cheap fuzzy/alias match fails (e.g.
   `difflib.get_close_matches` against the known CLI names) — spending an LLM
   call to parse "Cladue" into "Claude" is solvable with a 3-line fuzzy-match
   instead of a model round-trip, which is cheaper and has no failure mode where
   the parser itself misunderstands.
8. **Brainstorm + spec/plan.** This is exactly the existing relay/brainstorm
   machinery (the repo already has `.whyline/relay/brainstorm-tmp/`, multi-
   model independent passes converging into a shared spec — this very file is
   an instance of that mechanism). The idea doesn't need a new brainstorming
   engine; it needs the ledger entry to carry enough context (the original
   idea text, the triage report) to seed a relay brainstorm run, and for the
   relay's finished plan/spec to write its outcome back to the same Excel row.

## 4. Excel as the system of record — risks worth naming

- **Concurrent writers.** If Whyline (background tick) and the user (Excel
  open in Numbers/Excel.app) touch the file at the same time, last-write-wins
  can silently drop rows. Mitigate by never editing the live file directly —
  write to a temp file and atomic-rename, and treat "file locked because it's
  open on screen" as an expected, handled error (retry/backoff), not a crash.
- **Schema drift.** The user will eventually add a column by hand ("notes") in
  Excel directly. The ingest code needs to write by column *name*, not
  position, or a manually-inserted column shifts every future automated write.
- **One workbook vs. one-sheet-per-status.** A single "Ideas" sheet with a
  `status` column (new/triaged/planning/dropped/shipped) beats separate sheets
  per status — otherwise "create plan" requires *moving* a row between sheets,
  which is more failure-prone than flipping one cell.
- **"Send me the Excel file" over Telegram** is just `telegram.send_document()`
  on the existing workbook path — already works today, no new capability
  needed, just wiring.

## 5. The "default model catches spelling mistakes" requirement

Worth pushing back on gently: routing every inbound command through an LLM
"to catch typos" means every Telegram message costs an API call and adds
latency before the system even knows what the user wants, and it makes the
command grammar's failure mode "the model misread it" instead of "unknown
command, here are valid options." A deterministic parser with (a) a short list
of known commands/model names, (b) fuzzy matching for near-misses, and (c)
falling back to a clarifying Telegram reply ("Did you mean Claude?") when
confidence is low, is more predictable, cheaper, and auditable than "throw it
at the default model." Placeholders in the Telegram prompt (e.g. a message
template like `Plan · Model: _, _, _ · Backup: _ · Passes: _`) solve the
"help the user get the syntax right" problem earlier and better than fuzzy
correction after the fact — prevention over correction.

## 6. Whyline integration — concrete, minimal-diff path

Rather than a new subsystem, the smallest-diff integration is:
- One new trigger kind, `inbox`, in `definitions.TRIGGER_KINDS`, parallel to
  `folder` (a Telegram long-poll loop or a Mail rule feeds it, same as
  `folders.check()` feeds `folder`).
- One new agent archetype shipped as a template definition (`idea-triage.toml`)
  rather than new code paths — it's just an `AgentDef` with specific
  instructions, so the existing runner/backup/capabilities machinery applies
  unchanged.
- A new `whyline/agents/ledger.py` (xlsx read/append/update via `openpyxl`,
  atomic writes) — the only genuinely new storage code.
- A new, small reply-router that matches an inbound Telegram message to an open
  idea (by `reply_to_message_id` or, failing that, most-recent-open-idea) and
  either flips the ledger status (`drop`) or triggers the plan/brainstorm agent
  with the idea's context attached as its payload.
- Reuse `deliver.py` unchanged for outbound messages; reuse the relay/
  brainstorm mechanism unchanged for the "create plan" stage.

## 7. Open questions to resolve before writing any code

1. Does any of claude/codex/grok actually expose a read-only *web search*
   capability today (needed for "does this already exist" research), or does
   triage need an MCP web-search tool wired in as a `sources`-equivalent? This
   determines whether triage quality is good on day one or is initially just
   "the model's training-data guess."
2. Is Antigravity meant to participate only in human-supervised "create plan"
   sessions (fine, no capability change needed), or also in the unattended
   Telegram-triggered path (blocked until the capabilities spike covers it)?
3. Single workbook for all ideas, or one row-per-idea in a single sheet with a
   status column (recommended) vs. the user's "it has all the information
   when dropped" framing, which might imply they want full idea history
   preserved per row rather than archived elsewhere — needs clarifying with
   the user, since it changes whether "drop" deletes vs. marks.
4. What happens if Whyline's 2-minute tick is asleep for days (laptop closed)
   and 10 ideas pile up in Telegram — does triage run all 10 in one wake, and
   does the user get 10 messages at once or one digest? This is a product
   decision, not a technical one, and should be surfaced before building.

## 8. Phased build order (smallest safe increments)

1. `ledger.py`: xlsx read/append/update, atomic writes, column-by-name. Unit
   tests only, no agent wiring yet.
2. `inbox` trigger kind + Telegram long-poll ingestion -> writes a payload,
   claims an occurrence, exactly like `folder` today. Test with manual
   `whyline agents trigger` first before wiring live polling.
3. `idea-triage` agent definition + ledger write on completion + Telegram
   report-back via existing `deliver.py`. This alone is a shippable v1 ("idea
   catcher + scorer + spreadsheet"), independent of the plan/brainstorm stage.
4. Reply router (drop / create plan) — the first genuinely new piece of
   conversational state.
5. Wire "create plan" replies into the existing relay/brainstorm flow, with
   the model-panel command grammar from section 5, and write the plan's
   outcome back to the ledger row.
6. "Send me the Excel file" command — thin wrapper over
   `telegram.send_document()`, basically free once steps 1-3 exist.

## 9. Testing notes

- `ledger.py` should be tested against a real `openpyxl` round-trip (write,
  reopen, assert values) rather than mocked — spreadsheet corruption is exactly
  the kind of bug that only shows up against the real library (same lesson as
  the project's existing "don't mock the database" posture, if that convention
  carries over here).
- The reply-router matching logic (which idea does this Telegram reply belong
  to) is pure logic and should be unit-tested with fabricated update payloads,
  no network.
- Capability gating (point 2 above) should get an explicit test asserting that
  an `inbox`-triggered run refuses to use Antigravity as the sole runner,
  mirroring the existing `trigger()` unattended-capability check.

## Claude

## Revised assessment: converging on an Idea Inbox built on the existing brainstorm engine

My first pass and Codex's revised pass land in the same place by different routes,
and the Antigravity pass filed above this heading (its own title names it, despite
the mislabeled heading — not something I'm touching here) independently traced the
same conclusion through a third set of files. Three separate reads of this codebase
converging on "wire a Telegram/email front door onto the existing brainstorm engine,
not a new system" is itself evidence this is the real shape of the work, not one
model's bias.

### Where I land

- **Usefulness: 7/9.** Revising my original 6 up to match Codex. The friction
  removed — an idea never gets lost, prior art gets checked before a yes/no
  decision, an accepted idea walks straight into a plan the user still has to
  approve — is real and recurring. The weak link, which I flagged originally and
  nothing in the other passes overturns, is that "does this already exist" is
  exactly the kind of open-ended web research LLMs are inconsistent at; budget for
  a human skim before trusting the verdict.
- **MVP complexity: 6/9. Full multi-model-from-one-Telegram-line complexity: 8/9.**
  Unchanged from my first pass. Codex's phased plan is a more detailed version of
  the same split I drew between "System 1" (capture → triage → Excel → plan/drop)
  and "System 2" (auto-configured committee brainstorm). System 1 has no dependency
  on whyline and should be validated first — it tests the genuinely uncertain part
  (is the triage good enough to trust) before paying for the larger-but-mechanical
  integration work in System 2.
- **Verdict: yes, scoped down first.** Ship System 1 with one default model before
  building the Telegram-driven committee configurator.

### What the other passes changed in my analysis

- **The Antigravity unattended-mode gate is a hard blocker, not a detail.** The
  pass above traced `capabilities.py`'s
  `UNATTENDED_OK = frozenset({"claude", "codex", "grok"})` and the enforcement in
  `agents.trigger()` — Antigravity cannot be the sole or triggering runner on an
  unattended, Telegram-triggered path today. My own pass only gestured at this
  generically ("resolving the Antigravity unattended-mode gap"); it deserves to be
  stated as plainly as the other pass did, and surfaced to the user as an explicit
  scoping decision before "Claude, Codex, Antigravity, Grok" is promised as a
  from-Telegram committee.
- **Codex's SQLite-plus-`.xlsx`-projection design beats the file-format framing I
  used.** I treated the ledger as a CSV-vs-openpyxl choice. Once concurrent writers,
  crash recovery, and job retries are in scope — which they are the moment this runs
  unattended via launchd — SQLite as the source of truth with Excel as a generated
  projection is the correct call, and I'm deferring to that design over my original
  framing.
- **The conversational-state gap is now confirmed from two independent reads, not
  one.** Both the other pass and mine independently found the same missing piece by
  tracing different files: nothing in `src/whyline/agents/` or `telegram.py` models
  a multi-turn exchange, and every existing trigger is fire-and-forget. Two passes
  finding the same hole by different paths is the strongest signal in this document
  that it's real and deserves its own phase, not something to bolt on later.
- **Deterministic parsing over LLM-based typo correction: every pass agrees.** The
  idea's own text ("teklegram", "analayser") is the test case, and fuzzy-matching
  against known model/command names, falling back to a clarifying reply, beats an
  API round-trip per message. Codex's two-layer design — a deterministic parser
  first, a constrained-intent classifier only for unresolved free text — is a
  cleaner version of what both other passes sketched informally; I'd adopt it as
  written rather than re-deriving it.

### Where I still differ slightly

Codex leaves `.xlsx` generation conditional ("only if a real `.xlsx` is required;
otherwise CSV"). I'd commit to `openpyxl` from the start rather than leave it
conditional: the moment "send me the Excel file over Telegram" is a stated
requirement — it is, in the original ask — a `.xlsx` attachment is what "Excel
file" means on a plain reading of the request, and starting with CSV just adds a
rewrite later for a dependency that's one line in `pyproject.toml`.

### Bottom line

Don't build a new brainstorming system — whyline already has one, and this very
document is running on it. Build the Idea Inbox: Telegram/email capture, one-model
triage backed by real search, a SQLite ledger with an `openpyxl` projection,
explicit Plan/Drop/Refine actions, and only then wire "Create plan" into the
existing multi-model pipeline with the Antigravity unattended-mode gate respected
from day one.
