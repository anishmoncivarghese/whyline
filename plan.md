- [x] UCF-1: Dependencies and the session/event model

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `prompt_toolkit` is only pulled in via the new `[console]` extra (UCF5); `whyline-relay` is only pulled in via the existing `[relay]` extra (UCF1) -- both are optional at runtime.
  - `whyline run`'s exec-and-hand-over design is untouched by this plan -- it is not part of the console's event system at all.
  - Every relay/chat integration is a **direct, in-process function call** into already-structured whyline-relay functions (`chat.run_turn`, `preflight.run`, `running.live`, `state.load`) wherever one exists; only `start`/`resume` (whose real orchestration lives only in whyline-relay's own `cli.py`, not a reusable function) go through `relay_cli.main()` in-process with light text classification. No subprocess is ever spawned for whyline-relay integration.
  - Ctrl+C is caught via a plain `try/except KeyboardInterrupt` around the single call site that dispatched the in-flight command -- never around the whole REPL loop, and never anything that touches process signals.
  - Bare `account` and bare `model` (both interactive, real `input()` calls) are refused in `command` mode with a message pointing at `/model` -- never dispatched, since capturing stdout does nothing about stdin.
  - Every existing test in this repo must still pass after every task. This plan makes no changes to `whyline-relay`'s own repository at all -- it is a pure consumer of already-released, already-tested functions.

  **Note on this pairing:** Grok implements, Codex reviews.

  **Files:**
  - Modify: `pyproject.toml`
  - Create: `src/whyline/console/__init__.py` (empty)
  - Create: `src/whyline/console/session.py`
  - Test: `tests/console/__init__.py` (empty), `tests/console/test_session.py`

  **Interfaces:**
  - Produces: `SessionEvent(kind: str, text: str)` (a frozen dataclass; `kind` is one of `"output"`, `"handoff"`, `"pause"`, `"error"`, `"exit"`). `ConsoleSession(root: Path, mode: str = "command", agent: str | None = None, transcript: list[SessionEvent] = [])` (a plain, mutable dataclass) with one method, `record(event: SessionEvent) -> SessionEvent`, which appends to `transcript` and returns the same event (so callers can both store and immediately print it in one expression).

  Step 1: Add the two new dependency declarations

  In `pyproject.toml`, add a new optional-dependencies entry right after the
  existing `relay` one:

  ```toml
  [project.optional-dependencies]
  relay = ["whyline-relay>=0.2.1,<0.3"]
  console = ["prompt_toolkit>=3.0,<4.0"]
  ```

  And change the `dev` dependency group:

  ```toml
  [dependency-groups]
  dev = ["pytest>=8.0", "whyline-relay>=0.2.1,<0.3"]
  ```

  Run `uv sync` (or your environment's equivalent) so `whyline_relay` becomes
  importable for this repo's own test run -- every later task in this plan
  depends on it being installed.

  Step 2: Verify whyline_relay is now importable

  Run: `python3 -c "import whyline_relay; print('ok')"`
  Expected: prints `ok` (previously raised `ModuleNotFoundError`)

  Step 3: Write the failing tests

  Create `tests/console/__init__.py` (empty file -- makes `tests/console` a
  package so pytest discovers it alongside the existing flat `tests/*.py`
  files).

  Create `tests/console/test_session.py`:

  ```python
  from whyline.console.session import ConsoleSession, SessionEvent


  def test_session_event_holds_kind_and_text():
      event = SessionEvent(kind="output", text="hello")
      assert event.kind == "output"
      assert event.text == "hello"


  def test_console_session_defaults(tmp_path):
      session = ConsoleSession(root=tmp_path)
      assert session.mode == "command"
      assert session.agent is None
      assert session.transcript == []


  def test_record_appends_and_returns_the_event(tmp_path):
      session = ConsoleSession(root=tmp_path)
      event = SessionEvent(kind="output", text="hi")
      returned = session.record(event)
      assert returned is event
      assert session.transcript == [event]


  def test_record_preserves_order_across_multiple_events(tmp_path):
      session = ConsoleSession(root=tmp_path)
      first = session.record(SessionEvent(kind="output", text="one"))
      second = session.record(SessionEvent(kind="error", text="two"))
      assert session.transcript == [first, second]
  ```

  Step 4: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_session.py -v`
  Expected: FAIL (`ModuleNotFoundError: No module named 'whyline.console'`)

  Step 5: Implement

  Create `src/whyline/console/__init__.py` (empty).

  Create `src/whyline/console/session.py`:

  ```python
  """The provider-neutral session and event model for `whyline console`.

  Every command adapter returns a SessionEvent instead of printing directly,
  so the render loop (repl.py) is the only place that ever touches the
  terminal -- this is what lets a later full-screen UI reuse this exact
  model without rewriting the adapters.
  """

  from __future__ import annotations

  from dataclasses import dataclass, field
  from pathlib import Path


  @dataclass(frozen=True)
  class SessionEvent:
      kind: str  # "output" | "handoff" | "pause" | "error" | "exit"
      text: str


  @dataclass
  class ConsoleSession:
      root: Path
      mode: str = "command"  # "command" | "relay" | "chat"
      agent: str | None = None
      transcript: list[SessionEvent] = field(default_factory=list)

      def record(self, event: SessionEvent) -> SessionEvent:
          self.transcript.append(event)
          return event
  ```

  Step 6: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_session.py -v`
  Expected: PASS

  Step 7: Commit

  ```bash
  git add pyproject.toml src/whyline/console/__init__.py src/whyline/console/session.py tests/console/__init__.py tests/console/test_session.py
  git commit -m "feat: add console/relay dev dependency and the session/event model"
  ```

  ---

- [x] UCF-2: `adapters.py` -- `run_whyline_command` (in-process whyline commands)

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `prompt_toolkit` is only pulled in via the new `[console]` extra (UCF5); `whyline-relay` is only pulled in via the existing `[relay]` extra (UCF1) -- both are optional at runtime.
  - `whyline run`'s exec-and-hand-over design is untouched by this plan -- it is not part of the console's event system at all.
  - Every relay/chat integration is a **direct, in-process function call** into already-structured whyline-relay functions (`chat.run_turn`, `preflight.run`, `running.live`, `state.load`) wherever one exists; only `start`/`resume` (whose real orchestration lives only in whyline-relay's own `cli.py`, not a reusable function) go through `relay_cli.main()` in-process with light text classification. No subprocess is ever spawned for whyline-relay integration.
  - Ctrl+C is caught via a plain `try/except KeyboardInterrupt` around the single call site that dispatched the in-flight command -- never around the whole REPL loop, and never anything that touches process signals.
  - Bare `account` and bare `model` (both interactive, real `input()` calls) are refused in `command` mode with a message pointing at `/model` -- never dispatched, since capturing stdout does nothing about stdin.
  - Every existing test in this repo must still pass after every task. This plan makes no changes to `whyline-relay`'s own repository at all -- it is a pure consumer of already-released, already-tested functions.

  **Note on this pairing:** Grok implements, Codex reviews.

  **Files:**
  - Create: `src/whyline/console/adapters.py`
  - Test: `tests/console/test_adapters_whyline.py`

  **Interfaces:**
  - Consumes: `SessionEvent` (Task 1).
  - Produces: `run_whyline_command(argv: list[str]) -> SessionEvent`. Captures whatever `whyline.cli.main(argv)` would have printed to stdout/stderr and its exit code; refuses bare `account`/`model` without calling `cli.main` at all.

  Step 1: Write the failing tests

  Create `tests/console/test_adapters_whyline.py`:

  ```python
  import os
  from pathlib import Path

  from whyline.console import adapters


  def _chdir(path: Path):
      previous = os.getcwd()
      os.chdir(path)
      return previous


  def test_run_whyline_command_captures_output_and_succeeds(repo):
      previous = _chdir(repo.path)
      try:
          event = adapters.run_whyline_command(["note", "a decision", "--because", "testing"])
      finally:
          os.chdir(previous)
      assert event.kind == "output"


  def test_run_whyline_command_reports_a_nonzero_exit_as_an_error(repo, monkeypatch):
      previous = _chdir(repo.path)
      try:
          # "explain" with no whyline init here fails with EXIT_UNINITIALISED or
          # similar -- any real non-init'd repo already exercises a failure path
          # without needing to fake anything.
          event = adapters.run_whyline_command(["sync"])
      finally:
          os.chdir(previous)
      assert event.kind == "error"


  def test_run_whyline_command_refuses_bare_account():
      event = adapters.run_whyline_command(["account"])
      assert event.kind == "error"
      assert "/model" in event.text


  def test_run_whyline_command_refuses_bare_model():
      event = adapters.run_whyline_command(["model"])
      assert event.kind == "error"
      assert "/model" in event.text


  def test_run_whyline_command_allows_account_status(repo, monkeypatch, tmp_path):
      from whyline import account
      home = tmp_path / "home"
      monkeypatch.setattr(account.paths.Path, "home", lambda: home)
      account.save_global({
          agent: {"plan": None, "available": True}
          for agent in ("codex", "claude", "antigravity", "grok")
      })
      previous = _chdir(repo.path)
      try:
          event = adapters.run_whyline_command(["account", "status"])
      finally:
          os.chdir(previous)
      assert event.kind == "output"


  def test_run_whyline_command_allows_model_status(repo):
      previous = _chdir(repo.path)
      try:
          event = adapters.run_whyline_command(["model", "status"])
      finally:
          os.chdir(previous)
      assert event.kind == "output"
      assert "nothing set" in event.text.lower()
  ```

  Note: the `repo` fixture (from `tests/conftest.py`) gives a bare git repo
  with no `whyline init` run -- `sync` failing there (uninitialised) is a
  real, unforced failure path, not something you need to fake.

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_adapters_whyline.py -v`
  Expected: FAIL (`ModuleNotFoundError: No module named 'whyline.console.adapters'`)

  Step 3: Implement

  Create `src/whyline/console/adapters.py`:

  ```python
  """Bridging whyline console to whyline's own commands and whyline-relay's
  already-structured functions. Every function here returns a SessionEvent
  instead of printing -- see session.py's own docstring for why.
  """

  from __future__ import annotations

  import contextlib
  import io
  import re
  from pathlib import Path

  from whyline.console.session import SessionEvent

  _INTERACTIVE_ONLY = {"account", "model"}


  def run_whyline_command(argv: list[str]) -> SessionEvent:
      """Runs a non-interactive whyline command in-process, capturing its
      output. Bare "account"/"model" are interactive (real input() calls);
      redirecting stdout does nothing about stdin, so both are refused here
      rather than risking a hang on the wrong input source."""
      if len(argv) == 1 and argv[0] in _INTERACTIVE_ONLY:
          return SessionEvent(
              kind="error",
              text=(
                  f"'{argv[0]}' needs a subcommand here (e.g. "
                  f"'{argv[0]} status'), or use /model instead of the "
                  "interactive wizard."
              ),
          )
      from whyline import cli

      buf = io.StringIO()
      try:
          with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
              code = cli.main(argv)
      except SystemExit as error:
          code = error.code if isinstance(error.code, int) else cli.EXIT_ERROR
      text = buf.getvalue()
      return SessionEvent(kind="output" if code == 0 else "error", text=text)
  ```

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_adapters_whyline.py -v`
  Expected: PASS

  Step 5: Commit

  ```bash
  git add src/whyline/console/adapters.py tests/console/test_adapters_whyline.py
  git commit -m "feat: run_whyline_command adapter for in-process whyline commands"
  ```

  ---

- [ ] UCF-3: `adapters.py` -- `run_chat_turn`, `run_doctor`, `run_status`

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `prompt_toolkit` is only pulled in via the new `[console]` extra (UCF5); `whyline-relay` is only pulled in via the existing `[relay]` extra (UCF1) -- both are optional at runtime.
  - `whyline run`'s exec-and-hand-over design is untouched by this plan -- it is not part of the console's event system at all.
  - Every relay/chat integration is a **direct, in-process function call** into already-structured whyline-relay functions (`chat.run_turn`, `preflight.run`, `running.live`, `state.load`) wherever one exists; only `start`/`resume` (whose real orchestration lives only in whyline-relay's own `cli.py`, not a reusable function) go through `relay_cli.main()` in-process with light text classification. No subprocess is ever spawned for whyline-relay integration.
  - Ctrl+C is caught via a plain `try/except KeyboardInterrupt` around the single call site that dispatched the in-flight command -- never around the whole REPL loop, and never anything that touches process signals.
  - Bare `account` and bare `model` (both interactive, real `input()` calls) are refused in `command` mode with a message pointing at `/model` -- never dispatched, since capturing stdout does nothing about stdin.
  - Every existing test in this repo must still pass after every task. This plan makes no changes to `whyline-relay`'s own repository at all -- it is a pure consumer of already-released, already-tested functions.

  **Note on this pairing:** Grok implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/adapters.py`
  - Test: `tests/console/test_adapters_relay_structured.py`

  **Interfaces:**
  - Consumes: `SessionEvent` (Task 1); `whyline_relay.chat.run_turn`, `whyline_relay.chat.AgentUnavailable`, `whyline_relay.agents.AgentMissing`/`AgentTimeout`, `whyline_relay.preflight.run`, `whyline_relay.preflight.Check`, `whyline_relay.running.live`, `whyline_relay.running.Running`, `whyline_relay.state.load`, `whyline_relay.state.RelayState`, `whyline_relay.config.load` (all already released, unchanged by this plan).
  - Produces: `run_chat_turn(root: Path, *, agent: str, prompt: str) -> SessionEvent`. `run_doctor(root: Path, plan_path: Path | None = None) -> SessionEvent`. `run_status(root: Path) -> SessionEvent`.

  Step 1: Write the failing tests

  Create `tests/console/test_adapters_relay_structured.py`:

  ```python
  from pathlib import Path

  from whyline.console import adapters


  def _init_relay_repo(repo):
      import subprocess

      subprocess.run(
          ["git", "config", "user.email", "t@t"], cwd=repo.path, check=True
      )
      subprocess.run(["git", "config", "user.name", "t"], cwd=repo.path, check=True)
      (repo.path / "README.md").write_text("x\n")
      subprocess.run(["git", "add", "-A"], cwd=repo.path, check=True)
      subprocess.run(["git", "commit", "-m", "init"], cwd=repo.path, check=True)


  def test_run_chat_turn_returns_an_output_event_on_success(repo, monkeypatch):
      _init_relay_repo(repo)
      from whyline_relay import chat, config as relay_config

      def fake_run_fn(command, prompt, **kwargs):
          from whyline_relay.agents import RunResult
          return RunResult(0, '{"type":"result","result":"pong"}\n')

      monkeypatch.setattr(
          adapters, "_chat_run_fn_for_tests", fake_run_fn, raising=False
      )
      # run_chat_turn must accept an injected run_fn the same way chat.run_turn
      # itself does -- see the implementation step for why this parameter
      # exists.
      event = adapters.run_chat_turn(
          repo.path, agent="claude", prompt="ping", run_fn=fake_run_fn
      )
      assert event.kind == "output"
      assert "pong" in event.text


  def test_run_chat_turn_reports_agent_unavailable(repo):
      _init_relay_repo(repo)
      event = adapters.run_chat_turn(repo.path, agent="grok", prompt="ping")
      assert event.kind == "error"
      assert "grok" in event.text


  def test_run_chat_turn_reports_agent_missing(repo, monkeypatch):
      _init_relay_repo(repo)
      from whyline_relay import agents

      def fake_run_fn(command, prompt, **kwargs):
          raise agents.AgentMissing("claude is not installed")

      event = adapters.run_chat_turn(
          repo.path, agent="claude", prompt="ping", run_fn=fake_run_fn
      )
      assert event.kind == "error"
      assert "not installed" in event.text


  def test_run_doctor_reports_ok_when_checks_pass(repo, monkeypatch):
      from whyline_relay import preflight

      monkeypatch.setattr(
          preflight, "run",
          lambda root, plan_path=None, **kwargs: [
              preflight.Check(status="ok", message="all good")
          ],
      )
      event = adapters.run_doctor(repo.path)
      assert event.kind == "output"
      assert "all good" in event.text


  def test_run_doctor_reports_error_when_a_check_fails(repo, monkeypatch):
      from whyline_relay import preflight

      monkeypatch.setattr(
          preflight, "run",
          lambda root, plan_path=None, **kwargs: [
              preflight.Check(status="FAIL", message="broken", hint="fix it")
          ],
      )
      event = adapters.run_doctor(repo.path)
      assert event.kind == "error"
      assert "broken" in event.text
      assert "fix it" in event.text


  def test_run_status_with_nothing_running_says_so(repo):
      event = adapters.run_status(repo.path)
      assert event.kind == "output"
      assert "no relay run in progress" in event.text.lower()


  def test_run_status_reports_a_paused_run(repo):
      from whyline_relay import state

      state.save(
          repo.path,
          state.RelayState(
              plan="plan.md", branch="relay/plan", task_id="T-1", round=1,
              base_commit="abc123", paused_reason="stuck", log_path="",
          ),
      )
      event = adapters.run_status(repo.path)
      assert event.kind == "pause"
      assert "T-1" in event.text
      assert "stuck" in event.text
  ```

  Check `whyline_relay.state`'s exact save function name (`state.save(root,
  RelayState(...))`) against the real module before trusting it verbatim --
  read `src/whyline_relay/state.py` in the whyline-relay repo if it differs.

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_adapters_relay_structured.py -v`
  Expected: FAIL (`AttributeError: module 'adapters' has no attribute
  'run_chat_turn'`, etc.)

  Step 3: Implement

  Add to `src/whyline/console/adapters.py`:

  ```python
  def run_chat_turn(
      root: Path, *, agent: str, prompt: str, run_fn=None, runner=None
  ) -> SessionEvent:
      """Calls whyline-relay's chat.run_turn directly -- already the exact
      structured, reusable core chat's own REPL is built on. run_fn/runner
      are accepted only so tests can inject fakes the same way
      whyline-relay's own test suite does; real use never passes them."""
      from whyline_relay import agents, chat
      from whyline_relay import config as relay_config

      settings = relay_config.load(root)
      kwargs = {}
      if run_fn is not None:
          kwargs["run_fn"] = run_fn
      if runner is not None:
          kwargs["runner"] = runner
      try:
          record = chat.run_turn(
              root, agent=agent, prompt=prompt, settings=settings, **kwargs
          )
      except chat.AgentUnavailable as error:
          return SessionEvent(kind="error", text=str(error))
      except agents.AgentMissing as error:
          return SessionEvent(kind="error", text=str(error))
      except agents.AgentTimeout as error:
          return SessionEvent(
              kind="error", text=f"{error} -- try again, or /model another agent."
          )

      lines = []
      if record.get("failover_notice"):
          lines.append(record["failover_notice"])
      lines.append(f"[{record['agent']}] {record['response']}")
      if record["rate_limited"]:
          lines.append(
              f"{record['agent']} looks rate-limited -- /model another agent, or wait."
          )
      if record.get("diff_stat"):
          prefix = "" if record["ok"] else "⚠ "
          lines.append(f"{prefix}{record['diff_stat'].strip()}")
      return SessionEvent(
          kind="output" if record["ok"] else "error", text="\n".join(lines)
      )


  def run_doctor(root: Path, plan_path: Path | None = None) -> SessionEvent:
      """Calls whyline-relay's preflight.run directly -- already a clean,
      side-effect-free function returning structured Check objects."""
      from whyline_relay import preflight

      checks = preflight.run(root, plan_path)
      lines = []
      for check in checks:
          line = f"  {check.status:<4}  {check.message}"
          if check.status != "ok" and check.hint:
              line += f"\n        fix: {check.hint}"
          lines.append(line)
      failures = sum(check.status == "FAIL" for check in checks)
      lines.append("All checks passed." if failures == 0 else f"{failures} problem(s) found.")
      return SessionEvent(kind="output" if failures == 0 else "error", text="\n".join(lines))


  def run_status(root: Path) -> SessionEvent:
      """Calls whyline-relay's running.live/state.load directly -- both
      already side-effect-free, structured data access; builds its own text
      from the fields rather than reusing cmd_status's print statements."""
      from datetime import datetime

      from whyline_relay import agents as relay_agents
      from whyline_relay import running, state

      lines = []
      active = running.live(root)
      if active is not None:
          try:
              started = datetime.fromisoformat(active.started)
              elapsed = datetime.now(started.tzinfo) - started
              since = started.strftime("%H:%M:%S")
              ago = relay_agents.format_duration(elapsed.total_seconds())
          except ValueError:
              since, ago = active.started, "unknown"
          action = "reviewing" if active.role == "reviewer" else "implementing"
          lines.append(
              f"Running: {active.agent} {action} {active.task}, round "
              f"{active.round}, since {since} ({ago} ago)"
          )
      saved = state.load(root)
      if saved is None:
          if active is None:
              lines.append("No relay run in progress.")
          return SessionEvent(kind="output", text="\n".join(lines))
      lines.append(f"Task      {saved.task_id}")
      lines.append(f"Branch    {saved.branch}")
      lines.append(f"Plan      {saved.plan}")
      lines.append(f"Paused    {saved.paused_reason}")
      if saved.log_path:
          lines.append(f"Log       {saved.log_path}")
      return SessionEvent(kind="pause", text="\n".join(lines))
  ```

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_adapters_relay_structured.py -v`
  Expected: PASS

  If `test_run_status_reports_a_paused_run` fails because `state.save`'s real
  signature differs from what's written above, read
  `/Users/anish/whyline-relay/src/whyline_relay/state.py` and adjust the
  test's call to match -- do not change `run_status`'s own implementation to
  work around a test-only mismatch.

  Step 5: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 6: Commit

  ```bash
  git add src/whyline/console/adapters.py tests/console/test_adapters_relay_structured.py
  git commit -m "feat: run_chat_turn/run_doctor/run_status adapters (direct structured calls)"
  ```

  ---

- [ ] UCF-4: `adapters.py` -- `run_relay_oneshot` (`start`/`resume`)

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `prompt_toolkit` is only pulled in via the new `[console]` extra (UCF5); `whyline-relay` is only pulled in via the existing `[relay]` extra (UCF1) -- both are optional at runtime.
  - `whyline run`'s exec-and-hand-over design is untouched by this plan -- it is not part of the console's event system at all.
  - Every relay/chat integration is a **direct, in-process function call** into already-structured whyline-relay functions (`chat.run_turn`, `preflight.run`, `running.live`, `state.load`) wherever one exists; only `start`/`resume` (whose real orchestration lives only in whyline-relay's own `cli.py`, not a reusable function) go through `relay_cli.main()` in-process with light text classification. No subprocess is ever spawned for whyline-relay integration.
  - Ctrl+C is caught via a plain `try/except KeyboardInterrupt` around the single call site that dispatched the in-flight command -- never around the whole REPL loop, and never anything that touches process signals.
  - Bare `account` and bare `model` (both interactive, real `input()` calls) are refused in `command` mode with a message pointing at `/model` -- never dispatched, since capturing stdout does nothing about stdin.
  - Every existing test in this repo must still pass after every task. This plan makes no changes to `whyline-relay`'s own repository at all -- it is a pure consumer of already-released, already-tested functions.

  **Note on this pairing:** Grok implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/adapters.py`
  - Test: `tests/console/test_adapters_relay_oneshot.py`

  **Interfaces:**
  - Consumes: `SessionEvent` (Task 1); `whyline_relay.cli.main`.
  - Produces: `run_relay_oneshot(root: Path, argv: list[str]) -> SessionEvent`. `argv[0]` is the relay subcommand (`"start"` or `"resume"`); `--repo <root>` is appended automatically.

  Step 1: Write the failing tests

  Create `tests/console/test_adapters_relay_oneshot.py`:

  ```python
  from whyline.console import adapters


  def test_run_relay_oneshot_classifies_a_pause(monkeypatch):
      from whyline_relay import cli as relay_cli

      def fake_main(argv, prog="whyline-relay"):
          print("Paused: something went wrong")
          return 1

      monkeypatch.setattr(relay_cli, "main", fake_main)
      event = adapters.run_relay_oneshot("/some/repo", ["resume"])
      assert event.kind == "pause"
      assert "Paused: something went wrong" in event.text


  def test_run_relay_oneshot_classifies_completion(monkeypatch):
      from whyline_relay import cli as relay_cli

      def fake_main(argv, prog="whyline-relay"):
          print("Plan complete: 3 task(s) approved and committed.")
          return 0

      monkeypatch.setattr(relay_cli, "main", fake_main)
      event = adapters.run_relay_oneshot("/some/repo", ["start"])
      assert event.kind == "output"
      assert "Plan complete" in event.text


  def test_run_relay_oneshot_passes_repo_flag(monkeypatch):
      from whyline_relay import cli as relay_cli
      captured = []

      def fake_main(argv, prog="whyline-relay"):
          captured.append(argv)
          return 0

      monkeypatch.setattr(relay_cli, "main", fake_main)
      adapters.run_relay_oneshot("/some/repo", ["start"])
      assert captured == [["start", "--repo", "/some/repo"]]


  def test_run_relay_oneshot_reports_an_unrecognised_error_without_dropping_text(
      monkeypatch,
  ):
      from whyline_relay import cli as relay_cli

      def fake_main(argv, prog="whyline-relay"):
          print("something odd happened that matches no known pattern")
          return 1

      monkeypatch.setattr(relay_cli, "main", fake_main)
      event = adapters.run_relay_oneshot("/some/repo", ["start"])
      assert event.kind == "error"
      assert "something odd happened" in event.text


  def test_run_relay_oneshot_shows_the_install_hint_when_whyline_relay_is_missing(
      monkeypatch,
  ):
      import builtins

      real_import = builtins.__import__

      def fake_import(name, *args, **kwargs):
          if name == "whyline_relay" or name.startswith("whyline_relay."):
              raise ModuleNotFoundError(name)
          return real_import(name, *args, **kwargs)

      monkeypatch.setattr(builtins, "__import__", fake_import)
      event = adapters.run_relay_oneshot("/some/repo", ["start"])
      assert event.kind == "error"
      assert "whyline[relay]" in event.text or "whyline-relay" in event.text
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_adapters_relay_oneshot.py -v`
  Expected: FAIL (`AttributeError: module 'adapters' has no attribute
  'run_relay_oneshot'`)

  Step 3: Implement

  First, read `relay_install_hint()` in `src/whyline/cli.py` (it already
  exists, used by `cmd_relay`) so this reuses its exact wording instead of
  duplicating it.

  Add to `src/whyline/console/adapters.py`:

  ```python
  _PAUSE_PATTERN = re.compile(r"^Paused:", re.M)
  _COMPLETE_PATTERN = re.compile(r"^Plan complete", re.M)


  def run_relay_oneshot(root, argv: list[str]) -> SessionEvent:
      """Calls whyline-relay's cli.main in-process (the same shallow level
      cmd_relay already uses) for start/resume, whose real orchestration
      (branch setup, guards) is not factored into a reusable function --
      reimplementing it here would itself be duplication. Output is captured
      and lightly classified with the same text patterns relay-auto-resume.sh
      already parses; an unrecognized line is still shown verbatim, never
      dropped."""
      try:
          from whyline_relay import cli as relay_cli
      except ModuleNotFoundError as error:
          if error.name != "whyline_relay":
              raise
          from whyline.cli import relay_install_hint

          return SessionEvent(kind="error", text=relay_install_hint())

      full_argv = [*argv, "--repo", str(root)]
      buf = io.StringIO()
      with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
          code = relay_cli.main(full_argv, prog="whyline-relay")
      text = buf.getvalue()
      if _PAUSE_PATTERN.search(text):
          kind = "pause"
      elif _COMPLETE_PATTERN.search(text) or code == 0:
          kind = "output"
      else:
          kind = "error"
      return SessionEvent(kind=kind, text=text)
  ```

  Note `str(root)` handles both a real `Path` and the plain string
  `"/some/repo"` used in the tests above -- `str()` on an already-`str` value
  is a no-op.

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_adapters_relay_oneshot.py -v`
  Expected: PASS

  Step 5: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 6: Commit

  ```bash
  git add src/whyline/console/adapters.py tests/console/test_adapters_relay_oneshot.py
  git commit -m "feat: run_relay_oneshot adapter for start/resume"
  ```

  ---

- [ ] UCF-5: `editor.py` -- the guarded `prompt_toolkit` wrapper

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `prompt_toolkit` is only pulled in via the new `[console]` extra (UCF5); `whyline-relay` is only pulled in via the existing `[relay]` extra (UCF1) -- both are optional at runtime.
  - `whyline run`'s exec-and-hand-over design is untouched by this plan -- it is not part of the console's event system at all.
  - Every relay/chat integration is a **direct, in-process function call** into already-structured whyline-relay functions (`chat.run_turn`, `preflight.run`, `running.live`, `state.load`) wherever one exists; only `start`/`resume` (whose real orchestration lives only in whyline-relay's own `cli.py`, not a reusable function) go through `relay_cli.main()` in-process with light text classification. No subprocess is ever spawned for whyline-relay integration.
  - Ctrl+C is caught via a plain `try/except KeyboardInterrupt` around the single call site that dispatched the in-flight command -- never around the whole REPL loop, and never anything that touches process signals.
  - Bare `account` and bare `model` (both interactive, real `input()` calls) are refused in `command` mode with a message pointing at `/model` -- never dispatched, since capturing stdout does nothing about stdin.
  - Every existing test in this repo must still pass after every task. This plan makes no changes to `whyline-relay`'s own repository at all -- it is a pure consumer of already-released, already-tested functions.

  **Note on this pairing:** Grok implements, Codex reviews.

  **Files:**
  - Create: `src/whyline/console/editor.py`
  - Test: `tests/console/test_editor.py`

  **Interfaces:**
  - Produces: `EditorUnavailable(RuntimeError)`. `build_session(root: Path)` --
    returns a `prompt_toolkit.PromptSession` configured for multiline input
    with per-repo history at `.whyline/console-history`, or raises
    `EditorUnavailable` with an install-instruction message if
    `prompt_toolkit` isn't installed.

  Step 1: Write the failing tests

  Create `tests/console/test_editor.py`:

  ```python
  import builtins

  import pytest

  from whyline.console import editor


  def test_build_session_raises_a_clear_error_without_prompt_toolkit(
      tmp_path, monkeypatch
  ):
      monkeypatch.setattr(editor, "AVAILABLE", False)
      with pytest.raises(editor.EditorUnavailable, match=r"whyline\[console\]"):
          editor.build_session(tmp_path)


  def test_module_imports_cleanly_even_if_prompt_toolkit_is_missing(monkeypatch):
      # Simulates a real environment without the [console] extra installed --
      # editor.py itself must still import without raising.
      real_import = builtins.__import__

      def fake_import(name, *args, **kwargs):
          if name == "prompt_toolkit" or name.startswith("prompt_toolkit."):
              raise ImportError(name)
          return real_import(name, *args, **kwargs)

      monkeypatch.setattr(builtins, "__import__", fake_import)
      import importlib

      reloaded = importlib.reload(editor)
      assert reloaded.AVAILABLE is False
      importlib.reload(editor)  # restore real state for later tests in this process


  @pytest.mark.skipif(
      not editor.AVAILABLE, reason="prompt_toolkit not installed -- skip the real smoke test"
  )
  def test_build_session_returns_a_real_prompt_session_when_installed(tmp_path):
      session = editor.build_session(tmp_path)
      assert session is not None
      assert (tmp_path / ".whyline" / "console-history").parent.exists()
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_editor.py -v`
  Expected: FAIL (`ModuleNotFoundError: No module named 'whyline.console.editor'`)

  Step 3: Implement

  Create `src/whyline/console/editor.py`:

  ```python
  """A thin, import-guarded wrapper over prompt_toolkit's multiline editor.

  Guarded so the rest of the console package stays importable and testable
  without the [console] extra installed -- only actually starting the
  editor (build_session) requires it.
  """

  from __future__ import annotations

  from pathlib import Path

  try:
      from prompt_toolkit import PromptSession
      from prompt_toolkit.history import FileHistory

      AVAILABLE = True
  except ImportError:
      PromptSession = None
      FileHistory = None
      AVAILABLE = False


  class EditorUnavailable(RuntimeError):
      """prompt_toolkit is not installed."""


  def build_session(root: Path):
      if not AVAILABLE:
          raise EditorUnavailable(
              "The console's editor needs prompt_toolkit. Run: "
              "pip install 'whyline[console]'"
          )
      history_path = root / ".whyline" / "console-history"
      history_path.parent.mkdir(parents=True, exist_ok=True)
      return PromptSession(multiline=True, history=FileHistory(str(history_path)))
  ```

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_editor.py -v`
  Expected: PASS (the real-smoke-test only runs if `prompt_toolkit` happens
  to be installed in this environment; otherwise it's skipped, not failed)

  Step 5: Commit

  ```bash
  git add src/whyline/console/editor.py tests/console/test_editor.py
  git commit -m "feat: guarded prompt_toolkit editor wrapper"
  ```

  ---

- [ ] UCF-6: `repl.py`, `cli.py` wiring, and end-to-end test

  ## Global Constraints

  - No new *required* dependency in the base `whyline` install. `prompt_toolkit` is only pulled in via the new `[console]` extra (UCF5); `whyline-relay` is only pulled in via the existing `[relay]` extra (UCF1) -- both are optional at runtime.
  - `whyline run`'s exec-and-hand-over design is untouched by this plan -- it is not part of the console's event system at all.
  - Every relay/chat integration is a **direct, in-process function call** into already-structured whyline-relay functions (`chat.run_turn`, `preflight.run`, `running.live`, `state.load`) wherever one exists; only `start`/`resume` (whose real orchestration lives only in whyline-relay's own `cli.py`, not a reusable function) go through `relay_cli.main()` in-process with light text classification. No subprocess is ever spawned for whyline-relay integration.
  - Ctrl+C is caught via a plain `try/except KeyboardInterrupt` around the single call site that dispatched the in-flight command -- never around the whole REPL loop, and never anything that touches process signals.
  - Bare `account` and bare `model` (both interactive, real `input()` calls) are refused in `command` mode with a message pointing at `/model` -- never dispatched, since capturing stdout does nothing about stdin.
  - Every existing test in this repo must still pass after every task. This plan makes no changes to `whyline-relay`'s own repository at all -- it is a pure consumer of already-released, already-tested functions.

  **Note on this pairing:** Grok implements, Codex reviews.

  **Files:**
  - Create: `src/whyline/console/repl.py`
  - Modify: `src/whyline/cli.py`
  - Test: `tests/console/test_repl.py`, `tests/test_cli_console.py`

  **Interfaces:**
  - Consumes: everything from Tasks 1-5 (`ConsoleSession`, `SessionEvent`,
    all five adapters, `editor.build_session`/`EditorUnavailable`).
  - Produces: `repl.run(root: Path, *, print_fn=print, prompt_session=None) ->
    None` -- the main loop. `whyline console` as a new CLI subcommand.

  Step 1: Write the failing tests

  Create `tests/console/test_repl.py`:

  ```python
  from whyline.console import editor, repl
  from whyline.console.session import SessionEvent


  class FakePromptSession:
      """A minimal stand-in for prompt_toolkit.PromptSession: replays a fixed
      list of inputs, then raises EOFError (matching Ctrl+D) to end the loop."""

      def __init__(self, inputs):
          self._inputs = iter(inputs)

      def prompt(self, message=""):
          try:
              return next(self._inputs)
          except StopIteration:
              raise EOFError


  def test_repl_prints_a_banner_and_exits_cleanly(tmp_path, monkeypatch):
      monkeypatch.setattr(editor, "build_session", lambda root: FakePromptSession(["/exit"]))
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("whyline console" in line for line in lines)


  def test_repl_shows_the_install_hint_if_the_editor_is_unavailable(tmp_path, monkeypatch):
      def raise_unavailable(root):
          raise editor.EditorUnavailable("pip install 'whyline[console]'")

      monkeypatch.setattr(editor, "build_session", raise_unavailable)
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("whyline[console]" in line for line in lines)


  def test_route_switches_mode(tmp_path, monkeypatch):
      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(["/route relay", "/exit"]),
      )
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("Mode is now relay" in line for line in lines)


  def test_route_rejects_an_unknown_mode(tmp_path, monkeypatch):
      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(["/route nonsense", "/exit"]),
      )
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("Usage: /route" in line for line in lines)


  def test_command_mode_dispatches_to_run_whyline_command(tmp_path, monkeypatch):
      from whyline.console import adapters

      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(["model status", "/exit"]),
      )
      monkeypatch.setattr(
          adapters, "run_whyline_command",
          lambda argv: SessionEvent(kind="output", text=f"ran {argv}"),
      )
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("ran ['model', 'status']" in line for line in lines)


  def test_ctrl_c_during_dispatch_is_caught_and_the_session_continues(tmp_path, monkeypatch):
      from whyline.console import adapters

      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(["model status", "/exit"]),
      )

      def raising(argv):
          raise KeyboardInterrupt

      monkeypatch.setattr(adapters, "run_whyline_command", raising)
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("Cancelled" in line for line in lines)


  def test_model_slash_command_lists_available_agents(tmp_path, monkeypatch):
      from whyline import account

      monkeypatch.setattr(account, "available_agents", lambda root: {"claude", "codex"})
      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(["/model", "/exit"]),
      )
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("claude" in line and "codex" in line for line in lines)


  def test_model_slash_command_sets_the_active_agent(tmp_path, monkeypatch):
      from whyline import account

      monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(["/model claude", "/exit"]),
      )
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("claude is now the active chat agent" in line for line in lines)
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_repl.py -v`
  Expected: FAIL (`ModuleNotFoundError: No module named 'whyline.console.repl'`)

  Step 3: Implement `repl.py`

  Create `src/whyline/console/repl.py`:

  ```python
  """whyline console's REPL: ties the session, adapters, and editor together.

  The render loop below is the only place in this package that prints --
  every adapter returns a SessionEvent instead (see session.py).
  """

  from __future__ import annotations

  from pathlib import Path

  from whyline.console import adapters, editor
  from whyline.console.session import ConsoleSession, SessionEvent

  SLASH_COMMANDS = ("/model", "/route", "/status", "/stop", "/history", "/help", "/exit")

  _PREFIX = {"error": "⚠ ", "pause": "⏸ "}


  def _print_event(event: SessionEvent, print_fn) -> None:
      print_fn(f"{_PREFIX.get(event.kind, '')}{event.text}")


  def run(root: Path, *, print_fn=print) -> None:
      try:
          prompt_session = editor.build_session(root)
      except editor.EditorUnavailable as error:
          print_fn(str(error))
          return

      session = ConsoleSession(root=root)
      print_fn("whyline console -- /help for commands, /exit to quit.")
      while True:
          try:
              text = prompt_session.prompt(f"({session.mode}) > ")
          except (EOFError, KeyboardInterrupt):
              break
          text = text.strip()
          if not text:
              continue
          if text == "/exit":
              break
          if text == "/help":
              print_fn("Commands: " + ", ".join(SLASH_COMMANDS))
              continue
          if text == "/status":
              _print_event(session.record(adapters.run_status(session.root)), print_fn)
              continue
          if text == "/history":
              for event in session.transcript:
                  _print_event(event, print_fn)
              continue
          if text.startswith("/route"):
              parts = text.split(maxsplit=1)
              chosen = parts[1].strip() if len(parts) == 2 else ""
              if chosen in ("chat", "relay", "command"):
                  session.mode = chosen
                  print_fn(f"Mode is now {session.mode}.")
              else:
                  print_fn("Usage: /route <chat|relay|command>")
              continue
          if text.startswith("/model"):
              _handle_model(session, text, print_fn)
              continue
          if text == "/stop":
              print_fn("Nothing in flight to stop.")
              continue
          if text.startswith("/"):
              print_fn(f"Unknown command: {text}. Try {', '.join(SLASH_COMMANDS)}.")
              continue

          try:
              event = _dispatch(session, text)
          except KeyboardInterrupt:
              print_fn("Cancelled.")
              continue
          _print_event(session.record(event), print_fn)


  def _dispatch(session: ConsoleSession, text: str) -> SessionEvent:
      if session.mode == "command":
          return adapters.run_whyline_command(text.split())
      if session.mode == "chat":
          agent = session.agent or "claude"
          return adapters.run_chat_turn(session.root, agent=agent, prompt=text)
      # relay mode
      first = text.split(maxsplit=1)[0]
      if first == "doctor":
          return adapters.run_doctor(session.root)
      if first == "status":
          return adapters.run_status(session.root)
      if first in ("start", "resume"):
          return adapters.run_relay_oneshot(session.root, text.split())
      return SessionEvent(
          kind="error",
          text=f"Unknown relay command: {first!r}. Try doctor, status, start, resume.",
      )


  def _handle_model(session: ConsoleSession, text: str, print_fn) -> None:
      from whyline import account, model

      available = account.available_agents(session.root)
      if not available:
          print_fn("No agents detected as available. Run: whyline account detect")
          return
      parts = text.split(maxsplit=2)
      if len(parts) == 1:
          print_fn("Available: " + ", ".join(sorted(available)))
          return
      agent = parts[1]
      if agent not in available:
          print_fn(
              f"{agent} is not available here. Available: {', '.join(sorted(available))}"
          )
          return
      if len(parts) == 3:
          model.set_one(session.root, agent, parts[2])
          session.agent = agent
          print_fn(f"{agent} model set; now the active chat agent.")
      else:
          session.agent = agent
          print_fn(f"{agent} is now the active chat agent.")
  ```

  Step 4: Run the `repl.py` tests to verify they pass

  Run: `uv run pytest tests/console/test_repl.py -v`
  Expected: PASS

  Step 5: Wire `whyline console` into `cli.py`

  In `src/whyline/cli.py`, add a parser function next to `_add_model`:

  ```python
  def _add_console(subparsers: "argparse._SubParsersAction") -> None:
      subparsers.add_parser(
          "console", help="An editable multiline console for whyline and whyline-relay"
      )
  ```

  Add a command function next to `cmd_model`:

  ```python
  def cmd_console(args: argparse.Namespace) -> int:
      from whyline.console import repl

      root = _require_repo()
      repl.run(root)
      return EXIT_OK
  ```

  Register it in `COMMANDS`:

  ```python
  COMMANDS = {
      ...
      "account": cmd_account,
      "model": cmd_model,
      "console": cmd_console,
  }
  ```

  And call `_add_console(subparsers)` alongside the other `_add_*(subparsers)`
  calls inside `build_parser()` -- find where `_add_model(subparsers)` (or
  similar) is called and add the new line right after it.

  Step 6: Write and run the CLI wiring test

  Create `tests/test_cli_console.py`:

  ```python
  import os

  from whyline import cli
  from whyline.console import editor


  class _ImmediateExit:
      def prompt(self, message=""):
          raise EOFError


  def test_console_subcommand_runs_the_repl(repo, monkeypatch, capsys):
      monkeypatch.setattr(editor, "build_session", lambda root: _ImmediateExit())
      previous = os.getcwd()
      os.chdir(repo.path)
      try:
          code = cli.main(["console"])
      finally:
          os.chdir(previous)
      assert code == cli.EXIT_OK
      assert "whyline console" in capsys.readouterr().out
  ```

  Run: `uv run pytest tests/test_cli_console.py -v`
  Expected: PASS

  Step 7: Write and run the end-to-end test

  Create, in `tests/console/test_repl.py` (append to the file from Step 1):

  ```python
  def test_end_to_end_model_route_relay_doctor_and_chat(tmp_path, monkeypatch):
      """Exercises /model, /route relay -> doctor, /route chat -> a turn,
      /exit -- confirming the console layer disturbs no relay/chat state of
      its own (spec's own end-to-end bar)."""
      from whyline import account
      from whyline.console import adapters

      monkeypatch.setattr(account, "available_agents", lambda root: {"claude"})
      monkeypatch.setattr(
          adapters, "run_doctor",
          lambda root: SessionEvent(kind="output", text="All checks passed."),
      )
      monkeypatch.setattr(
          adapters, "run_chat_turn",
          lambda root, *, agent, prompt: SessionEvent(
              kind="output", text=f"[{agent}] response to {prompt!r}"
          ),
      )
      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(
              ["/model claude", "/route relay", "doctor", "/route chat", "hello", "/exit"]
          ),
      )
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("claude is now the active chat agent" in line for line in lines)
      assert any("Mode is now relay" in line for line in lines)
      assert any("All checks passed" in line for line in lines)
      assert any("Mode is now chat" in line for line in lines)
      assert any("response to 'hello'" in line for line in lines)
  ```

  Run: `uv run pytest tests/console/test_repl.py -v`
  Expected: PASS

  Step 8: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 9: Commit

  ```bash
  git add src/whyline/console/repl.py src/whyline/cli.py tests/console/test_repl.py tests/test_cli_console.py
  git commit -m "feat: whyline console REPL, CLI wiring, and end-to-end coverage"
  ```

  ---
