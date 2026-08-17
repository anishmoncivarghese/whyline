from whyline import brief, events, ledger, paths


def add_note(repo, decision: str, ts: str, files=None):
    event = events.new_event(
        events.NOTE, decision=decision, because="", files=files or [], alternatives=[]
    )
    event["ts"] = ts
    ledger.append(paths.ledger_path(repo.path), event)


def test_compose_says_so_when_nothing_is_recorded(repo):
    text = brief.compose(repo.path)
    assert "No decisions recorded" in text


def test_compose_lists_newest_decisions_first(repo):
    add_note(repo, "older", "2026-08-01T10:00:00.000Z")
    add_note(repo, "newer", "2026-08-05T10:00:00.000Z")
    text = brief.compose(repo.path)
    assert text.index("newer") < text.index("older")


def test_compose_respects_the_limit(repo):
    for day in range(1, 6):
        add_note(repo, f"decision {day}", f"2026-08-0{day}T10:00:00.000Z")
    text = brief.compose(repo.path, limit=2)
    assert "decision 5" in text
    assert "decision 1" not in text


def test_compose_labels_content_as_untrusted(repo):
    add_note(repo, "something", "2026-08-01T10:00:00.000Z")
    text = brief.compose(repo.path)
    assert "untrusted" in text.lower()


def test_compose_includes_rejected_alternatives(repo):
    event = events.new_event(
        events.NOTE,
        decision="chose redis",
        because="shared across instances",
        alternatives=[{"option": "LRU", "why_not": "lost on deploy"}],
        files=["cache.py"],
    )
    event["ts"] = "2026-08-01T10:00:00.000Z"
    ledger.append(paths.ledger_path(repo.path), event)
    text = brief.compose(repo.path)
    assert "LRU" in text
    assert "lost on deploy" in text
    assert "cache.py" in text


def test_compose_prefers_the_ledger_over_decisions_md(repo):
    from whyline import decisions

    add_note(repo, "from ledger", "2026-08-05T10:00:00.000Z")
    stale_event = events.new_event(events.NOTE, decision="from decisions.md")
    stale_event["ts"] = "2026-08-09T10:00:00.000Z"
    decisions.append_entry(paths.decisions_path(repo.path), stale_event)

    text = brief.compose(repo.path)

    assert "from ledger" in text
    assert "from decisions.md" not in text


def test_compose_falls_back_to_decisions_md_when_the_ledger_has_no_notes(repo):
    from whyline import decisions

    # Simulates a fresh clone: ledger.jsonl is gitignored and absent/empty,
    # but decisions.md is committed and populated.
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    event = events.new_event(events.NOTE, decision="recorded before the clone")
    event["ts"] = "2026-08-09T10:00:00.000Z"
    decisions.append_entry(paths.decisions_path(repo.path), event)

    text = brief.compose(repo.path)

    assert "No decisions recorded" not in text
    assert "recorded before the clone" in text
