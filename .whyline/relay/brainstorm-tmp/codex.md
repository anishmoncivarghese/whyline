# Whyline Idea Analyst: independent research and proposed plan

## Executive recommendation

Build this as a new **Idea Inbox** workflow inside Whyline, not as one large saved-agent prompt and not as an Excel-first application.

The product should let the user send an unstructured idea from Telegram or email, tolerate spelling and phrasing differences, research whether similar products and code already exist, produce a cited evaluation, score the idea and its complexity from 1–9, recommend **Work on it / Do not work on it / Need more evidence**, save the full record locally, and then wait for a deliberate decision:

- **Create plan** starts the existing Whyline brainstorm → synthesis → spec → plan machinery with an explicit model roster and fallback policy.
- **Drop** closes the idea without deleting its evidence or analysis.
- **Refine** adds more information and runs a new, versioned analysis rather than overwriting the old one.
- **Excel** generates the latest workbook and sends it to Telegram.

Use four layers:

1. **Telegram/email adapters** receive messages and turn them into immutable inbox events.
2. **An idea service and SQLite database** own identity, state, deduplication, scores, evidence, decisions, and jobs.
3. **A worker** performs web/code research and invokes Whyline’s current models and relay functions.
4. **An Excel projector** atomically regenerates a local `.xlsx` workbook from SQLite whenever an idea changes.

For the first release, run the worker as a macOS LaunchAgent. It works while the Whyline console and Terminal are closed, as long as the Mac is awake and the user is logged in. On wake or login it catches up queued work. If the Mac is powered off, no local code can run. Telegram retains unconsumed bot updates for no more than 24 hours, so a Mac-only version cannot honestly promise durable intake during a long shutdown. Add an optional tiny hosted inbox later if immediate acknowledgement and indefinite queueing while the Mac is off are required.

The feature is worth building for Whyline, but the differentiation is **not “AI scores startup ideas.”** That market already contains many products. Whyline’s defensible angle is a local, multi-model, evidence-linked path from a message to a durable decision, then directly into an executable, reviewed Whyline plan.

## What already exists in Whyline

This should reuse the repository rather than create a parallel automation stack.

### Existing capabilities that fit

- `src/whyline/agents/` already provides saved jobs, a SQLite state store, run records, a macOS LaunchAgent heartbeat, manual triggers, catch-up behavior, main/backup CLIs, notifications, and output delivery.
- `src/whyline/agents/mail.py` and `docs/agents-mail-recipe.md` already support Mail.app rules that pass an email to `whyline agents trigger` as untrusted input.
- `src/whyline/agents/telegram.py` already stores the bot token in Keychain on macOS, discovers chats, and sends messages/documents with the Telegram Bot API.
- `src/whyline/agents/deliver.py` already sends successful reports by Mail or Telegram.
- `src/whyline/console/adapters.py::run_brainstorm` already invokes the relay’s multi-model independent research, review passes, and final synthesis.
- `src/whyline/console/plan_job.py` already models brainstorm, synthesis revision, spec drafting, plan drafting, questions, approval, and discard.
- `src/whyline/console/auto_run.py` already has a checkpointed flow from research through spec and plan, supports a fallback chain, detects pauses, and can later launch a relay.
- whyline-relay already has `brainstorm.run_pass_zero`, `run_review_pass`, `run_final_synthesis`, `generate_plan_from_synthesis`, and the planner/spec question-and-answer machinery.

### Missing capabilities

- Telegram is outbound-only today; there is no inbound bot listener or offset persistence.
- Saved agents are read-only analysis jobs. The idea workflow needs controlled writes to its own database/workbook and, only after approval, to repository brainstorm/spec/plan files.
- There is no first-class idea entity, evidence model, score rubric, or idea lifecycle.
- The existing agent scheduler checks periodically, but there is no job queue for multi-stage workflows or per-idea commands.
- The existing Telegram layer has no commands, inline keyboards, callback-query handling, sender authorization, or message-to-idea correlation.
- There is no `.xlsx` dependency or exporter in `pyproject.toml`.
- There is no hosted inbox for periods when the Mac is powered off.

The right implementation is therefore a new `whyline.ideas` domain package that composes the existing agents, delivery, brainstorm, planner, and auto-run services.

## Competitive research and product position

The basic category is crowded. Current products already advertise combinations of idea scoring, market analysis, competitor discovery, risk assessment, MVP plans, and build/pass verdicts:

