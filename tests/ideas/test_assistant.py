"""The assistant proposes a card. Confirm is what would apply it."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import cli
from whyline.agents import capabilities
from whyline.ideas import analyse as scoring
from whyline.ideas import assistant, paths, store


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _block(kind="plan_setup", fields=None, summary="Use grok as the implementer with a one hour limit."):
    payload = {
        "kind": kind,
        "fields": {"implementer": "grok", "timeout": 60} if fields is None else fields,
        "summary": summary,
    }
    return f"notes\n```inbox-proposal\n{json.dumps(payload)}\n```\n"


def _runner(replies):
    calls = []
    queue = list(replies)

    def run_fn(command, prompt, **kwargs):
        calls.append({"command": list(command), "prompt": prompt, **kwargs})
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, tuple):
            code, output = item
            return SimpleNamespace(exit_code=code, output=output)
        return SimpleNamespace(exit_code=0, output=item)

    return calls, run_fn


def _set_pair(conn, primary="claude", backup="grok"):
    for key, value in (
        (assistant.ASSISTANT_KEY, primary),
        (assistant.BACKUP_KEY, backup),
    ):
        conn.execute(
            """
            INSERT INTO kv (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _snapshot(conn):
    ideas = [tuple(row) for row in conn.execute("SELECT * FROM ideas ORDER BY id")]
    events = [tuple(row) for row in conn.execute("SELECT * FROM events ORDER BY id")]
    kv = [
        (row["key"], row["value"])
        for row in conn.execute("SELECT key, value FROM kv ORDER BY key")
    ]
    return ideas, events, kv


def _read_only(agent):
    base = scoring._base_command(agent)
    command = capabilities.read_only_command(agent, base)
    return scoring._without_missing_settings(command, paths.workspace())


def test_implement_with_grok_proposes_plan_setup_and_changes_nothing(conn):
    idea = store.add(conn, "Ship the inbox", source="test")
    _set_pair(conn)
    before = _snapshot(conn)
    calls, run_fn = _runner([_block()])

    proposal = assistant.propose(
        conn,
        "implement with grok, one hour timeout",
        idea=idea,
        context="Set up card",
        run_fn=run_fn,
    )

    assert proposal.kind == "plan_setup"
    assert proposal.fields["implementer"] == "grok"
    assert proposal.fields["timeout"] == 60
    assert proposal.summary == "Use grok as the implementer with a one hour limit."
    assert proposal.error is None
    assert proposal.card is not None
    assert proposal.card.title == "Set up"
    assert proposal.card.buttons == ("Confirm", "Edit", "Cancel")
    assert "implementer: grok" in proposal.card.body
    assert "timeout: 60" in proposal.card.body
    assert "Nothing changes until you tap Confirm." in proposal.card.body
    assert proposal.card == assistant.confirm_card(
        "plan_setup",
        summary=proposal.summary,
        fields=proposal.fields,
        idea=idea,
    )
    got = store.get(conn, idea.id)
    assert got.status == "captured"
    assert got.revision == idea.revision
    assert _snapshot(conn) == before
    assert calls[0]["cwd"] == paths.workspace()
    assert calls[0]["timeout_seconds"] == 120
    assert calls[0]["command"] == _read_only("claude")
    prompt = calls[0]["prompt"]
    assert "implement with grok, one hour timeout" in prompt
    assert "title: Ship the inbox" in prompt
    assert "status: captured" in prompt
    assert "Set up card" in prompt
    assert "One hour is 60" in prompt
    assert "agents: claude, codex, grok" in prompt
    assert "timeouts: 15, 30, 45, 60, none" in prompt


def test_unknown_repo_is_rejected_naming_it(conn):
    idea = store.add(conn, "Ship the inbox", source="test")
    _set_pair(conn)
    before = _snapshot(conn)
    calls, run_fn = _runner(
        [
            _block(
                fields={"repo": "no-such-repo", "implementer": "grok"},
                summary="Plan in no-such-repo.",
            )
        ]
    )

    proposal = assistant.propose(
        conn,
        "plan this in no-such-repo",
        idea=idea,
        context="Set up card",
        run_fn=run_fn,
    )

    assert proposal.card is None
    assert proposal.error == "unknown repo no-such-repo"
    assert "no-such-repo" in proposal.error
    assert len(calls) == 1
    assert store.get(conn, idea.id).status == "captured"
    assert _snapshot(conn) == before


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"implementer": "claude"}, "unknown agent claude"),
        ({"repo": "no-such-repo"}, "unknown repo no-such-repo"),
        ({"timeout": 90}, "unknown timeout 90"),
        ({"action": "publish"}, "unknown action publish"),
        ({"idea_id": 9}, "unknown idea 9"),
        ({"release": "codex"}, "unknown agent codex"),
    ],
)
def test_validate_names_the_rejected_value(fields, named):
    allowed = assistant.Allowed(
        agents=frozenset({"grok"}),
        repos=frozenset({"agentdock"}),
        timeouts=frozenset(assistant.TIMEOUTS),
        actions=frozenset({"stop"}),
        idea_ids=frozenset({1}),
    )
    proposal = assistant.Proposal(
        kind="plan_setup",
        fields=fields,
        summary="Change one field.",
    )

    result = assistant.validate(proposal, allowed)

    assert result.card is None
    assert result.error == named


