import re
import pytest

from whyline import cli


def test_version_flag_succeeds(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == cli.EXIT_OK
    # Assert against the package's own version, not a literal. A hardcoded
    # string here broke the suite on the 0.1.1 bump, which is a test failing for
    # its own brittleness rather than for a defect in the code.
    from whyline import __version__

    assert __version__ in capsys.readouterr().out


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["nonsense"])
    assert exit_info.value.code == cli.EXIT_USAGE


def test_no_command_is_a_usage_error():
    assert cli.main([]) == cli.EXIT_USAGE


import json
import os

from whyline import cli, events, ledger, paths


def run_in(repo, argv, capsys):
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(argv)
    finally:
        os.chdir(previous)
    return code, capsys.readouterr().out


def test_explain_reports_no_record_when_the_ledger_is_empty(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["explain", "a.py:1"], capsys)
    assert code == cli.EXIT_OK
    assert "no reasoning recorded" in out.lower()


def test_explain_json_includes_confidence_and_path(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["explain", "a.py:1", "--json"], capsys)
    assert code == cli.EXIT_OK
    payload = json.loads(out)
    assert payload["confidence"] == "none"
    assert payload["path"] == "a.py"
    assert payload["line"] == 1


def test_explain_shows_the_decision_and_rejected_alternatives(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="Use Redis with a 30-second key",
        because="responses are user-specific",
        alternatives=[{"option": "in-memory LRU", "why_not": "lost on deploy"}],
        files=["a.py"],
    )
    event["ts"] = "1970-01-12T13:46:40.000Z"  # epoch 1_000_000
    ledger.append(paths.ledger_path(repo.path), event)
    code, out = run_in(repo, ["explain", "a.py:1"], capsys)
    assert code == cli.EXIT_OK
    assert "Use Redis with a 30-second key" in out
    assert "in-memory LRU" in out
    assert "lost on deploy" in out


