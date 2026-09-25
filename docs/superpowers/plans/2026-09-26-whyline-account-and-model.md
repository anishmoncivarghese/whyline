# Account Detection and Model Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `whyline account` (detects which plan/tier `codex` and `claude` are actually authenticated under, once per machine, confirmed once per repo) and `whyline model` (a per-repo model selector for `codex`/`claude`/`antigravity`, showing the detected plan as context), and teach `whyline run` to use the selected model.

**Architecture:** Two new, small modules (`account.py`, `model.py`) hold all detection/storage logic with no CLI parsing in them, matching how `runner.py`/`hooks.py` already separate logic from argument parsing. `runner.py`'s `build_argv`/`launch` gain an explicit `model` parameter (never resolving it themselves — that stays `cmd_run`'s job), preserving their existing purity. Two new files, gitignored, hold state: `~/.whyline/account.json` (global, whyline's first-ever cross-repo file) and `.whyline/{account,model}.json` (per repo).

**Tech Stack:** Python 3.11+, stdlib only (`json`, `base64`, `subprocess`, `pathlib`). No new dependencies (`whyline`'s `dependencies = []` is unchanged).

**Spec:** `docs/superpowers/specs/2026-09-25-account-and-model-selector-design.md`, sections 5.1-5.3 and 5.6 (this plan's scope), plus M1-M4, M7-M10. Section 5.4 (whyline-relay's read-only integration) is a separate plan, depending on this one shipping first.

## Global Constraints

- No new runtime dependency — stdlib only.
- Never store, log, or return a raw auth token — only the derived plan string and auth method (M2).
- Detection failure for one agent never blocks the other (M7) — always returns `{"plan": "unknown", "reason": "..."}`, never raises.
- Corrupt/malformed `account.json`/`model.json` reads as absent, never a crash (M8).
- Both per-repo files (`.whyline/account.json`, `.whyline/model.json`) are gitignored (M9).
- The detected plan is informational only — never filters or blocks a model choice (M4).
- `whyline model`'s Antigravity prompt carries the unattended-use caveat (M10) — this is display-only, never a block; `whyline run antigravity` stays fully supported.
- Every existing test must still pass after every task.

---

### Task 1: `paths.py` — a global directory, alongside the existing repo-scoped ones

**Files:**
- Modify: `src/whyline/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Produces: `paths.global_whyline_dir() -> Path` (`~/.whyline/`), `paths.global_account_path() -> Path`, `paths.account_path(root: Path) -> Path`, `paths.model_path(root: Path) -> Path`. Tasks 2 and 4 are the only callers.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_paths.py`:

```python
def test_global_whyline_dir_is_under_home(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    assert paths.global_whyline_dir() == tmp_path / ".whyline"


def test_global_account_path(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    assert paths.global_account_path() == tmp_path / ".whyline" / "account.json"


def test_account_path_is_repo_scoped(repo):
    assert paths.account_path(repo.path) == repo.path / ".whyline" / "account.json"


def test_model_path_is_repo_scoped(repo):
    assert paths.model_path(repo.path) == repo.path / ".whyline" / "model.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_paths.py -v`
Expected: FAIL — `AttributeError: module 'whyline.paths' has no attribute 'global_whyline_dir'`.

- [ ] **Step 3: Implement**

In `src/whyline/paths.py`, add after `DIR_NAME = ".whyline"`:

```python
GLOBAL_DIR_NAME = ".whyline"
```

Add at the end of the file:

```python
def global_whyline_dir() -> Path:
    return Path.home() / GLOBAL_DIR_NAME


def global_account_path() -> Path:
    return global_whyline_dir() / "account.json"


def account_path(root: Path) -> Path:
    return whyline_dir(root) / "account.json"


def model_path(root: Path) -> Path:
    return whyline_dir(root) / "model.json"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_paths.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline/paths.py tests/test_paths.py
git commit -m "feat: paths gains a global (home-directory) location, alongside repo-scoped ones"
```

---

### Task 2: `account.py` — detection and storage

**Files:**
- Create: `src/whyline/account.py`
- Test: `tests/test_account.py`

**Interfaces:**
- Consumes: `paths.global_account_path`, `paths.account_path` (Task 1).
- Produces: `account.detect_codex(auth_path=None) -> dict`, `account.detect_claude(runner=subprocess.run) -> dict`, `account.detect() -> dict`, `account.save_global(data: dict) -> None`, `account.load_global() -> dict | None`, `account.save_repo(root, data: dict) -> None`, `account.load_repo(root) -> dict | None`. Task 3 (`cli.py`) is the only caller.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_account.py`:

```python
import base64
import json
import subprocess

from whyline import account


def _fake_jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_detect_codex_reads_the_plan_from_the_decoded_jwt(tmp_path):
    auth_path = tmp_path / "auth.json"
    token = _fake_jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}})
    auth_path.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": token}}))
    result = account.detect_codex(auth_path)
    assert result == {"auth_mode": "chatgpt", "plan": "plus"}


