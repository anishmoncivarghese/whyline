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

## 2026-08-27 — Give the fence sanitiser and token estimate one home in whyline.textbudget

**Because:** render needed clipped for a single line of status output and reached into sync for it, which dragged brief, handoff, ownership, state and sync itself into every explain, timeline and status invocation — 14 modules where the baseline was 9 — against cli.py's documented 200ms cold-start budget and against render.py's own docstring claiming no import cost. Fixing it also removed a real duplication: the fence regex, which exists because of the C6 Critical where a note containing the closing tag escaped the fence, had been copied into brief and sync, so a security control had two definitions free to drift. textbudget imports only re and math, so render is back to baseline plus one dependency-free module.

**Rejected:**

- Inline a local trim helper in render — drops the import and restores the docstring, but leaves the fence pattern defined in two places, which is the condition that lets a security fix rot in one copy
- Keep importing sync._clipped and just fix the docstring — makes the claim true by lowering it, leaves the cold-start cost on three commands that never touch handoffs, and keeps a private cross-module dependency nothing in sync announces
- Leave it as a nit and ship — the cost is small, but the docstring was asserting something false, which is the exact class of defect this project has found sixteen times

**Files:** src/whyline/textbudget.py, src/whyline/render.py

<!-- whyline-event: 8d3b8e8dc17648228413c1421bf18995 -->

## 2026-08-27 — Default the init prompts to yes, and treat a closed stdin as consent

**Because:** The prompts read [y/N], so the likeliest first run — whyline init then Enter twice — created .whyline/ and nothing else: no instruction block, so no agent recorded or read anything, and no hooks, so nothing mechanical was captured. It printed Initialised and exited 0, then status advised running the command just run. A closed stdin was worse: EOFError counted as no, so init in a Makefile, devcontainer or CI step installed nothing and reported success where nobody watches a prompt. Running init is the consent; the prompts exist to allow opting out. Found by testing the published package from a clean uninstall rather than the editable dev tree, which had never exercised a fresh first run.

**Rejected:**

- Keep no as the default because these commands modify files the user owns — the conservatism is misplaced — init is already an explicit opt-in, and since 0.2.0 the replaced block is copied to .whyline/AGENTS.md.bak, so the safety is in the backup rather than in a default that yields an inert tool
- Warn loudly and exit non-zero when nothing was installed — honest, but it still leaves the common path failing and asks the user to diagnose an outcome they never intended
- Remove the prompts and always install — removes a legitimate opt-out for anyone who wants the state directory without whyline editing their instruction files, which --no-instructions and --no-hooks now serve

**Files:** src/whyline/cli.py

<!-- whyline-event: b77e6dc79c5b461bbc0a178d6e9f3d6c -->

## 2026-08-27 — Document that Codex hook trust applies only to future events

**Because:** The natural setup order — init, open codex, /hooks, trust, work — means the approving session has already passed its SessionStart, so that event is never recorded for the first session. Nothing is broken, since UserPromptSubmit fires on the next prompt and status flips to observed, but a user who trusts the hooks and immediately checks status sees 'configured but never observed' and concludes the hook is broken. The README now states the ordering and also that Codex lists the entries as Installed 1, Active 0 until approved, which is the same state status describes — so the two surfaces explain each other instead of each looking like a fault. Found by clean-uninstall testing against the published package, the same run that surfaced 0.2.1's init defect.

**Rejected:**

- Fire a synthetic SessionStart when trust is granted — whyline cannot detect trust being granted, and inventing an event that did not happen would put a false record in the ledger
- Fold it into the next feature release — the sentence costs nothing and the confusion lands at first run, which is where a new user decides whether the tool works

**Files:** README.md

<!-- whyline-event: 3ee3d5934d6744c29dfb130795757031 -->

## 2026-08-31 — Closed stale WL-0.2.0 handoff instead of leaving it dangling

**Actor:** claude
**Role:** assistant
**Task:** WL-0.2.0

**Because:** Handoff pointed at commit a1e63b1, several commits behind HEAD (ea9d1ac); the reviewed work it described already shipped across v0.2.0, v0.2.1, and v0.2.2

**Rejected:**

- Leave it as ready-for-review — would mislead future sessions into re-reviewing already-shipped work

<!-- whyline-event: 89d35311eae94f4e8420c9472c70de2c -->

## 2026-09-20 — Relay routes only on agent-written whyline handoffs, and pauses when one is missing

**Actor:** claude
**Role:** architect
**Task:** WL-RELAY-0.1.0

**Because:** The open question the relay exists to answer is whether agents still record handoffs and decisions under automation; a relay that writes the records itself cannot measure that

**Rejected:**

- Agent writes verdict.json and the relay translates it into whyline handoff — routes more reliably but destroys the measurement
- Accept either protocol, prefer a real handoff — two protocols to document and test, muddier metric, for a case a clear pause already handles

**Files:** docs/superpowers/specs/2026-09-20-whyline-relay-design.md

<!-- whyline-event: b50c273677684a628c64a325d5342dfa -->

## 2026-09-20 — whyline-relay ships as a separate repository and distribution, not inside whyline

**Actor:** claude
**Role:** architect
**Task:** WL-RELAY-0.1.0

**Because:** whyline's published position, recorded in the v0.2.0 decision, is that it does not orchestrate; shipping the scheduler separately keeps that literally true and leaves whyline-only users unaffected

