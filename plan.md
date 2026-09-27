# Account Capability Gating — active relay plan

- [ ] ACG-1: `account.py` -- detection, availability, manual override


  **Files:**
  - Modify: `src/whyline/account.py`
  - Test: `tests/test_account.py`

  **Interfaces:**
  - Produces: `detect_antigravity(which=None) -> dict` and `detect_grok(which=None) -> dict`, each returning `{"plan": None, "available": bool, "reason": str | None}`. `detect() -> dict` now returns all four agents, each carrying an `available` key (codex/claude: `plan != "unknown"`; antigravity/grok: as returned by their own detect function). `refresh() -> dict` -- re-runs `detect()`, stamps `detected_at`, preserves any agent whose *existing* global record has `manual: True` (keeping that record's own `available`/`manual` instead of the fresh value), saves globally, and returns the merged result. `ensure_detected() -> dict | None` -- calls `refresh()` only if `load_global()` is currently `None` (the very first time anything needs it, anywhere); returns the freshly detected data if it just ran, or `None` if data already existed. `set_manual(agent: str, available: bool) -> None` -- sets `{"available": available, "manual": True}` on `agent`'s global record (creating it if absent), leaving every other agent's record untouched. `available_agents(root: Path) -> set[str]` -- calls `ensure_detected()` first, then returns the subset of `("codex", "claude", "antigravity", "grok")` whose record (repo-confirmed if present, else global) has `available is True`; returns an empty set if neither exists.

  - **Step 1: Write the failing tests**

  Add to `tests/test_account.py`:

  ```python
  import shutil


  def test_detect_antigravity_available_when_on_path():
      result = account.detect_antigravity(which=lambda name: "/usr/bin/agy")
      assert result == {"plan": None, "available": True, "reason": None}


  def test_detect_antigravity_unavailable_when_not_on_path():
      result = account.detect_antigravity(which=lambda name: None)
      assert result["available"] is False
      assert "reason" in result and result["reason"]


  def test_detect_grok_available_when_on_path():
      result = account.detect_grok(which=lambda name: "/usr/bin/grok")
      assert result == {"plan": None, "available": True, "reason": None}


  def test_detect_grok_unavailable_when_not_on_path():
      result = account.detect_grok(which=lambda name: None)
      assert result["available"] is False


  def test_detect_uses_real_shutil_which_by_default(monkeypatch):
      # Regression proof for the "resolve inside the function body" rule:
      # monkeypatching shutil.which itself (not passing `which=`) must still
      # be observed, which only holds if `which` is not captured as a bound
      # default argument at definition time.
      monkeypatch.setattr(shutil, "which", lambda name: None)
      assert account.detect_antigravity()["available"] is False
      assert account.detect_grok()["available"] is False


  def test_detect_now_includes_all_four_agents_with_availability(monkeypatch):
      monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
      monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
      monkeypatch.setattr(
          account, "detect_antigravity", lambda: {"plan": None, "available": True, "reason": None}
      )
      monkeypatch.setattr(
          account, "detect_grok", lambda: {"plan": None, "available": False, "reason": "grok not found on PATH"}
      )
      result = account.detect()
      assert result["codex"] == {"plan": "plus", "available": True}
      assert result["claude"] == {"plan": "pro", "available": True}
      assert result["antigravity"] == {"plan": None, "available": True, "reason": None}
      assert result["grok"]["available"] is False


  def test_detect_marks_unknown_plan_as_unavailable(monkeypatch):
      monkeypatch.setattr(
          account, "detect_codex", lambda: {"plan": "unknown", "reason": "no auth file"}
      )
      monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
      monkeypatch.setattr(account, "detect_antigravity", lambda: {"plan": None, "available": False, "reason": "not found"})
      monkeypatch.setattr(account, "detect_grok", lambda: {"plan": None, "available": False, "reason": "not found"})
      result = account.detect()
      assert result["codex"]["available"] is False


  def test_refresh_saves_globally_and_stamps_detected_at(monkeypatch, tmp_path):
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
      monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
      monkeypatch.setattr(account, "detect_antigravity", lambda: {"plan": None, "available": True, "reason": None})
      monkeypatch.setattr(account, "detect_grok", lambda: {"plan": None, "available": False, "reason": "not found"})
      result = account.refresh()
      assert result["codex"]["available"] is True
      assert "detected_at" in result["codex"]
      assert account.load_global() == result


  def test_refresh_preserves_a_manual_override(monkeypatch, tmp_path):
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      account.save_global(
          {"grok": {"plan": None, "available": True, "manual": True, "reason": None}}
      )
      monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
      monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
      monkeypatch.setattr(account, "detect_antigravity", lambda: {"plan": None, "available": False, "reason": "not found"})
      monkeypatch.setattr(
          account, "detect_grok", lambda: {"plan": None, "available": False, "reason": "not found on PATH"}
      )
      result = account.refresh()
      # Fresh detection says grok is unavailable, but the prior manual
      # override said otherwise -- the override wins.
      assert result["grok"]["available"] is True
      assert result["grok"]["manual"] is True


  def test_ensure_detected_runs_only_once(monkeypatch, tmp_path):
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      calls = []
      monkeypatch.setattr(account, "refresh", lambda: calls.append(1) or {"codex": {"available": True}})
      first = account.ensure_detected()
      assert first is not None
      assert calls == [1]
      account.save_global({"codex": {"available": True}})
      second = account.ensure_detected()
      assert second is None
      assert calls == [1]  # refresh() was not called again


  def test_set_manual_creates_and_overrides(tmp_path, monkeypatch):
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      account.set_manual("antigravity", True)
      data = account.load_global()
      assert data["antigravity"] == {"available": True, "manual": True}
      account.set_manual("antigravity", False)
      assert account.load_global()["antigravity"] == {"available": False, "manual": True}


  def test_set_manual_does_not_disturb_other_agents(tmp_path, monkeypatch):
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      account.save_global({"codex": {"plan": "plus", "available": True}})
      account.set_manual("grok", True)
      data = account.load_global()
      assert data["codex"] == {"plan": "plus", "available": True}
      assert data["grok"] == {"available": True, "manual": True}


  def test_available_agents_from_global_data(tmp_path, monkeypatch):
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      account.save_global({
          "codex": {"plan": "plus", "available": True},
          "claude": {"plan": "unknown", "available": False},
          "antigravity": {"plan": None, "available": True},
          "grok": {"plan": None, "available": False},
      })
      assert account.available_agents(tmp_path) == {"codex", "antigravity"}


  def test_available_agents_prefers_repo_confirmation_over_global(tmp_path, monkeypatch):
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      account.save_global({"codex": {"available": True}, "claude": {"available": True}})
      account.save_repo(tmp_path, {"codex": {"available": True}, "claude": {"available": False}})
      assert account.available_agents(tmp_path) == {"codex"}


  def test_available_agents_empty_when_detection_itself_raises(tmp_path, monkeypatch):
      # account.py's own module docstring already promises "never raises: ...
      # so one agent's detection problem never blocks the other's" -- that
      # guarantee must extend to a total failure of refresh() itself (e.g. a
      # disk error writing the global file), not just to one agent's own
      # detect_x() call. No caller of available_agents() (cmd_model,
      # run_entry_menu) catches anything, so this has to hold here.
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      monkeypatch.setattr(account, "refresh", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
      assert account.available_agents(tmp_path) == set()


  def test_ensure_detected_returns_none_when_refresh_raises(tmp_path, monkeypatch):
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      monkeypatch.setattr(account, "refresh", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
      assert account.ensure_detected() is None
  ```

  - **Step 2: Run the tests to verify they fail**

  Run: `uv run pytest tests/test_account.py -v`
  Expected: FAIL on every new test (`AttributeError: module 'account' has no
  attribute 'detect_antigravity'`, etc.), and the pre-existing
  `test_detect_combines_both_agents` and the two
  `test_detect_cross_agent_isolation_*` tests will *also* start failing once
  you make the Step 3 changes below (their exact-equality assertions predate
  `available` and the two new agents) -- that's expected, fixed in Step 5.

  - **Step 3: Implement**

  In `src/whyline/account.py`:

  1. Add `import shutil` to the existing imports.

  2. Add, right after `detect_claude`:

     ```python
     def detect_antigravity(which=None) -> dict:
         """PATH-only: Antigravity has no reliable non-interactive login check
         (see preflight.py's own note in whyline-relay). "available" means
         "installed", not "subscribed" -- the user confirmed this bar."""
         which = which if which is not None else shutil.which
         found = which("agy") is not None
         return {
             "plan": None,
             "available": found,
             "reason": None if found else "agy not found on PATH",
         }


     def detect_grok(which=None) -> dict:
         """PATH-only, for the same reason as detect_antigravity."""
         which = which if which is not None else shutil.which
         found = which("grok") is not None
         return {
             "plan": None,
             "available": found,
             "reason": None if found else "grok not found on PATH",
         }
     ```

  3. Replace `detect()`:

     ```python
     def detect() -> dict:
         try:
             codex = detect_codex()
         except Exception as error:
             codex = {"plan": "unknown", "reason": f"could not detect codex: {error}"}
         codex["available"] = codex.get("plan") != "unknown"

         try:
             claude = detect_claude()
         except Exception as error:
             claude = {"plan": "unknown", "reason": f"could not detect claude: {error}"}
         claude["available"] = claude.get("plan") != "unknown"

         try:
             antigravity = detect_antigravity()
         except Exception as error:
             antigravity = {
                 "plan": None, "available": False,
                 "reason": f"could not detect antigravity: {error}",
             }

         try:
             grok = detect_grok()
         except Exception as error:
             grok = {
                 "plan": None, "available": False,
                 "reason": f"could not detect grok: {error}",
             }

         return {"codex": codex, "claude": claude, "antigravity": antigravity, "grok": grok}
     ```

  4. Add, right after `detect()` (needs `import datetime` -- add it to the
     existing imports):

     ```python
     def refresh() -> dict:
         """Re-runs detect(), stamps detected_at, saves it globally, and
         returns the merged result. An agent whose existing global record
         has manual=True keeps that record's own available/manual instead of
         the fresh value -- an explicit whyline account enable/disable must
         survive a later `whyline account detect`."""
         existing = load_global() or {}
         detected = detect()
         now = datetime.datetime.now().astimezone().isoformat()
         for agent, info in detected.items():
             info["detected_at"] = now
             prior = existing.get(agent)
             if isinstance(prior, dict) and prior.get("manual"):
                 info["available"] = prior["available"]
                 info["manual"] = True
         save_global(detected)
         return detected


     def ensure_detected() -> dict | None:
         """Runs refresh() only if no global account data exists yet -- the
         very first time anything needs it, anywhere. Returns the freshly
         detected data if it just ran, None if data already existed, or None
         if refresh() itself fails for any reason (this module's own
         docstring already promises detection never blocks anything else;
         a total refresh() failure -- e.g. a disk error saving the global
         file -- must not crash whichever caller just wanted to know what's
         available, matching detect()'s existing per-agent guarantee one
         level up)."""
         if load_global() is not None:
             return None
         try:
             return refresh()
         except Exception:
             return None


     def set_manual(agent: str, available: bool) -> None:
         """Explicitly overrides `agent`'s availability -- the "add or
         remove" surface -- surviving future refresh() calls until changed
         again. Every other agent's record is left untouched."""
         data = load_global() or {}
         data[agent] = {"available": available, "manual": True}
         save_global(data)


     def available_agents(root: Path) -> set[str]:
         """Every agent currently considered available: repo-confirmed data
         if present, else global data, else nothing. Always ensures
         detection has run at least once first (see ensure_detected)."""
         ensure_detected()
         data = load_repo(root)
         if data is None:
             data = load_global()
         if data is None:
             return set()
         return {
             agent
             for agent in ("codex", "claude", "antigravity", "grok")
             if isinstance(data.get(agent), dict) and data[agent].get("available") is True
         }
     ```

  - **Step 4: Run the new tests to verify they pass**

  Run: `uv run pytest tests/test_account.py -v`
  Expected: the new tests pass; three pre-existing tests still fail (see Step 5).

  - **Step 5: Fix the three pre-existing tests whose exact-equality assertions predate this change**

  In `tests/test_account.py`:

  - `test_detect_combines_both_agents`: its monkeypatched `detect_codex`/
    `detect_claude` return bare `{"plan": "plus"}`/`{"plan": "pro"}`, and it
    asserts `account.detect() == {"codex": {"plan": "plus"}, "claude":
    {"plan": "pro"}}` -- with no `available` key and no antigravity/grok.
    Update it to also monkeypatch `detect_antigravity`/`detect_grok`, and
    update the expected dict to include `available` on every agent:

    ```python
    def test_detect_combines_all_four_agents(monkeypatch, tmp_path):
        monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
        monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
        monkeypatch.setattr(
            account, "detect_antigravity",
            lambda: {"plan": None, "available": True, "reason": None},
        )
        monkeypatch.setattr(
            account, "detect_grok",
            lambda: {"plan": None, "available": False, "reason": "grok not found on PATH"},
        )
        assert account.detect() == {
            "codex": {"plan": "plus", "available": True},
            "claude": {"plan": "pro", "available": True},
            "antigravity": {"plan": None, "available": True, "reason": None},
            "grok": {"plan": None, "available": False, "reason": "grok not found on PATH"},
        }
    ```

    (renamed from `test_detect_combines_both_agents` since it now covers all
    four -- delete the old name, don't keep both)

  - `test_detect_cross_agent_isolation_codex_failure_does_not_block_claude`
    and `test_detect_cross_agent_isolation_codex_exception_does_not_block_claude`:
    each asserts `result["claude"] == {"auth_method": "claude.ai", "plan":
    "pro"}`. Add `"available": True` to both expected dicts (claude's plan is
    `"pro"`, not `"unknown"`, so `available` is `True`) -- no other change
    needed in either test.

  - **Step 6: Run the whole test file, then the whole suite**

  Run: `uv run pytest tests/test_account.py -v`
  Expected: PASS (every test in the file)

  Run: `uv run pytest -q`
  Expected: PASS

  - **Step 7: Commit**

  ```bash
  git add src/whyline/account.py tests/test_account.py
  git commit -m "feat: detect antigravity/grok availability; manual override; available_agents()"
  ```

  ---


- [ ] ACG-2: `cli.py` -- `enable`/`disable`, extended `status`, gated `whyline model`, first-run detection


  **Files:**
  - Modify: `src/whyline/cli.py`
  - Test: `tests/test_account_cli.py`, `tests/test_model_cli.py`, `tests/test_cli.py` (wherever `run_entry_menu` is exercised -- check both `tests/test_cli.py` and `tests/test_cli_chat_delegation.py` first, since `run_entry_menu` tests could be in either)

  **Interfaces:**
  - Consumes: `account.detect`, `account.refresh`, `account.ensure_detected`, `account.set_manual`, `account.available_agents` (Task 1).
  - Produces: `whyline account enable <agent>` / `disable <agent>` (new); `whyline account status`/bare `whyline account` unchanged in flow but `_print_account` now shows all four agents' availability; `whyline model`'s interactive wizard only asks about available agents; `run_entry_menu` triggers detection automatically the first time it's ever called with no global account data, printing a short summary before "Chat or relay?".

  - **Step 1: Write the failing tests**

  First, read `_require_repo()` in `src/whyline/cli.py` (used throughout the
  file) so your new tests match its existing error-handling convention if you
  need it.

  Add to `tests/test_account_cli.py`:

  ```python
  def test_enable_sets_manual_availability(repo, capsys, monkeypatch, tmp_path):
      home = tmp_path / "home"
      monkeypatch.setattr(account.paths.Path, "home", lambda: home)
      code, out = run_in(repo, ["account", "enable", "grok"], capsys)
      assert code == cli.EXIT_OK
      assert account.load_global()["grok"] == {"available": True, "manual": True}


  def test_disable_sets_manual_unavailability(repo, capsys, monkeypatch, tmp_path):
      home = tmp_path / "home"
      monkeypatch.setattr(account.paths.Path, "home", lambda: home)
      account.save_global({"codex": {"plan": "plus", "available": True}})
      code, out = run_in(repo, ["account", "disable", "codex"], capsys)
      assert code == cli.EXIT_OK
      assert account.load_global()["codex"] == {"available": False, "manual": True}


  def test_enable_and_disable_do_not_require_being_in_a_repo(
      capsys, monkeypatch, tmp_path
  ):
      home = tmp_path / "home"
      monkeypatch.setattr(account.paths.Path, "home", lambda: home)
      outside = tmp_path / "not-a-repo"
      outside.mkdir()
      previous = os.getcwd()
      os.chdir(outside)
      try:
          code = cli.main(["account", "enable", "grok"])
      finally:
          os.chdir(previous)
      assert code == cli.EXIT_OK


  def test_status_shows_all_four_agents_with_availability(repo, capsys):
      account.save_repo(
          repo.path,
          {
              "codex": {"plan": "plus", "available": True},
              "claude": {"plan": "unknown", "available": False, "reason": "not logged in"},
              "antigravity": {"plan": None, "available": True},
              "grok": {"plan": None, "available": False, "manual": True},
              "confirmed": True,
          },
      )
      code, out = run_in(repo, ["account", "status"], capsys)
      assert code == cli.EXIT_OK
      assert "codex" in out and "available" in out
      assert "antigravity" in out
      assert "grok" in out
      assert "manually set" in out  # grok's manual override is called out
  ```

  Note: `test_enable_and_disable_do_not_require_being_in_a_repo` deliberately
  does not use the `repo` fixture, since it's proving the opposite of what
  that fixture sets up.

  Add to `tests/test_model_cli.py`:

  ```python
  def _mark_all_available(monkeypatch, tmp_path, home):
      monkeypatch.setattr(account.paths.Path, "home", lambda: home)
      account.save_global({
          agent: {"plan": None, "available": True}
          for agent in ("codex", "claude", "antigravity", "grok")
      })


  def test_interactive_model_selection_only_offers_available_agents(
      repo, capsys, monkeypatch, tmp_path
  ):
      from whyline import account
      home = tmp_path / "home"
      monkeypatch.setattr(account.paths.Path, "home", lambda: home)
      account.save_global({
          "codex": {"plan": "plus", "available": True},
          "claude": {"plan": "unknown", "available": False},
          "antigravity": {"plan": None, "available": False},
          "grok": {"plan": None, "available": False},
      })
      code, out = run_in(
          repo, ["model"], capsys, monkeypatch, input_answers=["gpt-5-codex"]
      )
      assert code == cli.EXIT_OK
      assert model.load(repo.path) == {"codex": "gpt-5-codex"}
      assert "claude" not in out.lower() or "Model for claude" not in out


  def test_interactive_model_selection_with_nothing_available_says_so(
      repo, capsys, monkeypatch, tmp_path
  ):
      from whyline import account
      home = tmp_path / "home"
      monkeypatch.setattr(account.paths.Path, "home", lambda: home)
      account.save_global({
          agent: {"plan": None, "available": False}
          for agent in ("codex", "claude", "antigravity", "grok")
      })
      code, out = run_in(repo, ["model"], capsys)
      assert code == cli.EXIT_ERROR
      assert "whyline account detect" in out or "whyline account enable" in out
  ```

  Now update the two *existing* tests that assumed no filtering ever happens
  (`test_interactive_model_selection_writes_all_four_answers` and
  `test_interactive_model_selection_offers_grok`): both need
  `_mark_all_available(monkeypatch, tmp_path, home)` called before `run_in`,
  with `from whyline import account` added to the file's imports, since
  without account data present, `cmd_model` now shows the "nothing
  available" message instead of looping through four agents. Add the
  `monkeypatch, tmp_path` fixture parameters to both test signatures if they
  don't already have them.

  Now find wherever `run_entry_menu` is tested (`grep -rn "run_entry_menu"
  tests/`) and add:

  ```python
  def test_entry_menu_runs_detection_on_the_very_first_call(monkeypatch, tmp_path, capsys):
      from whyline import account, cli
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
      monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
      monkeypatch.setattr(
          account, "detect_antigravity", lambda: {"plan": None, "available": False, "reason": "not found"}
      )
      monkeypatch.setattr(
          account, "detect_grok", lambda: {"plan": None, "available": False, "reason": "not found"}
      )
      answers = iter(["chat", "chat"])
      cli.run_entry_menu(
          which=lambda name: "/usr/bin/whyline-relay",
          exec_fn=lambda *a: None,
          input_fn=lambda prompt="": next(answers),
          print_fn=lambda *a, **k: None,
      )
      assert account.load_global() is not None
      assert account.load_global()["codex"]["plan"] == "plus"


  def test_entry_menu_does_not_redetect_on_a_later_call(monkeypatch, tmp_path):
      from whyline import account, cli
      monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
      account.save_global({"codex": {"plan": "plus", "available": True}})
      calls = []
      monkeypatch.setattr(account, "refresh", lambda: calls.append(1) or {})
      answers = iter(["chat", "chat"])
      cli.run_entry_menu(
          which=lambda name: "/usr/bin/whyline-relay",
          exec_fn=lambda *a: None,
          input_fn=lambda prompt="": next(answers),
          print_fn=lambda *a, **k: None,
      )
      assert calls == []
  ```

  - **Step 2: Run the tests to verify they fail**

  Run: `uv run pytest tests/test_account_cli.py tests/test_model_cli.py -v`
  (and wherever you added the two entry-menu tests)
  Expected: FAIL (`enable`/`disable` aren't wired into the parser yet, `cmd_model` doesn't filter yet, `run_entry_menu` doesn't call detection yet).

  - **Step 3: Wire `enable`/`disable` into the parser and `cmd_account`**

  In `_add_account` (`src/whyline/cli.py`), add after the existing two
  `account_sub.add_parser(...)` lines:

  ```python
      enable_parser = account_sub.add_parser(
          "enable", help="Manually mark an agent as available"
      )
      enable_parser.add_argument("agent", choices=tuple(runner.AGENTS))
      disable_parser = account_sub.add_parser(
          "disable", help="Manually mark an agent as unavailable"
      )
      disable_parser.add_argument("agent", choices=tuple(runner.AGENTS))
  ```

  Replace `cmd_account`'s body:

  ```python
  def cmd_account(args: argparse.Namespace) -> int:
      from whyline import account

      if args.account_command == "detect":
          detected = account.refresh()
          _print_account(detected)
          return EXIT_OK
      if args.account_command == "enable":
          account.set_manual(args.agent, True)
          print(f"{args.agent}: manually marked available.")
          return EXIT_OK
      if args.account_command == "disable":
          account.set_manual(args.agent, False)
          print(f"{args.agent}: manually marked unavailable.")
          return EXIT_OK

      root = _require_repo()
      repo_data = account.load_repo(root)
      if repo_data is not None:
          _print_account(repo_data)
          return EXIT_OK
      global_data = account.load_global()
      if global_data is None:
          print("No detection yet. Run: whyline account detect", file=sys.stderr)
          return EXIT_ERROR
      _print_account(global_data)
      try:
          answer = input("Use this for this repo? [Y/n] ").strip().lower()
      except EOFError:
          answer = "y"
      confirmed = answer not in ("n", "no")
      to_save = dict(global_data)
      to_save["confirmed"] = confirmed
      account.save_repo(root, to_save)
      return EXIT_OK
  ```

  Note two deliberate changes from today's code, both worth a `whyline note`
  once this task is done: (1) `root = _require_repo()` moved past the
  `detect`/`enable`/`disable` early returns -- none of those three need a
  repo, and requiring one today was accidental, not a documented decision;
  (2) `detect`'s own inline `datetime`/`detected_at`/`save_global` logic
  moved into `account.refresh()` (Task 1), so `cmd_account` no longer needs
  `import datetime` for this -- check whether anything else in `cli.py` still
  uses the `datetime` import before removing it.

  - **Step 4: Extend `_print_account`**

  Replace it:

  ```python
  def _print_account(data: dict) -> None:
      for agent in ("codex", "claude", "antigravity", "grok"):
          info = data.get(agent) if isinstance(data.get(agent), dict) else {}
          plan = info.get("plan")
          available = info.get("available", False)
          if plan is None and agent in ("codex", "claude"):
              base = "no subscription tier (using an API key)"
          elif plan == "unknown":
              base = f"unknown ({info.get('reason', 'no reason given')})"
          elif plan:
              base = plan
          else:
              base = "installed" if available else "not installed"
          status = "available" if available else "not available"
          note = " (manually set)" if info.get("manual") else ""
          print(f"{agent}: {base} -- {status}{note}")
  ```

  - **Step 5: Gate `cmd_model`'s interactive wizard**

  Replace the interactive-loop portion of `cmd_model` (everything after the
  `set`/`status` early returns):

  ```python
      account.ensure_detected()
      available = account.available_agents(root)
      if not available:
          print(
              "No agents detected as available. Run: whyline account detect "
              "(or whyline account enable <agent> to add one manually).",
              file=sys.stderr,
          )
          return EXIT_ERROR

      repo_account = account.load_repo(root)
      for agent in ("codex", "claude", "antigravity", "grok"):
          if agent not in available:
              continue
          if repo_account is not None and agent in repo_account:
              plan = repo_account[agent].get("plan")
              if plan:
                  print(f"{agent} -- {plan}")
          if agent == "antigravity":
              print(
                  "Note: Antigravity is safe here for `whyline run`, but not "
                  "currently safe for any unattended whyline-relay role -- see README."
              )
          current_value = model.load(root).get(agent, "(default)")
          print(f"Current: {current_value}")
          try:
              answer = input(f"Model for {agent} (blank to keep default): ").strip()
          except EOFError:
              answer = ""
          if answer:
              model.set_one(root, agent, answer)
      return EXIT_OK
  ```

  - **Step 6: Wire first-run detection into `run_entry_menu`**

  In `run_entry_menu`, right after the `if which("whyline-relay") is None:
  return False` line, add:

  ```python
      from whyline import account

      freshly_detected = account.ensure_detected()
      if freshly_detected is not None:
          print_fn("First run: checking which agents you have access to...")
          for agent in ("codex", "claude", "antigravity", "grok"):
              info = freshly_detected.get(agent, {})
              state = "available" if info.get("available") else "not available"
              print_fn(f"  {agent}: {state}")
  ```

  before the existing `choice = input_fn("Chat or relay? [chat]: ")...` line.

  - **Step 7: Run the tests to verify they pass**

  Run: `uv run pytest tests/test_account_cli.py tests/test_model_cli.py -v`
  (and the entry-menu test file)
  Expected: PASS

  - **Step 8: Run the whole suite**

  Run: `uv run pytest -q`
  Expected: PASS

  - **Step 9: Commit**

  ```bash
  git add src/whyline/cli.py tests/test_account_cli.py tests/test_model_cli.py
  git commit -m "feat: whyline account enable/disable; gate whyline model and the entry menu by availability"
  ```

  ---

  ## Final check

  After Task 2's commit, run `uv run pytest -q` one more time and manually
  try the flow: in a scratch repo with no `~/.whyline/account.json` (rename
  it aside if you have one locally), run bare `whyline` and confirm it prints
  a detection summary before asking "Chat or relay?"; run `whyline account
  disable claude` then `whyline model` and confirm claude is no longer asked
  about; run `whyline account enable claude` and confirm it's back.
