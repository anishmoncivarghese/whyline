# Brainstorm: In the agent I can select the agent in chat etc, which I can select in top, similarly there should be an option to slect the back up agent as well or its autimatic, but whe its automtic people cant see but if its simialr to on top then people can see what is the back up, and click save. Another big thing I want In Plan now like we are doing it here now additional I want the Auto Mode, where now you automaticllay do the brain storming, specs, Plan and set up etc and run the plan without any interuption, here so when source is selected as Auto mode , then simialrly user can select the models , review passes, final write uo by , per agent timeout , attachment, drafter and reviewe, then it also do the things done in set up that is select the implementer, tester, reviwer etc simialr to set up this only comes in plan when the Auto mode is selectedc . and instead of make plan it shows check first, which checks ifalll modelsa re conencted , no issues nothing commited simialr what we do it set up so taht user knows there are some error which he can resolve. and once check passed run appears. Now in source otehr than AUto mode, if its Brainstome, i will describe plan etc, then its the sam e set up that we have now , make the plana dn then go to the set up mode.

## Codex

# Visible backups and an end-to-end Auto plan mode

## Recommendation

Build these as two related improvements around one principle: configuration should be visible before work starts, and the same checked configuration should be the one that runs.

1. Add a compact, repository-specific **Backup** control beside the existing top-bar Agent control. It must display the real configured fallback chain and, when failover is active, the agent actually being used. Include an **Automatic** choice, but always resolve it visibly—for example, `Automatic · codex → grok`—so “automatic” never means “hidden.” Save uses the existing top-bar Save button.
2. Add **Auto mode** as a fourth Plan source. Auto mode owns the complete workflow configuration—brainstorm, planning, execution roles, backup chain, and release—and replaces “Make the plan” with **Check** and **Run**. Run stays disabled until the exact current form has passed Check.
3. Execute Auto through the existing plan-job machinery and then hand off to the ordinary relay launcher: brainstorm → synthesis → spec → plan → final preflight → implementation, with routine approval screens skipped. It should pause only for a real failure or unresolved question and retain enough phase state to resume. A separate background coordinator can follow later if users need the planning stages to survive closing the console; it should not block the first release.

This preserves the current manual paths. “Brainstorm it,” “I’ll describe it,” and “I have a plan already” still create a plan and then go to the existing Set up flow. Auto is an explicit opt-in for users who want the whole sequence.

## What exists today

The requested behavior is close to existing capabilities, but they are spread across several screens and contracts:

- The top context bar in `console/tui.py` has Agent, Model, Repo, “all repos,” and Save. Its Agent is the requested Chat agent; it does not expose backup configuration or an active failover override.
- Relay already has one shared ordered `[backup].chain`, used by Chat, brainstorm, and relay roles. It is not a separately inferred backup per feature. Failover walks the chain, skips agents already tried, and stores sticky overrides. Chat already reports a failover notice in the transcript.
- Relay Set up exposes the backup chain as checkboxes, but the order is effectively the fixed agent-list order. It is visible only after planning, even though Chat and brainstorming also use it.
- Plan currently has three sources: brainstorm, description, and pasted plan. Brainstorm already collects selected agents, review passes, final writer, per-agent timeout, and attachments. Description/brainstorm also collect plan drafter and reviewer.
- Set up separately collects implementer, tester, reviewer, release, and backup; Check saves those values, prepares permission files, selects the plan, runs relay preflight, and enables Start only if there are no failures. Any form edit invalidates the check.
- The current Plan job deliberately returns to the main window for synthesis/spec/plan review and approval. That is appropriate for manual mode but conflicts with “run without interruption.”
- Current relay preflight checks repository setup, configured commands, login state, role safety, prompt availability, plan validity, a clean working tree, and the absence of another live relay. It assumes a plan already exists, so it cannot be reused unchanged for Auto’s initial Check.

The design should reuse these mechanisms rather than add a second backup system, a second role format, or a weaker “check.”

## 1. A visible Backup control in the top bar

