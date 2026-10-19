import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.ideas import analyse, paths, report, store
from whyline_relay.agents import AgentTimeout


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _payload(**overrides):
    data = {
        "title": "Local idea inbox",
        "problem": "Ideas vanish before they are judged.",
        "users": "One person capturing ideas from their phone.",
        "usefulness": 7,
        "complexity_mvp": 4,
        "complexity_full": 8,
        "verdict": "YES",
        "confidence": "medium",
        "existing": [
            {
                "name": "Notion",
                "url": "https://notion.so",
                "how_it_differs": "A workspace, not a scored inbox.",
            }
        ],
        "sources": [{"url": "https://notion.so", "title": "Notion"}],
        "deploy": "On this Mac, beside Whyline.",
        "risks": ["The score depends on the pages opened."],
        "next_step": "Ship capture and one scored report.",
    }
    data.update(overrides)
    return data


def _wrap(payload):
    return f"notes\n```idea-report\n{json.dumps(payload)}\n```\n"


def _events(conn, idea_id):
    return conn.execute(
        "SELECT * FROM events WHERE idea_id = ? ORDER BY id", (idea_id,)
    ).fetchall()


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


def test_valid_answer_stores_version_1_and_moves_to_scored(conn):
    original = "Keep ideas that arrive by message."
    idea = store.add(conn, original, source="test")
    calls, run_fn = _runner([_wrap(_payload())])

    def watching(command, prompt, **kwargs):
        assert store.get(conn, idea.id).status == "scoring"
        return run_fn(command, prompt, **kwargs)

    stored = analyse.analyse(conn, idea.id, agents=["claude"], run_fn=watching)
    got = store.get(conn, idea.id)

    assert stored.version == 1
    assert stored.agent == "claude"
    assert stored.usefulness == 7
    assert stored.complexity_mvp == 4
    assert stored.complexity_full == 8
    assert stored.verdict == "YES"
    assert stored.confidence == "medium"
    assert json.loads(stored.sources_json) == [
        {"url": "https://notion.so", "title": "Notion"}
    ]
    assert got.status == "scored"
    assert got.title == "Local idea inbox"
    assert got.original_text == original
    report_path = Path(stored.report_path)
    assert report_path == paths.reports_dir() / f"{idea.id}-v1.md"
    body = report_path.read_text(encoding="utf-8")
    assert f"> {original}" in body
    assert "# Local idea inbox" in body
    assert "Notion" in body
    if os.name != "nt":
        assert (report_path.stat().st_mode & 0o777) == 0o600
    assert [call["agent_name"] for call in calls] == ["claude"]
    assert calls[0]["cwd"] == paths.workspace()
    assert calls[0]["timeout_seconds"] == 15 * 60
    rows = _events(conn, idea.id)
    assert [(row["from_status"], row["to_status"]) for row in rows] == [
        ("captured", "scoring"),
        ("scoring", "scored"),
    ]


def test_second_analysis_is_version_2(conn):
    idea = store.add(conn, "One idea, scored twice.", source="test")
    _calls, run_fn = _runner(
        [
            _wrap(_payload(title="First cut")),
            _wrap(_payload(title="Second cut", verdict="NOT YET")),
        ]
    )
    first = analyse.analyse(conn, idea.id, agents=["claude"], run_fn=run_fn)
    second = analyse.analyse(conn, idea.id, agents=["codex"], run_fn=run_fn)
    got = store.get(conn, idea.id)

    assert first.version == 1
    assert second.version == 2
    assert second.agent == "codex"
    assert second.verdict == "NOT YET"
    assert got.status == "scored"
    assert got.title == "Second cut"
    assert got.revision == 4
    assert Path(first.report_path).is_file()
    assert Path(second.report_path) == paths.reports_dir() / f"{idea.id}-v2.md"
    assert "Second cut" in Path(second.report_path).read_text(encoding="utf-8")


