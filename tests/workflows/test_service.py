import json
from datetime import datetime, timedelta, timezone

import pytest

from whyline.workflows import definitions as d
from whyline.workflows import service, state
from whyline.workflows.steps import deliver

BRANCHY = '''
name = "branchy"
version = 1

[trigger]
kind = "manual"

[[input]]
name = "count"
type = "number"
default = 1

[[input]]
name = "loud"
type = "boolean"

[[step]]
id = "check"
type = "condition"
left = "{{ inputs.count }}"
op = "gt"
right = "5"
then = "big"
else = "small"

[[step]]
id = "big"
type = "set"
[step.values]
word = "BIG"

[[step]]
id = "small"
type = "set"
[step.values]
word = "small"

[[step]]
id = "ask"
type = "approval"
message = "Send the {{ inputs.count }} report?"

[[step]]
id = "tell"
type = "deliver"
to = "file"
subject = "Count {{ inputs.count }}"
text = "count is {{ inputs.count }}"
'''


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def write(home, name, text=BRANCHY):
    folder = home / ".whyline" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.toml").write_text(text.replace('name = "branchy"', f'name = "{name}"'))


def start(name="branchy", inputs=None, spawn=None):
    return service.run_now(name, inputs or {}, source="manual", repo_root=None,
                           spawn=spawn or (lambda _id: None))


def test_new_creates_a_valid_manual_workflow_that_is_not_accepted(home):
    path = service.new("fresh", "personal", None)
    assert path == home / ".whyline" / "workflows" / "fresh.toml"
    wf = service.load("fresh", None)
    assert wf.trigger.kind == "manual" and [s.type for s in wf.steps] == ["set"]
    assert service.rows(None)[0].status == state.NEEDS_REVIEW
    with pytest.raises(ValueError, match="already exists"):
        service.new("fresh", "personal", None)
    with pytest.raises(ValueError, match="needs a repository"):
        service.new("other", "repo", None)
    with pytest.raises(ValueError, match="lower-case"):
        service.new("Bad Name", "personal", None)


def test_new_in_a_repo(home, tmp_path):
    repo = tmp_path / "repo"
    path = service.new("fresh", "repo", repo)
    assert path == repo / ".whyline" / "workflows" / "fresh.toml"
    assert service.load("fresh", repo).kind == "repo"


def test_validate(home):
    assert service.validate(BRANCHY) == []
    errors = service.validate('name = "x"\n[[step]]\nid = "a"\ntype = "nope"\n')
    assert errors and "type" in errors[0]
    assert "not valid TOML" in service.validate("name = ")[0]


def test_save_writes_the_file(home):
    path = service.new("fresh", "personal", None)
    wf = service.load("fresh", None)
    changed = d.parse(d.render(wf).replace('message = "hello"', 'message = "bye"'),
                      kind="personal", path=path)
    assert service.save(changed) == path
    assert service.load("fresh", None).steps[0].fields["values"] == {"message": "bye"}


def test_rows_show_status_trigger_next_and_last(home):
    write(home, "branchy")
    (home / ".whyline" / "workflows" / "broken.toml").write_text("name = ")
    found = {r.name: r for r in service.rows(None)}
    assert found["branchy"].status == state.NEEDS_REVIEW
    assert found["branchy"].trigger == "on demand"
    assert found["broken"].status == "needs_review" and "TOML" in found["broken"].trigger
    service.accept("branchy", None)
    start()
    row = {r.name: r for r in service.rows(None)}["branchy"]
    assert row.status == "active" and row.last.startswith("running")


def test_load_exact_name_and_missing(home):
    write(home, "branchy")
    assert service.load("branchy", None).name == "branchy"
    with pytest.raises(service.NotFound):
        service.load("branch", None)
    (home / ".whyline" / "workflows" / "broken.toml").write_text("name = ")
    with pytest.raises(d.DefinitionError, match="broken.toml"):
        service.load("broken", None)


