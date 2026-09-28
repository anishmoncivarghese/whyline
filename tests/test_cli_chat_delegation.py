import pytest

from whyline import cli


@pytest.fixture(autouse=True)
def _default_no_console_extras(monkeypatch):
    """The legacy entry menu tests exercise the zero-extras plain-text
    fallback. Ensure console extras are treated as unavailable unless a test
    explicitly enables them."""
    from whyline.console import editor, tui

    monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
    monkeypatch.setattr(editor, "AVAILABLE", False)


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
    account.save_global({
        agent: {"plan": None, "available": True}
        for agent in ("codex", "claude", "antigravity", "grok")
    })
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


def test_entry_menu_redetects_a_pre_0_3_7_account_file(monkeypatch, tmp_path):
    """Regression: a file saved before account-capability gating (0.3.7) has
    only {"codex": {...}, "claude": {...}} with no "available" key and no
    antigravity/grok entries at all -- that schema must never be trusted as
    "already detected," or every agent reads as permanently unavailable
    with no way to self-heal short of an explicit `whyline account detect`."""
    from whyline import account, cli
    monkeypatch.setattr(account.paths.Path, "home", lambda: tmp_path)
    account.save_global({
        "codex": {"auth_mode": "chatgpt", "plan": "plus"},
        "claude": {"auth_method": "claude.ai", "plan": "pro"},
    })
    monkeypatch.setattr(account, "detect_codex", lambda: {"plan": "plus"})
    monkeypatch.setattr(account, "detect_claude", lambda: {"plan": "pro"})
    monkeypatch.setattr(
        account, "detect_antigravity",
        lambda: {"plan": None, "available": False, "reason": "not found"},
    )
    monkeypatch.setattr(
        account, "detect_grok",
        lambda: {"plan": None, "available": False, "reason": "not found"},
    )
    answers = iter(["chat", "chat"])
    cli.run_entry_menu(
        which=lambda name: "/usr/bin/whyline-relay",
        exec_fn=lambda *a: None,
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
    )
    refreshed = account.load_global()
    assert refreshed["codex"]["available"] is True
    assert "antigravity" in refreshed


def test_entry_menu_does_not_exec_into_chat_when_model_setup_fails(monkeypatch):
    import subprocess
    from whyline import cli

    calls = []
    answers = iter(["chat", "model"])
    printed = []
    result = cli.run_entry_menu(
        which=lambda name: "/usr/bin/whyline-relay",
        exec_fn=lambda binary, argv: calls.append(("exec", binary, argv)),
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        subprocess_fn=lambda argv: subprocess.CompletedProcess(argv, 1),
    )
    assert result is True
    assert calls == []  # never execs into chat
    assert any("did not complete" in line for line in printed)


def test_entry_menu_execs_into_chat_when_model_setup_succeeds(monkeypatch):
    import subprocess
    from whyline import cli

    calls = []
    answers = iter(["chat", "model"])
    result = cli.run_entry_menu(
        which=lambda name: "/usr/bin/whyline-relay",
        exec_fn=lambda binary, argv: calls.append(("exec", binary, argv)),
        input_fn=lambda prompt="": next(answers),
        print_fn=lambda *a, **k: None,
        subprocess_fn=lambda argv: subprocess.CompletedProcess(argv, 0),
    )
    assert result is True
    assert calls == [("exec", "whyline-relay", ["whyline-relay", "chat"])]


def test_entry_menu_launches_the_mouse_tui_when_available(monkeypatch, tmp_path):
    from whyline import cli
    from whyline.console import tui

    monkeypatch.setattr(cli.paths, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(tui, "TUI_AVAILABLE", True)
    calls = []
    monkeypatch.setattr(tui, "launch", lambda root: calls.append(root))

    def _unexpected_prompt(prompt=""):
        raise AssertionError("must not reach the plain text menu")

    result = cli.run_entry_menu(
        which=lambda name: "/usr/bin/whyline-relay",
        input_fn=_unexpected_prompt,
    )
    assert result is True
    assert calls == [tmp_path]


def test_entry_menu_launches_the_keyboard_console_when_tui_unavailable(
    monkeypatch, tmp_path
):
    from whyline import cli
    from whyline.console import editor, repl, tui

    monkeypatch.setattr(cli.paths, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
    monkeypatch.setattr(editor, "AVAILABLE", True)
    calls = []
    monkeypatch.setattr(repl, "run", lambda root, **kwargs: calls.append(root))

    def _unexpected_prompt(prompt=""):
        raise AssertionError("must not reach the plain text menu")

    result = cli.run_entry_menu(
        which=lambda name: "/usr/bin/whyline-relay",
        input_fn=_unexpected_prompt,
    )
    assert result is True
    assert calls == [tmp_path]


def test_entry_menu_falls_through_to_plain_menu_when_neither_extra_is_available(
    monkeypatch, tmp_path
):
    from whyline import cli
    from whyline.console import editor, tui

    monkeypatch.setattr(cli.paths, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(tui, "TUI_AVAILABLE", False)
    monkeypatch.setattr(editor, "AVAILABLE", False)
    answers = iter(["", ""])
    calls = []
    result = cli.run_entry_menu(
        which=lambda name: "/usr/bin/whyline-relay",
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
        input_fn=lambda prompt="": next(answers),
    )
    assert result is True
    assert calls == [("whyline-relay", ["whyline-relay", "chat"])]


def test_entry_menu_falls_through_when_no_repo_root_found(monkeypatch):
    from whyline import cli
    from whyline.console import tui

    monkeypatch.setattr(cli.paths, "find_repo_root", lambda: None)
    monkeypatch.setattr(tui, "TUI_AVAILABLE", True)
    calls = []
    monkeypatch.setattr(tui, "launch", lambda root: calls.append(root))
    answers = iter(["", ""])
    result = cli.run_entry_menu(
        which=lambda name: "/usr/bin/whyline-relay",
        exec_fn=lambda binary, argv: None,
        input_fn=lambda prompt="": next(answers),
    )
    assert result is True
    assert calls == []  # the TUI is never launched without a repo root
