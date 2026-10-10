# Grok Plan for Enhancement

## Console See files — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Files button that splits the whyline console and shows, read-only, the file an agent is writing, following each new file.

**Architecture:** `file_follow.py` decides which repository path changed after the follower was armed. The console paints that decision into a hidden-by-default right-hand `TextArea`. Git and the ledger are inputs to the pure module. The widget never writes a file and never parses a vendor tool stream.

**Tech Stack:** Python 3.11+, Textual 2.1.2 (`TextArea` with `read_only` and `soft_wrap`), pytest with `App.run_test()`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-11-console-see-files-design.md`

**Status:** suggested. Review the spec and this plan before executing. Do not start coding from this file until that review says to.

## Global Constraints

- Python `>=3.11`. The follow module uses the standard library only.
- Textual stays `>=0.60,<1` as already pinned; the installed version this plan was written against is 2.1.2. Use `TextArea(read_only=True, soft_wrap=False, show_line_numbers=True)`.
- No new package, no network call, no telemetry.
- The pane never writes or deletes the file it shows, and a follow failure must not cancel the agent run or clear the transcript.
- Buttons stay `width: auto` (see the comment above `WhylineConsoleApp.DEFAULT_CSS`). The new label is `Files`, not a long sentence.
- macOS and Linux are the tested platforms. Do not add a Windows-only path.
- `FileTouched` in the ledger is a hint. A path whose size and modification time are unchanged is not shown. That keeps reads off the pane. Antigravity already records writes only; Claude and Codex record any tool that carries a `file_path`.
- Files already dirty at the moment the follower is armed stay off the pane until they change again.

## Review Focus

These are the inputs most likely to show the wrong file. Each one has a test in the task that owns it.

- A repository that is already dirty when Files is turned on must keep the placeholder until a later write. Task 1, `test_existing_dirty_path_is_not_a_write_until_it_changes`.
- A ledger `FileTouched` whose bytes did not change must not become the current file. Task 1, `test_unchanged_hint_is_not_a_write`.
- A NUL in the first 8192 bytes, a file over 1_000_000 bytes, and a non-UTF-8 file must produce a notice and no text body. Task 1, `test_binary_oversize_and_non_utf8_are_notices`.
- `.whyline/` and `.git/` must never be the followed path. Task 1, `test_whyline_and_git_paths_are_ignored`.
- After the user scrolls the text area, a later save of the same file must keep `scroll_y`. Task 3, `test_same_file_update_keeps_user_scroll`.

---

## File structure

- Create `src/whyline/console/file_follow.py`. Pure decisions: parse porcelain, snapshot, poll, classify a file, first changed line. No Textual import.
- Create `tests/console/test_file_follow.py`. Unit tests for that module.
- Create `tests/console/test_see_files.py`. `App.run_test()` tests for the button, the hidden pane, and scroll.
- Modify `src/whyline/console/tui.py`. Button, split, pane, arm/disarm from `_set_busy` and the relay-running path, paint a `FollowUpdate`.
- Modify `src/whyline/console/repl.py` `_help_text`. One Files line.

Do not change whyline-relay, the ledger schema, or hooks.

### Task 1: Decide which file changed

**Files:**
- Create: `src/whyline/console/file_follow.py`
- Test: `tests/console/test_file_follow.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `MAX_BYTES: int = 1_000_000`
  - `SAMPLE_BYTES: int = 8192`
  - `@dataclass(frozen=True) class Snap: mtime_ns: int; size: int`
  - `@dataclass(frozen=True) class FollowUpdate: path: str; text: str | None; notice: str | None; changed_line: int`
  - `def parse_porcelain_z(blob: bytes) -> list[str]`
  - `def is_ignored(rel: str) -> bool`
  - `def classify(raw: bytes) -> str | None` — returns a notice, or `None` when `raw` is UTF-8 text of an allowed size
  - `def first_changed_line(before: str, after: str) -> int` — 1-based
  - `def poll(baseline: dict[str, Snap], found: dict[str, tuple[Snap, bytes]], hints: list[str]) -> tuple[dict[str, Snap], FollowUpdate | None]`
    `found` maps a repo-relative posix path to its new snap and its full bytes. `hints` are ledger paths to consider even when absent from porcelain; the caller has already dropped ignored paths. The returned dict is the new baseline.

