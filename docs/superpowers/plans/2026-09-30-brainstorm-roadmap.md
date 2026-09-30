# Brainstorm Roadmap Plan

**Source:** `docs/brainstorm/what-further-udpates-can-help-whyline.md` (final
synthesis by Claude over independent research and review passes from Claude,
Codex and Antigravity, 2026-09-30).

**Principle carried through every item:** never let suggestive state (a clean
tree, an approved-looking handoff, an installed-but-unverified hook) imply
more certainty than has been proven. Inference stays visibly inference.

**Order (user's choice):** 2, 1, 3, 4, 5, 6. Each item is planned in detail
here, implemented test-first, and released on its own (GitHub + PyPI) before
the next starts.

| Item | Release | Status |
|------|---------|--------|
| 2. Stale ownership and handoffs | 0.3.20 | released |
| 1. Exact commit provenance | 0.3.21 | released |
| 3. Decision lifecycle + `whyline decisions` | 0.3.22 | released |
| 4. Ledger read path + prompt retention | 0.3.23 | released |
| 5. Rename-aware relevance + `explain --diff` | 0.3.24 | released |
| 6. Antigravity hooks + `whyline doctor` | 0.3.25 | next |

---

## Item 2 — Stale ownership and handoffs (0.3.20)

**Measured defect:** this repository's `.whyline/ownership.json` holds 25
claims from 2026-09-27/28, none ever released, and `active-handoff.json` is an
"approved" FC-3 handoff at `eadabbc`, many commits behind HEAD. Every
`whyline sync` presents all of it as current, and FC-3 even becomes the
default task that narrows decision selection.

**Compatibility constraint:** whyline-relay reads `active-handoff.json`
directly (`whyline_relay/handoff.py`) and routes on `id`, `task`, `to_actor`,
`status`. Nothing here may change those fields' meaning.

### Tasks

- [x] **2.1 Claim leases.** `claim` records `expires_at` = now + TTL
  (default 72 h; `whyline claim … --ttl HOURS`). Claims without `expires_at`
  (every claim written before this release) expire 72 h after `claimed_at`.
  *Added during implementation:* a claim is also stale once its task has a
  terminal-status handoff (or `handoff close`) recorded after the claim --
  on this repo that retired 24 of 25 claims that the 72 h lease alone would
  not have touched yet (they were 1-2 days old, their tasks long approved).
  Re-claiming the same task/actor renews the lease (existing replace
  behavior). `ownership.split(claims, now)` → (active, stale).
- [x] **2.2 Stale claims stay inspectable, stop warning.** Overlap
  detection runs on active claims only. `sync` lists active claims and adds
  one line for stale ones with the command to clear them; `sync --json`
  carries `ownership.stale`. `status` reports active and stale counts.
- [x] **2.3 Release forms.** `whyline release TASK --actor A` (unchanged),
  `whyline release TASK` (every actor's claim on the task),
  `whyline release --stale`, `whyline release --all`. Reports how many
  claims were released.
- [x] **2.4 `whyline handoff close [--status completed|cancelled]
  [--summary …]`.** Adds `closed: true`, `closed_at`, `closed_status` to
  `active-handoff.json` (leaving `id`/`status`/`to_actor` untouched for the
  relay) and appends a `HandoffClosed` event to the ledger. Refuses cleanly
  when there is no active handoff or it is already closed.
- [x] **2.5 Settled handoffs.** `handoff.settled(root, record)` is true when
  the record is closed, or its status is terminal (approved, completed,
  complete, done, merged, cancelled, canceled, closed) *and* its
  `current_commit` is a strict ancestor of HEAD. `sync` then shows one
  "Last handoff" line (task, status, commit, commits behind) instead of the
  active block, and no longer uses that handoff's task/files to narrow or
  rank decisions. `sync --json` moves it to `last_handoff`; an explicit
  `--task` still works as before.
- [x] **2.6 Instructions.** The installed AGENTS.md block mentions
  `whyline handoff close` and `whyline release`.

### Tests

Unit tests per task (lease expiry incl. legacy claims, split, conflicts on
active only, each release form, close idempotency and relay-field
preservation, settled detection for closed / terminal-and-behind /
terminal-at-HEAD / non-terminal / unknown commit), sync text and JSON output,
CLI parsing including `handoff close` vs a normal handoff.

### Release

Full suite, decisions via `whyline note`, 0.3.20 notes, tag, CI on six
runners, PyPI, local upgrade.

---

## Item 1 — Exact commit provenance (0.3.21)

**Measured defect:** `decisions.md` (the committed store) records only
`## YYYY-MM-DD`, so on a fresh clone -- where the gitignored ledger is
absent -- `explain` caps at MEDIUM even for a single matching decision
(`resolve._has_day_precision`). Nothing ties a decision to a commit except
time windows, which can misattribute.

**Rule (from the brainstorm):** exactness is earned by explicit binding,
never inferred from a clean tree or from HEAD.

### Tasks

- [x] **1.1 Exact metadata in decisions.md.** Every new entry gets a second
  comment after `<!-- whyline-event: ID -->`:
  `<!-- whyline-meta: {"v":1,"ts":"<full ISO>","commit":"<sha>"} -->`
  (`commit` only when bound). A separate comment, not an extension of the
  event comment: older whyline versions read the whole `whyline-event`
  comment as the id, so extending it would corrupt ids and duplicate every
  entry for anyone not yet upgraded. `parse_entries` uses the meta `ts`
  when present and valid (full precision), else the heading day as before.
- [x] **1.2 `whyline note --commit SHA`.** Resolved with
  `git rev-parse --verify SHA^{commit}`; the full sha is stored in the
  ledger event and the meta comment. Unknown sha → error, nothing recorded.
  No automatic binding to HEAD.
- [x] **1.3 `whyline attach ID --commit SHA`.** Binds an existing decision
  (id or unique id prefix) after its code lands. Recorded as a
  `NoteAttached` ledger event and as an append-only
  `<!-- whyline-attach: {"v":1,"note":…,"commit":…,"ts":…} -->` line in
  decisions.md, so it survives a clone. `history.load` applies attachments
  (latest wins). Ambiguous or unknown id → error.
- [x] **1.4 `explain` prefers binding.** For a blamed line: notes bound to
  exactly the blamed commit (mentioning the path, or with no files) →
  HIGH, "bound to the commit that wrote this line", regardless of
  timestamp precision. Notes bound to a *different* commit are excluded
  from the time-window heuristic (they can still be reported by the
  "recorded earlier, since moved" fallback). Unbound notes behave as today.
- [x] **1.5 Show it.** brief/sync decision lines add `commit: <7 chars>`
  when bound; `explain --json` notes carry `commit`.

### Tests

Render/parse round trip with and without meta (and a pre-0.3.21 entry);
old-parser compatibility (the event id still parses); `note --commit`
valid/unknown/HEAD-by-name; `attach` by prefix, ambiguous, unknown, and
from a fresh clone (ledger deleted); explain HIGH via binding on a clone,
bound-elsewhere exclusion, mixed bound/unbound; brief/sync commit display.

---

## Item 3 — Decision lifecycle and a query surface (0.3.22)

**Defect:** a decision can never stop being current. A replaced or plainly
wrong decision keeps being handed to every agent by `brief`/`sync` as live
reasoning, and several matching decisions for one commit leave `explain`
at an ambiguous MEDIUM even when only one of them still stands. There is
also no way to list or search decisions short of reading `decisions.md`.

### Tasks

- [x] **3.1 Supersede.** `whyline note … --supersedes ID` (repeatable; id
  or unique prefix; must exist). Stored as full ids on the new note, in the
  meta comment, and as a visible `**Supersedes:**` line.
- [x] **3.2 Retract.** `whyline retract ID --because TEXT` records a
  `Retraction` event and a visible `## <day> — Retracted: <decision>`
  entry (with meta `retracts`) in decisions.md. Retraction entries are not
  decisions: history keeps them apart.
- [x] **3.3 Lifecycle.** `history.load` marks every note `lifecycle`:
  `active`, `superseded` (+ `superseded_by`) or `retracted`
  (+ `retracted_because`, `retracted_by`). A retracted note's own
  `supersedes` no longer take effect.
- [x] **3.4 Current reasoning only.** `brief`/`sync` select from active
  notes; "N recorded in total" still counts all.
- [x] **3.5 Explain.** When several decisions match a commit and exactly one
  is active, that one wins at HIGH ("…; N superseded or retracted"). A
  sole match that is superseded or retracted is still shown (it is why the
  line was written) with its status in the text and JSON.
- [x] **3.6 Review evidence on `note`.** `--verdict TEXT`,
  `--reviewed-commit SHA` (resolved), `--test "cmd: result"` (repeatable).
  Visible `**Verdict:**` / `**Reviewed commit:**` / `**Test:**` lines,
  parsed back; shown by brief/sync and `decisions show`.
- [x] **3.7 `whyline decisions`.** `list` (default; `--task`, `--file`,
  `--all`, `--limit`, `--json`), `search TEXT` (case-insensitive over
  decision, because, rejected options, files, task; `--all`, `--json`),
  `show ID` (full record incl. lifecycle and binding; `--json`). Named
  `decisions`, not `log`, which would collide with `git log` and
  `whyline timeline`.

### Tests

Supersede/retract recording and round trip from a clone; lifecycle
computation incl. retracted superseder; brief/sync exclusion; explain
disambiguation and status display; review fields round trip; each
`decisions` subcommand, filters, `--all`, `--json`, unknown/ambiguous ids.

---

## Item 4 — Ledger read path and prompt retention (0.3.23)

**Measured (this repository, 2026-09-30):** `ledger.jsonl` is 2.1 MB /
2,123 events; `Instruction` events (raw prompt bodies) are 918 events and
1.72 MB -- 81% of the file. Nothing reads prompt text except
`timeline --include-prompts`. Full parse: 16 ms now; 85 ms at 10x (21 MB),
452 ms at 50x (107 MB). Skipping `Instruction`/`FileTouched` lines before
JSON-decoding them: 29 ms / 145 ms. Conclusion, as the brainstorm asked:
no index or database is justified; skip what a command doesn't need,
store less, and allow pruning.

### Tasks

- [x] **4.1 Prompt capture policy.** `metadata` (default: no text, only
  `chars` and `sha256`), `redacted` (text with secret-shaped substrings
  masked, best effort, marked `redacted: true`), or `full` (as before).
  Stored in `.whyline/config.json`, which is local and gitignored (added to
  `.whyline/.gitignore` on write, so existing repositories are covered).
  `whyline ledger policy [metadata|redacted|full]` shows or sets it. The
  hook applies it at capture time.
- [x] **4.2 `whyline ledger prune --older-than DAYS [--dry-run]`.** Removes
  `Instruction`, `FileTouched`, `SessionStarted`, `SessionEnded` events
  older than DAYS. Never removes decisions, handoffs, closes, attachments
  or retractions. Rewrite is atomic and picks up lines appended by hooks
  during the rewrite. *Changed during implementation:* `ledger.append` now
  takes the ledger's lock (about 0.1 ms per event), because copying late
  lines alone still left an instant before the file swap in which a hook's
  event could be lost; the late-line copy remains for unlocked writers
  such as an older installed hook.
- [x] **4.3 `whyline ledger scrub-prompts [--dry-run]`.** Applies the
  current policy to prompts already recorded (e.g. after switching from
  the old implicit `full` to `metadata`).
- [x] **4.4 `whyline ledger stats`.** Size, events per type, prompt bytes,
  current policy.
- [x] **4.5 Lighter read path.** `ledger.read_all(..., skip_types=…)`
  skips lines by their serialized `"type":"…"` before decoding;
  `history.load(root, mechanical=False)` uses it. `brief`, `sync`,
  `decisions`, `attach`, `retract` load without mechanical events;
  `status`, `explain`, `timeline` keep the full read.
- [x] **4.6 Timeline.** `--include-prompts` says when a prompt was not
  captured (and under which policy) instead of printing nothing.

### Tests

Hook capture under each policy; secret masking samples; config read/write
and gitignore entry; prune keeps durable types and honors the cut-off and
`--dry-run`; prune/scrub preserve lines appended mid-rewrite; stats
output; skip_types equivalence with a full read for the kept types (incl.
a note whose text mentions "Instruction"); history.load mechanical=False
leaves notes/handoff state identical; timeline wording.

---

## Item 5 — Rename-aware relevance and diff-wide explain (0.3.24)

**Defect:** decisions record paths as they were. After `git mv`, `explain`
(`resolve._mentions`), `brief/sync --file` and `decisions --file` compare
literal paths, so every decision recorded under the old name silently stops
matching. And `explain` answers one line at a time, which is no help when
reviewing a change.

### Tasks

- [x] **5.1 `gitq.historical_paths(root, path)`** -- every name the file has
  had (`git log --follow --name-only`), current name first. Empty history
  (untracked/new) → just the path.
- [x] **5.2 Rename-aware matching.** `explain` matches notes and mechanical
  events against all historical names; a note matched only through an old
  name carries `matched_path`, shown as "(recorded as old/name.py)" so the
  inference stays visible. `brief --file`, `sync --file` and
  `decisions list --file` expand requested files the same way. (Rank hints
  from the dirty tree are not expanded: one `git log` per dirty file on
  every `sync` is not worth it for a ranking hint.)
- [x] **5.3 `gitq.blame_range(root, path, start, end, rev=None)`** -- one
  porcelain blame for a range, parsed per line.
- [x] **5.4 `resolve.explain_blamed(...)`** -- the line-level rules of
  `explain`, factored so a caller with a preloaded history and a blame can
  reuse them; `explain` itself is unchanged in behavior.
- [x] **5.5 `whyline explain --diff` / `--staged`.** For every changed
  line that existed in HEAD, blame it at HEAD (one blame per hunk) and
  resolve it; lines that are purely new are counted as new. Output groups
  lines by decision (id, decision text, confidence, file:line ranges) and
  ends with coverage: high / medium / low / unexplained / new. `--json`.
  Deleted files count their removed lines; binary files are skipped.

### Tests

historical_paths across one and two renames; explain HIGH via an old path
with matched_path shown; brief/sync/decisions --file finding old-path
decisions; blame_range against per-line blame; explain_blamed parity with
explain; --diff grouping, coverage counts, new-line counting, --staged vs
working tree, no changes, deleted file, JSON shape.
