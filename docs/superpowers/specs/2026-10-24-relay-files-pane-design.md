# Relay Files pane: Working file, Plan, and All files

Date: 2026-10-24
Status: agreed in conversation. Not an approval for this session to implement. Run the plan in Relay when you want it built.
Repo: whyline console (`src/whyline/console`). No whyline-relay change. No version bump, tag, or publish.

## What you asked for

Files stays the shared button it is today. Chat, Relay, and Agents all keep it. Do not remove it from Chat or Agents.

In Relay only, the open Files pane gains three choices:

- **Working file** shows the file the agent is writing now. This is today's follow behavior.
- **Plan** shows the whole Markdown plan for the work in progress. You scroll it yourself.
- **All files** shows the repository as a tree. A folder expands in place. A file opens inside this pane.

The pane changes to a newly written file only while **Working file** is selected. Plan stays on the plan. All files stays on the tree or on the file you opened from the tree.

Opening a file happens inside Whyline. The pane does not launch an external editor. The right side is not split into a tree on top and a file underneath. One choice fills the pane.

Pressing **All files** while a file from the tree is open returns to the tree, still expanded where you left it.

## What this spec assumes

Correct these before treating the spec as accepted.

- This is the Textual console (`whyline` with no arguments). It is not a VS Code extension.
- The existing Files split stays: below 120 columns the transcript and the pane stack; at 120 or more they sit side by side. Header and footer stay full width.
- The pane stays read-only. It never writes a file, never sends one anywhere, and adds no dependency.
- Writes still arrive from disk. The pane does not see an agent's unsaved buffer. The rules in `src/whyline/console/file_follow.py` still decide what a write is.
- Chat and Agents keep today's pane: path line, Earlier, Later, and the read-only view. They do not gain the three choices.
- The **Plan** button on the Relay row (`#relay-plan`) still creates or opens a plan. The **Plan** choice inside Files only displays a plan.

## Approaches

### A. One full-height view inside the existing pane

The three choices sit on their own row. The rest of `#file-pane` shows either the current viewer, the plan in that same viewer, or a `DirectoryTree`. Recommended. A terminal pane is too short to keep a tree and a file useful at the same time, and an external editor would leave the live console.

### B. Tree above the file, permanently

This matches a tall IDE window and fails in an 80x24 terminal. The file would keep only a few rows. Rejected.

### C. Open the file outside the terminal

The system editor would not follow later saves, and the console would no longer be the place you watch the work. Rejected.

## Design

### Choice row

Visible only when Files is on and `session.mode == "relay"`. Three buttons, in this order, with these labels and ids:

| Label | Id | Selected means |
|---|---|---|
| Working file | `file-working` | Today's follow view |
| Plan | `file-plan` | The plan file, in `#file-view` |
| All files | `file-all` | The tree, or a file opened from it |

The selected button uses `variant="success"`. The other two use the default variant. **Working file** is selected when the pane opens.

Earlier (`#file-earlier`) and Later (`#file-later`) are shown only while **Working file** is selected. The path line (`#file-path`) stays. The choice row may wrap. At 80x24 and at 120x40 the three buttons, the path line, and the view must all be on screen without scrolling the choice row away.

Chat and Agents do not mount these three buttons into view. Their Files behavior stays as specified in `docs/superpowers/specs/2026-10-11-console-see-files-design.md`.

### Working file

Unchanged from the see-files spec, with one addition: a new write replaces the text in `#file-view` only while **Working file** is selected.

While **Plan** or **All files** is selected, the follower keeps polling and keeps its ordered list of writes. It does not change the text on screen, the tree, or which choice is selected. Choosing **Working file** again shows the newest write from that list, clears any Earlier/Later hold, and scrolls the way a new path already scrolls.

### Which plan

`active_plan_file(root: Path) -> Path | None` in `src/whyline/console/file_pane.py`.

