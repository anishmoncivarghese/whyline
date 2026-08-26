# Decisions

Append-only. Written by whyline; readable without it.

## 2026-08-14 — Add CodeGraph as the clean-project M0 subject

**Because:** It tests fresh-repository bootstrap and instruction pickup that the three mature repositories cannot exercise

**Rejected:**

- Use only mature repositories — that would leave new-project behavior unmeasured

**Files:** m0/RESULTS.md

<!-- whyline-event: 936f971e4dc940fe9b1045c9e79e3f1a -->

## 2026-08-17 — brief.compose falls back to decisions.md when the ledger has no notes

**Because:** ledger.jsonl is gitignored so a fresh clone has an empty ledger but a committed decisions.md; reading only the ledger would silently break cross-machine handoff

**Rejected:**

- read only the ledger — works only on the machine that recorded the notes
- merge both sources — risks duplicate or conflicting entries with no stable id-based dedup guarantee across formats

**Files:** src/whyline/brief.py, src/whyline/decisions.py

<!-- whyline-event: 1a79534184014dfc9180ea54aaa45ec5 -->

## 2026-08-17 — Merge brief's two sources instead of choosing between them

**Because:** the ledger is gitignored and decisions.md is what travels, so a clone plus one local note hid the entire committed history and reported '1 of 1' when there were twenty

**Rejected:**

- read decisions.md only when the ledger is empty — works solely in the pristine clone state, which nobody is in after their first commit
- commit the ledger so brief always has it — puts raw prompt text in git, which the privacy decision forbids

**Files:** src/whyline/brief.py

<!-- whyline-event: 2aecb907b1f14630b697b9af35ed52eb -->

## 2026-08-17 — Resolve runner injection points at call time, not in the signature

**Because:** default arguments bind at import time, so monkeypatching runner.shutil.which had no effect and a test exec'd the real codex binary, replacing the pytest process

**Rejected:**

- patch the default argument tuple in tests — couples every test to CPython internals

**Files:** src/whyline/runner.py

<!-- whyline-event: 7db46b08486945ab8b229e9ac77c1088 -->

## 2026-08-18 — The AGENTS.md instruction must say decisions are recorded in addition to any other record-keeping

**Because:** observed 2026-08-18 in CodeGraph: an orchestrated Task 10 produced three commits and zero whyline decisions, while 42 lines of genuinely good reasoning went into the gitignored SDD ledger instead. whyline silently lost to a mechanism already active in the workflow, so the instruction must not read as the only place a record goes

**Rejected:**

- leave the wording as is — it competes implicitly with any active process and loses without signalling anything
- ingest from other ledgers — larger scope, and it would couple whyline to one particular workflow's file format

**Files:** src/whyline/agentsmd.py

<!-- whyline-event: 072c26643428418bbf20990825b9e533 -->

## 2026-08-18 — Delegation to another agent should point at whyline brief rather than re-deriving context by hand

**Because:** in the same session Claude hand-wrote a 187-line task brief containing project context it reconstructed manually, then launched codex with it. One line telling codex to run whyline brief would have replaced most of that. The copy-paste problem whyline exists to remove happened at full scale inside a repository where whyline was installed and working

**Rejected:**

- assume agents will think to run brief when delegating — they did not, in the one observation available

**Files:** src/whyline/agentsmd.py

<!-- whyline-event: 7eb00a71806b4361b634442608389a57 -->

## 2026-08-18 — M0's write-side result is bounded to direct interactive work, not orchestrated workflows

**Because:** M0 measured 19 decisions across 14 commits while agents worked directly with the human. Under an orchestrated flow with its own ledger the same repository recorded zero. The headline rate is therefore workflow-dependent and must be stated that way rather than as a general property

**Rejected:**

- treat the M0 rate as general — it would overstate a result measured under one workflow only

**Files:** m0/RESULTS.md

<!-- whyline-event: 0c921f3510014aaba79e6e7124118090 -->

## 2026-08-18 — Widen the write trigger to name reviewers, not only implementers

**Because:** "After completing any non-trivial change" describes someone who completed a change, so a reviewer following it exactly concludes it does not address them. Observed three times in CodeGraph (Tasks 10, 12, 13): the implementer recorded every time while the reviewer's rulings reached only a gitignored SDD ledger and died on clone. A trigger-coverage gap, not a compliance failure.

