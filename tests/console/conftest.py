import pytest


@pytest.fixture(autouse=True)
def _isolated_agent_detection(monkeypatch, tmp_path_factory):
    """/model now re-runs detection when an agent looks unavailable, and
    reads the global account file for labels. Unisolated, a console test
    would run the real `claude auth status` and read or write the
    developer's own ~/.whyline/account.json. Tests that want detection
    results set them explicitly."""
    from whyline import account, paths

    home = tmp_path_factory.mktemp("whyline-home")
    monkeypatch.setattr(paths, "global_whyline_dir", lambda: home)
    monkeypatch.setattr(account, "refresh", lambda: {})


@pytest.fixture(autouse=True)
def _no_real_scheduler(monkeypatch):
    """Agents mode asks whether the scheduler is loaded. A test must never
    bootstrap the developer's LaunchAgent or create ~/Library/LaunchAgents."""
    from whyline.agents import launchd

    monkeypatch.setattr(launchd, "status", lambda run=None: launchd.Status(False, None, ""))

    def refuse(*_args, **_kwargs):
        raise AssertionError("console test called the real scheduler; stub launchd.turn_on or turn_off")

    monkeypatch.setattr(launchd, "turn_on", refuse)
    monkeypatch.setattr(launchd, "turn_off", refuse)