def test_stale_codex_answer_file_is_not_scored_when_the_rerun_does_not_rewrite_it(conn):
    idea = store.add(conn, "Do not score the previous Codex reply again.", source="test")
    calls = []
    wrote = []

    def run_fn(command, prompt, **kwargs):
        calls.append({"command": list(command), "agent_name": kwargs["agent_name"]})
        if kwargs["agent_name"] != "codex":
            return SimpleNamespace(exit_code=0, output=_wrap(_payload(title="Recovered")))
        answer = Path(command[command.index("-o") + 1])
        if not wrote:
            answer.write_text(_wrap(_payload(title="First cut")), encoding="utf-8")
            wrote.append(answer)
            return SimpleNamespace(exit_code=0, output="session log, not the reply")
        # Exit 0, malformed session, and the -o file from the previous run stays.
        return SimpleNamespace(exit_code=0, output="this is not a report")

    first = analyse.analyse(conn, idea.id, agents=["codex"], run_fn=run_fn)
    second = analyse.analyse(
        conn, idea.id, agents=["codex", "claude"], run_fn=run_fn
    )
    got = store.get(conn, idea.id)
    note = _events(conn, idea.id)[-1]["note"]

    assert first.version == 1
    assert first.agent == "codex"
    assert second.version == 2
    assert second.agent == "claude"
    assert got.status == "scored"
    assert got.title == "Recovered"
    assert "First cut" in Path(first.report_path).read_text(encoding="utf-8")
    assert "Recovered" in Path(second.report_path).read_text(encoding="utf-8")
    assert "codex:" in note and "idea-report" in note
    assert [call["agent_name"] for call in calls] == ["codex", "codex", "claude"]
    assert wrote[0].is_file()
    assert "First cut" in wrote[0].read_text(encoding="utf-8")
    second_answer = Path(calls[1]["command"][calls[1]["command"].index("-o") + 1])
    assert second_answer != wrote[0]
    assert not second_answer.is_file() or "First cut" not in second_answer.read_text(
        encoding="utf-8"
    )


def test_malformed_answer_falls_through_to_the_next_agent(conn):
    idea = store.add(conn, "Needs a real report.", source="test")
    calls, run_fn = _runner(
        ["this is not a report", _wrap(_payload(title="Recovered"))]
    )
    stored = analyse.analyse(
        conn, idea.id, agents=["claude", "codex"], run_fn=run_fn
    )
    got = store.get(conn, idea.id)

    assert [call["agent_name"] for call in calls] == ["claude", "codex"]
    assert stored.agent == "codex"
    assert stored.version == 1
    assert got.status == "scored"
    assert got.title == "Recovered"
    note = _events(conn, idea.id)[-1]["note"]
    assert "claude:" in note
    assert "idea-report" in note


def test_model_failure_falls_through(conn):
    idea = store.add(conn, "The first two agents cannot run.", source="test")
    calls, run_fn = _runner(
        [
            AgentTimeout("claude timed out"),
            (1, "not logged in"),
            _wrap(_payload(title="Third try")),
        ]
    )
    stored = analyse.analyse(
        conn, idea.id, agents=["claude", "codex", "grok"], run_fn=run_fn
    )
    note = _events(conn, idea.id)[-1]["note"]

    assert [call["agent_name"] for call in calls] == ["claude", "codex", "grok"]
    assert stored.agent == "grok"
    assert stored.version == 1
    assert "claude:" in note and "timeout" in note.lower()
    assert "codex:" in note and "not logged in" in note.lower()


def test_antigravity_skipped_unattended_with_its_reason(conn):
    idea = store.add(conn, "Do not run antigravity headless.", source="test")
    calls, run_fn = _runner([_wrap(_payload(title="Scored without agy"))])
    stored = analyse.analyse(
        conn,
        idea.id,
        agents=["antigravity", "claude"],
        run_fn=run_fn,
        unattended=True,
    )
    note = _events(conn, idea.id)[-1]["note"]

    assert [call["agent_name"] for call in calls] == ["claude"]
    assert stored.agent == "claude"
    assert store.get(conn, idea.id).status == "scored"
    assert "antigravity: not cleared for unattended runs" in note


def test_antigravity_skipped_when_watched_for_no_read_only_mode(conn):
    idea = store.add(conn, "Antigravity has no verified read-only mode.", source="test")
    calls, run_fn = _runner([_wrap(_payload())])
    analyse.analyse(
        conn,
        idea.id,
        agents=["antigravity", "claude"],
        run_fn=run_fn,
        unattended=False,
    )
    note = _events(conn, idea.id)[-1]["note"]

    assert [call["agent_name"] for call in calls] == ["claude"]
    assert "antigravity: no verified read-only setting" in note


