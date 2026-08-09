# Phase 0 Measurement Policy

**Version:** 1.0  
**Date:** 2026-08-09  
**Status:** Fixed before valid timed pilot runs

## Handoff metrics

The primary Phase 0 handoff metric is **time to productive work**, not vendor token totals. A receiving agent becomes productive at the first repository-changing action after it has stated or demonstrated the correct implementation direction. For automated CLI pilots, first file-change time is the reproducible proxy; a facilitator must later verify that the change follows a correct plan.

Secondary metrics are task completion time, verification success, critical-context misses, human interventions, copy/paste events, and brief-preparation effort.

## Token accounting

Vendor-reported usage mixes task input with system prompts, tool schemas, repository instructions, cached context, and repeated turn context. The Phase 0 dry runs showed fixed context can dwarf the synthetic task. Therefore report, but do not conflate, these fields:

| Metric | Definition | Use |
|---|---|---|
| Logical input | Vendor-reported `input_tokens` | Total context processed as reported by the official CLI |
| Cached input | Vendor-reported cached-input field | Portion served from cache, where exposed |
| Uncached input proxy | `max(input_tokens - cached_input_tokens, 0)` | Diagnostic proxy only; not assumed to equal billed input |
| Output | Vendor-reported `output_tokens` | Generated response/tool-planning volume |
| Brief size | UTF-8 bytes, words, and estimated tokens using one fixed local estimator | Direct measure of condition payload |
| Cost | Vendor-reported cost, when exposed | Reported without estimating missing vendor prices |

Do not compare zero with unavailable data. Do not compare token fields across providers unless their official definitions are demonstrably equivalent.

## Phase 0 interpretation

- The PRD's 40% token-reduction target remains a v1 outcome target.
- Phase 0 will report whether structured handoffs reduce vendor-reported logical and uncached-input proxy values, but token reduction is not a hard gate when fixed harness context dominates or fields are incomparable.
- Time to productive work, correctness, and critical-context misses determine whether handoffs show a clear win.
- Report raw values and within-participant/within-provider differences. Do not use statistical-significance language for the ten-person sample.
- Cached/system overhead must never be removed from reported totals merely because it weakens the result.

## Timing rules

- Start the clock immediately before spawning the receiving CLI.
- First response time: arrival of the first agent message.
- Productive-work proxy: start of the first file-change event.
- Completion time: receipt of `turn.completed` after successful verification.
- If the process exits without a completion event, record failure and elapsed time.
- If the timeout expires, terminate, wait five seconds, then kill only if necessary; record the termination path.

## Data retention

- Commit only aggregate measurements and anonymized notes.
- Raw CLI events remain ephemeral by default because they can contain source and prompts.
- No session recordings by default. A future recording requires separate consent and an approved storage location outside the repository.
- Contact details remain in an owner-controlled scheduling system outside the repository; only participant aliases appear here.

