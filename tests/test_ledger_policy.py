"""Item 4 of the brainstorm roadmap: prompt retention policy, pruning,
and a lighter ledger read path
(docs/superpowers/plans/2026-09-30-brainstorm-roadmap.md)."""

import hashlib
import json

from whyline import cli, events, history, hook_entry, ledger, ledgerops, paths, sync


def _init(repo):
    paths.ledger_path(repo.path).parent.mkdir(parents=True, exist_ok=True)
    paths.ledger_path(repo.path).touch()


def run_in(repo, argv, capsys, monkeypatch):
    monkeypatch.chdir(repo.path)
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _prompt(repo, text):
    hook_entry.main(
        json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": text}),
        repo.path,
    )
    return ledger.read_all(paths.ledger_path(repo.path))[0][-1]


SECRET_PROMPT = (
    "deploy with key sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789 "
    "and token ghp_abcdefghijklmnopqrstuvwxyz0123456789 password=hunter2 "
    "then email me at someone@example.com"
)


# --- 4.1 capture policy -------------------------------------------------------------------


def test_default_policy_keeps_no_prompt_text(repo):
    _init(repo)
    event = _prompt(repo, "refactor the parser")
    assert "text" not in event
    assert event["chars"] == len("refactor the parser")
    assert event["sha256"] == hashlib.sha256(b"refactor the parser").hexdigest()
    assert event["capture"] == "metadata"


def test_full_policy_keeps_the_text(repo):
    _init(repo)
    ledgerops.set_policy(repo.path, "full")
    event = _prompt(repo, "refactor the parser")
    assert event["text"] == "refactor the parser"
    assert event["capture"] == "full"


def test_redacted_policy_masks_secret_shaped_text(repo):
    _init(repo)
    ledgerops.set_policy(repo.path, "redacted")
    event = _prompt(repo, SECRET_PROMPT)
    text = event["text"]
    for secret in ("sk-ant-api03", "ghp_abc", "hunter2", "someone@example.com"):
        assert secret not in text
    assert "deploy with key" in text and "then email me" in text
    assert event["capture"] == "redacted"


def test_policy_file_is_local_and_gitignored(repo):
    _init(repo)
    ledgerops.set_policy(repo.path, "full")
    config = json.loads((repo.path / ".whyline" / "config.json").read_text(encoding="utf-8"))
    assert config["prompt_capture"] == "full"
    assert "config.json" in (repo.path / ".whyline" / ".gitignore").read_text(encoding="utf-8")


def test_an_unknown_policy_value_falls_back_to_metadata(repo):
    _init(repo)
    (repo.path / ".whyline" / "config.json").write_text('{"prompt_capture": "everything"}')
    assert ledgerops.policy(repo.path) == "metadata"


def test_policy_command_shows_and_sets(repo, capsys, monkeypatch):
    _init(repo)
    code, out, _ = run_in(repo, ["ledger", "policy"], capsys, monkeypatch)
    assert code == cli.EXIT_OK and "metadata" in out
    code, out, _ = run_in(repo, ["ledger", "policy", "redacted"], capsys, monkeypatch)
    assert code == cli.EXIT_OK and ledgerops.policy(repo.path) == "redacted"


# --- 4.2 prune ------------------------------------------------------------------------------


def _event(type_, ts, **fields):
    event = events.new_event(type_, **fields)
    event["ts"] = ts
    return event


def _seed_old_and_new(repo):
    _init(repo)
    target = paths.ledger_path(repo.path)
    old, new = "2026-01-01T00:00:00.000Z", "2099-01-01T00:00:00.000Z"
    for ts in (old, new):
        for type_ in (events.INSTRUCTION, events.FILE_TOUCHED, events.SESSION_STARTED,
                      events.SESSION_ENDED, events.NOTE, events.HANDOFF,
                      events.HANDOFF_CLOSED, events.NOTE_ATTACHED, events.RETRACTION):
            ledger.append(target, _event(type_, ts, text="t" * 50))
    return target


def test_prune_drops_only_old_mechanical_events(repo, capsys, monkeypatch):
    target = _seed_old_and_new(repo)
    code, out, _ = run_in(repo, ["ledger", "prune", "--older-than", "30"], capsys, monkeypatch)
    assert code == cli.EXIT_OK and "Removed 4 events" in out
    kept, _ = ledger.read_all(target)
    old_types = sorted(e["type"] for e in kept if e["ts"].startswith("2026"))
    assert old_types == sorted([events.NOTE, events.HANDOFF, events.HANDOFF_CLOSED,
                                events.NOTE_ATTACHED, events.RETRACTION])
    assert sum(1 for e in kept if e["ts"].startswith("2099")) == 9


def test_prune_dry_run_changes_nothing(repo, capsys, monkeypatch):
    target = _seed_old_and_new(repo)
    before = target.read_text(encoding="utf-8")
    code, out, _ = run_in(repo, ["ledger", "prune", "--older-than", "30", "--dry-run"], capsys, monkeypatch)
    assert code == cli.EXIT_OK and "Would remove 4 events" in out
    assert target.read_text(encoding="utf-8") == before


