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


@pytest.fixture
def installed_agents(monkeypatch):
    """Pretend these relay agents are installed. `relay_ops.relay_agents`
    looks the CLIs up on PATH, so a test that fakes `account.agent_status`
    alone passes on a developer Mac and fails on CI, where none is installed."""
    from whyline.console import relay_ops

    def install(*names: str) -> None:
        monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: sorted(names))

    install("antigravity", "claude", "codex", "grok")
    return install


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    """The console asks PyPI for a newer whyline when it starts. A test must
    never reach the network or offer to reinstall the developer's whyline;
    tests/console/test_update.py sets its own fakes."""
    from whyline.console import update

    monkeypatch.setattr(update, "check", lambda current, **_kwargs: None)
    monkeypatch.setattr(update, "install_problem", lambda **_kwargs: "whyline runs from a test.")
