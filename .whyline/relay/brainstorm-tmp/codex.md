# Independent findings: further updates that can help Whyline

Whyline already has the right core shape: a committed human-readable decision log, a local event ledger, explicit handoffs, advisory ownership, and honest confidence levels. The most valuable next work is not another front end. It is strengthening the link between a decision, the code it explains, and the period in which it is valid.

## 1. Make decision-to-commit attribution explicit and durable

This is the highest-leverage update. `whyline note` records time, files, actor, role, and task, but not a commit. `resolve.explain` therefore infers attribution by placing note timestamps inside Git commit windows. That can be ambiguous when several decisions occur between commits, and a fresh clone loses the ledger's precise timestamp because `decisions.md` parses only the date from its heading. The tests correctly prevent that degraded record from claiming high confidence, but the underlying limitation remains.

Add an optional immutable Git binding to a decision:

- `whyline note ... --commit <sha>` for decisions recorded after a commit;
- `whyline note ... --pending-commit` followed by `whyline attach <decision-id> --commit HEAD` for the common pre-commit workflow;
- optionally let `handoff` attach all still-pending decisions for its task to `--current` after explicit confirmation.

`explain` should prefer an exact commit binding, fall back to the existing time-window heuristic, and say which mechanism produced its confidence. Do not silently bind every note to `HEAD`: decisions are commonly recorded while the relevant changes are still uncommitted, so that would create confident false provenance.

The committed Markdown format also needs a lossless, versioned machine representation. It currently preserves only the event ID in an HTML comment; the parser reconstructs the rest from display text, truncates timestamp precision to a day, and splits files on commas. Keep the readable entry, but add a safely encoded/versioned metadata comment (or a committed structured companion file) containing the exact timestamp, decision ID, files, task, and commit binding. Older entries should continue to parse through the current fallback.

Acceptance bar: after cloning with no local ledger, an exactly commit-bound decision can still produce high confidence; ambiguous or pending notes cannot.

## 2. Add lifecycle semantics for decisions

The decision log is append-only, but decisions themselves are not eternal. Today a superseded architecture choice and its replacement are both ranked as current history, with no relationship between them. That makes accumulated context less trustworthy over time.

Add explicit append-only lifecycle events rather than editing history in place:

- `whyline supersede <decision-id> --with <decision-id> --because ...`;
- `whyline retract <decision-id> --because ...` for a decision later found invalid;
- `whyline decisions show <id>` should display the chain;
- `brief`, `sync`, and `explain` should default to current decisions, while clearly disclosing relevant superseded decisions when they explain older blamed commits.

This preserves auditability while answering two different questions correctly: “what rule applies now?” and “why did this old line exist then?”

## 3. Expire or close checkout-local operational state

Ownership claims and the active handoff persist until someone explicitly replaces or releases them. `claimed_at` is recorded but never interpreted, and there is no handoff close/clear command. In a long-running checkout, abandoned claims become permanent warnings and an old handoff continues to look active.

Introduce leases and terminal states:

- a configurable claim TTL, with `whyline claim --ttl`, `renew`, and `release --all-for-task`;
- stale claims shown separately and excluded from active conflicts by default;
- `whyline handoff close <task> --status completed|cancelled` and `handoff clear`;
- optionally release that task's claims when a handoff is closed;
- `status` and `sync` should warn when the handoff's recorded `current_commit` differs from `HEAD`, or when its file/dirty snapshot no longer matches the checkout.

Never delete stale state silently. Mark it stale, make cleanup explicit or policy-driven, and retain the original timestamp for diagnosis.

## 4. Add privacy and retention controls for the local ledger

The hook stores every `UserPromptSubmit` body verbatim in `ledger.jsonl`. The file is gitignored and timeline JSON redacts prompts by default, which prevents accidental publication, but secrets and sensitive problem statements can still live indefinitely on disk.

Add repository-local capture policy with safe defaults:

- `prompt_capture = "metadata" | "redacted" | "full"`, preferably defaulting to metadata for new repositories;
- optional redaction patterns for known secret formats;
- `whyline ledger prune --older-than 30d` and `whyline ledger compact`;
- `status` should report capture mode, ledger size, oldest event, and retention policy;
- `init` should state plainly what will be captured before installing hooks.

