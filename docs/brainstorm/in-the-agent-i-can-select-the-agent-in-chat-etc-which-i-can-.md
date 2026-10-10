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

# Visible backup, and an Auto source on Plan

Independent pass on two console changes: show the backup the way the top bar already shows the chat agent, and add an Auto source on Plan that checks readiness and then runs brainstorm, spec, plan, setup, and the relay with no review stops.

## What was asked

1. Chat already picks its agent in the top bar. The backup should be choosable the same way, with Save. An automatic backup is acceptable only when the screen still names the agent that would take over. A backup that is chosen in the background and never shown is the problem.
2. Plan gains a source, Auto. With Auto selected, the form shows the brainstorm choices (models, review passes, final write-up, per-agent timeout, attachments, drafter, reviewer) and the Set up choices (implementer, tester, reviewer, and the rest of that form). Those Set up choices appear only for Auto. The button is Check, the same readiness check Set up already runs, so a login problem or a dirty tree is visible before any agent works. After a clean check, Run appears. Run does the brainstorm, the spec, the plan, setup, and the relay start with no approval stops.
3. The other sources stay on today's path: Make the plan, review it, then Set up.

## What the console does today

### The top bar is the chat agent, and it already has Save

`#context-bar` in `src/whyline/console/tui.py` is Agent, Model, Repo, "all repos", and Save. Save stays disabled until agent, model, repo, or "all repos" differs from the saved tuple (`_cb_dirty`). Save writes this repo's default agent and that agent's model (`.whyline/model.json`), and with "all repos" also writes the global default. Unavailable agents appear in the list and snap back, with the login hint.

Below 100 columns the labels shrink to A / M / R and the agent select narrows from 24 to 14, specifically so Save stays on screen. The bar is specified to never wrap (`docs/superpowers/specs/2026-10-05-console-context-bar-design.md`).

That select is the chat default. It is not a relay role, and it does not read or write the backup.

### The backup exists, and from the top bar it is invisible

Failover is one shared ordered chain, `[backup].chain` in `.whyline/relay/config.toml`. The approved chain design (`docs/superpowers/specs/2026-09-27-backup-chain-design.md`) uses that single list for chat, brainstorm, and the relay. An empty chain means no backup anywhere. The older per-role `[roles.backup]` and per-agent `[chat.backup]` tables were removed so there would be one list.

The chain is edited in one place: Relay → Set up, as one checkbox per installed agent (`RelaySetupScreen` in `relay_screens.py`). Those boxes are written only when Check runs (`save_roles` inside `_check`), which also commits the role files. In the guided Run flow, once roles are configured and every assigned agent is logged in, the checkboxes are hidden. The only trace is one summary line, `Backup: codex → grok`, or `Backup: none`.

When guided Set up has no roles yet, or a saved role is logged out, `recommend_roles` fills the backup with the usable agents left after implementer, tester, and reviewer (`relay_ops.py`). That is the automatic case. The person sees it only if they open Set up and read that line. The top bar never shows it. Console `/backups` and `/reset-backup` do not show it either; they print that those commands belong to `whyline relay chat` (`repl.py`).

Chat does fail over when the chain is non-empty: a rate limit or a lost login walks the chain, and the transcript can include `failover_notice` (`adapters.py`). With an empty chain, the same limit ends as "looks rate-limited — /model another agent, or wait." Someone who set Claude in the top bar and never opened Set up is in that second case, with no backup on screen.

Agents mode has a different backup: checkboxes on a scheduled agent definition (`agents_screens.py`). That list is per saved agent, not `[backup].chain`. This request is about the chat agent in the top bar, so that Agents-mode list stays as it is.

### Plan is three sources, then a series of stops, then a separate Set up

`RelayPlanScreen` sources are:

