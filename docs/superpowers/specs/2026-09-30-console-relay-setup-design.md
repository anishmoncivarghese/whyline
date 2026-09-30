# Console Relay Setup Design

**Status:** Drafted 2026-09-30, pending user review.

## Goal

Everything the relay needs, from a plan to a running relay, happens inside
`whyline console`, with no trip to a terminal wizard. In Relay mode the
console gains a **Plan** popup (make and approve `plan.md`) and a **Set up**
popup (assign roles, check, start). A started relay runs as its own process,
and its progress streams into the transcript.

## Context

Today the console's Relay mode accepts four typed commands (`doctor`,
`status`, `start`, `resume`). Planning and role assignment live in
`whyline relay setup`, an `input()`-driven terminal wizard. When the relay
isn't configured, switching to Relay mode closes the console and runs that
wizard. `run_relay_oneshot` runs `start` in-process under a process-wide
`redirect_stdout` and shows its output only once the run ends or pauses.

The relay already has most of the engine the console needs:

- `planner.start/_run_pipeline`: a draft<->review pipeline for a free-text
  description, then `review_gate`, whose approve path writes `plan.md` and
  commits only that file.
- `brainstorm.run_pass_zero/run_review_pass/run_final_synthesis`, plus
  `generate_plan_from_synthesis(root, settings, final_agent, models, topic)`,
  which turns `docs/brainstorm/<slug>.md` into a plan draft. A doc's file
  stem is its own slug, so an existing doc works by passing its stem as the
  topic.
- `setup.run_role_wizard`, which writes `.whyline/relay/config.toml` and
  `prompts/test.md`, and `setup.run`, which then commits with `commit_all`.
- `preflight.run(root, plan_path)` (doctor) and `whyline relay stop`, which
  writes a STOP file so the current agent finishes and nothing new starts.

What's missing is a form a UI can call without typed answers:
`review_gate` prints the draft and blocks on `confirm()`, `run_role_wizard`
blocks on `input()`, and the planner's progress goes to stdout.

## Non-goals

- **Antigravity and Grok as relay roles.** The relay's built-in adapters are
  Claude and Codex only. Adding the others is a separate piece of work; the
  role dropdowns list whatever the relay reports as built-in, so they appear
  once it lands.
- **A task picker for Start.** Start runs the plan from its first unchecked
  task. The typed `start --only T3` keeps working for single tasks.
- **Editing a custom `[pipeline]`.** Set up changes the three role
  assignments and the backup chain only.
- **Removing the terminal wizard.** `whyline relay setup` keeps working and
  is rebuilt on the same non-interactive functions.

## Decisions

- **CRS1 -- Two popups, Plan and Set up.** Planning can take many minutes
  of agent time and ends in a human approval; roles and checks take
  seconds. Kept apart, either can be redone alone (change roles without
  re-planning). Rejected: one stepped wizard -- awkward to leave and return
  to mid-plan.
- **CRS2 -- Plan and Set up are Relay-mode-only buttons.** They sit in the
  bottom bar next to Stop and Resume and are disabled in Command and Chat.
- **CRS3 -- Relay mode no longer closes the console when unconfigured.** It
  stays open and says: "No relay setup here yet -- use Plan, then Set up."
  `RELAY_SETUP`'s exit-to-wizard path is removed from `/route relay`.
- **CRS4 -- Start launches the relay as a separate process and streams its
  output.** `whyline relay start --repo <root>` runs via `subprocess.Popen`
  with `PYTHONUNBUFFERED=1` and `start_new_session=True`; a worker thread
  reads its stdout line by line into the transcript. The status line reads
  `running.live(root)` for "T2 · codex implementing · 3m". Rejected:
  in-process with a progress hook (needs a new relay hook and keeps the
  process-wide stdout redirect beside the full-screen UI); status polling
  only (loses the relay's own explanations).
- **CRS5 -- The relay outlives the console.** On quit with a live relay the
  console asks "The relay is still working on T3. Leave it running?" --
  Leave quits and the relay continues; Stop writes STOP, then quits. On the
  next launch, `status` and Resume find it through `running.live`.
- **CRS6 -- Stop in Relay mode writes STOP; it never kills.** The current
  agent finishes its turn and the relay pauses cleanly, so Resume works.
- **CRS7 -- Brainstorm as a plan source offers existing docs.** A dropdown
  lists "New brainstorm" plus each `docs/brainstorm/*.md` in the current
  repo. An existing doc goes straight to `generate_plan_from_synthesis`.
- **CRS8 -- Every setup commit is scoped to its own files.** Plan approval
  already commits only `plan.md`. Role assignment commits only
  `config.toml` and `prompts/test.md` (today `commit_all`).
- **CRS9 -- Set up preserves a custom pipeline.** If `config.toml` exists,
  only the `[roles]` keys and `[backup].chain` are rewritten; otherwise the
  default pipeline template is written.
- **CRS10 -- The relay change ships first.** whyline-relay 0.2.26 adds the
  non-interactive functions; whyline 0.3.29 requires `>=0.2.26`.

## whyline-relay changes (0.2.26)

All new functions take an optional `print_fn` for progress instead of
printing, and raise instead of prompting.

- `planner.draft(root, settings, description, *, print_fn=None,
  timeout_seconds=None) -> Path` -- runs the draft<->review pipeline and
  returns the draft path. Refuses (`PlanAlreadyInProgress`) like `start`.
- `planner.revise(root, settings, feedback, *, print_fn=None) -> Path` --
  re-runs the pipeline with the human's feedback.
- `planner.approve(root, settings, draft_path, *, drafted_by,
  replace=False) -> Path` -- writes `plan.md`, commits only it, clears the
  checkpoint. Raises `PlanExists` when `plan.md` exists and `replace` is
  false.
- `planner.discard(root)` -- exists; unchanged.
- `planner.validate(text) -> list[str]` -- plan-format problems for pasted
  text (empty list when valid), built on `plan.parse`.
- `setup.write_roles(root, implementer, tester, reviewer, backup=()) ->
  list[Path]` -- writes/updates config per CRS9, writes `prompts/test.md`,
  commits only those paths, returns them. `run_role_wizard` becomes its
  `input()` front end.
- `review_gate` and `_human_gate` are rebuilt on `approve`/`revise`/
  `discard`, keeping the terminal flow unchanged.

## Console changes (whyline 0.3.29)

### Bottom bar

Relay mode shows **Plan**, **Set up**, **Stop**, **Resume**. Plan and Set up
are disabled outside Relay mode. Resume is enabled when `state.load` finds a
paused run.

### Plan popup (`RelayPlanScreen`)

- **Source** dropdown: Paste, Draft, Brainstorm. Fields below it change
  with the choice.
- **Paste**: a TextArea. On Save, `planner.validate` runs; problems show in
  the popup's error line. Valid text is saved through `planner.approve`.
- **Draft**: a description box and a reference-paths box (one path per
  line, relative to the repo or absolute). Missing paths are reported
  before anything runs. The description sent to the planner ends with
  "Read these reference documents before planning:" and the paths.
- **Brainstorm**: a "From" dropdown -- "New brainstorm" or an existing doc.
  New shows the Brainstorm popup's fields (topic, models, passes, timeout,
  final writer) as a shared widget group; the run is the same one the
  Brainstorm button does, followed by `generate_plan_from_synthesis`.
  Existing shows a "Plan writer" agent dropdown.
