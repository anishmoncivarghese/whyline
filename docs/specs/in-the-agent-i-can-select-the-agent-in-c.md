# Visible backup chain and Auto plan

## Why

The top bar in `src/whyline/console/tui.py` shows Agent, Model, Repo, "all repos", and Save. Agent is the chat primary. The fallback those chats actually walk is `[backup].chain` in this repo's `.whyline/relay/config.toml`, one ordered list shared by Chat, brainstorm, planning, and relay roles (BC1 in `docs/superpowers/specs/2026-09-27-backup-chain-design.md`). That list is editable only inside Relay → Set up, as one checkbox per installed agent, stored in `relay_agents()` order when Set up's Check runs. A sticky failover is a transcript `failover_notice` plus `.whyline/relay/chat-active-agents.json`. The bar keeps showing the saved primary, so a chat that has already switched looks like the agent the user picked.

Plan has three sources in `RelayPlanScreen._SOURCES`: Brainstorm it, I'll describe it, and I have a plan already. Brainstorm collects models, review passes, the final writer, a 15/30/45/60-minute timeout, attachments, a drafter, and a reviewer, then the main window stops for synthesis, spec, and plan approval. Set up, a later screen, collects implementer, tester, reviewer, release, and the chain, and its Check writes those before `preflight.run`. Nothing gathers the whole workflow, checks it without writing, and runs it through.

This design adds the shared chain to the bar, and adds Auto as a fourth Plan source that checks one unsaved workflow and then runs it through implementation. Brainstorm, describe, and paste keep Make the plan or Save, their approval stops, and Set up.

## Decisions

- The bar edits the existing `[backup].chain`. It does not create a Chat-only backup, and it does not write the chain when "all repos" is ticked. "all repos" still writes only the global default agent and model.
- Automatic is a choice in the control, not a value in `config.toml`. Save writes the names it is showing. A chain that is already saved is left in that order. An empty chain is staged as the logged-in agents except the current primary, in `_PREFERENCE["implementer"]` order (`codex`, `claude`, `antigravity`, `grok`, then any other usable agent). `recommend_roles` stays the empty-state default for implementer, tester, and reviewer only.
- Selecting a named agent moves it to the front and keeps the rest. None clears the chain. Manage chain… edits the full order.
- Save of a chain commits only `.whyline/relay/config.toml`, through `setup.write_backup`. It does not call `write_roles`, and it does not clear `chat-active-agents.json` or `active-roles.json`. A dirty tree of other files does not block this Save.
- The closed bar shows the configured chain (`codex` plus `+1` when longer). A sticky chat override is a separate `using codex` label. Agent keeps the saved primary.
- The bar stays one row. Below 80 columns the Backup select is hidden and the Agent control carries `· bak {head}` and a Backup… row. The fit reserves the timeout select from `docs/specs/in-chat-therr-is-hardocded-limit-of-300s.md` when that widget is mounted.
- Auto is `("Auto — brainstorm to implementation", "auto")`. Brainstorm it stays the default. Auto has no "From:" control and always starts a new brainstorm, then a spec, then a plan. There is no "Write a spec first" toggle on Auto. Describe keeps its checkbox.
- Auto's Check worker is read-only. It calls no model, writes no path under the repository, writes no role or permission file, selects no plan, makes no commit, and does not call `trust_antigravity`, `decline_antigravity`, or `forget_antigravity_decline`. When a named agent is Antigravity and `antigravity_state` is `ask`, the existing trust dialog runs before that worker and is the only writer on this press: Trust it updates the machine settings file outside the repository, Not now writes only the gitignored `.whyline/relay/antigravity-declined` marker, and Escape writes nothing and does not start the worker. Footer Cancel writes nothing and does not undo either answer. Set up's Check keeps saving, because that screen's next button is Start and it has no later persist step.
- `preflight.run(root)` is not used raw for the first check. With no plan argument it still checks `settings.plan` and the saved roles. A missing plan, a finished plan, or a logged-out saved implementer would fail a form that is about to replace them, and Run could never start. The first check uses a new `scope="repository"` and a candidate layer over the unsaved form. The generated plan is checked later with `preflight.run(root, plan)`.
- Images whose delivery is `path-unverified` fail Check unless the form's "Continue anyway" box is ticked. That tick is part of the request. Run does not open the Continue dialog.
- Replace defaults off. A slug clash fails Check. Run does not ask "Replace it?" in the middle.
- The Auto timeout is the brainstorm control. Run writes it to this repo's `timeout_minutes` after the fingerprint matches, so the brainstorm, the spec, the plan, and the relay share one cap. The Chat bar timeout stays in `ConsoleSession` and still must not write `config.toml`.
- The first Auto runner is the existing foreground plan job. Closing the console during planning stops the planning subprocess and keeps a checkpoint. A background coordinator is not part of this release. After `_launch_relay`, the relay's own process and quit dialog stay in charge.
- "Without interruption" skips the synthesis, spec, and plan approval clicks. It does not answer an `## Open questions` section, ignore a `blocked` handoff, ignore `max_visits`, overwrite an artifact, bypass a dirty tree, or start after a stale fingerprint. Those pause with the artifacts kept.
- Auto's phase file is `.whyline/relay/auto-run.json`. The lock is `.whyline/relay/auto-run.lock`. Both join `gitcheck.RELAY_IGNORE`, as does `.whyline/relay/chat-active-agents.json`, so a sticky chat override does not by itself fail the clean-tree line. They are not added only to `.whyline/relay/.gitignore`, because `ensure_relay_gitignore` writes that file once and existing repos would keep the old copy.
- Agents-mode backup checkboxes stay on the scheduled-agent form. They are a different store.

