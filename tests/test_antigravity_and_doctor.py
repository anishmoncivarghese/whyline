"""Item 6 of the brainstorm roadmap: Antigravity hook coverage and
`whyline doctor` (docs/superpowers/plans/2026-09-30-brainstorm-roadmap.md).

Payload shapes below are the ones captured from a real agy 1.2.x run on
2026-09-30, not the (thinner) documented contract."""

import io
import json

import pytest

from whyline import cli, events, handoff, hook_entry, hooks, ledger, ownership, paths


def _init(repo):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()


def run_in(repo, argv, capsys, monkeypatch):
    monkeypatch.chdir(repo.path)
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _common(repo):
    return {
        "conversationId": "conv-1",
        "workspacePaths": [str(repo.path)],
        "modelName": "gemini-3.8-flash-high",
        "transcriptPath": "/tmp/t.jsonl",
    }


def _events(repo):
    return ledger.read_all(paths.ledger_path(repo.path))[0]


# --- 6.1 install --------------------------------------------------------------------------


def test_install_writes_a_named_whyline_hook(repo):
    assert hooks.install_antigravity(repo.path) == "installed"
    config = json.loads((repo.path / ".agents" / "hooks.json").read_text(encoding="utf-8"))
    ours = config["whyline"]
    assert ours["PreInvocation"] == [
        {"type": "command", "command": "whyline-hook --agent antigravity --event PreInvocation"}
    ]
    assert ours["PostToolUse"] == [{"matcher": "*", "hooks": [
        {"type": "command", "command": "whyline-hook --agent antigravity --event PostToolUse"}
    ]}]
    assert ours["Stop"][0]["command"].endswith("--event Stop")
    assert "PreToolUse" not in ours  # would have to decide permissions
    assert hooks.install_antigravity(repo.path) == "already-present"


def test_install_keeps_other_named_hooks(repo):
    target = repo.path / ".agents" / "hooks.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"lint": {"PostToolUse": []}}), encoding="utf-8")
    hooks.install_antigravity(repo.path)
    config = json.loads(target.read_text(encoding="utf-8"))
    assert config["lint"] == {"PostToolUse": []}
    assert "whyline" in config


def test_install_refuses_an_unreadable_file(repo):
    target = repo.path / ".agents" / "hooks.json"
    target.parent.mkdir()
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(hooks.SettingsUnreadable):
        hooks.install_antigravity(repo.path)
    assert target.read_text(encoding="utf-8") == "{not json"


# --- 6.2 hook entry -----------------------------------------------------------------------


def _fire(repo, event, payload, capsys=None):
    return hook_entry.main(json.dumps(payload), repo.path, agent="antigravity", event=event)


def test_first_invocation_starts_a_session_later_ones_do_not(repo):
    _init(repo)
    _fire(repo, "PreInvocation", {**_common(repo), "invocationNum": 0, "initialNumSteps": 1})
    _fire(repo, "PreInvocation", {**_common(repo), "invocationNum": 1, "initialNumSteps": 3})
    [started] = _events(repo)
    assert started["type"] == events.SESSION_STARTED
    assert (started["session"], started["agent"]) == ("conv-1", "antigravity")


def test_a_write_tool_records_the_touched_file(repo):
    _init(repo)
    _fire(repo, "PostToolUse", {**_common(repo), "stepIdx": 4, "error": "", "toolCall": {
        "name": "write_to_file",
        "args": {"TargetFile": str(repo.path / "src" / "a.py"), "CodeContent": "x"},
    }})
    [touched] = _events(repo)
    assert touched["type"] == events.FILE_TOUCHED
    assert (touched["path"], touched["tool"], touched["agent"]) == ("src/a.py", "write_to_file", "antigravity")