1. If `whyline_relay.state.load(root)` returns a state whose `plan` is non-empty, that string is the candidate. A relative path is under `root`. This is the run in progress, including a paused run.
2. If no relay state is loaded, the candidate is `relay_ops.configured_plan(root)`, the plan selected in `.whyline/relay/config.toml`.
3. Otherwise there is no candidate.

A missing run plan does not fall through to the configured plan. The run's plan is the one being worked on.

The candidate is shown only when it is a file and `Path.resolve()` stays inside `root.resolve()`. Anything else, including a symlink that leaves the repository, is no plan.

### Plan view

Choosing **Plan** loads that file into the existing read-only `#file-view` and hides the tree. The path line is the path relative to the repository, using forward slashes.

The first load of a path scrolls to the top. A later save of that same path reloads the text and keeps `scroll_x` and `scroll_y`. A change to a different plan path scrolls to the top.

While **Plan** is selected, poll that file's size and modification time on the same cadence as the follower. A failed read leaves the text as it was and puts the reason on the path line once. The run is not stopped.

When there is no plan, `#file-view` is empty and the path line is exactly `No plan yet.`

`file_follow.classify` still applies. A plan that is binary, not UTF-8, or over 1_000_000 bytes shows that function's notice and no body.

### All files

`RepoTree` subclasses Textual's `DirectoryTree` and lives in `file_pane.py`. Its root is the repository. `filter_paths` drops:

- any path whose name is `.git`
- any path that does not resolve inside the repository

Every other directory entry is listed, including ignored files and `.whyline`. The root starts expanded one level. Nested folders start collapsed. File contents are not read until a file is chosen.

Choosing **All files** shows `#file-tree` and hides `#file-view`. The same widget stays mounted, so expansion and the tree's scroll position survive a trip to **Plan** or **Working file** and survive opening a file.

A directory click expands or collapses in place. It does not replace the tree.

`DirectoryTree.FileSelected` hides the tree, shows `#file-view`, and loads that file read-only. **All files** stays the selected choice. The path line is the repository-relative path. The first load scrolls to the top. The same `classify` notices apply. A file that disappears shows `Deleted` and keeps the path, matching the follower.

Pressing **All files** while that file is showing hides the viewer and shows the same tree again. Pressing **All files** while the tree is already showing does nothing.

A new agent write does not replace a tree or a file opened from the tree.

### Errors

A failed directory listing, a failed plan read, or an unreadable file leaves the current body in place when there was one, and puts the reason on the path line once. The agent run continues. The transcript is not cleared.

### Testing

Pure tests in `tests/console/test_file_pane.py` cover `active_plan_file` and `RepoTree.filter_paths`: run state wins over config, a missing run plan does not fall through, a path outside the repository is rejected, `.git` is dropped, and an ignored file is kept.

Console tests in `tests/console/test_see_files.py` use `App.run_test()` and press buttons by id. They must pass at 80x24. Required cases:

- Chat and Agents show Files and do not show `#file-working`, `#file-plan`, or `#file-all`.
- Relay shows the three choices. **Working file** starts selected.
- A fake follow update changes the viewer only while **Working file** is selected. After a switch back from **Plan**, the viewer shows the newest write.
- **Plan** shows the whole fixture plan from the top. A second write of that file keeps `scroll_y`. With no plan, the path line is `No plan yet.`
- **All files** lists a folder and a file, omits `.git`, and expands the folder in place.
- Choosing the file shows its text. Pressing **All files** again shows the tree still expanded.
- A follow update during **All files** does not replace that text.

No network, no real home directory, and no `/Users/` paths in tests. Wait on a widget condition. Do not sleep for a fixed time.

## Out of scope

- Removing Files from Chat or Agents.
- Editing, syntax highlighting, or a row of editor tabs.
- A permanent tree-beside-file split, including on a wide terminal.
- An external editor or a VS Code extension.
- Changing how a plan is created, selected, or executed.
- A release, a version bump, or a whyline-relay change.
- Rewriting the Files help line.
