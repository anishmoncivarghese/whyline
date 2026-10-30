"""The job tracker: scores from a run into jobs.sqlite and jobs.xlsx (JOB-14)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import cli
from whyline.agents import after, records
from whyline.jobs import tracker


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    return home_dir


def _run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    manifest = {
        "01-acme-engineer.md": {"uid": "u1", "company": "Acme", "title": "Engineer", "url": "https://a/1"},
        "02-beta-designer.md": {"uid": "u2", "company": "Beta", "title": "Designer", "url": "https://b/2"},
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


def _answer(items) -> str:
    return "Done.\n```scores\n" + json.dumps(items) + "\n```\n"


def _item(name, total, verdict="shortlist", reason="fits"):
    return {"file": name, "total": total, "verdict": verdict, "reason": reason}


def test_scores_are_upserted(tmp_path):
    run = _run_dir(tmp_path)
    text = _answer([_item("01-acme-engineer.md", 82), _item("02-beta-designer.md", 40, "skip", "no")])
    assert tracker.record_run(run, text) == 2
    rows = {r["uid"]: r for r in tracker.list_rows()}
    assert rows["u1"]["score"] == 82 and rows["u1"]["company"] == "Acme"
    assert rows["u1"]["verdict"] == "shortlist" and rows["u1"]["status"] == "shortlisted"
    assert rows["u2"]["status"] == "new" and rows["u2"]["reason"] == "no"
    assert tracker.record_run(run, _answer([_item("01-acme-engineer.md", 90)])) == 1
    assert len(tracker.list_rows()) == 2
    assert [r["uid"] for r in tracker.list_rows(min_score=80)] == ["u1"]
    assert tracker.list_rows(min_score=80)[0]["score"] == 90


def test_an_unknown_file_is_ignored(tmp_path):
    run = _run_dir(tmp_path)
    text = _answer([_item("99-ghost.md", 70), _item("01-acme-engineer.md", 70)])
    assert tracker.record_run(run, text) == 1
    assert [r["uid"] for r in tracker.list_rows()] == ["u1"]


@pytest.mark.parametrize(
    "text",
    ["no block at all", "```scores\nnot json\n```", '```scores\n{"file": "x"}\n```', ""],
)
def test_a_malformed_block_records_nothing(tmp_path, text):
    run = _run_dir(tmp_path)
    assert tracker.record_run(run, text) == 0
    assert tracker.list_rows() == []


def test_status_changes_are_kept_on_the_next_run(tmp_path):
    run = _run_dir(tmp_path)
    tracker.record_run(run, _answer([_item("01-acme-engineer.md", 70)]))
    tracker.set_status("1", "applied", "sent cv")
    tracker.record_run(run, _answer([_item("01-acme-engineer.md", 95, "maybe")]))
    (row,) = tracker.list_rows()
    assert (row["status"], row["notes"], row["score"], row["verdict"]) == ("applied", "sent cv", 95, "maybe")
    assert tracker.list_rows(status="applied")[0]["uid"] == "u1"
    tracker.set_status("u1", "offer")
    assert tracker.list_rows()[0]["notes"] == "sent cv"
    with pytest.raises(tracker.TrackerError):
        tracker.set_status("u1", "bogus")
    with pytest.raises(tracker.TrackerError):
        tracker.set_status("nope", "applied")


def test_the_xlsx_opens_with_zipfile_and_has_the_rows(tmp_path):
    run = _run_dir(tmp_path)
    tracker.record_run(run, _answer([_item("01-acme-engineer.md", 82), _item("02-beta-designer.md", 40, "skip")]))
    target = tracker.xlsx_path()
    assert target.exists()
    with zipfile.ZipFile(target) as package:
        sheet = package.read("xl/worksheets/sheet1.xml").decode()
    assert sheet.count("<row ") == 3
    assert "Acme" in sheet and "Designer" in sheet and "shortlisted" in sheet


def test_the_cli_lists_sets_and_writes_the_excel(tmp_path, capsys):
    tracker.record_run(_run_dir(tmp_path), _answer([_item("01-acme-engineer.md", 82)]), export=False)
    assert cli.main(["jobs", "list", "--min-score", "50"]) == 0
    assert "Acme — Engineer" in capsys.readouterr().out
    assert cli.main(["jobs", "set", "1", "interview", "--note", "call Tue"]) == 0
    assert "interview" in capsys.readouterr().out
    assert cli.main(["jobs", "list", "--status", "new"]) == 0
    assert "No tracked jobs." in capsys.readouterr().out
    assert cli.main(["jobs", "set", "9", "applied"]) == 1
    capsys.readouterr()
    assert cli.main(["jobs", "excel"]) == 0
    assert tracker.xlsx_path().exists()


def test_the_post_run_hook_tracks_a_success_and_never_raises(tmp_path, monkeypatch):
    run = _run_dir(tmp_path)
    final = _answer([_item("01-acme-engineer.md", 77)])
    monkeypatch.setattr(records, "run_folder", lambda run_id: run)
    monkeypatch.setattr(records, "read_final", lambda run_id: final)
    defn = SimpleNamespace(before="jobs-fetch")
    after._post_run(defn, SimpleNamespace(run_id="r", outcome="failed"))
    assert tracker.list_rows() == []
    after._post_run(defn, SimpleNamespace(run_id="r", outcome="succeeded"))
    assert [r["score"] for r in tracker.list_rows()] == [77]

    def boom(run_id):
        raise OSError("gone")

    monkeypatch.setattr(records, "read_final", boom)
    after._post_run(defn, SimpleNamespace(run_id="r", outcome="succeeded"))
    after._post_run(SimpleNamespace(before=""), SimpleNamespace(run_id="r", outcome="succeeded"))