def test_explain_without_initialisation_exits_three(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    code, out = run_in(repo, ["explain", "a.py:1"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_explain_accepts_a_path_without_a_line(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["explain", "a.py", "--json"], capsys)
    assert code == cli.EXIT_OK
    assert json.loads(out)["line"] is None


def test_explain_does_not_print_a_recorded_note_for_an_uncommitted_line(repo, capsys):
    """Pins the Task 5 carry-forward constraint: resolve.explain populates
    `notes` on the uncommitted-line branch even though confidence is "none".
    The renderer must gate what it prints on confidence, not on whether
    `notes` is non-empty — otherwise an uncommitted line would appear to
    have recorded reasoning under a "Confidence: None" heading.
    """
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="Use Redis with a 30-second key",
        because="responses are user-specific",
        files=["a.py"],
    )
    event["ts"] = "2001-09-09T01:46:40.000Z"  # epoch 1_000_000_000
    ledger.append(paths.ledger_path(repo.path), event)
    # Append an uncommitted second line — git blame reports sha == all zeros.
    (repo.path / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    code, out = run_in(repo, ["explain", "a.py:2"], capsys)
    assert code == cli.EXIT_OK
    assert "none" in out.lower()
    assert "Use Redis with a 30-second key" not in out


def test_explain_does_not_print_a_recorded_note_for_an_untracked_file(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="Use Redis with a 30-second key",
        files=["untracked.py"],
    )
    ledger.append(paths.ledger_path(repo.path), event)
    (repo.path / "untracked.py").write_text("one\n", encoding="utf-8")

    code, out = run_in(repo, ["explain", "untracked.py:1"], capsys)

    assert code == cli.EXIT_OK
    assert "none" in out.lower()
    assert "Use Redis with a 30-second key" not in out


def test_explain_json_hides_notes_that_are_not_attributed_to_the_line(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="Use Redis with a 30-second key",
        files=["a.py"],
    )
    ledger.append(paths.ledger_path(repo.path), event)
    (repo.path / "a.py").write_text("one\ntwo\n", encoding="utf-8")

    code, out = run_in(repo, ["explain", "a.py:2", "--json"], capsys)

    assert code == cli.EXIT_OK
    payload = json.loads(out)
    assert payload["confidence"] == "none"
    assert payload["notes"] == []


def test_explain_low_confidence_does_not_deny_existing_reasoning(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    event = events.new_event(
        events.NOTE,
        decision="A later decision",
        files=["a.py"],
    )
    event["ts"] = "1970-01-24T03:33:20.000Z"  # epoch 2_000_000
    ledger.append(paths.ledger_path(repo.path), event)

    code, out = run_in(repo, ["explain", "a.py:1"], capsys)

    assert code == cli.EXIT_OK
    assert "Low — recorded evidence cannot be tied to this line." in out
    assert "all of it postdates" in out
    assert "no reasoning was recorded" not in out


def test_explain_warns_once_when_ledger_lines_are_unreadable(
    repo, capsys, monkeypatch
):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    path = paths.ledger_path(repo.path)
    path.parent.mkdir(parents=True)
    path.write_text("{torn\n{also-torn\n", encoding="utf-8")
    monkeypatch.chdir(repo.path)

    code = cli.main(["explain", "a.py:1"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_OK
    assert captured.err.count("warning:") == 1
    assert "skipped 2 unreadable ledger lines" in captured.err


def test_note_writes_to_both_the_ledger_and_decisions_md(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, _ = run_in(
        repo,
        [
            "note",
            "Store absolute monotonic expiry",
            "--because",
            "clock is injected",
            "--rejected",
            "sleep in tests: slow and flaky",
            "--file",
            "cache.py",
        ],
        capsys,
    )
    assert code == cli.EXIT_OK
    found, skipped = ledger.read_all(paths.ledger_path(repo.path))
    assert skipped == 0
    assert found[-1]["type"] == events.NOTE
    assert found[-1]["alternatives"] == [
        {"option": "sleep in tests", "why_not": "slow and flaky"}
    ]
    assert found[-1]["files"] == ["cache.py"]
    assert "monotonic expiry" in paths.decisions_path(repo.path).read_text()


def test_note_requires_initialisation(repo, capsys):
    code, _ = run_in(repo, ["note", "something"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_init_scaffolds_ledger_and_gitignore(repo, capsys):
    code, _ = run_in(repo, ["init", "--yes"], capsys)
    assert code == cli.EXIT_OK
    assert paths.ledger_path(repo.path).exists()
    ignore = (repo.path / ".whyline" / ".gitignore").read_text()
    assert "ledger.jsonl" in ignore
    assert "!decisions.md" in ignore
    assert (repo.path / ".claude" / "settings.json").exists()
    codex_hooks = json.loads((repo.path / ".codex" / "hooks.json").read_text())
    assert "whyline-hook --agent codex" in str(codex_hooks)


def test_init_preserves_existing_whyline_gitignore_entries(repo, capsys):
    directory = repo.path / ".whyline"
    directory.mkdir()
    (directory / ".gitignore").write_text("keep-me.tmp\n")
    run_in(repo, ["init", "--yes"], capsys)
    ignore = (directory / ".gitignore").read_text()
    assert "keep-me.tmp" in ignore
    assert "ledger.jsonl" in ignore


def test_init_is_idempotent(repo, capsys):
    run_in(repo, ["init", "--yes"], capsys)
    agents_before = (repo.path / "AGENTS.md").read_text()
    claude_before = (repo.path / "CLAUDE.md").read_text()
    code, _ = run_in(repo, ["init", "--yes"], capsys)
    assert code == cli.EXIT_OK
    assert (repo.path / "AGENTS.md").read_text() == agents_before
    assert (repo.path / "CLAUDE.md").read_text() == claude_before


def test_init_writes_shared_agent_instructions_with_yes(repo, capsys):
    run_in(repo, ["init", "--yes"], capsys)
    assert "whyline note" in (repo.path / "AGENTS.md").read_text()
    claude = (repo.path / "CLAUDE.md").read_text()
    assert "@AGENTS.md" in claude
    assert "canonical source" in claude


def test_init_preserves_existing_instruction_files(repo, capsys):
    (repo.path / "AGENTS.md").write_text("Existing agents rules.\n")
    (repo.path / "CLAUDE.md").write_text("Existing Claude rules.\n")
    run_in(repo, ["init", "--yes"], capsys)
    assert (repo.path / "AGENTS.md").read_text().startswith("Existing agents rules.")
    assert (repo.path / "CLAUDE.md").read_text().startswith("Existing Claude rules.")


def test_init_without_confirmation_does_not_modify_instruction_files(
    repo, capsys, monkeypatch
):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    code, _ = run_in(repo, ["init"], capsys)
    assert code == cli.EXIT_OK
    assert not (repo.path / "AGENTS.md").exists()
    assert not (repo.path / "CLAUDE.md").exists()


def test_brief_command_prints_the_context_block(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["brief"], capsys)
    assert code == cli.EXIT_OK
    assert re.search(r"^<whyline-context-[0-9a-f]{16}>$", out, re.M), out[:120]


def test_brief_accepts_relevance_and_budget_flags(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    event = events.new_event(
        events.NOTE,
        decision="keep this",
        task="WL-42",
        files=["a.py"],
    )
    ledger.append(paths.ledger_path(repo.path), event)

    code, out = run_in(
        repo,
        ["brief", "--task", "WL-42", "--file", "a.py", "--token-budget", "300"],
        capsys,
    )

    assert code == cli.EXIT_OK
    assert "keep this" in out


def test_sync_command_json_contains_git_and_handoff(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()

    code, out = run_in(repo, ["sync", "--json"], capsys)

    payload = json.loads(out)
    assert code == cli.EXIT_OK
    assert "git" in payload
    assert "active_handoff" in payload


def test_claim_warns_but_succeeds_on_overlap(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    code, _ = run_in(
        repo,
        ["claim", "WL-42", "--actor", "codex", "--file", "a.py"],
        capsys,
    )
    assert code == cli.EXIT_OK

    code, out = run_in(
        repo,
        ["claim", "WL-43", "--actor", "claude", "--file", "a.py", "--json"],
        capsys,
    )
    payload = json.loads(out)
    assert code == cli.EXIT_OK
    assert len(payload["conflicts"]) == 1


def test_release_is_idempotent_through_cli(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()

    for _ in range(2):
        code, out = run_in(
            repo,
            ["release", "WL-42", "--actor", "codex", "--json"],
            capsys,
        )
        assert code == cli.EXIT_OK
        assert json.loads(out)["claims"] == []


def test_brief_without_initialisation_exits_three(repo, capsys):
    code, _ = run_in(repo, ["brief"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_run_still_prints_the_sync_packet_when_the_agent_is_missing(
    repo, capsys, monkeypatch
):
    from whyline import runner

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    code, out = run_in(repo, ["run", "codex", "do the thing"], capsys)
    assert code == cli.EXIT_ERROR
    assert re.search(r"^<whyline-sync-[0-9a-f]{16}>$", out, re.M), out[:120]


def test_run_requires_initialisation(repo, capsys):
    code, _ = run_in(repo, ["run", "codex", "task"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_run_reports_git_failure_without_a_traceback(repo, capsys, monkeypatch):
    from whyline import gitq, sync

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()

    def fail(*_args, **_kwargs):
        raise gitq.GitUnavailable("broken repository")

    monkeypatch.setattr(sync, "compose", fail)
    code, _out, err = run_in_both(
        repo, ["run", "codex", "do the thing"], capsys
    )

    assert code == cli.EXIT_ERROR
    assert "git is unavailable" in err
    assert "Traceback" not in err


def _ledger_note(repo, decision, ts, files=None):
    event = events.new_event(events.NOTE, decision=decision, files=files or [])
    event["ts"] = ts
    ledger.append(paths.ledger_path(repo.path), event)


def test_timeline_lists_events_newest_first(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "older", "2026-08-01T10:00:00.000Z", ["a.py"])
    _ledger_note(repo, "newer", "2026-08-05T10:00:00.000Z", ["a.py"])
    code, out = run_in(repo, ["timeline"], capsys)
    assert code == cli.EXIT_OK
    assert out.index("newer") < out.index("older")


def test_timeline_filters_by_file(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "keep", "2026-08-01T10:00:00.000Z", ["a.py"])
    _ledger_note(repo, "drop", "2026-08-01T10:00:00.000Z", ["b.py"])
    code, out = run_in(repo, ["timeline", "--file", "a.py"], capsys)
    assert code == cli.EXIT_OK
    assert "keep" in out
    assert "drop" not in out


def test_timeline_filters_by_since(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "old", "2026-08-01T10:00:00.000Z")
    _ledger_note(repo, "recent", "2026-08-09T10:00:00.000Z")
    code, out = run_in(repo, ["timeline", "--since", "2026-08-05"], capsys)
    assert code == cli.EXIT_OK
    assert "recent" in out
    assert "old" not in out


def test_timeline_on_an_empty_ledger_says_so(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["timeline"], capsys)
    assert code == cli.EXIT_OK
    assert "No events recorded" in out


def test_timeline_requires_initialisation(repo, capsys):
    code, _ = run_in(repo, ["timeline"], capsys)
    assert code == cli.EXIT_UNINITIALISED


def test_status_json_reports_counts_and_hook_state(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "a", "2026-08-01T10:00:00.000Z")
    code, out = run_in(repo, ["status", "--json"], capsys)
    assert code == cli.EXIT_OK
    payload = json.loads(out)
    assert payload["events"] == 1
    assert payload["notes"] == 1
    assert payload["hook_installed"] is False
    assert payload["initialised"] is True


def test_status_counts_committed_history_on_a_fresh_clone(repo, capsys):
    event = events.new_event(
        events.NOTE,
        decision="durable decision",
        because="available after cloning",
        files=["a.py"],
    )
    event["ts"] = "2026-08-01T10:00:00.000Z"
    from whyline import decisions

    decisions.append_entry(paths.decisions_path(repo.path), event)

    code, out = run_in(repo, ["status", "--json"], capsys)

    payload = json.loads(out)
    assert code == cli.EXIT_OK
    assert payload["notes"] == 1
    assert payload["committed_decisions"] == 1
    assert payload["local_events"] == 0


def test_status_reports_each_agent_config_binary_and_observation(repo, capsys):
    from whyline import hooks, render

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    hooks.install_claude(repo.path / ".claude" / "settings.json")
    hooks.install_codex(repo.path / ".codex" / "hooks.json")
    event = events.new_event(
        events.SESSION_STARTED, session="codex-1", agent="codex"
    )
    ledger.append(paths.ledger_path(repo.path), event)
    monkeypatch_target = lambda _name: "/usr/local/bin/whyline-hook"
    original = render.shutil.which
    render.shutil.which = monkeypatch_target
    try:
        code, out = run_in(repo, ["status", "--json"], capsys)
    finally:
        render.shutil.which = original

    payload = json.loads(out)
    assert code == cli.EXIT_OK
    assert payload["hooks"]["claude"]["configured"] is True
    assert payload["hooks"]["claude"]["observed"] is False
    assert payload["hooks"]["codex"]["configured"] is True
    assert payload["hooks"]["codex"]["binary_available"] is True
    assert payload["hooks"]["codex"]["observed"] is True
    assert payload["hooks"]["codex"]["last_event"] == event["ts"]


def test_status_configured_but_unobserved_codex_points_to_hook_trust(
    repo, capsys, monkeypatch
):
    from whyline import hooks, render

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    hooks.install_codex(repo.path / ".codex" / "hooks.json")
    monkeypatch.setattr(render.shutil, "which", lambda _name: "/bin/whyline-hook")

    _code, out = run_in(repo, ["status", "--json"], capsys)

    codex = json.loads(out)["hooks"]["codex"]
    assert codex["configured"] is True
    assert codex["observed"] is False
    assert codex["healthy"] is False
    assert "/hooks" in codex["detail"]


def test_status_does_not_call_configured_hook_healthy_when_binary_is_missing(
    repo, capsys, monkeypatch
):
    from whyline import hooks, render

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    hooks.install_claude(repo.path / ".claude" / "settings.json")
    monkeypatch.setattr(render.shutil, "which", lambda _name: None)

    _code, out = run_in(repo, ["status", "--json"], capsys)

    claude = json.loads(out)["hooks"]["claude"]
    assert claude["configured"] is True
    assert claude["binary_available"] is False
    assert claude["healthy"] is False
    assert "not found" in claude["detail"]


def test_status_reports_skipped_torn_lines(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "a", "2026-08-01T10:00:00.000Z")
    with paths.ledger_path(repo.path).open("a", encoding="utf-8") as handle:
        handle.write('{"torn')
    code, out = run_in(repo, ["status", "--json"], capsys)
    assert code == cli.EXIT_OK
    assert json.loads(out)["skipped_lines"] == 1


def test_status_works_before_initialisation(repo, capsys):
    """status must not exit 3 — reporting "not initialised" is its whole job."""
    code, out = run_in(repo, ["status", "--json"], capsys)
    assert code == cli.EXIT_OK
    assert json.loads(out)["initialised"] is False


def test_timeline_rejects_an_unparseable_since(repo, capsys):
    """C4, 2026-08-17: --since was a raw string compare, so an unpadded or
    non-date value silently matched nothing and reported an empty ledger."""
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "a decision", "2026-08-01T10:00:00.000Z")
    for bad in ("2026-8-1", "yesterday", "01-08-2026", ""):
        code, _ = run_in(repo, ["timeline", "--since", bad], capsys)
        assert code == cli.EXIT_USAGE, f"{bad!r} should be a usage error"


def test_timeline_accepts_a_valid_since(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "recent", "2026-08-09T10:00:00.000Z")
    code, out = run_in(repo, ["timeline", "--since", "2026-08-05"], capsys)
    assert code == cli.EXIT_OK
    assert "recent" in out


def test_timeline_does_not_claim_an_empty_ledger_when_a_filter_matches_nothing(
    repo, capsys
):
    """C4's second half: a filter matching nothing must not say 'No events
    recorded.' when the ledger holds events."""
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    _ledger_note(repo, "exists", "2026-08-01T10:00:00.000Z", ["a.py"])
    code, out = run_in(repo, ["timeline", "--file", "nosuch.py"], capsys)
    assert code == cli.EXIT_OK
    assert "No events recorded" not in out
    assert "No events matched" in out
    assert "holds 1 event" in out


def test_timeline_still_reports_a_genuinely_empty_ledger(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["timeline"], capsys)
    assert code == cli.EXIT_OK
    assert "No events recorded" in out


def test_status_reports_a_deny_rule_as_not_recording(repo, capsys):
    """C3, 2026-08-17: a substring search reported 'installed' while the hook was
    blocked by a permissions deny rule."""
    import json

    settings = repo.path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"permissions": {"deny": ["Bash(whyline-hook)"]}, "hooks": {}})
    )
    code, out = run_in(repo, ["status", "--json"], capsys)
    assert code == cli.EXIT_OK
    assert json.loads(out)["hook_installed"] is False
    assert "deny" in json.loads(out)["hook_detail"]


def test_status_reports_partial_hook_wiring_as_not_recording(repo, capsys):
    import json

    from whyline import hooks

    settings = repo.path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": hooks.HOOK_COMMAND}]}
                    ]
                }
            }
        )
    )
    code, out = run_in(repo, ["status", "--json"], capsys)
    payload = json.loads(out)
    assert payload["hook_installed"] is False
    assert "missing" in payload["hook_detail"]


def test_timeline_json_redacts_prompt_text_by_default(repo, capsys):
    """Minor finding 2026-08-17: Instruction events carry raw prompt text, which
    is why ledger.jsonl is gitignored. --json must not spill it by default."""
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    event = events.new_event(
        events.INSTRUCTION, session="s1", text="my private prompt about salaries"
    )
    event["ts"] = "2026-08-01T10:00:00.000Z"
    ledger.append(paths.ledger_path(repo.path), event)

    code, out = run_in(repo, ["timeline", "--json"], capsys)
    assert code == cli.EXIT_OK
    assert "my private prompt about salaries" not in out
    assert "[redacted" in out

    code, out = run_in(repo, ["timeline", "--json", "--include-prompts"], capsys)
    assert code == cli.EXIT_OK
    assert "my private prompt about salaries" in out


def test_note_echoes_what_was_stored_not_what_was_typed(repo, capsys):
    """Minor 2026-08-18: the echo printed the raw multi-line argument while the
    record held the normalised one, misreporting what had been stored."""
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    code, out = run_in(repo, ["note", "line one\nline two"], capsys)
    assert code == cli.EXIT_OK
    assert "Recorded: line one line two" in out
    assert "\nline two" not in out.split("Recorded:")[1]


def test_note_records_actor_role_and_task(repo, capsys):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()

    code, _ = run_in(
        repo,
        [
            "note",
            "bounded the cache",
            "--actor",
            "codex",
            "--role",
            "implementer",
            "--task",
            "WL-42",
        ],
        capsys,
    )

    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert code == cli.EXIT_OK
    assert found[-1]["actor"] == "codex"
    assert found[-1]["role"] == "implementer"
    assert found[-1]["task"] == "WL-42"


def test_handoff_command_writes_active_record_and_json(repo, capsys):
    repo.commit({"a.py": "one\n"}, "first", epoch=1_000_000)
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()

    code, out = run_in(
        repo,
        [
            "handoff",
            "WL-42",
            "--from",
            "codex",
            "--to",
            "claude",
            "--status",
            "ready-for-review",
            "--summary",
            "implementation complete",
            "--test",
            "pytest -q: passed",
            "--json",
        ],
        capsys,
    )

    payload = json.loads(out)
    assert code == cli.EXIT_OK
    assert payload["task"] == "WL-42"
    assert payload["from_actor"] == "codex"
    assert payload["to_actor"] == "claude"
    assert payload["tests"] == [{"command": "pytest -q", "result": "passed"}]
    assert paths.active_handoff_path(repo.path).exists()


def test_status_reports_a_denied_but_fully_wired_hook_as_blocked(repo, capsys):
    """The earlier deny test used an empty hooks block, so it never exercised the
    case that matters: wired AND denied."""
    import json

    from whyline import hooks

    settings = repo.path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    event: [
                        {"hooks": [{"type": "command", "command": hooks.HOOK_COMMAND}]}
                    ]
                    for event in hooks.EVENTS
                },
                "permissions": {"deny": [f"Bash({hooks.HOOK_COMMAND})"]},
            }
        )
    )
    code, out = run_in(repo, ["status", "--json"], capsys)
    payload = json.loads(out)
    assert payload["hook_installed"] is False
    assert "blocked" in payload["hook_detail"]


def test_status_survives_settings_json_of_any_shape(repo, capsys):
    """Critical 2026-08-18: valid JSON of the wrong shape crashed status with an
    AttributeError traceback. A user-editable file must be parsed defensively."""
    import json

    settings = repo.path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    for shape in (
        {"hooks": [{"SessionStart": []}]},
        {"hooks": "yes"},
        {"permissions": ["deny"]},
        {"hooks": None, "permissions": None},
        {"hooks": {"SessionStart": "x"}},
        {"hooks": {"SessionStart": [{"hooks": "x"}]}},
        {"hooks": {"SessionStart": [{"hooks": [{"command": None}]}]}},
        [],
        "a string",
    ):
        settings.write_text(json.dumps(shape))
        code, out = run_in(repo, ["status", "--json"], capsys)
        assert code == cli.EXIT_OK, f"crashed on {shape!r}"
        assert json.loads(out)["hook_installed"] is False


def test_status_treats_glob_and_blanket_deny_rules_as_blocking(repo, capsys):
    """2026-08-18. A "precise" deny matcher regressed cases the crude substring
    check had caught: Bash(whyline-hook*) is Claude Code's idiomatic prefix-glob
    form, and Bash(**) and a bare Bash deny everything — all three reported a
    fully wired hook as installed while recording was dead. For a status command
    the safe direction is to withhold the claim."""
    import json

    from whyline import hooks

    wired = {
        event: [{"hooks": [{"type": "command", "command": hooks.HOOK_COMMAND}]}]
        for event in hooks.EVENTS
    }
    settings = repo.path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    for rule in (
        "Bash(whyline-hook)",
        "Bash(whyline-hook*)",
        "Bash(whyline-hook:*)",
        "Bash(*hook*)",
        "Bash(**)",
        "Bash(*)",
        "Bash",
        "bash(whyline-hook)",
        "BASH(whyline-hook)",
        'Bash("whyline-hook")',
        "Bash(env whyline-hook)",
        "Bash(/usr/local/bin/whyline-hook)",
    ):
        settings.write_text(
            json.dumps({"hooks": wired, "permissions": {"deny": [rule]}})
        )
        code, out = run_in(repo, ["status", "--json"], capsys)
        assert code == cli.EXIT_OK
        assert json.loads(out)["hook_installed"] is False, f"{rule} must block"


def test_status_does_not_treat_an_unrelated_deny_rule_as_blocking(repo, capsys):
    """The other direction: a rule naming a different concrete command must not
    report a working hook as dead."""
    import json

    from whyline import hooks

    wired = {
        event: [{"hooks": [{"type": "command", "command": hooks.HOOK_COMMAND}]}]
        for event in hooks.EVENTS
    }
    settings = repo.path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    for rule in (
        "Bash(whyline-hook-notes)",
        "Read(whyline-hook-notes)",
        "Bash(npm run build)",
    ):
        settings.write_text(
            json.dumps({"hooks": wired, "permissions": {"deny": [rule]}})
        )
        code, out = run_in(repo, ["status", "--json"], capsys)
        assert json.loads(out)["hook_installed"] is True, f"{rule} must not block"


def test_status_handles_a_deny_rule_written_as_a_bare_string(repo, capsys):
    import json

    from whyline import hooks

    wired = {
        event: [{"hooks": [{"type": "command", "command": hooks.HOOK_COMMAND}]}]
        for event in hooks.EVENTS
    }
    settings = repo.path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"hooks": wired, "permissions": {"deny": "Bash(whyline-hook)"}})
    )
    code, out = run_in(repo, ["status", "--json"], capsys)
    assert json.loads(out)["hook_installed"] is False


def run_in_both(repo, argv, capsys):
    """Like run_in, but returns stderr too. run_in drains capsys, so a second
    readouterr() in the same test sees an empty buffer."""
    previous = os.getcwd()
    os.chdir(repo.path)
    try:
        code = cli.main(argv)
    finally:
        os.chdir(previous)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_note_reports_cleanly_when_decisions_md_cannot_be_written(repo, capsys):
    """2026-08-18: note raised a raw traceback when storage was unwritable, and
    because the ledger was written first, a failure on decisions.md left the note
    in the local ledger only — brief and status showed it while a clone never
    would. The stores diverged silently."""
    import os

    from whyline import ledger

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()
    directory = paths.whyline_dir(repo.path)
    os.chmod(directory, 0o500)
    try:
        code, out, err = run_in_both(repo, ["note", "cannot store this"], capsys)
    finally:
        os.chmod(directory, 0o755)

    assert code == cli.EXIT_ERROR
    assert "Traceback" not in err
    assert "Nothing was recorded" in out + err
    # And crucially: the ledger must not hold what the committed record lacks.
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert [e for e in found if e.get("type") == events.NOTE] == []


def test_note_still_records_when_only_the_local_ledger_fails(repo, capsys):
    """The safe failure direction: decisions.md is the artefact that travels, so
    if only the local ledger fails the note is still durably recorded."""
    import os

    from whyline import ledger

    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).write_text("", encoding="utf-8")
    os.chmod(paths.ledger_path(repo.path), 0o000)
    try:
        code, out, err = run_in_both(repo, ["note", "durable anyway"], capsys)
    finally:
        os.chmod(paths.ledger_path(repo.path), 0o644)

    assert code == cli.EXIT_OK
    assert "Recorded:" in out
    assert "durable anyway" in paths.decisions_path(repo.path).read_text()
    assert "Traceback" not in err
    assert "could not write the local ledger" in err