**Rejected:**

- Same repo, second package — one release process, but the repo then contains the orchestrator it disclaims
- uv tool install whyline[relay] — simplest install, but whyline itself would ship an orchestrator

**Files:** docs/superpowers/specs/2026-09-20-whyline-relay-design.md

<!-- whyline-event: 0c868e24a13c4022bc72d5d30f69747b -->

## 2026-09-20 — Relay treats vendor agent commands as configuration and needs no change to whyline

**Actor:** claude
**Role:** architect
**Task:** WL-RELAY-0.1.0

**Because:** handoff --status is free-form so approved/assigned/blocked already work against 0.2.2; and codex-cli 0.155.1 has already dropped --full-auto in favour of -s workspace-write, so hardcoding vendor flags would break the tool on the next CLI release

**Rejected:**

- Add a status enum to whyline core — couples two release cycles for no gain
- Hardcode the PRD's codex --full-auto command — the flag no longer exists in the installed CLI

**Files:** docs/superpowers/specs/2026-09-20-whyline-relay-design.md

<!-- whyline-event: 27f56ac705f94ac183939aead956a085 -->

## 2026-09-20 — Relay plan splits routing, state, whylinecmd and init out of the spec's loop.py and cli.py

**Actor:** claude
**Role:** architect
**Task:** WL-RELAY-0.1.0

**Because:** The routing table is the only place the relay decides anything, and as a pure function it is exhaustively testable without launching a subprocess; the other three are contact surfaces with git, disk and whyline that each test better alone

**Rejected:**

- Follow the spec's nine-module table literally — loop.py would carry the routing table, the stop file, the resume record and the plan walk, which is the file a reviewer can least afford to misread

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: 5b85411dfb3c49c294cf8806e5bffd14 -->

## 2026-09-20 — Build whyline-relay with Codex as developer and Claude as sole reviewer and committer, not subagent-driven implementation

**Actor:** claude
**Role:** planner
**Task:** RELAY-PLAN

**Because:** The tool being built automates exactly this Codex-implements / Claude-reviews-and-commits split, so building it that way exercises the workflow and its handoff record on real work; Codex's workspace-write sandbox makes .git read-only, so 'Codex never commits' holds by construction and Claude verifies HEAD is unmoved before reviewing

**Rejected:**

- Keep subagent-driven-development with Claude implementing — no independent reviewer, and it never exercises the Codex path the tool depends on
- Let Codex commit its own work — the reviewer would judge a diff already in history and could not cleanly reject it
- Re-run Tasks 1-4 through Codex — they are committed and tested; redoing them spends quota for no defect found

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: d3e830accd6b4877809630cca702cc7d -->

## 2026-09-20 — Amend whyline-relay plan Task 5 after review: strict UTF-8 decoding and SIGTERM-only timeout replaced

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-5

**Because:** Both failed when probed with real processes (UnicodeDecodeError leaving an orphan; SIGTERM-ignoring agent outliving a 1s timeout by 6s). Fixed code and two tests were verified in a scratch copy against the old code before being written into the plan

**Rejected:**

- Leave the plan and patch agents.py in whyline-relay only — Codex must follow the plan verbatim, so the plan and the code would disagree

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: 1f6e3845f3c8490fb2eb1597762fdb17 -->

## 2026-09-20 — Amend whyline-relay plan Task 6 after review: commit_verified substring match replaced by whole-id match

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-6

**Because:** Real-repo probe showed RELAY-10 verifying RELAY-1; fix and 7 tests verified in a scratch copy (3 fail on old, 14 pass on new) before being written into the plan

**Rejected:**

- Patch gitcheck.py in whyline-relay only — Codex follows the plan verbatim, so plan and code would disagree

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: cdd223aab160430d9355801bf0ac2dc3 -->

## 2026-09-20 — Amend whyline-relay plan Task 7 after review: decide() now routes on (to_actor, status) as the spec's table requires

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-7

**Because:** Real probe showed three mis-addressed handoffs routing to an agent where spec 5.2 says pause; fix and 3 tests verified in a scratch copy (3 fail on old, 15 pass on new, 66 total) before being written into the plan; step counts updated to 12 and 66

**Rejected:**

- Patch routing.py in whyline-relay only — Codex follows the plan verbatim, so plan and code would disagree

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: 94e99a49c5174c88a8acef0a2a3e336b -->

## 2026-09-20 — Endorse whyline-relay's deterministic scheduler architecture, but treat autonomy as supervised until recovery and bookkeeping gaps are closed

**Actor:** codex
**Role:** reviewer
**Task:** RELAY-DESIGN-REVIEW

**Because:** the handoff-driven Codex-to-Claude loop directly removes manual prompt copying and terminal switching, while branch guards, commit verification, timeouts and explicit pauses bound risk; however the plan does not preserve the spec's exact resume decision point, does not validate handoff task ids, and leaves plan checkbox persistence ambiguous

**Rejected:**

- Give agents unrestricted control — permission, branch and no-push boundaries are essential even in unattended operation
- Call the design production-ready before M2 — real vendor CLI behavior is the central unproven assumption and the plan correctly requires a watched checkpoint