def test_human_release_is_allowed(conn):
    allowed = assistant.allowlist(conn)
    proposal = assistant.Proposal(
        kind="plan_setup",
        fields={"release": "human", "implementer": "grok", "timeout": "60m"},
        summary="Keep release with the user.",
    )

    result = assistant.validate(proposal, allowed)

    assert result.error is None
    assert result.card is not None
    assert result.card.buttons == assistant.CONFIRM_BUTTONS
    assert result.fields["timeout"] == 60
    assert "release: human" in result.card.body


def test_fence_inside_a_json_envelope_is_read(conn):
    idea = store.add(conn, "Ship the inbox", source="test")
    _set_pair(conn)
    envelope = json.dumps({"result": _block(summary="Read from the envelope.")})
    _calls, run_fn = _runner([envelope])

    proposal = assistant.propose(
        conn,
        "implement with grok, one hour timeout",
        idea=idea,
        context="Set up card",
        run_fn=run_fn,
    )

    assert proposal.kind == "plan_setup"
    assert proposal.summary == "Read from the envelope."
    assert proposal.fields["implementer"] == "grok"
    assert proposal.fields["timeout"] == 60


def test_codex_reply_is_read_from_its_output_file(conn):
    idea = store.add(conn, "Ship the inbox", source="test")
    _set_pair(conn, "codex", "grok")
    calls = []

    def run_fn(command, prompt, **kwargs):
        calls.append({"command": list(command), "cwd": kwargs["cwd"]})
        answer = Path(command[command.index("-o") + 1])
        answer.write_text(_block(summary="Read from the answer file."), encoding="utf-8")
        return SimpleNamespace(exit_code=0, output="session log, not the proposal")

    proposal = assistant.propose(
        conn,
        "implement with grok, one hour timeout",
        idea=idea,
        context="Set up card",
        run_fn=run_fn,
    )

    assert proposal.agent == "codex"
    assert proposal.summary == "Read from the answer file."
    assert proposal.fields["timeout"] == 60
    assert calls[0]["cwd"] == paths.workspace()
    assert calls[0]["command"][: len(_read_only("codex"))] == _read_only("codex")


def test_chat_backup_skips_an_agent_that_cannot_run_unattended(conn, monkeypatch):
    monkeypatch.setattr(
        "whyline.paths.find_repo_root", lambda start=None: Path("/repo")
    )
    monkeypatch.setattr("whyline.model.resolve", lambda root: ("grok", ""))
    monkeypatch.setattr(
        "whyline.console.relay_ops.read_backup",
        lambda root: ["antigravity", "codex"],
    )
    monkeypatch.setattr(
        "whyline.account.detect",
        lambda: {"claude": {"available": True}},
    )

    assert assistant.selected(conn) == ("grok", "codex")


