# Matched handoff task fixtures

These three synthetic Python tasks test whether prior-agent reasoning helps a receiving agent implement a small change without rediscovering constraints. They are deliberately similar: each requires a bounded change to an existing component, includes a concurrency or state constraint, has a tempting rejected alternative, and has objective tests.

## Materialize a clean study repository

```bash
python3 phase0/fixtures/materialize.py cache_ttl /tmp/study-cache-ttl --condition cold
cd /tmp/study-cache-ttl
python3 -m unittest discover -s tests -v
```

The materializer copies only participant-visible files and initializes Git. Facilitator files under each fixture's `facilitator/` directory are never copied. For `human` or `structured`, the selected brief is exposed as `HANDOFF.md`; for `cold`, no handoff file exists. `CONDITION.txt` records assignment for the facilitator's measurements.

## Fixture set

| ID | Goal | Hidden constraint | Rejected alternative |
|---|---|---|---|
| `cache_ttl` | Add per-entry cache TTL | Injected clock; preserve zero values | Sleeping tests and truthiness checks |
| `webhook_dedupe` | Prevent duplicate webhook processing | Reserve before handler call; release on failure | Marking only after success |
| `config_reload` | Reload configuration safely | Parse/validate before atomic replacement | Mutating live state during parsing |

## Study conditions

- **Cold:** give only `TASK.md` and the repository.
- **Human:** additionally give `briefs/human.md`.
- **Structured:** additionally give `briefs/structured.yaml`.

The materializer exposes only the assigned condition. Never manually copy `facilitator/source-truth.md` or a reference implementation into a participant repository.

## Pilot rubric

For each fixture record:

- clean baseline test result;
- completion time;
- first correct actionable plan time;
- tests after implementation;
- whether the hidden constraint was preserved;
- whether the rejected alternative was independently rediscovered;
- critical-context omissions in each supplied brief.
