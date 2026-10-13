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
