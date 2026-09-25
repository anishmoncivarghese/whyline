from __future__ import annotations

import base64
import json
from pathlib import Path
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


def test_detect_combines_both_agents(monkeypatch, tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"auth_mode": "apikey"}))
    monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
    monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
    assert account.detect() == {"codex": {"plan": "plus"}, "claude": {"plan": "pro"}}


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
    assert result["claude"] == {"auth_method": "claude.ai", "plan": "pro"}


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
    assert result["claude"] == {"auth_method": "claude.ai", "plan": "pro"}


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
