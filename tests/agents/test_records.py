import json
from datetime import datetime

from whyline import ledger, paths as wpaths
from whyline.agents import definitions as d, records

NOW = datetime(2026, 10, 5, 7, 0, 3)


def _agent(repo, report=""):
    text = f'name="digest"\ninstructions="x"\nrunner="claude"\nreport_folder="{report}"'
    return d.parse(text, kind="repo", path=repo / ".whyline/agents/digest.toml", repo_root=repo)


def test_new_run_creates_a_private_folder(repo):
    rec, folder = records.new_run(_agent(repo), source="manual", now=NOW)
    assert rec.run_id.startswith("20261005-070003-digest-") and len(rec.run_id.split("-")[-1]) == 4
    assert folder.is_dir() and (folder.stat().st_mode & 0o777) == 0o700


def test_finish_writes_metadata_final_report_and_ledger(repo, home):
    agent = _agent(repo, report="~/Reports/digest")
    rec, folder = records.new_run(agent, source="schedule", now=NOW)
    rec.cli, rec.outcome, rec.ended = "codex", "succeeded", NOW.isoformat()
    rec.used_backup = {"cli": "codex", "because": "claude: usage_limit until 15:00"}
    records.finish(rec, folder, final_text="All quiet.", defn=agent)
    meta = json.loads((folder / "metadata.json").read_text())
    assert meta["outcome"] == "succeeded" and meta["used_backup"]["cli"] == "codex"
    assert (folder / "final.md").read_text() == "All quiet.\n"
    assert (home / "Reports/digest/2026-10-05.md").read_text() == "All quiet.\n"
    events, _ = ledger.read_all(wpaths.ledger_path(repo))
    assert events[-1]["type"] == "AgentRunCompleted" and events[-1]["run_id"] == rec.run_id
    assert "All quiet" not in json.dumps(events[-1])


def test_a_second_report_the_same_day_gets_a_time_suffix(repo, home):
    agent = _agent(repo, report="~/Reports/digest")
    for minute in (0, 30):
        rec, folder = records.new_run(agent, source="manual", now=NOW.replace(minute=minute))
        rec.outcome = "succeeded"
        records.finish(rec, folder, final_text="x", defn=agent)
    assert sorted(p.name for p in (home / "Reports/digest").iterdir()) == ["2026-10-05-0730.md", "2026-10-05.md"]


def test_metadata_records_the_accepted_definition_hash(repo):
    text = 'name="digest"\ninstructions="x"\nrunner="claude"\n'
    path = repo / ".whyline" / "agents" / "digest.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    agent = d.parse(text, kind="repo", path=path, repo_root=repo)
    rec, folder = records.new_run(agent, source="manual", now=NOW)
    rec.outcome = "succeeded"
    records.finish(rec, folder, final_text="ok", defn=agent)
    meta = json.loads((folder / "metadata.json").read_text())
    assert meta["definition_hash"] == d.definition_hash(text)
    assert meta["definition_hash"] != d.definition_hash(d.render(agent))


def test_definition_hash_stays_the_one_captured_at_start(repo):
    started = 'name="digest"\ninstructions="x"\nrunner="claude"\n'
    changed = 'name="digest"\ninstructions="changed while running"\nrunner="claude"\n'
    path = repo / ".whyline" / "agents" / "digest.toml"
    path.parent.mkdir(parents=True)
    path.write_text(started)
    agent = d.parse(started, kind="repo", path=path, repo_root=repo)
    rec, folder = records.new_run(agent, source="manual", now=NOW)
    path.write_text(changed)
    rec.outcome = "succeeded"
    records.finish(rec, folder, final_text="ok", defn=agent)
    meta = json.loads((folder / "metadata.json").read_text())
    assert meta["definition_hash"] == d.definition_hash(started)
    assert meta["definition_hash"] != d.definition_hash(changed)


def test_same_minute_reports_are_not_overwritten(repo, home):
    agent = _agent(repo, report="~/Reports/digest")
    for text in ("one", "two", "three", "four"):
        rec, folder = records.new_run(agent, source="manual", now=NOW)
        rec.outcome = "succeeded"
        records.finish(rec, folder, final_text=text, defn=agent)
    folder = home / "Reports/digest"
    assert (folder / "2026-10-05.md").read_text() == "one\n"
    assert (folder / "2026-10-05-0700.md").read_text() == "two\n"
    assert (folder / "2026-10-05-070003.md").read_text() == "three\n"
    assert (folder / "2026-10-05-070003-2.md").read_text() == "four\n"
    assert len(list(folder.iterdir())) == 4


def test_failed_runs_write_no_report(repo, home):
    agent = _agent(repo, report="~/Reports/digest")
    rec, folder = records.new_run(agent, source="manual", now=NOW)
    rec.outcome = "failed"
    records.finish(rec, folder, final_text="", defn=agent)
    assert not (home / "Reports/digest").exists()


def test_list_runs_newest_first(repo):
    agent = _agent(repo)
    for minute in (1, 2, 3):
        rec, folder = records.new_run(agent, source="manual", now=NOW.replace(minute=minute))
        rec.outcome = "succeeded"
        records.finish(rec, folder, final_text=str(minute), defn=agent)
    runs = records.list_runs(agent.agent_id, limit=2)
    assert [records.read_final(r.run_id) for r in runs] == ["3\n", "2\n"]