- [ ] **Step 1: Write the failing test**

```python
from whyline.console.file_follow import (
    Snap, classify, first_changed_line, is_ignored, parse_porcelain_z, poll,
)

def test_porcelain_rename_keeps_the_new_path():
    blob = b"R  old.py\0new.py\0 M keep.py\0"
    assert parse_porcelain_z(blob) == ["new.py", "keep.py"]

def test_whyline_and_git_paths_are_ignored():
    assert is_ignored(".whyline/ledger.jsonl")
    assert is_ignored(".git/index")
    assert not is_ignored("src/whyline/console/tui.py")

def test_existing_dirty_path_is_not_a_write_until_it_changes():
    snap = Snap(mtime_ns=10, size=3)
    baseline, update = poll({"a.py": snap}, {"a.py": (snap, b"abc")}, [])
    assert update is None
    assert baseline["a.py"] == snap
    changed = Snap(mtime_ns=11, size=4)
    baseline, update = poll(baseline, {"a.py": (changed, b"abcd")}, [])
    assert update is not None
    assert update.path == "a.py"
    assert update.text == "abcd"
    assert update.notice is None

def test_unchanged_hint_is_not_a_write():
    snap = Snap(mtime_ns=5, size=1)
    _, update = poll({"a.py": snap}, {"a.py": (snap, b"a")}, ["a.py"])
    assert update is None

def test_binary_oversize_and_non_utf8_are_notices():
    assert classify(b"a\0b") == "binary, not shown"
    assert classify(b"x" * (1_000_001)) == "too large to show (1000001 bytes)"
    assert classify(b"\xff") == "not UTF-8, not shown"
    assert classify("ok\n".encode()) is None

def test_newest_mtime_wins_and_ignored_hint_never_arrives_as_text():
    older = Snap(mtime_ns=1, size=1)
    newer = Snap(mtime_ns=9, size=1)
    _, update = poll({}, {"a.py": (older, b"a"), "b.py": (newer, b"b")}, [])
    assert update.path == "b.py"

def test_first_changed_line_is_one_based():
    assert first_changed_line("a\nb\n", "a\nB\n") == 2
    assert first_changed_line("", "new\n") == 1
    assert first_changed_line("a\n", "a\nb\n") == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/console/test_file_follow.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'whyline.console.file_follow'`

- [ ] **Step 3: Write the minimal implementation**

`parse_porcelain_z`: walk NUL-separated records. Each record is `XY PATH` with `XY` the first two bytes and the path starting at byte 3. When either status character is `R` or `C`, the next NUL-terminated field is the destination; return that destination and skip the source. Decode paths as UTF-8 with `surrogateescape`.

`is_ignored`: true when the posix path is `.whyline`, `.git`, or starts with `.whyline/` or `.git/`.

`classify`: if `len(raw) > MAX_BYTES`, return `too large to show ({len} bytes)`. If `b"\0" in raw[:SAMPLE_BYTES]`, return `binary, not shown`. If `raw.decode("utf-8")` raises `UnicodeDecodeError`, return `not UTF-8, not shown`. Otherwise return `None`.

`poll`: copy `baseline`. Consider every key of `found` and every hint that is also a key of `found`. Skip `is_ignored`. A path is a candidate when it is absent from the old baseline or `found[path][0] != baseline[path]`. Among candidates, choose the greatest `mtime_ns`. Replace that path's baseline entry with the new snap before returning. If `classify` returns a notice, `FollowUpdate.text` is `None`, `notice` is that string, and `changed_line` is 1. Otherwise `text` is the UTF-8 decode, `notice` is `None`, and `changed_line` is `first_changed_line("", text)`. `poll` does not see the previous body. Task 3 calls `first_changed_line` again with the text already on screen.