### Meaning

The control edits the repository’s existing shared `[backup].chain`; it is not a new Chat-only backup. Its label or help text should say “Shared fallback” so users understand that Chat, brainstorm, planning, and execution all use it. This also preserves the earlier product decision that backup is per repository, not a machine-wide default.

The compact state can render as:

`Agent [claude ▾]  Backup [codex ▾] +1  Model [default]  Repo […]  [Save]`

The first fallback stays directly selectable like Agent. If the chain has more entries, show `+1` or `+2`; “Manage chain…” opens the existing Set up chain controls, upgraded to make order explicit. Selecting a named backup moves it to the front while retaining the remaining chain. Choosing None explicitly clears the whole chain. This gives the top bar the simple one-choice interaction the user asked for without inventing a second backup store.

The dropdown should contain:

- `Automatic · <resolved chain>`;
- `None — no fallback`;
- each installed/configured agent, with login/availability in the label;
- `Manage chain…` when ordering more than one fallback.

Automatic is a selection policy, not an unnamed runtime guess. When a saved chain exists it preserves that chain and displays its resolved names. When no chain exists, it uses the existing `recommend_roles`/usable-agent logic to stage an ordered chain, excluding the current primary where practical; the label must still show the names, including `Automatic · none` when nothing is usable. Save materializes that resolved chain. Re-selecting Automatic must not reorder a chain the user already arranged in Set up.

### Show configured versus effective agent

There are two facts to display:

- configured: `Agent claude · Backup codex → grok`;
- runtime override: `Using codex (backup for claude)` after failover.

Do not replace the primary Agent selection with the effective backup, because that would make a temporary sticky override look like a permanent preference. A small status suffix/chip in the context bar and the existing transcript notice make the state understandable. The chain editor can also offer “Reset active failover,” backed by the relay’s existing override reset behavior.

### Persistence and safety

Extend the context bar’s saved/current tuple and dirty tracking to include the backup chain. Save should persist Agent/model and backup together from the user’s perspective. Backup remains repository-scoped even when “all repos” is checked; the UI should say so rather than implying that a shared relay chain will be written globally. In the relay package, expose narrow public `read_backup`/`write_backup` functions instead of making the console call private TOML helpers or `write_roles`. They must preserve roles, pipeline, custom agents, timeout, and planner settings and commit only the config file.

Changing backup while a chat turn, planning job, or relay run is active should be refused with the same “finish or stop the current job” behavior used for repository switching. Existing active overrides should not be silently cleared by changing the configured chain; show a reset action instead.

## 2. Auto mode in Plan

Add `("Auto — brainstorm to implementation", "auto")` to the Plan source list. Selecting it should reveal one scrollable form composed from the same field builders used by Brainstorm and Set up, not copied widgets.

### Auto form

The form should contain these groups:

**Goal and research**

- plan name (optional) and topic/goal;
- selected research agents/models, with availability and resolved model names;
- review passes;
- final synthesis writer;
- per-agent timeout, using the same timeout type/options as Chat and Brainstorm, including No limit once that support is released;
- attachments, with the existing per-agent capability warning.

**Spec and plan**

- spec/plan drafter;
- spec/plan reviewer;
- “Write a spec first” fixed on for Auto, or shown as an advanced toggle defaulting on. The strongest default is on because Auto removes human review and therefore benefits from the extra reviewed artifact.

**Implementation**

- implementer;
- tester;
- reviewer;
- shared ordered backup chain;
- release role, defaulting to “you”;
- `Committer: whyline (automatic)` as read-only.

End with a plain-language summary such as:

`Claude + Codex research → Claude synthesizes → Grok drafts, Codex reviews → Grok implements, Claude tests, Codex reviews → Whyline commits → you release. Backup: Claude.`

This summary catches role mistakes more effectively than a dense set of dropdowns.

For other sources, keep the current fields and behavior. Manual brainstorm/description still shows drafter and reviewer, creates artifacts with explicit user review, then sends the user to Set up. Pasted plans continue to skip planner roles.

