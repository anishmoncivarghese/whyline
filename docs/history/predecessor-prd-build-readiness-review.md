# AgentDock PRD v4.0 — Build-Readiness Review

> **Superseded historical document.** This is the predecessor design for what
> shipped as **whyline**. It was written under the working name "AgentDock",
> which was **rejected**: an unrelated MIT-licensed AI-agent framework already
> uses that name commercially. This project makes no claim to it. The name is
> retained inside this document only so the reasoning stays readable; see
> `docs/superpowers/specs/2026-08-09-whyline-v1-design.md` for what was actually
> built and why the scope changed.


**Reviewed:** 2026-08-06  
**Source:** `predecessor-prd-v4.0.md`  
**Verdict:** **Conditionally buildable. Start Phase 0 now; do not start the full v1 implementation until the Phase 0 direction call and rename are complete.**

## Executive assessment

The PRD has a clear product thesis, disciplined v1 boundaries, a credible local-first architecture, measurable goals, and an unusually useful failure model. Its strongest decision is to make durable provenance the product and treat orchestration as supporting infrastructure.

The remaining uncertainty is product risk rather than basic engineering feasibility. The PRD correctly requires evidence that users value `explain`, and that structured handoffs outperform a short human-written brief. Phase 0 should therefore be treated as the first implementation phase, not as pre-project paperwork.

## What is ready

- Product wedge: durable, line-addressable reasoning and provenance.
- v1 boundaries: ledger, memory, structured handoff, two adapters, worktrees, and two roles.
- Trust model: subprocess-only adapters, no credential handling, Git remains authoritative.
- Storage direction: append-only JSONL source of truth with a rebuildable SQLite index.
- Failure behavior: explicit outcomes for crashes, rate limits, scope violations, and merge conflicts.
- Non-functional targets: startup, query latency, memory, compatibility, and privacy.
- Measurable outcomes: handoff time, provenance completeness, collision rate, adoption, and retention.

## Decisions required before Phase 1

| Decision | Owner | Deadline | Recommended default |
|---|---|---|---|
| Product name and package namespace | Product owner | Phase 0 exit | Choose from ledger/provenance semantics; verify package, GitHub, and domain availability before use |
| Second adapter after Claude Code | Tech lead | Phase 0 adapter spike | Codex, because it tests a genuinely different vendor CLI and matches the target workflow |
| Handoff generation method | Product + tech lead | Phase 0 experiment | Agent-generated summary with an editable template fallback |
| Ledger committed by default | Product + security reviewer | Before storage implementation | Commit reasoning records only after a configurable redaction hook; never commit raw transcripts |
| Phase 1 continuation metric | Product owner | Before first pilot | Ten external users complete a handoff unaided, and at least five use `explain` to answer a real repository question |
| Licence and project intent | Owner | Phase 0 exit | Apache-2.0; explicitly state whether this is a portfolio project or intended business |

## Specification gaps to close during design

These do not block Phase 0, but they should be recorded as architecture decisions before their related implementation milestone.

1. **Ledger schema and evolution.** Define event versioning, stable IDs, timestamp format, path normalization, hash semantics, and forward/backward compatibility.
2. **Line-level provenance semantics.** `explain file:line` needs a precise algorithm for renames, moved lines, squashes, uncommitted work, and multiple contributing sessions. A practical v1 can use ledger file events plus `git blame`, and clearly report confidence.
3. **Session identity and lifecycle.** Specify states and valid transitions for created, running, blocked, incomplete, completed, reviewed, and merged.
4. **Scope declarations.** Define whether scope is a path list, glob set, or inferred diff, and how overlap is checked before launch.
5. **Redaction contract.** Define hook input/output, failure behavior, secret scanning boundaries, and whether a failed hook blocks ledger persistence or only Git commit.
6. **Adapter process protocol.** Specify cancellation, timeouts, PTY resize, signal forwarding, ANSI cleanup, output capture limits, and behavior when the CLI output format changes.
7. **Context ranking.** Define a deterministic baseline for recency and path relevance before considering model-based ranking.
8. **Repository topology.** Define behavior in monorepos, nested Git repositories, submodules, bare repositories, and linked worktrees.
9. **Configuration precedence.** Establish CLI flags > environment > repository config > user config > defaults, with secrets forbidden in persisted config.
10. **Platform support.** Identify minimum Python, Git, macOS, Linux, and WSL versions and test them in CI.

## Material risks and controls

| Risk | Required control |
|---|---|
| Users like the idea of provenance but do not consult it | Instrument a local, privacy-preserving pilot log and measure actual `explain` usage rather than interview enthusiasm alone |
| Generated handoffs omit a critical decision | Always preview and confirm; preserve explicit open questions and verification results; compare against a hand-written control |
| Ledger leaks prompt secrets | Redaction hook, documentation warning, content-free defaults, fixtures containing synthetic secrets, and a pre-commit safety test |
| JSONL changes create noisy merge conflicts | One event per line, deterministic serialization, stable IDs, append discipline, and documented conflict recovery |
| Adapter breakage becomes the maintenance bottleneck | Version probes, conformance fixtures, capability flags, and visible degraded status |
| `explain file:line` overpromises certainty | Return provenance evidence and confidence/fallback language; never imply exact line causality when only file-level evidence exists |
| Eight commands expand Phase 1 beyond its evidence | Build them in vertical slices and keep commands thin over tested domain services |

## Recommended direction

Proceed with Phase 0 immediately. Build disposable experiment-quality adapters and prototypes, not the production framework. At the Phase 0 review, choose one of the four directions in PRD §13.1 and re-baseline Phase 1 scope. No public package or repository naming should use “AgentDock” before the rename decision.

