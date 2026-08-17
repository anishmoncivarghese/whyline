# Resume here — whyline v1

**Updated:** 2026-08-17 · **Branch:** `feature/whyline-v1` · **135 tests passing** · zero production dependencies · wheel builds and runs standalone

## One-line state

**All 12 tasks are complete. v1 is functionally done.** One gate remains: the final whole-branch review, which could not be run because the spend limit removed subagents.

## How to resume

```bash
cd /Users/anish/agentdock && git checkout feature/whyline-v1 && uv run pytest -q
```

Then read `.superpowers/sdd/2026-08-09-whyline-v1/progress.md` — the ledger, authoritative over anyone's recollection. Plan: `docs/superpowers/plans/2026-08-09-whyline-v1.md`. Spec: `docs/superpowers/specs/2026-08-09-whyline-v1-design.md`.

## THE ONE OUTSTANDING GATE

Tasks 8, 9, 11 and 12 were **written inline by the controller with no independent reviewer** — the spend limit made subagents unavailable and the owner directed working within the subscription only. Every earlier task had a task review; these four did not.

That matters because of this project's record: **10 defects caught, 6 originating in the plan rather than an implementation**, and nearly every one was the tool claiming to know more than it did. Two of the four unreviewed tasks each carried a defect found only by accident:

- `brief` reported `Recent decisions (1 of 1)` while hiding nineteen.
- `run` exec'd a real agent binary from inside the test suite, replacing the pytest process — visible only as an odd 43-dot run with no summary line.

When budget allows, run a whole-branch review on the most capable model, pointed first at:

1. `src/whyline/brief.py` — the merge and dedup logic and its six tests.
2. `src/whyline/runner.py` — call-time resolution of `which`/`exec_fn`, and that no test path can reach a real `os.execvp`.
3. `src/whyline/render.py` — `timeline_text`, `status_payload`, `status_text`.
4. The `minor (deferred)` lines in the ledger, for triage before any release.

Then `superpowers:finishing-a-development-branch`.

## What works

Seven commands: `init`, `note`, `explain`, `brief`, `run`, `timeline`, `status` — all verified against real repository data, not only unit tests.

- `explain` resolves a line to recorded reasoning with honest confidence, and never claims `high` at file level.
- `brief` merges the local ledger with the committed `decisions.md`, deduplicates by event id, and discloses which source each note came from.
- `run` hands the terminal over via `exec` — verified for real with a harmless binary, not just a mock.
- Cold start 41-79 ms against a 200 ms budget (19 ms of that is bare interpreter startup; whyline's own cost is 23-60 ms). `explain` on a 50,000-event 6.5 MB ledger ~159 ms against 1 s, which is why there is no SQLite index. An earlier claim of ~18 ms was wrong — it was the interpreter baseline, not the tool.

## The best demonstration so far

Dogfooded on this repository, `explain src/whyline/brief.py:40` surfaced a decision recorded earlier the same day whose rejected alternative was *"merge both sources"* — exactly what the later fix went on to do — and reported **Medium** confidence with *"commit 5d8bc27 last moved this line, so verify it still applies."* The tool caught its own superseded reasoning rather than presenting it as current.

## M0 result

**Build as designed.** 19 decisions across 14 commits in `/Users/anish/CodeGraph` — Claude 150%, Codex 130%, against a 60% threshold. All carried a rationale and a concrete rejected alternative. Codex was confirmed never reminded, which also settled whether a non-Claude agent reads and acts on `AGENTS.md`.

Only the **write** side is validated. Nothing yet shows a receiving agent *reads* what was recorded — the premise of `brief` and `run`. A clean negative exists on the read side (`docs/superpowers/specs/2026-08-16-handover-observations.md` §1): a declarative `AGENTS.md` instruction was ignored unprompted while the imperative, pre-authorized one fired twice. Full method and caveats: `m0/RESULTS.md`.

## Decisions fixed (do not relitigate)

- **Name: whyline.** Free on PyPI, npm, whyline.dev, whyline.sh. Unblocked the gate open since PRD v2.0 §3.4.
- **Licence: Apache-2.0.**
- **Always free, to help fellow developers.** No paid tier, hosted sync, or team product, ever.
- **v1 = one capture mechanism, two payoffs.** No adapters, no PTY supervision, no worktrees, no roles, no SQLite, no context-injection machinery.
- **`run` execs, never supervises.**
- **`.whyline/decisions.md` committed; `.whyline/ledger.jsonl` gitignored** (raw prompt text).
- **Notes link to commits lazily** via `git blame` plus timestamp windows, recording no SHAs — so rebases and squashes cannot invalidate the ledger.
- **Zero production dependencies** (Rich dropped).
- **Gemini excluded** — free personal tier withdrawn. Agents are Claude Code and Codex.

## The pattern worth carrying forward

Every substantive defect was the tool over-claiming, and the majority came from the plan, not the implementers:

1. Nothing gitignored `ledger.jsonl` — prompt text could have reached a commit.
2. A skip guard dereferenced a possibly-`None` path.
3. `blame_line` swallowed "git is broken" as "no history".
4. File-level `explain` returned `high` without consulting git at all.
5. A fix for a false message introduced a different false message.
6. Plan test data was off by a factor of 1000.
7. Low-confidence output contradicted its own detail line.
8. JSON exposed notes for uncommitted lines at `none` confidence.
9. `explain` silently skipped unreadable ledger lines instead of warning.
10. `brief` announced "1 of 1" while hiding nineteen decisions.

The suite was green before each. **Green tests do not ask whether the answer is true** — point every reviewer explicitly at the over-claim question.

## Open items

- **`uv.lock` is untracked** by design. Never `git add -A`; every commit uses explicit paths.
- **Not published.** README says install from a clone; PyPI/npm names are free but unclaimed. Claim early if you want them.
- **Read-side check.** Consider a short experiment on whether an agent runs `whyline brief` unprompted, now that both it and `run` exist. The instruction now carries all four parts (trigger, exact command, pre-authorization, verification); whether that makes it fire is unmeasured.
- **Model policy** (`feedback_subagent_models`) says Sonnet floor with Opus for hard tasks and the final review; **budget policy** (`feedback_no_extra_credits`) says never spend beyond the subscription. When they conflict, use fewer subagents rather than cheaper ones.
