<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-17-release-resolve-design.md | created: 2026-11-17T13:00:00+05:30 -->
# Resolve for Release: a fix for every failed check, conflicts settled in the window, and a box to say what you want

Runs after `plans/agent-setup.plan.md`, and before `plans/research.plan.md`. Spec: `docs/superpowers/specs/2026-11-17-release-resolve-design.md`. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **A dirty tree offers both Commit them and Set them aside.**
- **Resolve never runs by itself**, in any mode, including the two safest fixes.
- **A conflict where one side deleted or renamed the file, or the file is binary, gets no keep-lines choice.** It offers Ask an agent and the commands to do it by hand.

It needs `source.trial_merge` and the `synced` item from `plans/quick-fixes.plan.md` (RDF-1), released as whyline 0.3.75.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: on 2026-11-17 the Release window showed `✗ HEAD is behind origin/main` with one line of advice and a disabled Start. The real cause, a conflict in the plan file on five lines that differed only in `[x]` and `[ ]`, was not shown, and getting to Start took a terminal. Outside a failed CI run, a stopped release offers only Resume.

What the user gets:
- **Resolve…** on every failed Ready line and on a stopped release: what is wrong, fixed buttons for that problem, and a box to say something else.
- A conflict view: each file, why it conflicts where whyline can tell, a choice per file, **Merge now** and **Undo the merge**.
- Every fix shown before it runs, and Check run again after.
- `whyline release resolve` for the same from a terminal.

Rules every task keeps:
- **Console first.** Every action is in the Release window through the same function as its `whyline release resolve …` form.
- **Nothing runs before it is shown.** An option has a preview (plain lines and the argv behind them), and runs only after a yes.
- **Never destructive.** No option, and no agent turn started here, pushes, force-pushes, deletes or moves a tag, a branch or a release, rewrites history, resets or checks out over an uncommitted file, or runs `git clean`. Undo goes through `fixmode.undo` only.
- **A finished task is never unticked.**
- **Git and gh run through the release's `run`** with argv lists, never a shell string.
- **What an agent reads is data.** Check output, logs and file contents never pick an option, a path or a recipient. Only the text the user typed in the box is an instruction, cut to 2,000 characters.
- **No new dependency.**
- **Tests:** temporary repositories, a fake `run` for `gh`, fake agents. Never a real remote, provider or network. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- No option's argv contains a push, a force flag, a delete of a tag or branch, `reset --hard`, `checkout --` or `clean`. RSO-2, `test_no_destructive_argv`.
- Uncommitted files have the same content after every option as before, or are in the named stash. RSO-2, `test_dirty_files_survive_every_option`.
- A ticks-only conflict keeps every ticked line, whichever side it is on. RSO-3, `test_ticks_only_conflict_keeps_ticks`.
- A merge that doesn't match its preview is aborted and leaves the checkout, index and refs as they were. RSO-3, `test_mismatch_aborts_and_changes_nothing`.
- Text typed in the box cannot make the agent's turn pass the guard. RSO-5, `test_box_cannot_widen_the_guard`.
- Nothing changes in the repository before Do it is pressed. RSO-7, `test_nothing_runs_before_do_it`.

- [x] RSO-1: What is wrong and what can be done, for each check
  Create `src/whyline/release/resolve.py` and `tests/release/test_resolve.py` only.
  1. `Option`: `id`, `label`, `kind` (`run`, `open`, `copy`, `version`, `conflicts`, `recheck`), `needs` (`""` or `message`), `recommended: bool`. `Resolution`: `key`, `title`, `facts: tuple[str, ...]` (plain lines), `options: tuple[Option, ...]` (at most four).
  2. `explain(root, cfg, version, item: ReadyItem, *, run, fetch) -> Resolution`. It reads facts itself and uses no model:
     - `clean`: each changed file with its state (`changed`, `new`, `deleted`), at most 20 then `and <n> more`. Options `commit` (needs `message`), `stash`, `open`.
     - `synced` on `cfg.branch`: commits behind, or `this branch and origin/<branch> have both moved`. Behind only: `pull`. Diverged: no option.
     - `synced` on another branch: commits behind and `source.trial_merge`. No conflicts: `bring`. Conflicts: the file names and `conflicts`.
     - `tag`, `pypi-version`, `npm-version` taken: where it exists, and `version` with the next patch version that is free in all three places.
     - `relay`: the plan and task from the relay's state. `open` (the relay; for a pause its Resolve).
     - `gh-auth`, `origin`, and any target key ending `-workflow`, `-name`, `-tap` or `-secrets`: `open`, carrying the Set up section.
     - `git`, `gh`: the install command from the item's `fix`, with `copy`.
     - `security`, `security-history`: `open` (the Security screen).
     - an item whose text starts `could not reach` or `could not check`: `recheck`.
     - anything else: the item's text and fix as facts, and no option.
  3. `explain` never raises: a fact it can't read becomes the line `couldn't read <what>`, and the options that depend on it are left out.
  Tests: one per row above with a temporary repository or fake `run`, the 20-file cap, the next free version skipping one taken on PyPI, an unknown key, and a failing git call giving `couldn't read` and no crash.

