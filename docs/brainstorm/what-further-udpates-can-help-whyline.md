# Brainstorm: what further udpates can help whyline

## Claude

# What other updates can be done in Whyline — independent research

Grounded in the current source under `src/whyline/` (5.3k lines across `cli.py`,
`decisions.py`, `resolve.py`, `brief.py`, `sync.py`, `ownership.py`, `gitq.py`,
`account.py`, `model.py`, `hooks.py`, plus the console/TUI/relay layer) and the
README's stated design constraints (no orchestration, no credential handling,
advisory-only ownership). Ideas below are things I'd actually build next, not a
wishlist — each is tied to a concrete gap in the code as it exists today.

## 1. Give `explain` a deterministic link instead of a timestamp-window guess

`resolve.py` reaches HIGH confidence only by matching a note's timestamp against
a git-blame commit's epoch window (`explain()` in `resolve.py:70-225`) — a
genuinely clever heuristic, but still a heuristic: two decisions recorded close
together, or a note written slightly before/after the commit that landed it, can
land on MEDIUM or the wrong entry. `note` and `handoff` already know which files
are affected; they don't know which commit. Adding an optional `--commit <sha>`
to `whyline note` (defaulting to `HEAD` when the tree is clean at note time, and
back-fillable by a lightweight `git commit` post-hook that stamps the most recent
untied note) would let `explain` match on exact SHA first and only fall back to
the epoch-window logic when no commit was recorded. This turns the tool's most
distinctive feature — "why does this line exist" — from probabilistic into exact
for every decision recorded going forward, while keeping the existing heuristic
as the fallback for older history.

## 2. Decisions have no supersede/retract relationship

`decisions.md` is append-only by design (`decisions.py:1-5`), which is right for
auditability, but there's no way to mark a later decision as replacing an earlier
one on the same file. Today, if an agent reverses an earlier call, `brief` and
`explain` will happily surface both the original and the reversal with no
ordering signal beyond timestamp — a future reader (human or agent) has to infer
which one is "live." A `--supersedes <event-id>` flag on `note`, rendered as a
new `**Supersedes:**` field parsed the same way `**Files:**` is (`decisions.py:
92-116`), would let `brief`/`explain` either suppress the superseded entry or
label it clearly. Small addition, closes a real correctness gap in the
committed record.

## 3. Ownership claims never go stale

`ownership.claim()` stamps `claimed_at` (`ownership.py:59`) but nothing ever
reads it back — `conflicts()` only checks for shared files or a shared task
(`ownership.py:18-38`), forever, regardless of age. In practice a claim from
three weeks ago that an agent simply forgot to `release` will keep surfacing as
a live conflict in `claim`, `sync`, and `status` indefinitely, training users to
ignore the warning. Since ownership is explicitly advisory and local
(`.whyline/ownership.json` is gitignored per the README), the fix is cheap: have
`conflicts()` (or its callers) flag claims older than some threshold (e.g. 48h)
as "stale" rather than "active," and let `whyline release --stale` clear all of
them in one shot. This keeps the "advisory, never blocking" philosophy intact
while making the warning meaningful again.

## 4. `explain` and `brief` break silently across renames

`resolve._mentions()` matches a note's recorded path against `rel_path` with
plain equality (`resolve.py:64-67`), and `blame_line()` in `gitq.py:58-85` blames
one literal path with no `--follow`. Meanwhile `commits_touching()` *does* use
`--follow` specifically because "history stops at the most recent rename"
(`gitq.py:90-92`) — the code already knows renames matter for git history, but
that awareness doesn't extend to matching decisions against a renamed file. A
decision recorded against `src/cache.py` becomes invisible to `explain` the
moment that file is renamed to `src/caching/store.py`, even though git itself
can still trace the line's ancestry. Worth resolving the note's recorded path
through the same rename chain `commits_touching` already walks, so old decisions
keep attaching to a file that moved.

## 5. No way to query the decision log

There's `whyline timeline` (mechanical ledger events) and `whyline brief`
(relevance-ranked, token-budgeted, meant for agent context), but nothing meant
for a human to just ask "what has codex decided in the last week" or "show me
every decision that touched `src/cli.py`." `decisions.parse_entries()` already
returns structured dicts with actor/role/task/files/because/alternatives
(`decisions.py:92-141`) — the parsing exists, there's just no CLI surface over
it besides the token-capped brief. A `whyline log [--actor] [--file] [--task]
[--since] [--grep]` command, printing full entries with no budget trimming,
would make the committed record actually browsable instead of only
machine-consumable.

## 6. Codex mechanical capture is still an unverified assumption

The README says plainly: hooks are "Verified against Claude Code only... no
Codex hook event has been observed yet" and `whyline status` reports Codex as
"configured but never observed" until one organically arrives. That's an honest
status quo, but it means the tool's second-most-important pillar (mechanical
capture, layer 2 of 3 in the README's own model) is running on faith for half
its supported agents. A `whyline doctor --fire-test-event` that synthesizes one
hook payload through the real `hook_entry.py` path and confirms it lands in the
ledger would convert "never observed" into a real pass/fail check that runs at
`init` time, instead of waiting on an agent to happen to fire one.

## 7. No Gemini support in account/model detection

`account.py` detects Claude, Codex, Antigravity, and Grok (`detect_codex`,
`detect_claude`, `detect_antigravity`, `detect_grok`); `detect_antigravity` and
`detect_grok` are already PATH-only "installed, not subscribed" checks
(`account.py:97-113`) precisely because those CLIs have no reliable
non-interactive login check. Gemini CLI is in the same boat and is a real
competitor in this exact niche (coding agent with a CLI). Adding
`detect_gemini` on the same PATH-only pattern, plus a `model.py` entry, is a
same-shape addition, not new design — and the console's brainstorm/relay
feature already treats "some models available, others greyed out with a
reason" as a first-class UI state, so a new agent slots in without touching the
console layer at all.

## 8. `decisions.md` has no rotation story for long-lived repos

Every read path (`brief.compose`, `resolve.explain`, the new `log` idea above)
parses the *entire* `decisions.md` on every call — fine at the 19-decisions/
3-days scale the design was measured at, but the file is committed and
append-only forever. A repository that lives for two years will eventually be
parsing thousands of entries on every `sync` call just to rank and discard most
of them. Worth deciding now, while the format is still young: either an index
(`.whyline/decisions.idx.json`, rebuildable, gitignored, mapping id → byte
offset) to avoid re-parsing on every read, or an explicit `whyline archive
--before <date>` that moves old entries to `decisions-YYYY.md` while `explain`
and `brief` search all archive files but the hot path only touches the current
one. Either is a straightforward addition on top of the existing parser; doing
nothing means a silent performance cliff a few years out.

## 9. `whyline explain` has no batch/diff mode

`explain` takes exactly one `path:line` (`cli.py:358-384`, `_split_target`).
The natural companion to `sync` — which already computes `gitq.changed_paths()`
for the working tree (`gitq.py:131-160`) — would be `whyline explain --diff`,
explaining every changed line across the dirty tree in one pass, reusing the
same per-line `blame_line` + note-window logic already in `resolve.py`. That's
the moment a reviewer actually wants "why do these lines exist" — right before
committing or reviewing a diff — not one line at a time.

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
