# Brainstorm: what further udpates can help whyline

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

# Independent findings: further updates that can help Whyline

Whyline already has the right core shape: a committed human-readable decision log, a local event ledger, explicit handoffs, advisory ownership, and honest confidence levels. The most valuable next work is not another front end. It is strengthening the link between a decision, the code it explains, and the period in which it is valid.

## 1. Make decision-to-commit attribution explicit and durable

This is the highest-leverage update. `whyline note` records time, files, actor, role, and task, but not a commit. `resolve.explain` therefore infers attribution by placing note timestamps inside Git commit windows. That can be ambiguous when several decisions occur between commits, and a fresh clone loses the ledger's precise timestamp because `decisions.md` parses only the date from its heading. The tests correctly prevent that degraded record from claiming high confidence, but the underlying limitation remains.

Add an optional immutable Git binding to a decision:

- `whyline note ... --commit <sha>` for decisions recorded after a commit;
- `whyline note ... --pending-commit` followed by `whyline attach <decision-id> --commit HEAD` for the common pre-commit workflow;
- optionally let `handoff` attach all still-pending decisions for its task to `--current` after explicit confirmation.

`explain` should prefer an exact commit binding, fall back to the existing time-window heuristic, and say which mechanism produced its confidence. Do not silently bind every note to `HEAD`: decisions are commonly recorded while the relevant changes are still uncommitted, so that would create confident false provenance.

The committed Markdown format also needs a lossless, versioned machine representation. It currently preserves only the event ID in an HTML comment; the parser reconstructs the rest from display text, truncates timestamp precision to a day, and splits files on commas. Keep the readable entry, but add a safely encoded/versioned metadata comment (or a committed structured companion file) containing the exact timestamp, decision ID, files, task, and commit binding. Older entries should continue to parse through the current fallback.

Acceptance bar: after cloning with no local ledger, an exactly commit-bound decision can still produce high confidence; ambiguous or pending notes cannot.

## 2. Add lifecycle semantics for decisions

The decision log is append-only, but decisions themselves are not eternal. Today a superseded architecture choice and its replacement are both ranked as current history, with no relationship between them. That makes accumulated context less trustworthy over time.

Add explicit append-only lifecycle events rather than editing history in place:

- `whyline supersede <decision-id> --with <decision-id> --because ...`;
- `whyline retract <decision-id> --because ...` for a decision later found invalid;
- `whyline decisions show <id>` should display the chain;
- `brief`, `sync`, and `explain` should default to current decisions, while clearly disclosing relevant superseded decisions when they explain older blamed commits.

This preserves auditability while answering two different questions correctly: “what rule applies now?” and “why did this old line exist then?”

## 3. Expire or close checkout-local operational state

Ownership claims and the active handoff persist until someone explicitly replaces or releases them. `claimed_at` is recorded but never interpreted, and there is no handoff close/clear command. In a long-running checkout, abandoned claims become permanent warnings and an old handoff continues to look active.

Introduce leases and terminal states:

- a configurable claim TTL, with `whyline claim --ttl`, `renew`, and `release --all-for-task`;
- stale claims shown separately and excluded from active conflicts by default;
- `whyline handoff close <task> --status completed|cancelled` and `handoff clear`;
- optionally release that task's claims when a handoff is closed;
- `status` and `sync` should warn when the handoff's recorded `current_commit` differs from `HEAD`, or when its file/dirty snapshot no longer matches the checkout.

Never delete stale state silently. Mark it stale, make cleanup explicit or policy-driven, and retain the original timestamp for diagnosis.

## 4. Add privacy and retention controls for the local ledger

The hook stores every `UserPromptSubmit` body verbatim in `ledger.jsonl`. The file is gitignored and timeline JSON redacts prompts by default, which prevents accidental publication, but secrets and sensitive problem statements can still live indefinitely on disk.

Add repository-local capture policy with safe defaults:

- `prompt_capture = "metadata" | "redacted" | "full"`, preferably defaulting to metadata for new repositories;
- optional redaction patterns for known secret formats;
- `whyline ledger prune --older-than 30d` and `whyline ledger compact`;
- `status` should report capture mode, ledger size, oldest event, and retention policy;
- `init` should state plainly what will be captured before installing hooks.

Decision text remains committed by design, so this policy should apply only to mechanical local events and raw prompts, not quietly rewrite `decisions.md`.

## 5. Make history retrieval a first-class command