**Rejected:**

- Add a separate ## Reviewing section — doubles the injected block's length, and length is a real cost in a file agents skim every session
- Add a verification clause to the write half to match the read half — the write half has never had one and fires anyway (M0 measured 150%/130% against a 60% threshold), so it would change a working instruction on theory rather than evidence
- Wait for a measured before/after like the read-side check — the fix is a documentation clarification with little downside, so shipping now and noting it is unmeasured beats leaving a known gap open

**Files:** src/whyline/agentsmd.py

<!-- whyline-event: 6daf3fc3e54442e19bc8a3945b3a13f3 -->

## 2026-08-18 — Copy the replaced instruction block out instead of warning about possible loss

**Because:** 0.1.3 is the first release to change the block's content since init shipped, so it is the first to replace text inside the markers in existing repos. A human addition there vanishes silently, contradicting the project's degrade-with-a-warning invariant. Distinguishing whyline's own older wording from a human addition is impossible without retaining every prior version's text, so the replaced block is copied to AGENTS.md.whyline-bak and named in the return value rather than guessed about.

**Rejected:**

- Warn on every upgrade that content may have been lost — usually nothing was, and a warning that fires when nothing is wrong trains people to ignore it
- Keep a tuple of every prior canonical INSTRUCTION to diff against — precise, but grows without bound and silently mislabels any block a user edited into a shape matching an old version
- Preserve unrecognised lines by merging them into the new block — no rule says where they belong, and a wrong merge corrupts the instruction agents read every session

**Files:** src/whyline/agentsmd.py

<!-- whyline-event: fe102cd0ca54493194b987dc5220ceca -->

## 2026-08-18 — Write release notes as files in docs/releases/, read by the workflow at tag time

**Because:** Pushing a tag creates a tag, not a Release, so three versions shipped with no rationale visible to users — the wrong default for a tool whose purpose is preserving why. Notes live in the repo so they are reviewable in the same diff as the change they describe, and the workflow reads docs/releases/<tag>.md after publishing succeeds, since a Release pointing at a version PyPI rejected would be a lie.

**Rejected:**

- gh release create --generate-notes only — produces a commit list, which is what the existing git log already gives; kept as a visible fallback with a workflow warning so a missing file is not silent
- A single CHANGELOG.md — one file every release edits is a merge-conflict magnet, and GitHub cannot use it as per-release notes

**Files:** .github/workflows/release.yml

<!-- whyline-event: cf373ba27d7142588f3da380d4abc429 -->

## 2026-08-19 — State the read-side result as 50% at zero margin, not as a clearing of the threshold

**Because:** The docs carried 67% in prose while the table already said 50%, and the README shipped 67% in 0.1.3. The corrected figure meets the >=50% gate with nothing to spare, and the band immediately below is 'unreliable', so one unread session reclassifies the result. Stating it as 'fires' without that margin would repeat the over-claiming pattern that produced every substantive defect in this project. Also separates 3 Claude brief calls from 2 scoring reads: a mid-session brief is a real read but not the behaviour under test, which is orienting before touching code.

**Rejected:**

- Report 50% as clearing the threshold and move on — technically true and the reason the documentation decision is unchanged, but it hides that the trend across rounds is downward and that the result is one session from the unreliable band
- Delete the superseded 67% and 75% figures — leaves no trace that the number moved or that a measurement bug once inflated it, and the trend is the most informative part of the record
- Withhold the correction until the sample is larger — leaves a published README overstating a measured result, which is the exact failure this project keeps auditing itself for

**Files:** m0/RESULTS.md

<!-- whyline-event: 5c9f1f8a807c467f97ee107510218d3e -->

## 2026-08-19 — Let the README's read-side correction ride along with the next release rather than cut 0.1.4 for it

**Because:** PyPI's 0.1.3 page states the read-side rate as 67% when the measured figure is 50%. A README is baked into the published artifact and PyPI forbids re-uploading a version, so 0.1.3 cannot be amended in place. git and GitHub are already correct, 0.1.3's release notes never cite the figure, and the next substantive release carries the fix at no extra cost. Recorded in RESUME-HERE.md open items because the failure mode is not the delay, it is forgetting and shipping the overstatement again.

**Rejected:**