def test_reads_failures_and_outside_paths_are_not_recorded(repo):
    _init(repo)
    common = _common(repo)
    _fire(repo, "PostToolUse", {**common, "stepIdx": 1, "error": "", "toolCall": {
        "name": "view_file", "args": {"AbsolutePath": str(repo.path / "a.py")}}})
    _fire(repo, "PostToolUse", {**common, "stepIdx": 2, "error": "exit status 1", "toolCall": {
        "name": "write_to_file", "args": {"TargetFile": str(repo.path / "a.py")}}})
    _fire(repo, "PostToolUse", {**common, "stepIdx": 3, "error": "", "toolCall": {
        "name": "write_to_file", "args": {"TargetFile": "/etc/elsewhere.conf"}}})
    _fire(repo, "PostToolUse", {**common, "stepIdx": 4, "error": "", "toolCall": {
        "name": "run_command", "args": {"CommandLine": "whyline sync"}}})
    assert _events(repo) == []


def test_stop_ends_the_session_with_its_reason(repo):
    _init(repo)
    _fire(repo, "Stop", {**_common(repo), "executionNum": 0, "fullyIdle": True,
                         "terminationReason": "NO_TOOL_CALL", "error": ""})
    [ended] = _events(repo)
    assert ended["type"] == events.SESSION_ENDED
    assert (ended["session"], ended["status"]) == ("conv-1", "NO_TOOL_CALL")


def test_the_entry_point_always_answers_with_an_empty_object(repo, monkeypatch, capsys):
    _init(repo)
    monkeypatch.chdir(repo.path)
    for stdin in ("{not json", json.dumps({**_common(repo), "invocationNum": 0})):
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        monkeypatch.setattr("sys.argv", ["whyline-hook", "--agent", "antigravity", "--event", "PreInvocation"])
        with pytest.raises(SystemExit) as exit_info:
            hook_entry.entry()
        assert exit_info.value.code == 0
        assert capsys.readouterr().out.strip() == "{}"


# --- 6.3 init ------------------------------------------------------------------------------


def test_init_installs_the_antigravity_hook_when_agy_is_present(repo, capsys, monkeypatch):
    monkeypatch.setattr(hooks, "antigravity_in_use", lambda root: True)
    code, out, _ = run_in(repo, ["init", "--yes", "--no-relay"], capsys, monkeypatch)
    assert code == cli.EXIT_OK
    assert "Antigravity hook: installed" in out
    assert "trust this folder in Antigravity" in out
    assert (repo.path / ".agents" / "hooks.json").exists()


def test_init_leaves_antigravity_alone_when_it_is_not_used(repo, capsys, monkeypatch):
    monkeypatch.setattr(hooks, "antigravity_in_use", lambda root: False)
    run_in(repo, ["init", "--yes", "--no-relay"], capsys, monkeypatch)
    assert not (repo.path / ".agents").exists()


# --- 6.4 status ----------------------------------------------------------------------------


def test_status_reports_the_antigravity_hook(repo, capsys, monkeypatch):
    from whyline import render

    _init(repo)
    hooks.install_antigravity(repo.path)
    report = render.status_payload(repo.path)["hooks"]["antigravity"]
    assert report["configured"] and not report["observed"]
    assert "trust" in report["detail"].lower()
    _fire(repo, "PreInvocation", {**_common(repo), "invocationNum": 0})
    assert render.status_payload(repo.path)["hooks"]["antigravity"]["observed"]


# --- 6.5 doctor ----------------------------------------------------------------------------


def _doctor(repo, capsys, monkeypatch, *extra):
    return run_in(repo, ["doctor", "--json", *extra], capsys, monkeypatch)


def _check(payload, name):
    [found] = [c for c in payload["checks"] if c["name"] == name]
    return found


