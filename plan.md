- [ ] MTU-1: `dispatch()` becomes public; add the `[ui]` extra

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `textual` is only pulled in via the new `[ui]` extra (MTU1); base `whyline`/`whyline-relay` stay fully dependency-free.
  - No attachments panel -- attachments (sub-project #7) remain deferred indefinitely.
  - Every button dispatches the exact same text command the keyboard console already accepts (`/model`, `/route ...`, `/history`, `/help`) through the same `dispatch()` function -- never a separate, mouse-only implementation (MTU5).
  - `/stop` marks the active worker cancelled; it cannot forcibly interrupt Python code already running inside a thread. State this plainly in the UI text, never imply true interruption (MTU6).
  - This is the project's first use of Textual. **Before writing any TUI code, install it for real (`uv pip install textual` or add the `[ui]` extra locally and `uv sync`) and verify every API this plan assumes (`App`, `run_worker(..., thread=True)`, `call_from_thread`, `RichLog`, `TextArea`, `Header`, `Button`, `Horizontal`, `Pilot`/`App.run_test()`) against whatever version actually installs. If a name or signature differs from what this plan shows, use the real one and note the discrepancy in your `whyline note` -- the same "verify against reality" standard this project applies to every other external dependency (Grok's CLI flags, codex's sandbox modes, prompt_toolkit's own API).
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/repl.py`, `pyproject.toml`
  - Test: `tests/console/test_repl.py`

  **Interfaces:**
  - Produces: `dispatch(session: ConsoleSession, text: str) -> SessionEvent` (renamed from `_dispatch`, otherwise identical). `pyproject.toml` gains `[project.optional-dependencies] ui = ["textual"]`.

  Step 1: Read the current files fresh

  Read `src/whyline/console/repl.py` and the `[project.optional-dependencies]`
  block in `pyproject.toml` in full before making any change -- confirm
  `_dispatch`'s exact current body matches what's described here (it should,
  but this project's own convention is to verify, not assume).

  Step 2: Write the failing test

  `tests/console/test_repl.py` already tests dispatch behavior indirectly
  through `repl.run(...)`. Add a direct test of the renamed public function:

  ```python
  def test_dispatch_is_public_and_routes_by_mode(tmp_path):
      from whyline.console.repl import dispatch
      from whyline.console.session import ConsoleSession
      from whyline.console import adapters

      session = ConsoleSession(root=tmp_path, mode="command")
      called = []
      original = adapters.run_whyline_command
      adapters.run_whyline_command = lambda argv: called.append(argv) or original(argv)
      try:
          dispatch(session, "model status")
      finally:
          adapters.run_whyline_command = original
      assert called == [["model", "status"]]
  ```

  Step 3: Run the test to verify it fails

  Run: `uv run pytest tests/console/test_repl.py -k is_public -v`
  Expected: FAIL (`ImportError: cannot import name 'dispatch'`)

  Step 4: Rename `_dispatch` to `dispatch`

  In `src/whyline/console/repl.py`, rename the function definition:

  ```python
  def dispatch(session: ConsoleSession, text: str) -> SessionEvent:
  ```

  and update its one call site inside `run()`:

  ```python
          try:
              event = dispatch(session, text)
          except KeyboardInterrupt:
  ```

  Leave the function's body completely unchanged -- this is a rename only.

  Step 5: Add the `[ui]` extra

  In `pyproject.toml`, add a new line to `[project.optional-dependencies]`,
  right after the existing `console` entry:

  ```toml
  [project.optional-dependencies]
  relay = ["whyline-relay>=0.2.1,<0.3"]
  console = ["prompt_toolkit>=3.0,<4.0"]
  ui = ["textual>=0.60,<1.0"]
  ```

  Run `uv lock` afterward so the lockfile picks up the new optional group
  (it will not install `textual` into the base environment -- only
  `[project.optional-dependencies]` entries someone explicitly asks for get
  installed).

  Step 6: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_repl.py -v`
  Expected: PASS (every test in the file, including the new one)

  Step 7: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 8: Commit

  ```bash
  git add src/whyline/console/repl.py pyproject.toml uv.lock
  git commit -m "feat: dispatch() becomes public; add the [ui] extra for textual"
  ```

  ---