def test_primary_failure_uses_the_backup(conn):
    idea = store.add(conn, "Ship the inbox", source="test")
    _set_pair(conn, "claude", "grok")
    calls, run_fn = _runner(
        ["no proposal in this reply", _block(summary="Backup read the request.")]
    )

    proposal = assistant.propose(
        conn,
        "implement with grok, one hour timeout",
        idea=idea,
        context="Set up card",
        run_fn=run_fn,
    )

    assert [call["agent_name"] for call in calls] == ["claude", "grok"]
    assert proposal.agent == "grok"
    assert proposal.kind == "plan_setup"
    assert proposal.fields["implementer"] == "grok"
    assert proposal.fields["timeout"] == 60
    assert proposal.summary == "Backup read the request."
    assert proposal.card is not None
    assert all(call["cwd"] == paths.workspace() for call in calls)
    assert all(call["timeout_seconds"] == 120 for call in calls)


def test_both_failing_gives_the_help_reply(conn):
    idea = store.add(conn, "Ship the inbox", source="test")
    _set_pair(conn, "claude", "grok")
    before = _snapshot(conn)
    calls, run_fn = _runner([RuntimeError("claude is down"), "still no block"])

    proposal = assistant.propose(
        conn,
        "implement with grok, one hour timeout",
        idea=idea,
        context="Set up card",
        run_fn=run_fn,
    )

    assert [call["agent_name"] for call in calls] == ["claude", "grok"]
    assert proposal.card is None
    assert proposal.reply == assistant.HELP_TEXT
    assert proposal.help_command == "/help"
    assert "I couldn't read that. Use the buttons or a `key: value` message" in str(proposal)
    assert "/help" in str(proposal)
    assert store.get(conn, idea.id).status == "captured"
    assert _snapshot(conn) == before


def test_stop_proposal_opens_the_stop_card_and_does_not_stop(conn):
    idea = store.add(conn, "Ship the inbox", source="test")
    conn.execute("UPDATE ideas SET status = 'running' WHERE id = ?", (idea.id,))
    idea = store.get(conn, idea.id)
    _set_pair(conn)
    before = _snapshot(conn)
    calls, run_fn = _runner(
        [_block(kind="stop", fields={}, summary="Stop the relay for this idea.")]
    )

    proposal = assistant.propose(
        conn,
        "stop it",
        idea=idea,
        context="Status card",
        run_fn=run_fn,
    )

    expected = assistant.confirm_card(
        "stop",
        summary="Stop the relay for this idea.",
        fields={},
        idea=idea,
    )
    assert proposal.kind == "stop"
    assert proposal.card == expected
    assert proposal.card.title == "Stop"
    assert proposal.card.buttons == ("Confirm", "Edit", "Cancel")
    assert "Nothing stops until you tap Confirm." in proposal.card.body
    assert "Ship the inbox" in proposal.card.body
    got = store.get(conn, idea.id)
    assert got.status == "running"
    assert got.revision == idea.revision
    assert _snapshot(conn) == before
    assert calls[0]["cwd"] == paths.workspace()
    assert calls[0]["cwd"] != Path.cwd()


def test_resolve_proposal_opens_the_resolve_card_and_does_not_resolve(conn):
    idea = store.add(conn, "Ship the inbox", source="test")
    conn.execute("UPDATE ideas SET status = 'paused' WHERE id = ?", (idea.id,))
    idea = store.get(conn, idea.id)
    _set_pair(conn)
    before = _snapshot(conn)
    calls, run_fn = _runner(
        [
            _block(
                kind="resolve",
                fields={"action": "resume"},
                summary="Resume the paused run.",
            )
        ]
    )

    proposal = assistant.propose(
        conn,
        "resume it",
        idea=idea,
        context="Pause card",
        run_fn=run_fn,
    )

    assert proposal.card == assistant.confirm_card(
        "resolve",
        summary=proposal.summary,
        fields=proposal.fields,
        idea=idea,
    )
    assert proposal.card.title == "Resolve"
    assert "Nothing is resolved until you tap Confirm." in proposal.card.body
    assert store.get(conn, idea.id).status == "paused"
    assert _snapshot(conn) == before
    assert calls[0]["cwd"] == paths.workspace()