def test_doctor_on_a_healthy_repo(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    monkeypatch.setattr(hooks, "antigravity_in_use", lambda root: False)
    run_in(repo, ["init", "--yes", "--no-relay"], capsys, monkeypatch)
    code, out, _ = _doctor(repo, capsys, monkeypatch)
    payload = json.loads(out)
    assert code == cli.EXIT_OK
    assert _check(payload, "initialised")["status"] == "ok"
    assert _check(payload, "instructions")["status"] == "ok"
    assert _check(payload, "decisions.md")["status"] == "ok"
    assert _check(payload, "stale claims")["status"] == "ok"


def test_doctor_flags_stale_state_with_fixes(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    paths.ownership_path(repo.path).write_text(json.dumps({"v": 1, "claims": [
        {"task": "OLD", "actor": "a", "claimed_at": "2020-01-01T00:00:00.000Z"}]}))
    handoff.create(repo.path, task="T", from_actor="a", to_actor="b", status="approved")
    repo.commit({"b.py": "1\n"}, "d", epoch=1_000_100)

    code, out, _ = _doctor(repo, capsys, monkeypatch)

    payload = json.loads(out)
    stale = _check(payload, "stale claims")
    assert stale["status"] == "warn" and stale["fix"] == "whyline release --stale"
    unclosed = _check(payload, "handoff")
    assert unclosed["status"] == "warn" and "whyline handoff close" in unclosed["fix"]
    assert code == cli.EXIT_OK  # warnings don't fail


def test_doctor_fails_on_conflict_markers_and_exits_one(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    paths.decisions_path(repo.path).write_text("# Decisions\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> b\n")
    code, out, _ = _doctor(repo, capsys, monkeypatch)
    assert code == cli.EXIT_ERROR
    assert _check(json.loads(out), "decisions.md")["status"] == "fail"


def test_doctor_uninitialised_is_a_failure_with_the_fix(repo, capsys, monkeypatch):
    code, out, _ = _doctor(repo, capsys, monkeypatch)
    payload = json.loads(out)
    assert code == cli.EXIT_ERROR
    assert _check(payload, "initialised") == {
        "name": "initialised", "status": "fail",
        "detail": "whyline is not set up in this repository", "fix": "whyline init",
    }


def test_doctor_checks_antigravity_trust_without_changing_it(repo, capsys, monkeypatch, tmp_path_factory):
    from whyline import doctor

    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    hooks.install_antigravity(repo.path)
    settings = tmp_path_factory.mktemp("gemini") / "settings.json"
    settings.write_text(json.dumps({"trustedWorkspaces": ["/somewhere/else"]}))
    monkeypatch.setattr(doctor, "ANTIGRAVITY_SETTINGS", settings)
    before = settings.read_text()

    _, out, _ = _doctor(repo, capsys, monkeypatch)

    trust = _check(json.loads(out), "antigravity trust")
    assert trust["status"] == "warn" and "trust" in trust["fix"].lower()
    assert settings.read_text() == before
    settings.write_text(json.dumps({"trustedWorkspaces": [str(repo.path.resolve())]}))
    _, out, _ = _doctor(repo, capsys, monkeypatch)
    assert _check(json.loads(out), "antigravity trust")["status"] == "ok"


def test_doctor_text_output(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    paths.ownership_path(repo.path).write_text(json.dumps({"v": 1, "claims": [
        {"task": "OLD", "actor": "a", "claimed_at": "2020-01-01T00:00:00.000Z"}]}))
    _, out, _ = run_in(repo, ["doctor"], capsys, monkeypatch)
    assert "warn  stale claims" in out
    assert "      fix: whyline release --stale" in out


def test_doctor_warns_about_prompt_text_left_from_before_the_policy(repo, capsys, monkeypatch):
    from whyline import ledgerops

    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    ledgerops.set_policy(repo.path, "full")
    hook_entry.main(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s",
                                "prompt": "old prompt"}), repo.path)
    ledgerops.set_policy(repo.path, "metadata")
    _, out, _ = _doctor(repo, capsys, monkeypatch)
    check = _check(json.loads(out), "prompt capture")
    assert check["status"] == "warn" and check["fix"] == "whyline ledger scrub-prompts"
