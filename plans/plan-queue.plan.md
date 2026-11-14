<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-plan-queue-design.md | created: 2026-11-14T23:55:00+05:30 -->
# Plan queue: run several plans one after another, releasing as it goes

Runs after `plans/waiting-on-you.plan.md`, and before `plans/assistant-feedback.plan.md`. Spec: `docs/superpowers/specs/2026-11-14-plan-queue-design.md`. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Rehearse and the release record are not used here.** `plans/release-safety.plan.md` runs later. The go-ahead shows the Ready check's result only. Using Rehearse in the go-ahead is a follow-up for that plan.
- **The install check covers PyPI and npm targets.** Other targets are skipped with a line saying so.
- **No database change.** Telegram cards reuse the tables `waiting-on-you` added.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

There is no publish task. When the relay finishes, press **Release**.

Why: whyline can take one plan from relay to a released version without the user, but it cannot go on to the next plan. Between two plans the user has to notice the relay ended, release, wait, pick the next plan and start it. `plans/RUN-ORDER.md` lists over 30 plans.

What the user gets:
- A **Queue** screen: tick plans, order them, choose `Release` or `Carry on` after each, and Start.
- One setting for the queue, **Publish by itself** or **Ask me before publishing**, and an **Ask me** box per plan.
- The queue runs each relay, releases, checks the published version installs, brings in main and starts the next plan, with the console closed if the user likes.
- Any failure holds the queue where it is and says why. It never skips ahead.

Words used in this plan:
- **item**: one plan in the queue, with its settings and state.
- **stage**: one of `bring-in`, `relay`, `go-ahead`, `release`, `install-check`.
- **hold**: the queue stops at a stage, keeps its place and runs nothing until resumed.

Rules every task keeps:
- **Console first.** Every queue action is in the console's Queue screen and calls the same function as its `whyline queue …` command.
- **The queue removes questions, never checks.** No stage passes a flag or builds a step list that skips a release step, a check, the security scan or Verify. The release it runs is the one `whyline release run --mode auto` runs.
- **A hold never advances.** After any failure the queue's position does not move, and no later item starts.
- **The queue never forces and never edits.** No force push, no deleted tag or branch, no `--no-verify`, no merge strategy option. It never edits a plan, a spec or code.
- **Reuse, don't copy.** Starting a relay, merging main and running a release each go through the existing function named in the task. Where that code is inline today, the task moves it into a function and both callers use it.
- **Inbound text is data.** No Telegram message text chooses a plan, a version, a position or a command. Buttons carry ids that are looked up in the queue's own state.
- **No secret's value** in the state file, the log, a card or a dialog. Hold reasons pass `security.secrets` redaction, and home paths are shown as `~`.
- **No new dependency.**
- **Tests:** never start a real relay, release, `gh`, `uv`, `npm`, Telegram or a remote. Use fakes, temporary repositories and injected `run`, `spawn` and `clock` functions. Never sleep for a fixed time. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- The queue's release runs every step the normal release runs, in the same order. QUE-4, `test_release_stage_runs_every_step`.
- After a hold at any stage, no later item starts and the position is unchanged. QUE-5, `test_hold_never_skips_ahead`.
- A release is never started twice for one plan, by the queue and by `Release when a plan completes`. QUE-5, `test_release_is_not_started_twice`.
- Skip is refused once the item's relay has made a commit. QUE-5, `test_skip_refused_after_a_commit`.
- A go-ahead given for one commit is not used for another. QUE-6, `test_go_ahead_is_for_one_commit`.
- A Telegram tap with an unknown or stale id does nothing, and message text never selects an item. QUE-10, `test_taps_only_act_on_known_ids`.