**Files:** docs/superpowers/specs/2026-09-20-whyline-relay-design.md, docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: bb343b5bd3464e47a92c1195b7e4f4ed -->

## 2026-09-20 — Pre-review whyline-relay plan Tasks 8-13 by building them in a scratch copy and probing with real processes, then fold 10 fixes into the plan before dispatching to Codex

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-PLAN

**Because:** Tasks 5-7 each shipped a plan defect that cost a Codex round. Transcribing Tasks 8-13 exactly as written passed every plan test, so the defects were all in behaviour the tests did not cover: rate-limit words in ordinary output discarded successful handoffs; the reviewer's git add -A committed the relay's logs; run_plan ticked a stale copy of the plan; an unknown --only id succeeded silently; guard refused the default start from main and --branch did not lift it; resume ignored the saved base commit and branch; Ctrl+C left the agent running and saved no state; init checked a .codex/trust.json nothing creates and crashed without a terminal; and Task 13's push guard failed on Task 12's own deny list, which would have had Codex delete the deny rule. 17 new or changed tests fail on the original code and pass on the fixed code (126 pass); the round-cap test passes on both by design (it fills the coverage gap)

**Rejected:**

- Hand Tasks 8-13 to Codex as written and review each — the previous three tasks each needed a second round, and the Ctrl+C and F3 defects would have reached a real run or inverted a safety rule
- Fix the plan by reading it only — every defect above passed the plan's own tests and was found only by running real processes and repositories
- Also patch the review prompt so the reviewer reads untracked files (git diff omits new files) — noted for the M2 watched run instead, since it is outside Tasks 8-13 and changes committed Task 4 text

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: 321176aa28d344ab8c2e83dcdc90924b -->

## 2026-09-20 — Fold Codex's review of the whyline-relay plan into Tasks 8-10 and 12: resume at the decision point, task-id check on handoffs, relay commits the plan tick, clean-tree check after approval, allowlist is not a security boundary

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-PLAN

**Because:** Codex's three points were probed before acting: resume after Codex had already handed off re-ran Codex first (spec 5.6 says same decision point), and the tick left plan.md modified so it rode into the next task's commit with the last tick uncommitted; the task-id point was valid but smaller (a mislabelled handoff cannot route wrong work or tick a box, it only goes unnoticed). Resume now derives the next move from the handoff record, the single source of truth, and saves the real round and last_handoff_id. The owner chose the relay committing only plan.md after verifying Claude's commit. The dirty check runs before the tick so a pause leaves the task unticked and resume simply re-verifies. 11 new tests fail on the previous code and pass on the new (137 pass)

**Rejected:**

- Persist next actor and feedback in state as Codex suggested — derivable from the handoff record, which cannot go stale, and consistent with routing solely on that record
- Claude's commit includes the tick — ticks before the relay verifies, weakening ticked-means-committed
- Keep checkboxes only in relay state — plan.md would no longer show progress
- Widen commit_verified to search every commit since base — modifies approved Task 6 and is not needed; the pause message tells the user to stash rather than commit leftovers

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: 44fe0d13188b48d4afea81bae94a33ec -->

## 2026-09-20 — M2 real-CLI run of whyline-relay against codex-cli 0.155.1 and claude 2.1.278 found three plan assumptions wrong or incomplete

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-8

**Because:** Ran the real relay in a throwaway repo. (1) Codex worked headless under exec -s workspace-write, handed off from inside the sandbox and did not commit, but only because its prompt said so: when asked to git commit it did (probe commit 99411a5), so the sandbox does NOT make .git read-only and the spec's 'Codex never commits by construction' is false. (2) claude -p --permission-mode acceptEdits denied every Bash command (git add, git commit, whyline note, whyline handoff), and the project .claude/settings.json allowlist that init would write is ignored ('this workspace has not been trusted') until a trust dialog is accepted interactively; passing the same file with --settings is honored (a discriminating test: whyline sync allowed with the flag, denied without). With --settings, Claude reviewed, committed with the task id and Co-Authored-By trailer, and handed off approved. (3) The pause reason 'exited without handing off' hid the cause, which the claude JSON output names in permission_denials. Also confirmed live: resume derives the next move from the handoff record (only Claude ran on resume), the relay's logs stayed out of the commit, nested claude -p works, and Claude read the untracked hello.py without a git diff. Cost was about 7k Codex tokens and under 0.10 USD per Claude review turn

**Rejected:**

- Treat the sandbox as the guard and drop the runtime check — measured false
- Rely on init writing .claude/settings.json — ignored in any workspace never trusted interactively, so a fresh checkout silently gets no permissions

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: 005c2dbb0f454371876f68d12ee6e6d7 -->

## 2026-09-20 — Fold the M2 real-CLI findings into the whyline-relay plan and spec as Task 8b

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-8b

**Because:** Ran the real relay against codex-cli 0.155.1 and claude 2.1.278. Measured: Codex commits when asked, so the sandbox is not the guard and the relay now checks HEAD after every Codex turn; claude -p with acceptEdits denies all Bash, and a project .claude/settings.json allowlist is ignored in an untrusted workspace, so init now writes a relay-owned .whyline/relay/claude-settings.json passed with --settings (missing file fails loudly, no API call); pause reasons now quote the denied commands or the agent's last output line. Task 8b is a separate task because Task 8 is already committed. Verified by applying the plan's literal Task 8b instructions to the committed Task 8 tree (22 and 86 tests pass) and by a full end-to-end run of the assembled tool against the real CLIs: start from main, Codex implemented without committing, Claude reviewed and committed via the default command, the relay ticked and committed only plan.md, tree clean, exit 0. Spec corrected in five places

