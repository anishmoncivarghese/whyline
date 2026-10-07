import json

import pytest

from whyline.agents import definitions as d, service, state


class Result:
    exit_code, output = 0, json.dumps({"result": "ok", "permission_denials": []})


def _write(folder, name, extra=""):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.toml").write_text(f'name="{name}"\ninstructions="x"\nrunner="claude"\n{extra}')


def test_find_prefers_exact_kind_and_reports_ambiguity(repo, home):
    _write(repo / ".whyline/agents", "both")
    _write(home / ".whyline/agents", "both", 'workdir="~"')
    with pytest.raises(service.Ambiguous):
        service.find("both", repo)
    assert service.find("personal:both", repo).kind == "personal"
    with pytest.raises(service.AgentNotFound):
        service.find("nope", repo)


def test_save_new_accepts_and_describe_reads_like_the_spec(repo, home):
    text = ('name="digest"\ninstructions="x"\nrunner="claude"\nbackup=["codex"]\n'
            'sources=["docs"]\nreport_folder="~/Reports/d"\n[trigger]\nkind="weekdays"\nat="07:00"')
    defn = d.parse(text, kind="repo", path=repo / ".whyline/agents/digest.toml", repo_root=repo)
    service.save_new(defn)
    assert state.status_of(state.connect(), defn) == "active"
    assert service.describe(defn) == (
        "Every weekday at 07:00 on this Mac, claude reads docs (read-only) and answers your "
        "instructions. If claude is out of usage or logged out, codex runs it instead. It can't "
        "change files. Results go to history, a notification, and ~/Reports/d/<date>.md."
    )


def test_rows_run_now_history_pause(repo, home):
    _write(repo / ".whyline/agents", "a")
    service.accept("a", repo)
    rec = service.run_now("a", repo, run_fn=lambda *a, **k: Result())
    assert rec.outcome == "succeeded"
    [row] = [r for r in service.rows(repo) if getattr(r.defn, "name", "") == "a"]
    assert (row.status, row.last_outcome, row.when) == ("active", "succeeded", "on demand")
    assert service.history("a", repo)[0].run_id == rec.run_id
    service.pause("a", repo)
    assert service.rows(repo)[0].status == "paused"


def test_delete_removes_file_and_activation(repo, home):
    _write(repo / ".whyline/agents", "a")
    service.accept("a", repo)
    service.delete("a", repo)
    assert not (repo / ".whyline/agents/a.toml").exists()
    assert state.all_activations(state.connect()) == []