- [ ] QUE-1: Queue state, lock and log
  Create `src/whyline/queue/__init__.py`, `src/whyline/queue/state.py` and `tests/queue/test_state.py` only.
  1. `@dataclass class Item`: `plan: str` (path relative to the repository), `after: str = "release"` (`release` or `carry-on`), `bump: str = "patch"` (`patch` or `minor`), `ask: bool = False`, `state: str = "waiting"`, `stage: str = ""`, `version: str = ""`, `base_commit: str = ""` (HEAD when its relay started), `started: str = ""`, `finished: str = ""`, `hold_reason: str = ""`.
     - `state` is one of `waiting`, `running`, `releasing`, `waiting-for-you`, `held`, `done`, `skipped`.
  2. `@dataclass class Queue`: `schema: int = 1`, `publish: str = "ask"` (`auto` or `ask`), `items: list[Item]`, `started: str = ""`, `finished: str = ""`, `hold_after_current: bool = False`, `pid: int = 0`, `go_ahead: dict` (empty, or `version`, `commit`, `at`, `by`).
  3. `path(root)` is `.git/whyline-queue/queue.json`. `load(root) -> Queue | None` returns None for a missing file and raises `QueueError` with a plain sentence for an unreadable one or a newer `schema`. `save(root, queue)` writes atomically (`whyline.state.atomic_write_json`). Unknown keys in the file are kept on the next save.
  4. `current(queue) -> Item | None`: the first item not `done` or `skipped`. `active(queue) -> bool`: `started` is set and `finished` is not.
  5. `acquire(root, *, pid_alive=…)` and `release(root)`: a lock file `.git/whyline-queue/runner.lock` holding the pid. A lock whose pid is dead is taken over. A live one raises `QueueBusy`. `running(root, *, pid_alive=…) -> bool`.
  6. `log(root, line)` appends `<ISO time> <line>` to `.git/whyline-queue/queue.log`, after redaction, and keeps the last 2000 lines.
  Tests: round trip, unknown keys kept, a newer schema refused with its sentence, `current` and `active`, the lock taken over from a dead pid and refused for a live one, the log redacting a secret and a home path, and the log trimmed.

- [ ] QUE-2: Order, edits and warnings
  Create `src/whyline/queue/edit.py` and `tests/queue/test_edit.py` only.
  1. `candidates(root) -> list[PlanInfo]`: plans from `console.relay_ops.list_plans` that are in `plans/` itself (not `plans/done/`) and have unticked tasks.
  2. `suggest_order(root, plans) -> list[str]`: the order of the plan names in `plans/RUN-ORDER.md`'s table when that file exists; plans not in it follow, ordered by each one's `Runs after \`plans/<name>\`` line where it names another candidate, then by name. A cycle in the `Runs after` lines falls back to by name.
  3. Edits, each returning the changed `Queue` and raising `QueueError` with a plain sentence when refused: `add(queue, plan, *, after, bump, ask)`, `remove(queue, plan)`, `move(queue, plan, position)`, `set_item(queue, plan, *, after=None, bump=None, ask=None)`, `set_publish(queue, publish)`.
     - Only a `waiting` item can be removed, moved or changed, and it cannot move ahead of an item that is not `waiting`.
     - The last item not `done` or `skipped` is always `after = "release"`. Edits that would leave it `carry-on` set it back, and say so in the returned queue's `notice` (a plain string field on the result, not saved).
     - `ask=False` on an item is ignored while `publish` is `ask`.
     - A plan already in the queue is refused.
  4. `asks(queue, item) -> bool`: `queue.publish == "ask" or item.ask`.
  5. `warnings(root, queue, *, release_cfg, security_settings) -> list[str]`, in plain sentences, none blocking:
     - `<plan> runs after <other>, which isn't finished and isn't earlier in this queue.`
     - `No publish target is set, so Release will only push and tag.`
     - `The security check is off.` and `Secrets are only checked at release.` (the commit hook off)
     - `Nothing upgrades the installed tool after a release.` when the repository's project name is the running tool's (`whyline`) and `release_cfg.after` is empty.
  6. `releases(queue) -> int`: how many items not yet done have `after == "release"`.
  Tests: the order from a RUN-ORDER fixture, from `Runs after` lines and by name, a cycle, each edit and each refusal, the last item forced to release with its notice, `asks` in the four combinations, each warning and its absence, and `releases`.

