- [x] CRS-5: Require relay 0.2.26 and add `relay_ops.py`

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Modify: `pyproject.toml` (both `whyline-relay>=0.2.25,<0.3` → `whyline-relay>=0.2.26,<0.3`), `uv.lock`
  - Modify: `src/whyline/console/adapters.py` (extract `classify_relay_output`)
  - Create: `src/whyline/console/relay_ops.py`
  - Test: `tests/console/test_relay_ops.py` (create)

  **Interfaces:**
  - Consumes: relay 0.2.26 functions from Tasks 1–3; `whyline_relay.brainstorm.generate_plan_from_synthesis(root, settings, final_agent, models, topic, *, feedback=None, timeout_seconds=None) -> Path`; `whyline_relay.preflight.run(root) -> list[Check(status, message, hint)]`; `whyline_relay.running.live(root) -> Running | None` (fields `task`, `agent`, `role`); `adapters.BRAINSTORM_LABELS`.
  - Produces (all in `whyline.console.relay_ops`):
    - `@dataclass(frozen=True) class Draft: path: Path; text: str; drafted_by: str; source: str; topic: str = ""; agent: str = ""` — `source` is `"planner"` or `"brainstorm"`.
    - `@dataclass(frozen=True) class CheckLine: status: str; message: str; hint: str | None = None`
    - `validate_plan(text: str) -> list[str]`
    - `save_pasted_plan(root: Path, text: str, *, replace: bool = False) -> Path`
    - `missing_references(root: Path, refs: list[str]) -> list[str]`
    - `draft_description(description: str, refs: list[str]) -> str`
    - `draft_plan(root, description, refs, *, progress) -> Draft`
    - `pending_draft(root) -> str | None`
    - `resume_draft(root, *, progress) -> Draft`
    - `discard_draft(root, draft: Draft | None) -> None`
    - `revise_plan(root, draft: Draft, feedback: str, *, progress) -> Draft`
    - `approve_plan(root, draft: Draft, *, replace: bool = False) -> Path`
    - `brainstorm_docs(root) -> list[str]` — file stems, sorted.
    - `plan_from_brainstorm(root, topic: str, agent: str, *, progress, timeout_minutes: int | None = None) -> Draft`
    - `relay_agents() -> list[str]`
    - `current_roles(root) -> dict` — keys `implementer`, `tester`, `reviewer` (str) and `backup` (list[str]).
    - `save_roles(root, implementer, tester, reviewer, backup: list[str]) -> None`
    - `run_checks(root) -> list[CheckLine]`
    - `live_run(root) -> str | None` — e.g. `"T3, codex"`.
    - `paused_run(root) -> bool`
    - Re-exported exceptions: `PlanExists`, `PlanAlreadyInProgress` (from `whyline_relay.planner`) via `relay_ops.plan_exists_error()` / `relay_ops.in_progress_error()` returning the classes.
    - In `adapters.py`: `classify_relay_output(root: Path | str, text: str, code: int) -> SessionEvent`.

  Step 1: Bump the dependency

  ```bash
  sed -i '' 's/whyline-relay>=0.2.25,<0.3/whyline-relay>=0.2.26,<0.3/g' pyproject.toml
  uv lock --upgrade-package whyline-relay
  uv sync
  uv run python -c "import whyline_relay; print(whyline_relay.__version__)"
  ```

  Expected: `0.2.26`.

  Step 2: Write the failing tests

  Create `tests/console/test_relay_ops.py`:

  ```python
  import subprocess
  from pathlib import Path

  import pytest

  from whyline.console import adapters, relay_ops


  def _git(root: Path, *args: str) -> str:
      return subprocess.run(["git", *args], cwd=root, check=True,
                            capture_output=True, text=True).stdout


  @pytest.fixture
  def repo(tmp_path: Path) -> Path:
      _git(tmp_path, "init", "-q", "-b", "main")
      _git(tmp_path, "config", "user.email", "t@example.com")
      _git(tmp_path, "config", "user.name", "T")
      (tmp_path / "README.md").write_text("x\n")
      _git(tmp_path, "add", "-A")
      _git(tmp_path, "commit", "-qm", "initial")
      return tmp_path


  def test_save_pasted_plan_commits_plan_md(repo):
      path = relay_ops.save_pasted_plan(repo, "- [ ] T-1: build it")
      assert path == repo / "plan.md"
      assert path.read_text() == "- [ ] T-1: build it\n"
      assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["plan.md"]
      assert not (repo / ".whyline" / "relay" / "pasted-plan.md").exists()


  def test_save_pasted_plan_rejects_prose(repo):
      with pytest.raises(ValueError, match="no tasks"):
          relay_ops.save_pasted_plan(repo, "just words")


  def test_save_pasted_plan_asks_before_replacing(repo):
      (repo / "plan.md").write_text("- [ ] OLD-1: old\n")
      with pytest.raises(relay_ops.plan_exists_error()):
          relay_ops.save_pasted_plan(repo, "- [ ] T-1: new\n")
      relay_ops.save_pasted_plan(repo, "- [ ] T-1: new\n", replace=True)
      assert (repo / "plan.md").read_text() == "- [ ] T-1: new\n"


  def test_missing_references_resolves_home_relative_and_spaces(repo, monkeypatch, tmp_path_factory):
      home = tmp_path_factory.mktemp("home")
      monkeypatch.setenv("HOME", str(home))
      monkeypatch.setenv("USERPROFILE", str(home))  # what expanduser reads on Windows
      (home / "PRD one.md").write_text("x")
      (repo / "docs").mkdir()
      (repo / "docs" / "brief.md").write_text("x")
      absolute = repo / "README.md"
      refs = ["~/PRD one.md", "docs/brief.md", str(absolute), "docs/nope.md"]
      assert relay_ops.missing_references(repo, refs) == ["docs/nope.md"]


  def test_draft_description_lists_the_references():
      text = relay_ops.draft_description("Build the PRD", ["PRD.md", "docs/b.md"])
      assert text == (
          "Build the PRD\n\nRead these reference documents before planning:\n"
          "- PRD.md\n- docs/b.md"
      )
      assert relay_ops.draft_description("Build it", []) == "Build it"


  def test_brainstorm_docs_lists_stems(repo):
      folder = repo / "docs" / "brainstorm"
      folder.mkdir(parents=True)
      (folder / "b-topic.md").write_text("x")
      (folder / "a-topic.md").write_text("x")
      (folder / "notes.txt").write_text("x")
      assert relay_ops.brainstorm_docs(repo) == ["a-topic", "b-topic"]
      assert relay_ops.brainstorm_docs(repo / "missing") == []


  def test_current_roles_defaults_then_reads_config(repo):
      assert relay_ops.current_roles(repo) == {
          "implementer": "codex", "tester": "claude", "reviewer": "claude", "backup": [],
      }
      relay_ops.save_roles(repo, "claude", "codex", "codex", ["claude"])
      assert relay_ops.current_roles(repo) == {
          "implementer": "claude", "tester": "codex", "reviewer": "codex", "backup": ["claude"],
      }


  def test_relay_agents_are_the_relay_builtins():
      from whyline_relay import adapters as relay_adapters
      assert relay_ops.relay_agents() == sorted(relay_adapters.BUILTIN)


  def test_run_checks_returns_plain_lines(repo, monkeypatch):
      from whyline_relay import preflight
      monkeypatch.setattr(preflight, "run", lambda root: [
          preflight.Check("ok", "fine"), preflight.Check("FAIL", "bad", "fix it"),
      ])
      assert relay_ops.run_checks(repo) == [
          relay_ops.CheckLine("ok", "fine", None), relay_ops.CheckLine("FAIL", "bad", "fix it"),
      ]


  def test_live_run_names_the_task_and_agent(repo, monkeypatch):
      from whyline_relay import running
      monkeypatch.setattr(running, "live", lambda root: running.Running(
          agent="codex", task="T3", round=1, started="2026-09-30T10:00:00", pid=1, role="implementer"))
      assert relay_ops.live_run(repo) == "T3, codex"
      monkeypatch.setattr(running, "live", lambda root: None)
      assert relay_ops.live_run(repo) is None


  def test_classify_relay_output_keeps_run_relay_oneshot_behaviour(tmp_path):
      assert adapters.classify_relay_output(tmp_path, "Plan complete: 2 task(s)\n", 0).kind == "output"
      assert adapters.classify_relay_output(tmp_path, "boom\n", 2).kind == "error"
  ```

  Step 3: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_relay_ops.py -q`
  Expected: FAIL with `ImportError: cannot import name 'relay_ops'`.

  Step 4: Extract `classify_relay_output` in `src/whyline/console/adapters.py`

  In `run_relay_oneshot`, replace everything from `text = buf.getvalue()` to the end of the function with:

  ```python
      return classify_relay_output(root, buf.getvalue(), code)


  def classify_relay_output(root: Path | str, text: str, code: int) -> SessionEvent:
      """Turns a finished relay run's output into one event: a structured
      pause, a completion, or an error. Shared by the in-process one-shot and
      the console's streamed relay process."""
      if _PAUSE_PATTERN.search(text):
          from whyline_relay import state as relay_state

          saved = relay_state.load(Path(root))
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

  Step 5: Create `src/whyline/console/relay_ops.py`

  ```python
  """The console's calls into whyline-relay for planning and setup. Every
  function returns plain data or raises; the Plan and Set up popups own all
  presentation. whyline_relay is imported inside each function, like
  adapters.py does, so the console imports without it."""

  from __future__ import annotations

  import tomllib
  from dataclasses import dataclass, replace as dc_replace
  from pathlib import Path

  from whyline.console.adapters import BRAINSTORM_LABELS

  _DEFAULT_ROLES = {"implementer": "codex", "tester": "claude", "reviewer": "claude"}


  @dataclass(frozen=True)
  class Draft:
      path: Path
      text: str
      drafted_by: str
      source: str  # "planner" | "brainstorm"
      topic: str = ""
      agent: str = ""


  @dataclass(frozen=True)
  class CheckLine:
      status: str
      message: str
      hint: str | None = None


  def _settings(root: Path):
      from whyline_relay import config

      return config.load(root)


  def plan_exists_error():
      from whyline_relay import planner

      return planner.PlanExists


  def in_progress_error():
      from whyline_relay import planner

      return planner.PlanAlreadyInProgress


  def validate_plan(text: str) -> list[str]:
      from whyline_relay import planner

      return planner.validate(text)


  def save_pasted_plan(root: Path, text: str, *, replace: bool = False) -> Path:
      from whyline_relay import config, planner

      problems = planner.validate(text)
      if problems:
          raise ValueError("\n".join(problems))
      source = config.relay_dir(root) / "pasted-plan.md"
      source.parent.mkdir(parents=True, exist_ok=True)
      source.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
      try:
          return planner.approve(
              root, _settings(root), source, drafted_by="hand", replace=replace
          )
      finally:
          source.unlink(missing_ok=True)


  def missing_references(root: Path, refs: list[str]) -> list[str]:
      missing = []
      for ref in refs:
          path = Path(ref).expanduser()
          if not path.is_absolute():
              path = root / path
          if not path.exists():
              missing.append(ref)
      return missing


  def draft_description(description: str, refs: list[str]) -> str:
      if not refs:
          return description
      listed = "\n".join(f"- {ref}" for ref in refs)
      return (
          f"{description}\n\nRead these reference documents before planning:\n{listed}"
      )


  def _planner_draft(root: Path, path: Path) -> Draft:
      return Draft(
          path=path,
          text=path.read_text(encoding="utf-8"),
          drafted_by=_settings(root).planner.draft,
          source="planner",
      )


  def draft_plan(root: Path, description: str, refs: list[str], *, progress) -> Draft:
      from whyline_relay import planner

      path = planner.draft(
          root, _settings(root), draft_description(description, refs), print_fn=progress
      )
      return _planner_draft(root, path)


  def pending_draft(root: Path) -> str | None:
      from whyline_relay import planner

      return planner.pending_description(root)


  def resume_draft(root: Path, *, progress) -> Draft:
      from whyline_relay import planner

      return _planner_draft(root, planner.resume_draft(root, _settings(root), print_fn=progress))


  def discard_draft(root: Path, draft: Draft | None) -> None:
      """Drops the planner's checkpoint; a brainstorm draft has none. The draft
      file itself stays on disk either way."""
      from whyline_relay import planner

      if draft is None or draft.source == "planner":
          planner.discard(root)


  def _models(agent: str) -> list[tuple[str, str]]:
      return [(agent, BRAINSTORM_LABELS[agent])]


  def revise_plan(root: Path, draft: Draft, feedback: str, *, progress) -> Draft:
      from whyline_relay import brainstorm, planner

      settings = _settings(root)
      if draft.source == "planner":
          planner.revise(root, settings, feedback, print_fn=progress)
      else:
          progress(f"{BRAINSTORM_LABELS[draft.agent]} is revising the plan")
          brainstorm.generate_plan_from_synthesis(
              root, settings, draft.agent, _models(draft.agent), draft.topic,
              feedback=feedback,
          )
      return dc_replace(draft, text=draft.path.read_text(encoding="utf-8"))


  def approve_plan(root: Path, draft: Draft, *, replace: bool = False) -> Path:
      from whyline_relay import planner

      return planner.approve(
          root, _settings(root), draft.path, drafted_by=draft.drafted_by,
          replace=replace, clear_checkpoint=draft.source == "planner",
      )


  def brainstorm_docs(root: Path) -> list[str]:
      folder = root / "docs" / "brainstorm"
      if not folder.is_dir():
          return []
      return sorted(path.stem for path in folder.glob("*.md"))


  def plan_from_brainstorm(
      root: Path, topic: str, agent: str, *, progress, timeout_minutes: int | None = None
  ) -> Draft:
      from whyline_relay import brainstorm

      progress(f"{BRAINSTORM_LABELS[agent]} is turning the brainstorm into a plan")
      kwargs = {"timeout_seconds": timeout_minutes * 60} if timeout_minutes else {}
      path = brainstorm.generate_plan_from_synthesis(
          root, _settings(root), agent, _models(agent), topic, **kwargs
      )
      return Draft(
          path=path,
          text=path.read_text(encoding="utf-8"),
          drafted_by=f"brainstorm ({agent})",
          source="brainstorm",
          topic=topic,
          agent=agent,
      )


  def relay_agents() -> list[str]:
      from whyline_relay import adapters as relay_adapters

      return sorted(relay_adapters.BUILTIN)


  def current_roles(root: Path) -> dict:
      from whyline_relay import config

      agents = relay_agents()
      roles = dict(_DEFAULT_ROLES)
      backup: list[str] = []
      path = config.config_path(root)
      if path.exists():
          try:
              raw = tomllib.loads(path.read_text(encoding="utf-8"))
          except (tomllib.TOMLDecodeError, OSError):
              raw = {}
          for key in roles:
              value = (raw.get("roles") or {}).get(key)
              if value in agents:
                  roles[key] = value
          backup = [
              name for name in (raw.get("backup") or {}).get("chain", []) if name in agents
          ]
      return {**roles, "backup": backup}


  def save_roles(
      root: Path, implementer: str, tester: str, reviewer: str, backup: list[str]
  ) -> None:
      from whyline_relay import setup

      setup.write_roles(root, implementer, tester, reviewer, backup)


  def run_checks(root: Path) -> list[CheckLine]:
      from whyline_relay import preflight

      return [CheckLine(c.status, c.message, c.hint) for c in preflight.run(root)]


  def live_run(root: Path) -> str | None:
      from whyline_relay import running

      active = running.live(root)
      return None if active is None else f"{active.task}, {active.agent}"


  def paused_run(root: Path) -> bool:
      from whyline_relay import state

      return state.load(root) is not None
  ```

  Step 6: Run the tests

  Run: `uv run pytest tests/console -q`
  Expected: all PASS (including the existing `test_adapters_relay_*.py`, which cover `run_relay_oneshot` through the extracted function).

  Step 7: Commit

  ```bash
  git add pyproject.toml uv.lock src/whyline/console/adapters.py src/whyline/console/relay_ops.py tests/console/test_relay_ops.py
  git commit -m "feat(console): relay_ops for planning and setup; require whyline-relay 0.2.26"
  ```

