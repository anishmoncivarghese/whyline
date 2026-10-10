# Visible backups and an end-to-end Auto plan mode

## Recommendation

Build these as two related improvements around one principle: configuration should be visible before work starts, and the same checked configuration should be the one that runs.

1. Add a compact, repository-specific **Backup** control beside the existing top-bar Agent control. It must display the real configured fallback chain and, when failover is active, the agent actually being used. Do not describe a hidden choice as “automatic.” If Whyline recommends a backup, show the concrete suggestion and require Save.
2. Add **Auto mode** as a fourth Plan source. Auto mode owns the complete workflow configuration—brainstorm, planning, execution roles, backup chain, and release—and replaces “Make the plan” with **Check** and **Run**. Run stays disabled until the exact current form has passed Check.
3. Execute Auto as a durable relay workflow, not as a long chain of Textual callbacks. It should run brainstorm → synthesis → spec → plan → final preflight → implementation without routine human approval screens. It should pause only for a real failure or unresolved question, retain its checkpoint, and offer Resume.

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

The first fallback stays directly selectable like Agent. If the chain has more entries, `+1` or `+2` opens a small chain editor with ordered rows and Move up/Move down/Remove actions. A final “Manage chain…” option in the Select is another workable Textual pattern. Selecting a different first backup should move it to the front while retaining the remaining chain; choosing None should explicitly clear the whole chain. That avoids silently destroying an existing multi-hop chain.

The dropdown should contain:

- `None — no fallback`
- each installed/configured agent, with login/availability in the label;
- `Manage chain…` when ordering more than one fallback.

Do not use a bare `Automatic` value. Today the engine does not secretly choose an arbitrary backup; it walks the saved chain. For a repository without a chain, Whyline may prefill a visible staged value such as `Suggested: codex (not saved)`. Save then writes that concrete agent. The suggestion should exclude the current primary where practical and should come from the existing usable-agent/recommendation logic.

### Show configured versus effective agent

There are two facts to display:

- configured: `Agent claude · Backup codex → grok`;
- runtime override: `Using codex (backup for claude)` after failover.

Do not replace the primary Agent selection with the effective backup, because that would make a temporary sticky override look like a permanent preference. A small status suffix/chip in the context bar and the existing transcript notice make the state understandable. The chain editor can also offer “Reset active failover,” backed by the relay’s existing override reset behavior.

### Persistence and safety

Extend the context bar’s saved/current tuple and dirty tracking to include the backup chain. Save should persist Agent/model and backup together from the user’s perspective. In the relay package, expose a narrow public `setup.write_backup(root, chain)` function instead of making the console call private TOML helpers or `write_roles`. It must preserve roles, pipeline, custom agents, timeout, and planner settings and commit only the config file.

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

Auto’s first Check cannot call existing `preflight.run` unchanged because there is no generated plan yet. Add a structured candidate-workflow preflight which accepts the proposed request/config without first writing it.

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

The workflow’s own operational state must never make this check fail. Store Auto request/checkpoint state in an ignored relay-state file (for example `.whyline/relay/auto-run.json`, added to the relay gitignore), not as an untracked file that dirties the repository. Generated brainstorm, spec, plan, and config artifacts remain normal tracked and committed outputs. Unrelated user changes must still fail the clean-tree check.

Because the plan does not exist yet, Auto also needs a second, automatic preflight after plan approval. That pass calls the ordinary plan-aware relay preflight against the generated plan. A failure there stops before implementation; it must never start merely because the earlier candidate check passed.

## 4. Auto execution semantics

The Auto Run button should launch one durable coordinator owned by `whyline-relay`, while the console streams its progress through the existing relay subprocess mechanism. A TUI-only callback chain would die when the console exits and would make Stop/resume unreliable.

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

The console should only collect/render this request and display structured `Check`/progress events. The relay package should own validation, persistence, checkpoints, artifact transitions, resume, and cancellation. This keeps terminal and future non-TUI callers able to use the same workflow and avoids embedding business rules in widget handlers.

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
- **Console closes:** coordinator continues like a relay run; reopening the console shows its live phase and enables Stop.
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

### Phase C: durable coordinator

- Add the relay engine command/API, ignored checkpoint, structured progress, Stop, and Resume.
- Reuse current brainstorm, spec, planner, approval, plan validation, config, and full preflight primitives.
- Add the automatic second preflight and hand off into ordinary relay start.
- Test phase recovery and idempotence by stopping after each boundary and resuming without duplicating commits or model turns.

### Phase D: end-to-end hardening

- Scratch-repository tests for a clean full run, a failover during brainstorm, a failover during implementation, an unresolved question, a stale check, an artifact collision, final-preflight failure, closing/reopening the console, and Stop/Resume.
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
- Closing the console does not abandon the workflow; Stop actually terminates the active agent process.
- Existing manual Plan and Set up flows behave unchanged.

## One product choice to settle before implementation

Decide whether Auto is allowed to overwrite an existing brainstorm/spec/plan when the user ticks an explicit Replace option, or whether it always requires a new name. The safer default is no overwrite, caught during Check. Everything else can be derived from existing behavior and the recommendation above.
