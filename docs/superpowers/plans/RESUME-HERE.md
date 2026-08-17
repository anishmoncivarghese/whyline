# Resume here — whyline v1

**Updated:** 2026-08-17. **Branch:** `feature/whyline-v1` · **135 tests passing** · zero production dependencies · wheel builds and runs standalone


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

- **M0 collection is in progress.** On 2026-08-14, Mozhima, Duet and DocSift were migrated to canonical `AGENTS.md` instructions with minimal Claude import shims, and `whyline-probe` was installed in `~/.local/bin`. CodeGraph joined as a clean-project subject on 2026-08-15 at excluded baseline `bf0430e`. Existing instruction bodies were verified after migration. Work normally for 2–3 days, then fill in `m0/RESULTS.md`; thresholds are fixed in spec §5. Tasks 8, 9 and 12 wait on the outcome.
- **`uv.lock` is untracked** by design (the plan's `git add` lists omit it). Never use `git add -A` — it would sweep the lock into an unreviewed commit. Every task's commit step uses explicit paths.
- **Deferred minors** are listed in the ledger with `minor (deferred)` prefixes. Point the final Opus whole-branch review at them for triage.
- **Model policy:** Sonnet floor for all subagents, never Haiku, Opus for genuinely hard tasks and the final whole-branch review. Tasks 1, 3 and one re-review were dispatched on Haiku before this was known; that work was independently verified and is not being redone.

## Not yet done at all

No `brief`, `run`, `timeline` or `status` command exists yet. There is no README or CI. `explain`, `note`, and merge-safe `init` are working commands; Task 10's wheel and entrypoints have been verified.
