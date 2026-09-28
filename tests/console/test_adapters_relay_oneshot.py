from whyline.console import adapters


def test_run_relay_oneshot_classifies_a_pause(monkeypatch):
    from whyline_relay import cli as relay_cli

    def fake_main(argv, prog="whyline-relay"):
        print("Paused: something went wrong")
        return 1

    monkeypatch.setattr(relay_cli, "main", fake_main)

    event = adapters.run_relay_oneshot("/some/repo", ["resume"])
    assert event.kind == "pause"
    assert "Paused: something went wrong" in event.text


def test_run_relay_oneshot_classifies_completion(monkeypatch):
    from whyline_relay import cli as relay_cli

    def fake_main(argv, prog="whyline-relay"):
        print("Plan complete: 3 task(s) approved and committed.")
        return 0

    monkeypatch.setattr(relay_cli, "main", fake_main)

    event = adapters.run_relay_oneshot("/some/repo", ["start"])
    assert event.kind == "output"
    assert "Plan complete" in event.text


def test_run_relay_oneshot_passes_repo_flag(monkeypatch):
    from whyline_relay import cli as relay_cli

    captured = []

    def fake_main(argv, prog="whyline-relay"):
        captured.append(argv)
        return 0

    monkeypatch.setattr(relay_cli, "main", fake_main)

    adapters.run_relay_oneshot("/some/repo", ["start"])
    assert captured == [["start", "--repo", "/some/repo"]]


def test_run_relay_oneshot_reports_an_unrecognised_error_without_dropping_text(
    monkeypatch,
):
    from whyline_relay import cli as relay_cli

    def fake_main(argv, prog="whyline-relay"):
        print("something odd happened that matches no known pattern")
        return 1

    monkeypatch.setattr(relay_cli, "main", fake_main)

    event = adapters.run_relay_oneshot("/some/repo", ["start"])
    assert event.kind == "error"
    assert "something odd happened" in event.text


def test_run_relay_oneshot_shows_the_install_hint_when_whyline_relay_is_missing(
    monkeypatch,
):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "whyline_relay" or name.startswith("whyline_relay."):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    event = adapters.run_relay_oneshot("/some/repo", ["start"])
    assert event.kind == "error"
    assert "whyline[relay]" in event.text or "whyline-relay" in event.text


def test_run_relay_oneshot_reraises_missing_relay_internal_module(monkeypatch):
    import builtins
    import pytest

    real_import = builtins.__import__

    for error in (
        ModuleNotFoundError(
            "No module named 'whyline_relay.cli'", name="whyline_relay.cli"
        ),
        ModuleNotFoundError("whyline_relay.cli"),
    ):

        def fake_import(name, *args, err=error, **kwargs):
            if name == "whyline_relay":
                raise err
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(ModuleNotFoundError) as exc_info:
            adapters.run_relay_oneshot("/some/repo", ["start"])
        assert exc_info.value is error