## Design

### 1. Chain read and write

`whyline_relay.setup` gains two functions. `write_roles` keeps its signature for the CLI wizard and for Set up, and the chain half of that write goes through `write_backup` so there is one implementation of the table.

`read_backup(root) -> list[str]` returns `config.load(root).backup_chain`. A missing config file returns `[]`. `ConfigError` and `OSError` propagate. Callers must not turn a parse error into an empty chain.

`write_backup(root, chain, *, commit: bool = True) -> Path` copies `chain`, drops empty strings, and refuses a name that `config.load` would reject, before writing. It replaces only the `[backup]` table through the existing `_set_backup` and `_write_config`. An empty chain removes the table, which is what `_set_backup` does today. Roles, `[planner]`, `[pipeline]`, `[agents]`, `timeout_minutes`, `plan`, `max_rounds`, and `branch_prefix` stay byte-for-byte except for the table edit. With `commit=True` the message is `setup: backup chain codex, grok`, or `setup: backup chain none`. `gitcheck.commit_paths` commits that one path. Unstaged edits already inside `config.toml` ride along, because the writer reads the whole file; every other dirty path stays unstaged.

`write_roles` stops calling `_set_backup` itself. After it builds the role text it calls `write_backup(root, backup, commit=False)` when a chain argument is passed, then commits as it does now when `commit=True`.

Console wrappers in `relay_ops`: `read_backup(root)` and `save_backup(root, chain)`. `current_roles` keeps returning the chain for Set up, read via `read_backup`, still filtered to names `relay_agents` knows. The bar's editor uses `read_backup` unfiltered so a configured name is not hidden.

### 2. Top-bar Backup control

`#context-bar` gains, immediately after `#cb-agent`, a label `#cb-backup-label` ("Backup", help text "Shared fallback: chat, brainstorm, and the relay") and a `Select` `#cb-backup` with `allow_blank=False`. `#context-bar` is `height: 1`. It does not wrap.

The select rows are:

| Value | Prompt |
| --- | --- |
| `automatic` | `Automatic · {resolved}` |
| `none` | `None — no fallback` |
| each name from `relay_agents(root)` | `{name} — {available or the login hint}` |
| `manage` | `Manage chain…` |
| `reset` | `Reset failover (back to {primary})`, only when a chat override exists |

`resolved` is the saved chain joined with ` → `, or the staged empty-chain list from the decision above, or `none` when that stage is empty. The closed prompt for a saved chain is the head agent. A chain longer than one shows a static `#cb-backup-more` whose text is `+1` or `+2` (the count after the head). None shows `None`. While the select value is `automatic` and unsaved, the closed prompt is the Automatic row, including the names.

`manage` and `reset` are actions. On `Select.Changed` the control restores the previous real value (`automatic`, `none`, or an agent) with `prevent(Select.Changed)`. `manage` opens `BackupChainScreen`. `reset` runs only when no chat turn, plan job, or relay run is active.

The dirty tuple grows from `(agent, model, repo)` to `(agent, model, repo, chain)`. `chain` is the tuple the control would write. "all repos" stays a separate dirty flag and is not part of the chain. Save stays disabled until one of those differs. Selecting Automatic over a chain that is already the resolved order does not dirty Save. Selecting it over an empty chain dirties Save with the staged names. Selecting an agent produces `(agent, *rest)` with duplicates removed. Selecting None produces `()`.

`_cb_save` validates the model name first and returns without writing when it is empty or contains a space. It then writes the chain, then the agent and model. A chain change while `_busy_text`, `_plan_state`, `_relay_running()`, or `relay_ops.live_run` is set does not write. The transcript line is `Finish or stop the current job before changing the backup chain.` The select stays dirty. Repo switching keeps its own refusal. "all repos" never calls `save_backup`. After a chain write the transcript line is `Backup for this repo: codex → grok (chat, brainstorm, and the relay).` or `Backup for this repo: none (chat, brainstorm, and the relay).` The agent line stays the current `Default for this repo: …` line.