- [ ] QUE-3: The bring-in and relay stages
  Create `src/whyline/queue/stages.py` and `tests/queue/test_stages.py`. Edit `src/whyline/release/source.py`, `src/whyline/console/relay_ops.py`, `src/whyline/console/tui.py` and their tests.
  1. `source.merge_main(root, cfg, message, *, run, fetch) -> int` holds the fetch, the behind count and the `merge --no-ff` with its abort-on-conflict that `bring_in_main` has today, and returns the number of commits merged. `bring_in_main` calls it, with no change in its behaviour or messages.
  2. `relay_ops.start_args(root, plan: Path) -> list[str]`: the relay arguments the console's Start uses for a plan. Where `tui.py` builds them inline today, it calls this function.
  3. `@dataclass(frozen=True) class Outcome`: `ok: bool`, `hold: str = ""` (the reason, empty when ok), `detail: str = ""`.
  4. `stages.bring_in(root, cfg, item, *, run, fetch) -> Outcome`:
     - refuses when the checkout has uncommitted changes other than release-pending files (the same test `bring_in_main` uses), with `Commit or stash these first: <files>`
     - calls `merge_main` with the message `merge: bring <branch> in before <plan name>`
     - a conflict gives a hold with `source`'s own message
     - then checks the plan file exists and parses; a missing or unparsable plan gives a hold `<plan> is missing after bringing in <branch>` or the parser's message
     - a plan with no unticked task gives `Outcome(True, detail="nothing left")`, and the runner marks it done
  5. `stages.start_relay(root, item, *, launch, checks) -> Outcome`:
     - runs `relay_ops.select_plan` and `relay_ops.run_checks(root, plan)`; any `FAIL` line gives a hold with the first one's text
     - records `item.base_commit` (HEAD)
     - starts the relay with `ideas.run.launch(start_args(root, plan), root=root)`
  6. `stages.relay_outcome(root, item, *, live, paused, plan_tasks) -> Outcome | None`: None while `whyline_relay.running.live(root)` is set. Otherwise ok when every task of the plan is ticked, else a hold with the relay's pause line (`whyline_relay.status.pause_line`) or `The relay stopped at <task> with <n> tasks left`.
  Tests: `bring_in_main` unchanged (its existing tests pass untouched), a merge, a conflict hold with the merge aborted, a dirty checkout, the plan missing after the merge, nothing left, a preflight FAIL holding without a launch, the launch argv equal to `start_args`, `base_commit` recorded, and the three relay outcomes.

