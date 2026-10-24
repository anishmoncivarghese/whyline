<!-- whyline-plan v1 | source: draft | drafted-by: grok | spec: docs/superpowers/specs/2026-10-24-relay-files-pane-design.md | created: 2026-10-24T15:43:51+05:30 -->
# Relay Files pane: Working file, Plan, and All files

Spec: `docs/superpowers/specs/2026-10-24-relay-files-pane-design.md`. Read it before each task. Where this plan and the repository disagree about an existing name, follow the repository and keep the spec's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Build on the Files pane that already exists: `#see-files`, `#file-pane`, `#file-path`, `#file-view` (`FollowView`), `#file-earlier`, `#file-later`, and `file_follow.py`. Chat, Relay, and Agents keep the Files button. No whyline-relay edit. No new dependency. No version bump, tag, push, or publish.

The pane stays read-only. One choice fills it. Do not open an external editor. Do not split the pane into a tree above a file. The Relay row's Plan button (`#relay-plan`) is unchanged. The Files help line is unchanged.

Tests use `App.run_test()`, press buttons by id, and `await pilot.pause()` with no duration. No fixed sleep, no network, no real home directory, and no `/Users/` path. New console tests must pass at 80x24. `uv run pytest -q` is the suite command.

Review focus, each one pinned by the test named in its task:

- A follow update while Plan is selected must leave the plan text on screen. PANE-3, `test_follow_update_does_not_replace_plan`.
- A relay state whose plan file is missing must not show the configured plan. PANE-1, `test_missing_run_plan_does_not_fall_through`.
- A candidate that resolves outside the repository must not be read. PANE-1, `test_plan_outside_repo_is_rejected`.
- Pressing All files again after opening a file shows the same tree, still expanded. PANE-4, `test_all_files_again_restores_expanded_tree`.
- Chat does not show the three choices. PANE-3, `test_choices_are_relay_only`.

- [x] PANE-1: Resolve the plan file
  Edit only `src/whyline/console/file_pane.py` (new) and `tests/console/test_file_pane.py` (new).
  `active_plan_file(root: Path) -> Path | None`.
  If `whyline_relay.state.load(root)` returns a state whose `plan` is non-empty, that string is the candidate. A relative path is under `root`. A missing file, a directory, a path that does not resolve inside `root.resolve()`, or any exception from `load` or from resolving the path yields `None`. Do not then read `relay_ops.configured_plan`.
  If `load` returns `None`, the candidate is `relay_ops.configured_plan(root)`, with the same inside-repo file checks. An exception from the config yields `None`.
  Tests, with a real `RelayState` saved through `whyline_relay.state.save` and a config written as `plan = "plans/configured.plan.md"` under `.whyline/relay/config.toml`:
  `test_run_plan_wins` — state points at an existing `plans/run.plan.md`, config points at a different existing file, result is the run file.
  `test_missing_run_plan_does_not_fall_through` — state points at `plans/missing.plan.md`, config file exists, result is `None`.
  `test_configured_plan_when_idle` — no state file, config file exists, result is that file.
  `test_plan_outside_repo_is_rejected` — config `plan` is an absolute path outside `tmp_path`, result is `None`. A symlink inside `tmp_path` whose target is outside it is also `None`.
  `test_no_plan` — no state and no config, result is `None`.
  Verify with `uv run pytest -q tests/console/test_file_pane.py`. Change nothing else.

- [ ] PANE-2: Repository tree that hides .git
  Edit only `src/whyline/console/file_pane.py` and `tests/console/test_file_pane.py`.
  `RepoTree` subclasses `textual.widgets.DirectoryTree`. `filter_paths` drops a path whose name is `.git`, and drops a path that does not resolve inside the tree's root. Every other entry stays, including ignored names and `.whyline`.
  The widget test mounts `RepoTree` in a small Textual app on a temp directory that contains `.git/HEAD`, `.whyline/ledger.jsonl`, `ignored.txt`, and `src/main.py`. After load, the root's children include `src`, `ignored.txt`, and `.whyline`, and do not include `.git`. Expanding `src` shows `main.py`. Selecting `ignored.txt` posts `DirectoryTree.FileSelected` with that path. A symlink inside the temp directory whose target is outside it is not listed.
  The root is expanded one level when the widget mounts. Nested folders start collapsed. Do not read file contents in this task.
  Verify with `uv run pytest -q tests/console/test_file_pane.py`. Change nothing else.