- [ ] MTU-2: `tui.py` skeleton -- guarded import, layout, and a Pilot smoke test

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `textual` is only pulled in via the new `[ui]` extra (MTU1); base `whyline`/`whyline-relay` stay fully dependency-free.
  - No attachments panel -- attachments (sub-project #7) remain deferred indefinitely.
  - Every button dispatches the exact same text command the keyboard console already accepts (`/model`, `/route ...`, `/history`, `/help`) through the same `dispatch()` function -- never a separate, mouse-only implementation (MTU5).
  - `/stop` marks the active worker cancelled; it cannot forcibly interrupt Python code already running inside a thread. State this plainly in the UI text, never imply true interruption (MTU6).
  - This is the project's first use of Textual. **Before writing any TUI code, install it for real (`uv pip install textual` or add the `[ui]` extra locally and `uv sync`) and verify every API this plan assumes (`App`, `run_worker(..., thread=True)`, `call_from_thread`, `RichLog`, `TextArea`, `Header`, `Button`, `Horizontal`, `Pilot`/`App.run_test()`) against whatever version actually installs. If a name or signature differs from what this plan shows, use the real one and note the discrepancy in your `whyline note` -- the same "verify against reality" standard this project applies to every other external dependency (Grok's CLI flags, codex's sandbox modes, prompt_toolkit's own API).
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Create: `src/whyline/console/tui.py`
  - Test: `tests/console/test_tui.py` (new file)

  **Interfaces:**
  - Consumes: `ConsoleSession`, `SessionEvent` (unchanged, from `session.py`); `dispatch` (Task 1).
  - Produces: `TUI_AVAILABLE: bool`. `WhylineConsoleApp(App)` -- a Textual app taking `root: Path` at construction, composing a header, a transcript log, a prompt editor, and a row of buttons (Send, Model, Route, History, Stop, Help -- no Attach). `launch(root: Path) -> None` -- runs the app, or raises `TuiUnavailable` if `textual` isn't installed.

  Step 1: Install and verify Textual's real API

  Before writing any code: install `textual` in your environment (`uv sync
  --extra ui`, or `uv pip install textual` directly) and confirm these
  imports and calls actually work against the installed version:

  ```python
  from textual.app import App, ComposeResult
  from textual.containers import Horizontal
  from textual.widgets import Header, Footer, Button, TextArea, RichLog
  ```

  If any name differs (Textual's API has moved things between major
  versions in the past), use the real name and record the discrepancy via
  `whyline note` -- do not silently paper over a mismatch.

  Step 2: Write the failing test

  Create `tests/console/test_tui.py`:

  ```python
  import pytest

  from whyline.console import tui


  def test_tui_available_flag_exists():
      assert isinstance(tui.TUI_AVAILABLE, bool)


  def test_launch_raises_a_clear_error_without_textual(monkeypatch, tmp_path):
      monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
      with pytest.raises(tui.TuiUnavailable, match=r"whyline\[ui\]"):
          tui.launch(tmp_path)


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_app_composes_header_transcript_prompt_and_controls(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          assert app.query_one("#transcript") is not None
          assert app.query_one("#prompt") is not None
          for button_id in ("send", "model", "route", "history", "stop", "help"):
              assert app.query_one(f"#{button_id}") is not None
  ```

  `pytest-asyncio` may need adding as a dev dependency for the async test
  above (`uv add --group dev pytest-asyncio`, or confirm it is already
  present) -- check `pyproject.toml`'s `[dependency-groups]` first.

  Step 3: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_tui.py -v`
  Expected: FAIL (`ModuleNotFoundError: No module named 'whyline.console.tui'`)

  Step 4: Implement the skeleton

  Create `src/whyline/console/tui.py`:

  ```python
  """whyline console's mouse-enabled TUI, built on Textual.

  Import-guarded exactly like editor.py guards prompt_toolkit, so the rest
  of the console package stays importable and testable without the [ui]
  extra installed. Reuses ConsoleSession/SessionEvent/adapters.py and
  repl.py's dispatch() completely unchanged -- this module is a rendering
  layer, not a second implementation of the console's logic.
  """

  from __future__ import annotations

  from pathlib import Path

  try:
      from textual.app import App, ComposeResult
      from textual.containers import Horizontal
      from textual.widgets import Button, Footer, Header, RichLog, TextArea

      TUI_AVAILABLE = True
  except ImportError:
      App = object  # placeholder base so WhylineConsoleApp can still be defined
      ComposeResult = None
      Horizontal = None
      Button = Footer = Header = RichLog = TextArea = None
      TUI_AVAILABLE = False

  from whyline.console.session import ConsoleSession, SessionEvent

  _PREFIX = {"error": "⚠ ", "pause": "⏸ "}


  class TuiUnavailable(RuntimeError):
      """textual is not installed."""


  class WhylineConsoleApp(App):
      """The mouse-enabled console. Every widget dispatches through the same
      ConsoleSession/dispatch() path the keyboard REPL already uses."""

      def __init__(self, *, root: Path) -> None:
          super().__init__()
          self.session = ConsoleSession(root=root)

      def compose(self) -> ComposeResult:
          yield Header()
          yield RichLog(id="transcript")
          yield TextArea(id="prompt")
          yield Horizontal(
              Button("Send", id="send"),
              Button("Model", id="model"),
              Button("Route", id="route"),
              Button("History", id="history"),
              Button("Stop", id="stop"),
              Button("Help", id="help"),
          )
          yield Footer()

      def render_event(self, event: SessionEvent) -> None:
          self.session.record(event)
          transcript = self.query_one("#transcript", RichLog)
          transcript.write(f"{_PREFIX.get(event.kind, '')}{event.text}")


  def launch(root: Path) -> None:
      if not TUI_AVAILABLE:
          raise TuiUnavailable(
              "The mouse TUI needs textual. Run: pip install 'whyline[ui]'"
          )
      WhylineConsoleApp(root=root).run()
  ```

  Note: `App = object` in the `except ImportError` branch exists only so
  `class WhylineConsoleApp(App):` doesn't itself raise `NameError` at import
  time when `textual` is absent -- the class is still defined (satisfying
  `TUI_AVAILABLE` checks and imports elsewhere), it just can't be
  instantiated meaningfully without `textual` really installed, which
  `launch()`'s own check catches first anyway.

  Step 5: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_tui.py -v`
  Expected: PASS (the `TuiUnavailable` test always; the Pilot smoke test only
  if `textual` is actually installed in this environment, otherwise skipped)

  Step 6: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 7: Commit

  ```bash
  git add src/whyline/console/tui.py tests/console/test_tui.py pyproject.toml uv.lock
  git commit -m "feat: tui.py skeleton -- guarded import, header/transcript/prompt/controls layout"
  ```

  ---