### Buttons and validation state

When source is Auto, the footer becomes:

`[Check] [Run] [Cancel]`

- Check performs no model work and does not create a plan.
- Run is disabled until Check completes with zero FAIL results.
- Warnings are visible but do not block Run, matching current preflight behavior.
- Every relevant edit invalidates the result, clears or marks the old output stale, and disables Run.
- Check records a fingerprint of the complete request: all fields, ordered attachments plus file metadata/hash, relevant config/model resolution, and repository HEAD/status. Run recomputes it. A visually unchanged form must not be allowed to run after the repository or login state changed.

Check output should be grouped so fixes are obvious: Repository, Agents and logins, Inputs, Planning, Execution, and Concurrency.

## 3. What Auto Check must verify

Auto’s first Check cannot rely on existing `preflight.run` alone because there is no generated plan yet and doctor does not know every selected brainstorm agent. Reuse `preflight.run(root)` without a plan for the repository, login, command-safety, role, and clean-tree checks, then add a structured candidate-workflow layer for the staged form values. This preserves the same diagnostics users already see in Set up while covering fields doctor cannot inspect.

It should verify:

- inside an initialized Git repository;
- clean working tree, with no `--allow-dirty` escape in the Auto UI;
- no running relay, planning job, or incompatible unfinished draft;
- every selected research agent, final writer, drafter, planner reviewer, implementer, tester, execution reviewer, non-human release agent, and backup-chain member is configured, installed, and logged in where login can be checked;
- configured commands contain no prohibited permission-bypass flags;
- Antigravity trust is resolved before passing Check;
- attachments still exist, are readable, and have an understood delivery mode for every agent that needs them;
- review passes and timeout values are valid;
- target brainstorm/spec/plan names do not collide, or replacement policy is explicitly chosen;
- the role/pipeline and prompt templates needed for implement/test/review exist;
- the candidate config can be parsed and all selected names are valid.

The workflow’s own operational state must never make this check fail. Store Auto request/phase state in an ignored relay-state file, not as an untracked file that dirties the repository. Generated brainstorm, spec, plan, and config artifacts remain normal tracked and committed outputs. Unrelated user changes must still fail the clean-tree check. The first release only needs enough state to resume within/reopen the normal plan flow; full daemon-style recovery is a later hardening step.

Because the plan does not exist yet, Auto also needs a second, automatic preflight after plan approval. That pass calls the ordinary plan-aware relay preflight against the generated plan. A failure there stops before implementation; it must never start merely because the earlier candidate check passed.

## 4. Auto execution semantics

The Auto Run button should submit one immutable `AutoRunRequest` to the existing plan job, stream the current `plan · …` progress in the console, and launch the relay through the existing subprocess path after final preflight. This is the smallest architecture that reuses today’s tested brainstorm/spec/plan and relay boundaries. Persist phase/artifact metadata so Stop or a recoverable failure can resume without repeating completed model work; background survival after closing the console is not required for the first version.

Suggested phases are:

1. Revalidate the request fingerprint and acquire a single workflow/run lock.
2. Persist and commit the selected planner roles, execution roles, release role, backup chain, and timeout/config needed by later phases.
3. Run independent brainstorm passes and final synthesis.
4. If synthesis is structurally complete, continue automatically. If it contains unresolved Open Questions after the configured model reviews, pause with those questions and a checkpoint.
5. Draft and model-review the spec. Automatically accept only an approved, valid spec; model-requested revisions loop within the existing visit cap.
6. Draft and model-review the plan from the approved spec. Automatically accept only an approved plan that passes the relay plan parser.
7. Select the generated plan and run ordinary full preflight against it.
8. Start the implement/test/review relay and continue streaming progress.

“Without interruption” should mean no routine approval clicks between clean stages. It should not mean silently guessing when agents surface unresolved product decisions, ignoring a failed review, overwriting an existing artifact, bypassing a dirty tree, or continuing after a stale check. Those conditions pause with a precise reason and actions: Resume, Change settings, Replace (where safe), or Cancel.

