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
