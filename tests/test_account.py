from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest

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


def test_detect_codex_invalid_utf8_is_unknown_not_a_crash(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_bytes(b"\x80\xff\xfe not valid utf8")
    result = account.detect_codex(auth_path)
    assert result["plan"] == "unknown"
    assert "reason" in result


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


def test_detect_claude_missing_subscription_type_is_unknown_with_reason():
    stdout = json.dumps({"apiProvider": "firstParty", "authMethod": "claude.ai"})
    result = account.detect_claude(runner=_fake_runner(stdout))
    assert result["plan"] == "unknown"
    assert result["auth_method"] == "claude.ai"
    assert "reason" in result


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


def test_detect_cross_agent_isolation_codex_failure_does_not_block_claude(monkeypatch, tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "auth.json").write_bytes(b"\x80\xff invalid utf8")
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        account,
        "detect_claude",
        lambda: {"auth_method": "claude.ai", "plan": "pro"},
    )
    result = account.detect()
    assert result["codex"]["plan"] == "unknown"
    assert "reason" in result["codex"]
    assert result["claude"] == {"auth_method": "claude.ai", "plan": "pro", "available": True}


def test_detect_cross_agent_isolation_codex_exception_does_not_block_claude(monkeypatch):
    def _exploding_codex():
        raise RuntimeError("unexpected codex failure")

    monkeypatch.setattr(account, "detect_codex", _exploding_codex)
    monkeypatch.setattr(
        account,
        "detect_claude",
        lambda: {"auth_method": "claude.ai", "plan": "pro"},
    )
    result = account.detect()
    assert result["codex"]["plan"] == "unknown"
    assert "unexpected codex failure" in result["codex"]["reason"]
    assert result["claude"] == {"auth_method": "claude.ai", "plan": "pro", "available": True}


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


def test_load_global_invalid_utf8_reads_as_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.paths.global_account_path().parent.mkdir(parents=True)
    account.paths.global_account_path().write_bytes(b"\x80\xff broken utf8")
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


def test_load_repo_invalid_utf8_reads_as_absent(tmp_path):
    account.paths.account_path(tmp_path).parent.mkdir(parents=True)
    account.paths.account_path(tmp_path).write_bytes(b"\x80\xff broken utf8")
    assert account.load_repo(tmp_path) is None


def test_repo_account_and_model_files_are_gitignored():
    """Verify that .whyline/account.json and .whyline/model.json are gitignored."""
    repo_root = account.paths.find_repo_root(Path(__file__))
    if repo_root is None:
        pytest.skip("not inside a git repository")

    for path in (".whyline/account.json", ".whyline/model.json"):
        result = subprocess.run(
            ["git", "check-ignore", "-v", path],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{path} should be gitignored: {result.stdout}"


def test_repo_account_and_model_gitignored_skips_when_not_in_git_repo(monkeypatch):
    """Verify graceful skip when find_repo_root returns None."""
    monkeypatch.setattr(account.paths, "find_repo_root", lambda x: None)
    with pytest.raises(pytest.skip.Exception):
        test_repo_account_and_model_files_are_gitignored()


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
