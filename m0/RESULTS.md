# M0 Cooperation Test Results

**Window:** <start date> to <end date>
**Agents:** Claude Code 2.1.226, Codex 0.147.0

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
