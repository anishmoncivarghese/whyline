# Run order for the plans in this folder

Set on 2026-11-15. Run one plan at a time, top to bottom. Press **Release** at the end of each group. Each plan's own `Runs after` line says the same thing; when you change the order, change both.

Finished plans are in `plans/done/`.

| # | Group | Plan | Tasks | Needs |
|---|---|---|---|---|
| 0 | Running | `agent-tools.plan.md` | TLS-1..16 | |
| 1 | Quick fixes | `console-restart.plan.md` | CRS-1..4 | |
| 1 | | `release-notes-review.plan.md` | NOTE-1..6 | |
| 1 | | `relay-live-models.plan.md` | LMD-1..2 | whyline-relay 0.2.43 (on PyPI) |
| 1 | | `assistant-scheduled-access.plan.md` | ASST-24..27 | |
| 2 | Telegram daily use | `waiting-on-you.plan.md` | WAIT-1..7 | |
| 2 | | `assistant-feedback.plan.md` | FB-1..7 | |
| 2 | | `assistant-router.plan.md` | RT-1..7 | assistant-feedback |
| 3 | Process | `raaid-log.plan.md` | RAAID-1..14 | |
| 3 | | `sdlc-git-flow.plan.md` | GIT-1..6 | waiting-on-you (for GIT-4's go-ahead verbs) |
| 3 | | `sdlc-product-owner.plan.md` | PO-1..6 | |
| 3 | | `sdlc-evidence.plan.md` | EVD-1..5 | sdlc-product-owner |
| 3 | | `sdlc-done.plan.md` | DONE-1..6 | sdlc-evidence |
| 3b | Release hardening | `security-earlier.plan.md` | SEA-1..6 | |
| 3b | | `release-safety.plan.md` | SAF-1..6 | release-notes-review (the record's notes line) |
| 3b | | `release-supply-chain.plan.md` | SUP-1..6 | |
| 4 | Agents | `agent-profile.plan.md` | PRF-1..5 | agent-tools released |
| 4 | | `agent-draft.plan.md` | DRF-1..6 | agent-profile |
| 4 | | `agent-calls.plan.md` | CAL-1..5 | agent-draft |
| 5 | Assistant extras | `assistant-memory.plan.md` | MEM-1..6 | assistant-router |
| 5 | | `assistant-checkins.plan.md` | CKN-1..5 | |
| 5 | | `assistant-research.plan.md` | RES-1..5 | assistant-router, agent-tools (knowledge packs) |
| 5 | | `assistant-triggers.plan.md` | TRG-1..5 | assistant-checkins |
| 6 | Architecture | `architecture.plan.md` | ARC-1..15 | |
| 7 | Workflows | `workflows-2-to-4.plan.md` | WF-15..27, WF-29..34 (19) | agent-tools released, assistant-feedback (WF-24) |
| 8 | Job search | `job-search-5a-companies-cv.plan.md` | CMP-1..2, CVT-1..7 | |
| 8 | | `job-search-5b-saved-searches.plan.md` | SRCH-1..6, CHK-1..3 | 5a |
| 8 | | `job-search-5c-results-apply.plan.md` | JRUN-1..5, PACK-1..2, ASF-1, JSD-1 | 5b |
| 9 | Self-improvement | `self-improvement-1-checks.plan.md` | IMP-1..10, IMP-38..39 | |
| 9 | | `self-improvement-2-fix.plan.md` | IMP-11..23, IMP-40..43 | part 1, sdlc-git-flow, whyline-relay 0.2.43 (model overrides) |
| 9 | | `self-improvement-3-report-console.plan.md` | IMP-24..37, IMP-44..46 | part 2, waiting-on-you, assistant-checkins, sdlc-done, sdlc-product-owner and raaid-log (suggestions) |
| 10 | Trading desk | `trading-desk.plan.md` | TRD-1..15 | |
| Any time | | `windows-release-gate.plan.md` | WIN-1 | |

## Rules

- **One relay at a time.** Seven of these plans each add the next database version to `src/whyline/ideas/store.py` (waiting-on-you, and the assistant feedback, router, memory, research and triggers plans). Two running side by side would collide.
- **Don't commit to a running relay's branch.** New plans and plan changes go on `main`. The release's Bring in main step carries them over.
- **Groups 6 to 10 don't depend on each other.** They can be reordered. Groups 1 to 5 are in dependency order.
- **Task ids are unique across this folder.** The check-ins plan uses CKN, because the job search plans use CHK.