**Rejected:**

- Keep writing .claude/settings.json and require a one-time interactive trust dialog — a fresh checkout silently gets no permissions and the failure looks like the agent misbehaving
- Pass permissions as --allowedTools — also works, but a variadic option would swallow the prompt appended as the final argument, and it duplicates a reviewable file into a command line
- Enforce no-commit with a git hook keyed on an environment variable — an agent can pass --no-verify, and the post-turn HEAD check is simpler and detects it regardless

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md, docs/superpowers/specs/2026-09-20-whyline-relay-design.md

<!-- whyline-event: d710db58eaad46caa0b6d01db65c403d -->

## 2026-09-20 — Stub the CLI notifier in tests so the suite never pops real desktop notifications (whyline-relay plan Task 11)

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-PLAN

**Because:** An osascript tripwire showed the pre-reviewed suite made 3 real osascript calls, because tests that run cli.main start reach notify.send; it broke the plan's own rule that tests launch no real external process, and would have popped notifications on the owner's Mac on every Codex test run. An autouse fixture in tests/conftest.py replaces cli.notify with a no-op namespace: 0 calls afterwards, 140 tests pass, and test_notify.py still exercises the real notifier code because it imports the module directly

**Rejected:**

- Patch notify.send globally in conftest — it would neuter test_notify's own send tests
- Skip notifications when a CI or test env var is set — production code should not know it is under test

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: 4d487002dd214b908f252e9b56aab17f -->

## 2026-09-20 — Pre-run probes of Codex's sandbox changed whyline-relay Tasks 11 and 13 before the continuous Task 9-13 run

**Actor:** claude
**Role:** reviewer
**Task:** RELAY-PLAN

**Because:** Probed the real Codex sandbox (codex-cli 0.155.1, -s workspace-write): pgrep and pkill fail with 'sysmond service not found', so Task 11's pgrep-based interrupt test would pass vacuously under Codex; it now records the agent pid in a file and checks os.kill(pid, 0), which the sandbox permits (killpg, kill(pid,0) and self-SIGINT all match the unsandboxed control), and it fails without the kill-on-interrupt fix. An osascript tripwire showed the suite popped 3 real desktop notifications, now stubbed by tests/conftest.py. Task 13 Step 7 writes outside the workspace so it is Claude's, and Step 4's uv build may lack network in the sandbox so it may be skipped and run by Claude

**Rejected:**

- Leave the pgrep test — green under Codex but proves nothing there

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: fb2f18772b3e4298a8edbfadfb4646ca -->

## 2026-09-20 — whyline-relay 0.1.0 complete: Tasks 1-13 built by Codex and reviewed and committed by Claude; deviations from the plan and what real runs changed

**Actor:** claude
**Role:** reviewer
**Task:** WL-RELAY-0.1.0

