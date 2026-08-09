# Phase 0 Status

**Updated:** 2026-08-09  
**Overall:** In progress; Phase 1 remains blocked.

| Milestone | State | Evidence | Remaining gate |
|---|---|---|---|
| M0.1 Experiment readiness | Adjust | Protocol, screener, consent, metrics, three verified fixtures, condition isolation, measurement policy | Valid timed pilot, independent protocol review, recruitment |
| M0.2 Adapter feasibility | Adjust | Static checks pass; Codex read-only and two task runs pass; timeout/cancellation observed | Claude official login and successful task; schema handoff probes |
| M0.3 Direction gate | Not started | Explain mockup ready | Ten measured sessions and outcome analysis |

## Latest verification

- `python3 phase0/fixtures/verify_fixtures.py` — passed for all three fixtures.
- `python3 -m unittest discover -s phase0/probes/tests -v` — 2/2 passed, including silent-process timeout.
- Codex 0.146.0-alpha.9.2 — live read-only probe passed; cold and human engineering tasks passed.
- Claude Code 2.1.173 — structured error path passed; successful invocation blocked on official login.

## Decisions fixed

- Primary handoff evidence: time to productive work, correctness, and critical-context misses.
- Vendor token totals are reported with cached and uncached proxies, not treated as directly comparable across providers.
- Contact details remain outside the repository.
- Sessions are not recorded by default.
- Raw CLI event content is ephemeral by default.

## Immediate sequence

1. Authenticate Claude Code through its own official flow and repeat the harmless live probe.
2. Obtain an independent protocol review.
3. Run a valid, timestamped three-condition pilot after explicitly accepting the observed quota cost.
4. Recruit and schedule 10 qualified participants.
5. Run M0.3 analysis and direction review before Phase 1.