def test_all_failing_returns_the_idea_to_captured_naming_every_agent(conn):
    idea = store.add(conn, "Nobody could score this.", source="test")
    calls, run_fn = _runner(["nope", "still nope", "also nope"])

    with pytest.raises(analyse.AnalyseError) as caught:
        analyse.analyse(
            conn, idea.id, agents=["claude", "codex", "grok"], run_fn=run_fn
        )

    got = store.get(conn, idea.id)
    note = _events(conn, idea.id)[-1]["note"]
    assert got.status == "captured"
    assert got.title == "Nobody could score this."
    assert got.revision == 2
    assert note == str(caught.value)
    for agent in ("claude", "codex", "grok"):
        assert f"{agent}:" in note
    assert [call["agent_name"] for call in calls] == ["claude", "codex", "grok"]
    assert conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0
    assert list(paths.reports_dir().glob("*.md")) == []
    rows = _events(conn, idea.id)
    assert [(row["from_status"], row["to_status"]) for row in rows] == [
        ("captured", "scoring"),
        ("scoring", "captured"),
    ]


def test_fake_sees_cwd_equal_to_the_workspace(conn):
    idea = store.add(conn, "Run inside the inbox workspace.", source="test")
    conn.execute(
        "UPDATE ideas SET repo = ? WHERE id = ?",
        ("/tmp/some-user-repo", idea.id),
    )
    calls, run_fn = _runner([_wrap(_payload())])
    analyse.analyse(
        conn, idea.id, agents=["claude"], run_fn=run_fn, timeout_minutes=1
    )

    assert calls[0]["cwd"] == paths.workspace()
    assert calls[0]["cwd"] != Path("/tmp/some-user-repo")
    assert calls[0]["timeout_seconds"] == 60
    assert calls[0]["capture"] is True
    assert calls[0]["echo"] is False
    command = calls[0]["command"]
    assert command[0] == "claude"
    assert command[command.index("--permission-mode") + 1] == "plan"
    assert not any("claude-settings.json" in token for token in command)


def test_commands_are_read_only(conn):
    checks = {
        "claude": _assert_claude,
        "codex": _assert_codex,
        "grok": _assert_grok,
    }
    for agent, check in checks.items():
        idea = store.add(conn, f"Score with {agent}.", source="test")
        calls, run_fn = _runner([_wrap(_payload())])
        analyse.analyse(conn, idea.id, agents=[agent], run_fn=run_fn)
        assert calls[0]["cwd"] == paths.workspace()
        check(calls[0]["command"])


def _assert_claude(command):
    assert command[command.index("--permission-mode") + 1] == "plan"
    assert "acceptEdits" not in command
    assert not any("claude-settings.json" in token for token in command)


def _assert_codex(command):
    assert command[command.index("-s") + 1] == "read-only"
    assert "workspace-write" not in command
    assert "-o" in command


def _assert_grok(command):
    assert command[0] == "grok"
    assert command[-1] == "-p"
    names = [token.split("=", 1)[0] for token in command]
    assert "--allow" not in names
    assert "--always-approve" not in names
    assert "--yolo" not in names
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    denied = [
        command[index + 1]
        for index, token in enumerate(command[:-1])
        if token == "--deny"
    ]
    assert "Edit" in denied
    assert "Write" in denied


def test_prompt_holds_the_idea_rubric_recent_ideas_and_instructions(conn):
    target = store.add(conn, "A fresh thought about pigeons.", source="test")
    store.add(conn, "idea-title-OLD", source="test")
    for index in range(50):
        other = store.add(conn, f"idea-title-{index:02d}", source="test")
    store.add_analysis(
        conn,
        other.id,
        agent="claude",
        report_path="ignored.md",
        verdict="YES",
    )
    calls, run_fn = _runner([_wrap(_payload())])
    analyse.analyse(conn, target.id, agents=["claude"], run_fn=run_fn)
    prompt = calls[0]["prompt"]

    assert "A fresh thought about pigeons." in prompt
    assert report.RUBRIC in prompt
    assert f"Rubric version {report.RUBRIC_VERSION}" in prompt
    assert "idea-title-00" in prompt
    assert "idea-title-49 — YES" in prompt
    assert "idea-title-OLD" not in prompt
    assert (
        "Search the web and GitHub for existing products, libraries and "
        "repositories that do this."
    ) in prompt
    assert "List only sources it opened." in prompt
    assert '"not found" is not "does not exist".' in prompt
    assert "End with the idea-report block." in prompt
    assert "Flag a repeat." in prompt


def test_json_envelope_is_parsed(conn):
    idea = store.add(conn, "Wrapped in the CLI's JSON result.", source="test")
    envelope = json.dumps({"result": _wrap(_payload(title="From JSON"))})
    _calls, run_fn = _runner([envelope])
    stored = analyse.analyse(conn, idea.id, agents=["claude"], run_fn=run_fn)

    assert stored.version == 1
    assert store.get(conn, idea.id).title == "From JSON"
    assert store.get(conn, idea.id).status == "scored"