**Because:** Tasks 9-13 were built by Codex in one continuous uncommitted run, so the per-task commits were reconstructed from the plan's stage trees and checked against Codex's tree: all 33 source and test files, LICENSE and pyproject are byte-identical to Codex's; per-task test counts (104, 118, 125, 138, 140) matched its reports. Deviations: RELAY_IGNORE sits at the top of gitcheck.py (Task 8, accepted); cli.py orders two helpers differently from the plan's prose assembly (Task 12 takes Codex's file); the README was corrected by the reviewer for four verified defects (whyline not listed as a requirement, a worked example that fails on a fresh project, an undisclosed tick commit, the Codex commit caveat), a deliberate departure from the developer-only split, disclosed in the commit. My own process error, found by checking history: the staging script overwrote decisions.md and dropped earlier review notes; the five local commits were redone. Beyond the plan, real runs changed: Codex's sandbox does not stop it committing so the relay checks HEAD (Task 8b); Claude ignores project allowlists in untrusted workspaces so init writes .whyline/relay/claude-settings.json passed with --settings (Task 8b, 12); the suite popped real desktop notifications (stubbed in Task 11); pgrep and pkill fail in Codex's sandbox so the interrupt test uses a pid file (Task 11). Final proof: the committed tool run against the real codex 0.155.1 and claude 2.1.278 following the README, two tasks, 2m23s: relay/demo created, Codex never committed, Claude committed each task with the trailer and no relay logs, the relay ticked and committed only plan.md each time, tree clean, state cleared, exit 0. Open: the README spec link 404s until agentdock is pushed; agentdock's plan, spec and decisions.md changes are uncommitted; Codex turn time varied from under 1 to about 5 minutes

**Rejected:**

- One combined commit for Tasks 9-13 — loses the per-task history the protocol and commit_verified rely on
- Send the README back to Codex — the defects came from a thin plan instruction, which is now fixed, and a further round costs a Codex run for a factual edit

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md, docs/superpowers/specs/2026-09-20-whyline-relay-design.md

<!-- whyline-event: fd7ac3c3c7484c568597dd5a45856d68 -->

## 2026-09-21 — Publish whyline-relay 0.1.0 as a public repository and on PyPI through Trusted Publishing, before adding remove or any whyline init integration

**Actor:** claude
**Role:** reviewer
**Task:** WL-RELAY-0.1.0

**Because:** The owner approved the order: ship what is verified, add remove next, integrate with whyline init after real use. The relay is self-contained under .whyline/relay/ and touches none of whyline's files, so a later combined install needs no migration. Published with whyline's own pattern: a tag push runs the suite on Linux and macOS (Python 3.11 and 3.13) and publishes via OIDC with no API token, after a gate that refuses an sdist containing home paths or internal notes; I ran that gate and twine check on the exact tree before tagging. Verified from outside after release: PyPI lists the wheel and sdist (Apache-2.0, Python >=3.11), a clean venv installs and runs whyline-relay, no home paths in the installed package, and the GitHub Release has both assets. The CI and release workflows, project URLs and release notes were written by the reviewer, not Codex, and the commit says so

**Rejected:**

- Wait for Task 14 (remove) before publishing — departs from the approved order and delays a verified release
- Bundle the relay into whyline's install now — couples release cycles with a published package that has users, and the relay has only run toy plans on one OS

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: d760628d3860471a8ec91d6182e2c0a4 -->

## 2026-09-21 — Release whyline-relay 0.2.0, built by running the relay on its own plan, after the first real-world test of the automation

**Actor:** claude
**Role:** reviewer
**Task:** WL-RELAY-0.2.0

**Because:** The owner ran the relay for real on nine tasks (RELAY-14 to 22), each implemented by Codex and reviewed and committed by Claude, one round each, with independent acceptance tests (69) written before each run and run against the result. Real use surfaced what tests had not: the terminal was silent between turns and status said 'not running' during a run (progress lines, running marker); a review approved without running the tests because it copied the implementer's env-prefixed command and the allowlist denied it (fail-closed review prompt, wider permissions); a blocked handoff's question was hidden (shown in the pause); and re-running init silently overwrote edited files, found while writing the README (init keeps edited files, --overwrite replaces). Two of my own checks were wrong and I traced both to the test, not the code. Published through Trusted Publishing after a pre-flight (twine check, release gate, wheel install) on the exact tag tree; verified from outside: PyPI lists 0.2.0 with both files, a clean install reports 0.2.0, Apache-2.0, no home paths, and the GitHub Release has both assets. PyPI's JSON API lagged the release by about a minute, so a check made too early looked like a failure

**Rejected:**

- Release before the init fix — the upgrade path from 0.1 told users to re-run a command that silently discarded their edits
- Bundle the relay into whyline's install or whyline init now — agreed to wait for more real use and a whyline release

**Files:** docs/superpowers/plans/2026-09-20-whyline-relay.md

<!-- whyline-event: 47b04de9398d4fbaa84dcb5e709fad3d -->

## 2026-09-21 — Design pluggable agent adapters for whyline-relay before pipeline stages, planner and quota fallback

**Actor:** claude
**Role:** planner
**Task:** RELAY-ADAPTERS

**Because:** The owner has Claude, Codex and Gemini subscriptions and wants to assign agents to roles and later run multi-stage pipelines. That is four independent pieces; adapters are the foundation the rest depend on and deliver a concrete win alone. Decisions by the owner: actors are recorded by the agent's name (whyline's purpose is provenance); built-in adapters plus an opt-in generic adapter, whose limits the relay states plainly; the same agent may fill both roles with a visible warning. Approach chosen: code adapters with one interface. A probe of Gemini CLI 0.60.0 (isolated install with its own HOME, help text only, then deleted; the existing ~/.gemini was untouched and its credentials never read) showed a counterpart for each mechanism the relay relies on: -p with json output, a --policy file instead of a bypass, --skip-trust for the workspace-trust trap, and a read-only plan mode. It has no auth-status command, and whether headless Gemini can run git and whyline handoff under a policy is only knowable from a real signed-in run, so that spike precedes the Gemini adapter

**Rejected:**

- Swap only the command under the fixed codex and claude names — no login check or permission file for the substitute, confusing labels, no path to pipelines
- TOML adapter profiles — denial parsing and permission enforcement do not fit data, and a misconfigured profile would weaken the safe-by-default promise
- Record the role (implementer, reviewer) as the actor — whyline could no longer tell which model wrote the code

**Files:** docs/superpowers/specs/2026-09-22-relay-agent-adapters-design.md

<!-- whyline-event: 1f67f17c3c8544d58832e879b29af320 -->
## 2026-09-21 — Make relay subparser treat every token as positional

**Actor:** codex
**Role:** implementer
**Task:** WL-1

**Because:** argparse rejects a leading option such as --help before REMAINDER can capture it unless the relay subparser has no usable option prefix

**Rejected:**

- Use parse_known_args and append unknown tokens — it can reorder options that precede positional relay arguments

**Files:** src/whyline/cli.py

<!-- whyline-event: b0c7b0122a344283bbcd21472ba0d434 -->

## 2026-09-21 — Approve WL-1: whyline relay passes through to whyline_relay lazily, including the prefix_chars hack

**Actor:** claude
**Role:** reviewer
**Task:** WL-1