- [x] CRS-6: Relay-mode buttons, and Relay mode stays in the console

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Modify: `src/whyline/console/tui.py` (`compose`, `_sync_mode_indicator`, `on_button_pressed`, `_handle_slash`)
  - Modify: `src/whyline/console/repl.py` (`_HELP_TEXT` Relay line only)
  - Test: `tests/console/test_tui.py` (replace the two `..._defers_exec_until_after_exit` tests; add new ones)

  **Interfaces:**
  - Consumes: `relay_ops.paused_run(root)`, `repl._is_home`, `repl._HOME_REFUSAL`.
  - Produces: bottom-bar buttons `#relay-plan`, `#relay-setup`, `#relay-resume`; `WhylineConsoleApp._sync_relay_buttons() -> None`; `WhylineConsoleApp._open_relay_plan() -> None` and `_open_relay_setup() -> None` (stubs in this task that render `"Plan: coming in the next task."` — replaced in Tasks 9 and 11); `_relay: RelayProcess | None` attribute initialised to `None` (used from Task 8).

  Step 1: Write the failing tests

  In `tests/console/test_tui.py`, delete `test_route_relay_with_no_config_defers_exec_until_after_exit` and `test_typing_route_relay_with_no_config_defers_exec_until_after_exit`, and add:

  ```python
  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_relay_mode_without_config_stays_in_the_console(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await pilot.click("#mode-relay")
          await pilot.pause()
          assert app._exec_after is None
          assert app.session.mode == "relay"
          lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
          assert any("use Plan, then Set up" in line for line in lines)


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_plan_and_setup_are_only_enabled_in_relay_mode(tmp_path, monkeypatch):
      from whyline.console import relay_ops

      monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          for button_id in ("relay-plan", "relay-setup", "relay-resume"):
              assert app.query_one(f"#{button_id}", tui.Button).disabled
          await pilot.click("#mode-relay")
          await pilot.pause()
          assert not app.query_one("#relay-plan", tui.Button).disabled
          assert not app.query_one("#relay-setup", tui.Button).disabled
          assert app.query_one("#relay-resume", tui.Button).disabled  # nothing paused
          await pilot.click("#mode-chat")
          await pilot.pause()
          assert app.query_one("#relay-plan", tui.Button).disabled


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_resume_is_enabled_when_a_run_is_paused(tmp_path, monkeypatch):
      from whyline.console import relay_ops

      monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await pilot.click("#mode-relay")
          await pilot.pause()
          assert not app.query_one("#relay-resume", tui.Button).disabled


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_all_bottom_buttons_fit_in_80_columns(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(80, 24)):
          for button in app.query("#controls Button"):
              assert button.region.right <= 80, button.id


  @pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed -- skip the real smoke test")
  @pytest.mark.asyncio
  async def test_plan_refuses_in_the_home_repo(tmp_path, monkeypatch):
      monkeypatch.setattr(tui.Path, "home", classmethod(lambda cls: tmp_path))
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          app.session.mode = "relay"
          app._sync_mode_indicator()
          await pilot.click("#relay-plan")
          await pilot.pause()
          lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
          # "Not running agents here" is the refusal itself; the startup warning
          # also mentions the home directory, so it can't be the check.
          assert any("Not running agents here" in line for line in lines)
  ```

  Also add `"relay-plan", "relay-setup", "relay-resume"` to the tuple in `test_app_composes_header_transcript_prompt_and_controls`.

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_tui.py -q`
  Expected: the new tests FAIL (`NoMatches` for `#relay-plan`, and `_exec_after` is set).

  Step 3: Implement in `src/whyline/console/tui.py`

  Add to the imports from `whyline.console.repl`: `_HOME_REFUSAL`, `_is_home`. Add `from whyline.console import relay_ops` next to `from whyline.console import adapters`.

  In `__init__`, add after `self._spin = 0`:

  ```python
          self._relay = None  # the RelayProcess started by Start/Resume, if any
  ```

  In `compose`, change the controls row to:

  ```python
          yield Horizontal(
              Button("Model", id="model"),
              Button("Brainstorm", id="brainstorm"),
              Button("History", id="history"),
              Button("Stop", id="stop", disabled=True),
              Button("Help", id="help"),
              Button("Copy", id="copy"),
              Button("Plan", id="relay-plan", disabled=True),
              Button("Set up", id="relay-setup", disabled=True),
              Button("Resume", id="relay-resume", disabled=True),
              id="controls",
          )
  ```

  At the end of `_sync_mode_indicator`, add `self._sync_relay_buttons()`, and add the method:

  ```python
      def _sync_relay_buttons(self) -> None:
          """Plan and Set up only make sense in Relay mode; Resume only when a
          run is paused and nothing is running."""
          in_relay = self.session.mode == "relay"
          running = self._relay is not None and self._relay.running()
          self._main("#relay-plan", Button).disabled = not in_relay
          self._main("#relay-setup", Button).disabled = not in_relay or running
          try:
              paused = in_relay and relay_ops.paused_run(self.session.root)
          except Exception:  # no relay installed, unreadable state: not resumable
              paused = False
          self._main("#relay-resume", Button).disabled = not paused or running
  ```

  In `on_button_pressed`, before the final `elif button_id in (...)` branch, add:

  ```python
          elif button_id == "relay-plan":
              self._open_relay_plan()
          elif button_id == "relay-setup":
              self._open_relay_setup()
          elif button_id == "relay-resume":
              self._launch_relay(["resume"])
  ```

  In `_handle_slash`, replace the `needs_setup` branch:

  ```python
          if event.kind == "needs_setup":
              self._exec_after = RELAY_SETUP
              self.exit()
              return True
  ```

  with:

  ```python
          if event.kind == "needs_setup":
              # Setup happens here now (Plan, then Set up), not in the
              # terminal wizard, so the console stays open.
              self.session.mode = "relay"
              self.render_event(SessionEvent(
                  kind="output",
                  text="Mode is now relay. No relay setup here yet -- use Plan, then Set up.",
              ))
              self._sync_mode_indicator()
              return True
  ```

  Remove `RELAY_SETUP` from the `whyline.console.repl` import list if nothing else in `tui.py` uses it (the plain REPL keeps using it).

  Add the placeholder methods (Tasks 8, 9 and 11 replace their bodies):

  ```python
      def _refuse_in_home(self) -> bool:
          if _is_home(self.session.root):
              self.render_event(SessionEvent(kind="error", text=_HOME_REFUSAL))
              return True
          return False

      def _open_relay_plan(self) -> None:
          if self._refuse_in_home():
              return
          self.render_event(SessionEvent(kind="output", text="Plan: coming in the next task."))

      def _open_relay_setup(self) -> None:
          if self._refuse_in_home():
              return
          self.render_event(SessionEvent(kind="output", text="Set up: coming in a later task."))

      def _launch_relay(self, argv: list[str]) -> None:
          self.render_event(SessionEvent(kind="output", text="Relay runs: coming in a later task."))
  ```

  In `src/whyline/console/repl.py`, change the `_HELP_TEXT` line:

  ```python
          "  Relay    drive whyline-relay: doctor, status, start, resume",
  ```

  to:

  ```python
          "  Relay    Plan makes plan.md, Set up picks roles and starts; or type\n"
          "           doctor, status, start, resume",
  ```

  Step 4: Run the tests

  Run: `uv run pytest tests/console -q`
  Expected: all PASS. If `test_all_bottom_buttons_fit_in_80_columns` fails, add `#controls > Button { margin: 0; }` to `WhylineConsoleApp.DEFAULT_CSS` and re-run.

  Step 5: Commit

  ```bash
  git add src/whyline/console/tui.py src/whyline/console/repl.py tests/console/test_tui.py
  git commit -m "feat(console): Plan, Set up and Resume buttons in Relay mode"
  ```