- Cut 0.1.4 immediately for the README alone — reaches PyPI sooner, but spends a version number on a prose edit and adds a release users must evaluate for no behaviour change
- Leave it uncorrected and unrecorded — the overstatement is one sentence on a page few read, but this project audits itself specifically for published claims exceeding evidence, so tolerating one silently is the wrong precedent

**Files:** README.md

<!-- whyline-event: 17f0e6f85f3c4ec68b458176d1d9d09f -->

## 2026-08-19 — Reverse the hold and cut 0.1.4 as a documentation-only release

**Because:** Supersedes the decision recorded minutes earlier to let the README correction wait for the next substantive release. PyPI's 0.1.3 page overstated a measured result in the direction that flatters the tool, on the front page of a project whose whole argument is recording what actually happened. That is a credibility cost, not a cosmetic one, and it outweighs spending a version number on prose. Nothing in src/whyline changed, so the release carries no behaviour risk: the only shipped difference is the README metadata PyPI renders.

**Rejected:**

- Keep the hold as recorded — consistent with the earlier decision, but it leaves the overstatement live for an unknown period with no scheduled next release, and consistency with a decision made an hour ago is not a reason to keep a worse outcome
- Amend 0.1.3 in place — impossible — PyPI forbids re-uploading a version, and the README is baked into the built artifact rather than fetched
- Bump to 0.2.0 to signal the read-side result changed — implies an interface or feature change to anyone reading semver, when nothing about the tool's behaviour moved

**Files:** docs/releases/v0.1.4.md

<!-- whyline-event: 0d91132daa454cab975dabb204e00373 -->

## 2026-08-19 — Rule Codex compliant on the read side, and record that its session boundaries are unmeasurable

**Because:** Codex ran no brief for Plan 2 Task 7, six hours after its previous one, which reads as the instruction failing. The operator confirmed Phase 2 ran in one continuous session, and the trigger is 'at the start of a session', so reading once and not re-reading per task is what the instruction asks for. The instrument could not settle it: the shim writes CLAUDE_CODE_SESSION_ID into its session field, so the field is empty for Codex by construction, and inspecting the live Codex process showed only CODEX_MANAGED_BY_NPM and CODEX_MANAGED_PACKAGE_ROOT — no session identifier exists to capture. Consequence recorded because it bounds every Codex figure already published: a gap between two Codex briefs cannot distinguish one long session from many unread ones, so the counts are counts at session start, never a rate over tasks.

**Rejected:**

- Score the missing brief as a read-side failure — would have recorded a false negative against an agent that followed the instruction exactly, and would have been the second time this instrument manufactured one — the first being the /Users/anish log location that hid every Codex read
- Derive a session key by walking the process tree to a Codex ancestor and using its start time — technically workable, but puts fragile logic inside an instrument whose only safety property is being too simple to alter what it measures, for a collection that is already concluding
- Ask Codex to run brief per task instead of per session — changes the instruction to fit the instrument rather than measuring the instruction as written, and per-task rereading is waste once the history is already in context

**Files:** m0/READ-SIDE-PROTOCOL.md

<!-- whyline-event: 094044d600734827a7944f94c2d365fd -->

## 2026-08-22 — Reclassify automatic brief reading as unreliable at 43 percent

**Because:** The extended fixed-protocol sample now shows 3 reads across 7 Claude sessions, below the 50 percent threshold; the installed shim continued collecting after the 0.1.4 documentation snapshot

**Rejected:**

- Keep publishing 50 percent — that uses a superseded 4-session snapshot and overstates current evidence
- Infer reliability from nine Codex invocations — Codex has no measurable session denominator and the count is observational

**Files:** m0/RESULTS.md, README.md

<!-- whyline-event: 3f23fe3a005a48ba8e15a1d8e80e6f8b -->

## 2026-08-22 — Treat fresh-clone explain as a correctness gap before calling the workflow complete

**Because:** resolve.explain and status_payload read only ledger.jsonl, which is gitignored, while the committed decisions.md is the promised durable context and is already merged by brief

**Rejected:**

- Call decisions.md merely human-readable fallback — the design explicitly says explain works from git and decisions.md when the hook is absent
- Accept green tests as sufficient — no test exercises explain against committed-only history

**Files:** src/whyline/resolve.py, src/whyline/render.py, tests/test_resolve.py, README.md

<!-- whyline-event: 27a41cb755ac41e28cd287e7f4eb6e99 -->