`brief` is optimized for agent injection, `timeline` reads only the local ledger, and `explain` starts from one path or line. There is no direct way to search committed decisions by text, actor, role, task, status, or ID—especially on a fresh clone.

Add a `whyline decisions` family over the merged history model:

- `list --task --file --actor --role --since --status`;
- `search <text>` across decision, rationale, and rejected alternatives;
- `show <id> --json`;
- stable JSON output for integrations.

This can remain a linear scan initially. The README's own 50,000-event measurement does not justify introducing SQLite yet. Add an index only after a measured threshold is crossed.

## 6. Follow file renames in decision relevance, not only Git windows

`gitq.commits_touching` already uses `git log --follow`, so commit-window calculation survives a rename. But note selection still uses exact path equality in `resolve._mentions` and exact file intersection in `brief.select_entries`. A decision recorded for `src/old.py` is therefore invisible when asking about `src/new.py`, even if Git knows they are the same history.

Build a rename-aware alias set for a requested path from Git history, then use it consistently in `explain`, `brief`, and `sync`. Report the matched historical path so the user can see why the decision was included. Keep this conservative: only follow Git-detected renames, not similarity guesses invented by Whyline.

## 7. Create a durable review outcome surface

The repository documents a measured gap: implementers record decisions, while reviewer rulings often disappear into an uncommitted tracker. Wording in `AGENTS.md` was improved, but the cause and effect remain unmeasured.

Add a compact review record rather than hoping every verdict is translated into a generic note:

```text
whyline review WL-42 --actor claude --verdict approved \
  --commit <sha> --test "pytest -q: passed" \
  --finding "accepted bounded retry risk: upstream call is idempotent"
```

The durable entry should capture verdict, reviewed commit/range, findings that changed the result, accepted risks, and tests. It should not become a dump of every nit. `sync` can then distinguish implementation decisions from review evidence, and the next measurement can directly answer whether review capture improved.

## 8. Add diff-wide explanation for review and migration work

Single-line `explain` is useful interactively but expensive during a review. Add:

- `whyline explain --diff <base>..<head>`;
- `whyline explain --staged`;
- grouping by decision ID so one decision is not repeated for every changed line;
- a coverage summary: exact, heuristic, mechanical-only, and unexplained changed lines/files.

This turns Whyline from a lookup tool into a review aid and gives the project a measurable provenance-coverage signal. The output must preserve the current honesty rules: uncommitted lines and unmatched paths stay unexplained rather than inheriting a nearby file-level decision.

## 9. Turn `status` into an actionable doctor without conflating configuration and observation

`status` already does unusually careful hook inspection and distinguishes “configured” from “observed.” Extend that foundation with a `whyline doctor` command that checks:

- writable ledger and decision paths;
- parseability/conflict markers in `decisions.md`;
- instruction block freshness;
- exact hook command availability and last observation by agent;
- stale handoff/ownership state;
- configured agent binaries/models;
- oversized ledger and privacy policy.

For hooks, keep configuration, executable availability, and actual vendor observation as three separate facts. A synthetic `whyline hook test` can validate the entrypoint and write path, but it must not claim that Codex or Claude actually invoked the hook; only a real observed vendor event proves that.

## Recommended sequence

1. Introduce the versioned, lossless decision metadata and exact commit binding, with backward-compatible parsing.
2. Add decision lifecycle events and the query/show commands needed to manage them.
3. Add stale-state detection, handoff close, and ownership leases.
4. Add prompt-capture policy and ledger retention controls before the local log grows further.
5. Add rename-aware relevance and diff-wide explain on top of the stronger provenance model.
6. Add durable review outcomes and measure whether reviewer capture improves.
7. Consolidate all diagnostics under `doctor` after the new policies exist.

The unifying principle is: preserve Whyline's human-readable, local-first design, but make every confidence claim reproducible from durable identifiers rather than timing and convention alone.

## Antigravity

# Independent Research: What Further Updates Can Help Whyline

**Agent:** Antigravity  
**Perspective:** Independent architecture and code-grounded review  
**Scope:** Core CLI (`whyline`), Provenance Engine, Relay Integration, Ecosystem Support  
**Baseline Evaluated:** Whyline 0.3.19 (`src/whyline/`)

---

## Executive Summary

Whyline's core value proposition—enabling multi-agent collaboration without loss of reasoning across sessions—is sound and already delivers measurable value in direct CLI usage. Its disciplined architecture (zero-telemetry, local-only, stdlib-first for CLI cold start under 200 ms, process handover via `exec` rather than PTY supervision) avoids the brittle wrapper pitfalls common to agent tooling.