- [ ] CRS-7: `RelayProcess` — run the relay as its own process and follow its log

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Create: `src/whyline/console/relay_process.py`
  - Test: `tests/console/test_relay_process.py` (create)

  **Interfaces:**
  - Consumes: nothing from earlier tasks (standalone).
  - Produces:
    - `log_path(root: Path) -> Path` — `root/.whyline/relay/logs/console-run.log`
    - `stop_path(root: Path) -> Path` — `root/.whyline/relay/STOP`
    - `relay_argv(args: list[str], root: Path) -> list[str]`
    - `class RelayProcess(root, args, *, on_line, on_exit, argv=None, poll=0.1)` with `.start() -> None`, `.running() -> bool`, `.request_stop() -> None`, `.stop_following() -> None`, `.wait(timeout: float | None = None) -> int`. `on_line(str)` gets each output line without its newline; `on_exit(code: int, text: str)` gets the exit code and the whole output, once, after the last line.

  Step 1: Write the failing tests

  Create `tests/console/test_relay_process.py`:

  ```python
  import sys
  import threading
  import time
  from pathlib import Path

  from whyline.console import relay_process

  SCRIPT = (
      "import sys, time\n"
      "for i in range(3):\n"
      "    print(f'line {i}', flush=True)\n"
      "    time.sleep(0.2)\n"
      "sys.stdout.write('no newline at the end')\n"
      "sys.exit(int(sys.argv[1]))\n"
  )


  def _run(tmp_path: Path, code: int = 0, follow: bool = True):
      lines, exits, done = [], [], threading.Event()

      def on_exit(exit_code, text):
          exits.append((exit_code, text))
          done.set()

      proc = relay_process.RelayProcess(
          tmp_path, ["start"], on_line=lines.append, on_exit=on_exit,
          argv=[sys.executable, "-c", SCRIPT, str(code)], poll=0.05,
      )
      proc.start()
      return proc, lines, exits, done


  def test_lines_stream_in_order_before_exit(tmp_path):
      proc, lines, exits, done = _run(tmp_path)
      deadline = time.monotonic() + 10
      while not lines and time.monotonic() < deadline:
          time.sleep(0.02)
      assert lines[0] == "line 0"
      assert proc.running()  # it arrived while the process was still going
      assert done.wait(10)
      assert lines == ["line 0", "line 1", "line 2", "no newline at the end"]
      assert exits[0][0] == 0
      assert "line 2" in exits[0][1]


  def test_nonzero_exit_is_reported(tmp_path):
      proc, lines, exits, done = _run(tmp_path, code=3)
      assert done.wait(10)
      assert exits[0][0] == 3


  def test_output_goes_to_the_log_file_not_a_pipe(tmp_path):
      proc, lines, exits, done = _run(tmp_path)
      assert done.wait(10)
      assert "line 1" in relay_process.log_path(tmp_path).read_text()


  def test_relay_keeps_running_after_the_console_stops_following(tmp_path):
      # The console quitting must not kill the relay (no broken pipe).
      proc, lines, exits, done = _run(tmp_path)
      proc.stop_following()
      assert proc.wait(10) == 0
      assert "no newline at the end" in relay_process.log_path(tmp_path).read_text()


  def test_request_stop_writes_the_stop_file(tmp_path):
      proc, lines, exits, done = _run(tmp_path)
      proc.request_stop()
      assert relay_process.stop_path(tmp_path).exists()
      assert done.wait(10)


  def test_relay_argv_runs_the_relay_cli_with_this_python(tmp_path):
      argv = relay_process.relay_argv(["start", "--only", "T3"], tmp_path)
      assert argv[0] == sys.executable
      assert argv[-5:] == ["start", "--only", "T3", "--repo", str(tmp_path)]
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_relay_process.py -q`
  Expected: FAIL with `ImportError: cannot import name 'relay_process'`.

  Step 3: Implement `src/whyline/console/relay_process.py`

  ```python
  """Runs `whyline relay start|resume` as its own process for the console.

  Output goes to a log file, not a pipe, and a thread follows that file: once
  the console quits there is no reader left, and a relay writing to a closed
  pipe would die of it. The process also gets its own session / process group,
  so closing the terminal doesn't take it down."""

  from __future__ import annotations

  import os
  import subprocess
  import sys
  import threading
  import time
  from pathlib import Path

  _RELAY_MAIN = (
      "import sys; from whyline_relay.cli import main; "
      "sys.exit(main(sys.argv[1:], prog='whyline relay'))"
  )


  def log_path(root: Path) -> Path:
      return root / ".whyline" / "relay" / "logs" / "console-run.log"


  def stop_path(root: Path) -> Path:
      return root / ".whyline" / "relay" / "STOP"


  def relay_argv(args: list[str], root: Path) -> list[str]:
      return [sys.executable, "-c", _RELAY_MAIN, *args, "--repo", str(root)]


  class RelayProcess:
      def __init__(self, root: Path, args: list[str], *, on_line, on_exit,
                   argv: list[str] | None = None, poll: float = 0.1) -> None:
          self.root = root
          self.args = args
          self._argv = argv if argv is not None else relay_argv(args, root)
          self._on_line = on_line
          self._on_exit = on_exit
          self._poll = poll
          self._proc: subprocess.Popen | None = None
          self._following = True

      def start(self) -> None:
          path = log_path(self.root)
          path.parent.mkdir(parents=True, exist_ok=True)
          env = {**os.environ, "PYTHONUNBUFFERED": "1"}
          if os.name == "nt":
              group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
          else:
              group = {"start_new_session": True}
          with path.open("w", encoding="utf-8") as log:
              self._proc = subprocess.Popen(
                  self._argv, cwd=self.root, stdout=log, stderr=subprocess.STDOUT,
                  stdin=subprocess.DEVNULL, env=env, **group,
              )
          threading.Thread(target=self._follow, args=(path,), daemon=True).start()

      def running(self) -> bool:
          return self._proc is not None and self._proc.poll() is None

      def wait(self, timeout: float | None = None) -> int:
          return self._proc.wait(timeout)

      def request_stop(self) -> None:
          """The relay checks for this file between agent turns: the current
          agent finishes, nothing new starts, and the run pauses cleanly."""
          target = stop_path(self.root)
          target.parent.mkdir(parents=True, exist_ok=True)
          target.write_text("", encoding="utf-8")

      def stop_following(self) -> None:
          """Stops reporting (the console is quitting); the relay keeps going."""
          self._following = False

      def _follow(self, path: Path) -> None:
          collected: list[str] = []
          pending = ""
          with path.open(encoding="utf-8", errors="replace") as reader:
              while self._following:
                  chunk = reader.readline()
                  if chunk:
                      pending += chunk
                      if pending.endswith("\n"):
                          line = pending.rstrip("\r\n")
                          collected.append(line)
                          self._on_line(line)
                          pending = ""
                      continue
                  if self._proc.poll() is not None:
                      rest = reader.read()
                      for line in (pending + rest).splitlines():
                          collected.append(line)
                          self._on_line(line)
                      self._on_exit(self._proc.returncode, "\n".join(collected) + "\n")
                      return
                  time.sleep(self._poll)
  ```

  Step 4: Run the tests

  Run: `uv run pytest tests/console/test_relay_process.py -q`
  Expected: all PASS.

  Step 5: Commit

  ```bash
  git add src/whyline/console/relay_process.py tests/console/test_relay_process.py
  git commit -m "feat(console): run the relay as its own process and follow its log"
  ```

