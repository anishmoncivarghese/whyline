# Brainstorm: what further udpates can help whyline

## Final Synthesis

Three independent passes (Claude, Codex, Antigravity), followed by three review
passes reading each other's work, converged on the same diagnosis without
being told to: Whyline's core problem right now is not missing features, it's
that its claims of confidence and currency are weaker than they look.
Timestamps can't prove a decision matches a commit, decisions never expire or
get superseded, ownership and handoff state never expires either, and file
history breaks across renames. All three models found live evidence of this
in the repo itself while writing the brainstorm — `whyline sync` showed a
days-stale "approved" handoff for FC-3 and a stale ownership conflict from
task UCF-1. That's the strongest possible argument for the order below: fix
honesty and staleness before adding surface area.

### Recommended sequence

1. **Exact, honest provenance.** Add `whyline note --commit <sha>` for
   explicit commit binding, plus a pending/`attach` workflow for decisions
   made before the code lands (never auto-bind to `HEAD` just because the
   tree is clean — Codex's objection to Antigravity's original proposal,
   which Antigravity conceded). Store exact timestamp, event ID, and commit
   SHA in a versioned payload inside the existing HTML comment on each
   decision entry (`decisions.py:38`), not a separate companion file — one
   source of truth, backward-compatible parsing for older entries. This is
   the fix for the day-precision truncation that currently caps fresh-clone
   confidence at MEDIUM regardless of evidence quality.

2. **Stop the operational bleed.** Ownership claims (`ownership.py`) and
   handoffs (`handoff.py`) are the same bug in two files: advisory state that
   never expires and keeps injecting itself into every `sync`. Add TTLs and
   `release --stale`/`release --all-for-task` for claims, and explicit
   `handoff close --status` plus auto-suppression once an approved handoff's
   commit is behind HEAD. This is a present, measured defect, not future
   scaling work — fix it early since it's actively degrading context on every
   `sync` call today.

3. **Decision lifecycle and a query surface.** Split supersede (a new
   decision replaces an old one, old one stays as historical rationale) from
   retract (a decision was simply wrong, no replacement) as two verbs, not
   one flag. Ship them alongside a `whyline decisions` command family
   (`list`, `search`, `show <id>`, `--json`) rather than `whyline log`, which
   collides with `git log` and `whyline timeline`. `explain` should prefer an
   active superseding decision when multiple candidates match, resolving
   ambiguous MEDIUM cases back to HIGH. Add review-evidence fields
   (`--verdict`, `--reviewed-commit`, `--test`) directly to `note` rather than
   inventing a parallel `whyline review` command.

4. **Ledger scale and privacy, as one track.** The real cold-start risk is
   `ledger.jsonl`, not `decisions.md` — `history.load()` fully deserializes
   every mechanical event and raw prompt body just to pull out notes. Fix
   the read path (reverse-scan or a lightweight note stream) and the
   retention question (`prompt_capture = metadata|redacted|full`, defaulting
   safely; `ledger prune --older-than`) together, since both touch the same
   file and one motivates the other. Benchmark before reaching for an index
   or database — nothing measured yet justifies one.

5. **Rename-aware relevance and diff-wide explain.** Build a historical-path
   alias set from `git log --follow` (`gitq.historical_paths()`) and use it
   consistently across `explain`/`brief`/`sync`, surfacing the matched alias
   so relevance stays auditable. Then add `whyline explain --diff`/`--staged`,
   grouped by decision ID with a coverage summary (exact/heuristic/
   mechanical-only/unexplained) — this is what turns `explain` from a
   single-line debugging tool into an actual PR review aid, and it's most
   valuable once steps 1 and this alias set both exist.

6. **Ecosystem and diagnostics last.** Antigravity currently has zero
   mechanical hook coverage (no `.agents/hooks.json` install path) despite
   being a first-class runner — close that gap first, since a synthetic hook
   check is meaningless without a real target. Then consolidate all health
   checks (hook config/executable/observed status, ledger policy and size,
   stale ownership/handoffs, decision parseability) into one `whyline doctor`
   command rather than scattered ad hoc checks. Gemini support is reasonable
   but strictly lower priority than any correctness work above.

### Cross-cutting principle

Every item above is in service of one rule the three passes kept re-deriving
independently: Whyline should never let suggestive state (a clean tree, an
approved-looking handoff, an installed-but-unverified hook) imply more
certainty than it has actually proven. Inference must stay visibly inference;
exactness should be earned via explicit binding, not guessed from
correlation. That principle, not any single feature, is the real output of
this brainstorm.

