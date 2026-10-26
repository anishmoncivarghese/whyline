"""Action registry defaults, policy merge, and approval rules."""

import json

import pytest

from whyline.ideas import actions, store


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


EXPECTED = (
    ("capture", False, "instant", "none", "none"),
    ("brainstorm", False, "long", "tap", "tap"),
    ("status", False, "instant", "none", "none"),
    ("run_agent", False, "long", "none", "none"),
    ("ask_repo", False, "turn", "none", "none"),
    ("summarise", False, "turn", "none", "none"),
    ("remind", False, "instant", "none", "none"),
    ("remember", False, "instant", "none", "none"),
    ("forget", False, "instant", "none", "none"),
    ("do_task", True, "long", "tap", "tap"),
    ("stop", True, "instant", "tap", "tap"),
)


def test_registry_defaults(conn):
    assert tuple(actions.REGISTRY) == tuple(name for name, *_ in EXPECTED)
    for name, writes, cost, default_approval, min_approval in EXPECTED:
        action = actions.REGISTRY[name]
        assert action.name == name
        assert action.writes is writes
        assert action.cost == cost
        assert action.default_approval == default_approval
        assert action.min_approval == min_approval
        assert action.summary
        assert action.verb
    merged = actions.policy(conn)
    assert list(merged) == list(actions.REGISTRY)
    for name, action in actions.REGISTRY.items():
        assert merged[name] == {
            "enabled": True,
            "approval": action.default_approval,
        }


def test_merge_keeps_unknown_saved_keys_out(conn):
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?)",
        (
            actions.POLICY_KEY,
            json.dumps({
                "capture": {"enabled": False, "approval": "tap"},
                "not_an_action": {"enabled": True, "approval": "tap"},
            }),
        ),
    )
    merged = actions.policy(conn)
    assert "not_an_action" not in merged
    assert merged["capture"] == {"enabled": False, "approval": "tap"}
    assert merged["status"] == {"enabled": True, "approval": "none"}
    raw = conn.execute(
        "SELECT value FROM kv WHERE key = ?", (actions.POLICY_KEY,)
    ).fetchone()[0]
    assert "not_an_action" in json.loads(raw)


def test_do_task_and_stop_cannot_drop_to_none(conn):
    for name in ("do_task", "stop"):
        with pytest.raises(
            actions.PolicyError,
            match=f"{name} changes things, so it always needs a tap.",
        ):
            actions.set_policy(conn, name, approval="none")
        assert actions.policy(conn)[name]["approval"] == "tap"


def test_unknown_name_is_refused(conn):
    before = actions.policy(conn)
    with pytest.raises(actions.PolicyError, match="unknown action explode"):
        actions.set_policy(conn, "explode", enabled=True)
    assert actions.policy(conn) == before


def test_assistant_proposals_always_need_a_tap(conn):
    assert actions.approval_for(conn, "capture", proposed_by="assistant") == "tap"
    assert actions.approval_for(conn, "capture", proposed_by="keyword") == "none"
    assert actions.approval_for(conn, "do_task", proposed_by="keyword") == "tap"
    actions.set_policy(conn, "capture", approval="tap")
    assert actions.approval_for(conn, "capture", proposed_by="keyword") == "tap"
    assert actions.approval_for(conn, "status", proposed_by="assistant") == "tap"