- [ ] CRS-8: Start, Resume, Stop and quit with a running relay

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Modify: `src/whyline/console/tui.py` (`_launch_relay`, `_relay_finished`, Stop, typed start/resume, `action_quit`, `_tick`)
  - Create: `QuitRelayScreen` in `src/whyline/console/tui.py` (next to `ConfirmScreen`)
  - Test: `tests/console/test_tui_relay_run.py` (create)

  **Interfaces:**
  - Consumes: `relay_process.RelayProcess`, `relay_ops.live_run`, `adapters.classify_relay_output(root, text, code) -> SessionEvent`, `_sync_relay_buttons` (Task 6).
  - Produces: `WhylineConsoleApp._launch_relay(args: list[str]) -> None`; `WhylineConsoleApp._relay_label: str`; `QuitRelayScreen(label)` dismissing with `"leave"`, `"stop"` or `None`; module attribute `tui.RelayProcess` (imported name, so tests can replace it).

  Step 1: Write the failing tests

  Create `tests/console/test_tui_relay_run.py`:

  ```python
  import asyncio

  import pytest

  from whyline.console import relay_ops, tui

  pytestmark = [
      pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
      pytest.mark.asyncio,
  ]


  class FakeProcess:
      """Stands in for RelayProcess. Its callbacks use call_from_thread, which
      Textual refuses on the app's own thread, so tests drive them through
      asyncio.to_thread, as the real follower thread would."""

      instances = []

      def __init__(self, root, args, *, on_line, on_exit, **kwargs):
          self.root, self.args = root, args
          self.on_line, self.on_exit = on_line, on_exit
          self.alive = False
          self.stopped = self.unfollowed = False
          FakeProcess.instances.append(self)

      def start(self):
          self.alive = True

      def running(self):
          return self.alive

      def request_stop(self):
          self.stopped = True

      def stop_following(self):
          self.unfollowed = True

      def finish(self, code, text):
          self.alive = False
          self.on_exit(code, text)


  @pytest.fixture(autouse=True)
  def fake_relay(monkeypatch):
      FakeProcess.instances = []
      monkeypatch.setattr(tui, "RelayProcess", FakeProcess)
      monkeypatch.setattr(relay_ops, "live_run", lambda root: None)
      monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)


  def _lines(app):
      return [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]


  async def _relay_mode(app, pilot):
      app.session.mode = "relay"
      app._sync_mode_indicator()
      await pilot.pause()


  async def test_typed_start_streams_lines_and_reports_completion(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await _relay_mode(app, pilot)
          prompt = app.query_one("#prompt", tui.Input)
          prompt.value = "start --only T3"
          await pilot.press("enter")
          await pilot.pause()
          proc = FakeProcess.instances[-1]
          assert proc.args == ["start", "--only", "T3"]
          await asyncio.to_thread(proc.on_line, "T3: codex implementing")
          await pilot.pause()
          assert any("relay · T3: codex implementing" in line for line in _lines(app))
          assert not app.query_one("#stop", tui.Button).disabled
          await asyncio.to_thread(proc.finish, 0, "Plan complete: 1 task(s)\n")
          await pilot.pause()
          assert any("Relay finished." in line for line in _lines(app))
          assert app.query_one("#stop", tui.Button).disabled


  async def test_stop_asks_the_relay_to_pause_instead_of_killing_it(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await _relay_mode(app, pilot)
          app._launch_relay(["start"])
          await pilot.pause()
          await pilot.click("#stop")
          await pilot.pause()
          assert FakeProcess.instances[-1].stopped
          assert any("finishes its turn" in line for line in _lines(app))


  async def test_start_is_refused_while_another_relay_runs_here(tmp_path, monkeypatch):
      monkeypatch.setattr(relay_ops, "live_run", lambda root: "T3, codex")
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await _relay_mode(app, pilot)
          app._launch_relay(["start"])
          await pilot.pause()
          assert FakeProcess.instances == []
          assert any("already running here (T3, codex)" in line for line in _lines(app))


  async def test_a_second_start_is_refused_while_ours_runs(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await _relay_mode(app, pilot)
          app._launch_relay(["start"])
          app._launch_relay(["start"])
          await pilot.pause()
          assert len(FakeProcess.instances) == 1


  async def test_a_pause_enables_resume(tmp_path, monkeypatch):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await _relay_mode(app, pilot)
          app._launch_relay(["start"])
          await pilot.pause()
          monkeypatch.setattr(relay_ops, "paused_run", lambda root: True)
          await asyncio.to_thread(FakeProcess.instances[-1].finish, 3, "Paused: tests failed\n")
          await pilot.pause()
          assert not app.query_one("#relay-resume", tui.Button).disabled


  async def test_quitting_while_the_relay_runs_asks_first(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test() as pilot:
          await _relay_mode(app, pilot)
          app._launch_relay(["start"])
          await pilot.pause()
          await app.action_quit()
          await pilot.pause()
          assert isinstance(app.screen, tui.QuitRelayScreen)
          await pilot.click("#quit-leave")
          await pilot.pause()
      proc = FakeProcess.instances[-1]
      assert proc.unfollowed and not proc.stopped
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_tui_relay_run.py -q`
  Expected: FAIL (`AttributeError: module 'whyline.console.tui' has no attribute 'RelayProcess'`).

  Step 3: Implement in `src/whyline/console/tui.py`

  Add the import next to the other console imports:

  ```python
  from whyline.console.relay_process import RelayProcess
  ```

  In `__init__`, add `self._relay_label = ""`.

  Add after `ConfirmScreen`:

  ```python
  class QuitRelayScreen(ModalScreen):
      """Asked on quit while the relay is running: leave it running, stop it
      after the current agent, or stay."""

      DEFAULT_CSS = """
      QuitRelayScreen { align: center middle; }
      QuitRelayScreen > Vertical {
          width: 70; height: auto; padding: 1 2; border: thick $warning; background: $surface;
      }
      QuitRelayScreen Horizontal { height: auto; margin-top: 1; }
      QuitRelayScreen Button { margin-right: 2; }
      """

      def __init__(self, label: str) -> None:
          super().__init__()
          self._label = label

      def compose(self) -> ComposeResult:
          yield Vertical(
              Label(f"The relay is still working ({self._label}). Leave it running?"),
              Horizontal(
                  Button("Leave it running", id="quit-leave", variant="primary"),
                  Button("Stop it, then quit", id="quit-stop", variant="warning"),
                  Button("Cancel", id="quit-cancel"),
              ),
          )

      def on_button_pressed(self, event: "Button.Pressed") -> None:
          event.stop()
          choices = {"quit-leave": "leave", "quit-stop": "stop"}
          self.dismiss(choices.get(event.button.id))
  ```

  Replace the Task 6 placeholder `_launch_relay` with:

  ```python
      def _relay_running(self) -> bool:
          return self._relay is not None and self._relay.running()

      def _launch_relay(self, args: list[str]) -> None:
          """Start/Resume, from a button or typed. One relay at a time: ours,
          or one started elsewhere (a terminal) that running.live still sees."""
          if self._refuse_in_home():
              return
          if self._relay_running():
              self.render_event(SessionEvent(kind="error", text="The relay is already running."))
              return
          other = relay_ops.live_run(self.session.root)
          if other:
              self.render_event(SessionEvent(
                  kind="error", text=f"A relay is already running here ({other})."))
              return
          self._relay = RelayProcess(
              self.session.root, args,
              on_line=lambda line: self.call_from_thread(self._relay_line, line),
              on_exit=lambda code, text: self.call_from_thread(self._relay_finished, code, text),
          )
          try:
              self._relay.start()
          except OSError as error:
              self._relay = None
              self.render_event(SessionEvent(
                  kind="error", text=f"Could not start the relay ({' '.join(args)}): {error}"))
              return
          self._relay_label = f"relay: {' '.join(args)}"
          self._busy_since = time.monotonic()
          self.render_event(SessionEvent(
              kind="output", text=f"Running `whyline relay {' '.join(args)}`. Progress follows."))
          self._main("#thinking", Static).display = True
          self._main("#stop", Button).disabled = False
          self._sync_relay_buttons()

      def _relay_line(self, line: str) -> None:
          self.render_event(SessionEvent(kind="output", text=f"relay · {line}"))
          live = relay_ops.live_run(self.session.root)
          if live:
              self._relay_label = f"relay: {live}"

      def _relay_finished(self, code: int, text: str) -> None:
          self._relay = None
          self._relay_label = ""
          if not self._busy_text:
              self._main("#thinking", Static).display = False
              self._main("#stop", Button).disabled = True
          event = adapters.classify_relay_output(self.session.root, text, code)
          if event.kind == "pause":
              self.render_event(event)
          elif event.kind == "output":
              self.render_event(SessionEvent(kind="output", text="Relay finished."))
          else:
              self.render_event(SessionEvent(
                  kind="error",
                  text=f"The relay stopped with exit code {code}. Its full output is in "
                       ".whyline/relay/logs/console-run.log.",
              ))
          self._sync_relay_buttons()
  ```

  In `on_button_pressed`, change the `stop` branch to:

  ```python
          elif button_id == "stop":
              if self._relay_running():
                  self._relay.request_stop()
                  self.render_event(SessionEvent(
                      kind="output",
                      text="Stop requested: the current agent finishes its turn, then the "
                           "relay pauses. Resume carries on from there.",
                  ))
              else:
                  self._stop()
  ```

  In `_send`, just before `if not self._handle_slash(text):`, add:

  ```python
          first = text.split(maxsplit=1)[0]
          if self.session.mode == "relay" and first in ("start", "resume"):
              self._launch_relay(text.split())
              return
  ```

  (Place it after `prompt.value = ""` and the `input` render, so what you typed still appears.)

  In `_tick`, replace its first line `if not self._busy_text or not self.screen_stack:` with:

  ```python
          label = self._busy_text or self._relay_label
          if not label or not self.screen_stack:
  ```

  and in the `thinking.update(...)` call at its end use `label` instead of `self._busy_text`.

  In `_set_busy`, in the `else:` branch (not busy), only hide the thinking line and disable Stop when no relay is running:

  ```python
          else:
              self._busy_text = ""
              if not self._relay_running():
                  thinking.display = False
  ```

  and change its first line to `self._main("#stop", Button).disabled = not busy and not self._relay_running()`.

  Add:

  ```python
      async def action_quit(self) -> None:
          if self._relay_running():
              self.push_screen(QuitRelayScreen(self._relay_label or "relay"), self._quit_choice)
              return
          self.exit()

      def _quit_choice(self, choice: "str | None") -> None:
          if choice is None:
              return
          if choice == "stop":
              self._relay.request_stop()
          self._relay.stop_following()
          self.exit()
  ```

  Step 4: Run the tests

  Run: `uv run pytest tests/console -q`
  Expected: all PASS.

  Step 5: Commit

  ```bash
  git add src/whyline/console/tui.py tests/console/test_tui_relay_run.py
  git commit -m "feat(console): start, stop and resume the relay with live progress"
  ```