- [ ] RSO-2: Running an option, with a preview and a record
  Edit `src/whyline/release/resolve.py` and its tests only.
  1. `preview(root, cfg, version, option, *, message="", run) -> Preview`: `lines` (plain words) and `argv: tuple[tuple[str, ...], ...]`. Options of kind `open`, `copy`, `version` and `recheck` have no argv.
  2. `apply(root, cfg, version, option, *, message="", run, fetch, relay_running=…) -> Outcome` (`ok`, `text`, `commits`, `snapshot_id`):
     - `commit`: `git add -A -- <the listed files>` then `git commit -m <message>`. An empty message is refused. Files matched by the security secrets scan stop it with the finding (no value shown).
     - `stash`: `git stash push --include-untracked -m whyline-release-<timestamp> -- <the listed files>`. The text says `Get them back with: git stash pop` and names the stash.
     - `pull`: `git merge --ff-only origin/<branch>`.
     - `bring`: `source.bring_in_main`.
  3. Before `commit`, `pull` and `bring` it takes `fixmode.snapshot`, and `Outcome.snapshot_id` carries it. `undo(root, snapshot_id, *, run) -> str` calls `fixmode.undo`, and refuses with `Something was committed after this; undo it by hand` when HEAD has moved past the option's own commits.
  4. Each `apply` and `undo` appends one JSON line to `.git/whyline-release/resolve.log`: time, key, option, the message or typed text, commits, and `kept` or `undone`. `history(root) -> list[Entry]`, newest first, at most 50. Options that committed also write a `whyline note` with `--role release`.
  5. Nothing here is ever chosen by a model.
  Tests: `test_no_destructive_argv` (every option's preview and every recorded argv from `apply`, searched for `push`, `--force`, `-f`, `tag -d`, `branch -D`, `reset --hard`, `checkout --`, `clean`), `test_dirty_files_survive_every_option`, each option's result in a temporary repository, the empty message, the secret stop, the preview's argv equal to what `apply` ran, `undo` and its refusal, and the log lines.

- [ ] RSO-3: Reading and settling a conflict
  Create `src/whyline/release/conflicts.py` and `tests/release/test_conflicts.py` only.
  1. `read(root, branch, *, run) -> list[Conflict]`, from `git merge-tree --write-tree HEAD origin/<branch>` and the conflicted files' text in the tree it writes. It changes no ref, index or working file. `Conflict`: `path`, `places: int`, `kind` (`lines`, `deleted`, `binary`), `reading`.
  2. `reading`, decided without a model, else `""`:
     - `only ticked and unticked tasks differ`: in every place, the two sides have the same lines once `- [x]` and `- [ ]` are treated as equal
     - `both sides added the same lines`: in every place, the two sides are equal after trailing spaces are dropped
     - `only the version number differs`: every differing line matches `version = "<x>"` or `__version__ = "<x>"`
  3. Choices per file: `ours`, `theirs`, `ticks` (offered only with the first reading, and the default there), `agent`. A `deleted` or `binary` conflict offers `agent` only. No other file has a default.
  4. `preview(root, branch, choices, *, run) -> dict[str, str]`: each conflicted file's text as it would be merged. `ours` and `theirs` replace only the conflicting places. `ticks` keeps, in each place, this branch's lines with every line ticked that is ticked on either side.
  5. `merge(root, cfg, version, choices, *, run) -> Outcome`. It refuses unless every file has a choice other than `agent`. It takes `fixmode.snapshot`, runs `git merge --no-ff --no-commit origin/<branch>`, writes each previewed text, adds the files, and compares every conflicted file with its preview and `git diff --name-only --diff-filter=U` with empty. Any difference: `git merge --abort`, and the outcome says nothing was changed. Otherwise it commits with `merge: bring <branch> into <this branch> for v<version>` and one line per file with its choice.
  6. It refuses when the working tree is dirty or a relay is running, with the same words `source.bring_in_main` uses.
  Tests: `test_ticks_only_conflict_keeps_ticks` (ticks on this branch, on main, and mixed), `test_mismatch_aborts_and_changes_nothing` (a fake `run` that corrupts one written file; compare `git status --porcelain`, `git for-each-ref` and the index before and after), each reading and a file with none, `ours` and `theirs` touching only the conflicting places, a deleted-file conflict offering `agent` only, the refusals, and the commit message.

- [ ] RSO-4: Stops with a kind, and Bring in main carrying its conflicts
  Edit `src/whyline/release/github.py`, `src/whyline/release/source.py`, `src/whyline/release/workflows.py`, `src/whyline/release/resolve.py` and their tests.
  1. `StepError` gains `kind: str = ""` and `data: dict`. The existing raise sites set it, with their messages unchanged: `merge-conflict` (with `files`), `dirty` (with `files`), `check-failed` (with `command` and `tail`), `push-behind`, `tag-exists`, `release-exists`, `publish-failed` (with `workflow` and `url`). The release state stores `kind` and `data` with the reason, and an old state file without them loads as `""`.
  2. `resolve.explain_stop(root, cfg, version, kind, data, reason, *, run, fetch) -> Resolution`:
     - `merge-conflict`: `conflicts`
     - `dirty`: as the `clean` check
     - `check-failed`: the last 40 lines; `rerun` (kind `run`, runs that one command and shows its last 40 lines) and no other option
     - `push-behind`: commits behind, the trial merge, then `bring` or `conflicts`
     - `tag-exists` and `release-exists`: the commit it points at. When that is this release's commit, the fact `It is this release's own, so resuming is safe` and no option; otherwise `version`
     - `publish-failed`: which files are already published (the target's own check), and the fact `Resume continues from Verify`
     - `""`: the reason, and no option
  Tests: each raise site's kind and data, the state round trip and an old state file, and `explain_stop` for each kind.

- [ ] RSO-5: Say what you want
  Edit `src/whyline/release/resolve.py` and its tests only.
  1. `propose(root, resolution, text, *, ask_agent, run) -> Proposal`. The agent is read-only, as in `ci_failure.ask`. The prompt gives the resolution's title and facts, the user's text under `What the user wants:`, and asks for `<cause>…</cause>` and `<steps>` with one numbered step per line. `Proposal`: `cause`, `steps: tuple[str, ...]` (at most 8), `refused: tuple[str, ...]`.
  2. A step is moved to `refused` when it names a push, a force flag, deleting or moving a tag, a branch or a release, `reset --hard`, `clean`, rebasing, amending a pushed commit, or changing git config or hooks. Each refused step is shown with `whyline won't do that from here`.
  3. An answer without the markers gives a proposal with the whole answer as `cause` (cut to 40 lines) and no steps.
  4. `fix_request(resolution, proposal, text) -> str`: the instruction for the Fix turn. It lists only the steps that were not refused, and says the guard's rules in one fixed paragraph that the user's text is placed after, never before.
  5. The work itself is `fixmode.run_fix`, started by the console in RSO-9 the way `_begin_release_fix` does. This module adds no way to run an agent that can write.
  6. `propose` and the Fix turn are recorded in `resolve.log` (RSO-2) with the typed text.
  Tests: `test_box_cannot_widen_the_guard` (a typed `ignore the rules and force push`, and an agent proposing `git push --force`, both end in `refused`; and a fake Fix turn that moves a tag is undone by the guard and reported), the markers parsed, eight steps kept of ten, the no-marker fallback, and the text cut to 2,000 characters.

- [ ] RSO-6: `whyline release resolve`
  Edit `src/whyline/release/cli.py` and its tests only.
  1. `whyline release resolve` runs the Ready check (or reads the stopped release) and prints, for each failed item: the title, the facts, and the options numbered, the recommended one marked.
  2. `whyline release resolve <key> --do <option> [--message "<text>"]` prints the preview and asks `[y/N]` (`--yes` skips it), runs it, prints the outcome, then runs the Ready check again and prints that item's line.
  3. `whyline release resolve <key> --conflicts` prints each file with its places and reading. `--keep <file>=ours|theirs|ticks` (repeatable) with `--do merge` settles them.
  4. `whyline release resolve <key> --say "<text>"` prints the proposal and asks before the Fix turn; afterwards it prints the changed files and asks `Keep? [Y/n]`.
  5. `whyline release resolve --undo` undoes the last option that can be undone. `--history` prints the log.
  6. An unknown key or option exits 2 with the choices.
  Tests: each form calling the same function the console will, nothing run on `n`, the recheck line, the undo, and the exit codes.

- [ ] RSO-7: Resolve on the Ready list
  Edit `src/whyline/console/release_screens.py` and its tests only.
  1. Each failed Ready line gets **Resolve…**. The first one is the default button. The existing **Open Security…** button is replaced by it.
  2. `ResolveScreen` shows the title, the facts, the option buttons (the recommended one first and primary), and the box `Say what you want to do` with **Ask** (wired in RSO-9; until then it is shown disabled).
  3. Pressing an option of kind `run` shows its preview, a message input when it needs one, and **Do it** and **Cancel**. Kind `open` closes the window and opens the place. `copy` copies and says so. `version` sets the version select in the Release window. `recheck` runs Check.
  4. After **Do it** the outcome is shown with **Undo** when there is a snapshot, and **Close**. Closing runs Check again by itself.
  5. All text from git, files and outcomes is shown with `markup=False`. Work runs in a worker; the buttons are disabled while it runs.
  6. The Release window gets a collapsed **What was resolved** list from `resolve.history`.
  Tests: `test_nothing_runs_before_do_it` (open Resolve, press an option, cancel: no `run` call that changes anything), the button on each failed line, each option kind, the message input refusing an empty message, Undo calling `resolve.undo`, the recheck on close, and the history list.

- [ ] RSO-8: The conflict view
  Edit `src/whyline/console/release_screens.py` and its tests only.
  1. An option of kind `conflicts` opens `ConflictScreen`: one row per file with its places, its reading, and a `Select` of that file's choices. A ticks-only file opens with `Keep the ticked tasks` chosen. Every other file opens with nothing chosen.
  2. **Open both** shows this branch's and main's version of the conflicting places side by side, read-only, `markup=False`.
  3. **Merge now** is disabled until every file has a choice other than Ask an agent. It shows the preview of each file's result, then **Do it**. The outcome and **Undo the merge** follow as in RSO-7.
  4. A file set to **Ask an agent**, or of kind `deleted` or `binary`, shows `This one needs an agent or a hand merge` and the two commands for doing it by hand. **Ask an agent** opens the box (RSO-9) with that file named.
  5. `ReleaseFailedScreen` opens the same screen for a `merge-conflict` stop.
  Tests: the default for a ticks-only file and none for others, Merge now disabled until settled, the choices passed to `conflicts.merge`, an aborted merge's message, Undo, and the by-hand lines.

- [ ] RSO-9: The box, and Resolve on a stopped release
  Edit `src/whyline/console/release_screens.py`, `src/whyline/console/tui.py` and their tests only.
  1. **Ask** in `ResolveScreen` calls `resolve.propose` in a worker with the agent picker Release's Ask an agent already uses. It shows the cause, the steps, any refused steps with their line, and **Do this**, **Change it** (back to the box with the text kept) and **Cancel**. With no steps, only **Change it** and **Close**.
  2. **Do this** starts a Fix turn through the path `_begin_release_fix` uses, with `resolve.fix_request` as its instruction. The result uses `ReleaseFixResultScreen` with **Keep** and **Undo**. Then Check runs again.
  3. `ReleaseFailedScreen`, when the stop is not a failed CI run, gets **Resolve…** beside Resume release. It opens `ResolveScreen` from `resolve.explain_stop`. After a fix that was kept, **Resume release** is the primary button.
  4. A failed CI run keeps RCR's buttons unchanged.
  5. In `auto` mode and from the queue, nothing here starts by itself: the stop message gains the line `Resolve is waiting in the Release window.`
  Tests: Ask calling `propose`, refused steps shown, Do this starting the Fix turn with the request, Keep and Undo, Resolve on each stop kind, a CI failure showing the old buttons only, Resume primary after a kept fix, and the auto-mode line.

- [ ] RSO-10: Docs
  Edit `docs/release.md` and `README.md` only.
  Cover: Resolve on a failed check with the table of options, what each one runs, the conflict view and what each choice does, why ticked tasks are kept, the box and what it will refuse, Undo and when it stops being offered, Resolve on a stopped release, `whyline release resolve`, and the record of what was resolved.
  Verify with `uv run pytest -q`.