def test_a_hook_firing_mid_rewrite_waits_and_is_kept(repo, monkeypatch):
    import threading

    target = _seed_old_and_new(repo)
    late = _event(events.NOTE, "2099-02-02T00:00:00.000Z", decision="written mid-rewrite")
    real_replace = ledgerops._replace
    hook = threading.Thread(target=ledger.append, args=(target, late))

    def replace_while_a_hook_fires(tmp, dest):
        hook.start()  # a hook in another process, just before the swap
        hook.join(timeout=0.3)
        assert hook.is_alive()  # it is waiting for the rewrite's lock
        real_replace(tmp, dest)

    monkeypatch.setattr(ledgerops, "_replace", replace_while_a_hook_fires)
    ledgerops.prune(repo.path, older_than_days=30)
    hook.join(timeout=5)
    kept, skipped = ledger.read_all(target)
    assert skipped == 0
    assert any(e.get("decision") == "written mid-rewrite" for e in kept)


def test_an_unlocked_writer_mid_rewrite_is_still_kept(repo, monkeypatch):
    target = _seed_old_and_new(repo)
    real_snapshot_end = ledgerops._tail_hook
    late = ledger._serialise(
        _event(events.NOTE, "2099-02-02T00:00:00.000Z", decision="from an older hook")
    )

    def older_hook_writes():
        with target.open("a", encoding="utf-8") as handle:  # no lock
            handle.write(late + "\n")
        real_snapshot_end()

    monkeypatch.setattr(ledgerops, "_tail_hook", older_hook_writes)
    ledgerops.prune(repo.path, older_than_days=30)
    kept, _ = ledger.read_all(target)
    assert any(e.get("decision") == "from an older hook" for e in kept)


# --- 4.3 scrub ------------------------------------------------------------------------------


def test_scrub_applies_the_current_policy_to_recorded_prompts(repo, capsys, monkeypatch):
    _init(repo)
    ledgerops.set_policy(repo.path, "full")
    _prompt(repo, "first prompt")
    _prompt(repo, SECRET_PROMPT)
    ledgerops.set_policy(repo.path, "metadata")

    code, out, _ = run_in(repo, ["ledger", "scrub-prompts"], capsys, monkeypatch)

    assert code == cli.EXIT_OK and "Scrubbed 2 prompts" in out
    found, _ = ledger.read_all(paths.ledger_path(repo.path))
    assert all("text" not in e for e in found)
    assert found[0]["sha256"] == hashlib.sha256(b"first prompt").hexdigest()
    code, out, _ = run_in(repo, ["ledger", "scrub-prompts"], capsys, monkeypatch)
    assert "Scrubbed 0 prompts" in out


def test_scrub_refuses_under_the_full_policy(repo, capsys, monkeypatch):
    _init(repo)
    ledgerops.set_policy(repo.path, "full")
    code, _, err = run_in(repo, ["ledger", "scrub-prompts"], capsys, monkeypatch)
    assert code == cli.EXIT_ERROR and "policy is full" in err


# --- 4.4 stats ------------------------------------------------------------------------------


def test_stats_reports_size_types_and_policy(repo, capsys, monkeypatch):
    _seed_old_and_new(repo)
    code, out, _ = run_in(repo, ["ledger", "stats"], capsys, monkeypatch)
    assert code == cli.EXIT_OK
    assert "Policy" in out and "metadata" in out
    assert "Instruction" in out and "2 events" in out
    code, out, _ = run_in(repo, ["ledger", "stats", "--json"], capsys, monkeypatch)
    payload = json.loads(out)
    assert payload["events"] == 18 and payload["types"]["Note"] == 2


# --- 4.5 lighter read path ------------------------------------------------------------------


def test_skip_types_reads_the_same_kept_events(repo):
    target = _seed_old_and_new(repo)
    # a decision that merely *mentions* the skipped type must survive
    ledger.append(target, _event(events.NOTE, "2099-03-03T00:00:00.000Z",
                                 decision='the "type":"Instruction" field'))
    full, _ = ledger.read_all(target)
    light, _ = ledger.read_all(target, skip_types=ledgerops.MECHANICAL_TYPES)
    assert light == [e for e in full if e["type"] not in ledgerops.MECHANICAL_TYPES]


def test_history_without_mechanical_events_has_the_same_decisions(repo, capsys, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    _prompt(repo, "hello")
    run_in(repo, ["note", "a decision"], capsys, monkeypatch)
    full = history.load(repo.path)
    light = history.load(repo.path, mechanical=False)
    assert [e.event for e in light.notes] == [e.event for e in full.notes]
    assert not any(e["type"] == events.INSTRUCTION for e in light.ledger_events)


def test_sync_does_not_decode_prompts(repo, monkeypatch):
    repo.commit({"a.py": "1\n"}, "c", epoch=1_000_000)
    _init(repo)
    calls = []
    real = ledger.read_all
    monkeypatch.setattr(ledger, "read_all", lambda path, **kw: calls.append(kw) or real(path, **kw))
    sync.compose(repo.path)
    assert calls and all(kw.get("skip_types") for kw in calls)


# --- 4.6 timeline ---------------------------------------------------------------------------


def test_timeline_says_when_a_prompt_was_not_captured(repo, capsys, monkeypatch):
    _init(repo)
    _prompt(repo, "secret plans")
    code, out, _ = run_in(repo, ["timeline", "--json", "--include-prompts"], capsys, monkeypatch)
    payload = json.loads(out)
    [instruction] = [e for e in payload["events"] if e["type"] == "Instruction"]
    assert instruction["text"] == "[not captured: prompt_capture=metadata]"