- [ ] MTU-3: Send dispatches through a background worker

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `textual` is only pulled in via the new `[ui]` extra (MTU1); base `whyline`/`whyline-relay` stay fully dependency-free.
  - No attachments panel -- attachments (sub-project #7) remain deferred indefinitely.
  - Every button dispatches the exact same text command the keyboard console already accepts (`/model`, `/route ...`, `/history`, `/help`) through the same `dispatch()` function -- never a separate, mouse-only implementation (MTU5).
  - `/stop` marks the active worker cancelled; it cannot forcibly interrupt Python code already running inside a thread. State this plainly in the UI text, never imply true interruption (MTU6).
  - This is the project's first use of Textual. **Before writing any TUI code, install it for real (`uv pip install textual` or add the `[ui]` extra locally and `uv sync`) and verify every API this plan assumes (`App`, `run_worker(..., thread=True)`, `call_from_thread`, `RichLog`, `TextArea`, `Header`, `Button`, `Horizontal`, `Pilot`/`App.run_test()`) against whatever version actually installs. If a name or signature differs from what this plan shows, use the real one and note the discrepancy in your `whyline note` -- the same "verify against reality" standard this project applies to every other external dependency (Grok's CLI flags, codex's sandbox modes, prompt_toolkit's own API).
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/tui.py`
  - Test: `tests/console/test_tui.py`

  **Interfaces:**
  - Consumes: `dispatch` (Task 1), `render_event` (Task 2).
  - Produces: clicking Send (or the button with id `"send"`) reads the prompt's text, runs `dispatch(self.session, text)` in a background thread via `run_worker(..., thread=True)`, and renders the resulting `SessionEvent` back on the main thread once it completes.

  Step 1: Write the failing test

  Add to `tests/console/test_tui.py`:

  ```python
  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_send_dispatches_in_a_worker_and_renders_the_result(tmp_path, monkeypatch):
      from whyline.console.session import SessionEvent

      monkeypatch.setattr(
          tui, "dispatch",
          lambda session, text: SessionEvent(kind="output", text=f"ran {text!r}"),
      )
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          prompt = app.query_one("#prompt", tui.TextArea)
          prompt.text = "hello"
          await pilot.click("#send")
          await pilot.pause()  # let the worker's result land
          transcript = app.query_one("#transcript", tui.RichLog)
          assert any("ran 'hello'" in str(line) for line in transcript.lines)
  ```

  Check `RichLog`'s actual API for reading back written content in your
  installed Textual version (`transcript.lines`, or whatever the real
  attribute/method is) before trusting the assertion above verbatim --
  adjust it to however `RichLog` actually exposes its rendered content for
  testing.

  Step 2: Run the test to verify it fails

  Run: `uv run pytest tests/console/test_tui.py -k send_dispatches -v`
  Expected: FAIL (Send does nothing yet)

  Step 3: Implement

  In `src/whyline/console/tui.py`, add the import at the top (alongside the
  existing guarded Textual imports):

  ```python
  from whyline.console.repl import dispatch
  ```

  Also add one line to `__init__` (needed by Task 4's Stop, added now so this
  task's own dispatch path already uses it -- avoids a second pass over this
  same method later):

  ```python
      def __init__(self, *, root: Path) -> None:
          super().__init__()
          self.session = ConsoleSession(root=root)
          self._dispatch_token: object | None = None
  ```

  Add a button-press handler to `WhylineConsoleApp`:

  ```python
      def on_button_pressed(self, event: "Button.Pressed") -> None:
          if event.button.id == "send":
              self._send()

      def _send(self) -> None:
          prompt = self.query_one("#prompt", TextArea)
          text = prompt.text.strip()
          if not text:
              return
          prompt.text = ""
          self._dispatch_text(text)

      def _dispatch_text(self, text: str) -> None:
          """Launches one dispatch in a background thread. `token` is a
          unique, unguessable object identifying *this specific* dispatch --
          _stop() (Task 4) replaces self._dispatch_token with a new one,
          which is how a cancelled dispatch's late-arriving result is
          recognized and discarded (via `is`, not equality) once it finally
          returns, regardless of whatever Textual's own worker.cancel() does
          or doesn't guarantee about a thread already running Python code."""
          token = object()
          self._dispatch_token = token
          self.run_worker(lambda: self._dispatch_in_thread(text, token), thread=True)

      def _dispatch_in_thread(self, text: str, token: object) -> None:
          try:
              result = dispatch(self.session, text)
          except Exception as error:  # a safety net beyond adapters.py's own handling
              result = SessionEvent(kind="error", text=str(error))
          if token is self._dispatch_token:
              self.call_from_thread(self.render_event, result)
  ```

  Verify `on_button_pressed`'s exact signature and `Button.Pressed`'s import
  path against your installed Textual version in Step 1 of this task if it
  differs from what's shown here -- Textual has used both a
  `on_button_pressed` convention and an `@on(Button.Pressed, "#id")`
  decorator convention across versions; use whichever your installed version
  actually supports.

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_tui.py -v`
  Expected: PASS

  Step 5: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 6: Commit

  ```bash
  git add src/whyline/console/tui.py tests/console/test_tui.py
  git commit -m "feat: Send dispatches through a background worker"
  ```

  ---

