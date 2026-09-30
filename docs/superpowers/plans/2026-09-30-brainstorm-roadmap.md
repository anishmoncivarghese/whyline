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
| 1. Exact commit provenance | 0.3.21 | next |
| 3. Decision lifecycle + `whyline decisions` | 0.3.22 | planned |
| 4. Ledger read path + prompt retention | 0.3.23 | planned |
| 5. Rename-aware relevance + `explain --diff` | 0.3.24 | planned |
| 6. Antigravity hooks + `whyline doctor` | 0.3.25 | planned |

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
