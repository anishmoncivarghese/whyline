# Internal Fixture Pilot Report

**Status:** Automated solvability check passed; two engineering dry runs complete; valid timed comparison pending.  
**Date:** 2026-08-09

## Automated checks

Run:

```bash
python3 phase0/fixtures/verify_fixtures.py
```

The verifier materializes each fixture in a temporary directory, confirms its baseline fails, applies the facilitator-only reference implementation, and confirms all tests pass. Temporary repositories are deleted automatically.

### Result

| Fixture | Baseline | Reference | Baseline time | Reference time |
|---|---|---|---:|---:|
| Cache TTL | Expected failure: 4 errors | Pass | 46 ms | 48 ms |
| Webhook dedupe | Expected failure: 2 failures | Pass | 1,055 ms | 60 ms |
| Config reload | Expected failure: 5 errors | Pass | 48 ms | 55 ms |

The first verifier run also found that the unsolved config fixture could leave its reader thread alive after `reload` was missing. The test now guarantees thread shutdown with `finally`, and the verifier converts any future 10-second subprocess timeout into an explicit failed check.

Condition-isolation smoke testing also passed: cold materialization contains no `HANDOFF.md`, while human and structured materializations contain only the assigned brief under that neutral filename. No facilitator directory or alternative brief is copied.

## Comparability review

| Fixture | Production module | Tests | Core decision | Concurrency/state issue | Critical trap |
|---|---:|---:|---|---|---|
| Cache TTL | 14 baseline lines | 5 | Absolute monotonic expiry | Expiry state synchronized with values | Zero TTL/falsy values |
| Webhook dedupe | 11 baseline lines | 3 | Reserve before handler | Concurrent duplicate delivery | Release reservation on failure |
| Config reload | 17 baseline lines | 5 | Parse then atomic swap | Readers see complete snapshots | Values containing `=` |

All tasks require one small module change, have deterministic standard-library-only tests, include one important rejected alternative, and can be completed without external services. The webhook concurrency test has a one-second failure path in the unsolved baseline; solved runs should complete quickly.

## Open pilot work

- Run at least one timed cold, human-brief, and structured-brief trial using different fixtures.
- Record time to first correct actionable plan and total completion time.
- Confirm the facilitator can withhold unassigned brief files reliably.
- Ask an independent reviewer to follow only the written protocol and note ambiguities.

## Codex engineering dry runs

These runs validate mechanics only and are excluded from hypothesis results. Local event-arrival timestamps were not captured, and the initial cold fixture did not state the test command while the human brief did. That asymmetry has now been corrected by putting the same verification command in every `TASK.md`.

| Condition | Fixture | Outcome | Approx. wall time | Input tokens | Cached input | Output tokens | Observations |
|---|---|---|---:|---:|---:|---:|---|
| Cold | Cache TTL | 5/5 tests passed | ~37 s | 117,706 | 102,400 | 1,183 | Two failed test-discovery attempts before correct command |
| Human | Webhook dedupe | 3/3 tests passed | ~51 s | 153,822 | 129,536 | 1,478 | One failed `python` attempt; unsafe cleanup rejected, safe cleanup followed |

The minimal read-only Codex probe consumed another 27,219 input tokens (13,824 cached) and completed in 11.6 seconds. This fixed overhead makes raw token totals unsuitable for comparing brief quality without separating harness/system context from task-specific tokens.

The structured dry run was intentionally not executed after the second run increased input usage by roughly 31%. Before further runs, the pilot harness must capture local timestamps and the study must define whether vendor-reported cached/system tokens are included in the handoff metric.