- [ ] MTU-4: Model/Route/History/Help buttons and Stop

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `textual` is only pulled in via the new `[ui]` extra (MTU1); base `whyline`/`whyline-relay` stay fully dependency-free.
  - No attachments panel -- attachments (sub-project #7) remain deferred indefinitely.
  - Every button dispatches the exact same text command the keyboard console already accepts (`/model`, `/route ...`, `/history`, `/help`) through the same `dispatch()` function -- never a separate, mouse-only implementation (MTU5).
  - `/stop` marks the active worker cancelled; it cannot forcibly interrupt Python code already running inside a thread. State this plainly in the UI text, never imply true interruption (MTU6).
  - This is the project's first use of Textual. **Before writing any TUI code, install it for real (`uv pip install textual` or add the `[ui]` extra locally and `uv sync`) and verify every API this plan assumes (`App`, `run_worker(..., thread=True)`, `call_from_thread`, `RichLog`, `TextArea`, `Header`, `Button`, `Horizontal`, `Pilot`/`App.run_test()`) against whatever version actually installs. If a name or signature differs from what this plan shows, use the real one and note the discrepancy in your `whyline note` -- the same "verify against reality" standard this project applies to every other external dependency (Grok's CLI flags, codex's sandbox modes, prompt_toolkit's own API).
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/tui.py`
  - Test: `tests/console/test_tui.py`

  **Interfaces:**
  - Produces: clicking Model/Route/History/Help dispatches the identical
    `/model`, `/route`, `/history`, `/help` text through `dispatch()` (MTU5).
    Stop cancels the currently active worker, if any (MTU6).

  Step 1: Write the failing tests

  Add to `tests/console/test_tui.py`:

  ```python
  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_model_button_dispatches_the_same_text_as_typing_it(tmp_path, monkeypatch):
      from whyline.console.session import SessionEvent

      seen = []
      monkeypatch.setattr(
          tui, "dispatch",
          lambda session, text: seen.append(text) or SessionEvent(kind="output", text="ok"),
      )
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await pilot.click("#model")
          await pilot.pause()
      assert seen == ["/model"]


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_route_history_help_buttons_dispatch_their_slash_commands(tmp_path, monkeypatch):
      from whyline.console.session import SessionEvent

      seen = []
      monkeypatch.setattr(
          tui, "dispatch",
          lambda session, text: seen.append(text) or SessionEvent(kind="output", text="ok"),
      )
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await pilot.click("#route")
          await pilot.click("#history")
          await pilot.click("#help")
          await pilot.pause()
      assert seen == ["/route", "/history", "/help"]


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_stop_cancels_the_active_worker(tmp_path, monkeypatch):
      import threading
      from whyline.console.session import SessionEvent

      release = threading.Event()

      def slow_dispatch(session, text):
          release.wait(timeout=2)  # held open until the test itself lets go
          return SessionEvent(kind="output", text="too late")

      monkeypatch.setattr(tui, "dispatch", slow_dispatch)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          prompt = app.query_one("#prompt", tui.TextArea)
          prompt.text = "long running"
          await pilot.click("#send")
          await pilot.pause()  # let the worker actually start and block on release
          await pilot.click("#stop")  # invalidates the token while still blocked
          release.set()  # now let the blocked dispatch finish, "too late"
          await pilot.pause()
          await pilot.pause()  # give call_from_thread a beat to have run, if it were going to
          transcript = app.query_one("#transcript", tui.RichLog)
          assert not any("too late" in str(line) for line in transcript.lines)
  ```

  This is deterministic rather than timing-dependent: the dispatch is held
  open with a `threading.Event` until the test explicitly releases it *after*
  Stop has already invalidated the token, so there's no race about whether
  Stop happened before or after the dispatch would have finished on its own.

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_tui.py -k "model_button or route_history_help or stop_cancels" -v`
  Expected: FAIL (none of these buttons do anything yet, Stop doesn't exist)

  Step 3: Implement

  `_dispatch_text`, `_dispatch_in_thread`, and `_send` already exist from
  Task 3, using the `_dispatch_token` mechanism. Replace `on_button_pressed`
  to route the four new buttons through the exact same `_dispatch_text`, and
  add `_stop`:

  ```python
      def on_button_pressed(self, event: "Button.Pressed") -> None:
          button_id = event.button.id
          if button_id == "send":
              self._send()
          elif button_id == "stop":
              self._stop()
          elif button_id in ("model", "route", "history", "help"):
              self._dispatch_text(f"/{button_id}")

      def _stop(self) -> None:
          """Invalidates the current dispatch token (MTU6): whatever
          _dispatch_in_thread is running right now will still run to
          completion -- Python cannot forcibly interrupt it -- but its result
          will no longer match self._dispatch_token when it finally returns,
          so render_event is never called for it. This guarantee holds
          regardless of what worker.cancel() itself does or doesn't stop.
          worker.cancel() is still called below as a best-effort signal to
          Textual's own scheduler; verify its exact call shape (iterating
          self.workers vs. a single self.workers.cancel_all()) against your
          installed version."""
          self._dispatch_token = object()
          for worker in self.workers:
              worker.cancel()
  ```

  No change is needed to `_send`/`_dispatch_text`/`_dispatch_in_thread`
  themselves -- they were already written with this token in Task 3.

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_tui.py -v`
  Expected: PASS

  Step 5: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 6: Commit

  ```bash
  git add src/whyline/console/tui.py tests/console/test_tui.py
  git commit -m "feat: Model/Route/History/Help buttons and Stop"
  ```

  ---

- [ ] MTU-5: `whyline console --ui` wiring and end-to-end test

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `textual` is only pulled in via the new `[ui]` extra (MTU1); base `whyline`/`whyline-relay` stay fully dependency-free.
  - No attachments panel -- attachments (sub-project #7) remain deferred indefinitely.
  - Every button dispatches the exact same text command the keyboard console already accepts (`/model`, `/route ...`, `/history`, `/help`) through the same `dispatch()` function -- never a separate, mouse-only implementation (MTU5).
  - `/stop` marks the active worker cancelled; it cannot forcibly interrupt Python code already running inside a thread. State this plainly in the UI text, never imply true interruption (MTU6).
  - This is the project's first use of Textual. **Before writing any TUI code, install it for real (`uv pip install textual` or add the `[ui]` extra locally and `uv sync`) and verify every API this plan assumes (`App`, `run_worker(..., thread=True)`, `call_from_thread`, `RichLog`, `TextArea`, `Header`, `Button`, `Horizontal`, `Pilot`/`App.run_test()`) against whatever version actually installs. If a name or signature differs from what this plan shows, use the real one and note the discrepancy in your `whyline note` -- the same "verify against reality" standard this project applies to every other external dependency (Grok's CLI flags, codex's sandbox modes, prompt_toolkit's own API).
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/cli.py`
  - Test: `tests/test_cli_console.py`

  **Interfaces:**
  - Consumes: `tui.launch`, `tui.TuiUnavailable` (Tasks 2-4).
  - Produces: `whyline console --ui` launches the TUI; bare `whyline console` keeps launching today's keyboard REPL, unchanged.

  Step 1: Write the failing tests

  Read `_add_console` and `cmd_console` in `src/whyline/cli.py` fresh first
  (shown below as they existed when this plan was written -- confirm before
  trusting this verbatim):

  ```python
  def _add_console(subparsers: "argparse._SubParsersAction") -> None:
      subparsers.add_parser(
          "console", help="An editable multiline console for whyline and whyline-relay"
      )
  ```

  ```python
  def cmd_console(args: argparse.Namespace) -> int:
      from whyline.console import repl

      root = _require_repo()
      repl.run(root)
      return EXIT_OK
  ```

  Add to `tests/test_cli_console.py`:

  ```python
  def test_console_ui_flag_launches_the_tui(repo, monkeypatch):
      from whyline import cli
      from whyline.console import tui

      calls = []
      monkeypatch.setattr(tui, "launch", lambda root: calls.append(root))
      previous = os.getcwd()
      os.chdir(repo.path)
      try:
          code = cli.main(["console", "--ui"])
      finally:
          os.chdir(previous)
      assert code == cli.EXIT_OK
      assert calls == [repo.path.resolve()] or calls == [repo.path]


  def test_console_ui_flag_reports_a_clear_error_when_textual_is_missing(repo, capsys):
      from whyline import cli
      from whyline.console import tui

      if tui.TUI_AVAILABLE:
          pytest.skip("textual is installed in this environment -- nothing to test here")
      previous = os.getcwd()
      os.chdir(repo.path)
      try:
          code = cli.main(["console", "--ui"])
      finally:
          os.chdir(previous)
      assert code == cli.EXIT_ERROR
      assert "whyline[ui]" in capsys.readouterr().out
  ```

  Check `_require_repo()`'s exact return value (a resolved `Path` or not) to
  fix the first test's slightly defensive `or` assertion into a single exact
  equality once you've confirmed which it is.

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/test_cli_console.py -v`
  Expected: FAIL (`--ui` isn't a recognized argument yet)

  Step 3: Implement

  Replace `_add_console`:

  ```python
  def _add_console(subparsers: "argparse._SubParsersAction") -> None:
      parser = subparsers.add_parser(
          "console", help="An editable multiline console for whyline and whyline-relay"
      )
      parser.add_argument(
          "--ui", action="store_true",
          help="Launch the full-screen, mouse-enabled console instead of the keyboard-only one",
      )
  ```

  Replace `cmd_console`:

  ```python
  def cmd_console(args: argparse.Namespace) -> int:
      root = _require_repo()
      if getattr(args, "ui", False):
          from whyline.console import tui

          try:
              tui.launch(root)
          except tui.TuiUnavailable as error:
              print(str(error))
              return EXIT_ERROR
          return EXIT_OK

      from whyline.console import repl

      repl.run(root)
      return EXIT_OK
  ```

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/test_cli_console.py -v`
  Expected: PASS

  Step 5: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 6: Commit

  ```bash
  git add src/whyline/cli.py tests/test_cli_console.py
  git commit -m "feat: whyline console --ui launches the mouse-enabled TUI"
  ```

  ---
