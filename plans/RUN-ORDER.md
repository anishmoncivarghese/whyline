# Run order for the plans in this folder

Set on 2026-11-15. Run one plan at a time, top to bottom. Press **Release** at the end of each group. Each plan's own `Runs after` line says the same thing; when you change the order, change both.

Finished plans are in `plans/done/`.

`quick-fixes.plan.md` joins four small plans (console-restart, release-notes-review, relay-live-models, assistant-scheduled-access) so they run in one relay and ship in one release. Their task ids are unchanged. It also carries RDF-1..5: three fixes from releasing 0.3.74, new agents personal by default, and inline agent settings with whyline-relay 0.2.44 as the minimum. `telegram-daily-use.plan.md` does the same for waiting-on-you, plan-queue, assistant-feedback and assistant-router.

`watch-agents.plan.md` was started on 2026-11-17 ahead of agent-setup and check-ins. Check-ins (CKN-1..5) were moved into it so it could carry on, and agent-setup now runs after it.

| # | Group | Plan | Tasks | Needs |
|---|---|---|---|---|
| 0 | Done | `done/agent-tools.plan.md` | TLS-1..16 | released as whyline 0.3.74 on 2026-11-15 |
| 1 | Done | `done/quick-fixes.plan.md` | CRS-1..4, NOTE-1..6, LMD-1..2, ASST-24..27, RDF-1..5 (21) | released as whyline 0.3.75 on 2026-11-17 |
| 1b | Done | `done/watch-agents.plan.md` | WCH-1..11, CKN-1..5 (16) | released as whyline 0.3.76. Check-ins (CKN-1..5) ran inside it |
| 1c | Agent setup | `agent-setup.plan.md` | PKR-1..4, AMD-1..4, FLD-1..3, SKC-1..6, CON-1..4, MKT-1..3, RSK-1..3, LRV-1..3, DOC-1 (31) | watch-agents (the same New agent form), quick-fixes (RDF-4, personal agents and the skill picker's scope; LMD-2, the model dropdowns), whyline-relay 0.2.45 for LRV-1 (whyline-relay's `plans/live-run-settings.plan.md`, LRS-1..4) |
| 1d | Release Resolve | `release-resolve.plan.md` | RSO-1..10 | quick-fixes released (RDF-1, the trial merge) |
| 1e | Research | `research.plan.md` | RSR-1..12 | watch-agents (WCH-3, the page fetch), agent-tools (knowledge packs). Replaces `assistant-research.plan.md` (RES-1..5) |
| 2 | Telegram daily use | `telegram-daily-use.plan.md` | WAIT-1..7, QUE-1..11, FB-1..7, RT-1..8 (33) | research (RT-8, the research route) |
| 3 | Process | `raaid-log.plan.md` | RAAID-1..14 | |
| 3 | | `sdlc-git-flow.plan.md` | GIT-1..6 | telegram-daily-use (WAIT-5, for GIT-4's go-ahead verbs) |
| 3 | | `sdlc-product-owner.plan.md` | PO-1..6 | |
| 3 | | `sdlc-evidence.plan.md` | EVD-1..5 | sdlc-product-owner |
| 3 | | `sdlc-done.plan.md` | DONE-1..6 | sdlc-evidence |
| 3b | Release hardening | `security-earlier.plan.md` | SEA-1..6 | |
| 3b | | `release-safety.plan.md` | SAF-1..6 | quick-fixes (NOTE-4, the record's notes line) |
| 3b | | `release-supply-chain.plan.md` | SUP-1..6 | |
| 4 | Agents | `agent-profile.plan.md` | PRF-1..5 | agent-tools released, agent-setup (the same New agent form) |
| 4 | | `agent-draft.plan.md` | DRF-1..6 | agent-profile |
| 4 | | `agent-calls.plan.md` | CAL-1..5 | agent-draft |
| 5 | Assistant extras | `assistant-memory.plan.md` | MEM-1..6 | telegram-daily-use (the router) |
| 5 | | `assistant-triggers.plan.md` | TRG-1..5 | watch-agents (CKN-1, the gates) |
| 6 | Architecture | `architecture.plan.md` | ARC-1..15 | |
| 7 | Workflows | `workflows-2-to-4.plan.md` | WF-15..27, WF-29..34 (19) | agent-tools released, telegram-daily-use (FB, for WF-24) |
| 8 | Job search | `job-search-5a-companies-cv.plan.md` | CMP-1..2, CVT-1..7 | |
| 8 | | `job-search-5b-saved-searches.plan.md` | SRCH-1..6, CHK-1..3 | 5a |
| 8 | | `job-search-5c-results-apply.plan.md` | JRUN-1..5, PACK-1..2, ASF-1, JSD-1 | 5b |
| 8 | | `job-search-5d-after-apply.plan.md` | JAA-1..10 | 5c, research (JAA-8) |
| 9 | Self-improvement | `self-improvement-1-checks.plan.md` | IMP-1..10, IMP-38..39 | |
| 9 | | `self-improvement-2-fix.plan.md` | IMP-11..23, IMP-40..43 | part 1, sdlc-git-flow, whyline-relay 0.2.43 (model overrides) |
| 9 | | `self-improvement-3-report-console.plan.md` | IMP-24..37, IMP-44..46 | part 2, telegram-daily-use (WAIT), watch-agents (CKN-3, quiet hours), sdlc-done, sdlc-product-owner and raaid-log (suggestions) |
| 10 | Trading desk | `trading-desk.plan.md` | TRD-1..15 | |
| Any time | | `windows-release-gate.plan.md` | WIN-1 | |

## Rules

- **One relay at a time.** Seven of these plans each add the next database version to `src/whyline/ideas/store.py` (telegram-daily-use, which holds three of them: waiting cards, feedback and the router; and the assistant memory, research and triggers plans). Two running side by side would collide.
- **Don't commit to a running relay's branch.** New plans and plan changes go on `main`. The release's Bring in main step carries them over.
- **Groups 6 to 10 don't depend on each other.** They can be reordered. Groups 1 to 5 are in dependency order.
- **Task ids are unique across this folder.** The check-in tasks (in `watch-agents.plan.md`) use CKN, because the job search plans use CHK.