`#cb-failover` is a label, hidden when `failover.resolve_chat_agent(root, primary) == primary`. Otherwise its text is `using {effective}`. Reset calls `failover.clear_overrides(root, role=primary, storage_path=failover.chat_path(root))` and leaves the chain and `active-roles.json` alone. The transcript line is `Back to {primary}. The chain is still {chain}.`

`/backups` prints the same backup sentence, plus `Using {effective} for {primary} until reset.` when an override exists. `/reset-backup` performs the same clear as the Reset row. Both stop telling the user to run `whyline relay chat`.

### 3. Narrow row

`_cb_fit` keeps today's shrink at `width < 100` (Agent/Model/Repo labels become `A`/`M`/`R`). Backup's label becomes `Bak` at that width. The Backup select's width is 18 at `width >= 110` and 14 below that.

At `width < 80` the Backup label, Backup select, and `+N` label have `display = False`. Each Agent option's prompt becomes `{name} · bak {head}`, where `head` is `none` when the chain is empty, or `auto {head}` while Automatic is the unsaved selection. The Agent dropdown appends one row, value `backup-menu`, prompt `Backup…`. Choosing it restores the agent value and opens `BackupChainScreen`. `#cb-failover` stays visible at this width when an override exists. Save stays on the row. `#cb-timeout` and `#cb-timeout-label`, when the timeout spec has mounted them, stay mounted. This spec does not add them and does not read them.

### 4. Ordered chain editor

`src/whyline/console/chain_editor.py` holds `OrderedChain`, a widget with one row per installed agent: a checkbox and Up / Down buttons. Checking appends the agent. Unchecking removes it. Up and Down swap within the checked order. `order() -> list[str]` is the checked order, not `relay_agents()` order. `load(chain)` checks those names and leaves unknown names visible at the end, disabled, so a config name is not dropped on open. An Automatic button fills an empty list with the staged resolution and does nothing when the list is non-empty. A None button clears the checks.

`BackupChainScreen` is a modal with that widget, Reset failover (same rule as the bar), Save, and Cancel. Save returns the order to the bar, which marks itself dirty and does not write until the bar's Save. Cancel returns nothing.

`RelaySetupScreen` replaces the `#rs-backup-{agent}` checkboxes with one `OrderedChain`. `_chosen()` returns that order. Guided mode still collapses to the one-line summary, `Backup: codex → grok` or `Backup: none`. Set up's Check still calls `save_roles` and `save_release` and `prepare_agents` before `run_checks`. The chain in that call is the editor order. Set up does not gain Automatic as a stored mode. Its Automatic button only fills an empty editor.

### 5. Auto source and the form

`_SOURCES` becomes Brainstorm it, I'll describe it, I have a plan already, and `("Auto — brainstorm to implementation", "auto")`. The default value stays `brainstorm`.

`_show_source("auto")` shows `#rp-auto-group` and hides the paste, draft, and brainstorm groups, including "From:". It shows the existing drafter and reviewer rows. The footer hides Make the plan. It shows `#rp-check` (Check), `#rp-run` (Run, disabled), and Cancel. Resume draft and Discard it stay visible when `pending_draft` or `pending_spec` is set, on every source, because an unfinished draft is what Check will refuse.

`#rp-auto-group` is built from the same builders as the other screens:

- Plan name (`#rp-name`, already on the form) and the topic, model checkboxes, review passes, final write-up, per-agent timeout, and attachments from `brainstorm_field_widgets`.
- Drafter and reviewer, prefilled from `planner_agents`. When the final write-up changes from A to B, the drafter changes to B only if its current value is still A.
- Implementer, tester, reviewer, and release, prefilled from `current_roles` and `release_role` when `roles_configured` is true, otherwise from `recommend_roles(usable_agents)` for the three roles and `human` for release. The chain is prefilled from `read_backup` only, including when the role form was recommended.
- The read-only line `Committer: whyline (automatic)`.
- `OrderedChain` for the shared chain.
- A checkbox `#rp-replace`, "Replace an existing brainstorm, spec, or plan", default off.
- A checkbox `#rp-continue-paths`, "Continue anyway: some agents get images as file paths only", default off.
- A static `#rp-auto-summary`.

The summary is `auto_summary(request)` in `relay_ops`, one line:

`Claude + Codex research → Claude synthesizes → Grok drafts, Codex reviews → Grok implements, Claude tests, Codex reviews → whyline commits → you release. Backup: Claude.`

Release `human` renders as `you`. An empty chain renders as `Backup: none`. A custom `[pipeline]` in the loaded config adds ` This repo has a custom pipeline; Run updates the three role agents and leaves the other stages.`

