- [x] FC-1: `run_entry_menu` launches the richest available console (FC1)

  ## Global Constraints

  - No new runtime dependency.
  - The old plain-text entry menu's own code and behavior are completely untouched -- it remains the permanent zero-extras fallback, never removed.
  - Every existing test for the keyboard console (`test_repl.py`) and the entry menu (`test_cli_chat_delegation.py`) must keep passing unmodified -- the extraction in Task 2 must not change any existing behavior, only its internal shape.
  - `/route relay`'s setup handoff never asks for confirmation first -- it matches today's entry menu exactly, which execs into setup immediately once "relay" is chosen.
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/cli.py`
  - Test: `tests/test_cli_chat_delegation.py`

  **Interfaces:**
  - Produces: `run_entry_menu(...)` checks, before its existing "Chat or relay?" prompt, whether a repo root exists and `tui.TUI_AVAILABLE`/`editor.AVAILABLE`, launching the appropriate console instead when so. No change to its existing parameters or fallback behavior.

  Step 1: Read `run_entry_menu` fresh

  Read the whole function in `src/whyline/cli.py` before changing it --
  confirm its current body matches:

  ```python
  def run_entry_menu(
      which=None, exec_fn=None, input_fn=None, print_fn=None, subprocess_fn=None,
  ) -> bool:
      """..."""
      which = which if which is not None else _which
      exec_fn = exec_fn if exec_fn is not None else _exec
      input_fn = input_fn if input_fn is not None else input
      print_fn = print_fn if print_fn is not None else print
      subprocess_fn = subprocess_fn if subprocess_fn is not None else subprocess.run

      if which("whyline-relay") is None:
          return False

      from whyline import account

      freshly_detected = account.ensure_detected()
      if freshly_detected is not None:
          print_fn("First run: checking which agents you have access to...")
          for agent in ("codex", "claude", "antigravity", "grok"):
              info = freshly_detected.get(agent, {})
              state = "available" if info.get("available") else "not available"
              print_fn(f"  {agent}: {state}")

      choice = input_fn("Chat or relay? [chat]: ").strip().lower()
      if choice == "relay":
          exec_fn("whyline-relay", ["whyline-relay", "setup"])
          return True  # unreachable when exec_fn is the real os.execvp

      model_choice = input_fn(
          "Start chatting, or set a model first? [chat]: "
      ).strip().lower()
      if model_choice == "model":
          result = subprocess_fn(["whyline", "model"])
          if getattr(result, "returncode", 0) != 0:
              print_fn(
                  "Model setup did not complete -- not starting chat. Fix the "
                  "issue above, then run `whyline` again."
              )
              return True

      exec_fn("whyline-relay", ["whyline-relay", "chat"])
      return True  # unreachable when exec_fn is the real os.execvp
  ```

  Step 2: Write the failing tests

  Add to `tests/test_cli_chat_delegation.py`:

  ```python
  def test_entry_menu_launches_the_mouse_tui_when_available(monkeypatch, tmp_path):
      from whyline import cli
      from whyline.console import tui

      monkeypatch.setattr(cli.paths, "find_repo_root", lambda: tmp_path)
      monkeypatch.setattr(tui, "TUI_AVAILABLE", True)
      calls = []
      monkeypatch.setattr(tui, "launch", lambda root: calls.append(root))

      def _unexpected_prompt(prompt=""):
          raise AssertionError("must not reach the plain text menu")

      result = cli.run_entry_menu(
          which=lambda name: "/usr/bin/whyline-relay",
          input_fn=_unexpected_prompt,
      )
      assert result is True
      assert calls == [tmp_path]


  def test_entry_menu_launches_the_keyboard_console_when_tui_unavailable(
      monkeypatch, tmp_path
  ):
      from whyline import cli
      from whyline.console import editor, repl, tui

      monkeypatch.setattr(cli.paths, "find_repo_root", lambda: tmp_path)
      monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
      monkeypatch.setattr(editor, "AVAILABLE", True)
      calls = []
      monkeypatch.setattr(repl, "run", lambda root, **kwargs: calls.append(root))

      def _unexpected_prompt(prompt=""):
          raise AssertionError("must not reach the plain text menu")

      result = cli.run_entry_menu(
          which=lambda name: "/usr/bin/whyline-relay",
          input_fn=_unexpected_prompt,
      )
      assert result is True
      assert calls == [tmp_path]


  def test_entry_menu_falls_through_to_plain_menu_when_neither_extra_is_available(
      monkeypatch, tmp_path
  ):
      from whyline import cli
      from whyline.console import editor, tui

      monkeypatch.setattr(cli.paths, "find_repo_root", lambda: tmp_path)
      monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
      monkeypatch.setattr(editor, "AVAILABLE", False)
      answers = iter(["", ""])
      calls = []
      result = cli.run_entry_menu(
          which=lambda name: "/usr/bin/whyline-relay",
          exec_fn=lambda binary, argv: calls.append((binary, argv)),
          input_fn=lambda prompt="": next(answers),
      )
      assert result is True
      assert calls == [("whyline-relay", ["whyline-relay", "chat"])]


  def test_entry_menu_falls_through_when_no_repo_root_found(monkeypatch):
      from whyline import cli
      from whyline.console import tui

      monkeypatch.setattr(cli.paths, "find_repo_root", lambda: None)
      monkeypatch.setattr(tui, "TUI_AVAILABLE", True)
      calls = []
      monkeypatch.setattr(tui, "launch", lambda root: calls.append(root))
      answers = iter(["", ""])
      result = cli.run_entry_menu(
          which=lambda name: "/usr/bin/whyline-relay",
          exec_fn=lambda binary, argv: None,
          input_fn=lambda prompt="": next(answers),
      )
      assert result is True
      assert calls == []  # the TUI is never launched without a repo root
  ```

  Check `cli.py`'s current imports -- if `paths` isn't already imported at
  module level (it may only be imported lazily inside individual command
  functions today, matching this file's own "keep imports light" cold-start
  philosophy), the tests above reference `cli.paths.find_repo_root`, so
  Step 3's implementation must make `paths` reachable as `cli.paths` (a
  module-level `from whyline import paths` addition, or importing it lazily
  inside `run_entry_menu` itself and monkeypatching `whyline.paths` directly
  instead -- pick whichever matches this file's existing import style most
  closely, and adjust the test's monkeypatch target to match).

  Step 3: Run the tests to verify they fail

  Run: `uv run pytest tests/test_cli_chat_delegation.py -v`
  Expected: FAIL (the new tests fail; all pre-existing tests in the file
  still pass, since nothing has changed yet)

  Step 4: Implement

  In `src/whyline/cli.py`, insert the new priority check into
  `run_entry_menu`, right after the existing first-run detection block and
  before the `choice = input_fn("Chat or relay? [chat]: ")` line:

  ```python
      from whyline import paths
      from whyline.console import editor, repl, tui

      root = paths.find_repo_root()
      if root is not None:
          if tui.TUI_AVAILABLE:
              tui.launch(root)
              return True
          if editor.AVAILABLE:
              repl.run(root)
              return True

      choice = input_fn("Chat or relay? [chat]: ").strip().lower()
  ```

  If `paths` needs to be reachable as `cli.paths` for the tests above (per
  Step 2's note), add `from whyline import paths` to the top-level imports
  in `cli.py` instead of importing it lazily inside the function -- check
  whether `paths` is already imported at the top of the file first.

  Step 5: Run the tests to verify they pass

  Run: `uv run pytest tests/test_cli_chat_delegation.py -v`
  Expected: PASS (every test in the file, old and new)

  Step 6: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 7: Commit

  ```bash
  git add src/whyline/cli.py tests/test_cli_chat_delegation.py
  git commit -m "feat: bare whyline launches the richest available console"
  ```

  ---

- [x] FC-2: Shared slash-command handling, fixing the TUI button bug (FC4, keyboard side of FC2)

  ## Global Constraints

  - No new runtime dependency.
  - The old plain-text entry menu's own code and behavior are completely untouched -- it remains the permanent zero-extras fallback, never removed.
  - Every existing test for the keyboard console (`test_repl.py`) and the entry menu (`test_cli_chat_delegation.py`) must keep passing unmodified -- the extraction in Task 2 must not change any existing behavior, only its internal shape.
  - `/route relay`'s setup handoff never asks for confirmation first -- it matches today's entry menu exactly, which execs into setup immediately once "relay" is chosen.
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/repl.py`, `src/whyline/console/adapters.py`
  - Test: `tests/console/test_repl.py`, `tests/console/test_adapters_whyline.py`

  **Interfaces:**
  - Produces: `adapters.relay_is_configured(root: Path) -> bool`. `repl.handle_slash_command(session: ConsoleSession, text: str) -> SessionEvent | None` -- returns the event to render for `/help`, `/status`, `/handoff`, `/history`, `/route`, `/model`; returns `None` if `text` isn't one of these (the caller falls through to `dispatch()`). A new `SessionEvent` kind, `"needs_setup"`, is used for `/route relay` when `not adapters.relay_is_configured(session.root)`.

  Step 1: Read `repl.py`'s current `run()` loop fresh

  Read the whole file -- confirm the loop's current cascade of
  `if text == ...`/`if text.startswith(...)` branches (for `/exit`,
  `/help`, `/status`, `/handoff`, `/history`, `/route`, `/model`, `/stop`,
  unrecognized `/...`, and the final fallback to `dispatch()`) matches what
  this task assumes below, and confirm `_handle_model`'s exact current body
  (it directly calls `print_fn(...)` in each of its four branches today).

  Step 2: Write the failing tests

  Add to `tests/console/test_adapters_whyline.py`:

  ```python
  def test_relay_is_configured_true_when_config_toml_exists(tmp_path):
      from whyline.console import adapters

      config_dir = tmp_path / ".whyline" / "relay"
      config_dir.mkdir(parents=True)
      (config_dir / "config.toml").write_text("", encoding="utf-8")
      assert adapters.relay_is_configured(tmp_path) is True


  def test_relay_is_configured_false_when_absent(tmp_path):
      from whyline.console import adapters

      assert adapters.relay_is_configured(tmp_path) is False
  ```

  Add to `tests/console/test_repl.py`:

  ```python
  def test_handle_slash_command_help(tmp_path):
      from whyline.console.repl import handle_slash_command
      from whyline.console.session import ConsoleSession

      session = ConsoleSession(root=tmp_path)
      event = handle_slash_command(session, "/help")
      assert event is not None
      assert "Commands:" in event.text


  def test_handle_slash_command_returns_none_for_ordinary_text(tmp_path):
      from whyline.console.repl import handle_slash_command
      from whyline.console.session import ConsoleSession

      session = ConsoleSession(root=tmp_path)
      assert handle_slash_command(session, "hello there") is None


  def test_handle_slash_command_route_relay_needs_setup(tmp_path):
      from whyline.console.repl import handle_slash_command
      from whyline.console.session import ConsoleSession

      session = ConsoleSession(root=tmp_path, mode="command")
      event = handle_slash_command(session, "/route relay")
      assert event is not None
      assert event.kind == "needs_setup"
      assert session.mode == "command"  # unchanged -- the handoff hasn't happened yet


  def test_handle_slash_command_route_relay_switches_when_configured(tmp_path):
      from whyline.console.repl import handle_slash_command
      from whyline.console.session import ConsoleSession

      config_dir = tmp_path / ".whyline" / "relay"
      config_dir.mkdir(parents=True)
      (config_dir / "config.toml").write_text("", encoding="utf-8")
      session = ConsoleSession(root=tmp_path, mode="command")
      event = handle_slash_command(session, "/route relay")
      assert event is not None
      assert event.kind != "needs_setup"
      assert session.mode == "relay"


  def test_handle_slash_command_route_invalid_mode(tmp_path):
      from whyline.console.repl import handle_slash_command
      from whyline.console.session import ConsoleSession

      session = ConsoleSession(root=tmp_path)
      event = handle_slash_command(session, "/route nonsense")
      assert event is not None
      assert "Usage: /route" in event.text


  def test_route_relay_with_no_config_execs_into_setup(tmp_path, monkeypatch):
      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(["/route relay", "/exit"]),
      )
      calls = []
      lines = []
      repl.run(
          tmp_path, print_fn=lines.append,
          exec_fn=lambda binary, argv: calls.append((binary, argv)),
      )
      assert calls == [("whyline-relay", ["whyline-relay", "setup"])]
      # The user sees why they're being handed off, before it happens --
      # unlike today's plain entry menu (which execs silently), this is a
      # deliberate small improvement, not a parity requirement.
      assert any("No relay setup found" in line for line in lines)
  ```

  `repl.run` doesn't accept `exec_fn` yet -- Step 4 adds it. Also re-run the
  *entire existing* `tests/console/test_repl.py` file as part of Step 3
  below (not just the new tests), since this task's whole point is that no
  existing test's outcome changes.

  Step 3: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_repl.py tests/console/test_adapters_whyline.py -v`
  Expected: FAIL on every new test; every pre-existing test in `test_repl.py`
  still passes (nothing has changed yet).

  Step 4: Implement

  Add to `src/whyline/console/adapters.py`:

  ```python
  def relay_is_configured(root: Path) -> bool:
      """No import of whyline_relay needed just to check this -- the path is
      stable and simple enough to check directly."""
      return (root / ".whyline" / "relay" / "config.toml").exists()
  ```

  In `src/whyline/console/repl.py`, add `handle_slash_command` (place it
  above `run()`):

  ```python
  def handle_slash_command(session: ConsoleSession, text: str) -> SessionEvent | None:
      """Handles /help, /status, /handoff, /history, /route, /model
      uniformly for both console flavors. Returns the event to render, or
      None if `text` isn't one of these at all -- the caller should fall
      through to ordinary dispatch() in that case. /exit and /stop stay
      outside this function on purpose: each means something different per
      console (see the final-cutover design's FC4)."""
      if text == "/help":
          return SessionEvent(kind="output", text="Commands: " + ", ".join(SLASH_COMMANDS))
      if text == "/status":
          return adapters.run_status(session.root)
      if text == "/handoff":
          return adapters.run_last_handoff(session.root)
      if text == "/history":
          if not session.transcript:
              return SessionEvent(kind="output", text="(nothing yet)")
          lines = [f"{_PREFIX.get(e.kind, '')}{e.text}" for e in session.transcript]
          return SessionEvent(kind="output", text="\n".join(lines))
      if text.startswith("/route"):
          parts = text.split(maxsplit=1)
          chosen = parts[1].strip() if len(parts) == 2 else ""
          if chosen not in ("chat", "relay", "command"):
              return SessionEvent(kind="error", text="Usage: /route <chat|relay|command>")
          if chosen == "relay" and not adapters.relay_is_configured(session.root):
              return SessionEvent(
                  kind="needs_setup",
                  text="No relay setup found here. Running whyline-relay setup...",
              )
          session.mode = chosen
          return SessionEvent(kind="output", text=f"Mode is now {session.mode}.")
      if text.startswith("/model"):
          return _model_event(session, text)
      return None


  def _model_event(session: ConsoleSession, text: str) -> SessionEvent:
      from whyline import account, model

      available = account.available_agents(session.root)
      if not available:
          return SessionEvent(
              kind="error",
              text="No agents detected as available. Run: whyline account detect",
          )
      parts = text.split(maxsplit=2)
      if len(parts) == 1:
          return SessionEvent(kind="output", text="Available: " + ", ".join(sorted(available)))
      agent = parts[1]
      if agent not in available:
          return SessionEvent(
              kind="error",
              text=f"{agent} is not available here. Available: {', '.join(sorted(available))}",
          )
      if len(parts) == 3:
          model.set_one(session.root, agent, parts[2])
          session.agent = agent
          return SessionEvent(kind="output", text=f"{agent} model set; now the active chat agent.")
      session.agent = agent
      return SessionEvent(kind="output", text=f"{agent} is now the active chat agent.")
  ```

  Now replace `run()`'s loop body. Find the whole cascade from
  `if text == "/exit":` through the final `_print_event(session.record(event), print_fn)`
  call, and replace it with:

  ```python
          if text == "/exit":
              break
          if text == "/stop":
              print_fn("Nothing in flight to stop.")
              continue

          slash_event = handle_slash_command(session, text)
          if slash_event is not None:
              if slash_event.kind == "needs_setup":
                  print_fn(slash_event.text)
                  exec_fn("whyline-relay", ["whyline-relay", "setup"])
                  return
              _print_event(session.record(slash_event), print_fn)
              continue
          if text.startswith("/"):
              print_fn(f"Unknown command: {text}. Try {', '.join(SLASH_COMMANDS)}.")
              continue

          try:
              event = dispatch(session, text)
          except KeyboardInterrupt:
              print_fn("Cancelled.")
              continue
          _print_event(session.record(event), print_fn)
  ```

  Delete the now-unused `_handle_model` function entirely (replaced by
  `_model_event` above).

  Finally, give `run()` an injectable `exec_fn`, resolved the same way this
  project always resolves optional collaborators (inside the function body,
  never as a default argument):

  ```python
  def run(root: Path, *, print_fn=print, prompt_session=None, exec_fn=None) -> None:
      if exec_fn is None:
          exec_fn = _exec
      ...
  ```

  Add a small `_exec` helper near the top of `repl.py`, matching `cli.py`'s
  own:

  ```python
  def _exec(binary: str, argv: list[str]) -> None:
      os.execvp(binary, argv)
  ```

  (add `import os` to `repl.py`'s existing imports if not already present).

  Step 5: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_repl.py tests/console/test_adapters_whyline.py -v`
  Expected: PASS -- every pre-existing test in `test_repl.py` unchanged in
  outcome, plus every new test from Step 2.

  Step 6: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 7: Commit

  ```bash
  git add src/whyline/console/repl.py src/whyline/console/adapters.py tests/console/test_repl.py tests/console/test_adapters_whyline.py
  git commit -m "feat: extract shared slash-command handling; /route relay hands off to setup when unconfigured"
  ```

  ---

