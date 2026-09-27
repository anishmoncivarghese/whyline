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