Describe, brainstorm, and paste do not mount the execution fields, the replace checkbox, or the continue checkbox. Their buttons and `_submit` path stay as they are, including the mid-submit Continue dialog and the Replace confirmation.

The timeout widget is `BRAINSTORM_TIMEOUT_OPTIONS`, default 15. When that shared widget later grows a `none` row, Auto shows it because it uses the widget. `none` is request value `0`. The Chat `#cb-timeout` value is not read.

### 6. AutoRunRequest and the fingerprint

`plan_job.AutoRunRequest` is a frozen dataclass, schema 1:

- `name: str`, `topic: str`, `replace: bool`, `continue_paths: bool`
- `agents: tuple[str, ...]`, `passes: int`, `final_agent: str`, `timeout_minutes: int`
- `attachments: tuple[Path, ...]`
- `drafter: str`, `reviewer: str`
- `implementer: str`, `tester: str`, `reviewer_role: str`, `release: str`
- `chain: tuple[str, ...]`

`0` is the only non-positive timeout, and only when the widget offers `none`. A bool is not a timeout.

`auto_run.fingerprint(root, request) -> str` is sha256 of canonical JSON (`sort_keys=True`, separators `(",", ":")`) of schema 1 plus every field above, and:

- each attachment as path, size, and sha256 of its bytes, or `null` / `null` when the path is missing
- the resolved model string for every named agent, from `whyline.model.load` then `load_global`
- `account.agent_status(root)[agent]["available"]` for every named agent
- `git rev-parse HEAD`
- `git status --porcelain` stdout
- Antigravity trust as `trusted`, `declined`, `ask`, or `unused` when Antigravity is not named

The screen stores the fingerprint of the check that just passed. Any change to an Auto field, the chain order, either checkbox, or the attachments clears `#rp-checks`, drops the stored fingerprint, and disables Run. Switching away from Auto and back does the same.

### 7. What Check verifies

Pressing Check does not start the worker while a named agent is Antigravity and `antigravity_state(root)` is `ask`. Named means every research agent, the final writer, drafter, reviewer, implementer, tester, execution reviewer, every chain member, and release when release is not `human`. The screen pushes the trust dialog first and waits. The dialog is a `ConfirmScreen` subclass whose message, Trust it button, and Not now button match `_with_antigravity`. Its only added binding is Escape dismissing `None`. `_with_antigravity` is unchanged.

- Trust it (`True`) calls `trust_antigravity`. That writes the user's Antigravity settings file, which lives outside the repository, and removes `.whyline/relay/antigravity-declined` only when that marker is already present. From `ask` the marker is absent, so the repository gains no path. Then the worker starts.
- Not now (`False`) calls `decline_antigravity`. That creates `.whyline/relay/antigravity-declined` and no other path. The marker is already in `RELAY_IGNORE`. Then the worker starts.
- Escape (`None`) writes nothing and does not start the worker. `#rp-checks` stays empty and Run stays disabled. A non-True dismiss must not fall through to `decline_antigravity`.
- Any exception from `trust_antigravity` or `decline_antigravity` writes nothing further. The screen shows that message as one FAIL line, does not start the worker, and does not store a fingerprint.

The worker then runs with the same token pattern as Set up. It does not call `save_roles`, `save_release`, `save_planner`, `prepare_agents`, `select_plan`, `trust_antigravity`, `decline_antigravity`, `forget_antigravity_decline`, or any approve function. It creates no file under the repository and does not open the trust dialog. The fingerprint is computed in the worker after the dialog has returned, so the trust value Run recomputes is the value the dialog left behind. The screen stores a fingerprint only for a check with zero `FAIL` lines.

`preflight.run` gains `scope: str = "full"`. `full` is today's result, used by doctor, Set up, and `whyline relay start`. `repository` returns only these results, in today's order: inside a git repo, whyline installed and initialised, relay config loads, permission-bypass flags on configured commands (`bypass.find`), the clean-tree line, and the live-relay line. It does not return plan-file lines or login lines. `allow_dirty` is rejected in this scope (`ValueError`), so the Auto UI cannot pass it. Any other scope raises `ValueError`.

`relay_ops.candidate_checks(root, request) -> list[CheckLine]` adds the form. Status values stay `ok`, `warn`, and `FAIL`. The screen prints them under headings, in this order, using Set up's `f"{status:<4}  {message}"` line. A non-ok line keeps its `fix:` hint.

**Repository.** The `scope="repository"` results. The clean-tree FAIL names `gitcheck.dirty_paths`. The hint is `commit or stash your changes`. It does not mention `--allow-dirty`.