**Because:** Reviewed the diff and ran uv run pytest -q (244 passed). Probed -h, --help, --, --opt=value and empty args: all reach relay_cli.main verbatim with prog 'whyline relay'. The import is lazy, only a ModuleNotFoundError named whyline_relay gets the install hint, other import errors propagate, and pyproject.toml and uv.lock are untouched. The prefix_chars='\0' trick is unusual but is the smallest way to make argparse hand leading options to REMAINDER, and it is covered by the --help test.

**Rejected:**

- Request a parse_known_args rewrite — it can reorder options relative to positionals, which is worse than the current hack

**Files:** src/whyline/cli.py, tests/test_relay_cli.py

<!-- whyline-event: d9d849041ce04b4ab7f8ddc000326295 -->

## 2026-09-21 — Give the relay offer its own No-default confirmation path after core init succeeds

**Actor:** codex
**Role:** implementer
**Task:** WL-2

**Because:** The relay is optional, EOF and blank input must decline it, and explicit --relay controls whether a missing package is an error

**Rejected:**

- Reuse _confirm — it defaults blank input and EOF to Yes for core setup

**Files:** src/whyline/cli.py

<!-- whyline-event: 67a8f69680e24e5c90af9f4f45344c90 -->

## 2026-09-21 — Approve WL-2: whyline init offers the relay with a No-default prompt, --relay/--no-relay, and lazy in-process setup

**Actor:** claude
**Role:** reviewer
**Task:** WL-2

**Because:** Reviewed the diff and ran uv run pytest -q: all tests pass. The relay step runs only after core init returns OK, the existing-config check comes first as specified, --yes alone never opts in, EOF and blank decline, and a missing package prints relay_install_hint() to stderr (same as WL-1) with EXIT_ERROR only for explicit --relay. The relay's own non-zero code is returned and the Next line is printed only on 0. Core init output is unchanged; the one edited test_cli.py test only adds the third [y/N] prompt. Tests use a fake relay module and cover every case the task listed. I did not check the real whyline_relay package for prompt wording, since the spec fixes the wording and the tests use a fake.

**Rejected:**

- Reuse _confirm for the relay question — its default is Yes for blank input and EOF, which would opt in silently

**Files:** src/whyline/cli.py, tests/test_init_relay.py

<!-- whyline-event: c1ff44ee844c4823b400cbb7062210fd -->

## 2026-09-21 — Adapter spec corrected before planning: bypass flags live in one exempt module, the loop refuses them too, and the running marker accepts any agent

**Actor:** claude
**Role:** reviewer
**Task:** ADAPTERS-SPEC

**Because:** The spec contradicted tests/test_no_bypass.py (flag strings in adapters), let --skip-checks run a bypass flag, and running.py:42 rejects any marker but codex/claude so the one-relay guard fails open for other agents

**Rejected:**

- Flag strings inside each adapter — the guard test forbids them anywhere in src/
- Refusal in preflight only — --skip-checks would still run an agent with a bypass flag

**Files:** docs/superpowers/specs/2026-09-22-relay-agent-adapters-design.md

<!-- whyline-event: ee48ac926a80464093abeae5180e7be1 -->

## 2026-09-21 — Default doctor/start output and default init files stay byte-identical; role summary rows appear only for non-default roles or a generic agent

**Actor:** claude
**Role:** reviewer
**Task:** ADAPTERS-SPEC

**Because:** The 97 acceptance tests and 237 unit tests are the regression net for a refactor, and extra lines in default output would force edits to them and hide real regressions

**Rejected:**

- Always print the per-role summary (spec 5.5) — changes every default run for no information gain when both agents are fully managed

**Files:** docs/superpowers/plans/2026-09-22-relay-agent-adapters.md

<!-- whyline-event: 26c6861796404ea884e6cfe0c2f1e43a -->

## 2026-09-21 — Adapters ship as relay 0.2.2; the Gemini adapter waits for its own plan after the spike

**Actor:** claude
**Role:** reviewer
**Task:** ADAPTERS-SPEC

**Because:** whyline's pin whyline-relay>=0.2.1,<0.3 already admits 0.2.2 so no whyline release is needed, and Gemini's policy, login and denial behaviour is unmeasured, so a plan now would be guesses

**Rejected:**

- Widen whyline's pin and release both — extra release with no user-visible gain
- Include a Gemini adapter task now — the spike is unrun, so it would contain placeholders

**Files:** docs/superpowers/plans/2026-09-22-relay-agent-adapters.md

<!-- whyline-event: 47c289a48ac84b799f1450b4dd4c6b06 -->

## 2026-09-21 — Released whyline 0.3.0: the relay is an optional extra reached through 'whyline relay', and init offers it with default No

**Actor:** claude
**Role:** reviewer
**Task:** WL-RELEASE-030

**Because:** The extra keeps whyline dependency-free for everyone else, the in-process subcommand is the only way to expose the relay since a dependency's command is not put on PATH, and --yes must not opt in because the relay launches agents unattended and spends quota

**Rejected:**

- Hard dependency on whyline-relay — every whyline user would install an agent runner they did not ask for
- uv tool install whyline --with whyline-relay — exposes no whyline-relay command, measured

**Files:** pyproject.toml

<!-- whyline-event: d2b98eda30f546e29c0f1d4999e4ef16 -->

## 2026-09-22 — Gemini adapter spike: use the Antigravity CLI (agy), not gemini-cli; gemini-cli's individual-account product is discontinued