def test_detect_codex_never_returns_the_raw_token(tmp_path):
    auth_path = tmp_path / "auth.json"
    token = _fake_jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}})
    auth_path.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": token}}))
    result = account.detect_codex(auth_path)
    assert token not in json.dumps(result)


def test_detect_codex_with_an_api_key_reports_no_plan(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"auth_mode": "apikey"}))
    assert account.detect_codex(auth_path) == {"auth_mode": "apikey", "plan": None}


def test_detect_codex_missing_file_is_unknown_not_a_crash(tmp_path):
    result = account.detect_codex(tmp_path / "does-not-exist.json")
    assert result["plan"] == "unknown"
    assert "reason" in result


def test_detect_codex_malformed_json_is_unknown_not_a_crash(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{not json")
    result = account.detect_codex(auth_path)
    assert result["plan"] == "unknown"


def test_detect_codex_chatgpt_mode_missing_the_claim_is_unknown(tmp_path):
    auth_path = tmp_path / "auth.json"
    token = _fake_jwt({"https://api.openai.com/auth": {}})  # no chatgpt_plan_type
    auth_path.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": token}}))
    result = account.detect_codex(auth_path)
    assert result["plan"] == "unknown"
    assert result["auth_mode"] == "chatgpt"


def _fake_runner(stdout: str, returncode: int = 0):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    return run


def test_detect_claude_reads_the_subscription_type():
    stdout = json.dumps({"apiProvider": "firstParty", "authMethod": "claude.ai", "subscriptionType": "pro"})
    result = account.detect_claude(runner=_fake_runner(stdout))
    assert result == {"auth_method": "claude.ai", "plan": "pro"}


def test_detect_claude_with_an_api_key_reports_no_plan():
    stdout = json.dumps({"apiProvider": "thirdParty", "authMethod": "apiKeyHelper"})
    result = account.detect_claude(runner=_fake_runner(stdout))
    assert result == {"auth_method": "apiKeyHelper", "plan": None}


def test_detect_claude_binary_missing_is_unknown_not_a_crash():
    def run(argv, **kwargs):
        raise FileNotFoundError("claude not found")

    result = account.detect_claude(runner=run)
    assert result["plan"] == "unknown"
    assert "reason" in result


def test_detect_claude_unparseable_output_is_unknown_not_a_crash():
    result = account.detect_claude(runner=_fake_runner("not json"))
    assert result["plan"] == "unknown"


def test_detect_combines_both_agents(monkeypatch, tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"auth_mode": "apikey"}))
    monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
    monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
    assert account.detect() == {"codex": {"plan": "plus"}, "claude": {"plan": "pro"}}


def test_save_and_load_global_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    data = {"codex": {"plan": "plus"}, "claude": {"plan": "pro"}}
    account.save_global(data)
    assert account.load_global() == data


def test_load_global_returns_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    assert account.load_global() is None


def test_load_global_corrupt_file_reads_as_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.paths.global_account_path().parent.mkdir(parents=True)
    account.paths.global_account_path().write_text("{broken")
    assert account.load_global() is None


