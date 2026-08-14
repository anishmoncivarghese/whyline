# M0 Cooperation Test Results

**Window:** 2026-08-14 to <end date; evaluate after 2–3 normal work days>
**Agents:** Claude Code 2.1.226, Codex 0.147.0

**Collection status:** in progress. The probe and canonical instruction shim were
installed in Mozhima, Duet and DocSift on 2026-08-14. CodeGraph joined as a
clean-project subject on 2026-08-15 with excluded baseline commit `bf0430e`.
Events accumulate in `~/.whyline-m0.log`; installation smoke tests used a
separate temporary log and did not add a baseline event here.

| Agent | Non-trivial changes (from git log) | Probe firings | Unprompted firings | Rate (unprompted) |
|---|---:|---:|---:|---:|
| Claude Code | | | | |
| Codex | | | | |

## Quality check

| Firing | Note matched what changed? | Included a rejected alternative? |
|---|---|---|

## Decision

Threshold from spec §5: >=60% unprompted on Claude Code and >=1 firing on Codex
-> build as designed. 30-60% -> self-report is best-effort. <30% -> drop `brief`
and `run`, keep hook-only mechanical provenance.

**Outcome:** <build as designed | best-effort | fall back>