def test_stored_pair_is_who_runs(conn, monkeypatch):
    _set_pair(conn, "grok", "codex")
    monkeypatch.setattr(
        "whyline.paths.find_repo_root", lambda start=None: Path("/repo")
    )
    monkeypatch.setattr("whyline.model.resolve", lambda root: ("claude", "opus"))

    assert assistant.selected(conn) == ("grok", "codex")


def test_defaults_use_the_chat_agent_and_its_backup(conn, monkeypatch):
    monkeypatch.setattr(
        "whyline.paths.find_repo_root", lambda start=None: Path("/repo")
    )
    monkeypatch.setattr("whyline.model.resolve", lambda root: ("codex", "gpt"))
    monkeypatch.setattr(
        "whyline.console.relay_ops.read_backup",
        lambda root: ["grok", "claude"],
    )

    assert assistant.selected(conn) == ("codex", "grok")


def test_unusable_chat_agent_falls_back_to_the_first_two(conn, monkeypatch):
    monkeypatch.setattr(
        "whyline.paths.find_repo_root", lambda start=None: Path("/repo")
    )
    monkeypatch.setattr("whyline.model.resolve", lambda root: ("antigravity", ""))
    monkeypatch.setattr(
        "whyline.console.relay_ops.read_backup", lambda root: ["claude"]
    )
    monkeypatch.setattr(
        "whyline.account.detect",
        lambda: {
            "claude": {"available": True},
            "codex": {"available": True},
            "grok": {"available": True},
            "antigravity": {"available": True},
        },
    )

    assert assistant.selected(conn) == ("claude", "codex")


def test_unusable_chat_backup_keeps_the_chat_agent(conn, monkeypatch):
    monkeypatch.setattr(
        "whyline.paths.find_repo_root", lambda start=None: Path("/repo")
    )
    monkeypatch.setattr("whyline.model.resolve", lambda root: ("grok", ""))
    monkeypatch.setattr(
        "whyline.console.relay_ops.read_backup", lambda root: ["antigravity"]
    )
    monkeypatch.setattr(
        "whyline.account.detect",
        lambda: {
            "claude": {"available": True},
            "codex": {"available": True},
            "grok": {"available": True},
            "antigravity": {"available": True},
        },
    )

    assert assistant.selected(conn) == ("grok", "claude")


def test_no_chat_settings_use_the_first_two_detected(conn, monkeypatch):
    monkeypatch.setattr("whyline.paths.find_repo_root", lambda start=None: None)
    monkeypatch.setattr("whyline.model.load_global", lambda: {})
    monkeypatch.setattr(
        "whyline.account.detect",
        lambda: {
            "claude": {"available": True},
            "codex": {"available": False},
            "grok": {"available": True},
            "antigravity": {"available": True},
        },
    )

    assert assistant.selected(conn) == ("claude", "grok")


def test_idea_assistant_stores_the_pair(ideas_home, capsys):
    code = cli.main(["idea", "assistant", "grok", "--backup", "codex"])
    captured = capsys.readouterr()

    assert code == 0, captured.err
    assert captured.out.splitlines()[0] == "grok codex"
    conn = store.connect()
    try:
        assert assistant.selected(conn) == ("grok", "codex")
    finally:
        conn.close()


def test_idea_assistant_refuses_an_agent_that_cannot_run_unattended(ideas_home, capsys):
    code = cli.main(["idea", "assistant", "antigravity", "--backup", "grok"])
    captured = capsys.readouterr()

    assert code == 1
    assert "antigravity: not cleared for unattended runs" in captured.err
    conn = store.connect()
    try:
        row = conn.execute(
            "SELECT value FROM kv WHERE key = 'assistant'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None
