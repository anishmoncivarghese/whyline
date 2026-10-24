from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from whyline import account


def test_login_and_status_commands_cover_the_known_agents() -> None:
    assert account.LOGIN_COMMANDS == {
        "claude": ["claude", "auth", "login"],
        "codex": ["codex", "login"],
        "grok": ["grok", "login"],
    }
    assert "antigravity" not in account.LOGIN_COMMANDS
    assert account.STATUS_COMMANDS == {
        "claude": ["claude", "auth", "status"],
        "codex": ["codex", "login", "status"],
    }
    assert "antigravity" not in account.STATUS_COMMANDS
    assert "grok" not in account.STATUS_COMMANDS


def _fake_jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_detect_codex_reads_the_plan_from_the_decoded_jwt(tmp_path):
    auth_path = tmp_path / "auth.json"
    token = _fake_jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}})
    auth_path.write_text(
        json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": token}}),
        encoding="utf-8",
    )
    result = account.detect_codex(auth_path)
    assert result == {"auth_mode": "chatgpt", "plan": "plus"}


def test_detect_codex_never_returns_the_raw_token(tmp_path):
    auth_path = tmp_path / "auth.json"
    token = _fake_jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}})
    auth_path.write_text(
        json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": token}}),
        encoding="utf-8",
    )
    result = account.detect_codex(auth_path)
    assert token not in json.dumps(result)


def test_detect_codex_with_an_api_key_reports_no_plan(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"auth_mode": "apikey"}), encoding="utf-8")
    assert account.detect_codex(auth_path) == {"auth_mode": "apikey", "plan": None}


def test_detect_codex_missing_file_is_unknown_not_a_crash(tmp_path):
    result = account.detect_codex(tmp_path / "does-not-exist.json")
    assert result["plan"] == "unknown"
    assert "reason" in result