## 2026-08-22 — Use one merged history model for explain, status, and brief

**Because:** Fresh clones retain decisions.md but not the local ledger, so every read command must share the same deduplication and provenance rules; day-only timestamps cannot justify high confidence

**Rejected:**

- Keep merge logic inside brief — explain and status would continue to disagree after cloning
- Treat committed dates as exact timestamps — that would overstate temporal attribution

**Files:** src/whyline/history.py, src/whyline/brief.py, src/whyline/resolve.py, src/whyline/render.py

<!-- whyline-event: 2bd346615e0e4fc9a8bd545ee9f37f82 -->

## 2026-08-22 — Close the read-side experiment at 43 percent and lead handoffs with run

**Because:** The final fixed-threshold sample has 3 qualifying reads across 7 Claude Code sessions, which falls below the precommitted 50 percent threshold

**Rejected:**

- Keep the earlier 50 percent claim — it was an intermediate 4-session result superseded by the larger sample
- Report Codex reads as a rate — the instrument has no Codex session denominator

**Files:** README.md, m0/READ-SIDE-PROTOCOL.md, m0/RESULTS.md

<!-- whyline-event: ef602074d5664b2b8d7a253c8479391f -->

## 2026-08-22 — Keep active handoffs local while committing actor role and task on decisions

**Because:** Operational ownership and dirty-tree state belong to one checkout, while attribution on durable reasoning must survive cloning

**Rejected:**

- Commit active-handoff.json — stale owners and working-tree state would leak into other clones
- Restrict actor and role to vendor enums — custom human and workflow roles are legitimate

**Files:** src/whyline/handoff.py, src/whyline/decisions.py, src/whyline/cli.py, src/whyline/gitq.py

<!-- whyline-event: 8e310a8dab75477594bb140f3b1992df -->

## 2026-08-22 — Use token-bounded sync packets with advisory ownership warnings

**Because:** Agents need one compact relay containing task state Git state and relevant reasoning, while overlapping writes require visibility without turning Whyline into a locking orchestrator

**Rejected:**

- Include the newest ten decisions regardless of task — the measured 10.8 KB brief wastes context on unrelated history
- Enforce ownership as a lock — stale claims could block legitimate work and Git remains authoritative

**Files:** src/whyline/sync.py, src/whyline/brief.py, src/whyline/ownership.py, src/whyline/cli.py

<!-- whyline-event: 5ba393c157d944119090130b3bb230fd -->

## 2026-08-22 — Install Codex hooks separately and report configured executable and observed states

**Because:** Project-local Codex hooks require explicit trust and configuration alone cannot prove events are arriving; the official lifecycle payload exposes stable stdin fields and apply_patch command headers

**Rejected:**

- Infer writes from arbitrary shell commands — parsing shell effects is incomplete and would create false provenance
- Call an old last event broken — an idle repository can be healthy, so status reports the timestamp and age factually

**Files:** src/whyline/hooks.py, src/whyline/hook_entry.py, src/whyline/render.py, src/whyline/cli.py

<!-- whyline-event: 237cbeff831f49cb8887cc5e7f9dca20 -->

## 2026-08-22 — Complete Whyline 0.2.0 as a compact active-task relay without orchestration

**Actor:** codex
**Role:** implementer
**Task:** WL-0.2.0

**Because:** Explicit handoffs, task/file-bounded sync, attributed durable decisions, serialized advisory ownership, dual-vendor hooks, and observed health directly support two-terminal Claude and Codex work while preserving Git and the human as authorities

**Rejected:**

- Build a scheduler or shared conversation proxy — it would add credential, supervision, and vendor-output coupling outside Whyline's purpose
- Rely on automatic brief reading — the closed experiment measured only 43 percent

**Files:** src/whyline/sync.py, src/whyline/handoff.py, src/whyline/ownership.py, src/whyline/hooks.py, src/whyline/render.py

<!-- whyline-event: 176a9fe27d4b4a6e898a7ec9e936cd4b -->

## 2026-08-26 — Score distinct sessions within a fixed collection boundary, so the analyser reproduces its published result

**Because:** Two days after collection closed the script reported 12% and 'THE INSTRUCTION DOES NOT FIRE' against a published 43% and 'unreliable', so the repository contradicted itself for anyone who ran it. It counted SessionStarted events rather than sessions, and Claude Code's hook fires on resume, so 26 events represented 10 sessions with 17 from one long-lived session — the denominator tracked how often a session was reopened. It also had no closing bound, so every later session dragged the rate down. Now keyed on the session field at its earliest event and bounded at the shim's restoration mtime, it reproduces 7 sessions, 3 reads, 43% exactly.

