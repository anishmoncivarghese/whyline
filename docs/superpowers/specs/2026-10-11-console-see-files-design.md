# Console: See files

Date: 2026-10-11
Status: saved from the described behavior. Not an approval to implement.
Repo: whyline console (`src/whyline/console`). No whyline-relay change.

## What you asked for

The console is one terminal screen. While an agent is working, that screen stays the transcript until the turn ends.

You want a control, in the style of VS Code's editor beside the chat. Clicking it splits the console:

- The left side stays the console as it is now.
- The right side opens the file the agent is writing, read-only.
- The file scrolls up and down and left and right, so the whole file can be read.
- As the agent changes that file, the right side shows those saved changes.
- When the agent writes a different file, the right side moves to that file.

## What this spec assumes

Correct these before treating the spec as accepted.

- This is the Textual console (`whyline` with no arguments). It is not a VS Code extension.
- The right side updates when the agent's write reaches the disk. whyline does not receive the agent's private editor buffer, so characters do not appear one by one while the model is still thinking.
- A file the agent only reads does not take the right side. Reads would flicker the pane.
- The split is off until you turn it on. Turning it off gives the console the full width again and leaves the last file in memory for the next time you turn it on.
- Files the agent already wrote earlier in the same turn stay reachable. Following the newest write is the default. Moving back to an earlier file holds that file on screen until you return to the newest one.
- Chat, Relay, Agents, and Brainstorm all count as "an agent is working" once a run is actually in progress. An idle console shows an empty right side.
- The pane never writes the file, never sends it anywhere, and never adds a dependency.

## Approaches

### A. Follow bytes on disk

While a run is in progress and See files is on, notice files in the repository whose size or modification time changed after the run started. Show the newest text file. The ledger's `FileTouched` events are only a hint to look at a path. A hint whose bytes did not change is a read, and the pane ignores it.

This works for Claude, Codex, Grok, and Antigravity, including Grok, which has no hook. It shows each saved version, which is what the CLIs actually produce. Recommended.

### B. Parse each CLI's tool stream

Open the file when the model's tool call names it, before the write finishes. Each CLI's stream is a different format, and chat today waits for the whole turn (`whyline_relay.chat.run_turn`) before the console sees anything. Building four parsers to learn the path a few hundred milliseconds sooner is a second project. Rejected for this spec.

### C. A VS Code extension

A real editor pane, with the agent's cursor. That is a different product, a different install, and it does not help the terminal console you are using. Rejected.

## Design

### Layout

Header and footer stay full width. Between them, a horizontal split:

- Left, `#console-column`: the mode row, context bar, transcript, thinking line, prompt, and buttons, unchanged in behavior.
- Right, `#file-pane`: a path line, Earlier and Later, and a read-only `TextArea` (`soft_wrap=False`, line numbers on, both scrollbars). Textual in this repo is 2.1.2, and `TextArea` already has `read_only` and `soft_wrap`.

The control is a button labeled **Files**, id `see-files`, in the shared button set so Chat, Relay, and Agents all show it. Off, `#file-pane` is `display: none` and the left column is the full width. On, the two columns share the width.

The path line before any write says: `No file yet. A file opens here when an agent writes one.`

### What counts as a write

A follower is armed at the later of these two moments: See files is turned on, or a run starts while it is on. Arming records, for every path `git status --porcelain -z` lists, that path's size and modification time. Paths already dirty at that moment do not open.

On each poll, about every 0.4 seconds, and only while armed:

- List porcelain paths again. Also stat any new `FileTouched` path from `.whyline/ledger.jsonl` since the last offset.
- A path is a write when it is new since the snapshot, or its size or modification time differs.
- Ignore `.whyline/`, `.git/`, anything that does not resolve inside the repository, a file with a NUL byte in its first 8192 bytes, a file over 1_000_000 bytes, and a file that is not valid UTF-8.
- The write with the newest modification time is the file to show. Ignored files produce a single path-line notice (`binary, not shown`, `too large to show (N bytes)`, `not UTF-8, not shown`) and do not load into the text area.
- A path whose bytes did not change is not a write, even when the ledger recorded `FileTouched`. That is how reads stay off the pane.
- Deleting a file that is on screen replaces the text with `Deleted` and keeps the path.

Polling stops when the run stops. The last file stays on screen.

`git status` runs in a worker. A poll still in flight is skipped rather than stacked. The follow logic itself is pure and lives in `src/whyline/console/file_follow.py`. The widget only displays what that module returns.

### Scrolling

The first time a path is shown, scroll to the first line that differs from `git show HEAD:path` (line 1 when the file is new). Later saves of the same file scroll to the first line that differs from the text already on screen, unless you have scrolled yourself. A scroll you made is kept across that save, and the path line says the file was updated. Switching to another path clears that hold and scrolls to the new change.

Earlier and Later walk the files written during this armed session, oldest first. Choosing an earlier file holds it: newer writes join the list and update the path line (`held · N newer`) without replacing the text. Later, once you are back on the newest file, following resumes.

### Modes

`_set_busy(True)` and a running relay both arm the follower when See files is on. `_set_busy(False)` with no relay running disarms it. Stop disarms it. Turning Files off hides the pane and disarms the poll. Turning it on during a run arms from that moment, so the dirty tree you already had does not flood the pane.

Help (`/help` and the Help button) gains one line: `Files    split the console and follow the file the agent is writing`.

### Errors

A failed `git status`, an unreadable file, or a missing ledger leaves the pane as it was and puts the reason on the path line once. The agent run is not stopped and the transcript is not cleared.

### Testing

Pure tests in `tests/console/test_file_follow.py` cover the snapshot, the read-versus-write rule, ignore prefixes, binary and size, the first changed line, and porcelain rename records. Console tests in `tests/console/test_see_files.py` use `App.run_test()` the way `tests/console/test_tui.py` does: the button is in every mode, the pane is hidden until clicked, a fake poll result shows a file, a second path replaces it, and a same-file update after a user scroll does not move `scroll_y`.

## Out of scope

- Editing the file from the pane.
- Streaming tokens from Claude, Codex, Grok, or Antigravity.
- A VS Code, Cursor, or JetBrains extension.
- Syntax highlighting as a requirement. The text area may leave `language` unset.
- Following files outside the repository, including attachment temp files.
- Opening the pane from `whyline run` in a normal terminal. That command hands the terminal to the vendor CLI and has no console to split.
