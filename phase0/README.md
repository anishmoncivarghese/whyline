# Phase 0 — Product-direction validation

Phase 0 tests two independent hypotheses before production implementation:

1. A structured handoff helps a receiving coding agent become productive faster and with less reconstructed context than a cold start or a short hand-written brief.
2. Repository-linked provenance changes developer behavior during review, debugging, or onboarding.

Current progress is tracked in `STATUS.md`.

The study protocol is fixed in `experiment-protocol.md`. Do not change hypotheses, primary metrics, or success thresholds after collecting results without recording the amendment and analyzing pre- and post-amendment results separately.

## Contents

- `experiment-protocol.md` — preregistered study design and analysis rules.
- `participant-screener.md` — target-user inclusion and exclusion criteria.
- `interview-guide.md` — moderated session and provenance interview script.
- `participant-consent.md` — plain-language consent and data-handling script.
- `metrics-template.csv` — one row per participant/task/condition.
- `measurement-policy.md` — fixed timing, token-accounting, and retention rules.
- `explain-mockup.md` — test stimulus for the provenance hypothesis.
- `adapter-capability-matrix.md` — feasibility observations and evidence status.
- `recruitment-tracker.csv` — privacy-minimal scheduling tracker.

## Study status

- Protocol: drafted, awaiting M0.1 review approval.
- Participants: not yet recruited.
- Adapter checks: repeatable static probe passed for Claude Code 2.1.173 and Codex CLI 0.146.0-alpha.9.2; quota-consuming live probes pending.
- Product direction: undecided until M0.3.

## Data handling

Use synthetic repositories and tasks unless a participant explicitly chooses their own repository. Do not copy source, prompts, credentials, transcripts, recordings, or employer names into this repository. Participant identifiers are study-local aliases such as `P01`. Store contact details outside the project repository. Sessions are not recorded by default.