def test_detect_codex_malformed_json_is_unknown_not_a_crash(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{not json", encoding="utf-8")
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
    auth_path.write_text(
        json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": token}}),
        encoding="utf-8",
    )
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
    account.paths.global_account_path().write_text("{broken", encoding="utf-8")
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
    account.paths.account_path(tmp_path).write_text("{broken", encoding="utf-8")
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
    result = account.refresh(enabled={"codex", "claude", "antigravity", "grok"})
    assert result["codex"]["available"] is True
    assert "detected_at" in result["codex"]
    assert account.load_global() == result


def test_refresh_keeps_enablement_and_updates_detected_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global(
        {"grok": {"plan": None, "available": True, "manual": True, "reason": None}}
    )
    monkeypatch.setattr(
        account, "detect_codex",
        lambda: (_ for _ in ()).throw(AssertionError("codex detector")),
    )
    monkeypatch.setattr(
        account, "detect_claude",
        lambda: (_ for _ in ()).throw(AssertionError("claude detector")),
    )
    monkeypatch.setattr(
        account, "detect_antigravity",
        lambda: (_ for _ in ()).throw(AssertionError("antigravity detector")),
    )
    monkeypatch.setattr(
        account, "detect_grok",
        lambda: {"plan": None, "available": False, "reason": "not found on PATH"},
    )
    result = account.refresh()
    # Legacy available=True means enabled; detection updates readiness.
    assert result["grok"]["enabled"] is True
    assert result["grok"]["available"] is False
    assert result["grok"]["manual"] is True


def test_ensure_detected_does_not_launch_when_nothing_is_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(
        account, "refresh", lambda enabled=None: calls.append(1) or {"codex": {"available": True}}
    )
    assert account.ensure_detected() is None
    assert calls == []


def test_ensure_detected_runs_only_once_after_a_stale_enabled_file(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({"claude": {"available": True}})
    calls = []
    monkeypatch.setattr(
        account, "refresh", lambda enabled=None: calls.append(1) or {"claude": {"available": True}}
    )
    first = account.ensure_detected()
    assert first is not None
    assert calls == [1]
    account.save_global({
        agent: {"available": True}
        for agent in ("codex", "claude", "antigravity", "grok")
    })
    second = account.ensure_detected()
    assert second is None
    assert calls == [1]


def test_ensure_detected_does_not_launch_for_a_pre_0_3_7_file_without_available(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({
        "codex": {"auth_mode": "chatgpt", "plan": "plus"},
        "claude": {"auth_method": "claude.ai", "plan": "pro"},
    })
    calls = []
    monkeypatch.setattr(
        account, "refresh",
        lambda enabled=None: calls.append(1) or {
            agent: {"available": True}
            for agent in ("codex", "claude", "antigravity", "grok")
        },
    )
    result = account.ensure_detected()
    assert result is None
    assert calls == []


def test_ensure_detected_treats_a_current_file_as_already_detected(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({
        agent: {"plan": None, "available": True}
        for agent in ("codex", "claude", "antigravity", "grok")
    })
    calls = []
    monkeypatch.setattr(account, "refresh", lambda: calls.append(1) or {})
    result = account.ensure_detected()
    assert result is None
    assert calls == []


def test_set_enabled_creates_and_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.set_enabled("antigravity", True)
    data = account.load_global()
    assert data["antigravity"] == {"enabled": True}
    account.set_enabled("antigravity", False)
    assert account.load_global()["antigravity"] == {"enabled": False}


def test_set_enabled_does_not_disturb_other_agents(tmp_path, monkeypatch):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({"codex": {"plan": "plus", "available": True}})
    account.set_enabled("grok", True)
    data = account.load_global()
    assert data["codex"] == {"plan": "plus", "available": True}
    assert data["grok"] == {"enabled": True}


def _all_on_path(name: str) -> str:
    return f"/usr/bin/{name}"


def test_available_agents_from_global_data(tmp_path, monkeypatch):
    # A separate home dir from the repo root -- global and repo account
    # files must never collide onto the same physical path in a test, or
    # save_repo silently overwrites whatever save_global just wrote (and
    # vice versa), matching neither in isolation.
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path / "home")
    account.save_global({
        "codex": {"plan": "plus", "available": True},
        "claude": {"plan": "unknown", "available": False},
        "antigravity": {"plan": None, "available": True},
        "grok": {"plan": None, "available": False},
    })
    assert account.available_agents(tmp_path, which=_all_on_path) == {"codex", "antigravity"}


def test_available_agents_ignores_repo_enablement(tmp_path, monkeypatch):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path / "home")
    account.save_global({
        "codex": {"available": True, "enabled": True, "plan": "plus"},
        "claude": {"available": True, "enabled": False, "plan": "pro"},
        "antigravity": {"available": True, "enabled": True},
        "grok": {"available": True, "enabled": False},
    })
    account.save_repo(tmp_path, {
        "codex": {"available": False},
        "claude": {"available": True, "plan": "pro"},
        "antigravity": {"available": False},
        "grok": {"available": True},
        "confirmed": True,
    })
    assert account.available_agents(tmp_path, which=_all_on_path) == {"codex", "antigravity"}


def test_available_agents_falls_back_to_global_when_repo_file_predates_available_field(
    tmp_path, monkeypatch
):
    # A repo account.json written before 0.3.7 (account-capability gating)
    # has plan/detected_at but no "available" key anywhere -- see
    # _looks_current's docstring for the same schema on the global file.
    # available_agents() must not read that as "every agent unavailable
    # here": it predates the question, so the accurate, current global
    # data should be used instead, exactly as ensure_detected() already
    # does for a stale global file.
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path / "home")
    account.save_global({
        agent: {"available": True}
        for agent in ("codex", "claude", "antigravity", "grok")
    })
    account.save_repo(tmp_path, {
        "codex": {"plan": "plus", "detected_at": "2026-09-25T00:00:00"},
        "claude": {"plan": "pro", "detected_at": "2026-09-25T00:00:00"},
        "confirmed": True,
    })
    assert account.available_agents(tmp_path, which=_all_on_path) == {
        "codex", "claude", "antigravity", "grok"
    }


def test_available_agents_empty_when_detection_itself_raises(tmp_path, monkeypatch):
    # account.py's own module docstring already promises "never raises: ...
    # so one agent's detection problem never blocks the other's" -- that
    # guarantee must extend to a total failure of refresh() itself (e.g. a
    # disk error writing the global file), not just to one agent's own
    # detect_x() call. No caller of available_agents() (cmd_model,
    # run_entry_menu) catches anything, so this has to hold here.
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({"claude": {"available": True}})
    monkeypatch.setattr(
        account, "refresh",
        lambda enabled=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert account.available_agents(tmp_path, which=lambda name: None) == set()


def test_ensure_detected_returns_none_when_refresh_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({"claude": {"available": True}})
    monkeypatch.setattr(
        account, "refresh",
        lambda enabled=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert account.ensure_detected() is None


def test_legacy_enabled_inferred_from_available_without_rewrite(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({
        "claude": {"plan": "pro", "available": True},
        "codex": {"plan": "plus", "available": False},
        "grok": {"available": True, "manual": True},
        "antigravity": {"available": False, "manual": True},
    })
    path = account.paths.global_account_path()
    before = path.read_text(encoding="utf-8")
    assert account.enabled_agents() == {"claude", "grok"}
    status = account.agent_status(tmp_path, which=_all_on_path)
    assert status["claude"]["enabled"] is True
    assert status["grok"]["enabled"] is True
    assert status["codex"]["enabled"] is False
    assert status["antigravity"]["enabled"] is False
    loaded = json.loads(before)
    assert "enabled" not in loaded["claude"]
    assert "enabled" not in loaded["grok"]
    assert path.read_text(encoding="utf-8") == before


def test_repo_data_cannot_override_global_enablement(tmp_path, monkeypatch):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path / "home")
    account.save_global({
        "claude": {"enabled": False, "available": True, "plan": "pro"},
        "codex": {"enabled": True, "available": True, "plan": "plus"},
        "grok": {"enabled": False, "available": True},
        "antigravity": {"enabled": True, "available": True},
    })
    account.save_repo(tmp_path, {
        "claude": {"available": True, "plan": "max"},
        "codex": {"available": False},
        "grok": {"available": True},
        "antigravity": {"available": False},
        "confirmed": True,
    })
    status = account.agent_status(tmp_path, which=_all_on_path)
    assert status["claude"]["enabled"] is False
    assert status["claude"]["available"] is False
    assert status["claude"]["label"] == "off in Settings"
    assert "whyline account enable claude" in status["claude"]["hint"]
    assert status["codex"]["enabled"] is True
    assert status["codex"]["available"] is True
    assert status["grok"]["available"] is False
    assert status["antigravity"]["available"] is True
    assert account.available_agents(tmp_path, which=_all_on_path) == {
        "codex", "antigravity"
    }


def test_enabled_missing_binary_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path / "home")
    account.save_global({
        "claude": {"enabled": True, "available": True, "plan": "pro"},
        "codex": {"enabled": True, "available": True, "plan": "plus"},
        "grok": {"enabled": True, "available": True},
        "antigravity": {"enabled": True, "available": True},
    })
    status = account.agent_status(tmp_path, which=lambda name: None)
    for agent in account.AGENT_ORDER:
        assert status[agent]["enabled"] is True
        assert status[agent]["installed"] is False
        assert status[agent]["available"] is False
        assert status[agent]["label"] == "not installed"
    assert account.available_agents(tmp_path, which=lambda name: None) == set()


def test_grok_and_antigravity_login_wording_is_honest(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path / "home")
    account.save_global({
        "claude": {"enabled": False, "available": False},
        "codex": {"enabled": False, "available": False},
        "grok": {"enabled": True, "available": True},
        "antigravity": {"enabled": True, "available": True},
    })
    status = account.agent_status(tmp_path, which=_all_on_path)
    assert status["grok"]["available"] is True
    assert status["grok"]["label"] == "installed (login not checked)"
    assert status["antigravity"]["available"] is True
    assert status["antigravity"]["label"] == "installed (login not checked)"


def test_all_disabled_yields_empty_available_set(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path / "home")
    account.set_enabled_many({agent: False for agent in account.AGENT_ORDER})
    assert account.enabled_agents() == set()
    assert account.available_agents(tmp_path, which=_all_on_path) == set()
    status = account.agent_status(tmp_path, which=_all_on_path)
    for agent in account.AGENT_ORDER:
        assert status[agent]["enabled"] is False
        assert status[agent]["available"] is False
        assert status[agent]["label"] == "off in Settings"


def test_refresh_does_not_call_disabled_claude_detector(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({
        "claude": {
            "enabled": False,
            "available": True,
            "plan": "pro",
            "auth_method": "claude.ai",
        },
        "codex": {"enabled": True, "available": True, "plan": "plus"},
        "antigravity": {"enabled": False, "available": True},
        "grok": {"enabled": False, "available": True},
    })
    monkeypatch.setattr(
        account, "detect_claude",
        lambda: (_ for _ in ()).throw(AssertionError("claude detector")),
    )
    monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
    monkeypatch.setattr(
        account, "detect_antigravity",
        lambda: (_ for _ in ()).throw(AssertionError("antigravity detector")),
    )
    monkeypatch.setattr(
        account, "detect_grok",
        lambda: (_ for _ in ()).throw(AssertionError("grok detector")),
    )
    result = account.refresh()
    assert result["claude"]["plan"] == "pro"
    assert result["claude"]["auth_method"] == "claude.ai"
    assert result["claude"]["enabled"] is False
    assert "detected_at" not in result["claude"]
    assert result["codex"]["enabled"] is True
    assert "detected_at" in result["codex"]


def test_check_provider_never_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({"claude": {"enabled": True, "plan": "pro"}})
    before = account.paths.global_account_path().read_text(encoding="utf-8")
    monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "max"})
    result = account.check_provider("claude")
    assert result["plan"] == "max"
    assert result["available"] is True
    assert account.paths.global_account_path().read_text(encoding="utf-8") == before


def test_set_enabled_many_preserves_plan_auth_fields_and_merges_results(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({
        "claude": {
            "plan": "pro",
            "auth_method": "claude.ai",
            "available": True,
            "detected_at": "old",
        },
        "codex": {
            "plan": "plus",
            "auth_mode": "chatgpt",
            "available": True,
        },
        "grok": {"plan": None, "available": True, "reason": None},
        "antigravity": {"plan": None, "available": False, "reason": "agy not found"},
    })
    account.set_enabled_many(
        {"claude": True, "codex": False, "grok": True, "antigravity": False},
        results={
            "claude": {
                "plan": "max",
                "available": True,
                "detected_at": "new",
            },
        },
    )
    data = account.load_global()
    assert data["claude"]["enabled"] is True
    assert data["claude"]["plan"] == "max"
    assert data["claude"]["auth_method"] == "claude.ai"
    assert data["claude"]["detected_at"] == "new"
    assert data["codex"]["enabled"] is False
    assert data["codex"]["plan"] == "plus"
    assert data["codex"]["auth_mode"] == "chatgpt"
    assert data["codex"]["available"] is True
    assert data["grok"]["enabled"] is True
    assert data["grok"]["plan"] is None
    assert data["antigravity"]["enabled"] is False
    assert data["antigravity"]["reason"] == "agy not found"


def test_replacement_failure_preserves_the_old_json(monkeypatch, tmp_path):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({"claude": {"plan": "pro", "enabled": True}})
    target = account.paths.global_account_path()
    before = target.read_text(encoding="utf-8")

    def boom(self, dest):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError):
        account.set_enabled("codex", True)
    assert target.read_text(encoding="utf-8") == before
    leftovers = [path for path in target.parent.iterdir() if path.name.endswith(".tmp")]
    assert leftovers == []


def test_agent_status_reports_enabled_installed_and_effective_available(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path / "home")
    account.save_global({
        "claude": {"enabled": True, "available": True, "plan": "max"},
        "codex": {"enabled": True, "available": True, "plan": None},
        "grok": {"enabled": True, "available": True},
        "antigravity": {"enabled": False, "available": True},
    })
    status = account.agent_status(
        tmp_path, which=lambda name: "/usr/bin/claude" if name == "claude" else None
    )
    assert status["claude"] == {
        "enabled": True,
        "installed": True,
        "available": True,
        "label": "max",
        "hint": None,
    }
    assert status["codex"]["enabled"] is True
    assert status["codex"]["installed"] is False
    assert status["codex"]["available"] is False
    assert status["codex"]["label"] == "not installed"
    assert status["antigravity"]["label"] == "off in Settings"
    assert status["antigravity"]["hint"] == (
        "Open Settings or run: whyline account enable antigravity"
    )
