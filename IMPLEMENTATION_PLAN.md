# AgentDock — Implementation Plan

**Plan date:** 2026-08-06  
**Planning basis:** PRD v4.0 and `PRD_REVIEW.md`  
**Delivery model:** Evidence-gated phases with a formal review after every milestone and a final release review.

## Operating rules

- Build vertical slices that produce user-observable behavior; avoid implementing all infrastructure before one command works end to end.
- The JSONL ledger is authoritative. SQLite, caches, and rendered views must be disposable and rebuildable.
- Vendor CLIs are subprocesses. The application never reads, stores, refreshes, or proxies vendor credentials.
- Git is authoritative for repository and worktree state.
- Every milestone ends with tests, a risk update, a requirements trace, and a written go/adjust/stop decision.
- Any change to v1 scope needs evidence and an explicit plan revision.

## Review protocol used at every milestone

Create `reviews/<milestone-id>.md` using this structure:

1. Planned versus delivered.
2. Demonstration and acceptance-test results.
3. Automated test results and platform matrix.
4. Security/privacy review, including credential and prompt-data handling.
5. Performance results against applicable budgets.
6. PRD requirements trace: satisfied, partial, deferred, or failed.
7. Known defects, debt, and updated risk register.
8. User evidence and metric results, where applicable.
9. Decision: **go**, **adjust**, **repeat**, or **stop**, with named owner.

A milestone is incomplete until its review is written and its blocking findings are resolved or explicitly accepted by the owner.

## Phase 0 — Validate the product direction (2 weeks)

### M0.1 — Experiment design and recruitment

**Deliverables**

- Define target-user screener and recruit 10 multi-agent developers.
- Prepare three matched handoff conditions: cold start, hand-written brief, structured generated brief.
- Define measurement for elapsed time, receiving-agent tokens when exposed, manual copy/paste, correctness, missing context, and user trust.
- Prepare an interactive or static `explain` prototype using realistic repository history.
- Record the continuation metric and interview script before running sessions.

**Exit criteria**

- Ten sessions scheduled or a documented recruitment fallback exists.
- Experiment protocol can be repeated by another person.
- Metrics and interpretation thresholds are fixed before results are observed.

**Review:** `reviews/M0.1-experiment-readiness.md` — research design, bias, privacy, and measurement audit.

### M0.2 — Adapter feasibility spikes

**Deliverables**

- Disposable Claude Code and Codex subprocess probes.
- Record non-interactive invocation, cwd behavior, environment pass-through, exit codes, streaming, cancellation, self-summarisation, resume, usage reporting, and rate-limit/error behavior.
- Draft the adapter capability matrix and conformance-test cases.
- Verify no authentication material is read or persisted.

**Exit criteria**

- Both CLIs complete a harmless fixture task non-interactively in an isolated test repository.
- Limitations are captured as adapter capabilities rather than hidden assumptions.
- At least one reliable handoff-summary path exists per adapter, including editable fallback.

**Review:** `reviews/M0.2-adapter-feasibility.md` — subprocess safety, terms constraints, failure handling, and go/no-go per adapter.

### M0.3 — Handoff and provenance validation

**Deliverables**

- Run the matched handoff study and 10 interviews.
- Test whether the `explain` output changes review, debugging, or onboarding behavior.
- Report quantitative results and recurring qualitative themes.
- Decide generated-summary versus heuristic/manual fallback behavior.

**Exit criteria**

- At least one PRD floor is met: a clear handoff win or strong provenance behavior evidence.
- The direction is selected using PRD §13.1.
- Rename, licence, product intent, second adapter, ledger default, and Phase 1 continuation metric are resolved.

**Review:** `reviews/M0.3-direction-gate.md` — formal **build**, **rebalance**, **reconsider**, or **stop** decision. Phase 1 cannot begin without approval.

## Phase 1 — Core v1 (8–10 weeks after Phase 0 approval)

Phase 1 uses six independently reviewable vertical milestones. Schedule may overlap only after interfaces are accepted.

### M1.1 — Foundation and contracts

**Deliverables**

