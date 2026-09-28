- [x] RLV-1: Structured pause rendering + failure classification

  ## Global Constraints

  - No new runtime dependency.
  - No changes to whyline-relay's own repository -- this plan only changes how `whyline`'s console adapters consume its already-structured, already-released functions (`state.load`, `handoff.read`).
  - `run_relay_oneshot`'s `output`/`error` classification is untouched -- only its `pause` case changes.
  - `failure_kind`'s phrase matches are anchored to this project's own existing, stable pause-message wording (`failover.REASON_TEXT`'s phrases, "exited without handing off", "hit the ... round cap", "reported blocked:") -- never new invented patterns.
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/adapters.py`
  - Test: `tests/console/test_adapters_relay_oneshot.py`, `tests/console/test_adapters_relay_structured.py`

  **Interfaces:**
  - Produces: `failure_kind(reason: str) -> str` -- one of `"rate-limit"`, `"auth"`, `"no-handoff"`, `"round-cap"`, `"blocked"`, `"other"`. `run_relay_oneshot`'s pause case now renders `"[<kind>] Task <id>\nReason <reason>\nLog <path>\nResume: whyline-relay resume"` built from `state.load(root)`, falling back to the raw captured text if `state.load` returns `None` at that moment.

  Step 1: Write the failing tests

  Add to `tests/console/test_adapters_relay_structured.py` (it already imports
  `from whyline.console import adapters`):

  ```python
  def test_failure_kind_classifies_rate_limit():
      assert adapters.failure_kind("codex hit a usage or rate limit; try again when it resets") == "rate-limit"


  def test_failure_kind_classifies_auth():
      assert adapters.failure_kind("codex is no longer logged in; try again once you've signed back in") == "auth"


  def test_failure_kind_classifies_no_handoff():
      assert adapters.failure_kind("grok exited without handing off; nothing was routed") == "no-handoff"


  def test_failure_kind_classifies_round_cap():
      assert adapters.failure_kind("T-1 hit the 3-round cap without an approval") == "round-cap"


  def test_failure_kind_classifies_blocked():
      assert adapters.failure_kind("codex reported blocked: needs clarification") == "blocked"


  def test_failure_kind_falls_back_to_other():
      assert adapters.failure_kind("something entirely unrecognized happened") == "other"
  ```

  Add to `tests/console/test_adapters_relay_oneshot.py`:

  ```python
  def test_run_relay_oneshot_pause_uses_structured_state_not_raw_text(
      monkeypatch, tmp_path
  ):
      from whyline_relay import cli as relay_cli, state

      state.save(
          tmp_path,
          state.RelayState(
              plan="plan.md", branch="relay/plan", task_id="T-1", round=2,
              base_commit="abc123",
              paused_reason="codex hit a usage or rate limit; try again when it resets",
              log_path="/tmp/T-1-2-codex.log",
          ),
      )

      def fake_main(argv, prog="whyline-relay"):
          print("Paused: codex hit a usage or rate limit; try again when it resets")
          return 1

      monkeypatch.setattr(relay_cli, "main", fake_main)
      event = adapters.run_relay_oneshot(tmp_path, ["resume"])
      assert event.kind == "pause"
      assert "[rate-limit]" in event.text
      assert "T-1" in event.text
      assert "/tmp/T-1-2-codex.log" in event.text
      assert "whyline-relay resume" in event.text


  def test_run_relay_oneshot_pause_falls_back_to_raw_text_with_no_saved_state(
      monkeypatch, tmp_path
  ):
      from whyline_relay import cli as relay_cli

      def fake_main(argv, prog="whyline-relay"):
          print("Paused: something odd, no state file exists for this")
          return 1

      monkeypatch.setattr(relay_cli, "main", fake_main)
      event = adapters.run_relay_oneshot(tmp_path, ["resume"])
      assert event.kind == "pause"
      assert "something odd, no state file exists for this" in event.text
  ```

  Check `whyline_relay.state.save`'s exact signature against the real module
  (`src/whyline_relay/state.py` in the whyline-relay repo) before trusting
  the call above verbatim -- confirm the field names match `RelayState`'s
  current dataclass definition.

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_adapters_relay_structured.py tests/console/test_adapters_relay_oneshot.py -v`
  Expected: FAIL (`AttributeError: module 'adapters' has no attribute
  'failure_kind'`; the pause case still returns raw text)

  Step 3: Implement

  In `src/whyline/console/adapters.py`, add near the top (after the existing
  imports):

  ```python
  _FAILURE_PHRASES = (
      ("rate-limit", "hit a usage or rate limit"),
      ("auth", "is no longer logged in"),
      ("no-handoff", "exited without handing off"),
      ("round-cap", "round cap"),
      ("blocked", "reported blocked:"),
  )


  def failure_kind(reason: str) -> str:
      """Classifies a pause's reason text into a coarse kind, using this
      project's own stable, existing pause-message phrasing -- never a new
      invented pattern."""
      for kind, phrase in _FAILURE_PHRASES:
          if phrase in reason:
              return kind
      return "other"
  ```

  Then replace `run_relay_oneshot`'s pause branch. Find:

  ```python
      if _PAUSE_PATTERN.search(text):
          kind = "pause"
      elif _COMPLETE_PATTERN.search(text) or code == 0:
          kind = "output"
      else:
          kind = "error"
      return SessionEvent(kind=kind, text=text)
  ```

  Replace with:

  ```python
      if _PAUSE_PATTERN.search(text):
          from whyline_relay import state as relay_state

          saved = relay_state.load(root)
          if saved is not None:
              kind_label = failure_kind(saved.paused_reason)
              structured = (
                  f"[{kind_label}] Task {saved.task_id}\n"
                  f"Reason {saved.paused_reason}\n"
                  f"Log {saved.log_path}\n"
                  "Resume: whyline-relay resume"
              )
              return SessionEvent(kind="pause", text=structured)
          return SessionEvent(kind="pause", text=text)
      if _COMPLETE_PATTERN.search(text) or code == 0:
          kind = "output"
      else:
          kind = "error"
      return SessionEvent(kind=kind, text=text)
  ```

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_adapters_relay_structured.py tests/console/test_adapters_relay_oneshot.py -v`
  Expected: PASS

  Step 5: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 6: Commit

  ```bash
  git add src/whyline/console/adapters.py tests/console/test_adapters_relay_structured.py tests/console/test_adapters_relay_oneshot.py
  git commit -m "feat: structured pause rendering with failure-kind classification"
  ```

  ---

- [x] RLV-2: `/handoff` command showing the last handoff record

  ## Global Constraints

  - No new runtime dependency.
  - No changes to whyline-relay's own repository -- this plan only changes how `whyline`'s console adapters consume its already-structured, already-released functions (`state.load`, `handoff.read`).
  - `run_relay_oneshot`'s `output`/`error` classification is untouched -- only its `pause` case changes.
  - `failure_kind`'s phrase matches are anchored to this project's own existing, stable pause-message wording (`failover.REASON_TEXT`'s phrases, "exited without handing off", "hit the ... round cap", "reported blocked:") -- never new invented patterns.
  - Every existing test in this repo must still pass after every task.

  **Note on this pairing:** Antigravity implements, Codex reviews.

  **Files:**
  - Modify: `src/whyline/console/adapters.py`, `src/whyline/console/repl.py`
  - Test: `tests/console/test_adapters_relay_structured.py`, `tests/console/test_repl.py`

  **Interfaces:**
  - Consumes: `whyline_relay.handoff.read` (unchanged).
  - Produces: `run_last_handoff(root) -> SessionEvent`. `/handoff` added to `repl.py`'s `SLASH_COMMANDS` and dispatch.

  Step 1: Write the failing tests

  Add to `tests/console/test_adapters_relay_structured.py`:

  ```python
  def _write_handoff(root, **fields):
      import json

      target = root / ".whyline"
      target.mkdir(parents=True, exist_ok=True)
      record = {
          "v": 1, "id": "abc123", "type": "Handoff",
          "task": "T-1", "from_actor": "codex", "to_actor": "claude",
          "status": "ready-for-review", "summary": "Implemented the cache",
          **fields,
      }
      (target / "active-handoff.json").write_text(json.dumps(record))


  def test_run_last_handoff_renders_the_current_record(tmp_path):
      _write_handoff(tmp_path)
      event = adapters.run_last_handoff(tmp_path)
      assert event.kind == "output"
      assert "T-1" in event.text
      assert "codex" in event.text and "claude" in event.text
      assert "ready-for-review" in event.text
      assert "Implemented the cache" in event.text


  def test_run_last_handoff_shows_questions_when_blocked(tmp_path):
      _write_handoff(
          tmp_path, status="blocked", questions=["Which cache?", "Run tests?"]
      )
      event = adapters.run_last_handoff(tmp_path)
      assert "Which cache?" in event.text
      assert "Run tests?" in event.text


  def test_run_last_handoff_with_nothing_recorded_says_so(tmp_path):
      event = adapters.run_last_handoff(tmp_path)
      assert event.kind == "output"
      assert "No handoff recorded yet" in event.text
  ```

  Add to `tests/console/test_repl.py`:

  ```python
  def test_handoff_slash_command_dispatches_to_run_last_handoff(tmp_path, monkeypatch):
      from whyline.console import adapters

      monkeypatch.setattr(
          editor, "build_session",
          lambda root: FakePromptSession(["/handoff", "/exit"]),
      )
      monkeypatch.setattr(
          adapters, "run_last_handoff",
          lambda root: SessionEvent(kind="output", text="the last handoff"),
      )
      lines = []
      repl.run(tmp_path, print_fn=lines.append)
      assert any("the last handoff" in line for line in lines)
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_adapters_relay_structured.py tests/console/test_repl.py -v`
  Expected: FAIL (`AttributeError: module 'adapters' has no attribute
  'run_last_handoff'`; `/handoff` not recognized in `repl.py`)

  Step 3: Implement

  Add to `src/whyline/console/adapters.py`:

  ```python
  def run_last_handoff(root: Path) -> SessionEvent:
      """Renders whyline-relay's current handoff record directly -- already
      exactly the structured function needed, no new parsing."""
      from whyline_relay import handoff as relay_handoff

      record = relay_handoff.read(root)
      if record is None:
          return SessionEvent(kind="output", text="No handoff recorded yet.")
      lines = [
          f"{record.task}: {record.from_actor} -> {record.to_actor} "
          f"({record.status})",
          record.summary,
      ]
      for question in record.questions:
          lines.append(f"Question: {question}")
      return SessionEvent(kind="output", text="\n".join(lines))
  ```

  In `src/whyline/console/repl.py`, update `SLASH_COMMANDS`:

  ```python
  SLASH_COMMANDS = (
      "/model", "/route", "/status", "/handoff", "/stop", "/history", "/help", "/exit",
  )
  ```

  and add a branch right after the existing `if text == "/status":` block:

  ```python
          if text == "/handoff":
              _print_event(session.record(adapters.run_last_handoff(session.root)), print_fn)
              continue
  ```

  Step 4: Run the tests to verify they pass

  Run: `uv run pytest tests/console/test_adapters_relay_structured.py tests/console/test_repl.py -v`
  Expected: PASS

  Step 5: Run the whole suite

  Run: `uv run pytest -q`
  Expected: PASS

  Step 6: Commit

  ```bash
  git add src/whyline/console/adapters.py src/whyline/console/repl.py tests/console/test_adapters_relay_structured.py tests/console/test_repl.py
  git commit -m "feat: /handoff shows the current handoff record"
  ```

  ---