`first_changed_line`: split both sides with `splitlines()`. Walk zipped lines from 1. Return the first index whose lines differ. If one side is longer, return `min(len(old), len(new)) + 1`. If they are equal, return 1.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/console/test_file_follow.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/whyline/console/file_follow.py tests/console/test_file_follow.py
git commit -m "feat: decide which file the console should follow"
```

### Task 2: Split the console and keep the pane hidden

**Files:**
- Modify: `src/whyline/console/tui.py` (`_SHARED_BUTTONS`, `DEFAULT_CSS`, `compose`, a new `FilePane` is not required — build the pane inline)
- Modify: `src/whyline/console/repl.py` (`_help_text`)
- Test: `tests/console/test_see_files.py`

**Interfaces:**
- Consumes: nothing from Task 1 yet. The pane can show the placeholder with no follower.
- Produces: widget ids the next task paints into:
  - `#see-files` button, label `Files`, in `_SHARED_BUTTONS`
  - `#split` `Horizontal`
  - `#console-column` `Vertical` holding every widget `compose` yields today between the header and the footer
  - `#file-pane` `Vertical`, `display: none` until the button is pressed
  - `#file-path` `Static`
  - `#file-earlier` and `#file-later` buttons, labels `Earlier` and `Later`, both `disabled=True` at start
  - `#file-view` `TextArea(read_only=True, soft_wrap=False, show_line_numbers=True)`
  - `WhylineConsoleApp._files_on: bool` starting `False`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from whyline.console import tui

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")