The coordinator checkpoint should include request version/fingerprint, current phase, topic, artifact paths and hashes, selected roles/chain, and last successful check. Resume must continue from the last valid artifact rather than rerun paid model work. Stop should terminate the current agent process group, mark the workflow stopped, and leave committed artifacts/checkpoint resumable.

Progress in the main window should use phase names, for example:

`auto · research 2/4 · codex`

`auto · synthesis · claude`

`auto · spec review 1/3 · codex`

`auto · final preflight`

`relay · T1 draft · grok`

## Data/API shape

Use a single immutable request rather than several loosely coupled dictionaries. For example, `AutoRunRequest` can contain:

- goal/name, attachments, replace policy;
- a nested brainstorm configuration;
- planner drafter/reviewer and max visits;
- execution roles, release, and ordered backup chain;
- timeout policy;
- schema version.

The console should collect/render this request, let the existing plan job orchestrate the foreground phases, and display structured `Check`/progress events. Reusable relay/plan helpers should own validation, persistence, artifact transitions, and cancellation so business rules do not live in widget handlers and a future background coordinator can reuse the same contract.

Factor shared widgets and collectors for:

- ordered backup chain;
- planner roles;
- execution roles/release;
- brainstorm configuration.

That prevents Auto and Set up from drifting. `RelaySetupScreen` and the top bar must read and write the same chain contract.

## Failure behavior

- **A selected agent becomes unavailable after Check:** Run’s fingerprint/recheck fails before model work; if it happens during the workflow, normal configured failover walks the visible backup chain.
- **All backups fail:** pause with the agents tried and keep the checkpoint. Do not silently substitute an unconfigured model.
- **An agent fails in one brainstorm slot:** retain current brainstorm graceful degradation and label output with the agent that actually ran.
- **Open questions remain:** pause once, show the exact questions, accept answers, then Resume from that phase.
- **Spec or plan review exhausts its visit cap:** pause with the draft path and review reason.
- **A target artifact already exists:** fail Check unless the user explicitly enabled Replace; never ask midway through an otherwise unattended run.
- **Final preflight fails:** do not start implementation; show fixes and keep the completed artifacts.
- **Console closes during planning:** warn before exit or stop the active planning subprocess while preserving the last committed phase; reopening can resume from that phase. Once the relay has launched, its existing process behavior applies.
- **User edits Auto fields after Check:** invalidate immediately and require Check again.

## Implementation order

### Phase A: visible backup configuration

- Add relay `read/write_backup` APIs that preserve the rest of config.
- Add the top-bar Backup state, dirty/save handling, compact chain editor, availability labels, and effective-override status.
- Reuse the chain editor in Set up so ordering is explicit.
- Cover config preservation, no-chain behavior, reorder behavior, Save, reset override, and narrow-terminal layout.

This is independently useful and makes failover understandable before Auto depends on it.

### Phase B: Auto form and candidate Check

- Introduce `AutoRunRequest` and shared field/collector components.
- Add the Auto source and conditional groups/buttons.
- Add read-only candidate preflight and fingerprint invalidation.
- Test every field dependency, unavailable agent, dirty tree, active run, attachments, trust, warnings, stale checks, and 80x24 reachability.

### Phase C: Auto runner and relay handoff

- Extend the existing plan job with Auto sequencing, ignored phase state, structured progress, Stop, and Resume.
- Reuse current brainstorm, spec, planner, approval, plan validation, config, and full preflight primitives.
- Add the automatic second preflight and hand off into ordinary relay start.
- Test phase recovery and idempotence by stopping after each boundary and resuming without duplicating commits or model turns.

### Phase D: end-to-end hardening

- Scratch-repository tests for a clean full run, a failover during brainstorm, a failover during implementation, an unresolved question, a stale check, an artifact collision, final-preflight failure, closing the console during planning, and Stop/Resume.
- Ensure every generated commit is narrowly scoped and the repository is clean at the point implementation begins.

