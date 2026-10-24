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
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_detect_writes_the_global_file_and_prints_it(repo, capsys, monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    account.set_enabled("codex", True)
    account.set_enabled("claude", True)
    monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
    monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})

    code, out = run_in(repo, ["account", "detect"], capsys)

    assert code == cli.EXIT_OK
    assert "plus" in out and "pro" in out
    saved = json.loads(
        account.paths.global_account_path().read_text(encoding="utf-8")
    )
    assert saved["codex"]["plan"] == "plus"
    assert "detected_at" in saved["codex"]


def test_status_with_no_detection_at_all_says_so(repo, capsys, monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    code, out = run_in(repo, ["account", "status"], capsys)
    assert code == cli.EXIT_ERROR
    assert "whyline account detect" in out or "detect" in out


def test_status_first_run_in_a_repo_confirms_and_writes_repo_file(
    repo, capsys, monkeypatch, tmp_path
):
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
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
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    account.save_global({"codex": {"plan": "plus"}, "claude": {"plan": "pro"}})

    run_in(repo, ["account", "status"], capsys, monkeypatch, input_answer="n")
    saved = account.load_repo(repo.path)
    assert saved["confirmed"] is False


def test_status_with_an_existing_repo_file_just_prints_it_no_prompt(repo, capsys):
    account.save_repo(repo.path, {"codex": {"plan": "plus"}, "confirmed": True})
    code, out = run_in(repo, ["account", "status"], capsys)
    assert code == cli.EXIT_OK
    assert "plus" in out


def test_print_account_formats_api_key_and_unknown_reasons(repo, capsys):
    account.save_repo(
        repo.path,
        {
            "codex": {"plan": None},
            "claude": {"plan": "unknown", "reason": "claude not found"},
            "confirmed": True,
        },
    )
    code, out = run_in(repo, ["account", "status"], capsys)
    assert code == cli.EXIT_OK
    assert "codex: no subscription tier (using an API key)" in out
    assert "claude: unknown (claude not found)" in out


def test_enable_sets_enabled_in_whyline(repo, capsys, monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    code, out = run_in(repo, ["account", "enable", "grok"], capsys)
    assert code == cli.EXIT_OK
    assert "enabled in Whyline" in out
    assert account.load_global()["grok"] == {"enabled": True}


def test_disable_sets_disabled_in_whyline_and_preserves_fields(
    repo, capsys, monkeypatch, tmp_path
):
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    account.save_global({"codex": {"plan": "plus", "available": True}})
    code, out = run_in(repo, ["account", "disable", "codex"], capsys)
    assert code == cli.EXIT_OK
    assert "disabled in Whyline" in out
    saved = account.load_global()["codex"]
    assert saved["enabled"] is False
    assert saved["plan"] == "plus"
    assert saved["available"] is True


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


def test_detect_checks_enabled_providers_only(repo, capsys, monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(account.paths.Path, "home", lambda: home)
    account.save_global({
        "claude": {"enabled": True, "plan": "pro", "available": True},
        "codex": {"enabled": False, "plan": "plus", "available": True},
        "grok": {"enabled": False, "available": True},
        "antigravity": {"enabled": False, "available": True},
    })
    claude_calls = []
    monkeypatch.setattr(
        account, "detect_claude", lambda: claude_calls.append(1) or {"plan": "max"}
    )
    monkeypatch.setattr(
        account, "detect_codex",
        lambda: (_ for _ in ()).throw(AssertionError("codex detector")),
    )
    monkeypatch.setattr(
        account, "detect_grok",
        lambda: (_ for _ in ()).throw(AssertionError("grok detector")),
    )
    monkeypatch.setattr(
        account, "detect_antigravity",
        lambda: (_ for _ in ()).throw(AssertionError("antigravity detector")),
    )
    code, out = run_in(repo, ["account", "detect"], capsys)
    assert code == cli.EXIT_OK
    assert claude_calls == [1]
    saved = json.loads(
        account.paths.global_account_path().read_text(encoding="utf-8")
    )
    assert saved["claude"]["plan"] == "max"
    assert saved["claude"]["enabled"] is True
    assert saved["codex"]["plan"] == "plus"
    assert saved["codex"]["enabled"] is False