**Rejected:**

- Pick a round close date such as Aug 23 12 — 00 UTC: yields 9 sessions and 33%, and a boundary chosen after seeing the data in the direction that flatters the result is indistinguishable from moving the goalposts — the symlink mtime is an observable event instead
- Leave the script unbounded and treat the drifting figure as more data — collection ended when the instrument was uninstalled, so later sessions were never measured under it, and counting them silently redefines the experiment after its threshold was precommitted
- Deduplicate by timestamp proximity instead of session id — guesses at boundaries the hook already records explicitly, and would merge genuinely distinct sessions that start together, as two did at 06:33:33

**Files:** m0/analyse-readside.py

<!-- whyline-event: cb01743a1ea74a83a716b7239f9d52be -->

## 2026-08-26 — Let inferred relevance rank the history instead of filtering it

**Because:** sync seeded relevance from the working tree's changed paths and passed them as a filter, so any dirty file the caller never mentioned discarded every decision recorded against another path: a repository with a full history printed 'Relevant decisions (0 of 0 for task (any))' and none of them, while brief on identical data showed them all. The installed instruction then tells the next agent to announce the context is empty, so a selection bug laundered itself into a confident false statement — the round-one Critical where brief announced '1 of 1' over a hidden history, recurring in the flagship command. select_entries now takes rank_files as a hint that orders without excluding; an explicit --task or --file still narrows, and the header names the recorded total whenever anything narrowed so 0 of 0 can never imply an empty history.

**Rejected:**

- Stop passing changed paths to selection at all — fixes the disclosure but throws away the relevance ordering that makes a budgeted packet useful mid-task
- Keep the filter and add an 'omitted' line — the count was already 0 of 0, so there was nothing to report an omission against, and it would still bury the history behind a budget the caller never set

**Files:** src/whyline/brief.py, src/whyline/sync.py

<!-- whyline-event: 1642ee865e4f450886197bae5188ca83 -->

## 2026-08-26 — State Codex mechanical capture as untested rather than working

**Because:** The release notes and README asserted that the Codex hook records sessions and file edits. No Codex hook event exists in any ledger (170 claude-code, zero codex), hook_entry dispatches on Claude Code's payload schema, and the three tests covering the path feed Claude-Code-shaped payloads with the --agent flag set, so they demonstrate labelling and apply_patch parsing rather than that Codex invokes the hook or sends that shape. Because the hook swallows every exception by design a schema mismatch would fail silently forever, so the honest surface is status, which already reports 'configured but never observed' per vendor. Code unchanged; only the prose overstated.

**Rejected:**

- Leave the claim and rely on status to correct it — the README is what a reader believes, and requiring them to run a command to discover the headline two-vendor feature is unverified is the over-claim pattern this project audits itself for
- Remove Codex hook support until confirmed — init writing .codex/hooks.json is harmless and is the prerequisite for ever observing an event, so deleting it would guarantee the gap never closes

**Files:** README.md, docs/releases/v0.2.0.md

<!-- whyline-event: fc941ba78fc5492a971e5f142b60c80e -->

## 2026-08-26 — Defer the committed-Markdown separator fix to the next release

**Because:** A comma inside a recorded path round-trips through decisions.md as two fabricated paths, and an alternative whose option contains ' — ' re-splits at the wrong point. On a fresh clone with no ledger those fabricated paths drive explain and sync relevance. Checked the real record: zero mismatches across every entry with a ledger twin, so nothing is currently corrupted. The fix changes the format of the durable artefact and needs a backward-compatible parser for entries already committed in the wild, which deserves its own pass rather than being rushed into a release being published now.

**Rejected:**

- Fix it in this release — the format change is the durable artefact's on-disk contract and a rushed parser that misreads existing 0.1.x entries would corrupt data that is currently intact
- Leave it unrecorded because it affects no current data — latent and silent is exactly the failure class this project keeps finding late, and an unrecorded known defect is one nobody will fix

**Files:** src/whyline/decisions.py

<!-- whyline-event: 88a796763d3e4a0a8259e9c409583404 -->
