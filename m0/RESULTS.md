# M0 Cooperation Test Results

**Window:** 2026-08-14 to 2026-08-17
**Agents:** Claude Code 2.1.226, Codex 0.147.0
**Primary subject:** `/Users/anish/CodeGraph`, a clean isolated repository, baseline `bf0430e` (excluded)
**Secondary subjects:** Mozhima, Duet — instrumented 2026-08-14 but no development work followed, so they contribute no data. DocSift was never instrumented.

## Evidence sources

Two channels ran concurrently and overlap:

| Channel | What it is | Volume |
|---|---|---|
| `~/.whyline-m0.log` | The throwaway M0 probe | 16 lines, of which **13 genuine** (three `--help` smoke invocations excluded) |
| `CodeGraph/.whyline/decisions.md` + `ledger.jsonl` | **The real product** | **19 `Note` events** |

The product channel is the better measure: it is what v1 actually ships. The hook also ran, recording 47 `FileTouched`, 10 `Instruction`, 7 `SessionStarted` and 6 `SessionEnded` events — so the mechanical layer works unattended as designed.

## Firing rate

Denominator is post-baseline commits in CodeGraph (14 total), attributed to agent by timestamp. Probe timestamps are UTC; commit times below are local (UTC+5:30).

| Agent | Non-trivial changes | Decisions recorded | Probe firings | Rate |
|---|---:|---:|---:|---:|
| Claude Code | 4 | 6 | 1 | **150%** |
| Codex | 10 | 13 | 12 | **130%** |
| **Total** | **14** | **19** | **13** | **136%** |

Rates exceed 100% because a single commit frequently embodies more than one recorded decision — which is the desired behaviour, not an artefact.

**Timestamp correlation.** The twelve Codex probe firings (UTC 04:21–05:57 on 08-17) map onto local 09:51–11:27, matching commits `5207431` (09:51:41) through `7c4b595` (11:27:05) one-for-one or better. Recording tracked the work rather than being batched afterwards.

## Quality check

All 19 decisions carry both a `--because` rationale and at least one `--rejected` alternative with a concrete reason. Representative samples:

| Decision | Rejected alternative |
|---|---|
| Check schema compatibility before applying idempotent DDL | DDL-first migration — mutates unsupported databases before refusal |
| Require a Swift grammar/runtime fix before the v0.2 adapter | Accept 23.5% parse errors — fails the stated 5% gate |
| Pin better-sqlite3 to ^13.0.0, not ^11.0.0 | ^11.0.0 resolves to 11.10.0, no prebuilds dir, requires node-gyp source build |
| Canonicalize repository roots and re-check after symlink resolution | Lexical path checks only — symlink escapes remain readable |

These are specific, technically substantive, and would be genuinely costly to rediscover. This is the field PRD v4.0 §9.2 called the highest-value one, and §6.3 argued no amount of output parsing could recover it. The self-report mechanism produces it directly.

## Decision

Threshold from spec §5: ≥60% unprompted on Claude Code and ≥1 firing on Codex → build as designed. 30–60% → self-report is best-effort. <30% → drop `brief` and `run`, keep hook-only mechanical provenance.

**Outcome: build as designed.** Both agents exceed the threshold by a wide margin, recording quality is higher than the design assumed, and Codex's compliance was confirmed unprompted.

## Caveats that limit this result

Recorded so the result is not read as broader than it is.

1. **Unprompted-ness: confirmed by the operator.** The probe log has no column for it, so this rested initially on timestamp clustering. The operator confirmed on 2026-08-17 that **Codex was never reminded** — all 13 of its decisions came from `AGENTS.md` alone. `docs/superpowers/specs/2026-08-16-handover-observations.md` §1 separately documents two confirmed unprompted Claude firings.

   This also settles that document's §4, which listed "Codex reads `AGENTS.md` and acts on it" as an untested assumption. It is now tested: a non-Claude agent read the instruction and followed it twelve times without a nudge.

2. **The read side is unreliable.** The separate experiment in `m0/READ-SIDE-PROTOCOL.md` closed on 2026-08-23: Claude Code read unprompted near the start of 3 of 7 sessions, **43%**, below the precommitted 50% threshold. `run` is therefore the reliable handoff path; instruction-driven `brief` reads remain a best-effort fallback. Earlier 67%, 75%, and 50% figures are superseded; the 75% was also affected by an analyser bug that credited a Codex read to a Claude session. Codex produced 9 logged reads, but has no session denominator because the measured `SessionStarted` events came from the Claude hook, so its count is observational rather than a rate.

3. **A single-project, single-operator sample.** All usable data comes from one repository over three days with one operator who knew the instruction existed.

4. **Instruction form matters, but the amended read instruction remains inconsistent.** Observations §1 records a clean negative: a *declarative* AGENTS.md instruction ("record decision history through whyline rather than appending here") was not followed unprompted, while the *imperative + exact command + pre-authorized* `whyline note` instruction was followed twice unprompted. The `whyline brief` instruction was amended to include a trigger, exact command, pre-authorization, and visible verification. Its final measured rate was still only 3 of 7 Claude Code sessions (43%), so the four-part form improves the chance of a read but does not make it reliable. Codex was separately observed reading, without a denominator.

   **The reviewer trigger has now produced the outcome it targeted — but the observation cannot attribute it.** 0.1.3 widened the write trigger to name reviewers, after zero reviewer-voiced entries across the whole of Plan 1 (26 entries, all implementer-voiced). Within the next five tasks, two appeared, one of them substantive: a reviewer traced a CALLS precision drop from 1.000 to 0.250, established it was an oracle sentinel mismatch rather than a fabricated edge, and recorded that in `decisions.md` — exactly the reasoning that previously died in a gitignored ledger.

   **This is not clean evidence that the wording change caused it.** Two things changed at the same time: the trigger was widened, *and* the reviewing sessions began running inside the reviewed repository rather than from a sibling one. The second change fixes a different cause entirely — a reviewer working from elsewhere never loads the project's `AGENTS.md`, so no wording could have reached it. Both were introduced together on 2026-08-19, so this round cannot separate them.

   To attribute it, one variable has to move alone. The cheaper direction: run a reviewing session from a sibling repository again and see whether the reviewer still records. If it does, the wording was doing the work; if it does not, session location was.