## Claude

# What other updates can be done in Whyline — review pass 1

Having read Codex's and Antigravity's independent passes alongside my own, the
headline result is convergence, not disagreement: all three of us landed on
commit-bound provenance, supersede/retract semantics, stale advisory state, and
rename-aware matching as the load-bearing gaps, arrived at independently from
the same source. That's a stronger signal than any one pass alone. What follows
keeps my original grounding but revises priority and detail where the other two
passes caught something sharper, and pushes back where I think a proposal adds
more machinery than the problem needs.

## 1. Deterministic commit binding for `explain` — converged, strengthen the format

All three passes independently proposed `--commit <sha>` on `whyline note` so
`explain` can match exact SHA before falling back to the epoch-window heuristic
in `resolve.py:70-225`. Codex and Antigravity both caught something I
under-weighted: `decisions.py:38`'s `render_entry` writes only `## YYYY-MM-DD`,
truncating to day precision, so even a same-day note/commit pairing can't be
told apart on a fresh clone where `.whyline/ledger.jsonl` (gitignored) is
absent — `_has_day_precision()` hard-caps confidence at MEDIUM regardless of how
few decisions or commits exist. That's a sharper diagnosis than "the heuristic
is sometimes wrong"; it's "the heuristic can't even reach HIGH from a clone
today." I'd fold the fix in with mine: store the exact timestamp and commit SHA
in the existing HTML comment on the entry (it already carries the event ID),
rather than Codex's suggestion of a separate "committed structured companion
file" — extending one comment is less to keep in sync than a parallel format,
and the parser already has to read that line. Keep backward-compatible parsing
for older entries without the comment.

## 2. Supersede/retract — converged, adopt the sharper two-verb split

I originally proposed a single `--supersedes`. Codex and Antigravity both split
this into `supersede` (a new decision explicitly replaces an old one) and
`retract` (a decision is later found simply wrong, with no replacement) — that
distinction is worth keeping instead of collapsing into one flag, since "why did
this line exist then" and "what rule applies now" need different answers for
each case. `brief`/`sync` should default to current decisions and disclose
superseded ones only when they're the ones explaining an older blamed commit;
`explain` should prefer an active superseding decision when multiple candidates
land in the same commit window, resolving what is currently the MEDIUM-confidence
"several decisions match, ambiguous" branch back to HIGH.

## 3. Ownership *and* handoff staleness — converged, and I was too narrow

I only flagged ownership claims never expiring (`ownership.py:59`,
`conflicts()` at `ownership.py:18-38`). Antigravity's pass caught the same shape
of bug in `handoff.py:66`: an approved/completed handoff sits in
`active-handoff.json` forever and keeps injecting itself into every `sync` as
if still open. I can confirm this isn't theoretical — the `whyline sync` I ran
for this review pass surfaced exactly that: task FC-3, status "approved,"
already committed at `eadabbc` days ago, still presented as the active handoff,
plus a live "1 overlapping ownership claim" warning against an old task. Both
deserve the same fix shape: a TTL/staleness threshold (`claim --ttl`,
`release --stale`, `release --all-for-task` for ownership; `handoff close
--status` and auto-clearing on approval for handoffs), with stale state marked
and excluded from active warnings rather than silently deleted. Same principle,
two files — worth doing together rather than as separate work items.

## 4. Rename-aware matching — converged