**Agents and logins.** Every research agent, the final writer, drafter, reviewer, implementer, tester, execution reviewer, every chain member, and release when release is not `human`, is in `relay_agents` and `agent_status[...]["available"]` is true where that agent has a login check. A logged-out agent is `FAIL` with the status hint. Antigravity `declined` is `FAIL`: `Antigravity is not trusted for this repo`. Antigravity `trusted` is `ok`. Antigravity `ask` is `FAIL`: `Antigravity trust is not resolved for this repo`. That line does not open the dialog. The generic-agent warning preflight already emits for Antigravity is a `warn` here too.

**Inputs.** Topic non-empty. At least one research agent. Review passes match `^[0-9]+$` (zero is allowed). Timeout is one of the shared widget's values. Each attachment exists, is a file, and is readable. `delivery_for` is not empty for every research agent, the drafter, and the reviewer. An image with delivery `path-unverified` is `FAIL` listing the agents, unless `continue_paths` is true, in which case it is `warn` with the same sentence the Continue dialog uses today. A missing file stays `FAIL` either way.

**Planning.** Drafter and reviewer are non-empty and distinct from the FAIL cases above. `[planner].max_visits` loads as a positive int; the default 3 is `ok` and the form does not edit it. Target paths, using the slug functions that already write them:

- brainstorm: `brainstorm.shared_path(root, topic)` (`docs/brainstorm/{slug}.md`, slug length 60)
- spec: `docs/specs/{specs._slug(name or topic)}.md` (slug length 40)
- plan: `relay_ops.plan_path(root, name or topic)` (`plans/{slug}.plan.md`, slug length 40)

An existing path is `FAIL` naming the path, unless `replace` is true, in which case the line is `ok` and says Run will replace it. `name` falls back to the topic, then to `plan`, matching `_plan_name`.

**Execution.** Implementer, tester, and reviewer are non-empty. Implementer equal to reviewer is the same `warn` preflight already emits, and does not block. Release `human` is `ok`. The implement, test, and review prompt templates resolve, using the same prompt lookup preflight uses for those stages. A custom pipeline is the `warn` in the summary, not a FAIL. The candidate config is built in memory by applying the request's roles, chain, planner, release, and timeout onto the loaded TOML. It is parsed with `config.load` of a synthetic root inside a `tempfile.TemporaryDirectory` created outside the repository and outside the Antigravity settings directory. That directory is removed in a `finally` before the worker returns, including when `config.load` raises. Check does not create the copy under `.whyline/relay/`. A `ConfigError` is `FAIL` with that message.

**Concurrency.** `running.live` is `FAIL` with today's "another relay is running here" line. An unfinished plan or spec draft is `FAIL`: `A plan draft is already unfinished -- open Plan to resume or discard it.` A live `auto-run.lock` whose pid is running is `FAIL`: `An Auto run is already in progress.` A lock whose pid is dead is `ok` and the line says the stale lock will be taken. This console's own `_plan_state` or `_busy_text` is `FAIL`: `Finish or stop the current job first.`

**Will write.** `ok` lines, not counted as failures: the three roles, the release, the chain, the planner pair, and `Relay timeout for this repo becomes 15m` (or `30m`, `45m`, `60m`, or `no limit` when the value is `0`). The line says later relay tasks in this repo use that timeout. These lines do not include Antigravity trust or the decline marker. Trust was settled before the worker, or Antigravity is not named.

Run stays disabled until the latest check has zero `FAIL` lines and the stored fingerprint equals a fresh `fingerprint(root, request)`. Warnings do not block. The screen's own "A relay is already running here" error from Set up is the Concurrency line, so Run is off for that too.

### 8. Run, the checkpoint, and the phases

Run recomputes the fingerprint. A mismatch writes `This check is out of date. Check again.` into the transcript, clears the stored fingerprint, and does not dismiss into a run. A match dismisses the screen with the `AutoRunRequest` and the fingerprint. The main window runs it the way it runs a `PlanRequest`: one worker, progress into the transcript and the thinking line, Stop enabled.

`src/whyline/console/auto_run.py` owns the sequence. `plan_job.run_auto` calls it. Widget handlers do not.

The checkpoint `.whyline/relay/auto-run.json` is schema 1: fingerprint, phase, topic, name, the request as JSON, artifact path and sha256 for brainstorm, spec, and plan, the persist commit sha, `last_check` (the fingerprint), and an optional pause `{reason, actions}`. `actions` is a subset of `resume`, `change`, `replace`, `cancel`. `gitcheck.ensure_relay_ignored` runs before the first write. The lock file holds the pid and is taken with `O_CREAT|O_EXCL`. A dead pid is removed and the lock retaken. A live pid raises `AutoBusy`.

Phases, in order. A phase whose stored artifact exists and whose sha256 matches the file is not called again.