def test_save_and_load_repo_round_trip(tmp_path):
    data = {"codex": {"plan": "plus"}, "confirmed": True}
    account.save_repo(tmp_path, data)
    assert account.load_repo(tmp_path) == data


def test_load_repo_returns_none_when_absent(tmp_path):
    assert account.load_repo(tmp_path) is None


def test_load_repo_corrupt_file_reads_as_absent(tmp_path):
    account.paths.account_path(tmp_path).parent.mkdir(parents=True)
    account.paths.account_path(tmp_path).write_text("{broken")
    assert account.load_repo(tmp_path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_account.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'whyline.account'`.

- [ ] **Step 3: Implement**

Create `src/whyline/account.py`:

```python
"""Detecting which plan/tier each agent's CLI is actually authenticated under.

Never returns or stores a raw auth token -- only the derived plan string and
auth method. Never raises: every detection function returns at least
{"plan": "unknown", "reason": "..."} on any failure, so one agent's detection
problem never blocks the other's (spec M7).
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from whyline import paths


def _decode_jwt_payload(token: str) -> dict:
    """Decode a JWT's middle (payload) segment as JSON. Raises ValueError for
    anything that isn't shaped like a JWT -- callers turn that into "unknown"."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT (expected 3 dot-separated segments)")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def detect_codex(auth_path: Path | None = None) -> dict:
    """Read ~/.codex/auth.json (or `auth_path`, for tests) and derive the
    ChatGPT plan type, if any. auth_mode != "chatgpt" (e.g. an API key) means
    there is no subscription tier to report -- not an error."""
    target = auth_path if auth_path is not None else Path.home() / ".codex" / "auth.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"plan": "unknown", "reason": f"could not read {target}: {error}"}
    auth_mode = data.get("auth_mode")
    if auth_mode != "chatgpt":
        return {"auth_mode": auth_mode, "plan": None}
    try:
        claims = _decode_jwt_payload(data["tokens"]["id_token"])
        plan = claims["https://api.openai.com/auth"]["chatgpt_plan_type"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {
            "auth_mode": auth_mode,
            "plan": "unknown",
            "reason": f"could not read the plan from Codex's own auth token: {error}",
        }
    return {"auth_mode": auth_mode, "plan": plan}


def detect_claude(runner=subprocess.run) -> dict:
    """Run `claude auth status` and read its subscriptionType field directly.
    apiProvider != "firstParty" (e.g. an API key) means no subscription tier
    applies -- not an error."""
    try:
        result = runner(
            ["claude", "auth", "status"], capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"plan": "unknown", "reason": f"could not run claude auth status: {error}"}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        return {"plan": "unknown", "reason": f"could not parse claude auth status output: {error}"}
    if data.get("apiProvider") != "firstParty":
        return {"auth_method": data.get("authMethod"), "plan": None}
    return {"auth_method": data.get("authMethod"), "plan": data.get("subscriptionType", "unknown")}


def detect() -> dict:
    return {"codex": detect_codex(), "claude": detect_claude()}


def save_global(data: dict) -> None:
    target = paths.global_account_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_global() -> dict | None:
    try:
        return json.loads(paths.global_account_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_repo(root: Path, data: dict) -> None:
    target = paths.account_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_repo(root: Path) -> dict | None:
    try:
        return json.loads(paths.account_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_account.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline/account.py tests/test_account.py
git commit -m "feat: account.py detects which plan/tier codex and claude are authenticated under"
```

---

### Task 3: `cli.py` — `whyline account status` / `whyline account detect`

**Files:**
- Modify: `src/whyline/cli.py`
- Test: `tests/test_account_cli.py`

**Interfaces:**
- Consumes: `account.detect`, `account.save_global`, `account.load_global`, `account.save_repo`, `account.load_repo` (Task 2).
- Produces: `whyline account status`, `whyline account detect`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_account_cli.py`:

```python
import json
import os

from whyline import account, cli


def run_in(repo, argv, capsys, monkeypatch=None, input_answer=None):
    if monkeypatch is not None and input_answer is not None:
        monkeypatch.setattr("builtins.input", lambda prompt="": input_answer)
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(argv)
    finally:
        os.chdir(previous)
    return code, capsys.readouterr().out


def test_detect_writes_the_global_file_and_prints_it(repo, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
    monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})

    code, out = run_in(repo, ["account", "detect"], capsys)

    assert code == cli.EXIT_OK
    assert "plus" in out and "pro" in out
    saved = json.loads(account.paths.global_account_path().read_text())
    assert saved["codex"]["plan"] == "plus"
    assert "detected_at" in saved["codex"]


def test_status_with_no_detection_at_all_says_so(repo, capsys):
    code, out = run_in(repo, ["account", "status"], capsys)
    assert code == cli.EXIT_ERROR
    assert "whyline account detect" in out or "detect" in out


def test_status_first_run_in_a_repo_confirms_and_writes_repo_file(
    repo, capsys, monkeypatch, tmp_path
):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({"codex": {"plan": "plus"}, "claude": {"plan": "pro"}})

    code, out = run_in(repo, ["account", "status"], capsys, monkeypatch, input_answer="y")

    assert code == cli.EXIT_OK
    assert "plus" in out
    saved = account.load_repo(repo.path)
    assert saved["confirmed"] is True
    assert saved["codex"]["plan"] == "plus"


def test_status_declining_still_writes_the_repo_file_so_it_does_not_ask_again(
    repo, capsys, monkeypatch, tmp_path
):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({"codex": {"plan": "plus"}, "claude": {"plan": "pro"}})

    run_in(repo, ["account", "status"], capsys, monkeypatch, input_answer="n")
    saved = account.load_repo(repo.path)
    assert saved["confirmed"] is False


def test_status_with_an_existing_repo_file_just_prints_it_no_prompt(repo, capsys):
    account.save_repo(repo.path, {"codex": {"plan": "plus"}, "confirmed": True})
    code, out = run_in(repo, ["account", "status"], capsys)
    assert code == cli.EXIT_OK
    assert "plus" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_account_cli.py -v`
Expected: FAIL — `argparse` rejects the unknown `account` subcommand.

- [ ] **Step 3: Implement**

In `src/whyline/cli.py`, add two new `_add_*` functions after `_add_init`:

```python
def _add_account(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "account", help="Detect which plan/tier codex and claude are authenticated under"
    )
    account_sub = parser.add_subparsers(dest="account_command", required=True)
    account_sub.add_parser("status", help="Show the detected/confirmed account")
    account_sub.add_parser("detect", help="Re-run detection and refresh the global cache")
```

Add the call in `build_parser()`, right after `_add_init(subparsers)`:

```python
    _add_init(subparsers)
    _add_account(subparsers)
    return parser
```

Add the command functions after `cmd_init`:

```python
def _print_account(data: dict) -> None:
    for agent in ("codex", "claude"):
        info = data.get(agent, {})
        plan = info.get("plan")
        if plan is None:
            print(f"{agent}: no subscription tier (using an API key)")
        elif plan == "unknown":
            print(f"{agent}: unknown ({info.get('reason', 'no reason given')})")
        else:
            print(f"{agent}: {plan}")


def cmd_account(args: argparse.Namespace) -> int:
    from whyline import account

    root = _require_repo()
    if args.account_command == "detect":
        detected = account.detect()
        now = datetime.datetime.now().astimezone().isoformat()
        for info in detected.values():
            info["detected_at"] = now
        account.save_global(detected)
        _print_account(detected)
        return EXIT_OK

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

Add `"account": cmd_account,` to the `COMMANDS` dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_account_cli.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline/cli.py tests/test_account_cli.py
git commit -m "feat: whyline account status/detect"
```

---

### Task 4: `model.py` — per-repo model choice

**Files:**
- Create: `src/whyline/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: `paths.model_path` (Task 1).
- Produces: `model.load(root) -> dict`, `model.save(root, data: dict) -> None`, `model.set_one(root, agent: str, model: str) -> None`. Task 5 (`cli.py`, `runner.py`) is the only caller.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_model.py`:

```python
from whyline import model


def test_load_returns_empty_dict_when_absent(tmp_path):
    assert model.load(tmp_path) == {}


def test_save_then_load_round_trips(tmp_path):
    model.save(tmp_path, {"codex": "gpt-5-codex"})
    assert model.load(tmp_path) == {"codex": "gpt-5-codex"}


def test_load_corrupt_file_reads_as_empty(tmp_path):
    model.paths.model_path(tmp_path).parent.mkdir(parents=True)
    model.paths.model_path(tmp_path).write_text("{broken")
    assert model.load(tmp_path) == {}


def test_set_one_adds_a_single_agent_without_disturbing_others(tmp_path):
    model.save(tmp_path, {"claude": "opus"})
    model.set_one(tmp_path, "codex", "gpt-5-codex")
    assert model.load(tmp_path) == {"claude": "opus", "codex": "gpt-5-codex"}


def test_set_one_with_a_blank_value_removes_the_key(tmp_path):
    model.save(tmp_path, {"codex": "gpt-5-codex", "claude": "opus"})
    model.set_one(tmp_path, "codex", "")
    assert model.load(tmp_path) == {"claude": "opus"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'whyline.model'`.

- [ ] **Step 3: Implement**

Create `src/whyline/model.py`:

```python
"""Per-repo model choice for codex/claude/antigravity.

No value is ever validated against a list of real model names (spec M4) --
whatever string is set is used as-is; a wrong choice fails at the agent's own
invocation time, same as an unconfigured model always has.
"""

from __future__ import annotations

import json
from pathlib import Path

from whyline import paths


def load(root: Path) -> dict:
    try:
        return json.loads(paths.model_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save(root: Path, data: dict) -> None:
    target = paths.model_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_one(root: Path, agent: str, value: str) -> None:
    """A blank `value` clears that agent's entry entirely, rather than storing
    an empty string -- matching `load(root).get(agent)` returning None either
    way (absent or never-set read identically to every caller)."""
    data = load(root)
    if value:
        data[agent] = value
    else:
        data.pop(agent, None)
    save(root, data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_model.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline/model.py tests/test_model.py
git commit -m "feat: model.py stores a per-repo model choice for each agent"
```

---

### Task 5: `runner.py` model support, `whyline model` command, `cmd_run` wiring, gitignore

**Files:**
- Modify: `src/whyline/runner.py`
- Modify: `src/whyline/cli.py`
- Test: `tests/test_runner.py`, `tests/test_model_cli.py` (new)

**Interfaces:**
- Consumes: `model.load`, `model.set_one` (Task 4).
- Produces: `runner.MODEL_FLAG`, `runner.build_argv(agent, task, brief_text, model=None)`, `runner.launch(..., model=None)`; `whyline model`, `whyline model set <agent> <model>`, `whyline model status`; `cmd_run` becomes model-aware.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_runner.py`:

```python
def test_build_argv_appends_the_model_flag_when_given():
    argv = runner.build_argv("codex", "task", "ctx", model="gpt-5-codex")
    assert argv == ["codex", "--model", "gpt-5-codex", "ctx\n\ntask"]


def test_build_argv_with_no_model_is_unchanged():
    assert runner.build_argv("codex", "task", "ctx") == ["codex", "ctx\n\ntask"]


def test_build_argv_appends_the_model_flag_for_antigravity():
    argv = runner.build_argv("antigravity", "task", "ctx", model="gemini-3-pro")
    assert argv == ["agy", "-i", "--model", "gemini-3-pro", "ctx\n\ntask"]


def test_launch_passes_the_model_through_to_build_argv():
    calls = []
    runner.launch(
        "codex", "task", "ctx", which=lambda name: f"/usr/bin/{name}",
        exec_fn=lambda binary, argv: calls.append((binary, argv)), model="gpt-5-codex",
    )
    assert calls == [("codex", ["codex", "--model", "gpt-5-codex", "ctx\n\ntask"])]
```

Create `tests/test_model_cli.py`:

```python
import os

from whyline import cli, model


def run_in(repo, argv, capsys, monkeypatch=None, input_answers=None):
    if monkeypatch is not None and input_answers is not None:
        answers = iter(input_answers)
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(argv)
    finally:
        os.chdir(previous)
    return code, capsys.readouterr().out


def test_model_set_writes_one_agent(repo, capsys):
    code, out = run_in(repo, ["model", "set", "codex", "gpt-5-codex"], capsys)
    assert code == cli.EXIT_OK
    assert model.load(repo.path) == {"codex": "gpt-5-codex"}


def test_model_status_with_nothing_set_says_so(repo, capsys):
    code, out = run_in(repo, ["model", "status"], capsys)
    assert code == cli.EXIT_OK
    assert "nothing set" in out.lower()


def test_model_status_prints_current_selections(repo, capsys):
    model.save(repo.path, {"codex": "gpt-5-codex"})
    code, out = run_in(repo, ["model", "status"], capsys)
    assert "gpt-5-codex" in out


def test_interactive_model_selection_writes_all_three_answers(repo, capsys, monkeypatch):
    code, out = run_in(
        repo, ["model"], capsys, monkeypatch,
        input_answers=["gpt-5-codex", "opus", ""],
    )
    assert code == cli.EXIT_OK
    assert model.load(repo.path) == {"codex": "gpt-5-codex", "claude": "opus"}


def test_interactive_model_selection_prints_the_antigravity_caveat(repo, monkeypatch, capsys):
    answers = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        cli.main(["model"])
    finally:
        os.chdir(previous)
    out = capsys.readouterr().out
    assert "not currently safe" in out or "unattended" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runner.py tests/test_model_cli.py -v`
Expected: FAIL — `build_argv` rejects the unexpected `model` keyword; `model`/`model set`/`model status` are unrecognized subcommands.

- [ ] **Step 3: Implement**

In `src/whyline/runner.py`, add after `AGENTS`:

```python
MODEL_FLAG = {"claude": "--model", "codex": "--model", "antigravity": "--model"}
```

Change `build_argv`:

```python
def build_argv(
    agent: str, task: str, brief_text: str, model: str | None = None
) -> list[str]:
    if agent not in AGENTS:
        known = ", ".join(sorted(AGENTS))
        raise UnknownAgent(f"Unknown agent {agent!r}. Known agents: {known}")
    command = list(AGENTS[agent])
    if model:
        command += [MODEL_FLAG[agent], model]
    prompt = f"{brief_text}\n\n{task}" if brief_text else task
    return [*command, prompt]
```

Change `launch`'s signature and its one call to `build_argv`:

```python
def launch(
    agent: str,
    task: str,
    brief_text: str,
    which=None,
    exec_fn=None,
    model: str | None = None,
) -> int:
    """Replace this process with the agent's own CLI.
    ...  # docstring unchanged
    """
    argv = build_argv(agent, task, brief_text, model=model)
    which = which if which is not None else _which
    exec_fn = exec_fn if exec_fn is not None else _exec
    if which(argv[0]) is None:
        raise AgentMissing(f"{argv[0]} is not installed or not on PATH")
    exec_fn(argv[0], argv)
    return 0  # unreachable when exec_fn is the real os.execvp
```

In `src/whyline/cli.py`, add `_add_model` after `_add_account`:

```python
def _add_model(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "model", help="Choose which model each agent uses in this repo"
    )
    model_sub = parser.add_subparsers(dest="model_command")
    set_parser = model_sub.add_parser("set", help="Set one agent's model non-interactively")
    set_parser.add_argument("agent", choices=tuple(runner.AGENTS))
    set_parser.add_argument("model")
    model_sub.add_parser("status", help="Show current selections")
```

Wire it into `build_parser()`:

```python
    _add_account(subparsers)
    _add_model(subparsers)
    return parser
```

Add the command function after `cmd_account`:

```python
def cmd_model(args: argparse.Namespace) -> int:
    from whyline import account, model

    root = _require_repo()
    if args.model_command == "set":
        model.set_one(root, args.agent, args.model)
        return EXIT_OK
    if args.model_command == "status":
        current = model.load(root)
        if not current:
            print("Nothing set.")
        else:
            for agent, chosen in current.items():
                print(f"{agent}: {chosen}")
        return EXIT_OK

    repo_account = account.load_repo(root)
    for agent in ("codex", "claude", "antigravity"):
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

Add `"model": cmd_model,` to `COMMANDS`.

Change `cmd_run` to resolve and pass the model:

```python
def cmd_run(args: argparse.Namespace) -> int:
    from whyline import gitq, model as model_module, paths, sync

    root = _require_repo()
    if not paths.is_initialised(root):
        print("whyline is not initialised here. Run: whyline init", file=sys.stderr)
        return EXIT_UNINITIALISED
    try:
        brief_text = sync.compose(
            root,
            task=args.task_id,
            files=args.files,
            token_budget=args.token_budget,
        )
    except gitq.GitUnavailable as error:
        print(f"git is unavailable: {error}", file=sys.stderr)
        return EXIT_ERROR
    chosen_model = model_module.load(root).get(args.agent)
    try:
        runner.launch(args.agent, args.task, brief_text, model=chosen_model)
    except (runner.UnknownAgent, runner.AgentMissing) as error:
        print(str(error), file=sys.stderr)
        print(brief_text)
        return EXIT_ERROR
    return EXIT_OK
```

Finally, add `"account.json"` and `"model.json"` to `GITIGNORE_LINES`:

```python
GITIGNORE_LINES = (
    "ledger.jsonl",
    "index.db",
    "active-handoff.json",
    "ownership.json",
    "readside.log",
    "*.lock",
    "*.bak",
    "account.json",
    "model.json",
    "!decisions.md",
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_runner.py tests/test_model_cli.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — every existing `build_argv`/`launch` call has no `model=` keyword, so it defaults to `None` and produces byte-for-byte identical argv to before.

- [ ] **Step 6: Commit**

```bash
git add src/whyline/runner.py src/whyline/cli.py tests/test_runner.py tests/test_model_cli.py
git commit -m "feat: whyline run is model-aware; whyline model sets a per-repo choice"
```

---

### Task 6: README — document `whyline account` and `whyline model`

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the "Honest Limitations" section (or the section documenting `whyline run`'s supported agents), and add a new section immediately after it:

```markdown
### Choosing a model: `whyline account` and `whyline model`

`whyline account detect` checks which plan/tier `codex` and `claude` are actually authenticated under (Claude Pro/Max/Team, ChatGPT Plus/Pro/Team) — not just whether they're logged in. It runs once per machine (cached in `~/.whyline/account.json`) and asks you to confirm it once per repo (`.whyline/account.json`, gitignored — this is personal plan/billing info, never committed). `whyline account status` shows what's on file.

`whyline model` lets you pick a model per agent for this repo (`.whyline/model.json`, also gitignored), showing the detected plan as context. `whyline model set <agent> <model>` sets one non-interactively; `whyline model status` shows the current choices. `whyline run` uses whatever's set automatically — no flag needed. Nothing is validated against a list of real model names; a wrong choice just fails at the agent's own invocation time.

**Antigravity's model can be set here too, and `whyline run antigravity` is fully safe with it** — that command hands the terminal to a human, so nothing here is affected by Antigravity's own headless-mode limitations. Those limitations *do* apply if you separately, deliberately configure Antigravity as a whyline-relay role via its documented [generic-adapter recipe](https://github.com/anishmoncivarghese/whyline-relay#using-antigravity-agy-today-via-the-generic-adapter) — `whyline model` will remind you of this when you set Antigravity's model, but never blocks it, since the interactive `whyline run` use is completely unaffected.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document whyline account and whyline model"
```

## Not in this plan

- **whyline-relay's read-only integration** (reading `.whyline/model.json` as a default in `init`/`roles set`, and the antigravity-specific `preflight.py` warning) — a separate plan, depending on this one shipping first (spec section 6, phase 2).
- **Antigravity's own subscription/tier detection** — no verified mechanism exists (spec non-goals).
- **Filtering or validating model choices against what a plan permits** — explicitly rejected in the spec (M4); the detected plan is shown as context only.