- Python package, `uv`-based developer workflow, linting, typing, tests, CI for macOS/Linux and documented WSL verification.
- Domain models for events, sessions, handoffs, roles, adapter capabilities, and lifecycle transitions.
- Versioned configuration and ledger schemas with migration policy.
- CLI shell with stable exit-code and structured-error conventions.
- Architecture decision records for all gaps listed in `PRD_REVIEW.md`.

**Exit criteria**

- Clean checkout can install, test, and invoke the CLI using documented commands.
- Schema round-trip, invalid-input, migration, and lifecycle-transition tests pass.
- No production dependency requires credential access.

**Review:** `reviews/M1.1-foundation.md` — architecture, dependency, packaging, schema, and threat-model review.

### M1.2 — Provenance ledger vertical slice

**Deliverables**

- Append-only, deterministic JSONL writer with atomic persistence and corruption recovery.
- Rebuildable SQLite index with schema versioning.
- Event types required by PRD §9.6.
- `timeline` filters and `--json`.
- Redaction hook with safe failure behavior.

**Exit criteria**

- Rebuilding the index yields results equivalent to direct ledger replay.
- Concurrent writers, interrupted writes, malformed tail records, and JSONL merge-conflict fixtures are tested.
- `explain` and `timeline` performance is measured on 50,000 generated events; `explain` remains under 1 second.
- Synthetic secret fixtures do not reach commit-ready ledger output.

**Review:** `reviews/M1.2-ledger.md` — data integrity, privacy, performance, and schema-evolution review.

### M1.3 — `explain` and project memory

**Deliverables**

- `explain <file>[:line]` with `--json`, evidence links, and explicit confidence/fallback semantics.
- `memory --preview`, `--add`, and `--prune`.
- Deterministic relevance ranking by path and recency.
- Enforced default 2,000-token injected-context budget.
- Explicit-confirmation flow before modifying `AGENTS.md`; append-only decision log.

**Exit criteria**

- A real fixture history resolves instruction, session, alternatives, review, and merge where evidence exists.
- Rename, moved-line, squash, deleted-file, and uncommitted-change cases degrade honestly.
- Full decision logs are never injected; previews exactly match injected content.
- Cold `explain`, `timeline`, and `status` startup remains under 200 ms; brief composition remains under 2 seconds excluding model calls.

**Review:** `reviews/M1.3-explain-memory.md` — provenance accuracy, overclaiming, context quality, and performance review with a no-context control.

### M1.4 — Adapter runtime and session supervision

**Deliverables**

- Production Claude Code and Codex adapters behind the accepted contract.
- PTY/non-interactive invocation, streaming output, cancellation, signal forwarding, timeouts, output limits, and ANSI cleanup.
- `run`, `status`, and `--json` status.
- Visible adapter capability and degraded-state reporting.
- Conformance suite with pinned tested CLI versions.

**Exit criteria**

- Both adapters pass the conformance suite and failure fixtures.
- Crash, kill, rate-limit, missing binary, unsupported version, and malformed output behaviors match the PRD.
- Environment pass-through is tested without logging or persisting credential-like values.
- Five concurrent supervised fixture sessions keep AgentDock's resident memory under 300 MB.

**Review:** `reviews/M1.4-adapters.md` — process safety, compatibility, terms compliance, failure recovery, and resource review.

### M1.5 — Worktrees, scope, roles, and merge

**Deliverables**

- Isolated worktree creation and preserved recovery state.
- Declared file scope, overlap refusal, explicit force path, and post-session scope-violation detection.
- Developer and reviewer roles from editable repository configuration.
- `merge <session>` with diff preview; conflicts are presented, never auto-resolved.
- Cleanup guidance that never destroys unmerged work automatically.

**Exit criteria**

- Parallel non-overlapping fixture tasks succeed without clobbering.
- Overlapping tasks are refused unless explicitly forced.
- Out-of-scope edits appear in session state and the ledger.
- Crash and conflict fixtures preserve recoverable worktrees; Git always wins disagreements.

**Review:** `reviews/M1.5-isolation.md` — destructive-operation safety, race conditions, Git topology, and recovery review.

### M1.6 — Structured handoff and integrated v1 pilot

**Deliverables**