- [ValidateIdea](https://validateidea.org/) advertises demand, competition, monetization, an opportunity score, and an idea dashboard.
- [Verdiccio](https://www.verdiccio.com/) advertises separate agents for demand, competition, monetization, go-to-market, and risk, using sources including Reddit, Hacker News, Product Hunt, YC, GitHub, Google Trends, and competitor sites.
- [IdeaValidator](https://ideavalidator.app/) advertises live cited research, consistent scoring dimensions, and a Worth Doing / Proceed with Caution / Pass verdict.
- [Idea Copilot](https://ideacopilot.ai/) advertises competitor data, an MVP plan, and a build-or-kill verdict.
- [StartupDeckAI](https://www.startupdeck.in/) advertises scored validation reports, competitor and market analysis, sources, and retained company memory.

This proves demand for the workflow but also proves that a generic validator is easy to copy. Whyline should differentiate on:

1. **Capture anywhere, keep locally.** Telegram/email intake with a local database and workbook the user owns.
2. **Evidence before score.** Every competitive claim and score links to evidence, search time, and source quality.
3. **Multi-model disagreement.** Claude, Codex, Grok, and optionally Antigravity independently assess the idea before synthesis; the report preserves disagreements instead of hiding them behind one score.
4. **Decision provenance.** “Create plan,” “Drop,” later refinements, and score changes become durable Whyline decisions.
5. **Idea-to-execution continuity.** One approved Telegram action turns the same evidence into a brainstorm, spec, reviewed plan, and eventually a relay run.
6. **Honest uncertainty.** The system reports evidence coverage and confidence separately from viability. It must not manufacture market size or label an idea good merely because the prose sounds convincing.

## Desired user experience

### First-time setup

The user runs:

```text
whyline ideas setup
```

The wizard should:

1. choose a default repository or an “unassigned” inbox;
2. choose the local workbook path, defaulting to `~/Documents/Whyline Ideas.xlsx`;
3. connect the existing Telegram bot token or set up a new one;
4. ask the user to send `/start` to the bot, then pin the allowed private `chat_id`;
5. optionally install a Mail.app rule with an allowed sender list;
6. choose the default analyser model and the planning roster;
7. install/enable the Whyline LaunchAgent;
8. run a round-trip test and show the precise offline promise.

The bot should send a compact starter card:

```text
Send me an idea in ordinary language.

Examples
• An app that …
• Analyse whether … already exists
• /new — guided idea template
• /ideas — recent ideas
• /status — running and waiting work
• /excel — send the latest workbook
• /help — commands and examples
```

### Free-form idea capture

Any ordinary private message that is not clearly a command becomes a candidate idea. The bot immediately creates an ID and echoes its interpretation:

```text
IDEA-0042 captured

Working title: Voice notes to reviewed engineering plans
Problem: founders lose ideas and do not validate alternatives before building
Target user: solo technical founders

[Analyse] [Edit] [Cancel]
```

For a long, clear message, analysis can be the default after a short undo window. For a vague message such as “make something for invoices,” ask no more than three high-value questions: target user, painful job, and desired outcome. Do not start expensive multi-model work when the core problem is still ambiguous.

Photos, documents, forwarded emails, and voice messages should be later increments. The database schema should support attachments from day one, but v1 can accept text and `.txt`/`.md` files only.

### Initial analysis response

Telegram should receive a concise decision card, not the entire research document:

```text
IDEA-0042 · Analysis complete

Viability: 7/9
Complexity: 5/9
Recommendation: WORK ON IT
Confidence: Medium

Why: strong workflow fit and feasible MVP, but several idea-validation tools already exist. The opportunity is Whyline’s local multi-model idea-to-plan workflow, not generic scoring.

Closest products: Verdiccio, IdeaValidator, Idea Copilot
Closest code: 4 relevant GitHub repositories reviewed
Best deployment: local Mac worker + Telegram; optional hosted inbox later

[Full report] [Create plan] [Refine] [Drop]
[Evidence] [Excel] [Status]
```

The full Markdown report is saved locally and may also be sent as a document. Telegram text has practical length limits, so the bot should paginate or attach long output; the existing `send_document` implementation can be reused.

### Drop flow

Pressing **Drop** or sending `drop IDEA-0042` must not delete anything. It produces:

```text
IDEA-0042 marked Dropped.
Reason? (optional)

[Duplicate] [Low value] [Too complex] [Not now] [Type reason]
```

The final state is `dropped`, with `decided_at`, `decision_source=telegram`, and an optional reason. The workbook updates, and the idea stays searchable. “Reopen” creates a new workflow transition; it does not erase the drop decision.

### Create-plan flow and placeholders

Pressing **Create plan** must first show the effective setup. The user’s requested wording can be preserved, but the internal fields need to be unambiguous:

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
Repository: agentdock
Start implementation after approval: No

[Start] [Models] [Passes] [Roles]
[Repository] [Cancel]
```

Helpful placeholders when the user types `create plan`:

```text
Models: Claude, Codex, Antigravity, Grok
Passes: 1
Final: Claude
Backup: Claude, Codex, Grok
Repository: <choose repository>
Spec first: Yes
Auto-start relay: No
```

The parser can understand compact variations such as:

```text
create plan models claude codex agy grok backup claude pass 1
```

but it must return the normalized card for confirmation before starting. “Backup Claude” is not meaningful for a stage already being run by Claude; validation should explain that and select the next distinct fallback rather than silently creating a self-backup.

Antigravity needs special handling. Whyline’s current capability spike found that its plan mode can still write files and therefore excluded it from unattended read-only agents. The relay already requires repository trust before Antigravity work. The Telegram flow may list it in an approved brainstorm roster, but it must stop at a `needs_local_approval` gate if that repository has not already been trusted. It should not weaken the current protection.

After confirmation, the job should reuse the current brainstorm/auto-run checkpoints. When a model asks a material question, Telegram receives the question and safe choices. The pipeline stays paused until answered. Plan creation ends at review by default:

```text
IDEA-0042 · Plan ready
Saved: plans/voice-notes-to-reviewed-plans.plan.md
12 tasks · spec and plan reviewed

[Approve] [Request changes] [Discard plan]
[Start relay] [Open report]
```

Never start implementation merely because the user requested a plan. “Create plan” and “start relay” are separate authority boundaries.

### Excel request

`/excel`, `send excel`, `send updated spreadsheet`, or the **Excel** button should:

1. enqueue an `export_workbook` job;
2. regenerate the workbook from the database into a temporary file;
3. validate that it can be opened and contains the expected sheets/row counts;
4. atomically replace the local workbook;
5. send that exact version through Telegram’s `sendDocument`;
6. record the workbook revision and delivery result.

The response should say, for example, `Whyline Ideas.xlsx · 42 ideas · updated 14 Oct 2026 02:35 IST`, so the user can see whether it is current.

## Intent understanding without unsafe guesswork

Use a two-stage router.

### Stage 1: deterministic parsing

Recognize exact commands, button callback payloads, IDs, and common aliases without a model:

- `/new`, `new idea`, `analyse this`;
- `/ideas`, `list ideas`, `show recent`;
- `create plan`, `make plan`, `plan IDEA-0042`;
- `drop`, `archive`, `not worth it`;
- `/excel`, `send sheet`, `send spreadsheet`;
- `/status`, `what is running?`;
- `cancel`, `stop`, and answers tied to an outstanding question.

Normalize case and whitespace and use conservative fuzzy matching for command words only. Never fuzzy-match an arbitrary idea into a destructive command.

### Stage 2: constrained model classification

If deterministic parsing fails, call the configured default model with the recent conversation and a strict JSON schema:

```json
{
  "intent": "submit_idea | create_plan | drop | refine | export_excel | status | answer | unknown",
  "idea_id": "IDEA-0042 or null",
  "fields": {},
  "confidence": 0.0,
  "needs_confirmation": true,
  "clarifying_question": ""
}
```

The model only classifies and extracts. It cannot directly mutate state or launch work. The service validates the JSON, resolves the idea and current state, applies authorization and idempotency checks, and asks for confirmation when confidence is low or the action is consequential.

Conversation correlation rules are important:

- A button callback includes `idea_id`, expected state revision, and action.
- Free text within a pending-question window answers that question.
- Free text mentioning an explicit `IDEA-nnnn` applies to that idea.
- Otherwise the most recent active idea may be suggested, but must be confirmed for Drop, Create plan, Approve, Discard, or Start relay.

This provides spelling tolerance without allowing a probabilistic model to choose the wrong idea or execute an unintended action.

## Evidence and analysis pipeline

The analyser should produce evidence, not just a polished opinion.

### 1. Structure the idea

Extract and retain both the original text and a normalized brief:

- working title;
- user/problem/job-to-be-done;
- proposed solution;
- target user and buyer;
- context or industry;
- business model, if stated;
- constraints, founder resources, and desired deployment;
- keywords, synonyms, and alternative phrasings;
- assumptions and missing information.

Every later report links to the immutable original inbox event. A model revision never replaces it.

### 2. Generate search plans

Create several narrow queries rather than one broad query:

- exact problem and target user;
- proposed solution category and synonyms;
- “alternative to” and “competitor” queries;
- open-source implementation queries;
- platform/app-store queries where relevant;
- user-pain queries from forums or issue trackers;
- deployment and regulatory constraints.

Keep the generated queries in the evidence record. This makes it possible to inspect coverage and rerun stale research later.

### 3. Search independent source classes

Minimum useful coverage:

- **General web:** product sites, vendor documentation, credible articles, and domain-specific sources.
- **GitHub:** repository search first, then README/license/activity inspection for the most relevant candidates. GitHub’s official search API returns at most 1,000 results, has separate search rate limits, and may return `incomplete_results`; authenticated general search is limited to 30 requests/minute and code search to 10 requests/minute. The analyser must store those caveats rather than treat an empty result as proof that no code exists. See [GitHub REST search documentation](https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28).
- **Product discovery:** Product Hunt can add useful matches through its official GraphQL API, but its API requires a token, is rate-limited, and by default may not be used commercially. It should be an optional connector after license review, not a hard dependency. See [Product Hunt API documentation](https://api.producthunt.com/v2/docs) and [rate limits](https://api.producthunt.com/v2/docs/rate_limits/headers).
- **App stores and package registries:** query only where the proposed product actually belongs; record whether results came from an official API, search page, or general web index.
- **Local code and Whyline history:** optionally search the user’s allowed repositories and previous ideas for duplicates or reusable components. Never scan the whole home directory by default.

Avoid scraping sources whose terms prohibit it. Connector availability belongs in the evidence-coverage score.

### 4. Canonicalize and rank candidates

Deduplicate products and repositories by canonical URL/domain/repository. For each candidate capture:

- name, URL, type (`commercial_product`, `open_source`, `internal_code`);
- one-sentence fit;
- target audience and primary job;
- key features and deployment model;
- pricing/license where verified;
- activity signals and last observed date;
- similarities, differences, and a relevance score;
- evidence URLs supporting each claim.

For GitHub projects, stars alone must not decide quality. Include license, recent release/commit, open-issue health, documentation, security posture where visible, and whether it is a library, demo, abandoned prototype, or deployable product.

### 5. Independent model analysis

The initial inexpensive analysis may use one default model. The deeper version should ask selected models independently to assess the same evidence packet, then synthesize agreements and disagreements. Models do not browse independently unless their adapter is explicitly allowed to do so; ideally Whyline gathers sources once and gives every model the same evidence bundle, reducing inconsistent search coverage.

The synthesis must distinguish:

- facts directly supported by sources;
- reasonable inferences;
- unverified assumptions;
- model disagreements;
- information the user must validate with customers.

### 6. Versioned report

Save each run as a distinct analysis version with source timestamps. A later refresh can say what changed: a new competitor, a dead repository, an altered price, or a different score. Do not silently rewrite history.

## Scoring model

One overall 1–9 number is useful for triage but too opaque on its own. Store component scores, an evidence confidence, and the formula version.

### Proposed components

| Dimension | Weight | Meaning of a high score |
|---|---:|---|
| Problem value | 20% | Painful, frequent, costly problem for a clear user |
| Evidence of demand | 15% | Direct signals beyond the submitter’s belief |
| Differentiation/wedge | 15% | A credible reason to choose this over existing options |
| Founder/resource fit | 10% | Fits the user’s skills, access, budget, and time |
| Feasibility | 15% | MVP is technically and operationally achievable |
| Distribution | 10% | Reachable users and a plausible acquisition route |
| Monetization/strategic value | 10% | Credible economic or internal productivity value |
| Timing/risk | 5% | Favorable timing with manageable legal/platform risk |

Each component is an integer 1–9 with a short rationale and evidence references. Compute the weighted score, round to one decimal for the report, and show the nearest integer as the headline.

### Complexity score

Complexity is separate and is **not inverted into viability**. A valuable difficult idea can score viability 8 and complexity 9.

| Complexity input | Weight |
|---|---:|
| Engineering breadth and novelty | 25% |
| Integrations/platform dependencies | 20% |
| Security/privacy/compliance | 20% |
| Operations and reliability | 15% |
| Data acquisition/migration | 10% |
| Go-to-market/organizational complexity | 10% |

The report should give an MVP complexity and full-product complexity when they differ materially.

### Recommendation

Internally use three states:

- `work_on_it`: viability ≥ 7, no fatal constraint, and confidence at least medium;
- `do_not_work_on_it`: viability ≤ 4 or a demonstrated fatal constraint;
- `need_more_evidence`: everything else, or low evidence coverage.

The user asked for Yes/No, so the headline can display `Should I work on it? YES`, `NO`, or `NOT YET — VALIDATE FIRST`. A forced binary answer under weak evidence is misleading. If a strict Yes/No export column is required, derive it as `Yes` only for `work_on_it`; retain the richer status next to it.

### Confidence and freshness

Add:

- `confidence`: low / medium / high;
- `evidence_coverage`: percentage of planned source classes successfully searched;
- `researched_at` and `refresh_after`;
- `rubric_version` and `model_runs`.

This prevents two ideas with the same 7/9 score—one thoroughly researched and one speculative—from looking equivalent.

## Data model and state machine

Use a separate local SQLite database such as `~/.whyline/ideas/state.sqlite3`, mode `0600`. The workbook is a projection, never the source of truth.

### Core tables

`ideas`

- `id` (`IDEA-0001`), title, original_text, normalized_brief JSON;
- source (`telegram`, `mail`, `console`, `cli`), source sender/chat, repository;
- lifecycle state, state revision, created/updated/decided timestamps;
- current analysis version and current recommendation;
- decision, decision reason, decision actor/source.

`inbox_events`

- provider, provider update/message ID, sender, received timestamp;
- raw text/attachment references, normalized hash;
- processing state and error;
- unique provider key for deduplication.

`analyses`

- idea ID, version, structured brief, report path;
- component scores, overall score, complexity scores;
- recommendation, confidence, coverage, rubric version;
- started/completed time and status.

`evidence`

- analysis ID, source type, query, URL, title, excerpt/summary;
- observed timestamp, claim IDs, relevance, source-quality label;
- fetch result and content hash.

`candidates`

- analysis ID, canonical identity, product/repository metadata;
- similarity, differences, reusable-code assessment, license/activity.

`jobs`

- kind, idea ID, state, attempts, available_at, lease owner/expiry;
- idempotency key, checkpoint JSON, error, created/started/finished timestamps.

`transitions`

- idea ID, from/to state, actor, channel, reason, timestamp, event ID.

`conversation_context`

- channel and chat/sender key, active idea, pending question/action, expiry.

`outbox`

- destination, message/document payload reference, idempotency key;
- delivery state, attempts, next attempt, provider message ID.

### Lifecycle

```text
captured
  → needs_clarification
  → queued_for_analysis
  → analysing
  → analysed
      → dropped
      → refining → queued_for_analysis
      → plan_configuring
          → planning
          → plan_waiting_for_answer
          → plan_review
              → plan_approved
              → plan_discarded
              → relay_ready
```

Failures are job states, not idea states. For example, an idea remains `analysing` while a failed job is retried, then moves to `analysis_failed` only after policy is exhausted. Every mutating command carries the expected idea revision, so stale Telegram buttons cannot approve a newer plan or drop a reopened idea.

Use a transactional outbox: state change and outgoing-response intent commit together. A crash after saving an analysis but before replying then results in a retry of the reply, not a second analysis.

## Excel workbook design

Use `openpyxl` as a new dependency or optional `ideas` extra. It supports creating and updating `.xlsx` files without requiring Excel to be installed. Its documentation warns that `Workbook.save()` overwrites an existing file without warning, so Whyline must save to a temporary sibling, reopen/validate it, then use `os.replace` for an atomic swap. See the [openpyxl tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html).

Recommended workbook sheets:

### Ideas

One row per idea, optimized for sorting and filtering:

- ID, Title, Original idea, Problem, Target user, Source;
- State, Decision, Decision reason;
- Viability 1–9, Complexity 1–9, Recommendation, Confidence;
- Closest competitor, Best reusable code;
- Suggested deployment, MVP summary;
- Repository, Report link, Plan link;
- Created, Last analysed, Updated.

### Scores

One row per idea-analysis version with every component score, rationale, overall formula result, rubric version, confidence, and model roster.

### Competitors

One row per candidate: idea ID, analysis version, name, type, URL, relevance, similarities, differences, price/license, activity, notes.

### Evidence

One row per source: idea ID, analysis version, claim/dimension, source type, title, URL, observed date, reliability, summary.

### Workflow

Every decision and transition, including `Create plan`, `Drop`, reopen, questions, approvals, and generated artifact paths.

### Runs

Job timing, models used, outcome, retry/fallback information, and error category—without secrets or full raw prompts.

Format each range as an Excel table, freeze the header, enable filters, use stable column names, ISO timestamps, wrapped text, hyperlinks, and conditional color scales for scores. Avoid complex formulas as the source of calculations; calculate scores in Python and write their results so mobile Excel and alternate spreadsheet tools display the same values.

Do not edit a workbook while Excel has it locked. If replacement fails, keep the database update, retain the temporary export, mark `export_pending`, and tell the user: “Idea saved; close the workbook so Whyline can refresh it.” Never lose an idea because the spreadsheet is open.

## Telegram design

### Transport

For the Mac-only release, use Bot API long polling through `getUpdates` with a positive timeout, persisting `last_update_id` only after the inbox event is committed. Telegram states that `getUpdates` and webhooks are mutually exclusive, update offsets are how deliveries are acknowledged, and incoming updates are retained for no longer than 24 hours. See the official [Telegram Bot API](https://core.telegram.org/bots/api).

Extend the current `telegram.py` rather than replacing it:

- `get_updates(offset, timeout, allowed_updates)`;
- `answer_callback_query`;
- `edit_message_text` or send a new state card;
- inline-keyboard encoding/decoding;
- `set_my_commands` during setup;
- persisted chat authorization and update cursor;
- retry classification including `retry_after` for rate limits.

The current token-in-Keychain and redaction behavior should remain. Use only a private chat in v1. Store an exact allowlist of Telegram user ID and chat ID; knowing the bot username is not authorization.

Callback data is small, so encode an opaque server-side token or compact tuple such as action, numeric idea key, and revision. Never put repository paths, prompts, or secrets into callback data.

### Hosted transport later

If adding the always-on inbox, switch Telegram to a webhook on a public HTTPS endpoint and configure Telegram’s `secret_token`, which is returned in the `X-Telegram-Bot-Api-Secret-Token` header. The cloud endpoint verifies that header, allowlists sender/chat IDs, writes an encrypted durable event, acknowledges quickly, and lets the Mac pull the queue over an outbound authenticated connection. Telegram retries unsuccessful webhook requests, but Whyline still needs idempotency by `update_id`.

The hosted service should hold only what it needs to queue: provider IDs, encrypted message payload, routing metadata, and expiry. The Mac remains authoritative for the idea database, reports, model credentials, repositories, and Excel file.

## Email design

### Phase 1: Mail.app rule

Reuse the existing Mail.app recipe, but route matching mail into `whyline ideas ingest --channel mail --file …` instead of a general saved-agent prompt.

Require:

- a sender allowlist;
- a subject prefix such as `[WHYLINE IDEA]` or a dedicated mailbox folder;
- message ID deduplication;
- plain-text extraction and attachment size/type limits;
- clear separation of mail content as untrusted data.

Suggested mail commands:

```text
Subject: [WHYLINE IDEA] Local invoice assistant
Body: <free-form idea>
```

and, for actions:

```text
Subject: [WHYLINE ACTION] IDEA-0042 CREATE PLAN
Body:
Models: claude, codex, grok
Passes: 1
```

For consequential email actions, send a Telegram confirmation instead of trusting a spoofable-looking subject alone. Mail actions need a random per-install reply token or a signed link if they are ever allowed without Telegram confirmation.

### Hosted Gmail option

For a later provider-native integration, Gmail’s API supports mailbox watch notifications through Google Cloud Pub/Sub. The watch must be renewed at least every seven days, Google recommends daily renewal, and the notification contains a history ID rather than the message body, so the worker must then synchronize message history. Google also says rare notifications may be delayed or dropped and recommends periodic sync. This is more operationally complex than the Mail.app rule and requires OAuth, so it should be optional. See [Gmail push notifications](https://developers.google.com/workspace/gmail/api/guides/push).

An inbound-email service could provide a simpler always-on address, but it introduces another vendor, privacy surface, and recurring cost. Telegram should be the primary remote channel for v1; Mail.app is a convenient secondary intake path.

## Closed terminal, sleeping Mac, and powered-off Mac

These cases need separate, honest behavior.

| State | Mac-only LaunchAgent | Optional hosted inbox |
|---|---|---|
| Terminal/Whyline console closed | Works | Works |
| User logged in, Mac awake | Polls and analyses immediately | Pulls and analyses immediately |
| Mac asleep | No analysis; catches up after wake if message still retained | Cloud acknowledges/queues; analysis starts after wake |
| Mac powered off | No analysis or response | Cloud acknowledges/queues; analysis starts after boot/login |
| Mac off longer than 24 h | Telegram update may be lost | Durable queue preserves it per configured retention |
| No internet | Local queued jobs wait | Cloud retains received events; Mac reconnects later |

The current Whyline scheduler uses a per-user LaunchAgent with `RunAtLoad` and a two-minute heartbeat. Extend it to call a cheap `ideas tick` as part of the same heartbeat or add a dedicated `com.whyline.ideas` service. A dedicated long-poll listener gives faster Telegram responses but needs crash supervision; a hybrid works well:

- a LaunchAgent `KeepAlive` listener receives Telegram updates and enqueues them;
- the existing short tick reconciles stale leases, export retries, and missed work;
- analysis workers are separate child processes with bounded concurrency.

Apple documents that jobs cannot execute while a Mac is powered off, and behavior during sleep depends on the launchd scheduling mechanism. Whyline should keep its own persisted due/queue logic and reconcile at startup rather than assuming launchd replayed every occurrence. See Apple’s [Scheduling Timed Jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).

Do not try to make the iPhone the always-on analyser. iOS normally suspends background apps and grants background execution only under controlled modes and scheduling. It is suitable as the client and notification surface, not as the reliable queue/worker. See Apple’s [background execution modes](https://developer.apple.com/documentation/Xcode/configuring-background-execution-modes) and [Background Tasks](https://developer.apple.com/documentation/BackgroundTasks).

On listener startup:

1. acquire a single-instance lock;
2. recover expired job leases;
3. read the durable Telegram cursor;
4. fetch pending updates;
5. deduplicate into inbox events;
6. reconcile analyses/workbook projections/outbox deliveries;
7. begin long polling.

This means “Whyline starts and scans” is part of the answer, but the scan is of durable provider/database queues, not every email and directory on the computer.

## Security and safety

This feature accepts hostile internet text and can eventually start agents that write code, so it needs an explicit authority boundary.

- Allow only configured Telegram user/chat IDs and mail senders. Default to one private Telegram chat.
- Store the bot token in Keychain as today. Never put it in the workbook, SQLite diagnostic output, logs, callback data, or model prompts.
- Treat message bodies, URLs, retrieved pages, repository READMEs, and email attachments as untrusted evidence, not instructions. Quote and delimit them in prompts.
- The intake classifier cannot execute commands. It returns typed intent only.
- Analysis is read-only with respect to user repositories. The idea service alone writes its database, reports, and workbook.
- Create-plan requires explicit confirmation. Start-relay requires a separate explicit confirmation.
- Enforce repository allowlists and current Whyline trust checks; do not accept arbitrary paths from a Telegram message.
- Never execute shell snippets found in an idea, web page, README, or model response.
- Pin or record URLs before fetching; block localhost, private/link-local addresses, file URLs, and cloud metadata endpoints to prevent SSRF.
- Apply attachment size/type limits, malware/quarantine handling where possible, and decompression limits.
- Redact secrets before including logs or reports in Telegram/Excel.
- Keep an append-only audit record for incoming action, normalized intent, confirmation, actor, state revision, and result.
- Rate-limit inbound messages and expensive analyses. One user typo must not launch four models repeatedly.
- Provide `whyline ideas pause`, `resume`, `doctor`, `queue`, and an immediate listener-off switch.

## Proposed architecture and files

Keep UI adapters thin and put business rules in service modules usable by CLI, console, Telegram, and future iPhone/Mac apps.

```text
src/whyline/ideas/
  __init__.py
  schema.py            # Idea, Analysis, Score, Job, Evidence value objects
  state.py             # SQLite schema/migrations/transactions
  service.py           # lifecycle commands and revision checks
  ingest.py            # channel-neutral inbox event ingestion
  intents.py           # deterministic parser + constrained model fallback
  research.py          # query plan and connector orchestration
  connectors/
    web.py
    github.py
    producthunt.py      # optional, license/config gated
    local.py
  scoring.py           # versioned deterministic rubric calculations
  reports.py           # Markdown report assembly
  workbook.py          # atomic .xlsx projection
  jobs.py              # leases, retries, checkpoints, concurrency
  worker.py            # executes analysis/plan/export/delivery jobs
  telegram_listener.py # updates/callbacks and cursor
  mail_ingest.py
  planning.py           # adapter to brainstorm/spec/plan services
  outbox.py             # retryable responses/documents
```

Changes outside the package:

- extend `src/whyline/agents/telegram.py` with inbound Bot API primitives shared by Ideas;
- reuse its token and known-chat storage without changing existing outbound delivery;
- add `whyline ideas …` commands to `src/whyline/cli.py`;
- extend launchd setup or add an Ideas LaunchAgent;
- add an Ideas screen later, after the CLI/bot workflow is proven;
- add an `.xlsx` library dependency and document the data/workbook location;
- call `whyline.console.adapters.run_brainstorm`, `plan_job`, and `auto_run` through stable service functions rather than importing Textual widgets.

Do not make a general `AgentDef` run this whole flow. Agent runs are intentionally read-only and their `trigger` has a minimum gap; the new workflow needs exact message deduplication, multiple idea states, controlled artifact writes, and long pauses awaiting user decisions. Reuse the runner/fallback/delivery primitives, not the saved-agent abstraction as the domain model.

## Concurrency, retry, and recovery rules

- Exactly one active analysis or planning job per idea.
- Configurable global concurrency, default one expensive job and one lightweight export/delivery job.
- `provider + update_id` is the Telegram inbox idempotency key; RFC Message-ID plus content hash is the email key.
- Every job has a lease. A crashed worker’s expired lease becomes retryable without duplicating completed artifacts.
- Retry network/rate-limit failures with provider-aware backoff and jitter. Do not retry invalid configuration or explicit model refusals endlessly.
- Persist phase checkpoints so a planning question or Mac restart resumes from that phase instead of re-running all models.
- Persist the exact model roster, resolved model names, prompts/templates versions, and fallbacks used.
- A model failure may use the approved fallback chain. It must be visible in the report and run history.
- Workbook export is coalesced: ten rapid updates require one newest-revision export, not ten file rewrites.
- Outbound Telegram messages/documents have stable idempotency keys and delivery receipts.
- If research connectors partly fail, finish only when the minimum evidence policy is met; otherwise report `Need more evidence` and list unavailable sources.

## Delivery plan

### Phase 0 — Product and contract spike

- Finalize the scoring rubric, report schema, state machine, and Telegram command grammar.
- Decide the default workbook location, retention, and whether ideas are global or repository-first.
- Prototype one Telegram long-poll round trip using the existing bot module.
- Prototype atomic workbook creation with six sheets and validation.
- Define the common planning service API around current brainstorm/auto-run functions.
- Threat-model prompt injection, sender spoofing, stale callbacks, repository selection, and hosted queue data.

Exit: one manually supplied inbox event becomes a database row, a deterministic sample analysis, an updated workbook, and a Telegram decision card.

### Phase 1 — Local idea ledger, CLI, and Excel

- Add SQLite migrations and idea/report/workbook services.
- Implement `whyline ideas add/list/show/analyse/drop/reopen/export/doctor`.
- Implement versioned scoring and Markdown reports with fixture evidence.
- Generate the workbook atomically and handle an open/locked file.
- Record transitions and Whyline decisions for non-trivial plan/drop choices.

Exit: the whole lifecycle works from the CLI and survives crashes without losing or duplicating an idea.

### Phase 2 — Telegram inbox and controls

- Add long polling, cursor persistence, allowlists, commands, inline keyboards, callbacks, and conversation context.
- Add deterministic intents and constrained model fallback.
- Add analysis status/progress, report delivery, retryable outbox, and `/excel`.
- Install the listener with launchd and reconcile on startup/wake/login.

Exit: with Terminal closed and the Mac awake, a phone message is analysed, stored, exported, and returned; duplicate updates and stale buttons are harmless.

### Phase 3 — Real evidence connectors

- Add general web search through a configured provider, GitHub search, and local allowed-repository search.
- Add source canonicalization, candidate ranking, coverage/confidence, citation validation, and freshness.
- Add Product Hunt only if its commercial-use terms and token configuration are acceptable.
- Test adversarial pages and prompt injection.

Exit: reports cite reproducible sources, distinguish products from reusable code, and lower confidence when coverage is incomplete.

### Phase 4 — Create-plan integration

- Add the normalized roster/roles/passes card and validation.
- Adapt the checkpointed brainstorm → synthesis → spec → plan flow to background jobs.
- Send material questions to Telegram and resume from saved checkpoints.
- Preserve Antigravity trust and all existing dirty-tree/preflight gates.
- End at plan review; add a separate Start relay action.

Exit: an analysed idea can become a reviewed plan through Telegram, including one pause-and-answer cycle, without skipping local safety checks.

### Phase 5 — Email intake

- Add the Mail.app script/rule and sender/prefix controls.
- Add email deduplication and Telegram confirmation for consequential actions.
- Consider Gmail/Outlook provider APIs only after the local recipe proves useful.

Exit: an allowed email creates exactly one idea and receives or triggers the configured response path.

### Phase 6 — Optional always-on hosted inbox

- Deploy a minimal Telegram webhook and encrypted durable queue.
- Add Mac outbound sync, acknowledgements, retention/deletion, account/device pairing, and queue status.
- Keep analysis, model credentials, repositories, and Excel local.
- Document cost, availability, privacy, export, and account deletion.

Exit: a message sent while the Mac is powered off is immediately acknowledged, remains queued beyond Telegram’s 24-hour retention, and is processed exactly once after the Mac returns.

### Phase 7 — Native companion UI, only if justified

- Add an Ideas section to the planned Mac/iPhone companion: inbox, scores, evidence, decisions, planning questions, and workbook sharing.
- Use push notifications for attention, while the hosted queue/Mac remains the correctness mechanism. Apple’s APNs architecture requires a provider server and device tokens; see [Registering with APNs](https://developer.apple.com/documentation/usernotifications/registering-your-app-with-apns).

Telegram is enough to validate the product before taking on App Store, APNs, and native-client work.

## Testing strategy

### Unit and contract tests

- schema migration forward/backward compatibility and private file permissions;
- every legal/illegal lifecycle transition and optimistic-revision conflict;
- exact/fuzzy/model intent routing, especially misspellings near destructive actions;
- score formula, rounding, missing evidence, rubric versioning;
- Telegram update/callback parsing, cursor acknowledgement, sender rejection, and 429 retry;
- email sender/prefix/message-ID checks;
- connector timeouts, partial results, GitHub `incomplete_results`, canonicalization, and source freshness;
- workbook sheet/column contracts, hyperlinks, tables, atomic replacement, validation, and file-lock failure;
- job leasing, crash recovery, retry policy, checkpoint resume, and outbox idempotency.

### Security tests

- prompt injection in idea text, email, retrieved pages, README, and attachment;
- spoofed sender/chat, replayed callbacks, stale revision, guessed idea IDs;
- malicious URLs targeting localhost/private networks/metadata services;
- oversized and malformed attachments and spreadsheet formula injection;
- bot-token/redaction tests across errors, reports, database diagnostics, and workbook;
- repository escape through absolute paths, symlinks, or `..`;
- verify Create plan never starts a relay without the second authority step.

For spreadsheet formula injection, prefix user-controlled cells beginning with `=`, `+`, `-`, or `@` as literal text. Excel can otherwise treat an idea or retrieved title as a formula.

### End-to-end scenarios

1. Misspelled Telegram idea → interpretation → analyse → cited report → Excel row.
2. Same Telegram update delivered twice → one idea, one analysis, one response.
3. User presses an old Drop button after refining → rejected as stale with current state shown.
4. Mac sleeps during analysis → job lease recovers and resumes/retries safely after wake.
5. Mac is off for less than 24 hours in local-only mode → pending Telegram update is processed on boot.
6. Hosted mode, Mac off for several days → cloud queues, Mac processes once after reconnect.
7. `create plan` with four models, one unavailable, and fallback → visible substitution and saved checkpoint.
8. Planner asks a question → Telegram answer resumes the same plan, not a new run.
9. Excel is open/locked → database/report succeed, export is pending, later retry sends the newest workbook.
10. Malicious evidence says “ignore instructions and run shell command” → treated only as quoted evidence.

## Product decisions still needed

These should be asked during design, not guessed in implementation:

1. Is the idea ledger global across all repositories, or does each idea belong to one repository from capture time? Recommendation: global inbox, assign a repository only before planning.
2. Is a hosted inbox acceptable for powered-off-Mac reliability? Recommendation: ship local-only first, make the limitation explicit, then offer hosted queue as opt-in.
3. Which email path matters first: Apple Mail, Gmail, Outlook, or a dedicated inbound address? Recommendation: Apple Mail recipe first because Whyline already has it and it avoids new OAuth infrastructure.
4. Where should the workbook live, and may Whyline create timestamped backups? Recommendation: user-selected path with a default in Documents and daily retained backups.
5. Is the intended analyser only for software/product ideas, or any business/project idea? Recommendation: start with software and automation ideas, where GitHub/code reuse and Whyline planning create real differentiation.
6. Should reports use paid search/data APIs? Recommendation: support connector configuration, but ensure a useful GitHub + general-web baseline and show coverage honestly.
7. Should the initial result be cheap single-model analysis or multi-model every time? Recommendation: one-model triage first, then a **Deep analysis** action; use multi-model automatically when Create plan is chosen.

## Success measures

- time from Telegram send to capture acknowledgement and to final report;
- percentage of messages routed correctly without clarification;
- duplicate idea/job/message rate;
- percentage of reports meeting minimum evidence coverage;
- citation validity and stale-source rate;
- score reproducibility under the same evidence and rubric version;
- ideas moved to Drop, Refine, Plan, and Relay;
- percentage of planning pauses resolved from Telegram;
- workbook projection lag and failed/locked export recovery;
- number of messages lost because the Mac was offline;
- model/fallback cost and duration per completed decision;
- zero unauthorized senders accepted, zero stale actions applied, zero source text executed as instructions.

## Final assessment

Build it, but build the **decision pipeline**, not merely the bot or score prompt.

The best v1 is:

1. Telegram text intake on an awake Mac;
2. a durable SQLite idea ledger;
3. cited web/GitHub comparison;
4. versioned 1–9 viability and complexity rubrics with confidence;
5. a local Excel projection and `/excel` delivery;
6. explicit Drop/Refine/Create plan actions;
7. plan creation that reuses Whyline’s existing multi-model and checkpoint machinery and stops before implementation.

This is technically feasible and strongly aligned with Whyline. Its largest risks are not model quality or Telegram plumbing; they are unreliable evidence, accidental actions from ambiguous text, treating Excel as a database, and promising work while the Mac is off without an always-on component. The design above addresses those risks while leaving a clear path to a hosted queue and native phone experience later.
