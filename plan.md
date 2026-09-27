- [x] WEM-1: `cli.py` — `run_entry_menu` replaces `exec_into_chat`

  Global constraints:
  - No new runtime dependency.
  - which/exec_fn/subprocess_fn must be resolved at call time, not bound as default arguments.
  - No permission or validation logic is duplicated from whyline-relay into whyline -- this only ever execs into whyline-relay chat or whyline-relay setup, or runs whyline model as a plain subprocess.
  - Every existing test must still pass after every task.

  **Files:**
  - Modify: `src/whyline/cli.py`
  - Modify: `tests/test_cli_chat_delegation.py`
  - Modify: `tests/test_cli.py`

  **Interfaces:**
  - Produces: `cli.run_entry_menu(which=None, exec_fn=None, input_fn=None, print_fn=None, subprocess_fn=None) -> bool`. Returns `False` only when `whyline-relay` isn't installed (matching `exec_into_chat`'s own return contract, so `main()`'s existing fallback-to-usage branch needs no change beyond calling the new function). `exec_into_chat` is removed -- this is a deliberate, complete replacement of decision D2 from the chat-repl spec (bare `whyline` no longer execs straight into chat), not a parallel path.

  Step 1: Write the failing tests

  First, read `tests/test_cli_chat_delegation.py` in full -- it currently tests
  `exec_into_chat` directly. Replace its entire contents with:

  ```python
  from whyline import cli


  def test_entry_menu_default_choice_execs_into_chat():
      calls = []
      answers = iter(["", ""])  # accept both bracketed defaults: chat, chat
      result = cli.run_entry_menu(
          which=lambda name: f"/usr/bin/{name}" if name == "whyline-relay" else None,
          exec_fn=lambda binary, argv: calls.append(("exec", binary, argv)),
          input_fn=lambda prompt="": next(answers),
          subprocess_fn=lambda argv: calls.append(("subprocess", argv)),
      )
      assert result is True
      assert calls == [("exec", "whyline-relay", ["whyline-relay", "chat"])]


  def test_entry_menu_relay_choice_execs_into_setup():
      calls = []
      answers = iter(["relay"])
      result = cli.run_entry_menu(
          which=lambda name: f"/usr/bin/{name}" if name == "whyline-relay" else None,
          exec_fn=lambda binary, argv: calls.append(("exec", binary, argv)),
          input_fn=lambda prompt="": next(answers),
          subprocess_fn=lambda argv: calls.append(("subprocess", argv)),
      )
      assert result is True
      assert calls == [("exec", "whyline-relay", ["whyline-relay", "setup"])]


  def test_entry_menu_model_choice_runs_whyline_model_then_execs_into_chat():
      calls = []
      answers = iter(["chat", "model"])
      result = cli.run_entry_menu(
          which=lambda name: f"/usr/bin/{name}" if name == "whyline-relay" else None,
          exec_fn=lambda binary, argv: calls.append(("exec", binary, argv)),
          input_fn=lambda prompt="": next(answers),
          subprocess_fn=lambda argv: calls.append(("subprocess", argv)),
      )
      assert result is True
      assert calls == [
          ("subprocess", ["whyline", "model"]),
          ("exec", "whyline-relay", ["whyline-relay", "chat"]),
      ]


  def test_entry_menu_falls_through_when_whyline_relay_is_not_installed():
      def _unexpected_prompt(prompt=""):
          raise AssertionError(f"should never prompt when relay is absent: {prompt!r}")

      calls = []
      result = cli.run_entry_menu(
          which=lambda name: None,
          exec_fn=lambda binary, argv: calls.append((binary, argv)),
          input_fn=_unexpected_prompt,
          subprocess_fn=lambda argv: calls.append(("subprocess", argv)),
      )
      assert result is False
      assert calls == []


  def test_main_with_no_args_delegates_to_the_entry_menu(monkeypatch):
      calls = []
      monkeypatch.setattr(
          cli, "run_entry_menu", lambda **kwargs: calls.append("called") or True
      )
      code = cli.main([])
      assert calls == ["called"]
      assert code == cli.EXIT_OK


  def test_main_with_no_args_prints_usage_when_whyline_relay_is_absent(monkeypatch, capsys):
      monkeypatch.setattr(cli, "run_entry_menu", lambda **kwargs: False)
      code = cli.main([])
      assert code == cli.EXIT_USAGE
      assert capsys.readouterr().err  # existing usage text, unchanged
  ```

  Then, in `tests/test_cli.py`, find `test_no_command_is_a_usage_error` (it
  currently monkeypatches `cli.exec_into_chat`) and change it to monkeypatch
  the new function instead:

  ```python
  def test_no_command_is_a_usage_error(monkeypatch):
      # Real environments often have whyline-relay on PATH, which would make an
      # unmocked cli.main([]) actually run the entry menu (and potentially
      # exec) rather than reach the usage-error path this test checks.
      monkeypatch.setattr(cli, "run_entry_menu", lambda **kwargs: False)
      assert cli.main([]) == cli.EXIT_USAGE
  ```

  Step 2: Run tests to verify they fail

  Run: `uv run pytest tests/test_cli_chat_delegation.py tests/test_cli.py -k "entry_menu or no_command_is_a_usage_error" -v`
  Expected: FAIL — `cli.run_entry_menu` does not exist yet, and `main()` still
  calls `exec_into_chat`.

  Step 3: Implement

  In `src/whyline/cli.py`, add `import subprocess` alongside the existing
  `import os`/`import shutil` lines.

  Replace the entire `exec_into_chat` function:

  ```python
  def exec_into_chat(which=None, exec_fn=None) -> bool:
      """Replace this process with `whyline-relay chat`, if it's installed.

      `which`/`exec_fn` are resolved here, not as default arguments -- binding
      them in the signature would capture the function objects at import time,
      so a test's monkeypatch would silently have no effect and this would exec
      the real whyline-relay during a test run. `runner.py` documents this
      exact defect happening twice already; the same shape is used here on
      purpose.
      """
      which = which if which is not None else _which
      exec_fn = exec_fn if exec_fn is not None else _exec
      binary = which("whyline-relay")
      if binary is None:
          return False
      exec_fn("whyline-relay", ["whyline-relay", "chat"])
      return True  # unreachable when exec_fn is the real os.execvp
  ```

  with:

  ```python
  def run_entry_menu(
      which=None, exec_fn=None, input_fn=None, print_fn=None, subprocess_fn=None,
  ) -> bool:
      """Ask "Chat or relay?" and act on it. Returns False only when
      whyline-relay isn't installed, so main()'s existing fallback-to-usage
      behavior is unchanged for anyone not using the relay side.

      `which`/`exec_fn`/`subprocess_fn` are resolved here, not as default
      arguments -- binding them in the signature would capture the function
      objects at import time, so a test's monkeypatch would silently have no
      effect and this would exec/spawn something real during a test run.
      `runner.py` documents this exact defect happening twice already; the
      same shape is used here on purpose.
      """
      which = which if which is not None else _which
      exec_fn = exec_fn if exec_fn is not None else _exec
      input_fn = input_fn if input_fn is not None else input
      print_fn = print_fn if print_fn is not None else print
      subprocess_fn = subprocess_fn if subprocess_fn is not None else subprocess.run

      if which("whyline-relay") is None:
          return False

      choice = input_fn("Chat or relay? [chat]: ").strip().lower()
      if choice == "relay":
          exec_fn("whyline-relay", ["whyline-relay", "setup"])
          return True  # unreachable when exec_fn is the real os.execvp

      model_choice = input_fn(
          "Start chatting, or set a model first? [chat]: "
      ).strip().lower()
      if model_choice == "model":
          subprocess_fn(["whyline", "model"])
      exec_fn("whyline-relay", ["whyline-relay", "chat"])
      return True  # unreachable when exec_fn is the real os.execvp
  ```

  Update `main()`. Replace:

  ```python
  def main(argv: list[str] | None = None) -> int:
      parser = build_parser()
      args = parser.parse_args(argv)
      if not args.command:
          if exec_into_chat():
              return EXIT_OK
          parser.print_usage(sys.stderr)
          return EXIT_USAGE
      return COMMANDS[args.command](args)
  ```

  with:

  ```python
  def main(argv: list[str] | None = None) -> int:
      parser = build_parser()
      args = parser.parse_args(argv)
      if not args.command:
          if run_entry_menu():
              return EXIT_OK
          parser.print_usage(sys.stderr)
          return EXIT_USAGE
      return COMMANDS[args.command](args)
  ```

  Step 4: Run tests to verify they pass

  Run: `uv run pytest tests/test_cli_chat_delegation.py tests/test_cli.py -v`
  Expected: PASS, all of them.

  Step 5: Run the full suite

  Run: `uv run pytest -q`
  Expected: PASS.

  Step 6: Commit

  ```bash
  git add src/whyline/cli.py tests/test_cli_chat_delegation.py tests/test_cli.py
  git commit -m "feat: whyline asks Chat or Relay instead of going straight to chat"
  ```

  ---

