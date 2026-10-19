"""CLI coverage for `whyline idea`."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import cli
from whyline.ideas import documents, store


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


def invoke(argv, capsys):
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


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


def _runner(replies):
    calls = []
    queue = list(replies)

    def run_fn(command, prompt, **kwargs):
        calls.append({"prompt": prompt, "agent_name": kwargs.get("agent_name")})
        item = queue.pop(0)
        return SimpleNamespace(exit_code=0, output=item)

    return calls, run_fn


def _add(capsys, text):
    code, out, err = invoke(["idea", "add", text], capsys)
    assert code == 0, err
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[0].isdigit()
    assert Path(lines[-1]).is_file()
    return lines[0]


def test_add_then_list_shows_the_idea(ideas_home, capsys):
    idea_id = _add(capsys, "Ship a local idea inbox")

    code, out, err = invoke(["idea", "list"], capsys)

    assert code == 0, err
    assert f"{idea_id}  captured  Ship a local idea inbox" in out


def test_drop_then_reopen_round_trips(ideas_home, capsys):
    idea_id = _add(capsys, "Round trip")

    code, out, err = invoke(["idea", "drop", idea_id], capsys)
    assert code == 0, err
    assert f"idea {idea_id}  dropped" in out
    code, out, err = invoke(["idea", "list", "--status", "dropped"], capsys)
    assert code == 0, err
    assert f"{idea_id}  dropped  Round trip" in out

    code, out, err = invoke(["idea", "reopen", idea_id], capsys)
    assert code == 0, err
    assert f"idea {idea_id}  captured" in out
    code, out, err = invoke(["idea", "list"], capsys)
    assert f"{idea_id}  captured  Round trip" in out
    code, out, err = invoke(["idea", "list", "--status", "dropped"], capsys)
    assert idea_id not in out
    assert code == 0, err


def test_score_with_a_fake_runner_prints_the_scores(ideas_home, capsys, monkeypatch):
    calls, run_fn = _runner([_wrap(_payload())])
    monkeypatch.setattr("whyline_relay.agents.run", run_fn)
    idea_id = _add(capsys, "Score this idea")

    code, out, err = invoke(["idea", "score", idea_id, "--agent", "claude"], capsys)

    assert code == 0, err
    assert "agent: claude" in out
    assert "usefulness: 7" in out
    assert "complexity_mvp: 4" in out
    assert "complexity_full: 8" in out
    assert "verdict: YES" in out
    assert Path(out.splitlines()[-1]).is_file()
    assert [call["agent_name"] for call in calls] == ["claude"]

    code, shown, err = invoke(["idea", "show", idea_id], capsys)
    assert code == 0, err
    assert "Usefulness: 7/9" in shown
    assert "documents:" in shown
    assert "brainstorm:" in shown
    assert "history:" in shown
    assert "captured -> scoring" in shown
    assert "scoring -> scored" in shown


def test_refine_appends_context_and_scores_again(ideas_home, capsys, monkeypatch):
    calls, run_fn = _runner(
        [
            _wrap(_payload(title="First cut")),
            _wrap(_payload(title="Second cut", usefulness=6, verdict="NOT YET")),
        ]
    )
    monkeypatch.setattr("whyline_relay.agents.run", run_fn)
    idea_id = _add(capsys, "Keep a private ledger")
    code, _out, err = invoke(["idea", "score", idea_id, "--agent", "claude"], capsys)
    assert code == 0, err

    code, out, err = invoke(
        ["idea", "refine", idea_id, "Ship it on this Mac", "--agent", "codex"],
        capsys,
    )

    assert code == 0, err
    assert "agent: codex" in out
    assert "usefulness: 6" in out
    assert "verdict: NOT YET" in out
    assert "Ship it on this Mac" in calls[-1]["prompt"]
    code, shown, err = invoke(["idea", "show", idea_id], capsys)
    assert code == 0, err
    assert "Ship it on this Mac" in shown
    assert "scored -> scored" in shown
    assert "scored -> scoring" in shown
    assert "Second cut" in shown
    assert "# Second cut" in shown or "title: Second cut" in shown


def test_doctor_reports_an_unwritable_workbook_and_a_missing_cupsfilter(
    ideas_home, capsys, monkeypatch
):
    ideas_home.mkdir()
    ideas_home.chmod(0o700)
    workbook = ideas_home / "ideas.xlsx"
    workbook.write_bytes(b"locked")
    workbook.chmod(0o444)
    monkeypatch.setattr(documents, "CUPSFILTER", str(ideas_home / "missing-cupsfilter"))

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert "workbook is not writable" in text
    assert "cupsfilter is missing" in text
    assert ideas_home.stat().st_mode & 0o777 == 0o700


def test_doctor_reports_a_0755_folder_and_leaves_it(ideas_home, capsys):
    ideas_home.mkdir()
    ideas_home.chmod(0o755)

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert f"{ideas_home} mode is 0755, expected 0700" in text
    assert ideas_home.stat().st_mode & 0o777 == 0o755
    assert not (ideas_home / "ideas.sqlite3").exists()
    assert list(ideas_home.iterdir()) == []


def test_doctor_does_not_create_an_absent_ledger(ideas_home, capsys):
    ideas_home.mkdir()
    ideas_home.chmod(0o700)
    database = ideas_home / "ideas.sqlite3"

    code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert code == 1
    assert f"ideas database is missing ({database})" in text
    assert not database.exists()
    assert list(ideas_home.iterdir()) == []
    assert ideas_home.stat().st_mode & 0o777 == 0o700


def test_doctor_reads_an_existing_ledger_without_changing_it(ideas_home, capsys):
    ideas_home.mkdir()
    ideas_home.chmod(0o700)
    conn = store.connect()
    conn.close()
    database = ideas_home / "ideas.sqlite3"
    before = database.read_bytes()
    mode = database.stat().st_mode & 0o777

    _code, out, err = invoke(["idea", "doctor"], capsys)

    text = out + err
    assert "ok     schema: schema version 3" in text
    assert f"ok     folder: {ideas_home} mode 0700" in text
    assert database.read_bytes() == before
    assert database.stat().st_mode & 0o777 == mode
    assert ideas_home.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    "argv",
    [
        ["idea", "show", "42"],
        ["idea", "score", "42"],
        ["idea", "drop", "42"],
        ["idea", "reopen", "42"],
        ["idea", "refine", "42", "more context"],
    ],
)
def test_unknown_id_exits_1(ideas_home, capsys, argv):
    code, _out, err = invoke(argv, capsys)
    assert code == 1
    assert "no idea 42" in err


def test_agents_sets_the_default_used_by_score(ideas_home, capsys, monkeypatch):
    calls, run_fn = _runner([_wrap(_payload())])
    monkeypatch.setattr("whyline_relay.agents.run", run_fn)
    idea_id = _add(capsys, "Use the saved default")
    code, out, err = invoke(["idea", "agents", "codex"], capsys)
    assert code == 0, err
    assert out.splitlines()[0] == "codex"

    code, out, err = invoke(["idea", "score", idea_id], capsys)

    assert code == 0, err
    assert "agent: codex" in out
    assert [call["agent_name"] for call in calls] == ["codex"]


def test_documents_stores_the_format(ideas_home, capsys):
    code, out, err = invoke(["idea", "documents", "word"], capsys)
    assert code == 0, err
    assert out.splitlines()[0] == "word"
    assert Path(out.splitlines()[-1]).is_file()
    conn = store.connect()
    try:
        row = conn.execute(
            "SELECT value FROM kv WHERE key = 'doc_formats'"
        ).fetchone()
    finally:
        conn.close()
    assert row["value"] == "word"