- [ ] CRS-9: Plan popup — Paste

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Create: `src/whyline/console/relay_screens.py` (`RelayPlanScreen`)
  - Modify: `src/whyline/console/tui.py` (`_open_relay_plan`, `_plan_saved`)
  - Test: `tests/console/test_relay_plan_screen.py` (create)

  **Interfaces:**
  - Consumes: `relay_ops.validate_plan`, `relay_ops.save_pasted_plan`, `relay_ops.plan_exists_error`, `relay_ops.pending_draft`, `tui.ConfirmScreen(message, confirm_label)` (dismisses `True`/`False`).
  - Produces: `RelayPlanScreen(root: Path, status: dict, active: str)` dismissing with the saved `Path` or `None`. Widget ids: `#rp-source` (Select: `"paste"`, `"draft"`, `"brainstorm"`), `#rp-paste` (TextArea), `#rp-paste-group`, `#rp-draft-group`, `#rp-brainstorm-group`, `#rp-form`, `#rp-working`, `#rp-progress`, `#rp-review`, `#rp-draft`, `#rp-feedback`, `#rp-error`, buttons `#rp-go`, `#rp-approve`, `#rp-changes`, `#rp-send-changes`, `#rp-cancel`, `#rp-resume-draft`, `#rp-discard-draft`. Methods used by Tasks 10–11: `_set_state(state: str)` with states `"form"`, `"working"`, `"review"`; `_error(text: str)`; `_run(work, on_done)` (runs `work(progress)` in a thread; calls `on_done(result)` or shows the exception); `_confirm_replace(retry)`.

  Step 1: Write the failing tests

  Create `tests/console/test_relay_plan_screen.py`:

  ```python
  from pathlib import Path

  import pytest

  from whyline.console import relay_ops, tui
  from whyline.console.relay_screens import RelayPlanScreen

  pytestmark = [
      pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
      pytest.mark.asyncio,
  ]

  STATUS = {agent: {"available": agent in ("claude", "codex"), "label": "ok"}
            for agent in ("claude", "codex", "antigravity", "grok")}


  class PlanExists(RuntimeError):
      pass


  @pytest.fixture(autouse=True)
  def quiet_ops(monkeypatch):
      monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
      monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
      monkeypatch.setattr(relay_ops, "plan_exists_error", lambda: PlanExists)


  async def _open(app, pilot):
      results = []
      app.push_screen(RelayPlanScreen(app.session.root, STATUS, "claude"), results.append)
      await pilot.pause()
      return app.screen, results


  def _error_text(screen):
      return str(screen.query_one("#rp-error", tui.Static).renderable)


  async def test_paste_saves_a_valid_plan(tmp_path, monkeypatch):
      saved = []
      monkeypatch.setattr(relay_ops, "save_pasted_plan",
                          lambda root, text, replace=False: saved.append((text, replace)) or root / "plan.md")
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, results = await _open(app, pilot)
          screen.query_one("#rp-source", tui.Select).value = "paste"
          await pilot.pause()
          screen.query_one("#rp-paste").load_text("- [ ] T-1: build it\n")
          await pilot.click("#rp-go")
          await pilot.pause()
      assert saved == [("- [ ] T-1: build it\n", False)]
      assert results == [tmp_path / "plan.md"]


  async def test_paste_shows_why_an_invalid_plan_is_refused(tmp_path, monkeypatch):
      def refuse(root, text, replace=False):
          raise ValueError("no tasks found -- write each task as `- [ ] ID: title`")

      monkeypatch.setattr(relay_ops, "save_pasted_plan", refuse)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, results = await _open(app, pilot)
          screen.query_one("#rp-source", tui.Select).value = "paste"
          await pilot.pause()
          screen.query_one("#rp-paste").load_text("just prose")
          await pilot.click("#rp-go")
          await pilot.pause()
          assert "no tasks found" in _error_text(screen)
          assert results == []


  async def test_paste_over_an_existing_plan_asks_first(tmp_path, monkeypatch):
      calls = []

      def save(root, text, replace=False):
          calls.append(replace)
          if not replace:
              raise PlanExists("plan.md already exists")
          return root / "plan.md"

      monkeypatch.setattr(relay_ops, "save_pasted_plan", save)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, results = await _open(app, pilot)
          screen.query_one("#rp-source", tui.Select).value = "paste"
          await pilot.pause()
          screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
          await pilot.click("#rp-go")
          await pilot.pause()
          assert isinstance(app.screen, tui.ConfirmScreen)
          await pilot.click("#confirm")
          await pilot.pause()
      assert calls == [False, True]
      assert results == [tmp_path / "plan.md"]


  async def test_only_the_chosen_sources_fields_show(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          assert screen.query_one("#rp-source", tui.Select).value == "draft"
          assert screen.query_one("#rp-draft-group").display
          assert not screen.query_one("#rp-paste-group").display
          screen.query_one("#rp-source", tui.Select).value = "paste"
          await pilot.pause()
          assert screen.query_one("#rp-paste-group").display
          assert not screen.query_one("#rp-draft-group").display


  async def test_plan_button_opens_the_popup_and_reports_the_saved_plan(tmp_path, monkeypatch):
      from whyline import account

      monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
      monkeypatch.setattr(relay_ops, "save_pasted_plan", lambda root, text, replace=False: root / "plan.md")
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          app.session.mode = "relay"
          app._sync_mode_indicator()
          await pilot.click("#relay-plan")
          await pilot.pause()
          assert isinstance(app.screen, RelayPlanScreen)
          app.screen.query_one("#rp-source", tui.Select).value = "paste"
          await pilot.pause()
          app.screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
          await pilot.click("#rp-go")
          await pilot.pause()
          lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
          assert any("Saved plan.md" in line and "Set up" in line for line in lines)
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_relay_plan_screen.py -q`
  Expected: FAIL with `ModuleNotFoundError: No module named 'whyline.console.relay_screens'`.

  Step 3: Create `src/whyline/console/relay_screens.py`

  ```python
  """The Relay-mode popups: Plan (make and approve plan.md) and Set up
  (roles, checks, start). Every relay call goes through relay_ops, run in a
  worker thread; results come back through call_from_thread and are dropped
  if the user cancelled in the meantime (the same token pattern the console
  uses for chat replies)."""

  from __future__ import annotations

  from pathlib import Path

  from textual.app import ComposeResult
  from textual.containers import Horizontal, Vertical, VerticalScroll
  from textual.screen import ModalScreen
  from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

  from whyline.console import relay_ops

  _SOURCES = [
      ("Draft from a description", "draft"),
      ("Paste a plan", "paste"),
      ("From a brainstorm", "brainstorm"),
  ]
  _STATE_BUTTONS = {
      "form": {"rp-go", "rp-cancel"},
      "working": {"rp-cancel"},
      "review": {"rp-approve", "rp-changes", "rp-cancel"},
  }


  class RelayPlanScreen(ModalScreen):
      DEFAULT_CSS = """
      RelayPlanScreen { align: center middle; }
      RelayPlanScreen > Vertical {
          width: 96; max-width: 100%; height: auto; max-height: 100%; padding: 0 2;
          border: thick $accent; background: $surface;
      }
      RelayPlanScreen #rp-form, RelayPlanScreen #rp-review { height: auto; max-height: 1fr; }
      RelayPlanScreen #rp-working { height: auto; }
      RelayPlanScreen Horizontal { height: auto; }
      RelayPlanScreen .field-label { width: 18; padding: 1 1 0 0; }
      RelayPlanScreen TextArea { height: 8; }
      RelayPlanScreen #rp-refs { height: 4; }
      RelayPlanScreen #rp-source { width: 40; }
      RelayPlanScreen #rp-error { color: $error; height: auto; }
      RelayPlanScreen #rp-error.-empty { display: none; }
      RelayPlanScreen #rp-buttons { margin-top: 1; }
      RelayPlanScreen #rp-buttons Button { margin-right: 1; }
      """

      def __init__(self, root: Path, status: dict, active: str) -> None:
          super().__init__()
          self._root = root
          self._status = status
          self._active = active
          self._token: object | None = None
          self._draft: relay_ops.Draft | None = None

      def compose(self) -> ComposeResult:
          form = VerticalScroll(
              Label("Plan: make plan.md, the task list the relay works through."),
              Horizontal(
                  Label("Source:", classes="field-label"),
                  Select(_SOURCES, value="draft", allow_blank=False, id="rp-source"),
              ),
              Vertical(
                  Label("Paste the plan (each task as `- [ ] ID: title`):"),
                  TextArea(id="rp-paste"),
                  id="rp-paste-group",
              ),
              Vertical(
                  Label("What should the plan build?"),
                  TextArea(id="rp-description"),
                  Label("Reference documents, one path per line (e.g. PRD.md):"),
                  TextArea(id="rp-refs"),
                  id="rp-draft-group",
              ),
              Vertical(*self._brainstorm_widgets(), id="rp-brainstorm-group"),
              id="rp-form",
          )
          yield Vertical(
              form,
              Vertical(Static("", id="rp-progress"), id="rp-working"),
              VerticalScroll(
                  Static("", id="rp-draft"),
                  Input(placeholder="What should change?", id="rp-feedback"),
                  id="rp-review",
              ),
              Static("", id="rp-error", classes="-empty"),
              Horizontal(
                  Button("Save", id="rp-go", variant="success"),
                  Button("Approve", id="rp-approve", variant="success"),
                  Button("Request changes", id="rp-changes"),
                  Button("Send changes", id="rp-send-changes", variant="primary"),
                  Button("Resume draft", id="rp-resume-draft", variant="primary"),
                  Button("Discard it", id="rp-discard-draft", variant="warning"),
                  Button("Cancel", id="rp-cancel"),
                  id="rp-buttons",
              ),
          )

      def _brainstorm_widgets(self) -> list:
          """Filled in by Task 11; empty until then."""
          return [Label("Brainstorm source: coming in a later task.")]

      def on_mount(self) -> None:
          self._set_state("form")
          self._show_source("draft")
          pending = relay_ops.pending_draft(self._root)
          if pending:
              self._error(f'A plan draft for "{pending}" was left unfinished.')
              self.query_one("#rp-resume-draft").display = True
              self.query_one("#rp-discard-draft").display = True

      # -- state -----------------------------------------------------------

      def _set_state(self, state: str) -> None:
          self._state = state
          self.query_one("#rp-form").display = state == "form"
          self.query_one("#rp-working").display = state == "working"
          self.query_one("#rp-review").display = state == "review"
          self.query_one("#rp-feedback").display = False
          visible = _STATE_BUTTONS[state]
          for button in self.query("#rp-buttons Button"):
              button.display = button.id in visible
          self.query_one("#rp-go", Button).label = (
              "Save" if self._source() == "paste" else "Make the plan"
          )

      def _source(self) -> str:
          return self.query_one("#rp-source", Select).value

      def _show_source(self, source: str) -> None:
          for name in ("paste", "draft", "brainstorm"):
              self.query_one(f"#rp-{name}-group").display = name == source
          self.query_one("#rp-go", Button).label = (
              "Save" if source == "paste" else "Make the plan"
          )

      def on_select_changed(self, event: "Select.Changed") -> None:
          if event.select.id == "rp-source":
              self._show_source(event.value)

      def _error(self, text: str) -> None:
          error = self.query_one("#rp-error", Static)
          error.update(text)
          error.set_class(not text, "-empty")

      # -- running work off the UI thread -----------------------------------

      def _progress(self, token: object):
          def report(line: str) -> None:
              self.app.call_from_thread(self._add_progress, line, token)
          return report

      def _add_progress(self, line: str, token: object) -> None:
          if token is not self._token:
              return
          progress = self.query_one("#rp-progress", Static)
          progress.update(f"{progress.renderable}\n· {line}".strip())

      def _run(self, work, on_done) -> None:
          """Runs work(progress) in a thread. on_done(result) runs on the UI
          thread; an exception is shown in the error line and returns to the
          form with every input still filled in."""
          token = object()
          self._token = token
          self._error("")
          self.query_one("#rp-progress", Static).update("Working…")
          self._set_state("working")

          def in_thread() -> None:
              try:
                  result = work(self._progress(token))
              except Exception as error:  # agent missing, timed out, parse failure...
                  self.app.call_from_thread(self._failed, error, token)
                  return
              self.app.call_from_thread(self._succeeded, on_done, result, token)

          self.run_worker(in_thread, thread=True)

      def _succeeded(self, on_done, result, token: object) -> None:
          if token is self._token:
              on_done(result)

      def _failed(self, error: Exception, token: object) -> None:
          if token is not self._token:
              return
          self._set_state("form")
          self._error(str(error) or error.__class__.__name__)

      # -- saving ----------------------------------------------------------

      def _confirm_replace(self, retry) -> None:
          from whyline.console.tui import ConfirmScreen

          def answered(confirmed: bool) -> None:
              if confirmed:
                  retry()
          self.app.push_screen(
              ConfirmScreen("plan.md already exists. Replace it?", "Replace"), answered
          )

      def _save_paste(self, replace: bool = False) -> None:
          text = self.query_one("#rp-paste", TextArea).text
          try:
              path = relay_ops.save_pasted_plan(self._root, text, replace=replace)
          except relay_ops.plan_exists_error():
              self._confirm_replace(lambda: self._save_paste(replace=True))
              return
          except ValueError as error:
              self._error(str(error))
              return
          self.dismiss(path)

      # -- buttons ---------------------------------------------------------

      def on_button_pressed(self, event: "Button.Pressed") -> None:
          event.stop()
          handler = getattr(self, f"_on_{event.button.id.replace('-', '_')}", None)
          if handler is not None:
              handler()

      def _on_rp_cancel(self) -> None:
          self._token = object()  # a late result from a cancelled run is dropped
          self.dismiss(None)

      def _on_rp_go(self) -> None:
          if self._source() == "paste":
              self._save_paste()
  ```

  Step 4: Wire the Plan button in `src/whyline/console/tui.py`

  Replace the Task 6 placeholder `_open_relay_plan` with:

  ```python
      def _open_relay_plan(self) -> None:
          if self._refuse_in_home():
              return
          from whyline import account
          from whyline.console.relay_screens import RelayPlanScreen

          self.push_screen(
              RelayPlanScreen(self.session.root, account.agent_status(self.session.root),
                              self.session.agent or "claude"),
              self._plan_saved,
          )

      def _plan_saved(self, path: "Path | None") -> None:
          if path is None:
              return
          self.render_event(SessionEvent(
              kind="output",
              text=f"Saved {path.name} and committed it. Next: Set up, to pick who "
                   "implements, tests and reviews.",
          ))
          self._sync_relay_buttons()
  ```

  Step 5: Run the tests

  Run: `uv run pytest tests/console -q`
  Expected: all PASS.

  Step 6: Commit

  ```bash
  git add src/whyline/console/relay_screens.py src/whyline/console/tui.py tests/console/test_relay_plan_screen.py
  git commit -m "feat(console): Plan popup with a pasted plan"
  ```

