# Resume here — whyline v1

**Updated:** 2026-08-18 · **SHIPPED: whyline 0.1.2 on PyPI** · repo public at `github.com/anishmoncivarghese/whyline` · branch `main` · 174 tests · CI green on macOS+Linux × py3.11/3.13 · zero production dependencies

## One-line state

**All 12 tasks complete. The whole-branch review ran and found six Criticals — all now fixed.** Repo is live and PRIVATE at `github.com/anishmoncivarghese/whyline`; CI passes. One gate remains: the *fixes* are controller-written and unreviewed, so a scoped verification pass over `8a11ad8..HEAD` is owed before PyPI and before flipping the repo public.

## How to resume

```bash
cd /Users/anish/agentdock && git checkout feature/whyline-v1 && uv run pytest -q
```

Then read `.superpowers/sdd/2026-08-09-whyline-v1/progress.md` — the ledger, authoritative over anyone's recollection. Plan: `docs/superpowers/plans/2026-08-09-whyline-v1.md`. Spec: `docs/superpowers/specs/2026-08-09-whyline-v1-design.md`.

## Review history — all three rounds are done

Three Opus passes ran. The first verdicted **NOT SAFE TO PUBLISH** with six
Criticals; the second found two more *in the fixes for those six*; the third found
one regression in the fix for those two. All resolved, all verified on real data,
and 0.1.2 shipped after the third came back with no blockers.

The lesson, recorded because it cost three rounds to learn: **controller
self-review passed work that an independent pass immediately found Criticals in,
every single time.** Do not skip the review step on this codebase.

What the first round found, for context on how careful to be:

| | Finding |
|---|---|
| C6 | The untrusted fence was **escapable** — a note containing the closing tag pushed text into the next agent's prompt unlabelled. `decisions.md` is committed, so cloning a hostile repo was a delivery mechanism. |
| C5 | A newline in `note` could **forge a backdated entry** in the committed record, which `brief` then presented as genuine. |
| C3 | `status` said `Hook installed` when the hook was **blocked by a deny rule**, and when only one of four events was wired. |
| C4 | `--since 2026-8-1` matched nothing and reported **"No events recorded."** |
| C1/C2 | Distinct decisions sharing a first line were **silently collapsed**; a stripped id comment made one decision print twice and be attributed to two sources. |

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
11. The untrusted fence was escapable, so a cloned repo could inject into the next agent's prompt.
12. A newline in `note` forged a backdated entry in the committed record.
13. `status` reported a blocked hook as installed.
14. `--since` silently matched nothing and claimed the ledger was empty.
15. The README stated an ~18 ms cold start that was the bare interpreter baseline, not the tool. Real figures are 41-79 ms.
16. A Minor cleanup cached `shutil.which` at import, recreating the late-binding defect and hanging a test run by replacing pytest with Claude Code.

The suite was green before each. **Green tests do not ask whether the answer is true** — point every reviewer explicitly at the over-claim question.

## Open items

- **`uv.lock` is now tracked** (was a must-fix deferred minor). Still never `git add -A`; every commit uses explicit paths.
- **Published.** Repo public, `whyline` 0.1.0 through 0.1.3 on PyPI, each with a GitHub Release (notes in `docs/releases/<tag>.md`, which the release workflow reads at tag time). **npm deliberately skipped** (Python CLI; a placeholder would be squatting). **No domains** — the owner does not want a website.
- **RESOLVED by 0.1.4.** PyPI's 0.1.3 page overstated the read-side rate as 67% against a measured 50%. A README is baked into the published artifact and PyPI forbids re-uploading a version, so 0.1.3 could not be amended. The hold-until-next-release decision recorded earlier the same day was reversed within the hour and 0.1.4 shipped as a documentation-only release, because leaving a known overstatement on the front page of a tool arguing for honest records was the wrong trade at any size.
- **The local `whyline` is an editable install pointing at this repo** (`uv-receipt.toml`), so `whyline` runs the working tree, not the PyPI wheel. Convenient, and it means packaging faults are invisible locally — install the real artifact into a scratch venv before trusting a release.
- **Read-side check IN PROGRESS.** `m0/READ-SIDE-PROTOCOL.md`, thresholds fixed before collection, scored by `m0/analyse-readside.py`. Both Claude and Codex have been observed reading unprompted in sessions they owned. The instrument is a shim at `~/.local/bin/whyline`; **restore the real symlink with `m0/end-readside-collection.sh` when done.**
- **Nine deferred minors** still untriaged — test-coverage gaps, none blocking.
- **Model policy** (`feedback_subagent_models`) says Sonnet floor with Opus for hard tasks and the final review; **budget policy** (`feedback_no_extra_credits`) says never spend beyond the subscription. When they conflict, use fewer subagents rather than cheaper ones.