- [ ] WEM-2: README — document the new entry menu

  Global constraints:
  - No new runtime dependency.
  - which/exec_fn/subprocess_fn must be resolved at call time, not bound as default arguments.
  - No permission or validation logic is duplicated from whyline-relay into whyline -- this only ever execs into whyline-relay chat or whyline-relay setup, or runs whyline model as a plain subprocess.
  - Every existing test must still pass after every task.

  **Files:**
  - Modify: `README.md`

  **Interfaces:**
  - None — documentation only.

  Step 1: Update the README

  Find the existing bullet (added for 0.3.5): "Typing `whyline` with no
  arguments starts an interactive chat REPL...". Replace it:

  ```markdown
  - **Typing `whyline` with no arguments asks "Chat or relay?"** (if whyline-relay is installed; otherwise it prints its usual usage). Chat leads into `whyline-relay chat` -- the same interactive REPL as before, with an added first question letting you run `whyline model` before starting if you want to pick a model. Relay leads into `whyline-relay setup`, a guided wizard that assigns implementer/tester/reviewer roles to a plan and runs `doctor`'s own correctness checks before offering to start it. See whyline-relay's own README for the full picture of both.
  ```

  Step 2: Commit

  ```bash
  git add README.md
  git commit -m "docs: document the Chat or Relay entry menu"
  ```