1. **Revalidate.** Fresh fingerprint must equal the dismissed fingerprint. Acquire the lock. Write phase `start`.
2. **Persist.** `write_planner`, `write_roles` (with the chain), `write_release`, and `write_timeout_minutes`, each with `commit=False`, then one `commit_paths` of the config file and the test prompt `write_roles` creates. `timeout_minutes` is the request value, including `0` for no limit. The commit message is `setup: auto run roles, backup, and timeout`. Store that commit sha. If `write_timeout_minutes` is missing from the installed relay, this release's relay package adds it as the timeout spec describes: replace or insert the top-level key, `0` for no limit. Chat still never calls it.
3. **Research.** `adapters.run_brainstorm` with the request's agents, passes, final writer, attachments, and timeout. `timeout_minutes == 0` passes `chat.NO_LIMIT` once that sentinel exists, and until then a request value of `0` is a Check `FAIL` (`No limit is not available yet`) so Run cannot reach this phase without the sentinel. `run_final_synthesis` gains `unattended: bool = False`. Auto passes `True`, which appends one paragraph to the synthesis prompt: decide questions whose answer follows from the request, record each decision in the document, and leave `## Open questions` only for a choice that would change what gets built and cannot be derived from the request. The default `False` leaves today's prompt text unchanged. A finished `docs/brainstorm/{slug}.md` that contains `## Final Synthesis` is the artifact.
4. **Synthesis gate.** `open_questions` on that file, or a brainstorm `blocked` outcome, pauses in the existing answering state. The prompt asked the model to decide; the runner does not invent an answer. The user's answer goes through `revise_synthesis` and this phase runs again. A synthesis with no open questions continues.
5. **Spec.** `draft_spec` from the brainstorm path, the same task text `run_spec_from_synthesis` builds, plus the same unattended paragraph. The planner's own draft/review loop and `[planner].max_visits` (default 3) stay the visit cap. Auto calls `approve_spec` only when that loop returns a non-empty draft and `open_questions` is empty. `replace` is the request flag. `PlanQuestions`, `loop.Paused` for the visit cap, and a `blocked` handoff pause with the draft path and the reason. Actions are Resume, Change settings, and Cancel.
6. **Plan.** `draft_plan` from the approved spec, same visit cap and the same accept rule. `approve_plan` runs only when `planner.validate` / `plan.parse` accepts the draft. A parse error pauses with the draft path. It does not start the relay.
7. **Final preflight.** `select_plan` on the new plan, then `preflight.run(root, plan)` with `scope="full"`. Any `FAIL` stops before `_launch_relay`. The spec, the plan, and the config commit stay. The FAIL lines print, and the transcript says Set up can open on that plan. This phase re-runs on Resume because it is free and must see the tree as it is.
8. **Relay.** `_launch_relay(["start"])` only when phase 7 has zero FAILs. The checkpoint phase becomes `relay`. Progress from here is the relay's own `relay · T1 draft · grok` lines.

Progress before launch is `auto · research 2/4 · codex`, `auto · synthesis · claude`, `auto · spec review 1/3 · codex`, `auto · plan review`, `auto · final preflight`. The counts are the research index and the planner visit index the underlying calls already know.

Stop sets the cancel event on the in-flight `agents.run`, marks the checkpoint `stopped`, and releases the lock. Completed artifacts stay. `agents.run` must accept `cancel_event` as `docs/specs/in-chat-therr-is-hardocded-limit-of-300s.md` specifies: a set event SIGTERMs the process group (`start_new_session=True` is already set) and SIGKILLs it `KILL_GRACE_SECONDS` (5) later, and the child is reaped before `AgentCancelled` leaves `run`. This spec does not add the Chat timeout menu and does not change Chat's 300-second default. Release 3 of this work depends on that parameter. Release 1 does not.

Closing the console during phases 1–7 uses that same cancel and writes `stopped`. It does not offer "Leave it running". After phase 8, `QuitRelayScreen` is unchanged: leave the relay running, or stop it, or stay.

Resume reads the checkpoint, takes the lock, and continues at the first phase whose artifact is missing or whose hash differs. It does not call `approve_spec` or `approve_plan` again when the hash matches, so a repeated resume does not add a second commit of the same file. `commit_paths` is already a no-op when the path has no diff; skipping the approve call avoids rewriting the file. If the saved fingerprint's form no longer matches a fresh fingerprint, Resume stays disabled and the loaded form requires Check. Login, HEAD, and porcelain are part of that fresh fingerprint. The persist commit is allowed to have moved HEAD; resume compares the form fields, the artifact hashes, and a repository-scope check that the tree is clean, not the pre-persist HEAD stored inside the old fingerprint. The screen loads the saved request into the Auto form when the checkpoint is `paused` or `stopped`.

