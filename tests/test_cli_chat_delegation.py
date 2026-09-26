from whyline import cli


def test_execs_into_whyline_relay_chat_when_installed():
    calls = []
    result = cli.exec_into_chat(
        which=lambda name: f"/usr/bin/{name}" if name == "whyline-relay" else None,
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
    )
    assert result is True
    assert calls == [("whyline-relay", ["whyline-relay", "chat"])]


def test_falls_through_when_whyline_relay_is_not_installed():
    calls = []
    result = cli.exec_into_chat(
        which=lambda name: None,
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
    )
    assert result is False
    assert calls == []


def test_main_with_no_args_delegates_to_chat(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "exec_into_chat",
        lambda which=None, exec_fn=None: calls.append("called") or True,
    )
    code = cli.main([])
    assert calls == ["called"]
    assert code == cli.EXIT_OK


def test_main_with_no_args_prints_usage_when_whyline_relay_is_absent(monkeypatch, capsys):
    monkeypatch.setattr(cli, "exec_into_chat", lambda which=None, exec_fn=None: False)
    code = cli.main([])
    assert code == cli.EXIT_USAGE
    assert capsys.readouterr().err  # existing usage text, unchanged