However, a close examination of the implementation reveals critical friction points in three areas:
1. **Provenance fragility**: `explain` relies on fuzzy timestamp-window heuristics between `git blame` and decision timestamps, meaning squashes, rebases, fresh clones, or multi-decision commits degrade confidence from `HIGH` to `MEDIUM` or `LOW`.
2. **Operational state leak & staleness**: advisory ownership claims and completed handoffs accumulate indefinitely in local JSON files, causing perpetual false-positive conflict warnings and wasting prompt token budgets.
3. **Ecosystem & UX gaps**: Antigravity is supported as a launch runner (`agy`), but lacks mechanical hook integration (`.agents/hooks.json`), leaving its prompts, sessions, and file touches unrecorded; decision history lacks a searchable query tool (`whyline log`); and diff-wide provenance review is missing.

Below are 10 concrete, code-grounded proposals to harden and advance Whyline.

---

## 1. Deterministic Commit-Bound Provenance (`resolve.py`, `decisions.py`)

### The Problem
In [`src/whyline/resolve.py:123-130`](file:///Users/anish/agentdock/src/whyline/resolve.py#L123-L130), `explain` determines whether a line's authoring matches a recorded decision using a time-window heuristic:
```python
lower = gitq.previous_commit_epoch(root, rel_path, blame.sha)
in_window = [
    note for note in notes
    if _epoch_of(note) <= blame.epoch
    and (lower is None or _epoch_end(note) > lower)
]
```
This heuristic suffers from several systemic failure modes:
1. **Post-commit note creation**: If an agent records a decision during code review, after a commit, or in a commit hook, `blame.epoch < note.epoch`. The note falls into the "all of it postdates this line's last change" branch ([`resolve.py:204-207`](file:///Users/anish/agentdock/src/whyline/resolve.py#L204-L207)) and confidence drops to `LOW`.
2. **Squashes, rebases, and clock skew**: Git rewrite operations alter commit epochs, breaking alignment with earlier recorded note timestamps.
3. **Fresh clone confidence ceiling**: In [`decisions.py:38`](file:///Users/anish/agentdock/src/whyline/decisions.py#L38), `render_entry` writes only `## YYYY-MM-DD`. On fresh clones where `.whyline/ledger.jsonl` is absent (gitignored), `_has_day_precision()` is true, which hard-caps `explain` confidence to `MEDIUM` ([`resolve.py:132-144`](file:///Users/anish/agentdock/src/whyline/resolve.py#L132-L144)) even if only a single commit and decision ever existed.

### Proposed Update
- **Support explicit commit binding**: Update `whyline note` with an optional `--commit <sha>` flag. If omitted and the working tree is clean or committing, default to `gitq.head_commit(root)`.
- **Durable commit storage**: Store `**Commit:** <sha>` or HTML comment `<!-- whyline-commit: <sha> -->` in `decisions.md` and `commit` in `events.NOTE`.
- **Direct resolution**: In `resolve.explain()`, check first if `note.commit == blame.sha`. If an exact commit match is found, assign `HIGH` confidence immediately, bypassing the timestamp window.
- **Clone durability**: Because the commit SHA is committed to `decisions.md`, fresh clones can immediately achieve `HIGH` confidence resolution without needing `ledger.jsonl`.

---

## 2. Path Rename & File Move Tracking in `explain` (`resolve.py`, `gitq.py`)

### The Problem
[`gitq.commits_touching()`](file:///Users/anish/agentdock/src/whyline/gitq.py#L88-L100) correctly uses `git log --follow` to traverse renames. However, [`resolve.explain()`](file:///Users/anish/agentdock/src/whyline/resolve.py#L70-L82) filters candidate notes using [`_mentions(entry.event, rel_path)`](file:///Users/anish/agentdock/src/whyline/resolve.py#L64-L68):
```python
def _mentions(event: dict, rel_path: str) -> bool:
    if event.get("path") == rel_path:
        return True
    return rel_path in (event.get("files") or [])
```
If a file `src/auth/legacy.py` is renamed to `src/auth/oauth.py`, `git blame` attributes an older line to the commit created when it was named `src/auth/legacy.py`. However, `_mentions` only filters for `src/auth/oauth.py`. All historical decisions recorded under `src/auth/legacy.py` are discarded, and `explain` falsely outputs: `"no reasoning recorded for this line"`.

### Proposed Update
- Add `gitq.historical_paths(root, rel_path)` using `git log --follow --name-only --format="" -- rel_path` to gather prior paths for `rel_path`.
- Pass the union of current and previous paths into note candidate filtering in `resolve.explain()`.

---

## 3. Advisory Ownership Lifecycle & Stale Claim Expiration (`ownership.py`, `sync.py`)

### The Problem
In [`src/whyline/ownership.py`](file:///Users/anish/agentdock/src/whyline/ownership.py), claims are added via `claim()` and removed via `release(task, actor)`. There is no expiration mechanism, no batch release, and no hook on task completion.
In long-running repositories, old claims accumulate indefinitely. For instance, in `agentdock` right now, `whyline sync` reports:
```
Ownership: 25 active claims
WARNING: 1 overlapping ownership claim; coordinate before writing.
```
This warning has been continuously firing for an old, completed task (`UCF-1`) claimed by two agents months ago.
Furthermore, every claim is formatted and injected into `sync` context ([`sync.py:130-165`](file:///Users/anish/agentdock/src/whyline/sync.py#L130-L165)), consuming valuable tokens in the context budget.

### Proposed Update
- **Add Claim TTL / Expiration**: In `ownership.load()`, mark or exclude claims whose `claimed_at` timestamp is older than a configurable threshold (e.g., 7 days or 72 hours).
- **Auto-release on approved handoff**: In `handoff.create()`, when `--status approved` or `--status completed` is passed, automatically release ownership claims associated with that task ID.
- **Batch release CLI**: Provide `whyline release --all`, `whyline release --task <task>` (releasing across all actors), and `whyline release --stale`.
- **Sync noise suppression**: Expired/stale claims should be omitted from `whyline sync` prompts and conflict checks.

---

## 4. Active Handoff State Management & Archival (`handoff.py`, `sync.py`)

### The Problem
[`src/whyline/handoff.py:66`](file:///Users/anish/agentdock/src/whyline/handoff.py#L66) persists the latest handoff in `.whyline/active-handoff.json`. Once written, it stays "Active" forever until another handoff overwrites it.
In current sessions, running `whyline sync` continues to display:
```
Active handoff:
- task: FC-3
- from/to: codex -> codex
- status: approved
- summary: Approved and committed eadabbc...
```
Even though task `FC-3` was completed and committed days ago, every fresh agent session begins with an obsolete "approved" handoff, taking ~150-200 tokens from the sync prompt fence.
Additionally, [`handoff.py:60-63`](file:///Users/anish/agentdock/src/whyline/handoff.py#L60-L63) defaults `base_commit` and `current_commit` to `gitq.head_commit(root)` when omitted, resulting in `base == current` and losing the commit range diff context.

### Proposed Update
- **Add Handoff Archival / Clearing**: Add `whyline handoff clear` (or `archive`). When a handoff reaches `approved` or the repository branch merges/advances, archive the handoff to the ledger and clear `active-handoff.json`.
- **Smart Base-Commit Detection**: If `--base` is omitted in `whyline handoff`, infer `base_commit` using `git merge-base HEAD origin/main` (or upstream branch) or the previous handoff's `current_commit`, instead of setting `base = current = HEAD`.
- **Sync Context Suppression**: If an active handoff is in status `approved` or `completed` and the git tree has moved past `current_commit`, treat it as inactive in `whyline sync` unless `--include-completed` is explicitly requested.

---

## 5. First-Class Mechanical Hook Support for Antigravity (`hooks.py`, `hook_entry.py`, `render.py`)

### The Problem
Whyline currently configures hooks for Claude Code (`.claude/settings.json`) and Codex (`.codex/hooks.json`) in [`src/whyline/hooks.py`](file:///Users/anish/agentdock/src/whyline/hooks.py).
However, Antigravity (`agy`) is already supported in `runner.py`, `account.py`, and `model.py`, but has **no hook configuration**.
Antigravity natively supports lifecycle hooks via `.agents/hooks.json` (or `.agent/hooks.json`) covering:
- `PreToolUse`
- `PostToolUse`
- `PreInvocation`
- `PostInvocation`
- `Stop`

Because `whyline init` does not configure Antigravity hooks, any direct session run in Antigravity produces zero mechanical events (`SessionStarted`, `SessionEnded`, `Instruction`, `FileTouched`) in `.whyline/ledger.jsonl`.
Furthermore, [`render.py:259`](file:///Users/anish/agentdock/src/whyline/render.py#L259) only audits `claude` and `codex` hooks in `whyline status`.

### Proposed Update
- **Add Antigravity hook installation**: Implement `hooks.install_antigravity(root / ".agents" / "hooks.json")` supporting `PostToolUse`, `PreInvocation`, and `Stop`.
- **Support in hook_entry**: Update `hook_entry.py` to handle Antigravity's payload format.
- **Audit in `whyline status`**: Include Antigravity hook status alongside Claude and Codex in `render.py`.

---

## 6. Decision Superseding & Retraction Model (`decisions.py`, `brief.py`, `sync.py`)

### The Problem
Decisions in `.whyline/decisions.md` are purely append-only without relationship links. In real software development, architectures evolve: decision D2 often deliberately supersedes or retracts decision D1.
Currently, both D1 and D2 coexist equally in `decisions.md`. When an agent calls `whyline sync` or `brief`, both D1 and D2 are injected into the prompt. The agent sees conflicting instructions (e.g., "Use SQLite" vs "Migrated to DuckDB") and has no automated way to know D2 superseded D1.
Furthermore, in `resolve.explain()`, this triggers the ambiguity branch ([`resolve.py:154-163`](file:///Users/anish/agentdock/src/whyline/resolve.py#L154-L163)): `"several decisions match this commit; the link is ambiguous"`, dropping confidence to `MEDIUM`.

### Proposed Update
- **Add `--supersedes <id>` / `--retracts <id>`**:
  Allow recording superseding links:
  ```bash
  whyline note "Use DuckDB for analytics" --because "SQLite locks on concurrency" \
    --supersedes 3a8f9c12 --file src/db.py --actor codex --task T-12
  ```
- **Store link in `decisions.md`**:
  Render `**Supersedes:** 3a8f9c12` in the decision block.
- **Filter in `brief` and `sync`**:
  In `brief.select_entries()`, suppress superseded decisions from the default output unless `--all` is passed, or mark them `[SUPERSEDED by <id>]`.
- **Disambiguate `explain`**:
  In `resolve.py`, if multiple decisions match a commit window and one supersedes the others, select the active superseding decision to maintain `HIGH` confidence.

---

## 7. Diff-Wide Explain for Code Review (`cli.py`, `resolve.py`)

### The Problem
Whyline's `explain` command only takes a single file or line: `whyline explain <file>[:line]`.
When an agent or human reviewer reviews a pull request or staged diff (e.g. 10 files with 40 modified hunks), running `whyline explain` line-by-line is completely impractical.
Reviewers need to know:
- Why did the code being *modified or deleted* exist in the first place?
- Does any changed line violate a past recorded decision or rejected alternative?

### Proposed Update
- Add `whyline explain --diff [ref]` (or `whyline explain --staged`):
  1. Inspects `git diff` against `HEAD` (or specified base ref).
  2. Extracts modified and deleted line ranges.
  3. Blames the previous commits for those lines and resolves matching decisions.
  4. Outputs a structured summary:
     - Prior rationale for lines being altered or deleted.
     - Warnings if any current change resurrects an option explicitly listed under `**Rejected:**`.

---

## 8. Queryable Decision Log: `whyline log` (`cli.py`, `history.py`)

### The Problem
Currently, the only read interfaces for decisions are:
- `whyline brief` (token-bounded summary for the next agent),
- `whyline explain` (line/file attribution),
- `whyline timeline` (chronological event stream).

There is no dedicated tool to query or search decisions. If a developer or agent wants to ask:
- "What decisions were recorded by `codex` on task `FC-3`?"
- "Which decisions mention `cache`?"
- "What decisions were recorded since 2026-09-01?"
they are forced to manually inspect `decisions.md` with grep or regex.

### Proposed Update
Implement `whyline log`:
```bash
whyline log [--task <task>] [--actor <actor>] [--file <path>] [--query <text>] [--since <date>] [--json]
```
- Reuses `history.load()` and regex filters without adding external dependencies.
- Supports machine-readable `--json` for scripting and agent tool calls.
- Provides pagination or limit controls to keep output concise.

---

## 9. Performance & Scale: Decision Indexing & Ledger Hygiene (`ledger.py`, `history.py`)

### The Problem
In [`src/whyline/ledger.py:20-38`](file:///Users/anish/agentdock/src/whyline/ledger.py#L20-L38), `read_all()` reads and parses every single line in `.whyline/ledger.jsonl`.
[`history.load()`](file:///Users/anish/agentdock/src/whyline/history.py#L94-L107) calls `ledger.read_all()`, deserializing every mechanical event (`FileTouched`, `Instruction` with raw prompt text, `SessionStarted`, `SessionEnded`) just to extract `events.NOTE`!
In a project with 20,000+ tool calls and prompt submits, `ledger.jsonl` grows into tens of megabytes.
Because `history.load()` is executed on almost every CLI command (`brief`, `sync`, `explain`, `timeline`, `status`), reading the full ledger in pure Python will eventually breach Whyline's strict 200 ms interactive budget.

### Proposed Update
- **Ledger Segmentation / Offset Index**:
  - Store mechanical high-volume events (`FileTouched`, `Instruction`) in `ledger.jsonl`, but maintain a lightweight index or separate notes ledger (`notes.jsonl`), or:
  - Cache loaded notes and file mtimes in `.whyline/.cache.json`.
- **Fast-path for `brief` and `sync`**:
  - `brief` and `sync` only require `events.NOTE`. If `decisions.md` is already parsed and up-to-date, scan `ledger.jsonl` from the end (reverse read) only up to the timestamp of the last known committed decision, rather than reading the entire multi-megabyte file from line 1.
- **Log Rotation**:
  - Add `whyline maintenance rotate` to archive historical sessions older than 30 days into `.whyline/ledger.archive.jsonl.gz`.

---

## 10. Hook Verification & Synthetic Health Check (`cli.py`, `hooks.py`, `render.py`)

### The Problem
README notes: *"no Codex hook event has been observed yet, so treat Codex mechanical capture as untested rather than working: run whyline status, which will say configured but never observed until one arrives."*
Developers and agents have no direct way to test whether a hook command (`whyline-hook --agent codex`) works without launching a real agent, running a prompt, and hoping the hook fires. If permissions, path resolution, or JSON formatting fail, the hook silently swallows exceptions (`except Exception: pass` in [`hook_entry.py:96`](file:///Users/anish/agentdock/src/whyline/hook_entry.py#L96)), leaving the user wondering why nothing is recorded.

### Proposed Update
- Add `whyline hook check [--agent <name>]`:
  1. Verifies hook JSON syntax in `.claude/settings.json`, `.codex/hooks.json`, and `.agents/hooks.json`.
  2. Verifies `whyline-hook` executable availability on PATH.
  3. Executes a dry-run synthetic `SessionStart` / `PostToolUse` event with `--dry-run` or test payload.
  4. Reports explicit diagnostic errors if the hook cannot write to `.whyline/ledger.jsonl`.

---

## Summary Prioritization Matrix

| Proposal | Impact | Implementation Effort | Core Risk Addressed |
| :--- | :--- | :--- | :--- |
| **1. Commit-Bound Provenance** | High | Low | Flaky time-window matching; clone confidence loss |
| **2. Path Rename Tracking** | Medium | Low | False-negative "no reasoning" on renamed files |
| **3. Ownership Expiration & TTL** | High | Low | Perpetual false conflict warnings and sync token waste |
| **4. Active Handoff Archival** | High | Low | Zombie approved handoffs cluttering sync prompts |
| **5. Antigravity Hook Support** | High | Low | Missing mechanical telemetry for Antigravity sessions |
| **6. Decision Superseding** | Medium | Medium | Conflicting history and ambiguous explain matches |
| **7. Diff-Wide Explain** | High | Medium | Inability to review PRs or staged diffs against rationale |
| **8. Queryable `whyline log`** | Medium | Low | Lack of decision searchability for agents & humans |
| **9. Ledger Indexing & Scaling** | Medium | Medium | Long-term degradation of <200ms cold start budget |
| **10. Hook Synthetic Verification** | Medium | Low | Silent hook misconfigurations and permission failures |

---

## Alignment with Whyline Principles

All 10 proposals adhere strictly to Whyline's foundational constraints:
- **Zero credential touching**: No API tokens, keys, or external network requests.
- **Process handover via `exec`**: Runner remains clean; no PTY wrapping or screen scraping.
- **Standard library first**: All proposed core CLI enhancements use Python standard library modules (`pathlib`, `json`, `argparse`, `subprocess`, `datetime`, `re`), preserving zero extra dependencies for core commands.
- **Honest confidence**: Clear distinction between commit-bound certainty (`HIGH`), heuristic inference (`MEDIUM`), and absence of data (`NONE`).
- **Cold start integrity**: Maintains module import budget < 60 modules and cold-start latency < 200 ms.