- [ ] CRS-10: Plan popup — Draft, review, request changes, resume/discard

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Modify: `src/whyline/console/relay_screens.py` (`RelayPlanScreen` handlers)
  - Test: `tests/console/test_relay_plan_screen.py` (append)

  **Interfaces:**
  - Consumes: `relay_ops.missing_references`, `draft_plan`, `revise_plan`, `approve_plan`, `resume_draft`, `discard_draft`, `in_progress_error`, `Draft` (Task 5); `_run`, `_set_state`, `_error`, `_confirm_replace` (Task 9).
  - Produces: `RelayPlanScreen._show_review(draft: relay_ops.Draft)` (used by Task 11); handlers `_on_rp_approve`, `_on_rp_changes`, `_on_rp_send_changes`, `_on_rp_resume_draft`, `_on_rp_discard_draft`; `_on_rp_go` handles `"draft"`.

  Step 1: Write the failing tests

  Append to `tests/console/test_relay_plan_screen.py`:

  ```python
  def _draft(tmp_path, text="- [ ] T-1: build it\n", source="planner"):
      path = tmp_path / "draft.md"
      path.write_text(text)
      return relay_ops.Draft(path=path, text=text, drafted_by="codex", source=source)


  async def _wait_for(pilot, condition, what):
      for _ in range(100):
          if condition():
              return
          await pilot.pause(0.05)
      raise AssertionError(f"never happened: {what}")


  async def test_draft_reviews_then_approves(tmp_path, monkeypatch):
      calls = []

      def draft_plan(root, description, refs, *, progress):
          calls.append((description, refs))
          progress("codex is drafting the plan")
          return _draft(tmp_path)

      monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: [])
      monkeypatch.setattr(relay_ops, "draft_plan", draft_plan)
      monkeypatch.setattr(relay_ops, "approve_plan",
                          lambda root, draft, replace=False: root / "plan.md")
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, results = await _open(app, pilot)
          screen.query_one("#rp-description").load_text("Build what PRD.md describes")
          screen.query_one("#rp-refs").load_text("PRD.md\n\n  docs/b.md  \n")
          await pilot.click("#rp-go")
          await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
          assert "T-1: build it" in str(screen.query_one("#rp-draft", tui.Static).renderable)
          await pilot.click("#rp-approve")
          await pilot.pause()
      assert calls == [("Build what PRD.md describes", ["PRD.md", "docs/b.md"])]
      assert results == [tmp_path / "plan.md"]


  async def test_draft_reports_missing_reference_files_before_running(tmp_path, monkeypatch):
      monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: ["nope.md"])
      monkeypatch.setattr(relay_ops, "draft_plan",
                          lambda *a, **k: pytest.fail("must not draft"))
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          screen.query_one("#rp-description").load_text("Build it")
          screen.query_one("#rp-refs").load_text("nope.md")
          await pilot.click("#rp-go")
          await pilot.pause()
          assert "nope.md" in _error_text(screen)


  async def test_draft_needs_a_description(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          await pilot.click("#rp-go")
          await pilot.pause()
          assert "Describe what the plan should build" in _error_text(screen)


  async def test_an_agent_failure_returns_to_the_form_with_inputs_kept(tmp_path, monkeypatch):
      def fail(*a, **k):
          raise RuntimeError("codex is not logged in")

      monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: [])
      monkeypatch.setattr(relay_ops, "draft_plan", fail)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          screen.query_one("#rp-description").load_text("Build it")
          await pilot.click("#rp-go")
          await _wait_for(pilot, lambda: "not logged in" in _error_text(screen), "error")
          assert screen.query_one("#rp-form").display
          assert screen.query_one("#rp-description").text == "Build it"


  async def test_request_changes_sends_feedback_and_shows_the_new_draft(tmp_path, monkeypatch):
      revised = []
      monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: [])
      monkeypatch.setattr(relay_ops, "draft_plan", lambda *a, **k: _draft(tmp_path))

      def revise(root, draft, feedback, *, progress):
          revised.append(feedback)
          return _draft(tmp_path, "- [ ] T-1: a\n- [ ] T-2: b\n")

      monkeypatch.setattr(relay_ops, "revise_plan", revise)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          screen.query_one("#rp-description").load_text("Build it")
          await pilot.click("#rp-go")
          await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
          await pilot.click("#rp-changes")
          await pilot.pause()
          screen.query_one("#rp-feedback", tui.Input).value = "split it in two"
          await pilot.click("#rp-send-changes")
          await _wait_for(pilot, lambda: "T-2: b" in str(
              screen.query_one("#rp-draft", tui.Static).renderable), "revised draft")
      assert revised == ["split it in two"]


  async def test_an_unfinished_draft_can_be_resumed(tmp_path, monkeypatch):
      monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build it")
      monkeypatch.setattr(relay_ops, "resume_draft", lambda root, *, progress: _draft(tmp_path))
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          assert "left unfinished" in _error_text(screen)
          await pilot.click("#rp-resume-draft")
          await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")


  async def test_an_unfinished_draft_can_be_discarded(tmp_path, monkeypatch):
      discarded = []
      monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build it")
      monkeypatch.setattr(relay_ops, "discard_draft", lambda root, draft: discarded.append(draft))
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          await pilot.click("#rp-discard-draft")
          await pilot.pause()
          assert discarded == [None]
          assert _error_text(screen) == ""
          assert not screen.query_one("#rp-resume-draft").display


  async def test_approving_over_an_existing_plan_asks_first(tmp_path, monkeypatch):
      calls = []
      monkeypatch.setattr(relay_ops, "missing_references", lambda root, refs: [])
      monkeypatch.setattr(relay_ops, "draft_plan", lambda *a, **k: _draft(tmp_path))

      def approve(root, draft, replace=False):
          calls.append(replace)
          if not replace:
              raise PlanExists("exists")
          return root / "plan.md"

      monkeypatch.setattr(relay_ops, "approve_plan", approve)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, results = await _open(app, pilot)
          screen.query_one("#rp-description").load_text("Build it")
          await pilot.click("#rp-go")
          await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
          await pilot.click("#rp-approve")
          await pilot.pause()
          await pilot.click("#confirm")
          await pilot.pause()
      assert calls == [False, True]
      assert results == [tmp_path / "plan.md"]
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_relay_plan_screen.py -q`
  Expected: the new tests FAIL (Make the plan does nothing for Draft yet).

  Step 3: Implement in `src/whyline/console/relay_screens.py`

  Replace `_on_rp_go` and add the handlers below it in `RelayPlanScreen`:

  ```python
      def _on_rp_go(self) -> None:
          source = self._source()
          if source == "paste":
              self._save_paste()
          elif source == "draft":
              self._start_draft()
          else:
              self._start_brainstorm()

      def _start_brainstorm(self) -> None:
          """Filled in by Task 11."""
          self._error("Brainstorm source: coming in a later task.")

      def _start_draft(self) -> None:
          description = self.query_one("#rp-description", TextArea).text.strip()
          if not description:
              self._error("Describe what the plan should build.")
              return
          refs = [line.strip() for line in
                  self.query_one("#rp-refs", TextArea).text.splitlines() if line.strip()]
          missing = relay_ops.missing_references(self._root, refs)
          if missing:
              self._error("Can't find: " + ", ".join(missing))
              return
          root = self._root

          def work(progress):
              try:
                  return relay_ops.draft_plan(root, description, refs, progress=progress)
              except relay_ops.in_progress_error() as error:
                  raise RuntimeError(
                      "A plan draft is already unfinished -- close this and open Plan "
                      "again to resume or discard it."
                  ) from error

          self._run(work, self._show_review)

      def _show_review(self, draft: relay_ops.Draft) -> None:
          self._draft = draft
          self.query_one("#rp-draft", Static).update(draft.text)
          self._set_state("review")

      def _on_rp_approve(self, replace: bool = False) -> None:
          try:
              path = relay_ops.approve_plan(self._root, self._draft, replace=replace)
          except relay_ops.plan_exists_error():
              self._confirm_replace(lambda: self._on_rp_approve(replace=True))
              return
          except ValueError as error:  # plan.PlanError: the draft isn't a usable plan
              self._error(f"{error}. The draft is still at {self._draft.path}.")
              return
          self.dismiss(path)

      def _on_rp_changes(self) -> None:
          feedback = self.query_one("#rp-feedback", Input)
          feedback.display = True
          self.query_one("#rp-send-changes").display = True
          self.query_one("#rp-changes").display = False
          feedback.focus()

      def _on_rp_send_changes(self) -> None:
          feedback = self.query_one("#rp-feedback", Input).value.strip()
          if not feedback:
              self._error("Say what should change.")
              return
          draft, root = self._draft, self._root
          self.query_one("#rp-feedback", Input).value = ""
          self._run(
              lambda progress: relay_ops.revise_plan(root, draft, feedback, progress=progress),
              self._show_review,
          )

      def _on_rp_resume_draft(self) -> None:
          root = self._root
          self._run(lambda progress: relay_ops.resume_draft(root, progress=progress),
                    self._show_review)

      def _on_rp_discard_draft(self) -> None:
          relay_ops.discard_draft(self._root, None)
          self._error("")
          self.query_one("#rp-resume-draft").display = False
          self.query_one("#rp-discard-draft").display = False
  ```

  Also change `_on_rp_cancel` so cancelling in the review state drops the planner checkpoint (the draft file stays):

  ```python
      def _on_rp_cancel(self) -> None:
          self._token = object()  # a late result from a cancelled run is dropped
          if self._state == "review" and self._draft is not None:
              relay_ops.discard_draft(self._root, self._draft)
          self.dismiss(None)
  ```

  In `on_mount`, after `self._set_state("form")`, hide the two draft-recovery buttons by default (the `_STATE_BUTTONS` map already hides them; the pending-draft branch shows them).

  Step 4: Run the tests

  Run: `uv run pytest tests/console -q`
  Expected: all PASS.

  Step 5: Commit

  ```bash
  git add src/whyline/console/relay_screens.py tests/console/test_relay_plan_screen.py
  git commit -m "feat(console): draft a plan, review it, request changes or approve"
  ```

