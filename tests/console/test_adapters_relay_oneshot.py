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
    assert "uv tool install --reinstall whyline" in event.text


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


def test_run_relay_oneshot_pause_uses_structured_state_not_raw_text(
    monkeypatch, tmp_path
):
    from whyline_relay import cli as relay_cli, state

    state.save(
        tmp_path,
        state.RelayState(
            plan="plan.md",
            branch="relay/plan",
            task_id="T-1",
            round=2,
            base_commit="abc123",
            paused_reason="codex hit a usage or rate limit; try again when it resets",
            log_path="/tmp/T-1-2-codex.log",
        ),
    )

    def fake_main(argv, prog="whyline-relay"):
        print("Paused: codex hit a usage or rate limit; try again when it resets")
        return 1

    monkeypatch.setattr(relay_cli, "main", fake_main)
    event = adapters.run_relay_oneshot(tmp_path, ["resume"])
    assert event.kind == "pause"
    assert "[rate-limit]" in event.text
    assert "T-1" in event.text
    assert "/tmp/T-1-2-codex.log" in event.text
    assert "whyline-relay resume" in event.text


def test_run_relay_oneshot_pause_falls_back_to_raw_text_with_no_saved_state(
    monkeypatch, tmp_path
):
    from whyline_relay import cli as relay_cli

    def fake_main(argv, prog="whyline-relay"):
        print("Paused: something odd, no state file exists for this")
        return 1

    monkeypatch.setattr(relay_cli, "main", fake_main)
    event = adapters.run_relay_oneshot(tmp_path, ["resume"])
    assert event.kind == "pause"
    assert "something odd, no state file exists for this" in event.text