Decision text remains committed by design, so this policy should apply only to mechanical local events and raw prompts, not quietly rewrite `decisions.md`.

## 5. Make history retrieval a first-class command

`brief` is optimized for agent injection, `timeline` reads only the local ledger, and `explain` starts from one path or line. There is no direct way to search committed decisions by text, actor, role, task, status, or ID—especially on a fresh clone.

Add a `whyline decisions` family over the merged history model:

- `list --task --file --actor --role --since --status`;
- `search <text>` across decision, rationale, and rejected alternatives;
- `show <id> --json`;
- stable JSON output for integrations.

This can remain a linear scan initially. The README's own 50,000-event measurement does not justify introducing SQLite yet. Add an index only after a measured threshold is crossed.

## 6. Follow file renames in decision relevance, not only Git windows

`gitq.commits_touching` already uses `git log --follow`, so commit-window calculation survives a rename. But note selection still uses exact path equality in `resolve._mentions` and exact file intersection in `brief.select_entries`. A decision recorded for `src/old.py` is therefore invisible when asking about `src/new.py`, even if Git knows they are the same history.

Build a rename-aware alias set for a requested path from Git history, then use it consistently in `explain`, `brief`, and `sync`. Report the matched historical path so the user can see why the decision was included. Keep this conservative: only follow Git-detected renames, not similarity guesses invented by Whyline.

## 7. Create a durable review outcome surface

The repository documents a measured gap: implementers record decisions, while reviewer rulings often disappear into an uncommitted tracker. Wording in `AGENTS.md` was improved, but the cause and effect remain unmeasured.

Add a compact review record rather than hoping every verdict is translated into a generic note:

```text
whyline review WL-42 --actor claude --verdict approved \
  --commit <sha> --test "pytest -q: passed" \
  --finding "accepted bounded retry risk: upstream call is idempotent"
```

The durable entry should capture verdict, reviewed commit/range, findings that changed the result, accepted risks, and tests. It should not become a dump of every nit. `sync` can then distinguish implementation decisions from review evidence, and the next measurement can directly answer whether review capture improved.

## 8. Add diff-wide explanation for review and migration work

Single-line `explain` is useful interactively but expensive during a review. Add:

- `whyline explain --diff <base>..<head>`;
- `whyline explain --staged`;
- grouping by decision ID so one decision is not repeated for every changed line;
- a coverage summary: exact, heuristic, mechanical-only, and unexplained changed lines/files.

This turns Whyline from a lookup tool into a review aid and gives the project a measurable provenance-coverage signal. The output must preserve the current honesty rules: uncommitted lines and unmatched paths stay unexplained rather than inheriting a nearby file-level decision.

## 9. Turn `status` into an actionable doctor without conflating configuration and observation

`status` already does unusually careful hook inspection and distinguishes “configured” from “observed.” Extend that foundation with a `whyline doctor` command that checks:

- writable ledger and decision paths;
- parseability/conflict markers in `decisions.md`;
- instruction block freshness;
- exact hook command availability and last observation by agent;
- stale handoff/ownership state;
- configured agent binaries/models;
- oversized ledger and privacy policy.

For hooks, keep configuration, executable availability, and actual vendor observation as three separate facts. A synthetic `whyline hook test` can validate the entrypoint and write path, but it must not claim that Codex or Claude actually invoked the hook; only a real observed vendor event proves that.

## Recommended sequence

1. Introduce the versioned, lossless decision metadata and exact commit binding, with backward-compatible parsing.
2. Add decision lifecycle events and the query/show commands needed to manage them.
3. Add stale-state detection, handoff close, and ownership leases.
4. Add prompt-capture policy and ledger retention controls before the local log grows further.
5. Add rename-aware relevance and diff-wide explain on top of the stronger provenance model.
6. Add durable review outcomes and measure whether reviewer capture improves.
7. Consolidate all diagnostics under `doctor` after the new policies exist.

The unifying principle is: preserve Whyline's human-readable, local-first design, but make every confidence claim reproducible from durable identifiers rather than timing and convention alone.
