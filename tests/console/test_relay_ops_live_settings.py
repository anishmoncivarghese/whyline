import json
import os
import tomllib
from pathlib import Path

import pytest

from whyline import models
from whyline.console import relay_ops

_CONFIG = """\
plan = "plans/x.plan.md"
timeout_minutes = 30
max_rounds = 6

[roles]
implementer = "claude"
reviewer = "plain"

[backup]
chain = ["plain"]

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


def _stored(repo: Path) -> dict:
    target = repo / ".whyline" / "relay" / "run-settings.json"
    return json.loads(target.read_text(encoding="utf-8"))


def _config(repo: Path) -> dict:
    return tomllib.loads((repo / ".whyline/relay/config.toml").read_text())


def _mark_running(repo: Path, round_: int) -> None:
    from whyline_relay import running

    target = running.path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({
            "agent": "claude", "task": "T-1", "round": round_,
            "started": "2026-11-01T10:00:00+05:30", "pid": os.getpid(),
            "role": "implementer", "model": "",
        }),
        encoding="utf-8",
    )


def test_set_run_timeout_writes_the_file(repo):
    message = relay_ops.set_run_timeout(repo, 45, keep=False)

    assert message == "Timeout 45m from the next turn."
    assert _stored(repo)["timeout_minutes"] == 45
    assert _config(repo)["timeout_minutes"] == 30


def test_set_run_timeout_keep_reaches_config(repo):
    relay_ops.set_run_timeout(repo, 45, keep=True)

    assert _config(repo)["timeout_minutes"] == 45


def test_set_run_rounds_writes_the_file(repo):
    message = relay_ops.set_run_rounds(repo, 9, keep=False)

    assert message == "Round cap 9 from the next check."
    assert _stored(repo)["max_rounds"] == 9


def test_set_run_rounds_keep_reaches_config(repo):
    relay_ops.set_run_rounds(repo, 9, keep=True)

    assert _config(repo)["max_rounds"] == 9


def test_set_run_rounds_below_running_round_is_a_value_error(repo):
    _mark_running(repo, 5)

    with pytest.raises(ValueError, match="T-1 is already on round 5"):
        relay_ops.set_run_rounds(repo, 3, keep=False)


def test_set_run_timeout_out_of_range_is_a_value_error(repo):
    with pytest.raises(ValueError, match="1 to 1440"):
        relay_ops.set_run_timeout(repo, 5000, keep=False)


def test_set_run_backup_writes_the_file(repo):
    message = relay_ops.set_run_backup(repo, ["claude"], keep=False)

    assert "claude" in message
    assert _stored(repo)["backup_chain"] == ["claude"]


def test_set_run_backup_keep_reaches_config(repo):
    relay_ops.set_run_backup(repo, ["claude"], keep=True)

    assert _config(repo)["backup"]["chain"] == ["claude"]


def test_set_run_backup_unknown_agent_is_a_value_error(repo):
    with pytest.raises(ValueError):
        relay_ops.set_run_backup(repo, ["nobody"], keep=False)


def test_run_settings_before_any_change(repo):
    found = relay_ops.run_settings(repo)

    assert set(found) == {"timeout", "rounds", "backup"}
    assert found["timeout"].current == 30
    assert not any(s.changed for s in found.values())


def test_run_settings_after_a_change(repo):
    relay_ops.set_run_timeout(repo, 45, keep=False)
    relay_ops.set_run_rounds(repo, 9, keep=False)

    found = relay_ops.run_settings(repo)

    assert found["timeout"].current == 45
    assert found["timeout"].configured == 30
    assert found["timeout"].changed
    assert found["rounds"].current == 9
    assert found["rounds"].configured == 6
    assert found["rounds"].changed
    assert not found["backup"].changed


def test_model_options_come_from_whyline_models(repo):
    models.add("claude", "claude-my-own-1")

    for read in (relay_ops.cached_model_options, relay_ops.model_options_for_agent):
        options = read("claude")
        assert ("claude-my-own-1", "claude-my-own-1") in options
        assert options == models.cached("claude")
