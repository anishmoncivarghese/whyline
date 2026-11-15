import json
import os
import tomllib
from pathlib import Path

import pytest

from whyline.console import relay_ops

_CONFIG = """\
plan = "plans/x.plan.md"

[roles]
implementer = "claude"
reviewer = "plain"

[agents.claude]
model = "sonnet"

[agents.plain]
adapter = "generic"
command = ["plain-agent", "--go"]
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    (relay / "config.toml").write_text(_CONFIG, encoding="utf-8")
    return tmp_path


def _overrides(repo: Path) -> dict:
    target = repo / ".whyline" / "relay" / "model-overrides.json"
    return json.loads(target.read_text(encoding="utf-8"))


def _mark_running(repo: Path, agent: str, model: str) -> None:
    from whyline_relay import running

    target = running.path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({
            "agent": agent, "task": "T-1", "round": 1,
            "started": "2026-11-01T10:00:00+05:30", "pid": os.getpid(),
            "role": "implementer", "model": model,
        }),
        encoding="utf-8",
    )


def test_switch_model_live_writes_the_override(repo):
    message = relay_ops.switch_model_live(repo, "claude", "opus", keep=False)

    assert message == "claude → opus from its next turn."
    assert _overrides(repo)["claude"]["model"] == "opus"
    config = tomllib.loads((repo / ".whyline/relay/config.toml").read_text())
    assert config["agents"]["claude"]["model"] == "sonnet"


def test_switch_model_live_with_keep_saves_the_config(repo):
    relay_ops.switch_model_live(repo, "claude", "opus", keep=True)

    assert _overrides(repo)["claude"]["keep"] is True
    config = tomllib.loads((repo / ".whyline/relay/config.toml").read_text())
    assert config["agents"]["claude"]["model"] == "opus"


def test_run_models_after_a_switch_is_pending_while_the_turn_runs_the_old_model(repo):
    relay_ops.switch_model_live(repo, "claude", "opus", keep=False)
    _mark_running(repo, "claude", "sonnet")

    model = relay_ops.run_models(repo)["claude"]

    assert model == relay_ops.RunModel(
        agent="claude", current="opus", configured="sonnet", pending=True
    )


def test_run_models_not_pending_when_the_turn_runs_the_current_model(repo):
    relay_ops.switch_model_live(repo, "claude", "opus", keep=False)
    _mark_running(repo, "claude", "opus")

    assert relay_ops.run_models(repo)["claude"].pending is False


def test_run_models_without_a_switch_or_a_run(repo):
    model = relay_ops.run_models(repo)["claude"]

    assert (model.current, model.configured, model.pending) == ("sonnet", "sonnet", False)
    assert "plain" not in relay_ops.run_models(repo)


def test_switch_model_live_refuses_an_agent_without_model_flag(repo):
    from whyline_relay import roles

    with pytest.raises(roles.RoleSetError, match="has no way to set a model"):
        relay_ops.switch_model_live(repo, "plain", "opus", keep=False)
    assert not (repo / ".whyline/relay/model-overrides.json").exists()