`resolve._mentions()` (`resolve.py:64-67`) and `blame_line()`
(`gitq.py:58-85`) match on literal path equality with no `--follow`, while
`commits_touching()` already uses `--follow` for exactly this reason
(`gitq.py:90-92`). All three passes independently found this; Antigravity named
the concrete fix I'd converge on — `gitq.historical_paths()` built from `git log
--follow --name-only`, with the resulting alias set used consistently across
`explain`, `brief`, and `sync`, and the matched historical path surfaced in
output so a reader can see why a decision was included.

## 5. Queryable decision log — converged on need, diverged on shape

All three of us want a query surface beyond token-capped `brief` and
mechanical-only `timeline`; `decisions.parse_entries()` already returns
everything needed (`decisions.py:92-141`). I proposed `whyline log [...]`,
Antigravity proposed the same name and flag shape, Codex proposed a
`whyline decisions` family (`list`/`search`/`show --json`). I'd side with
Codex's grouping here on reflection — `log` reads as a mechanical-ledger name
next to `timeline`, and a `decisions` subcommand family scales better once
supersede/retract (above) needs its own `decisions show <id>` to display a
chain. Linear scan is fine to start; no index until a measured threshold is
crossed, per Codex's note that the README's own 50k-event measurement doesn't
justify one yet.

## 6. Hook health check — my framing was too narrow, broaden it

I proposed a Codex-only `--fire-test-event` because the README singles out
Codex as unverified. Antigravity's pass points out this should be agent-general
(`whyline hook check [--agent]`) rather than Codex-specific, and Codex's own
pass wants it folded into a broader `whyline doctor`. I now agree the broader
framing is right, especially since Antigravity separately notes the project has
zero hook coverage for itself: no `.agents/hooks.json` install path exists, so
any Antigravity-run session produces zero mechanical events today. A synthetic
per-agent hook check only becomes meaningful once there's a real target for it
to check.

## 7. Ledger scale — my diagnosis was on the wrong file

I flagged `decisions.md` needing a rotation story. Antigravity's pass is more
precise: `decisions.md` stays small by comparison; the actual growth risk is
`ledger.jsonl`, which `history.load()` reads and fully deserializes on nearly
every command (`brief`, `sync`, `explain`, `timeline`, `status`) just to pull
out `events.NOTE`, even though it also carries every `FileTouched` and raw
`Instruction` prompt (`ledger.py:20-38`, `history.py:94-107`). That's the file
that actually threatens the <200ms cold-start budget at scale, not the decision
log. I'd deprioritize my original archive-file proposal for `decisions.md` and
replace it with Antigravity's: reverse-read the ledger only up to the last
known committed decision timestamp when all `brief`/`sync` need is notes, plus
an explicit rotation command for old mechanical events.

## 8. Ledger privacy/retention — a real gap I missed

Codex's pass raised something absent from my list entirely: `ledger.jsonl`
stores every `UserPromptSubmit` body verbatim, and while it's gitignored and
`timeline` redacts by default, nothing stops a secret or sensitive prompt from
living on disk indefinitely. A repo-local `prompt_capture =
metadata|redacted|full` setting (defaulting to metadata for new repos), plus
`whyline ledger prune --older-than` and surfacing capture mode in `status`, is a
reasonable safety addition that's orthogonal to the performance fix above —
worth doing regardless of ledger size, and cheap given the redaction logic
already exists for `timeline`.

## 9. Diff-wide `explain` — converged

Single-line `explain` (`cli.py:358-384`) has no batch mode; all three passes
want `whyline explain --diff`/`--staged`, reusing `gitq.changed_paths()`
(`gitq.py:131-160`) and the existing per-line resolution logic. Codex's addition
of grouping by decision ID (so one decision isn't repeated per changed line) and
a coverage summary (exact/heuristic/mechanical-only/unexplained) is worth
adopting directly — it turns this from "explain, looped" into an actual review
aid. Keep the honesty rule intact: uncommitted or unmatched lines stay
unexplained rather than inheriting a nearby file-level decision.

## 10. Gemini support — still unique to my pass, still low priority

Neither other pass flagged this. `detect_antigravity`/`detect_grok` are already
PATH-only checks (`account.py:97-113`) because those CLIs have no reliable
non-interactive login check; Gemini CLI is the same shape and the console
already treats "installed, greyed out" as first-class UI. I'd leave this as a
same-shape, low-effort addition, but rank it below everything above — it's not
blocking anything the other passes found, unlike the provenance/staleness work.

## Noted but not adopting as-is

Codex's proposal for a dedicated `whyline review` command (verdict/commit/test/
finding as a distinct record from a generic `note`) is interesting but I'm not
convinced it needs new plumbing: a review is already an actor=reviewer note
with `--because` and `--rejected`; the missing piece is probably just a
`--verdict` and `--test` field on the existing `note`/`decisions.py` schema
rather than a parallel command family. Worth revisiting after supersede/retract
(item 2) lands, since both touch the same rendering code.

## Lower-priority / smaller polish

- `ownership.conflicts()` only detects *exact* file-string overlap
  (`ownership.py:24-26`); if a claim is ever extended to accept directories or
  globs, this needs prefix-aware matching or it will silently miss real
  conflicts.
- `note`'s `--rejected "option: why not"` parsing (`events.parse_rejected`,
  `events.py:31-39`) splits on the first `:`, so an option string containing a
  colon (e.g. `"use redis:6379 as cache: too much ops overhead"`) parses wrong
  with no error. Worth a `--rejected-option`/`--rejected-reason` pair as an
  alternative to the single delimited string, or at minimum a warning when the
  option side itself contains a colon.

## Codex

### Review pass 1: revised findings

The strongest result from the combined review is convergence. Claude and
Antigravity independently identified the same load-bearing gaps as my first
pass: commit-bound provenance, decision lifecycle, stale operational state,
rename-aware relevance, searchable history, hook diagnostics, and diff-wide
explanation. That agreement changes the recommendation from a broad feature
list into a narrower hardening program. Antigravity also corrected my scale
focus: the growing `ledger.jsonl`, not the relatively small committed decision
log, is the file most likely to threaten the cold-start budget.

### 1. Make provenance durable and exact

This remains the highest-leverage update. `explain` currently infers a
decision's relationship to a blamed commit through timestamp windows. The
committed Markdown heading keeps only day precision, so a fresh clone without
the gitignored ledger cannot recover the exact timestamp and is structurally
unable to reach high confidence through that path.

Add an optional immutable commit binding and a lossless committed record:

- `whyline note ... --commit <sha>` for a known commit;
- a pending state plus an explicit attach operation for decisions made before
  the code is committed;
- exact timestamp, event ID, files, task, lifecycle links, and commit binding
  in a versioned metadata payload inside the existing decision-entry HTML
  comment;
- backward-compatible parsing of today's display-oriented entries.

Claude's suggestion to extend the existing comment is better than my earlier
allowance for a separate structured companion file: one atomic entry avoids a
second source of truth. I still reject Antigravity's proposed automatic binding
to `HEAD` merely because the tree is clean. Cleanliness does not prove that the
decision describes `HEAD`, and a false exact link is worse than honest
heuristic confidence. `explain` should state whether confidence came from an
exact binding or the timestamp fallback.

Acceptance bar: after a fresh clone with no local ledger, an exactly bound
decision still resolves at high confidence; a pending or ambiguous one does
not.

### 2. Give decisions append-only lifecycle semantics and a query surface

All three passes agree that old and current choices cannot remain peers
forever. Preserve the audit trail with explicit `supersede` and `retract`
events: superseding means a replacement now governs, while retracting means
the old decision was invalid without implying a replacement. `brief` and
`sync` should default to current decisions, whereas `explain` must retain an
old decision when it explains historical code and show the later lifecycle
chain.

The lifecycle work should land with a first-class `whyline decisions` family:

- `list` with task, file, actor, role, status, and date filters;
- `search` across decision, rationale, and rejected alternatives;
- `show <id>` displaying commit bindings and supersede/retract chains;
- stable JSON output for integrations.

I prefer this grouping over `whyline log`, because `log` is easy to confuse
with the mechanical timeline. A linear scan is enough initially; none of the
evidence justifies SQLite or another index yet.

### 3. Close stale ownership and handoff state

This is a present defect, not future polish. The sync run for this review still
reports an approved FC-3 handoff as active even though the checkout has moved
past its recorded commit, plus an overlapping ownership warning among old
claims. Antigravity was right to treat the handoff and ownership files as two
instances of the same lifecycle problem.

Add claim leases (`--ttl`, `renew`, `release --stale`, and task-wide release),
handoff terminal states (`close --status completed|cancelled`), and explicit
archival/clearing. Stale records should remain inspectable but be excluded from
active conflict warnings and default sync context. Closing a handoff may offer
to release its task's claims, but automatic deletion would hide useful
diagnostic history.

Antigravity also found that omitted handoff bases can collapse to
`base == current`. That should become an explicit unknown or use the previous
handoff/current task boundary when reliable. Blindly choosing
`merge-base HEAD origin/main` is unsafe in repositories without that upstream
convention.

### 4. Fix ledger privacy and scale together

My first pass covered retention primarily as a privacy issue. Antigravity's
code-grounded finding is sharper: `history.load()` can deserialize the entire
mixed mechanical ledger merely to recover note events, so high-volume prompts
and file touches eventually tax nearly every command. Meanwhile raw prompt
bodies may persist indefinitely even though timeline output redacts them.

Treat these as one storage-policy track:

- default new repositories to `prompt_capture = metadata`, with explicit
  `redacted` and `full` modes;
- report capture mode, oldest event, size, and retention policy in status;
- add prune/compact or rotation operations for old mechanical events;
- keep committed decision text outside this policy;
- benchmark a reverse-scan, lightweight note stream, or offset cache before
  choosing an index architecture.

The last point matters: the problem is measured full-file work, not proof that
a database is required. Preserve the standard-library and cold-start goals.

### 5. Make relevance rename-aware

Git commit-window lookup follows renames, but note selection still compares
literal paths. Build a conservative historical alias set from Git's detected
rename history and use it consistently in `explain`, `brief`, and `sync`.
Output should name the historical path that matched so relevance remains
auditable. Do not invent aliases from Whyline-side similarity guesses.

### 6. Add diff-wide explanation as the review-facing workflow

All three passes converge here. Add `whyline explain --diff <base>..<head>`
and `--staged`, group results by decision ID, and summarize exact, heuristic,
mechanical-only, and unexplained coverage. Modified and deleted lines should
surface their prior rationale; unmatched or uncommitted lines must stay
unexplained instead of borrowing a nearby file-level decision. Once exact
bindings and rename aliases exist, this becomes a meaningful review tool and a
measurable provenance-coverage signal rather than merely a loop over lines.

### 7. Extend decision records for review evidence before adding a new command

I still think durable review outcomes matter, but Claude's pushback on a
standalone `whyline review` command is persuasive. A review is already a
reviewer-authored decision; the missing structure is verdict, reviewed
commit/range, tests, accepted risks, and material findings. Add those as
optional fields in the same versioned note schema first, and teach
`decisions list/show` to filter and render them. Introduce a dedicated command
only if usage shows that a shorthand improves capture. Do not record every nit.

### 8. Complete hook coverage, then consolidate diagnostics

Antigravity found an ecosystem gap absent from my first pass: it is available
as a runner but lacks the mechanical hook installation and status path used by
the other supported agents. Confirm the actual Antigravity hook contract, then
add installation, payload translation, observation reporting, and tests rather
than assuming that launch support implies capture support.

A synthetic hook check remains useful, but its claim must be precise. It can
prove configuration parses, the executable resolves, payload translation
works, and the ledger is writable. It cannot prove that a vendor invoked the
hook; only a real observed event can. Fold this into an actionable
`whyline doctor` covering decision parseability, writable paths, instruction
freshness, stale operational state, agent configuration, ledger policy/size,
and three distinct hook facts: configured, executable, and observed.

### 9. Lower-priority additions and cautions

- Gemini support is a reasonable same-shape runner/account addition from
  Claude's pass, but it should not outrank correctness for already-supported
  agents.
- Directory or glob ownership claims would require prefix-aware conflict
  checks; exact string overlap is sufficient only while claims remain exact
  files.
- The colon-delimited `--rejected "option: reason"` interface is ambiguous
  when the option itself contains a colon. Structured repeatable option/reason
  arguments are safer than increasingly clever parsing.
- Never silently infer that an approved handoff, clean tree, configured hook,
  or similarly suggestive state proves more than it actually does. Whyline's
  honest-confidence rule should govern operational UX as well as `explain`.

### Recommended sequence

1. Versioned decision metadata, exact commit binding, and compatible parsing.
2. Supersede/retract plus `decisions list/search/show`.
3. Ownership leases and handoff close/archive behavior.
4. Prompt-capture policy and measured ledger fast paths/retention.
5. Rename-aware relevance and diff-wide explanation.
6. Structured review fields and measurement of reviewer capture.
7. Missing agent hook support and consolidated `doctor` diagnostics.

The unifying principle remains local, human-readable, and honest: durable IDs
and explicit lifecycle should support every strong claim, while inference stays
visible as inference.

## Antigravity

### Review pass 1: revised findings & synthesis

Reading Claude's and Codex's reviews against my initial pass demonstrates striking convergence across all three models on Whyline's primary architectural gaps:
1. Commit-bound provenance to replace fragile epoch-window matching,
2. Explicit decision lifecycle semantics (supersede and retract),
3. Operational state accumulation (both ownership claims and active handoffs leaking into `sync`),
4. Rename-aware relevance tracking across file moves,
5. Diff-wide provenance explanation for code reviews, and
6. Missing mechanical hook coverage and health diagnostics.

This review pass incorporates the critiques from Claude and Codex, sharpens the architectural boundaries, concedes on areas where my initial proposals violated Whyline's honest-confidence principle, and produces an integrated, hardened roadmap.

---

### 1. Hardening Provenance: Explicit Commit Binding Without Guessing

My initial proposal suggested auto-binding decisions to `HEAD` when the working tree was clean. Codex offered an essential correction: **cleanliness does not prove that a decision describes `HEAD`**. Guessing creates false exactness, which violates Whyline's foundational honest-confidence principle.

**Revised design:**
- **Explicit binding only**: `whyline note ... --commit <sha>` explicitly links a decision to a commit.
- **Pending & attach workflow**: Decisions made during planning or mid-implementation are recorded without a commit SHA. Provide `whyline attach <decision-id> [--commit <sha>]` (or a Git `post-commit` hook helper) to bind commits once they actually exist.
- **Lossless comment metadata**: Rather than Codex's early idea of a separate structured companion file, converge with Claude and Codex on extending the HTML comment already emitted by `decisions.py:38`:
  `<!-- whyline-event: <uuid> commit: <sha> epoch: <int> -->`
  This preserves human readability in standard Markdown viewers while allowing fresh clones (lacking local `.whyline/ledger.jsonl`) to resolve high confidence without day-precision truncation capping them at `MEDIUM`.
- **Honest resolution tiers**: `resolve.py` checks exact commit bindings first (`HIGH`), falls back to the epoch window (`MEDIUM`), and flags ambiguity explicitly when multiple unrelated decisions fall within the commit window.

---

### 2. Decision Lifecycle & The `whyline decisions` Query Surface

All three passes recognized that decisions cannot remain flat and uncoordinated forever.

**Revised design:**
- **Two-verb lifecycle (`supersede` vs `retract`)**: Adopt the clean split between:
  - `--supersedes <id>`: A new decision replaces an older one; the older decision remains historical rationale for past commits, but the new decision governs future work.
  - `whyline retract <id> --because <reason>`: A past decision was erroneous or abandoned without a direct successor.
- **Unified command family: `whyline decisions`**: I initially proposed `whyline log`. I concede to Codex and Claude: `log` easily collides conceptually with `git log` and `whyline timeline`. Instead, introduce `whyline decisions`:
  - `whyline decisions list [--task <t>] [--actor <a>] [--file <f>] [--status active|superseded|retracted]`: Filtered listing.
  - `whyline decisions search <query>`: Text search across decisions, rationales, and rejected options.
  - `whyline decisions show <id>`: Displays decision detail, exact commit binding, supersession lineage, and review findings.
  - `--json`: Machine-readable output for agent scripting.
- **Structured review fields on `note`**: Rather than a premature `whyline review` command (Codex) or loose text, adopt Claude's recommendation to extend `whyline note` with optional review-specific metadata (`--verdict approved|rejected`, `--reviewed-commit <sha>`, `--test <result>`). This captures review rigor within the existing event pipeline.
- **Parsing safety for `--rejected`**: Fix `events.parse_rejected()` splitting on the first colon, which breaks when the option string contains a colon (e.g., URLs, ports like `redis:6379`). Support structured arguments or safer delimiters.

---

### 3. Operational State Cleanup: Ownership Leases & Handoff Terminal States

In our live test during this review, running `whyline sync` still displayed:
- An approved handoff for task `FC-3` (committed days ago), and
- `WARNING: 1 overlapping ownership claim` from ancient task `UCF-1`.

This confirms that advisory state accumulation is not a hypothetical scaling edge-case; it is an active bug degrading prompt token budgets right now.

**Revised design:**
- **Ownership leases**:
  - Add TTLs to claims (`claim --ttl <hours>`, defaulting to 72h).
  - Add `whyline release --task <task>`, `whyline release --all`, and `whyline release --stale`.
  - Prefix-aware matching in `ownership.conflicts()` if directory or glob claims are ever supported.
- **Handoff terminal states & smart baselines**:
  - Handoffs must have explicit closure: `whyline handoff close [--status completed|cancelled]`.
  - When a handoff is approved or closed and the repository HEAD has moved past `current_commit`, `sync.py` must suppress it from the active context fence.
  - Base commit detection: Concede to Codex that hardcoding `merge-base origin/main` is unsafe across repos. Instead, inspect git tracking upstream if available, or fall back to the preceding handoff's `current_commit`, or record an explicit `None` rather than collapsing `base == current == HEAD`.

---

### 4. Ledger Scale & Privacy Policy

Claude and Codex both accepted my finding that `ledger.jsonl` (and not `decisions.md`) is the critical scaling bottleneck because `history.load()` deserializes every `FileTouched` and raw prompt `Instruction` on almost every CLI command just to extract notes. Codex also introduced an indispensable privacy requirement: prompt retention.

**Revised design:**
- **Prompt retention policy**:
  - Add repo-level configuration `prompt_capture = metadata | redacted | full` (defaulting to `metadata` or `redacted`).
  - Add `whyline ledger prune --older-than <days>` to clean raw prompts while keeping event counts and hashes.
- **Read fast-paths**:
  - For `brief` and `sync`, which only require `events.NOTE`, avoid parsing the entire multi-megabyte mechanical ledger.
  - Read backwards from the end of `ledger.jsonl`, or maintain a secondary `notes.jsonl` stream / lightweight cache in `.whyline/`.
  - Benchmark against Whyline's <200ms cold start budget before adding any heavy database dependency.

---

### 5. Rename-Aware Relevance & Diff-Wide Explanation

Both features represent natural extensions of Git's existing capabilities into Whyline's reasoning engine.

**Revised design:**
- **Rename tracking via `gitq.historical_paths()`**:
  - Use `git log --follow --name-only` to resolve prior paths.
  - Match candidate decisions against any historical alias of the file, reporting the alias matched in `explain` output so attribution remains transparent.
- **Diff-wide review: `whyline explain --diff [ref]` & `--staged`**:
  - Map modified/deleted line ranges to prior commits and decisions.
  - Group explanations by decision ID to prevent repetitive hunk spam.
  - Provide a coverage summary: percentage of diff lines with exact (`HIGH`), heuristic (`MEDIUM`), mechanical-only, or unexplained provenance.
  - Surface alerts if a changed hunk re-implements an option recorded under `**Rejected:**`.

---

### 6. Antigravity Ecosystem Integration & Consolidated `whyline doctor`

Antigravity is already a first-class runner in `runner.py`, but has zero mechanical hook support. Furthermore, testing whether hooks work across agents is currently impossible without blind manual runs.

**Revised design:**
- **First-class Antigravity hook support**:
  - Implement hook installer for Antigravity's `.agents/hooks.json` contract (`PreInvocation`, `PostToolUse`, `Stop`).
  - Teach `hook_entry.py` to parse Antigravity event payloads into standard Whyline `Instruction` and `FileTouched` events.
  - Include Antigravity hook status in `render.py` (`whyline status`).
- **Consolidated `whyline doctor`**:
  - Broaden the hook-check proposal into a unified diagnostic command:
    - Verifies JSON configs for Claude, Codex, and Antigravity hooks.
    - Tests `whyline-hook` executable PATH resolution and dry-run execution.
    - Validates `.whyline/` directory permissions and ledger health.
    - Flags stale ownership claims, unclosed handoffs, and malformed decision blocks.

---

### Revised Prioritization & Implementation Sequence

| Phase | Focus | Core Deliverables | Why This Order |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **Provenance Durability & Fresh Clones** | Explicit `--commit`, lossless HTML comment metadata, `attach` workflow. | Solves the primary confidence ceiling on fresh clones without breaking backward compatibility. |
| **Phase 2** | **Operational Hygiene** | Claim TTLs, `release --stale`, `handoff close`, sync suppression for stale states. | Stops immediate token-budget bleed and false-positive conflict warnings currently seen in live runs. |
| **Phase 3** | **Decision Lifecycle & Querying** | `--supersedes`, `retract`, `whyline decisions list/search/show`, review fields on `note`. | Gives developers and agents clean tools to inspect, supersede, and audit decisions without manual grep. |
| **Phase 4** | **Ledger Scale & Privacy** | Prompt capture modes, `ledger prune`, reverse-read fast-path for `history.load()`. | Protects the <200ms cold-start budget and prevents sensitive prompt leakage before ledger size explodes. |
| **Phase 5** | **Review Workflows & Renames** | Rename-aware `historical_paths()`, `whyline explain --diff` / `--staged`. | Transforms `explain` from a single-line debugging utility into a PR/code review power tool. |
| **Phase 6** | **Ecosystem & Diagnostics** | Antigravity `.agents/hooks.json` integration, `whyline doctor`. | Closes the loop on agent observability and provides self-healing diagnostics across all supported agents. |