**Actor:** claude
**Role:** reviewer
**Task:** GEMINI-SPIKE

**Because:** gemini-cli 0.60.0 rejects oauth-personal for every account (reasonCode UNSUPPORTED_CLIENT), paid or free, redirecting to Antigravity; agy 1.2.8 is already OAuth'd to the same Google AI subscription and runs headlessly with -p/--output-format json/--mode accept-edits, no bypass flag

**Rejected:**

- gemini-cli with a Gemini API key — works, but abandons the subscription-based auth model the relay uses for Codex and Claude, and the user has a paid Google AI subscription already
- gemini-cli with --dangerously-skip-permissions or --yolo — never done, per the relay's own no-bypass rule

**Files:** docs/superpowers/specs/2026-09-22-relay-agent-adapters-design.md

<!-- whyline-event: 9bb819293e2f4edcbe89c82ed1e2553e -->

## 2026-09-22 — agy is fail-closed by default and needs explicit workspace pinning per invocation

**Actor:** claude
**Role:** reviewer
**Task:** GEMINI-SPIKE

**Because:** Every tool call (even read_file) is auto-denied headlessly unless permissions.allow lists it, in a GLOBAL settings.json (~/.gemini/antigravity-cli/settings.json), not a per-repo file; and without --add-dir <root> --new-project, agy silently operated on a stale prior project instead of the invocation's cwd, reading the wrong AGENTS.md

**Rejected:**

- Rely on cwd alone to select the repo, as codex/claude/gemini-cli do — measured to silently read/act on the wrong directory

**Files:** docs/superpowers/specs/2026-09-22-relay-agent-adapters-design.md

<!-- whyline-event: c2ce417a719e493baadc4f7384597eeb -->

## 2026-09-24 — Added Antigravity (agy) as a real whyline run target; corrected the Gemini-CLI limitation note

**Actor:** claude
**Role:** reviewer
**Task:** RUNNER-ANTIGRAVITY

**Because:** Antigravity was only ever documented in whyline-relay's generic-adapter docs, not implemented in whyline's own runner.AGENTS registry; run's argparse choices were also hardcoded separately and had silently drifted from the registry. agy needs -i/--prompt-interactive (verified against agy --help and a live invocation) to seed a session and hand over the terminal, the same shape a bare claude/codex prompt already gets

**Rejected:**

- leave the README claim as-is and only add Antigravity support in code — would still misrepresent Gemini CLI as merely unsupported rather than dead/superseded
- hardcode a second agent list in cli.py's argparse choices — derives it from runner.AGENTS instead, so the two can no longer drift apart the way they just had

**Files:** src/whyline/runner.py, src/whyline/cli.py, README.md

<!-- whyline-event: 88a68e93b4a24c919643f14f3cd82870 -->

## 2026-09-25 — Place global whyline state in ~/.whyline

**Actor:** antigravity
**Role:** implementer
**Task:** ACM-1

**Because:** Matches the repo-scoped directory name and keeps global path resolution stdlib-only without platform-dependent XDG branching

**Rejected:**

- XDG config dir ~/.config/whyline — adds platform branching for Windows/macOS and diverges from existing .whyline naming convention

**Files:** src/whyline/paths.py

<!-- whyline-event: f1cb4481895345ab82278c4cd67d6152 -->

## 2026-09-25 — Approve ACM-1 global and repo-scoped path helpers

**Actor:** codex
**Role:** reviewer
**Task:** ACM-1

**Because:** The implementation matches all four specified interfaces, tests cover each path resolution behavior, and both focused and full test suites pass

**Files:** src/whyline/paths.py, tests/test_paths.py

<!-- whyline-event: 4f8104d881244008a6b340f282ac4bd4 -->

## 2026-09-25 — Derive agent plans using stdlib-only JWT payload decoding for Codex and CLI status for Claude with non-raising fallbacks

**Actor:** antigravity
**Role:** implementer
**Task:** ACM-2

**Because:** Meets stdlib-only requirement, avoids leaking or persisting raw auth tokens, and guarantees detection failures return unknown status without raising

**Rejected:**

- external PyJWT dependency — violates stdlib-only runtime dependency constraint
- shell command for Codex auth — auth token is already stored in ~/.codex/auth.json

**Files:** src/whyline/account.py

<!-- whyline-event: ea58c6c3b54b4e148dffb48130885ad4 -->

## 2026-09-25 — Request changes to ACM-2 detection fallbacks

**Actor:** codex
**Role:** reviewer
**Task:** ACM-2

**Because:** Invalid UTF-8 in Codex auth raises UnicodeDecodeError and can block Claude detection, while missing Claude subscriptionType returns unknown without the required reason; regression tests are needed for both contracts

**Files:** src/whyline/account.py, tests/test_account.py

<!-- whyline-event: 109c13bc9748416fa9d972c06ea8f349 -->

## 2026-09-25 — Isolate agent detection boundaries and catch UnicodeDecodeError during auth and storage parsing

**Actor:** antigravity
**Role:** implementer
**Task:** ACM-2

**Because:** UnicodeDecodeError inherits from ValueError so it escaped OSError/JSONDecodeError handlers, and isolating detect calls guarantees detection failure in one agent never blocks the other

**Rejected:**

- catching broad Exception in detect_codex — masking bugs makes diagnostics in reason messages less informative