| Source | Extra fields | Button |
|---|---|---|
| Brainstorm it (default) | From (new or an existing doc), topic, model checkboxes, review passes, final write-up, per-agent timeout (15/30/45/60), attachments, drafter, reviewer | Make the plan |
| I'll describe it | Description, attachments, "Write a spec first" (on by default), drafter, reviewer | Make the plan |
| I have a plan already | Paste box | Save |

Drafter and reviewer are shown for the first two sources and hidden for paste (`_show_source`). They are saved to `[planner]` when the job starts. Model checkboxes, passes, final write-up, timeout, and attachments come from `brainstorm_field_widgets`, shared with the Chat brainstorm popup. Unavailable models are shown and disabled.

Make the plan closes the popup. The main window runs the job (`plan_job.py`, `_start_plan_job` in `tui.py`). The human stops along that path are:

- Brainstorm synthesis: Approve, or type a change, or answer open questions. Discard leaves the brainstorm doc.
- Spec, always after a brainstorm, and after "I'll describe it" when the checkbox is on: Approve commits `docs/specs/<slug>.md`, or type a change.
- Plan: Approve commits `plans/<slug>.plan.md`, or type a change.
- A name clash asks "Replace it?"
- Antigravity, if any selected agent is Antigravity and this repo has not answered the trust question, asks before the job starts.
- Attachments that some models can only see as paths ask "Continue?" before the popup closes.

After the plan is saved, the transcript says to open Set up next. Set up opens by itself only when this plan was started from the Run button (`_run_flow`). Plan alone does not open it.

The per-agent timeout on that form is sent with brainstorm turns (`timeout_seconds` on `run_brainstorm` and synthesis revision). Spec and plan turns use the relay config's own `timeout_minutes`. The form does not write that config value.

### Set up's Check is the readiness gate, and Start stays off until it passes

Set up picks the plan, implementer, tester, reviewer, a fixed line "Committer: whyline (automatic)", release (default "you"), and the backup checkboxes. Check then:

- saves roles and release (commits those files),
- writes any missing agent permission files and commits those,
- selects the plan,
- runs `preflight.run` (doctor),
- checks for a relay already running here.

Doctor's lines include the repo being a git repo, whyline initialised, relay setup present, each agent on PATH and logged in, the plan parsing with unchecked tasks, and "working tree is clean". A dirty tree FAILs and lists the files. The popup does not offer to commit them. Start enables only when the FAIL count is 0 and no relay is already running. Editing any field clears the results and disables Start again.

That clean-tree line is the "nothing committed" check in this request. The product's wording is "working tree is clean".

Doctor without a plan path still runs. It cannot say the plan parses, because there is no plan yet. Doctor checks the role agents and the backup chain. It does not, by itself, know which extra models the brainstorm form ticked.

## Recommendation: name the backup on the top bar, and save it with the existing Save

Add a Backup select to `#context-bar`, built like the Agent select: the same agents, unavailable ones snap back with the login hint. Include an Automatic entry. Automatic is the default when this repo has no explicit backup choice.

The control always shows a name:

- A chosen agent displays as that agent.
- Automatic displays as `Automatic · codex` (the first chain entry that is not the current chat agent), or `Automatic · codex → grok` when the chain has more than one hop, or `Automatic · none` when the chain is empty.

Save is the button already on the bar. Backup joins the dirty tuple, so Save lights up when the backup changes and stays disabled when it matches what is stored. There is no second Save button.

What Save writes:

- A named agent becomes the head of `[backup].chain`. The rest of the chain stays, with that agent removed from later positions. Set up's checkboxes remain the place that edits the full order.
- Automatic, when the chain is empty, writes the `recommend_roles` leftovers for the agents that are logged in, then the label updates to those names. Automatic, when a chain is already saved, leaves the chain as it is and only displays its head. That keeps a chain ordered in Set up intact.
- The transcript line names the scope, because this chain is shared: `Backup for this repo: codex → grok (chat, brainstorm, and the relay).`