- [ ] CRS-11: Plan popup — Brainstorm source (new or existing doc)

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Modify: `src/whyline/console/tui.py` (extract the brainstorm fields so both popups share them)
  - Modify: `src/whyline/console/relay_screens.py` (`_brainstorm_widgets`, `_start_brainstorm`)
  - Test: `tests/console/test_relay_plan_screen.py` (append)

  **Interfaces:**
  - Consumes: `relay_ops.brainstorm_docs`, `relay_ops.plan_from_brainstorm`, `adapters.run_brainstorm(root, *, topic, agents, passes, final_agent, timeout_minutes, progress) -> SessionEvent`, `_show_review` (Task 10).
  - Produces (in `tui.py`): `brainstorm_field_widgets(status: dict, default_final: str) -> list` and `collect_brainstorm(query_one) -> dict | str` — both used by `BrainstormScreen` and `RelayPlanScreen`. Plan popup ids: `#rp-from` (Select: `"new"` or a doc stem), `#rp-writer` (Select of available agents), `#rp-new-group`, plus the shared `#bs-*` ids.

  Step 1: Write the failing tests

  Append to `tests/console/test_relay_plan_screen.py`:

  ```python
  async def test_an_existing_brainstorm_doc_becomes_a_plan(tmp_path, monkeypatch):
      calls = []
      monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: ["trading-prd"])

      def plan_from(root, topic, agent, *, progress, timeout_minutes=None):
          calls.append((topic, agent))
          return _draft(tmp_path, source="brainstorm")

      monkeypatch.setattr(relay_ops, "plan_from_brainstorm", plan_from)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          screen.query_one("#rp-source", tui.Select).value = "brainstorm"
          await pilot.pause()
          screen.query_one("#rp-from", tui.Select).value = "trading-prd"
          await pilot.pause()
          assert not screen.query_one("#rp-new-group").display
          screen.query_one("#rp-writer", tui.Select).value = "codex"
          await pilot.click("#rp-go")
          await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
      assert calls == [("trading-prd", "codex")]


  async def test_a_new_brainstorm_runs_then_becomes_a_plan(tmp_path, monkeypatch):
      from whyline.console import adapters
      from whyline.console.session import SessionEvent

      ran, planned = [], []

      def run_brainstorm(root, *, progress, **choice):
          ran.append(choice)
          progress("Researching independently: Claude, Codex")
          return SessionEvent(kind="output", text="done")

      def plan_from(root, topic, agent, *, progress, timeout_minutes=None):
          planned.append((topic, agent, timeout_minutes))
          return _draft(tmp_path, source="brainstorm")

      monkeypatch.setattr(adapters, "run_brainstorm", run_brainstorm)
      monkeypatch.setattr(relay_ops, "plan_from_brainstorm", plan_from)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          screen.query_one("#rp-source", tui.Select).value = "brainstorm"
          await pilot.pause()
          assert screen.query_one("#rp-from", tui.Select).value == "new"
          screen.query_one("#bs-topic", tui.Input).value = "trading platform"
          screen.query_one("#bs-timeout", tui.Select).value = 30
          await pilot.click("#rp-go")
          await _wait_for(pilot, lambda: screen.query_one("#rp-review").display, "review")
      assert ran[0]["topic"] == "trading platform"
      assert ran[0]["agents"] == ["claude", "codex"]
      assert planned == [("trading platform", "claude", 30)]


  async def test_a_failed_brainstorm_is_shown_and_no_plan_is_made(tmp_path, monkeypatch):
      from whyline.console import adapters
      from whyline.console.session import SessionEvent

      monkeypatch.setattr(adapters, "run_brainstorm",
                          lambda root, *, progress, **c: SessionEvent(kind="error", text="No selected agent succeeded"))
      monkeypatch.setattr(relay_ops, "plan_from_brainstorm", lambda *a, **k: pytest.fail("no plan"))
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          screen.query_one("#rp-source", tui.Select).value = "brainstorm"
          await pilot.pause()
          screen.query_one("#bs-topic", tui.Input).value = "x"
          await pilot.click("#rp-go")
          await _wait_for(pilot, lambda: "No selected agent succeeded" in _error_text(screen), "error")
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_relay_plan_screen.py -q`
  Expected: the three new tests FAIL (`NoMatches` for `#rp-from`).

  Step 3: Extract the shared brainstorm fields in `src/whyline/console/tui.py`

  Add these module-level functions above `class BrainstormScreen`:

  ```python
  def brainstorm_field_widgets(status: dict, default_final: str) -> list:
      """Topic, models, passes, final writer and timeout -- shared by the
      Brainstorm popup and the Plan popup's brainstorm source."""
      boxes = []
      for agent in BRAINSTORM_AGENTS:
          info = status[agent]
          boxes.append(
              Checkbox(f"{agent:<12} {info['label']}", value=info["available"],
                       disabled=not info["available"], id=f"bs-{agent}")
          )
      return [
          Input(placeholder="Topic, e.g. how the relay should handle a failed Codex run",
                id="bs-topic"),
          Label("Models:", classes="field-label"),
          *boxes,
          Horizontal(Label("Review passes:", classes="field-label"), Input("1", id="bs-passes")),
          Horizontal(
              Label("Final write-up:", classes="field-label"),
              Select([(a, a) for a in BRAINSTORM_AGENTS], value=default_final,
                     allow_blank=False, id="bs-final"),
          ),
          Horizontal(
              Label("Per-agent timeout:", classes="field-label"),
              Select([(f"{m} minutes", m) for m in BRAINSTORM_TIMEOUT_OPTIONS],
                     value=15, allow_blank=False, id="bs-timeout"),
          ),
      ]


  def collect_brainstorm(query_one) -> "dict | str":
      """The brainstorm fields' values, or a message saying what's missing.
      `query_one` is the owning screen's query_one."""
      topic = query_one("#bs-topic", Input).value.strip()
      if not topic:
          return "Enter a topic."
      agents = [a for a in BRAINSTORM_AGENTS if query_one(f"#bs-{a}", Checkbox).value]
      if not agents:
          return "Pick at least one model."
      raw = query_one("#bs-passes", Input).value.strip() or "0"
      if not raw.isdigit():
          return "Review passes must be a whole number (0 or more)."
      final = query_one("#bs-final", Select).value
      timeout = query_one("#bs-timeout", Select).value
      if timeout not in BRAINSTORM_TIMEOUT_OPTIONS:
          return "Choose a timeout of 15, 30, 45, or 60 minutes."
      return {
          "topic": topic,
          "agents": agents,
          "passes": int(raw),
          "final_agent": final if final in agents else agents[0],
          "timeout_minutes": timeout,
      }
  ```

  In `BrainstormScreen.compose`, replace the `boxes` loop and the field widgets after the first `Label(...)` with `*brainstorm_field_widgets(self._status, self._default_final),` (keep the leading explanatory `Label` and `id="bs-fields"`). Replace the body of `BrainstormScreen.collect` with `return collect_brainstorm(self.query_one)`.

  Step 4: Fill in the brainstorm source in `src/whyline/console/relay_screens.py`

  Replace `_brainstorm_widgets` and `_start_brainstorm`, and extend `on_select_changed`:

  ```python
      def _brainstorm_widgets(self) -> list:
          from whyline.console.repl import BRAINSTORM_AGENTS
          from whyline.console.tui import brainstorm_field_widgets

          usable = [a for a in BRAINSTORM_AGENTS if self._status[a]["available"]]
          default = self._active if self._active in usable else (usable or ["claude"])[0]
          docs = relay_ops.brainstorm_docs(self._root)
          return [
              Horizontal(
                  Label("From:", classes="field-label"),
                  Select([("New brainstorm", "new"), *((doc, doc) for doc in docs)],
                         value="new", allow_blank=False, id="rp-from"),
              ),
              Horizontal(
                  Label("Plan writer:", classes="field-label"),
                  Select([(a, a) for a in (usable or ["claude"])], value=default,
                         allow_blank=False, id="rp-writer"),
                  id="rp-writer-row",
              ),
              Vertical(*brainstorm_field_widgets(self._status, default), id="rp-new-group"),
          ]

      def on_select_changed(self, event: "Select.Changed") -> None:
          if event.select.id == "rp-source":
              self._show_source(event.value)
          elif event.select.id == "rp-from":
              new = event.value == "new"
              self.query_one("#rp-new-group").display = new
              # A new brainstorm's own "Final write-up" also writes the plan.
              self.query_one("#rp-writer-row").display = not new

      def _start_brainstorm(self) -> None:
          from whyline.console import adapters
          from whyline.console.tui import collect_brainstorm

          root = self._root
          chosen = self.query_one("#rp-from", Select).value
          if chosen != "new":
              writer = self.query_one("#rp-writer", Select).value
              self._run(
                  lambda progress: relay_ops.plan_from_brainstorm(
                      root, chosen, writer, progress=progress),
                  self._show_review,
              )
              return
          choice = collect_brainstorm(self.query_one)
          if isinstance(choice, str):
              self._error(choice)
              return

          def work(progress):
              result = adapters.run_brainstorm(root, progress=progress, **choice)
              if result.kind == "error":
                  raise RuntimeError(result.text)
              return relay_ops.plan_from_brainstorm(
                  root, choice["topic"], choice["final_agent"], progress=progress,
                  timeout_minutes=choice["timeout_minutes"],
              )

          self._run(work, self._show_review)
  ```

  In `on_mount`, after `self._show_source("draft")`, add `self.query_one("#rp-writer-row").display = False` (the default "From" is New brainstorm).

  Add `RelayPlanScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }` and `RelayPlanScreen Checkbox:focus { border: none; }` to its `DEFAULT_CSS` (same reason as in `BrainstormScreen`).

  Step 5: Run the tests

  Run: `uv run pytest tests/console -q`
  Expected: all PASS, including the existing Brainstorm popup tests.

  Step 6: Commit

  ```bash
  git add src/whyline/console/tui.py src/whyline/console/relay_screens.py tests/console/test_relay_plan_screen.py
  git commit -m "feat(console): plan from a new or existing brainstorm"
  ```