- [ ] PANE-3: Relay choices and the plan view
  Edit only `src/whyline/console/tui.py` and `tests/console/test_see_files.py`.
  Compose `#file-working`, `#file-plan`, and `#file-all` in `#file-pane`, labels `Working file`, `Plan`, and `All files`, in that order, on their own row above the path line. `display` is true only when Files is on and `session.mode == "relay"`. Elsewhere `display` is false, including Chat and Agents. The selected button uses `variant="success"`. Opening the pane in Relay selects Working file.
  `#file-earlier` and `#file-later` have `display` true only while Working file is selected.
  Choosing Plan hides nothing the user cannot get back, loads `active_plan_file` into the existing `#file-view`, and hides any tree. The path line is the path relative to the repository with forward slashes. The first load of a path sets `scroll_x` and `scroll_y` to 0. A later save of that same path reloads the text and keeps both scroll offsets. A different path scrolls to the top. `file_follow.classify` decides a notice; a notice clears the body and the path line is `"{relative} — {notice}"`. No plan: empty view, path line exactly `No plan yet.` A failed read leaves the previous body and puts the reason on the path line once.
  When the follower is already armed and Plan is selected, stat that file on the existing follow poll. Do not start a second timer. When it is not armed, load once on selection.
  `_apply_follow` while Plan or All files is selected still records the path in `_follow_order` and the text in `_follow_shown`, then returns before it changes `#file-view` or `#file-path`. Choosing Working file again loads the newest stored text, clears the Earlier/Later hold, and scrolls the way a newly shown path already scrolls.
  At 80x24 and at 120x40, with Files on in Relay, all three buttons, the path line, and `#file-view` are inside the screen.
  Tests in `tests/console/test_see_files.py`:
  `test_choices_are_relay_only` — after clicking `#see-files`, Chat and Agents have the three buttons with `display` false; Relay has `display` true. `#see-files` stays visible in all three modes.
  `test_working_file_starts_selected` — in Relay, `#file-working` is success and Earlier and Later are shown.
  `test_plan_shows_file_from_the_top` — config selects a three-line plan, `#file-plan` shows all of it, `scroll_y == 0`, and Earlier and Later are not displayed.
  `test_plan_reload_keeps_scroll` — set `scroll_y` away from 0, write the same file again, `scroll_y` is unchanged and the new text is shown. Pointing the config at a different existing plan and selecting Plan again sets `scroll_y` back to 0.
  `test_no_plan_yet` — no state and no config, path line is `No plan yet.`
  `test_follow_update_does_not_replace_plan` — `_apply_follow` with a different path and text while Plan is selected leaves the plan text in `#file-view`. Clicking `#file-working` then shows that follow text.
  `test_choices_fit_at_80_and_120` — the three buttons and `#file-view` intersect the screen at `(80, 24)` and `(120, 40)`.
  Leave `#file-all` selectable. Its tree content is the next task. Until then, choosing it must not raise and must not steal Working file's stored follow text.
  Verify with `uv run pytest -q tests/console/test_see_files.py tests/console/test_file_pane.py`. Change nothing else.

- [ ] PANE-4: All files, open a file, and come back
  Edit only `src/whyline/console/tui.py` and `tests/console/test_see_files.py`.
  Mount one `#file-tree` (`RepoTree` on the session root) in `#file-pane` and keep it mounted for the life of the app. Choosing All files shows `#file-tree`, hides `#file-view`, and leaves All files selected. Choosing Working file or Plan hides `#file-tree` and shows `#file-view`.
  A directory click expands or collapses in place. `DirectoryTree.FileSelected` hides `#file-tree`, shows `#file-view`, loads that file read-only, and keeps All files selected. The path line is repository-relative with forward slashes. The first load scrolls to the top. `classify` notices and a missing file (`Deleted` on the path line, body cleared) match the follower.
  Pressing `#file-all` while that file is showing hides `#file-view` and shows the same `#file-tree` instance, still expanded where it was. Pressing `#file-all` while the tree is already showing does nothing.
  A follow update during All files does not change the tree, the open file's text, or the selected choice.
  Tests, on a temp repo with `src/main.py` containing `hello`, a nested folder left collapsed, and a `.git` directory:
  `test_all_files_lists_folder_and_hides_git` — `#file-all` shows `src` and does not show `.git`.
  `test_folder_expands_in_place` — expanding `src` shows `main.py` and the tree remains on screen.
  `test_open_file_from_tree` — `FileSelected` for `src/main.py` shows `hello` in `#file-view`, `#file-tree` is not displayed, and `#file-all` stays success.
  `test_all_files_again_restores_expanded_tree` — after that open, clicking `#file-all` shows the same tree with `src` still expanded. Clicking `#file-plan` and then `#file-all` shows that same tree, still expanded. Clicking `#file-all` while the tree is already showing leaves it displayed.
  `test_follow_does_not_steal_tree_file` — `_apply_follow` of another path while that file is open leaves `hello` on screen and leaves All files selected.
  `test_binary_tree_file_is_a_notice` — a file with a NUL in the first 8192 bytes shows `binary, not shown` and an empty body.
  `test_deleted_tree_file` — after the file is shown, delete it and select it again. The path line is `Deleted` and the body is empty.
  Verify with `uv run pytest -q tests/console/test_see_files.py tests/console/test_file_pane.py` and then `uv run pytest -q`. Change nothing else.