def test_pressing_enter_at_the_init_prompts_installs_everything(repo, capsys, monkeypatch):
    """The most likely first run, and it used to produce a dead install.

    `[y/N]` meant Enter declined, so a user who typed `whyline init` and pressed
    Enter twice got `.whyline/` and nothing else: no instruction block, so no
    agent ever recorded or read anything, and no hooks, so nothing mechanical was
    captured either. It printed "Initialised" and exited 0, and `status` then told
    them to run the command they had just run. Running `init` is the consent; the
    sub-prompts exist to allow opting out, not to make declining the default.
    """
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    code, _ = run_in(repo, ["init"], capsys)
    assert code == cli.EXIT_OK
    assert "whyline note" in (repo.path / "AGENTS.md").read_text()
    assert (repo.path / ".claude" / "settings.json").exists()
    assert (repo.path / ".codex" / "hooks.json").exists()


def test_init_prompts_default_to_yes(repo, capsys, monkeypatch):
    """The prompt itself must show `[Y/n]`, or the default is a trap."""
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "")
    run_in(repo, ["init"], capsys)
    assert asked, "init should still ask"
    assert all("[Y/n]" in prompt for prompt in asked), asked


def test_non_interactive_init_sets_up_rather_than_silently_doing_nothing(
    repo, capsys, monkeypatch
):
    """`whyline init` from a Makefile, devcontainer or CI step.

    stdin is closed there, so `input` raises EOFError. That returned False, so
    the setup silently no-opped and still exited 0 — a broken install reporting
    success, in the one context where nobody is watching a prompt.
    """
    def closed_stdin(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed_stdin)
    code, _ = run_in(repo, ["init"], capsys)
    assert code == cli.EXIT_OK
    assert "whyline note" in (repo.path / "AGENTS.md").read_text()
    assert (repo.path / ".codex" / "hooks.json").exists()


def test_init_still_allows_declining(repo, capsys, monkeypatch):
    """Opting out must remain possible — just not by accident."""
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    code, _ = run_in(repo, ["init"], capsys)
    assert code == cli.EXIT_OK
    assert not (repo.path / "AGENTS.md").exists()
    assert not (repo.path / ".claude" / "settings.json").exists()


def test_init_flags_skip_prompts_without_installing(repo, capsys, monkeypatch):
    """Explicit opt-out for scripts that want state but not file changes."""
    def unexpected(prompt):
        raise AssertionError(f"should not have prompted: {prompt}")

    monkeypatch.setattr("builtins.input", unexpected)
    code, _ = run_in(repo, ["init", "--no-instructions", "--no-hooks"], capsys)
    assert code == cli.EXIT_OK
    assert not (repo.path / "AGENTS.md").exists()
    assert not (repo.path / ".claude" / "settings.json").exists()
    assert paths.ledger_path(repo.path).exists()
