from whyline import cli


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

