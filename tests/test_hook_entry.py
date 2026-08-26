import json

from whyline import events, hook_entry, ledger, paths


def test_records_a_file_touched_event_from_a_post_tool_use_payload(repo):
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "abc123",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(repo.path / "cache.py")},
        }
    )
    assert hook_entry.main(payload, repo.path) == 0
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert found[-1]["type"] == events.FILE_TOUCHED
    assert found[-1]["path"] == "cache.py"
    assert found[-1]["session"] == "abc123"


def test_records_a_session_started_event(repo):
    payload = json.dumps({"hook_event_name": "SessionStart", "session_id": "s1"})
    assert hook_entry.main(payload, repo.path) == 0
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert found[-1]["type"] == events.SESSION_STARTED
    assert found[-1]["session"] == "s1"


def test_malformed_json_never_fails_the_session(repo):
    assert hook_entry.main("{not json", repo.path) == 0
    assert ledger.read_all(paths.ledger_path(repo.path)) == ([], 0)


def test_unknown_event_is_ignored_silently(repo):
    payload = json.dumps({"hook_event_name": "SomethingElse"})
    assert hook_entry.main(payload, repo.path) == 0
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert found == []


def test_a_path_outside_the_repository_is_ignored(repo):
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/etc/hosts"},
        }
    )
    assert hook_entry.main(payload, repo.path) == 0
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert found == []


def test_an_unwritable_ledger_never_fails_the_session(repo, monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ledger, "append", explode)
    payload = json.dumps({"hook_event_name": "SessionStart", "session_id": "s"})
    assert hook_entry.main(payload, repo.path) == 0


def test_codex_identity_is_recorded_on_every_event_type(repo):
    payloads = [
        {"hook_event_name": "SessionStart", "session_id": "s1"},
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "do the work",
        },
        {"hook_event_name": "SessionEnd", "session_id": "s1"},
    ]
    for payload in payloads:
        hook_entry.main(json.dumps(payload), repo.path, agent="codex")

    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert [event["agent"] for event in found] == ["codex", "codex", "codex"]


def test_codex_apply_patch_records_each_in_repo_path(repo):
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "codex-session",
        "tool_name": "apply_patch",
        "tool_input": {
            "command": """*** Begin Patch
*** Update File: src/a.py
*** Add File: src/b.py
*** Delete File: old.py
*** Move to: src/moved.py
*** Update File: ../outside.py
*** End Patch"""
        },
    }

    hook_entry.main(json.dumps(payload), repo.path, agent="codex")

    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert [event["path"] for event in found] == [
        "old.py",
        "src/a.py",
        "src/b.py",
        "src/moved.py",
    ]
    assert all(event["agent"] == "codex" for event in found)
    assert all(event["tool"] == "apply_patch" for event in found)


def test_codex_does_not_guess_writes_from_shell_commands(repo):
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "codex-session",
        "tool_name": "Bash",
        "tool_input": {"command": "touch src/a.py"},
    }

    hook_entry.main(json.dumps(payload), repo.path, agent="codex")

    assert ledger.read_all(paths.ledger_path(repo.path)) == ([], 0)