- [x] FC-3: Wire the TUI to the shared handler, fixing its buttons (FC2 TUI side, FC4 completion)

  ## Global Constraints

  - No new runtime dependency.
  - The old plain-text entry menu's own code and behavior are completely untouched -- it remains the permanent zero-extras fallback, never removed.
  - Every existing test for the keyboard console (`test_repl.py`) and the entry menu (`test_cli_chat_delegation.py`) must keep passing unmodified -- the extraction in Task 2 must not change any existing behavior, only its internal shape.
  - `/route relay`'s setup handoff never asks for confirmation first -- it matches today's entry menu exactly, which execs into setup immediately once "relay" is chosen.
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/tui.py`
  - Test: `tests/console/test_tui.py`

  **Interfaces:**
  - Produces: `WhylineConsoleApp`'s Model/Route/History/Help buttons call `handle_slash_command` directly and render its result synchronously (no worker). `_send()` checks `handle_slash_command` first, before deciding whether to spawn a worker for `dispatch()`. `launch(root, *, exec_fn=None)` performs a deferred `exec` after `app.run()` returns, if the app requested one.

  Step 1: Read `tui.py` fresh

  Read the whole file -- confirm `_send`, `_dispatch_text`,
  `_dispatch_in_thread`, `on_button_pressed`, and `launch` match this
  plan's earlier description of them (from Task 4 of the mouse-TUI plan).

  Step 2: Write the failing tests

  Add to `tests/console/test_tui.py`:

  ```python
  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_model_button_actually_lists_available_agents(tmp_path, monkeypatch):
      from whyline import account

      monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await pilot.click("#model")
          await pilot.pause()
          transcript = app.query_one("#transcript", tui.RichLog)
          assert any(
              "claude" in str(line) and "codex" in str(line) for line in transcript.lines
          )


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_route_relay_with_no_config_defers_exec_until_after_exit(
      tmp_path, monkeypatch
  ):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await pilot.click("#route")
          await pilot.pause()
          assert app._exec_after == ("whyline-relay", ["whyline-relay", "setup"])
      # app.run_test()'s own context manager has now exited (app.run() returned)
      # -- confirm launch() is what actually performs the exec, not the app itself.


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  def test_launch_performs_the_deferred_exec_after_app_run_returns(tmp_path, monkeypatch):
      calls = []

      class FakeApp:
          def __init__(self, *, root):
              self._exec_after = None

          def run(self):
              self._exec_after = ("whyline-relay", ["whyline-relay", "setup"])

      monkeypatch.setattr(tui, "WhylineConsoleApp", FakeApp)
      tui.launch(tmp_path, exec_fn=lambda binary, argv: calls.append((binary, argv)))
      assert calls == [("whyline-relay", ["whyline-relay", "setup"])]


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  def test_launch_does_not_exec_when_nothing_was_requested(tmp_path, monkeypatch):
      calls = []

      class FakeApp:
          def __init__(self, *, root):
              self._exec_after = None

          def run(self):
              pass  # ordinary exit, no setup requested

      monkeypatch.setattr(tui, "WhylineConsoleApp", FakeApp)
      tui.launch(tmp_path, exec_fn=lambda binary, argv: calls.append((binary, argv)))
      assert calls == []
  ```

  Step 3: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_tui.py -v`
  Expected: FAIL on every new test; every pre-existing test in the file
  still passes (nothing has changed yet).

  Step 4: Implement

  In `src/whyline/console/tui.py`, add the import:

  ```python
  from whyline.console.repl import dispatch, handle_slash_command
  ```

  Add `self._exec_after: tuple[str, list[str]] | None = None` to
  `__init__` (alongside the existing `self._dispatch_token`).

  Replace `on_button_pressed`:

  ```python
      def on_button_pressed(self, event: "Button.Pressed") -> None:
          button_id = event.button.id
          if button_id == "send":
              self._send()
          elif button_id == "stop":
              self._stop()
          elif button_id in ("model", "route", "history", "help"):
              self._handle_slash(f"/{button_id}")
  ```

  Replace `_send`:

  ```python
      def _send(self) -> None:
          prompt = self.query_one("#prompt", TextArea)
          text = prompt.text.strip()
          if not text:
              return
          prompt.text = ""
          if not self._handle_slash(text):
              self._dispatch_text(text)
  ```

  Add `_handle_slash`, the shared entry point both `on_button_pressed` and
  `_send` use:

  ```python
      def _handle_slash(self, text: str) -> bool:
          """Handles a slash command synchronously on the main thread -- no
          worker needed, these are fast, local operations. Returns True if
          `text` was a recognized slash command (whether or not it also
          triggered a setup handoff), False otherwise, so _send() knows
          whether to fall through to an ordinary (possibly slow) dispatch()
          call in a worker."""
          event = handle_slash_command(self.session, text)
          if event is None:
              return False
          if event.kind == "needs_setup":
              self._exec_after = ("whyline-relay", ["whyline-relay", "setup"])
              self.exit()
              return True
          self.render_event(event)
          return True
  ```

  Replace `launch`:

  ```python
  def launch(root: Path, *, exec_fn=None) -> None:
      if not TUI_AVAILABLE:
          raise TuiUnavailable(
              "The mouse TUI needs textual. Run: pip install 'whyline[ui]'"
          )
      if exec_fn is None:
          exec_fn = _exec
      app = WhylineConsoleApp(root=root)
      app.run()
      if app._exec_after is not None:
          binary, argv = app._exec_after
          exec_fn(binary, argv)
  ```

  Add the same `_exec` helper `repl.py` has (or import it from there, if
  you prefer a single shared definition -- either is fine, since it's a
  one-line wrapper: `def _exec(binary, argv): os.execvp(binary, argv)`,
  needing `import os`).

  Step 5: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_tui.py -v`
  Expected: PASS -- every pre-existing test unchanged in outcome, plus
  every new test from Step 2.

  Step 6: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 7: Commit

  ```bash
  git add src/whyline/console/tui.py tests/console/test_tui.py
  git commit -m "feat: wire the TUI's buttons to the shared slash-command handler; deferred setup handoff"
  ```

  ---