- [ ] CRS-12: Set up popup — roles, check, start

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Modify: `src/whyline/console/relay_screens.py` (add `RelaySetupScreen`)
  - Modify: `src/whyline/console/tui.py` (`_open_relay_setup`, `_setup_done`)
  - Test: `tests/console/test_relay_setup_screen.py` (create)

  **Interfaces:**
  - Consumes: `relay_ops.relay_agents`, `current_roles`, `save_roles`, `run_checks`, `live_run`, `CheckLine` (Task 5); `WhylineConsoleApp._launch_relay(["start"])` (Task 8).
  - Produces: `RelaySetupScreen(root: Path)` dismissing with `"start"` or `None`. Ids: `#rs-implementer`, `#rs-tester`, `#rs-reviewer` (Select), `#rs-backup-<agent>` (Checkbox), `#rs-checks` (Static), `#rs-error`, buttons `#rs-check`, `#rs-start`, `#rs-cancel`.

  Step 1: Write the failing tests

  Create `tests/console/test_relay_setup_screen.py`:

  ```python
  import pytest

  from whyline.console import relay_ops, tui
  from whyline.console.relay_screens import RelaySetupScreen

  pytestmark = [
      pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
      pytest.mark.asyncio,
  ]


  @pytest.fixture(autouse=True)
  def ops(monkeypatch):
      monkeypatch.setattr(relay_ops, "relay_agents", lambda: ["claude", "codex"])
      monkeypatch.setattr(relay_ops, "current_roles", lambda root: {
          "implementer": "claude", "tester": "codex", "reviewer": "codex", "backup": ["claude"]})
      monkeypatch.setattr(relay_ops, "live_run", lambda root: None)
      saved = []
      monkeypatch.setattr(relay_ops, "save_roles",
                          lambda root, i, t, r, b: saved.append((i, t, r, b)))
      return saved


  def _checks(*statuses):
      return lambda root: [relay_ops.CheckLine(s, f"{s} message", "the fix" if s == "FAIL" else None)
                           for s in statuses]


  async def _open(app, pilot):
      results = []
      app.push_screen(RelaySetupScreen(app.session.root), results.append)
      await pilot.pause()
      return app.screen, results


  async def _wait_for(pilot, condition, what):
      for _ in range(100):
          if condition():
              return
          await pilot.pause(0.05)
      raise AssertionError(f"never happened: {what}")


  def _checks_text(screen):
      return str(screen.query_one("#rs-checks", tui.Static).renderable)


  async def test_fields_are_prefilled_from_the_current_config(tmp_path):
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          assert screen.query_one("#rs-implementer", tui.Select).value == "claude"
          assert screen.query_one("#rs-tester", tui.Select).value == "codex"
          assert screen.query_one("#rs-backup-claude", tui.Checkbox).value
          assert not screen.query_one("#rs-backup-codex", tui.Checkbox).value
          assert screen.query_one("#rs-start", tui.Button).disabled


  async def test_a_clean_check_saves_roles_and_enables_start(tmp_path, monkeypatch, ops):
      monkeypatch.setattr(relay_ops, "run_checks", _checks("ok", "warn"))
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, results = await _open(app, pilot)
          screen.query_one("#rs-implementer", tui.Select).value = "codex"
          await pilot.click("#rs-check")
          await _wait_for(pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start")
          assert "warn  warn message" in _checks_text(screen)
          await pilot.click("#rs-start")
          await pilot.pause()
      assert ops == [("codex", "codex", "codex", ["claude"])]
      assert results == ["start"]


  async def test_a_failing_check_keeps_start_disabled_and_shows_the_fix(tmp_path, monkeypatch):
      monkeypatch.setattr(relay_ops, "run_checks", _checks("ok", "FAIL"))
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          await pilot.click("#rs-check")
          await _wait_for(pilot, lambda: "FAIL" in _checks_text(screen), "checks")
          assert "fix: the fix" in _checks_text(screen)
          assert screen.query_one("#rs-start", tui.Button).disabled


  async def test_changing_a_field_after_a_check_disables_start_again(tmp_path, monkeypatch):
      monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          await pilot.click("#rs-check")
          await _wait_for(pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start")
          screen.query_one("#rs-reviewer", tui.Select).value = "claude"
          await pilot.pause()
          assert screen.query_one("#rs-start", tui.Button).disabled
          assert _checks_text(screen) == ""


  async def test_start_stays_disabled_while_a_relay_runs_here(tmp_path, monkeypatch):
      monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
      monkeypatch.setattr(relay_ops, "live_run", lambda root: "T3, codex")
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          await pilot.click("#rs-check")
          await _wait_for(pilot, lambda: "ok" in _checks_text(screen), "checks")
          assert screen.query_one("#rs-start", tui.Button).disabled
          assert "already running here (T3, codex)" in str(
              screen.query_one("#rs-error", tui.Static).renderable)


  async def test_saving_roles_can_fail_visibly(tmp_path, monkeypatch):
      def boom(*a):
          raise RuntimeError("not a git repository")

      monkeypatch.setattr(relay_ops, "save_roles", boom)
      app = tui.WhylineConsoleApp(root=tmp_path)
      async with app.run_test(size=(110, 40)) as pilot:
          screen, _ = await _open(app, pilot)
          await pilot.click("#rs-check")
          await _wait_for(pilot, lambda: "not a git repository" in str(
              screen.query_one("#rs-error", tui.Static).renderable), "error")


  async def test_setup_button_starts_the_relay(tmp_path, monkeypatch):
      monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
      monkeypatch.setattr(relay_ops, "paused_run", lambda root: False)
      launched = []
      app = tui.WhylineConsoleApp(root=tmp_path)
      monkeypatch.setattr(app, "_launch_relay", launched.append)
      async with app.run_test(size=(110, 40)) as pilot:
          app.session.mode = "relay"
          app._sync_mode_indicator()
          await pilot.click("#relay-setup")
          await pilot.pause()
          screen = app.screen
          await pilot.click("#rs-check")
          await _wait_for(pilot, lambda: not screen.query_one("#rs-start", tui.Button).disabled, "start")
          await pilot.click("#rs-start")
          await pilot.pause()
      assert launched == [["start"]]
  ```

  Step 2: Run the tests to verify they fail

  Run: `uv run pytest tests/console/test_relay_setup_screen.py -q`
  Expected: FAIL with `ImportError: cannot import name 'RelaySetupScreen'`.

  Step 3: Add `RelaySetupScreen` to `src/whyline/console/relay_screens.py`

  ```python
  class RelaySetupScreen(ModalScreen):
      """Who implements, tests and reviews; a check (doctor); then Start.
      Start is only enabled by a check with no FAIL, and any edit after a
      check clears it, so nothing starts on settings nobody checked."""

      DEFAULT_CSS = """
      RelaySetupScreen { align: center middle; }
      RelaySetupScreen > Vertical {
          width: 90; max-width: 100%; height: auto; max-height: 100%; padding: 0 2;
          border: thick $accent; background: $surface;
      }
      RelaySetupScreen Horizontal { height: auto; }
      RelaySetupScreen .field-label { width: 18; padding: 1 1 0 0; }
      RelaySetupScreen Select { width: 30; }
      RelaySetupScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; }
      RelaySetupScreen Checkbox:focus { border: none; }
      RelaySetupScreen #rs-results { height: auto; max-height: 12; }
      RelaySetupScreen #rs-error { color: $error; height: auto; }
      RelaySetupScreen #rs-error.-empty { display: none; }
      RelaySetupScreen #rs-buttons { margin-top: 1; }
      RelaySetupScreen #rs-buttons Button { margin-right: 2; }
      """

      ROLES = (("implementer", "Implementer:"), ("tester", "Tester:"), ("reviewer", "Reviewer:"))

      def __init__(self, root: Path) -> None:
          super().__init__()
          self._root = root
          self._agents = relay_ops.relay_agents()
          self._roles = relay_ops.current_roles(root)
          self._token: object | None = None
          self._filling = True  # ignore change events while the form is built

      def compose(self) -> ComposeResult:
          rows = [
              Horizontal(
                  Label(label, classes="field-label"),
                  Select([(a, a) for a in self._agents], value=self._roles[role],
                         allow_blank=False, id=f"rs-{role}"),
              )
              for role, label in self.ROLES
          ]
          backups = [
              Checkbox(agent, value=agent in self._roles["backup"], id=f"rs-backup-{agent}")
              for agent in self._agents
          ]
          yield Vertical(
              Label("Set up: who does what, then check everything is ready."),
              *rows,
              Label("Backup, used when an agent fails:"),
              *backups,
              VerticalScroll(Static("", id="rs-checks"), id="rs-results"),
              Static("", id="rs-error", classes="-empty"),
              Horizontal(
                  Button("Check", id="rs-check", variant="primary"),
                  Button("Start", id="rs-start", variant="success", disabled=True),
                  Button("Cancel", id="rs-cancel"),
                  id="rs-buttons",
              ),
          )

      def on_mount(self) -> None:
          self.call_after_refresh(self._ready)

      def _ready(self) -> None:
          self._filling = False

      def _error(self, text: str) -> None:
          error = self.query_one("#rs-error", Static)
          error.update(text)
          error.set_class(not text, "-empty")

      def _invalidate(self) -> None:
          if self._filling:
              return
          self._token = object()
          self.query_one("#rs-checks", Static).update("")
          self.query_one("#rs-start", Button).disabled = True

      def on_select_changed(self, event: "Select.Changed") -> None:
          self._invalidate()

      def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
          self._invalidate()

      def _chosen(self) -> tuple[str, str, str, list[str]]:
          implementer, tester, reviewer = (
              self.query_one(f"#rs-{role}", Select).value for role, _ in self.ROLES
          )
          backup = [a for a in self._agents if self.query_one(f"#rs-backup-{a}", Checkbox).value]
          return implementer, tester, reviewer, backup

      def on_button_pressed(self, event: "Button.Pressed") -> None:
          event.stop()
          if event.button.id == "rs-cancel":
              self._token = object()
              self.dismiss(None)
          elif event.button.id == "rs-start":
              self.dismiss("start")
          elif event.button.id == "rs-check":
              self._check()

      def _check(self) -> None:
          token = object()
          self._token = token
          self._error("")
          self.query_one("#rs-start", Button).disabled = True
          self.query_one("#rs-checks", Static).update("Checking…")
          root, chosen = self._root, self._chosen()

          def in_thread() -> None:
              try:
                  relay_ops.save_roles(root, *chosen)
                  checks = relay_ops.run_checks(root)
                  running = relay_ops.live_run(root)
              except Exception as error:
                  self.app.call_from_thread(self._check_failed, error, token)
                  return
              self.app.call_from_thread(self._show_checks, checks, running, token)

          self.run_worker(in_thread, thread=True)

      def _check_failed(self, error: Exception, token: object) -> None:
          if token is not self._token:
              return
          self.query_one("#rs-checks", Static).update("")
          self._error(str(error) or error.__class__.__name__)

      def _show_checks(self, checks: list, running: "str | None", token: object) -> None:
          if token is not self._token:
              return
          lines = []
          for check in checks:
              line = f"{check.status:<4}  {check.message}"
              if check.status != "ok" and check.hint:
                  line += f"\n      fix: {check.hint}"
              lines.append(line)
          failures = sum(check.status == "FAIL" for check in checks)
          lines.append("All checks passed." if failures == 0 else f"{failures} problem(s) found.")
          self.query_one("#rs-checks", Static).update("\n".join(lines))
          if running:
              self._error(f"A relay is already running here ({running}).")
          self.query_one("#rs-start", Button).disabled = failures > 0 or bool(running)
  ```

  Step 4: Wire the Set up button in `src/whyline/console/tui.py`

  Replace the Task 6 placeholder `_open_relay_setup` with:

  ```python
      def _open_relay_setup(self) -> None:
          if self._refuse_in_home():
              return
          from whyline.console.relay_screens import RelaySetupScreen

          self.push_screen(RelaySetupScreen(self.session.root), self._setup_done)

      def _setup_done(self, choice: "str | None") -> None:
          if choice == "start":
              self._launch_relay(["start"])
  ```

  Step 5: Run the whole suite

  Run: `uv run pytest -q`
  Expected: all PASS.

  Step 6: Commit

  ```bash
  git add src/whyline/console/relay_screens.py src/whyline/console/tui.py tests/console/test_relay_setup_screen.py
  git commit -m "feat(console): Set up popup assigns roles, checks and starts the relay"
  ```

- [ ] CRS-13: Try it for real, then release whyline 0.3.29

  ## Global Constraints

  - Python `>=3.11`; use `tomllib` for reading TOML. Add no new dependencies to either package.
  - whyline must require `whyline-relay>=0.2.26,<0.3` (both places it appears in `pyproject.toml`).
  - Every commit the relay or console makes on the user's behalf is scoped to its own files (`gitcheck.commit_paths`), never `commit_all` / `git add -A`.
  - Relay role dropdowns list `sorted(whyline_relay.adapters.BUILTIN)` — today `["claude", "codex"]`. Do not hard-code Antigravity or Grok.
  - Console code imports `whyline_relay` lazily inside functions (the existing pattern in `src/whyline/console/adapters.py`), so the console still imports without it.
  - Console widget lookups on the main screen go through `WhylineConsoleApp._main(selector, type)`, never `App.query_one` (a dialog may be on top).
  - Relay output goes to `.whyline/relay/logs/console-run.log` (already git-ignored by the relay under `.whyline/relay/logs/`), never a pipe.
  - Plan and Set up refuse in the home-directory repo with the existing `_HOME_REFUSAL` text from `src/whyline/console/repl.py`.
  - After each task, record the decision per `AGENTS.md`:
    `whyline note "<decision>" --because "<why>" --file <path> --actor <your agent name> --role implementer --task CRS-<task number>`.
  - Commit messages end with a blank line and your own `Co-Authored-By:` line if your harness adds one. Do not push or tag except in Tasks 4 and 13.

  **Files:**
  - Modify: `pyproject.toml` (`version = "0.3.29"`), `uv.lock`
  - Create: `docs/releases/v0.3.29.md`

  Step 1: Manual run in a scratch project

  ```bash
  uv tool install --force --editable /Users/anish/agentdock
  mkdir -p /tmp/relay-console-try && cd /tmp/relay-console-try
  git init -q && printf '# Todo app\nA CLI todo list with add, list, done.\n' > PRD.md
  git add -A && git commit -qm init && whyline init
  whyline console
  ```

  In the console: click **Relay** (it stays open and says to use Plan). Click **Plan** → Source "Draft from a description" → description "Build what PRD.md describes", reference `PRD.md` → **Make the plan** → watch the progress lines → read the draft → **Approve**. Click **Set up** → leave codex / claude / claude → **Check** → **Start**. Watch `relay · …` lines, then click **Stop** and confirm the run pauses and **Resume** becomes clickable. Press ctrl+q while it runs and confirm the "Leave it running?" prompt. Write down anything that looked wrong and fix it (with a test) before continuing.

  Step 2: Bump the version and write the release notes

  ```bash
  cd /Users/anish/agentdock
  sed -i '' 's/^version = "0.3.28"/version = "0.3.29"/' pyproject.toml
  uv lock
  ```

  Create `docs/releases/v0.3.29.md`:

  ```markdown
  # whyline 0.3.29

  Relay setup moves into the console. Requires whyline-relay 0.2.26.

  ## What's changed

  - **Relay mode has Plan, Set up and Resume buttons** (greyed out in
    Command and Chat). Relay mode no longer closes the console to run the
    terminal setup wizard.
  - **Plan** makes `plan.md` three ways: paste one, draft one from a
    description plus reference documents (a PRD, say), or turn a brainstorm
    into one -- a new brainstorm, or one already in `docs/brainstorm/`.
    Drafts are shown for review: approve, or request changes and get a new
    draft. Approving commits only `plan.md`.
  - **Set up** picks the implementer, tester, reviewer and backups, runs the
    relay's checks, and enables Start only when nothing failed.
  - **The relay runs as its own process** with its progress streaming into
    the transcript. Stop lets the current agent finish, then pauses; Resume
    carries on. Quitting while it runs asks whether to leave it running.
    Typed `start` and `resume` work the same way.

  ## Upgrading

  ```bash
  uv tool upgrade --refresh whyline
  ```
  ```

  Step 3: Test, commit, tag, push, confirm

  ```bash
  uv run pytest -q
  git add pyproject.toml uv.lock docs/releases/v0.3.29.md .whyline/decisions.md
  git commit -m "chore: release whyline 0.3.29 (relay Plan and Set up in the console)"
  git tag v0.3.29
  git push origin main v0.3.29
  ```

  Then check `gh run list --limit 3` until the `release` run for `v0.3.29` is `success`, and
  `curl -s https://pypi.org/simple/whyline/ | grep -o 'whyline-0.3.29[^"#<]*' | sort -u` shows the wheel and sdist. On failure: `gh run view <id> --log-failed`, fix, `git tag -f v0.3.29 && git push -f origin v0.3.29`.

  Step 4: Install the release

  ```bash
  uv tool install --force --refresh --index-url https://pypi.org/simple 'whyline==0.3.29'
  ```
