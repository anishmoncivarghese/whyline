# Brainstorm: Now I am thinking of creating an analayser say I send an email out, or an telegram bot now when the i type somthing the bot picks up and then anlayse the idea and thn say tell me is there any existing applictaion or code that performs the same task, compares it wih avaiable resource and is it useful to create the this, where to deploy and rate the idea 1-9 with 1 being lowest and 9 hightes., complexity 1-9, should I work on it Yes, No , and so on , .Alsoall the idea needs to be say saved in Excel file on my computer . now once the initial nalysis is completed by brainstorming then send initial report based on the reposne user can then tell creat plan or drop , plan dropped it updated in excel plan is dropped and it has all the information, create plan then it starts brainstorming and work on the specs and plan, now before brainstorming say now user send messge in teklegram create plan and then add say models to be used for brainstorming like Claude, Codex, Antigravity and grok  and back up Claude  and pass 1 somthing like that so it automatcially sets the brainstorming set up and add the prompts . Now we need to integrated into whylien so understand how do to it, so the rsponse should be Plan  Model  Claude, Codex, Antigravity Grok back up Claude pass 1, now when you send message by teleagram give placholders which can help useers another thing, is now use the default model to catch it so that in case of any slight change or spelling mistake model can make the correction, Also anotehr thing is if say whyline is not runnning in terminal or say computer is off, how cna it run then is it when whyline starts it scans and does it or any other method, another things excel keeps on updating with the idea, i can sayt send an email and excel file is sent to telegram , updated excel with all the idea,

## Codex

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