def test_same_name_in_repo_and_personal_is_ambiguous(home, tmp_path):
    repo = tmp_path / "repo"
    write(home, "dup")
    folder = repo / ".whyline" / "workflows"
    folder.mkdir(parents=True)
    (folder / "dup.toml").write_text(BRANCHY.replace('name = "branchy"', 'name = "dup"'))
    with pytest.raises(service.Ambiguous) as caught:
        service.load("dup", repo)
    message = str(caught.value)
    assert "personal:dup" in message and f"repo:{repo.resolve()}:dup" in message
    assert service.load("repo:dup", repo).kind == "repo"
    assert service.load("personal:dup", repo).kind == "personal"
    assert service.load(f"repo:{repo.resolve()}:dup", repo).kind == "repo"


def test_review_summary_then_diff_when_reaccepting(home):
    write(home, "branchy")
    first = service.review("branchy", None)
    assert first[0].startswith("Trigger: manual") and "Approval ask" in " ".join(first)
    assert state.get(state.connect(), service.load("branchy", None).workflow_id) is None
    service.accept("branchy", None)
    assert service.review("branchy", None) == []
    write(home, "branchy", BRANCHY.replace('to = "file"', 'to = "email"\nemail = "a@b.co"'))
    diff = service.review("branchy", None)
    assert "- Deliver tell: sends to file" in diff
    assert "+ Deliver tell: sends to email a@b.co" in diff
    act = state.get(state.connect(), service.load("branchy", None).workflow_id)
    assert act.capabilities[-1] == "Deliver tell: sends to file"  # review changed nothing


def test_pause_and_resume_need_acceptance(home):
    write(home, "branchy")
    with pytest.raises(ValueError, match="accept it first"):
        service.pause("branchy", None)
    service.accept("branchy", None)
    service.pause("branchy", None)
    assert service.rows(None)[0].status == state.PAUSED
    service.resume("branchy", None)
    assert service.rows(None)[0].status == state.ACTIVE


def test_run_now_checks_state_and_inputs(home):
    write(home, "branchy")
    spawned = []
    with pytest.raises(ValueError, match="accept it first"):
        start(spawn=spawned.append)
    service.accept("branchy", None)
    with pytest.raises(ValueError, match='unknown input "bogus"'):
        start(inputs={"bogus": "1"}, spawn=spawned.append)
    with pytest.raises(ValueError, match='input "count": must be a number'):
        start(inputs={"count": "many"}, spawn=spawned.append)
    with pytest.raises(ValueError, match='input "loud": must be a boolean'):
        start(inputs={"loud": "maybe"}, spawn=spawned.append)
    assert spawned == []
    run_id = start(inputs={"count": "7", "loud": "true"}, spawn=spawned.append)
    assert spawned == [run_id]
    detail = service.run_detail(run_id)
    assert detail.run["status"] == "running" and detail.run["source"] == "manual"
    assert json.loads(detail.run["inputs_json"]) == {"count": 7, "loud": True}
    service.pause("branchy", None)
    with pytest.raises(ValueError, match="paused: resume it first"):
        start(spawn=spawned.append)


def test_edited_workflow_cannot_run_until_accepted_again(home):
    write(home, "branchy")
    service.accept("branchy", None)
    write(home, "branchy", BRANCHY.replace('"BIG"', '"HUGE"'))
    with pytest.raises(ValueError, match="needs review"):
        start()


def test_second_run_stays_queued_while_one_is_live(home):
    write(home, "branchy")
    service.accept("branchy", None)
    spawned = []
    first = start(spawn=spawned.append)
    second = start(spawn=spawned.append)
    assert spawned == [first]
    assert service.run_detail(second).run["status"] == "queued"
    assert [r["id"] for r in service.runs("branchy", None)] == [second, first]


def test_run_detail_cancel_and_missing_run(home):
    write(home, "branchy")
    service.accept("branchy", None)
    run_id = start()
    assert service.cancel(run_id) == "cancelled"
    assert service.run_detail(run_id).run["status"] == "cancelled"
    with pytest.raises(service.NotFound):
        service.run_detail(999)
    with pytest.raises(service.NotFound):
        service.cancel(999)


