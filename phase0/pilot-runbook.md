# Timed Pilot Runbook

## Purpose

Validate task timing, condition isolation, instructions, and measurement mechanics before recruiting measured participants. Pilot data must be marked `PILOT` and excluded from Phase 0 outcome totals.

## Setup

1. Select a sequence from `experiment-protocol.md`.
2. Materialize three different fixture/condition pairs in fresh temporary destinations.
3. Verify the repository contains `TASK.md` and `CONDITION.txt`; only human/structured conditions contain `HANDOFF.md`.
4. Run baseline tests and confirm expected failures.
5. Record provider and exact CLI version.

For a Codex engineering pilot, use the timestamped harness only after approval to send synthetic data and consume quota:

```bash
python3 phase0/probes/timed_codex_pilot.py cache_ttl cold \
  --confirm-external-synthetic-data
```

The harness creates a temporary condition-isolated repository, records local event timings and aggregate usage, prints a summary, and does not persist raw event content.

## Timing

- Start `time_to_productive_seconds` when the receiving agent receives the prompt and repository.
- Stop it when the agent states a correct actionable plan and begins the relevant edit or diagnostic.
- Stop `total_task_seconds` when all tests pass or at 20 minutes.
- Record interventions immediately; do not reconstruct them afterward.

## Prompt

Cold condition:

```text
Complete the task in TASK.md. Inspect the repository, implement the smallest correct change, and run the documented tests.
```

Human or structured condition:

```text
Complete the task in TASK.md. A previous agent's handoff is in HANDOFF.md. Inspect the repository, implement the smallest correct change, and run the documented tests.
```

Do not add hints during a trial. If safety or tooling requires intervention, record it as a protocol deviation.

## Post-trial checks

- Tests pass.
- Diff is limited to the implementation module unless a test correction is justified.
- Hidden constraint in facilitator source truth is preserved.
- No unassigned brief or facilitator content was exposed.
- Agent output did not contain credentials or unrelated user-level context.

## Pilot exit

Proceed to measured sessions only when all three conditions can be run from this document by a reviewer, each fixture fits the 20-minute cap, and no condition-isolation defect remains.
