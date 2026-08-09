# Phase 0 Experiment Protocol

**Protocol version:** 1.0  
**Status:** Draft for M0.1 review  
**Target sample:** 10 qualified participants  
**Study shape:** Within-subject, counterbalanced comparison plus provenance interview

## Research questions

### Handoff hypothesis

Does a structured generated handoff reduce receiving-agent context reconstruction compared with:

- **C — Cold start:** task statement and repository only.
- **H — Human brief:** task statement plus a participant-written brief capped at 150 words.
- **S — Structured brief:** task statement plus the PRD handoff schema, capped at 2,000 estimated tokens.

### Provenance hypothesis

When developers see realistic `explain file:line` evidence, do they use it to make a different or faster review, debugging, or onboarding decision?

## Participants

Recruit 10 developers who meet `participant-screener.md`. Aim for a mix of solo and team workflows, but do not treat company size as an outcome subgroup with this sample.

## Handoff tasks

Prepare three matched tasks in synthetic repositories. Each task must:

- require a prior agent's architectural or debugging conclusion;
- include at least one rejected alternative that is costly to rediscover;
- have objective completion checks;
- be completable in 20 minutes by the receiving agent;
- be similar in complexity without sharing the same solution.

Pilot all tasks internally before participant sessions. Record pilot duration and revise tasks only before participant data collection begins.

## Assignment and counterbalancing

Each participant completes all three conditions on different matched tasks. Rotate conditions using these sequences:

| Participant aliases | Sequence |
|---|---|
| P01, P04, P07, P10 | C → H → S |
| P02, P05, P08 | H → S → C |
| P03, P06, P09 | S → C → H |

Do not allow a participant to use the same repository twice. Keep receiving-agent provider constant within a participant. Record provider and version.

## Procedure

1. Read the consent script and confirm consent.
2. Record participant background without employer or repository-identifying data.
3. Explain that the study evaluates the workflow, not the participant.
4. For each assigned condition:
   - provide the clean repository and task;
   - start the timer when the receiving agent gets the initial prompt;
   - stop time-to-productive-work when the agent first states a correct actionable plan and begins the relevant edit or diagnostic;
   - stop task time when verification passes or at 20 minutes;
   - record copy/paste events, clarification interventions, token/usage fields exposed by the official CLI, outcome, and missing-context incidents;
   - ask the participant for confidence and trust ratings before revealing the source-session record.
5. Show the original source-session decisions and note material omissions or distortions.
6. Run the provenance scenarios in `interview-guide.md` using `explain-mockup.md`.
7. Conduct the closing interview.

## Metrics

### Primary handoff metrics

- Median seconds to productive work by condition.
- Median receiving-agent input and output tokens by condition, only when officially exposed.
- Copy/paste count outside the supplied condition artifact.
- Task success: verification passed within 20 minutes.
- Critical-context miss: an omitted or wrong fact caused rework, failure, or an unsafe decision.

### Secondary handoff metrics

- Participant trust in supplied context, 1–5.
- Confidence in outcome, 1–5.
- Number of human clarification interventions.
- Total task time.
- Brief preparation time and generation cost.

### Provenance metrics

- Behavioral value: participant identifies a concrete decision they would change, accelerate, or verify using the evidence.
- Retrieval value: participant can answer who/why/alternatives/review/merge questions correctly.
- Intended weekly use, recorded but not treated as behavioral proof.
- Ranked scenario value: review, debugging, onboarding, incident response.

## Success thresholds and interpretation

### Clear handoff win

Structured handoff must satisfy all of:

- at least 25% lower median time to productive work than cold start;
- no worse than the human brief on median time to productive work;
- zero increase in critical-context misses versus the human brief;
- at least 7 of 10 participants prefer it to cold start after seeing the source record.

The PRD's 40% token-reduction target is reported where data exists, but is not a Phase 0 gate if one or both official CLIs do not expose comparable usage.

### Strong provenance interest

At least 7 of 10 participants must identify a concrete behavior change in a realistic scenario, and at least 5 must rank the capability as valuable enough to install for a real repository. Stated enthusiasm alone does not qualify.

### Direction decision

| Handoff | Provenance | Decision |
|---|---|---|
| Strong | Strong | Build v1 as scoped |
| Modest/weak | Strong | Rebalance to provenance-first |
| Strong | Weak | Reconsider seriously |
| Weak | Weak | Stop |

At least one hypothesis must meet its threshold to continue.

## Analysis

- Report participant-level raw measurements and medians; avoid significance claims at n=10.
- Compare all three conditions within participants and note order effects.
- Analyze failures and critical omissions qualitatively even when aggregate time improves.
- Mark missing token data as unavailable, never zero.
- Separate results recorded after any protocol amendment.
- Record deviations, facilitator interventions, crashes, and rate limits.
- Apply `measurement-policy.md` for timing, token accounting, and missing usage data.

## Threats to validity

- Learning and fatigue: mitigated by counterbalancing and matched tasks.
- Provider differences: held constant within participant and reported.
- Synthetic-task realism: invite participants to map results to a recent real handoff during interview.
- Facilitator bias: use the fixed script and thresholds.
- Novelty bias for provenance: require a concrete scenario decision, not a preference rating alone.
- Generated-brief leakage: source agents receive only their task and repository; facilitators must not hand-edit S except to remove secrets.

## Protocol amendment log

| Version | Date | Change | Reason | Data affected |
|---|---|---|---|---|
| 1.0 | 2026-08-06 | Initial draft | M0.1 | None |
| 1.1 | 2026-08-09 | Added fixed measurement policy; clarified token overhead and privacy-minimal retention | Engineering dry runs | No measured participant data |