def test_retry_a_failed_run_with_the_same_inputs(home):
    write(home, "branchy")
    service.accept("branchy", None)
    run_id = start(inputs={"count": "9"})
    with pytest.raises(ValueError, match="only a failed or cancelled run"):
        service.retry(run_id, spawn=lambda _id: None)
    state.set_run(state.connect(), run_id, status="failed", reason="boom")
    spawned = []
    again = service.retry(run_id, spawn=spawned.append)
    assert again != run_id and spawned == [again]
    new_run = service.run_detail(again).run
    assert new_run["source"] == "retry"
    assert json.loads(new_run["inputs_json"]) == {"count": 9}


def test_decide_approves_a_waiting_run(home):
    write(home, "branchy")
    service.accept("branchy", None)
    run_id = start()
    conn = state.connect()
    state.set_run(conn, run_id, status="waiting", reason="approval")
    row = state.create_approval(conn, run_id, "ask", revision="r", message="ok?",
                                expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert service.decide(row["id"], "wrong", "approve", "me") == "out_of_date"
    assert service.decide(row["id"], row["nonce"], "approve", "me") == "approved"
    assert service.run_detail(run_id).approvals[0]["decided_by"] == "me"
    assert service.decide(row["id"], row["nonce"], "approve", "me") == "out_of_date"


def test_resolve_settles_an_unknown_outcome_run(home):
    write(home, "branchy")
    service.accept("branchy", None)
    run_id = start()
    with pytest.raises(ValueError, match="not unknown_outcome"):
        service.resolve(run_id, "done")
    conn = state.connect()
    state.set_step(conn, run_id, "tell", status="unknown_outcome", seq=4)
    state.set_run(conn, run_id, status="unknown_outcome", reason="may have run")
    with pytest.raises(ValueError, match="choice must be"):
        service.resolve(run_id, "maybe")
    assert service.resolve(run_id, "failed") == "failed"


def test_cap_round_trip(home):
    assert service.get_cap() == 0
    service.set_cap(5)
    assert service.get_cap() == 5
    with pytest.raises(ValueError):
        service.set_cap(-1)


def test_dry_run_shows_branch_taken_and_what_deliver_would_send(home, monkeypatch):
    write(home, "branchy")

    def boom(*args, **kwargs):
        raise AssertionError("a dry run must not call a handler that writes")

    monkeypatch.setattr(deliver, "run_deliver", boom)
    monkeypatch.setattr(deliver.agent_deliver, "send", boom)
    monkeypatch.setattr(deliver, "_write_report", boom)
    monkeypatch.setattr(state, "connect", boom)

    text = "\n".join(service.dry_run("branchy", {"count": "9"}, None))
    assert 'word = "BIG"' in text
    assert "goes to big" in text
    assert "skipped" not in text  # then = the next step, so nothing is jumped over
    assert "would ask for approval" in text and "Send the 9 report?" in text
    assert "would send to file, subject 'Count 9'" in text and "count is 9" in text

    other = "\n".join(service.dry_run("branchy", {"count": "2"}, None))
    assert 'word = "small"' in other and "big (set) skipped" in other
    assert not (home / ".whyline" / "workflows" / "reports").exists()


def test_dry_run_checks_inputs_and_reports_template_failures(home):
    write(home, "branchy")
    with pytest.raises(ValueError, match="unknown input"):
        service.dry_run("branchy", {"nope": "1"}, None)
    text = BRANCHY.replace("count is {{ inputs.count }}", "{{ steps.big.word }}")
    write(home, "branchy", text)
    lines = service.dry_run("branchy", {"count": "1"}, None)
    assert any("would fail" in line and "skipped" in line for line in lines)


def test_dry_run_reports_agent_and_wait(home):
    write(home, "agentic", '''
name = "agentic"
version = 1

[trigger]
kind = "manual"

[[step]]
id = "pause"
type = "wait"
minutes = 5

[[step]]
id = "think"
type = "agent"
runner = "claude"
instructions = "Summarise"
inputs = ["hello {{ run.id }}"]

[[step]]
id = "end"
type = "stop"
''')
    text = "\n".join(service.dry_run("agentic", {}, None))
    assert "would wait for 5 minutes" in text
    assert "would run claude" in text and "Summarise" in text and "hello 0" in text
    assert "the run ends here" in text