The select shows the configured next backup, not a sticky override already in `chat-active-agents.json`. A sticky switch (Claude failed, chat is on Codex until reset) is a muted suffix on the bar, `using codex`, so the saved choice and the agent actually answering stay distinct.

`/backups` in the console prints the chain and any sticky override. `/reset-backup` clears the sticky override and leaves the chain. Both stop redirecting people to another program.

Layout: the 80-column rule stays. Backup is on the same row when Save still fits (measure at 80×24, the existing bar test). When it does not fit, Backup is the second column inside the Agent popup — same select widget, opened from the agent control — rather than a second transcript row. The label shrinks to B the way Agent shrinks to A.

Agents-mode backup checkboxes are a different store and stay on the new-agent form.

## Recommendation: Auto is a fourth Plan source, and it checks before it spends a model

Add `("Auto", "auto")` to `_SOURCES`. Brainstorm it stays the default. Auto is opt-in.

When Auto is selected, `_show_source` shows:

- Plan name (already on the form).
- The new-brainstorm fields from `brainstorm_field_widgets`: topic, model checkboxes, review passes, final write-up, per-agent timeout, attachments.
- Drafter and reviewer, prefilled from `[planner]`. Changing final write-up updates drafter only when drafter still matches the previous final write-up, matching the guided-flow default that the drafter is the synthesis writer.
- A Set up block with its own ids (`#rp-auto-implementer` and the rest): implementer, tester, reviewer, the read-only committer line, release, backup checkboxes, and the one-line meaning (`codex writes the code → …`). Prefill from `current_roles` / `release_role`, or from `recommend_roles` when this repo has no roles yet.

That Set up block is `display = False` for Brainstorm, I'll describe it, and paste. Those three sources keep today's buttons and today's fields.

Auto does not show "From: existing brainstorm". An existing doc is the Brainstorm source. Auto always starts a new brainstorm, then a spec, then a plan. There is no "Write a spec first" box on Auto; the spec step is part of the run.

### Check, then Run

For Auto the primary button is Check. Run is a second button, hidden until the latest check has zero FAILs and no relay is already running. Cancel stays. Editing any Auto field clears the check output and hides Run, the same invalidate rule as Set up.

Check does the form checks first, on the error line, before any agent or any write:

- topic present, at least one model, review passes a whole number, timeout one of 15, 30, 45, 60,
- plan name slug free (no `plans/<slug>.plan.md` and no `docs/specs/<slug>.md`), so Run will not need a Replace dialog later,
- every ticked model, the drafter, the reviewer, the three roles, every backup box, and release when release is an agent, is installed and logged in,
- if Antigravity is among them and this repo has not been trusted, the existing trust question is asked here. A decline is a FAIL line ("Antigravity isn't trusted here"), and Run stays hidden.

Then Check does what Set up's Check does, minus selecting a plan that does not exist yet: `save_roles`, `save_release`, `save_planner`, `prepare_agents`, then `preflight.run(root)` with no plan path. Results render as the same `ok` / `warn` / `FAIL` lines, including `working tree is clean` and the dirty-file list. A relay already running is the same error Set up shows, and it keeps Run hidden.

User files that are already dirty stay a FAIL. Check does not commit them. Role and permission files that Check itself writes are committed the way Set up already commits them, so a passing check leaves a clean tree.

The brainstorm timeout is copied into the relay's `timeout_minutes` as part of this save. Otherwise the number on the form caps brainstorm turns only, and spec, plan, and the later relay run keep a different cap. One field on an unattended run has to mean one cap.

Attachment models that receive images as paths only are a FAIL line on this check ("codex will get images as paths only"), cleared by removing the image or by a "Continue anyway" checkbox on the form. That replaces the Continue dialog, which would be a stop in the middle of Run.

### What Run does, and where it is allowed to stop

Run dismisses with a `PlanRequest` whose source is `auto`, carrying the brainstorm choice, drafter, reviewer, the role tuple, and the plan name. The main window runs it as today's plan job, with the review and answering states skipped for this source.