- [ ] QUE-4: The release stage and the install check
  Create `src/whyline/queue/installcheck.py` and `tests/queue/test_installcheck.py`. Edit `src/whyline/queue/stages.py`, `src/whyline/release/cli.py`, `src/whyline/release/config.py` and their tests.
  1. `release/cli.py` gets `run_auto(root, cfg, *, bump: str, say, on_progress=None) -> engine.Result`: the version from the existing next-version function for `bump`, the plan from the existing plan builder, then `engine.run(mode="auto")`. `_run` calls it for `--mode auto --yes`, so both paths build one plan.
  2. `stages.release(root, cfg, item, *, run_auto=…) -> Outcome`: calls `run_auto`, stores `item.version`, and returns ok for a finished release. Any other result gives a hold with the result's message. A release already stopped for this checkout (`release.state.load` with `failed_id` or a `You stopped before` reason) is never restarted here: it gives a hold `The release of v<version> is stopped; resume it, then resume the queue`.
  3. `stages.release_done(root, item) -> bool`: no release state is left and the tag `v<item.version>` exists on `origin`. The runner uses it on resume, so a release the user finished by hand is not run again.
  4. `ReleaseConfig.install_check: str = ""`: empty means automatic, `off` turns it off, anything else is the command to run (split with `shlex`, never through a shell), with `{version}` replaced. Read and written like the other fields.
  5. `installcheck.command(root, cfg, version) -> list[str] | None`:
     - the configured command when set
     - PyPI target: `uvx --no-cache --from <project name>==<version> <first console script> --version` when `uv` is on PATH and `pyproject.toml` has `[project.scripts]`
     - npm target: `npx --yes <package>@<version> --version` when `package.json` has a `bin`
     - otherwise None
  6. `installcheck.run(root, cfg, version, *, run, clock, sleep) -> Outcome`: runs the command in an empty temporary folder with a 5-minute timeout. A non-zero exit is tried again every 30 seconds for up to 5 minutes, because a registry's index lags the upload. Still failing gives a hold `v<version> was published but doesn't install or start: <last 3 lines>`. None gives ok with the detail `No install check for this target`.
  Tests: `test_release_stage_runs_every_step` (the step ids `run_auto` hands the engine equal the ids the normal `--mode auto` run builds, in order, for a branch release and a release-branch release), a finished release, a failed one holding with its message, a stopped release not restarted, `release_done`, each `command` form, `off`, a configured command with `{version}`, the retry then success, the hold text, and round trip of `install_check`.

- [ ] QUE-5: The runner
  Create `src/whyline/queue/runner.py` and `tests/queue/test_runner.py`. Edit `src/whyline/console/tui.py` (`_plan_release_due`) and its test.
  1. `runner.step(root, *, stage_fn, clock) -> str` does one stage for the current item and saves, returning `continue`, `wait`, `held` or `finished`:
     - order per item: `bring-in`, `relay` (start, then poll `relay_outcome`), then for `after == "release"`: `go-ahead` when `edit.asks`, `release`, `install-check`
     - a `carry-on` item is `done` after its relay
     - every stage start and end is logged
     - a hold sets the item `held` with its reason and stage, and returns `held`
     - after the last item, `finished` is set and the summary line is logged: `Queue finished: <n> plans, <m> releases (<versions>), <duration>.`
     - `hold_after_current` turns into a hold with the reason `You asked to hold after <plan>` once the current item is done
  2. `runner.run(root, *, spawn, sleep, pid_alive)`: takes the lock, then loops on `step`. Each stage runs as a new process, `[sys.executable, "-m", "whyline", "queue", "stage", <name>]`, waited for. The relay is polled every 20 seconds. The loop ends on `held` or `finished` and releases the lock. An exception in the loop is logged, turned into a hold with its one-line message, and never leaves the lock behind.
  3. `runner.resume(root) -> str`: refused with the reason while the cause is still there (the relay is paused or stopped with tasks left; a release is stopped; the checkout has a merge in progress). Otherwise the item goes back to its stage and the runner can be started. A `release` stage is skipped when `stages.release_done` is true.
  4. `runner.skip(root) -> str`: marks the current item `skipped`, only while `git rev-list --count <base_commit>..HEAD` is 0 or its relay never started. Otherwise it is refused: `<plan> has commits; later plans may build on them. Stop the queue or fix and resume.`
  5. `runner.stop(root)`: sets `finished`, logs it, and leaves the checkout and any running relay alone. It is refused while a release stage is running.
  6. `runner.hold(root, *, after_current: bool)`: `after_current` sets the flag. Without it, a hold is set at once when no stage is running, else after the running stage ends. It never interrupts a relay turn or a release.
  7. The console's `_plan_release_due` returns False while `queue.state.active` is true for the checkout, so `Release when a plan completes` does not start a second release.
  Tests: `test_hold_never_skips_ahead` (a hold injected at each of the five stages, then ten more `step` calls: the position and every later item's state are unchanged), `test_release_is_not_started_twice`, `test_skip_refused_after_a_commit`, a three-item queue with one carry-on run to `finished` with fakes, the summary line, hold after current, resume refused while the relay is paused, resume skipping a release finished by hand, stop refused during a release, an exception becoming a hold with the lock released, and each stage spawned as its own process.

- [ ] QUE-6: The go-ahead
  Create `src/whyline/queue/goahead.py` and `tests/queue/test_goahead.py`. Edit `src/whyline/queue/runner.py` and its tests.
  1. `goahead.prepare(root, cfg, item, *, ready, run) -> Ask`: runs the release's Ready check for the next version and returns `version`, `commit` (HEAD), `tasks` and `commits` (since the last release tag), `ready_ok`, and `text`: `<repo>: <plan stem> is ready to release as v<version>. <n> tasks, <m> commits. Checks passed.` A failed Ready check gives a hold with its first failing item.
  2. The `go-ahead` stage sets the item `waiting-for-you`, saves the `Ask` in the queue, and returns `wait`. The runner polls the queue file every 20 seconds while waiting and runs nothing else.
  3. `goahead.give(root, version, commit, *, by) -> str`: accepted only when both match the saved `Ask` and HEAD is still `commit`. It records `go_ahead` (`version`, `commit`, `at`, `by`: `console`, `terminal` or `telegram`). Otherwise it is refused with `That go-ahead was for <old>; the queue is now at <new>. Check it again.`, and the `Ask` is prepared again.
  4. `goahead.given(root, item) -> bool`: a recorded go-ahead whose commit is HEAD. The release stage is refused without it when `edit.asks`.
  5. `goahead.decline(root)`: holds the queue with `You held the release of v<version>`.
  6. `goahead.reminder_due(queue, *, clock) -> bool`: true once, 6 hours after the `Ask` was saved.
  Tests: `test_go_ahead_is_for_one_commit` (given, then HEAD moves: `given` is false and a new `Ask` is saved), the text, a failed Ready check holding, give with a wrong version or commit refused, decline, the release stage refused without a go-ahead when asked and allowed when not asked, and the reminder true once.

- [ ] QUE-7: The CLI
  Create `src/whyline/queue/cli.py` and `tests/queue/test_cli.py`. Edit `src/whyline/cli.py` (register `queue`) and its test.
  1. Commands, each calling the function named:
     - `whyline queue list`: candidates in suggested order with their task counts (`edit.candidates`, `edit.suggest_order`)
     - `whyline queue add <plan> [--after release|carry-on] [--bump patch|minor] [--ask]`, `remove <plan>`, `move <plan> <position>`, `set <plan> […]`, `publish auto|ask`
     - `whyline queue start [--publish auto|ask] [--yes]`: prints the warnings; with `publish auto` asks `This queue will publish <n> releases without asking. Each one can't be undone. Start? [y/N]` unless `--yes`; refuses with the reason when a relay, a release or a queue is running, the checkout is dirty, or the Ready check fails for sign-in or remote; then starts `whyline queue run` detached (`start_new_session`, output to the queue log)
     - `whyline queue status`: one line per item (`<n>. <plan stem>  <state>  <detail>`), and the hold reason or the go-ahead text
     - `whyline queue hold [--after-current]`, `resume`, `skip`, `stop`
     - `whyline queue go-ahead`: prints the `Ask` text and asks `Release v<version>? This can't be undone. [y/N]` unless `--yes`
     - `whyline queue run` and `whyline queue stage <name>`: used by the runner, hidden from help
  2. A plan is named by its file name or stem, resolved only against `edit.candidates` and the queue's items. A path outside `plans/` is refused.
  3. Exit code 0 on success, 1 for a refusal, with the sentence on stderr.
  Tests: each command calling its function, the start question and `--yes`, each start refusal, a plan name outside the candidates refused, the status lines for every state, and the hidden commands absent from `--help`.

