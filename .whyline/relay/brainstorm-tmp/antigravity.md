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
