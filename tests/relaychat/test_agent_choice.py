import pytest

from whyline.agents import capabilities
from whyline.relaychat import agent_choice, settings


class FakeOps:
    def __init__(self, installed, roles=None, backup=()):
        self.installed = installed
        self.roles = roles or {"implementer": "claude", "tester": "antigravity",
                               "reviewer": "grok", "backup": []}
        self.backup = list(backup)

    def relay_agents(self, root):
        return list(self.installed)

    def current_roles(self, root):
        return self.roles

    def read_backup(self, root):
        return self.backup


@pytest.fixture
def setup(monkeypatch, tmp_path):
    def apply(installed, saved=None, backup=(), working=None, roles=None, readonly=None):
        ops = FakeOps(installed, roles, backup)
        monkeypatch.setattr(agent_choice, "_relay_ops", lambda: ops)
        monkeypatch.setattr(settings, "load", lambda repo, base=None: settings.ChatSettings(agent=saved))
        monkeypatch.setattr(agent_choice, "_working_agent", lambda repo, roles: working)
        allowed = set(readonly if readonly is not None else installed)
        monkeypatch.setattr(capabilities, "can_run", lambda cli: cli in allowed)
        return tmp_path

    return apply


def test_choices_only_read_only_agents(setup):
    repo = setup(["claude", "codex", "grok"], readonly=["claude", "grok"])
    assert agent_choice.choices(repo) == ["claude", "grok"]


def test_chosen_wins_over_saved(setup):
    repo = setup(["claude", "grok"], saved="claude")
    got = agent_choice.pick(repo, chosen="grok")
    assert got.agent == "grok" and got.shares_quota is False


def test_saved_agent_wins(setup):
    repo = setup(["claude", "grok"], saved="grok", backup=["claude"])
    assert agent_choice.pick(repo).agent == "grok"


def test_saved_agent_without_read_only_mode_is_never_picked(setup):
    repo = setup(["claude", "codex"], saved="codex", readonly=["claude"], backup=["codex", "claude"])
    got = agent_choice.pick(repo)
    assert got.agent == "claude"
    assert agent_choice.pick(repo, chosen="codex").agent == "claude"


def test_backup_chain_skips_working_agent(setup):
    repo = setup(["claude", "grok", "codex"], backup=["claude", "grok"], working="claude")
    got = agent_choice.pick(repo)
    assert got.agent == "grok" and got.shares_quota is False


def test_backup_skips_agents_without_read_only_mode(setup):
    repo = setup(["claude", "grok", "codex"], backup=["codex", "grok"], readonly=["claude", "grok"])
    assert agent_choice.pick(repo).agent == "grok"


def test_falls_back_to_reviewer_sharing_quota(setup):
    repo = setup(["claude", "grok"], backup=["claude"], working="claude")
    got = agent_choice.pick(repo)
    assert got.agent == "grok" and got.shares_quota is True


def _real(monkeypatch, tmp_path, live_agent, cut_off=None):
    from types import SimpleNamespace

    from whyline_relay import running, state

    ops = FakeOps(["claude", "grok", "codex"], backup=["claude", "grok"])
    monkeypatch.setattr(agent_choice, "_relay_ops", lambda: ops)
    monkeypatch.setattr(settings, "load", lambda repo, base=None: settings.ChatSettings(agent=None))
    monkeypatch.setattr(capabilities, "can_run", lambda cli: True)
    marker = SimpleNamespace(agent=live_agent) if live_agent else None
    monkeypatch.setattr(running, "live", lambda root: marker)
    saved = SimpleNamespace(stage="review", cut_off={"agent": cut_off} if cut_off else None)
    monkeypatch.setattr(state, "load", lambda root: saved)
    return tmp_path


def test_live_marker_agent_is_skipped(monkeypatch, tmp_path):
    repo = _real(monkeypatch, tmp_path, live_agent="claude")
    assert agent_choice.pick(repo).agent == "grok"


def test_stopped_relay_skips_nobody(monkeypatch, tmp_path):
    repo = _real(monkeypatch, tmp_path, live_agent=None, cut_off="claude")
    assert agent_choice.pick(repo).agent == "claude"


def test_stale_cut_off_is_not_treated_as_working(monkeypatch, tmp_path):
    repo = _real(monkeypatch, tmp_path, live_agent="grok", cut_off="claude")
    assert agent_choice.pick(repo).agent == "claude"


def test_no_read_only_agent_at_all(setup):
    repo = setup(["codex"], readonly=[], saved="codex")
    got = agent_choice.pick(repo)
    assert got.agent is None and got.shares_quota is False and got.why


def test_reviewer_without_read_only_mode_gives_none(setup):
    repo = setup(["claude", "codex"], readonly=["claude"],
                 roles={"implementer": "claude", "tester": "claude", "reviewer": "codex", "backup": []})
    assert agent_choice.pick(repo).agent is None