@pytest.mark.asyncio
async def test_files_button_is_shared_and_the_pane_starts_hidden(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        button = app.query_one("#see-files", tui.Button)
        assert button.label == "Files"
        assert button.display is True
        assert app.query_one("#file-pane").display is False
        assert app.query_one("#transcript") is not None
        await pilot.click("#see-files")
        await pilot.pause()
        assert app.query_one("#file-pane").display is True
        assert "No file yet" in str(app.query_one("#file-path").renderable)
        view = app.query_one("#file-view", tui.TextArea)
        assert view.read_only is True
        assert view.soft_wrap is False

@pytest.mark.asyncio
async def test_files_button_stays_in_relay_and_agents(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        for mode in ("relay", "agents", "chat"):
            await pilot.click(f"#mode-{mode}")
            await pilot.pause()
            assert app.query_one("#see-files").display is True
```

Import `TextArea` the same way `tui.py` imports it. If the module imports Textual symbols only inside `if TUI_AVAILABLE`, the test should use `from textual.widgets import Button, TextArea` under the same skip. Match `tests/console/test_tui.py`, which uses `tui.Input` and `tui.RichLog`, so export or reuse the names `tui.py` already binds. `Button` is already used as `tui.Button` only if it is imported into the module namespace. `test_tui.py` uses `tui.Input` and `tui.RichLog`. Follow that: `app.query_one("#see-files", tui.Button)`.

Add a help assertion that does not need the app:

```python
def test_help_mentions_files():
    from whyline.console.repl import _help_text
    assert "Files" in _help_text()
    assert "follow the file" in _help_text()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/console/test_see_files.py -v`

Expected: FAIL with `NoMatches` on `#see-files`

- [ ] **Step 3: Write the minimal implementation**

In `tui.py`:

- Add `"see-files"` to `_SHARED_BUTTONS`.
- In `compose`, yield `Button("Files", id="see-files")` inside `#controls`, before Stop.
- Wrap the widgets that are currently direct children between `Header()` and `Footer()` in `Vertical(..., id="console-column")`. Yield `Horizontal(column, pane, id="split")` instead of yielding those widgets at the app root. `query_one("#transcript")` must still work.
- Pane:

```python
pane = Vertical(
    Horizontal(
        Static("No file yet. A file opens here when an agent writes one.", id="file-path"),
        Button("Earlier", id="file-earlier", disabled=True),
        Button("Later", id="file-later", disabled=True),
    ),
    TextArea("", id="file-view", read_only=True, soft_wrap=False, show_line_numbers=True),
    id="file-pane",
)
```

- CSS:

```css
#split { height: 1fr; }
#console-column { width: 1fr; height: 1fr; }
#file-pane { width: 1fr; height: 1fr; display: none; }
#file-path { width: 1fr; height: 1; padding: 0 1; }
#file-view { height: 1fr; }
#file-pane Horizontal { height: auto; }
```

Keep the existing rule `RichLog#transcript { height: 1fr; }`. Do not set `#file-pane` to `height: auto`.

- `on_button_pressed`: `see-files` toggles `self._files_on` and `#file-pane.display`. Turning it off does not clear `#file-view`.
- Initialize `self._files_on = False` next to `self._busy_text = ""`.

In `repl.py` `_help_text`, after the Modes block, add the line:

```python
"Files    split the console and follow the file the agent is writing",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/console/test_see_files.py tests/console/test_tui.py -v`

Expected: PASS, including `test_app_composes_header_transcript_prompt_and_controls`

- [ ] **Step 5: Commit**

```bash
git add src/whyline/console/tui.py src/whyline/console/repl.py tests/console/test_see_files.py
git commit -m "feat: add a hidden file pane beside the console"
```

### Task 3: Follow writes while a run is busy

**Files:**
- Modify: `src/whyline/console/tui.py` (`_set_busy`, relay running, Stop, the Files toggle)
- Modify: `tests/console/test_see_files.py`

**Interfaces:**
- Consumes from Task 1: `Snap`, `FollowUpdate`, `poll`, `is_ignored`, `parse_porcelain_z`, `first_changed_line`, `classify` is used inside `poll`.
- Consumes from Task 2: `#file-pane`, `#file-path`, `#file-view`, `#file-earlier`, `#file-later`, `_files_on`.
- Produces on `WhylineConsoleApp`:
  - `_follow_base: dict[str, Snap]`
  - `_follow_order: list[str]` oldest first
  - `_follow_index: int | None`
  - `_follow_hold: bool`
  - `_follow_shown: dict[str, str]`
  - `_follow_offset: int` byte offset into `.whyline/ledger.jsonl`
  - `_follow_poll_flying: bool`
  - `def _arm_follow(self) -> None`
  - `def _disarm_follow(self) -> None` leaves the text on screen
  - `def _follow_tick(self) -> None` called from the existing busy tick path, or from `set_interval(0.4, ...)` started in `_arm_follow` and stopped in `_disarm_follow`
  - `def _apply_follow(self, update: FollowUpdate, previous: str) -> None`

The worker side, so tests can skip git, is a method that accepts an injected result:

- `def _apply_follow(self, update: FollowUpdate) -> None` is what tests call. Gathering porcelain, snaps, hints, and `HEAD` text is `_gather_follow(self) -> FollowUpdate | None`, which tests replace.

- [ ] **Step 1: Write the failing test**

Add to `tests/console/test_see_files.py`:

```python
@pytest.mark.asyncio
async def test_a_write_opens_on_the_right_and_a_second_file_replaces_it(tmp_path):
    from whyline.console.file_follow import FollowUpdate
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#see-files")
        app._apply_follow(FollowUpdate("src/a.py", "one\n", None, 1))
        await pilot.pause()
        view = app.query_one("#file-view", tui.TextArea)
        assert view.text == "one\n"
        assert "src/a.py" in str(app.query_one("#file-path").renderable)
        app._apply_follow(FollowUpdate("src/b.py", "two\n", None, 1))
        await pilot.pause()
        assert view.text == "two\n"
        assert "src/b.py" in str(app.query_one("#file-path").renderable)
        await pilot.click("#file-earlier")
        await pilot.pause()
        assert view.text == "one\n"
        assert app._follow_hold is True

@pytest.mark.asyncio
async def test_same_file_update_keeps_user_scroll(tmp_path):
    from whyline.console.file_follow import FollowUpdate
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#see-files")
        body = "\n".join(f"line {i}" for i in range(80)) + "\n"
        app._apply_follow(FollowUpdate("src/a.py", body, None, 1))
        await pilot.pause()
        view = app.query_one("#file-view", tui.TextArea)
        view.scroll_y = 20
        app._follow_user_scrolled = True
        nxt = body + "tail\n"
        app._apply_follow(FollowUpdate("src/a.py", nxt, None, 81))
        await pilot.pause()
        assert view.scroll_y == 20
        assert "updated" in str(app.query_one("#file-path").renderable).lower()

@pytest.mark.asyncio
async def test_notice_does_not_dump_bytes(tmp_path):
    from whyline.console.file_follow import FollowUpdate
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#see-files")
        app._apply_follow(FollowUpdate("blob.bin", None, "binary, not shown", 1))
        await pilot.pause()
        assert app.query_one("#file-view", tui.TextArea).text == ""
        assert "binary, not shown" in str(app.query_one("#file-path").renderable)

@pytest.mark.asyncio
async def test_busy_arms_and_idle_disarms_without_clearing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tui.WhylineConsoleApp, "_arm_follow", lambda self: calls.append("arm"))
    monkeypatch.setattr(tui.WhylineConsoleApp, "_disarm_follow", lambda self: calls.append("disarm"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.click("#see-files")
        app._set_busy(True, "claude")
        app._set_busy(False)
        await pilot.pause()
        assert calls == ["arm", "disarm"]
```

`_set_busy(False)` must call `_disarm_follow` only when the relay is not running. The test does not start a relay, so one disarm is correct. `_set_busy(True)` calls `_arm_follow` only when `_files_on` is already true. Click Files first.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/console/test_see_files.py -v`

Expected: FAIL with `AttributeError: _apply_follow`

- [ ] **Step 3: Write the minimal implementation**

State on the app, initialized in `__init__`:

```python
self._follow_base = {}
self._follow_order = []
self._follow_index = None
self._follow_hold = False
self._follow_shown = {}
self._follow_offset = 0
self._follow_poll_flying = False
self._follow_user_scrolled = False
self._follow_timer = None
```

`_arm_follow`: if the timer is already running, return. Set `_follow_base` by statting every `parse_porcelain_z` path that is not ignored (missing files are simply absent). Set `_follow_offset` to the ledger's current size, or 0 if there is no ledger. Start `self.set_interval(0.4, self._follow_tick)` and keep the handle.

`_disarm_follow`: stop and drop the timer. Do not clear `#file-view` or `_follow_order`.

`_set_busy(True, ...)`: existing behavior, then if `self._files_on`: `_arm_follow()`.

`_set_busy(False)`: existing behavior, then if not `self._relay_running()`: `_disarm_follow()`.

Where a relay run sets the thinking line without `_set_busy` (the external-relay watch around `_watch_external_relay` / the block that sets `_busy_since` near the relay start), call `_arm_follow()` when Files is on and `_disarm_follow()` when that run goes idle and `_busy_text` is empty. Read those two sites and add the calls there. Do not arm on an idle status poll.

Files toggle on: if `_busy_text` or `_relay_running()`, `_arm_follow()`. Files toggle off: `_disarm_follow()` and hide the pane.

`_follow_tick`: if `_follow_poll_flying`, return. Set the flag, `run_worker(self._gather_follow, thread=True, exclusive=True)`. The worker callback applies the update on the app thread with `call_from_thread` and clears the flag. A worker exception sets the path line to the exception text once and clears the flag. It does not touch the transcript.

`_gather_follow` returns `FollowUpdate | None`:

- `git -C root status --porcelain -z` via `subprocess.run`, stdout bytes. On `OSError` or non-zero, return `None` and record the stderr line for the path.
- For each parsed path that is not ignored, `stat` the resolved path. Reject a path that does not stay inside `root.resolve()`.
- Read ledger bytes from `_follow_offset`, parse complete JSON lines, collect `path` from objects whose `type` is `FileTouched`, advance the offset past the last complete line. Stat those paths too.
- Build `found: dict[str, tuple[Snap, bytes]]` only for paths whose snap differs from `_follow_base` or that are new. Read the file bytes only for those candidates, not for the whole tree.
- `poll(self._follow_base, found, hints)`.
- Store the returned baseline back onto `_follow_base` from the worker's result, on the app thread, inside `_apply_follow`'s caller. `_gather_follow` returns `(new_base, update, new_offset)` so the app thread is the only writer of that state. Tests call `_apply_follow` directly and do not go through `_gather_follow`.

`_apply_follow(update)`:

- If `update.text is None`: set `#file-path` to `f"{update.path} — {update.notice}"`, clear `#file-view` with `load_text("")`, and do not add the path to `_follow_order`.
- Else: remember `previous = self._follow_shown.get(update.path, "")`. On the first time this path is shown in the session, `changed = update.changed_line`. On a later save, `changed = first_changed_line(previous, update.text)`.
- Append the path to `_follow_order` the first time it is shown.
- If `_follow_hold` and the path is not the one at `_follow_index`, leave the text area alone. Set the path line to the held path plus `held · N newer`, where N is how many entries sit after the index. Still store `self._follow_shown[update.path] = update.text`.
- Otherwise set `_follow_index` to the new path's index, `_follow_hold = False`, `load_text(update.text)`, store shown text.
- If the path is unchanged and `_follow_user_scrolled`: save `scroll_x` and `scroll_y`, `load_text`, restore both with `scroll_to(x, y, animate=False)`, and set the path line to `{path} — updated`.
- Otherwise `load_text`, then `move_cursor((changed - 1, 0))` and `scroll_cursor_visible()`. Set `_follow_user_scrolled = False` around that programmatic move with a `_follow_moving` flag.
- `#file-view` watch: on `scroll_y` / `scroll_x` changed while `_follow_moving` is false, set `_follow_user_scrolled = True`. A short way that matches Textual 2.1.2: subclass is unnecessary. In `_apply_follow`, before the programmatic scroll set `self._follow_moving = True`, and clear it at the end. Bind `watch` by giving the TextArea an id and handling the event in the app:

```python
def on_text_area_changed(self, event):
    return
```

Do not use `Changed` for scrolling. Override is heavier than needed. Read `scroll_y` inside the TextArea's `watch_scroll_y` by a tiny subclass in `tui.py`:

```python
class FollowView(TextArea):
    def watch_scroll_y(self, old, new):
        self.app._note_file_scroll()
    def watch_scroll_x(self, old, new):
        self.app._note_file_scroll()
```

`_note_file_scroll`: if `self._follow_moving`, return. Else `self._follow_user_scrolled = True`.

Earlier: if the order is empty, return. `_follow_hold = True`, index = max(0, index - 1), load `_follow_shown[order[index]]`, path line is that path. Later: index = min(len - 1, index + 1). When the index becomes the last item, `_follow_hold = False`. Disable Earlier at index 0 and Later at the last index.

Switching path clears `_follow_user_scrolled`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/console/test_see_files.py tests/console/test_file_follow.py tests/console/test_tui.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/whyline/console/tui.py tests/console/test_see_files.py
git commit -m "feat: follow the file an agent is writing"
```

## Self-review

Spec coverage:

- Split left/right, read-only, both scroll directions: Task 2 (`soft_wrap=False`, `read_only=True`) and Task 3 (scroll keep).
- Follow the newest written file, keep earlier files: Task 3 Earlier/Later and `_follow_order`.
- Do not follow reads, do not open files already dirty at arm time, ignore `.whyline` and `.git`, notices for binary, size, and encoding: Task 1.
- Arm only while a run is in progress and Files is on: Task 3 `_set_busy` test.
- Disk writes, not tool-stream parsing: Task 1 `poll` and the out-of-scope line in the spec. No task parses a CLI stream.
- Help line: Task 2.

Placeholder scan: no TBD, no "handle edge cases", no "similar to Task N" without the code the step needs.

Type consistency: `FollowUpdate.path`, `.text`, `.notice`, `.changed_line` are the same in Task 1 and Task 3. `Snap.mtime_ns` and `Snap.size` are the same. `_apply_follow` takes one `FollowUpdate`.

Review focus: the five lines in the header each name a test that exists in Task 1 or Task 3.
