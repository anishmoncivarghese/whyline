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