A model failure during research, spec, plan, or the relay walks the chain just written, through the existing `failover.next_backup` path. The transcript names the agent that actually ran, which brainstorm already does for a substituted section. When the chain is exhausted the run pauses with the agents tried. It does not substitute an agent that is not in the chain.

Release `human` still pauses on a release task after the relay starts. That pause is the release role the form already showed. It is not a Check failure.

The bottom-bar Run button is unchanged: no plan yet opens Plan, otherwise it asks new versus existing, and existing opens guided Set up.

## Error handling

- **Unreadable relay config on the bar.** The Backup select shows the error and Save does not write a chain. It does not replace the file with an empty chain.
- **Chain Save during a chat turn, plan job, or relay run.** No write. The select stays dirty. The transcript says to finish or stop the job.
- **`write_backup` raises `GitError`.** The transcript shows the message. Agent and model are not written, because validation happens first and the chain write happens before the model files.
- **Sticky override.** Saving a new chain leaves it. The bar shows `using codex` and Reset. Reset during a job is refused with the same sentence as a chain change.
- **Agent logged out after Check.** The fresh fingerprint differs and Run refuses before any model call. If the agent disappears mid-run, failover walks the saved chain.
- **Chain exhausted.** Pause with the agents tried and the checkpoint. Resume retries only after the user changes the chain or the login and Checks again.
- **Open questions or `blocked`.** Pause once, print the questions or the block reason, keep the artifact. Answering resumes that phase.
- **Visit cap.** Pause with the draft path (`draft-spec.md` or `draft-plan.md`) and the review reason. Resume continues that draft. Cancel discards it through the existing `discard_spec` / `discard_draft`.
- **Slug clash with Replace off.** Check FAIL. Run never starts and never prompts.
- **Final preflight FAIL.** No `_launch_relay`. Artifacts stay committed. Set up can open on the plan.
- **Dirty tree.** Check FAIL from `scope="repository"`. The Auto UI has no dirty override. The run's own `auto-run.json`, lock, and `chat-active-agents.json` are in `RELAY_IGNORE` so they are not the dirty paths.
- **Stale lock.** A dead pid is taken. A live pid fails Check and fails Run.
- **Console closed during planning.** The child is killed, the checkpoint is `stopped`, and the next session offers Resume from the last matching artifact.
- **Antigravity still `ask`.** The dialog opens and the worker does not start. Escape writes nothing and does not check. Not now leaves the gitignored decline marker, then the worker FAILs `Antigravity is not trusted for this repo`. Trust it leaves the machine settings file updated, with no new repository path, and the worker runs.
- **Antigravity settings or the decline marker cannot be written.** The exception text is the only FAIL line. The worker does not start. Run stays off. A fingerprint is not stored.
- **Cancel on the Auto form.** Footer Cancel writes no file and makes no commit. It does not delete `.whyline/relay/antigravity-declined`, does not edit the Antigravity settings file, and does not undo Trust it or Not now from this visit. Closing the screen is the whole effect. Cancel while the trust dialog is up is the dialog's Escape path, because the dialog is modal.
- **Edit after Check.** Fingerprint dropped, Run disabled, output cleared.

## Testing

Relay tests, in the whyline-relay tree, against a scratch git repo:

- `read_backup` on a missing file is `[]`. A `ConfigError` from a bad name is not reported as an empty chain.
- `write_backup` changes the chain and leaves `[roles]`, `[planner]`, `[pipeline]`, `[agents]`, `timeout_minutes`, and `plan` unchanged. The commit's file list is only `config.toml`. An empty chain removes `[backup]`. A second call with the same chain does not make another commit.
- `write_roles` still writes the chain it is given, and a caller that uses `write_backup(commit=False)` plus `write_roles` produces one chain table.
- `preflight.run(root, scope="repository")` has no plan-file line and no login line, fails a dirty tree, and rejects `allow_dirty`. `scope="full"` still reports a missing plan and a logged-out saved role. An unknown scope raises `ValueError`.
- `RELAY_IGNORE` contains `auto-run.json`, `auto-run.lock`, and `chat-active-agents.json`. `ensure_relay_ignored` adds the new lines to an exclude file that already has the old list.

Console tests:

- The bar loads `codex → grok` as head `codex` and `+1`. Save is disabled until the chain changes. None then Save commits an empty chain and leaves a pre-written role line in the file. "all repos" saves the global agent and model and leaves the chain.
- Automatic on a saved chain does not reorder it and does not enable Save. Automatic on an empty chain, with codex logged in as the primary and claude and grok usable, stages `claude, grok` and not the `recommend_roles` backup (which would have dropped the tester and reviewer).
- Selecting claude when the chain is `grok, claude` yields `claude, grok`.
- Save while a fake relay is live writes nothing and leaves the select dirty. Save with a sticky override leaves `chat-active-agents.json` in place and the label reads `using codex`.
- At width 80 with the timeout select mounted, Backup is visible and Save's region ends at or before column 80. At width 79, Backup is hidden, the agent prompt contains `bak`, and `Backup…` opens the editor.
- Set up's editor round-trips `grok, claude` rather than the sorted agent list. Its Check still writes roles.
- Auto is absent from the execution fields on the other three sources. Those sources still build the same `PlanRequest` as before.
- The drafter follows the final writer only while it still equals the previous writer.
- Check on a dirty tree, a logged-out selected agent, a missing attachment, a `path-unverified` image, a slug clash, and a live relay each produce a FAIL in the named group. Antigravity is not in `ask` in these cases, so the dialog does not open. For each, the worker leaves every path under the repository and the Antigravity settings file unchanged, and `git status` is unchanged. The same image with Continue anyway is a warning and Run can enable. Replace off fails the clash; Replace on is an ok line.
- With Antigravity already `trusted`, already `declined`, or not named, the worker does not call `trust_antigravity`, `decline_antigravity`, or `forget_antigravity_decline`.
- Pressing Check while Antigravity is named and the state is `ask` opens the trust dialog and does not start the worker. Escape leaves the repository and the settings file unchanged. Trust it changes the settings file, adds no path under the repository, then the worker's trust line is ok. Not now adds only `.whyline/relay/antigravity-declined`. Where `.git/info/exclude` already lists that pattern, `git status --porcelain` is unchanged. The clean-tree line does not report the marker. Check does not call `ensure_relay_ignored`. The worker then FAILs `Antigravity is not trusted for this repo` and stores no fingerprint. Footer Cancel after Not now leaves the marker. Footer Cancel after Trust it leaves the settings file trusted. A worker that observes `ask` with the dialog skipped FAILs `Antigravity trust is not resolved for this repo` and writes nothing.
- A saved plan that does not exist, and a saved implementer that is logged out, do not fail Check when the form names logged-in agents and a free slug.
- Editing the topic after a clean Check disables Run. Changing only the porcelain (a new untracked file) makes the recomputed fingerprint differ, so Run refuses.
- The 80×24 popup fit test includes the Auto form with Check, Run, and Cancel reachable.
- A fake-runner end-to-end run on a scratch repo commits the config once, the brainstorm, the spec, and the plan, passes the second preflight, and calls the relay launcher once. Stop after each artifact and Resume again: the model fake is not called for a phase whose hash matches, and `git log` shows one commit per artifact.
- An open-questions synthesis pauses and does not draft a spec until an answer returns a synthesis without that section.
- A visit-cap pause does not call `approve_spec`. A final-preflight FAIL does not call the launcher. A dead lock is taken. A live lock fails Check.
- Closing the app object during research sets the cancel event and leaves the checkpoint `stopped`.
- `/backups` and `/reset-backup` print the chain and clear only the chat override.

## Releases

1. **Backup, on its own.** The relay release that adds `read_backup`, `write_backup`, the `scope` argument, and the `RELAY_IGNORE` lines. The console release that depends on that relay floor and ships the bar, the dirty tuple, the narrow row, the ordered editor in Set up and on the bar, the override label and reset, and `/backups` / `/reset-backup`. Manual Plan and Set up's Check-then-Start behavior stay. Auto is not in this release.

2. **Auto form and read-only Check.** `AutoRunRequest`, the shared builders, the Auto source, `candidate_checks`, the fingerprint, and invalidation. The footer is Check and Cancel. Run is not shown. The Check-worker tests assert the repository tree and the Antigravity settings file are unchanged. Trust it and Not now are separate tests. They are the only writes a Check press can make to the repository or the Antigravity settings, and both finish before the worker starts. The runner is not in this release, so a passing Check cannot start work.

3. **Runner.** `auto_run`, the plan-job sequence, the checkpoint, Stop, Resume, the second preflight, and `_launch_relay`. This release depends on `agents.run(..., cancel_event=...)` from the timeout spec. It does not turn on the Chat `none` menu by itself. Run is shown and stays disabled until Check passes. The scratch-repo suite in Testing is the gate for tagging this release: a clean run, failover in research and in the relay, an open question, a stale fingerprint, a slug clash, a failed second preflight, console close during planning, and Stop/Resume that does not commit the same artifact twice.

The work is done when the bar shows this repo's first backup and one action shows the order, Save commits only `config.toml`, a sticky failover reads as `using codex` while Agent shows the saved primary, Auto shows the research, planning, execution, backup, timeout, attachment, and release choices on one screen, Run stays off until this form and this repo state pass Check, a clean run starts the relay only after the generated plan passes full preflight, a real failure pauses with the artifacts kept, and the three existing sources still end in Set up.