- Schema-valid handoff generation, editable preview/confirmation, persistence, decision append, relevance-filtered injection, and target launch.
- `init` scaffolding and complete eight-command v1 surface.
- End-to-end journeys: init → run → handoff → explain → timeline → merge.
- User documentation covering quotas, secrets, permissions, worktrees, recovery, and supported versions.
- External pilot with at least 10 target users.

**Exit criteria**

- A Claude-originated decision reaches a Codex brief for the same files within budget.
- Ten external users complete a handoff unaided.
- `explain` answers a real repository question for the agreed continuation cohort.
- Install-to-first-handoff median is under 10 minutes; handoff transition median is under 60 seconds with zero copy/paste.
- No unresolved critical/high security or data-loss finding remains.

**Review:** `reviews/M1.6-v1-gate.md` — complete PRD trace, pilot evidence, security, performance, accessibility of CLI output, documentation, and release decision.

## Phase 2 — Depth (6–8 weeks, only after the Phase 1 gate)

### M2.1 — Review workflow and session resume

- Add explicit review request/completion records and adapter-specific resume where supported.
- Verify stale sessions, changed branches, incompatible CLI versions, and partial handoffs.
- Review: `reviews/M2.1-review-resume.md`.

### M2.2 — Cost visibility, third adapter, and interface completion

- Add usage/cost capture only where reported by the official CLI; mark estimates and unknowns clearly.
- Choose a third adapter from pilot demand and run the same conformance suite.
- Ensure `--json` behavior is stable across all required machine-readable commands.
- Review: `reviews/M2.2-depth.md`.

### M2 exit gate

- At least 30% of Phase 1 pilot users remain active at day 30.
- Over 80% of sessions expose captured usage where the vendor CLI makes it available.
- Review workflow demonstrably catches or improves real findings.
- Review: `reviews/M2-release-gate.md`; decide whether Phase 3 demand exists.

## Phase 3 — Surface (evidence-gated, no committed schedule)

Evaluate TUI, command routing, role library, plugin SDK, compare mode, and knowledge graph individually. Each proposal requires user evidence, estimated maintenance cost, success metric, and a reversible prototype. Do not accept external adapters before the conformance suite and contribution policy are stable.

## Final review

After the approved delivery scope is complete, create `reviews/FINAL.md` and run a clean-room release audit:

- Trace every in-scope PRD requirement to code, tests, documentation, or an explicit deferral decision.
- Re-run unit, integration, adapter-conformance, end-to-end, corruption-recovery, and platform tests from a clean checkout.
- Perform security and privacy review of subprocess environment handling, prompts, ledger, redaction, permissions, and worktree cleanup.
- Benchmark cold commands, brief composition, 50,000-event explain/timeline queries, and five concurrent sessions.
- Test install, first handoff, crash recovery, merge conflict, missing/degraded adapters, and complete removal without loss of human-readable decisions.
- Compare actual user metrics with PRD targets and document misses without redefining the targets after the fact.
- Audit documentation, licence, naming, package ownership, release artifacts, and rollback/recovery instructions.
- Classify all remaining findings by severity and issue a final **ship**, **limited pilot**, **return to milestone**, or **stop** decision.

## Requirements trace summary

| PRD area | Primary milestone |
|---|---|
| F0 adapters | M0.2, M1.4 |
| F1 project memory | M1.3 |
| F2 structured handoff | M0.3, M1.6 |
| F3/F6 provenance and event ledger | M1.2, M1.3 |
| F4 isolation and failure | M1.4, M1.5 |
| F5 roles | M1.5 |
| Eight CLI commands | M1.2–M1.6 |
| Security and privacy | Every review; final audit |
| Performance | M1.2–M1.4, M1.6, final audit |
| Validation metrics | M0.3, M1.6, M2 exit |

## Immediate next actions

1. Approve or amend the build-readiness review and this plan.
2. Name the product owner and technical lead.
3. Start M0.1 by fixing the experiment protocol and recruiting participants.
4. In parallel, start only disposable M0.2 adapter probes; do not establish public naming or production architecture yet.
5. Hold the M0.3 direction review before creating the Phase 1 backlog.