The sequence is the functions that already exist:

1. `adapters.run_brainstorm` for the topic, models, passes, final writer, timeout, and attachments.
2. `run_spec_from_synthesis`, then `approve_spec` (commits the spec).
3. `run_plan_from_spec`, then `approve_plan` (commits the plan).
4. `select_plan` on the new file, then `preflight.run(root, plan)`. This second doctor is what can finally say the plan parses and has unchecked tasks.
5. On zero FAILs, `whyline relay start` through the existing `_launch_relay`. Progress stays in the transcript (`plan · …`, then `relay · …`).

A non-zero second doctor does not start the relay. The new FAIL lines are printed, the plan file stays (it is already committed), and Set up can be opened on it. That is a failed start, reported the same way Set up reports a failed check.

Stop still cuts the current agent and leaves a resumable draft, as it does for any plan job. "No interruption" means no approval prompt. It does not mean the run cannot be stopped.

Open questions are the one place a model can still demand a person. Auto's spec and plan prompts tell the drafter to decide, record the decision in the doc, and not hand off `blocked`. If a `blocked` handoff or an `## Open questions` section comes back anyway, the run stops in the existing answering state and the questions are printed. It does not invent answers, and it does not discard the draft. Answering continues the Auto sequence from that stage. Product choices stay with the person who was asked; the run simply refuses to guess.

Replace dialogs do not appear on this path, because Check already refused an existing spec or plan slug.

### The other sources stay on the current path

Brainstorm, I'll describe it, and paste keep Make the plan or Save, the synthesis / spec / plan reviews, and Set up as a separate step. Their forms do not grow the role block. Approving a plan still ends in "Next: Set up…", and Set up still opens on its own only from the Run button.

The bottom-bar Run button is unchanged: no plan yet opens Plan, otherwise it asks new versus existing, and existing opens guided Set up.

## Limits

- The top-bar backup and Set up's checkboxes write the same chain. The bar changes who is first. Set up changes membership and order. Saving Automatic must not reorder a chain the person already set.
- Auto's first Check cannot prove the future plan parses. The second doctor, after the plan is committed, is what gates `start`. A plan that fails that check is already a committed file.
- Auto will commit the spec, the plan, the role files, and permission files without a per-file confirm. Check is the confirm. A dirty tree of the user's own files blocks Run until they clean it.
- Copying the brainstorm timeout into relay `timeout_minutes` changes the cap for later relay tasks in this repo, not only for this Auto run. The Check output should say that in one line.
- An unattended run that hits a release task still pauses when release is "you". That pause is the release role working as designed. Auto does not switch release to an agent on its own. The release select is on the form so the person can choose before Check.
- Brainstorm still spends every selected model. Check only proves they are logged in and the tree is clean. A usage limit during the run still walks `[backup].chain`, which is why the chain has to be the one just saved, and why its head has to be visible before Run.

## Files a later implementation would touch

- `src/whyline/console/tui.py` — context-bar Backup select, dirty tuple, Save, the 80-column fit, and the Auto branch of the plan job (skip review, chain spec and plan approval, second doctor, start).
- `src/whyline/console/relay_screens.py` — Auto source, conditional Set up block, Check / Run buttons.
- `src/whyline/console/plan_job.py` — `PlanRequest.source = "auto"` and a runner that calls the existing brainstorm, spec, and plan functions in order.
- `src/whyline/console/relay_ops.py` — read and write the chain head; copy timeout into relay config without dropping other keys; doctor for the brainstorm models that are not already in a role.
- `src/whyline/console/repl.py` — `/backups` and `/reset-backup` report the chain instead of sending people to `whyline relay chat`.
- Console tests for the bar at 80 columns, Auto's hidden role block on the other sources, Run staying hidden until a clean check, and a field edit hiding Run again.