## Acceptance criteria

- A user can always see the repository’s first backup in the top bar and the complete ordered chain with one action.
- Save persists exactly the visible chain without rewriting unrelated relay configuration.
- When a backup is active, the UI distinguishes requested primary from effective agent.
- Auto exposes all research, planning, execution, backup, timeout, attachment, and release choices on one screen.
- Auto Run cannot be pressed until the exact current request and repository state pass Check.
- A clean Auto run needs no synthesis/spec/plan approval clicks and proceeds into implementation.
- The generated plan is subjected to ordinary plan-aware preflight before implementation starts.
- Genuine ambiguity or failure pauses safely with a resumable checkpoint and a concrete fix.
- Stop terminates the active planning agent and preserves completed artifacts; after relay launch, existing relay Stop behavior remains authoritative.
- Existing manual Plan and Set up flows behave unchanged.

## Product choices to settle before implementation

1. Whether Auto may overwrite an existing brainstorm/spec/plan behind an explicit Replace option. The safer default is no overwrite, caught during Check.
2. Whether closing the console during the planning phases should cancel-and-resume later or promote Auto planning to a background relay-owned process. Start with cancel-and-resume unless background continuation is already a firm requirement.

## Grok

# Name the backup on the bar, and let Auto run only after a read-only check

The bar should show the fallback the way it already shows the chat agent, and Plan should gain an Auto source that gathers the brainstorm and Set up choices, checks them, and then runs through to the relay. Brainstorm, I'll describe it, and paste stay on Make the plan, then Set up.

## What is already there

`#context-bar` in `src/whyline/console/tui.py` is Agent, Model, Repo, "all repos", and Save. Save stays disabled until agent, model, repo, or "all repos" differs from the saved tuple (`_cb_dirty`). Save writes this repo's default agent and that agent's model (`.whyline/model.json`). "all repos" also writes the global default agent and model, then clears the checkbox. It leaves relay config alone. Unavailable agents stay in the list and snap back, with the login hint. Below 100 columns the labels shrink so Save stays on screen. The bar never wraps (`docs/superpowers/specs/2026-10-05-console-context-bar-design.md`). An approved timeout plan adds a timeout select on this same row and requires that select and Save to fit in 80 columns. That select is a chat-session preference and must keep leaving `.whyline/relay/config.toml` untouched.

The Agent select is the chat default. It is a different thing from a relay role, and the bar does not read the backup.

Failover is one ordered list, `[backup].chain`, in this repo's `.whyline/relay/config.toml`. BC1 in `docs/superpowers/specs/2026-09-27-backup-chain-design.md` means one list shared by chat, brainstorm, and the relay inside the repo. An empty chain means no backup for any of them. The old per-role and per-agent backup tables are gone. The list is edited in Relay → Set up as one checkbox per installed agent (`RelaySetupScreen`). The boxes are stored when Set up's Check runs, which also commits the role files. In the guided flow, once roles are set and every assigned agent is logged in, the boxes hide and one line remains: `Backup: codex → grok`, or `Backup: none`.

`recommend_roles` (`relay_ops.py`) fills the role form when Set up has no roles, or when a saved role is logged out. It assigns implementer, tester, and reviewer first, then puts the remaining usable agents in the backup. That default belongs on the role form. Using it for the chat bar would drop the tester and the reviewer out of chat failover.

Chat already walks a non-empty chain on a rate limit or a lost login, skips agents already tried, stores a sticky override, and can print `failover_notice` in the transcript. An empty chain ends as "looks rate-limited — /model another agent, or wait." Console `/backups` and `/reset-backup` still tell people to use `whyline relay chat`.

Agents mode has its own checkboxes on a scheduled agent. That store stays separate.

Plan sources today:

| Source | Extra fields | Button |
|---|---|---|
| Brainstorm it (default) | From, topic, model checkboxes, review passes, final write-up, per-agent timeout (15/30/45/60), attachments, drafter, reviewer | Make the plan |
| I'll describe it | Description, attachments, "Write a spec first" (on by default), drafter, reviewer | Make the plan |
| I have a plan already | Paste box | Save |