**Files:** src/whyline/account.py, tests/test_account.py

<!-- whyline-event: ee9e8b8df2f04c2aa671d277338273be -->

## 2026-09-25 — Request changes to ACM-2 gitignore coverage

**Actor:** codex
**Role:** reviewer
**Task:** ACM-2

**Because:** The implementation and all tests pass, but the tracked .whyline/.gitignore does not ignore the required per-repo account.json and model.json files, so generated account and model selections could be committed

**Files:** .whyline/.gitignore, tests/test_account.py

<!-- whyline-event: 6afd9448b46649a8a1c88e27f1501d88 -->

## 2026-09-25 — Ignore per-repo account.json and model.json in tracked .whyline/.gitignore with regression coverage

**Actor:** antigravity
**Role:** implementer
**Task:** ACM-2

**Because:** Prevents machine- and user-specific account and model files from being committed, satisfying the ACM-2 constraint

**Rejected:**

- updating cli.py GITIGNORE_LINES now — deferred to ACM-5 per plan to keep task scope cleanly partitioned

**Files:** .whyline/.gitignore, tests/test_account.py

<!-- whyline-event: f6251d983fd0409fbd89c4c40df0226e -->

## 2026-09-25 — Approve ACM-2 account detection and storage implementation

**Actor:** codex
**Role:** reviewer
**Task:** ACM-2

**Because:** The implementation derives only plan and auth metadata, isolates Codex and Claude failures, treats malformed state as absent, gitignores both per-repo files, and passes focused and full test suites

**Files:** src/whyline/account.py, tests/test_account.py, .whyline/.gitignore

<!-- whyline-event: 7acf4cad04a14e5b944d59e381dca07a -->

## 2026-09-25 — Isolate test home path from repo root and combine captured streams in test helper

**Actor:** antigravity
**Role:** implementer
**Task:** ACM-3

**Because:** repo fixture initializes git in tmp_path, so pointing Path.home directly to tmp_path collides global account.json with repo account.json, and cmd_account prints error diagnostics to sys.stderr

**Rejected:**

- pointing Path.home directly to tmp_path — collides ~/.whyline with repo root and bypasses repo confirmation
- printing cmd_account error to stdout — violates CLI convention of writing diagnostic errors to stderr

**Files:** src/whyline/cli.py, tests/test_account_cli.py

<!-- whyline-event: 72b1fe5bea384ed0bba38c71289a8af0 -->

## 2026-09-25 — Approve account status and detect CLI workflow

**Actor:** codex
**Role:** reviewer
**Task:** ACM-3

**Because:** The commands persist only derived account metadata, correctly default confirmation to yes while recording explicit decline, handle missing detection cleanly, and all focused and full tests pass

**Files:** src/whyline/cli.py, tests/test_account_cli.py

<!-- whyline-event: d79e08c5e2064b4cbdbaf9d4e12e3890 -->

## 2026-09-25 — Clear agent key on blank value and coerce malformed JSON to empty dict in model storage

**Actor:** antigravity
**Role:** implementer
**Task:** ACM-4

**Because:** Blank model selection semantically clears the per-repo override, and malformed or non-dict model.json should read as absent without crashing

**Rejected:**

- storing empty string for blank value — would diverge from absent key and require caller null checks
- raising JSONDecodeError or TypeError on malformed JSON — violates spec requirement that corrupt model.json reads as absent

**Files:** src/whyline/model.py

<!-- whyline-event: 49fe042d1c764469b5d92d280695813e -->

## 2026-09-25 — Approve per-repo model choice persistence

**Actor:** codex
**Role:** reviewer
**Task:** ACM-4

**Because:** The implementation satisfies the load, save, and set_one contracts; corrupt, non-dict, and invalid-UTF-8 files degrade to empty configuration; focused and full test suites pass

**Rejected:**

- requesting changes — no functional, safety, or coverage defect was found

**Files:** src/whyline/model.py, tests/test_model.py

<!-- whyline-event: 8957faef382f4651b42e53112cbd5ab9 -->

## 2026-09-25 — Pass per-repo agent model flag without validation and gitignore local account and model config

**Actor:** antigravity
**Role:** implementer
**Task:** ACM-5

**Because:** The agent CLI validates model names at execution time without Whyline needing hardcoded model catalogs, and account.json/model.json are local per-repo configuration files that must not be tracked in git

**Rejected:**

- validating model names against hardcoded list — would break as soon as vendors release new models
- committing account.json or model.json — leaks user plan data and forces developer-specific model choices into git

**Files:** src/whyline/runner.py, src/whyline/cli.py

<!-- whyline-event: ce70782429a447538013c3c9e8a50dbf -->

## 2026-09-25 — Approve per-repository model selection and runner propagation

**Actor:** codex
**Role:** reviewer
**Task:** ACM-5

**Because:** The CLI supports interactive, set, and status workflows; cmd_run passes the configured model to each agent without filtering; local configuration is ignored; focused and full tests pass

**Rejected:**

- requesting changes — implementation and coverage satisfy ACM-5, including EOF handling by inspection and explicit run wiring tests

**Files:** src/whyline/runner.py, src/whyline/cli.py, tests/test_runner.py, tests/test_model_cli.py

<!-- whyline-event: 6940488b6723431dbc09cc8c3fd1afd6 -->