- [ ] QUE-8: The Queue screen: setting up
  Create `src/whyline/console/queue_screen.py` and `tests/console/test_queue_screen.py`. Edit `src/whyline/console/tui.py` (open it from the Relay screen's buttons and the command list) and its test.
  1. `QueueScreen` lists `edit.candidates` in `edit.suggest_order`, one row each:
     - a checkbox
     - the plan's title and `<done> of <total> tasks`
     - **After**: a select, `Release` or `Carry on`
     - **Version**: a select, `patch` or `minor`, shown only for `Release`
     - **Ask me**: a checkbox, disabled and ticked while the queue's setting is `Ask me before publishing`
     - **Up** and **Down**
  2. Above the rows: **Publishing**, a select with `Ask me before publishing` (the default) and `Publish by itself`. Below them: the warnings from `edit.warnings`, then the line `<n> plans, <m> releases`.
  3. **Start** saves through the same functions as the CLI and calls the CLI's start function. With `Publish by itself` it first shows `This queue will publish <m> releases without asking. Each one can't be undone.` with **Start** and **Ask me before each instead**. A refusal is shown in the screen with its reason.
  4. The last ticked row always shows `Release`, with the note `The last plan always releases` when the user picks `Carry on` there.
  5. All plan titles and reasons are shown with `markup=False`. The screen fits 80x24 and scrolls its rows.
  Tests: the rows in suggested order, ticking and reordering saved through `edit`, the last row forced to Release with its note, **Ask me** disabled under the queue setting, the warnings shown, the publish question and both its buttons, a refusal shown, a title with square brackets shown as plain text, and the fit at 80x24.

- [ ] QUE-9: The Queue screen: while it runs
  Edit `src/whyline/console/queue_screen.py`, `src/whyline/console/tui.py` and their tests only.
  1. While `queue.state.active`, the screen shows one row per item with its state in words: `waiting`, `running · <task>, <done> of <total> tasks`, `releasing · <step title>`, `waiting for you`, `held`, `done · v<version>`, `done · carried on`, `skipped`. It refreshes every 2 seconds from the queue file, the relay's live status (`relay_ops.live_status`) and the release state.
  2. Waiting rows keep their controls from QUE-8, plus **Remove**. **Add a plan** lists the candidates not in the queue. The running row has no controls.
  3. Buttons by state:
     - running: **Hold after this plan**, **Stop queue**
     - waiting for you: the `Ask` text, **Publish** (then `Release v<version> to <targets>? This can't be undone.` with **Yes, publish**) and **Hold**
     - held: the reason, **Resume queue**, **Skip this plan**, **Stop queue**, and **Open** which goes to the screen that fixes it (the relay's Resolve for a relay hold, the Release screen for a release hold)
  4. Each button calls the function its CLI command calls. A refusal is shown with its reason.
  5. The console title adds `queue <n> of <total>` while a queue is active, `queue held` when held and `queue waiting for you` at a go-ahead.
  6. When the queue's runner is not alive but the queue is active and not held (the Mac restarted), the screen says `The queue isn't running` with **Start it again**, which calls the same start function.
  Tests: each state's row text, the 2-second refresh with fakes, controls only on waiting rows, each button calling its function, Publish needing the second yes, a refused resume shown, the three title forms, and **Start it again**.

- [ ] QUE-10: Telegram cards for the queue
  Edit `src/whyline/ideas/waiting.py`, `src/whyline/ideas/actions.py`, `src/whyline/ideas/bot.py` and their tests only.
  1. `waiting.scan` gains three kinds, read from each repo's queue file:
     - `queue_held`: text `<repo> queue is holding at <plan stem>: <reason>. <n> plans are waiting behind this.` Buttons: `queue_resume`. When the hold comes from a stopped relay or release, that stop's own card (WAIT-1) is still sent, and this card follows it.
     - `queue_goahead`: the `Ask` text. Buttons: `queue_publish`, `queue_hold`. Key: `<version>|<commit>`.
     - `queue_finished`: the summary line. No buttons.
     Keys change with the item, stage and reason, so WAIT-2's dedupe sends each once. The 6-hour reminder (`goahead.reminder_due`) sends the go-ahead card once more with `Still waiting:` in front.
  2. Actions, registered like WAIT-4's:
     - `queue_resume` (`writes=True`, approval `tap`): `runner.resume`, then starts the runner. A refusal is answered with its reason.
     - `queue_publish` (`writes=True`, approval `tap`): answers with a second card, `Release v<version> to <targets>? This can't be undone.` with **Yes, publish** and **Hold**. **Yes** calls `goahead.give(root, version, commit, by="telegram")` with the version and commit stored in the card's request row, never from message text.
     - `queue_hold` (`writes=True`, approval `tap`): `goahead.decline`.
  3. A tap whose request row is unknown, already answered or for a version and commit the queue has moved past is answered `That card is out of date.` and does nothing.
  4. The cards are on by default and follow WAIT-6's on/off settings for relay and release cards. No new setting.
  Tests: `test_taps_only_act_on_known_ids` (an unknown id, an answered id, a stale version, and free text naming a plan: nothing in the queue changes), each kind's text and buttons, the reminder sent once, publish needing both taps, hold, resume refused with its reason, and the cards off when WAIT-6's setting is off.

- [ ] QUE-11: Docs
  Create `docs/queue.md`. Edit `docs/release.md`, `docs/assistant.md` and `README.md` only.
  Cover: setting up a queue, Release and Carry on, the two publishing settings and the per-plan box, what the queue does for each plan, the install check and its setting, every reason it holds and how to resume, Skip and why it is refused after a commit, the Telegram cards, running it with the console closed, the `whyline queue` commands, and adding an upgrade command to the release's `after` list when the repository's tool is the one running the queue.
  Verify with `uv run pytest -q`.
