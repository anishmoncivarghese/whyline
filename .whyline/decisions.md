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