Drafter and reviewer are hidden for paste. Make the plan closes the popup. The main window's plan job then stops for synthesis approval, spec approval, plan approval, a name clash, the Antigravity trust question, and an attachment "Continue?" when some models can only see paths. After the plan is saved, the transcript says to open Set up. Set up opens by itself only from the bottom-bar Run flow.

The brainstorm timeout goes out on brainstorm turns. Spec, plan, and the relay read `timeout_minutes` from relay config. The form does not write that value.

Set up's Check saves roles and release, writes missing permission files, selects the plan, runs `preflight.run`, and checks for a relay already running. Start enables only when the FAIL count is 0. Warnings stay visible and do not block. Editing a field clears the results. Doctor with no plan path still runs. It can say the tree is clean, the agents in the saved roles and chain are logged in, and commands are safe. It cannot say a future plan parses, and it does not know which brainstorm models the form ticked. `.whyline/relay/` is gitignored except `config.toml` and `prompts/`, so a run's own scratch files can live there without failing the clean-tree line.

## Backup on the bar

Add a Backup control for this repo's existing chain. The label is Shared fallback: chat, brainstorm, and the relay all read this list. There is one chain.

The closed control shows real agent names:

- A chosen head displays as that agent, with `+1` or `+2` when the chain is longer. "Manage chain…" opens the order editor.
- Automatic displays the chain it resolves to, for example `Automatic · codex → grok`, or `Automatic · none` when no other usable agent is logged in.
- None displays as `None — no fallback`. The option text says this clears the chain for chat, brainstorm, and the relay.

Automatic is a policy with a visible result. When a chain is already saved, Automatic shows that chain, and Save leaves the order alone, including an order set in Set up. When no chain is saved, Automatic stages the logged-in agents except the current chat agent, in the implementer preference order already in `relay_ops` (`codex`, `claude`, `antigravity`, `grok`, then any other usable agent). Save writes that staged list. The role form keeps using `recommend_roles` for its own empty-state default.

Choosing a named agent moves it to the front and keeps the rest of the chain. None writes an empty chain. Set up's checkboxes need an explicit order; today they follow the fixed agent-list order. The bar, Set up, and Auto read and write the chain through one pair of functions.

The select shows the configured chain. A sticky override (Claude failed, this chat is answering as Codex until reset) is a suffix on the bar, `using codex`, plus the transcript notice that already exists. The Agent control keeps showing the saved primary. Save leaves the override in place. The chain editor offers Reset active failover, using the relay's existing reset. Changing the chain while a chat turn, a plan job, or a relay run is active uses the bar's existing refusal: finish or stop the current job.

Save is the button already on the bar. The chain joins the dirty tuple. "all repos" still writes only the default agent and model. The chain stays in this repo's `config.toml`. The transcript line is `Backup for this repo: codex → grok (chat, brainstorm, and the relay).`

The relay package exposes `read_backup` / `write_backup`. Those preserve roles, pipeline, custom agents, timeout, and planner settings. Agent and model keep writing `.whyline/model.json` with no git commit, as they do now. A chain change commits `config.toml` alone. Other dirty files stay unstaged. A dirty tree does not block this Save. Auto's check is what refuses a dirty tree.

Layout is measured at 80×24, with Save still on the row, and with the timeout select from the approved timeout plan on that row. If Backup fits, it sits beside Agent. If it would push Save past column 80, Backup opens from the Agent control as the same select, and the closed Agent label carries a short suffix such as `claude · bak codex`. The bar still does not wrap. `/backups` prints the chain and any sticky override. `/reset-backup` clears the override and leaves the chain.

Agents-mode backup checkboxes stay on the new-agent form.

## Auto is a fourth Plan source

Add `("Auto", "auto")` to `_SOURCES`. Brainstorm it stays the default.

Auto shows one form built from the same field builders as Brainstorm and Set up:

- Plan name and topic.
- Research agents, review passes, final write-up, the brainstorm timeout control, attachments.
- Drafter and reviewer, prefilled from `[planner]`. Changing the final write-up updates the drafter only while the drafter still matches the previous final write-up.
- Implementer, tester, reviewer, the read-only line `Committer: whyline (automatic)`, release (default "you"), and the ordered backup chain.
- One summary line, for example `Claude + Codex research → Claude synthesizes → Grok drafts, Codex reviews → Grok implements, Claude tests, Codex reviews → whyline commits → you release. Backup: Claude.`

Those execution fields stay hidden on Brainstorm, I'll describe it, and paste. Those sources keep today's buttons. Auto has no "From: existing brainstorm" control. An existing doc stays on the Brainstorm source. Auto always starts a new brainstorm, then a spec, then a plan. The spec stays in the run because the human approval stops are gone and the spec is the reviewed artifact in their place. "I'll describe it" keeps its own "Write a spec first" checkbox.

The timeout control is the brainstorm one. When that control gains No limit, Auto gains it from the shared widget. The value is the cap for this run's brainstorm, spec, plan, and relay. The chat-bar timeout stays a different control and still must not write relay config.

### Check reports, Run persists

The Auto footer is Check, Run, and Cancel. Run stays disabled until the latest check has zero FAILs and no relay is already running here. Warnings stay visible and do not block. Any edit clears the result and disables Run.

Check calls no model, writes no roles, writes no permission files, and creates no plan. Set up's Check saves because Start has no later persist step. Auto's Run is that step. Someone who Checks and then Cancels leaves the repo as they found it.

Check reports in groups — Repository, Agents and logins, Inputs, Planning, Execution, Concurrency:

- The form is complete: topic, at least one model, review passes a whole number, timeout a value the shared control allows.
- The plan and spec slugs are free, unless Replace is ticked. Replace defaults off. A clash FAILs here, so Run never asks "Replace it?" in the middle.
- Every ticked model, the final writer, drafter, reviewer, the three roles, every chain member, and release when release is an agent, is installed and logged in where login can be checked.
- Antigravity trust is already answered for this repo. An unanswered repo gets the existing trust question here. A decline is a FAIL line, and Run stays off.
- Commands for those agents contain no permission-bypass flags.
- Attachments exist, are readable, and have a real delivery mode for every selected agent. An agent that would receive images as paths only is a FAIL, cleared by removing the image or by ticking Continue anyway on the form. That tick is part of the request. It stands in for the Continue dialog.
- `preflight.run(root)` with no plan path: git repo, whyline initialised, clean working tree, no live relay. The user's own dirty files FAIL. Check offers no `--allow-dirty` and commits nothing.
- A candidate layer beside doctor, in the same check-line shape, for the brainstorm models and planner roles doctor does not know. Doctor stays the role-and-repo check.

Check stores a fingerprint of the form, the ordered attachments and their file identity, the resolved agents, and the repo HEAD and status. Run computes the fingerprint again. A form that still looks the same fails closed when the tree or a login changed after Check.

The check output includes the line Run will make true, for example `Relay timeout for this repo becomes 30m`, plus the roles, chain, and planner it will write. That write is one commit of those config files at the start of Run, after the fingerprint matches. Later relay tasks in this repo then see that timeout. The check line says so before the user presses Run.

The run's phase file lives in the gitignored part of `.whyline/relay/`, beside the brainstorm temp files. A tracked scratch file would make the clean-tree check fail on the run itself.

### Run reuses the plan job, then the relay

Run submits one immutable `AutoRunRequest` — goal, attachments, replace policy, brainstorm settings, drafter and reviewer, execution roles, release, ordered chain, timeout, schema version — to the existing plan job. The job streams `plan · …` in the console. After the plan exists and a second, plan-aware preflight passes, the job starts the relay through the existing launcher. This release stays in that foreground job. Closing the console during planning stops the planning subprocess and keeps the last committed phase. Reopening resumes from that phase. After the relay has started, the relay's own process is in charge. A coordinator that keeps planning alive with the console closed can come later. The first release works without it.

