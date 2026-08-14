# Resume here — whyline v1

**Updated:** 2026-08-14.
**Branch:** `feature/whyline-v1` · **Code head:** `1ca4a66` · **92 tests passing** · zero production dependencies

## One-line state

Tasks 1–7 and 10 are complete and reviewed. Continue with **Task 11 — `timeline` + `status`** while Tasks 8, 9 and 12 remain gated on M0 collection.

## How to resume

```bash
cd /Users/anish/agentdock && git checkout feature/whyline-v1 && uv run pytest -q
```

Then read, in order:
1. This file.
2. `.superpowers/sdd/2026-08-09-whyline-v1/progress.md` — the ledger. It is authoritative over anyone's recollection, including mine. Every completed task has a `Task <N>: complete` line.
3. `docs/superpowers/plans/2026-08-09-whyline-v1.md` — the plan.
4. `docs/superpowers/specs/2026-08-09-whyline-v1-design.md` — the spec.

Execution follows `superpowers:subagent-driven-development`: fresh implementer per task, task review after each, Opus review of the whole branch at the end.

## Task status

| Task | State |
|---|---|
| 1 — M0 cooperation probe | ✅ complete (artifacts only; collection not started) |
| 2 — Scaffold, CLI shell, paths | ✅ complete |
| 3 — Events + ledger | ✅ complete (2 fix rounds) |
| 4 — Git queries | ✅ complete (1 fix round) |
| 5 — Resolution + confidence | ✅ complete (2 fix rounds) |
| 6 — `explain` command | ✅ complete (1 fix round) |
| 7 — `note` + decisions.md | ✅ complete |
| 10 — Hook + `init` | ✅ complete (1 fix round) |
| **11 — `timeline` + `status`** | **pending — start here** |
| **GATE** | **M0 results needed before 8, 9, 12** |
| 8 — `brief` | gated on M0 |
| 9 — `run` | gated on M0 |
| 12 — Perf, CI, README | gated on M0 |

Execution order and the reason only 8/9/12 are gated: plan §"Execution order — ruling 2026-08-09".

### Immediate next action

Task 11 — implement `timeline` and `status`. Start M0 collection independently; it is still required before Tasks 8, 9 and 12.

## The milestone is real

`explain` works end to end on this repository's own history:

```
$ uv run whyline explain src/whyline/resolve.py:1
src/whyline/resolve.py:1

Last touched by   anish
Commit            9c56f69  ·  2026-08-10

Confidence        None — nothing is recorded for this line.
                  no reasoning recorded for this line
```

Cold start 18 ms against the 200 ms budget. `--json` works. The `Confidence: None` is correct, not a bug — nothing has been recorded yet.

## Decisions fixed (do not relitigate)

- **Name: whyline.** Free on PyPI, npm, whyline.dev, whyline.sh. Unblocks the gate open since PRD v2.0 §3.4.
- **Licence: Apache-2.0.**
- **Always free. Built to help fellow developers, not to earn money.** No paid tier, hosted sync, or team product, ever.
- **v1 = one capture mechanism, two payoffs.** No adapters, no PTY supervision, no worktrees, no roles, no SQLite, no context-injection machinery.
- **`run` execs, never supervises** — hands the terminal over, so no vendor output format can break it.
- **`.whyline/decisions.md` committed; `.whyline/ledger.jsonl` gitignored** (it holds raw prompt text).
- **Notes link to commits lazily** via `git blame` plus timestamp windows, recording no SHAs — so rebases and squashes cannot invalidate the ledger.
- **Rich dropped**; zero production dependencies.
- **Gemini excluded** — its free personal tier is closed. Agents are Claude Code and Codex.

## What the review loop actually caught

Worth knowing, because it shapes how to run the rest: **every substantive defect so far was the tool claiming to know more than it did, and four came from the plan rather than from an implementer.**

1. Nothing gitignored `ledger.jsonl` — prompt text could have reached a commit.
2. A skip guard dereferenced a possibly-`None` path — suite crashed instead of skipping on a source tarball.
3. `blame_line` swallowed "git is broken" as "no history" — a misconfigured git would have made `explain` confidently report no reasoning for every line in the repo.
4. File-level `explain <file>` returned **`high` confidence without consulting git at all** — even for a file not in git, even outside a repository.
5. The fix for a false message introduced a different false message ("timestamps are unreadable" for timestamps that were perfectly readable and merely postdated the line).
6. Plan test data was off by a factor of 1000 (epoch 1,000,000 vs 1,000,000,000).
7. Low-confidence output said no reasoning existed while its detail line said reasoning did exist but could not be attributed.
8. JSON exposed file-level notes for uncommitted and untracked lines even when confidence was `none`.
9. `explain` silently skipped unreadable ledger lines instead of issuing the warning required by the specification.

The suite was green before each of these. Green tests do not ask whether the answer is *true*. Keep pointing reviewers at the over-claim question explicitly.

## Open items

- **M0 collection has not started.** AgentDock now has the production `AGENTS.md`/`CLAUDE.md` shared-instruction setup, but the formal probe is not installed into Mozhima, Duet or DocSift. Install the probe, append the M0 snippet to each canonical `AGENTS.md`, add the Claude import shim, work normally 2–3 days, then fill in `m0/RESULTS.md`. Thresholds are fixed in spec §5. Tasks 8, 9, 12 wait on the outcome.
- **`uv.lock` is untracked** by design (the plan's `git add` lists omit it). Never use `git add -A` — it would sweep the lock into an unreviewed commit. Every task's commit step uses explicit paths.
- **Deferred minors** are listed in the ledger with `minor (deferred)` prefixes. Point the final Opus whole-branch review at them for triage.
- **Model policy:** Sonnet floor for all subagents, never Haiku, Opus for genuinely hard tasks and the final whole-branch review. Tasks 1, 3 and one re-review were dispatched on Haiku before this was known; that work was independently verified and is not being redone.

## Not yet done at all

No `brief`, `run`, `timeline` or `status` command exists yet. There is no README or CI. `explain`, `note`, and merge-safe `init` are working commands; Task 10's wheel and entrypoints have been verified.