- **Working state**: the popup stays open with a spinner and the progress
  lines from `print_fn`. Cancel is available; a cancelled run's late result
  is discarded (the console's existing token pattern).
- **Review state**: the draft in a read-only scrolling view, with
  **Approve**, **Request changes** (reveals a feedback box and a Send
  button; Send calls `revise` and returns to Working), and **Cancel**
  (`discard`; the draft file stays on disk).
- **Replace confirmation**: if `plan.md` exists, Approve and Paste's Save
  ask "plan.md already exists. Replace it?" first.

### Set up popup (`RelaySetupScreen`)

- **Implementer / Tester / Reviewer** dropdowns listing the relay's built-in
  agents, prefilled from `config.toml` when it exists (defaults codex,
  claude, claude).
- **Backup** checkboxes, one per built-in agent, prefilled likewise.
- **Check**: calls `write_roles`, then runs `preflight.run` in a worker with
  a spinner. Results render as `ok` / `warn` / `FAIL` lines with each
  failure's fix. Changing any field after a check clears the results and
  disables Start.
- **Start**: enabled only when the last check had no FAIL. Closes the popup
  and launches the relay per CRS4.
- A dirty-tree FAIL lists the dirty files. The popup never offers to commit
  them.

### Running relay

- Each stdout line becomes an `output` event, prefixed `relay ·`.
- Exit handling reuses `run_relay_oneshot`'s classification: a pause
  renders the structured pause (task, reason, log) and enables Resume; a
  completion renders "Plan complete"; anything else is an error with the
  last lines of output.
- Resume launches `whyline relay resume` the same way.
- Typed `start`/`resume` in Relay mode use this path too, so there is one
  way the console runs the relay.

## Error handling

- Agent missing, not logged in, or timed out during Draft or Brainstorm:
  the message shows in the popup's error line with **Retry** and
  **Cancel**; every input stays filled in.
- A draft that doesn't parse after the relay's own retry: the problems show
  in the popup and the draft stays at its path, named in the message.
- `PlanAlreadyInProgress`: the popup offers **Resume draft** (planner
  resume) or **Discard it**.
- Another relay already running (`running.live` is set): Start is disabled
  with "A relay is already running here (T3, codex)".
- The relay process fails to launch: an error event with the command that
  failed.
- Home-directory guard: Plan and Set up refuse in `~`, like Chat and Relay
  already do.

## Testing

**whyline-relay**

- `draft`, `revise`, `approve` (including `PlanExists` and `replace=True`),
  `validate`, with fake agents.
- `write_roles`: fresh config, update preserving a custom `[pipeline]`,
  backup chain, and a commit that contains only its own paths while
  unrelated dirty files stay uncommitted.
- The terminal `setup` and `plan` flows still pass their existing tests.

**whyline console** (Textual pilot tests, fake relay functions)

- Plan and Set up are disabled in Command and Chat, enabled in Relay.
- Unconfigured Relay mode stays in the console.
- Plan: Paste valid and invalid; Draft with a missing reference path; Draft
  to Review to Approve; Request changes to Revise; Brainstorm from an
  existing doc; Replace confirmation.
- Set up: prefill from an existing config; Start disabled until a clean
  check; editing a field after a check disables Start again.
- Running relay: a fake `whyline relay` script prints lines slowly; they
  appear in order before it exits; Stop writes the STOP file; the quit
  prompt appears while it runs.

**Manual**

- Run the console in `~/TradingPlatform`: Plan from the PRD via Draft,
  approve, Set up with codex/claude/claude, Check, Start, watch T1 begin,
  Stop.

## Release

1. whyline-relay 0.2.26 (the relay changes), released and on PyPI.
2. whyline 0.3.29 requiring `whyline-relay>=0.2.26,<0.3`.