The sequence uses the functions that already exist:

1. Recompute the fingerprint and take the single run lock.
2. Persist and commit the planner roles, execution roles, release, chain, and this run's timeout.
3. `run_brainstorm`, then synthesis. A complete synthesis continues. An `## Open questions` section or a `blocked` handoff pauses in the existing answering state. The Auto prompts tell the drafter to decide and record the decision in the doc. Questions that come back anyway are printed, and the run waits. Answering resumes at that phase.
4. Draft and review the spec, then `approve_spec` only for an approved, valid spec. Revisions stay inside the existing visit cap. Past the cap, the run pauses with the draft path and the review reason.
5. Draft and review the plan, then `approve_plan` only when the plan parses.
6. `select_plan`, then `preflight.run(root, plan)`. This is the check that can say the plan parses and has unchecked tasks. Any FAIL stops before start. The spec and plan stay committed. The FAIL lines print, and Set up can open on that plan.
7. On a clean second check, `whyline relay start` through `_launch_relay`.

Stop ends the current agent process group, marks the workflow stopped, and leaves the committed artifacts and the phase file resumable. Resume continues from the last good artifact.

Progress names the phase: `auto · research 2/4 · codex`, `auto · synthesis · claude`, `auto · final preflight`, then `relay · T1 draft · grok`.

A model that dies mid-run walks the chain just saved. The transcript names the agent that actually ran. When the chain runs out, the run pauses with the agents tried.

Release defaulting to "you" still pauses at a release task. That pause is the release role. The release select is on the form so the choice is made before Check.

### The other sources

Brainstorm, I'll describe it, and paste keep Make the plan or Save, the review stops, and Set up as the next step. Approving a plan still ends in "Next: Set up…". The bottom-bar Run button is unchanged: no plan yet opens Plan, otherwise it asks new versus existing, and existing opens guided Set up.

## Order of work

1. `read_backup` / `write_backup`, the bar control, dirty tracking, the 80-column fit (including the timeout select), override status, and `/backups` / `/reset-backup`. Set up's chain editor gains an explicit order and uses the same read and write.
2. `AutoRunRequest`, the shared field builders, the Auto source, the read-only check, and fingerprint invalidation.
3. The plan-job sequence, the ignored phase file, the second preflight, Stop, and Resume, then the existing relay start.
4. A scratch repo covering a clean run, failover during brainstorm, failover during the relay, an open question, a stale fingerprint, a slug clash, a failed second preflight, closing the console during planning, and Stop/Resume that does not commit the same artifact twice.

## Done when

- The bar shows this repo's first backup, and one action shows the full order.
- Save writes that chain and commits only `config.toml`. Roles, the previous timeout, and planner settings stay as they were. "all repos" leaves the chain where it is.
- A sticky failover reads as `using codex` while Agent still shows the saved primary.
- Auto shows the research, planning, execution, backup, timeout, attachment, and release choices on one screen, and only on that source.
- Run stays off until this form and this repo state pass Check. A later edit, a new dirty file, or a logged-out agent turns it off again.
- A clean run asks for no synthesis, spec, or plan approval, and it starts the relay only after the generated plan passes the plan-aware preflight.
- An open question, a failed review, an exhausted chain, or a failed second preflight pauses with the artifacts kept and a concrete next step.
- The three existing sources still end in Set up.

## Choices

- An empty chain's Automatic list is the logged-in agents except the current chat agent. `recommend_roles` stays the empty-state default for the role form only.
- Auto always writes a spec. The describe source keeps the checkbox.
- Auto Check only reports. Run writes config after the fingerprint matches. Set up's Check can keep saving, because that screen's next button is Start.
- The first Auto release runs in the existing plan job and hands off to the existing relay start. A background coordinator is a later choice.
- "all repos" writes the global default agent and model. The backup chain stays in this repo's config.
- Images that would arrive as paths fail Check unless the form accepts that before Run.
