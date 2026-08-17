from whyline import brief, decisions, events, ledger, paths


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


def test_compose_includes_notes_from_both_sources(repo):
    """Superseded 2026-08-17. This test previously asserted that decisions.md
    content was ABSENT whenever the ledger held anything — which encoded the
    defect where one local note hid an entire committed history."""
    add_note(repo, "from ledger", "2026-08-05T10:00:00.000Z")
    other_event = events.new_event(events.NOTE, decision="from decisions.md")
    other_event["ts"] = "2026-08-09T10:00:00.000Z"
    decisions.append_entry(paths.decisions_path(repo.path), other_event)

    text = brief.compose(repo.path)

    assert "from ledger" in text
    assert "from decisions.md" in text
    assert "2 of 2" in text


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


def _note(decision, ts, *, event_id=None, because="", files=None, alternatives=None):
    event = events.new_event(
        events.NOTE,
        decision=decision,
        because=because,
        files=files or [],
        alternatives=alternatives or [],
    )
    event["ts"] = ts
    if event_id is not None:
        event["id"] = event_id
    return event


def test_compose_merges_both_sources_rather_than_choosing(repo):
    """Regression for the 2026-08-17 defect: one ledger note used to hide a full
    committed history and report "1 of 1"."""
    for index in range(3):
        decisions.append_entry(
            paths.decisions_path(repo.path),
            _note(f"committed {index}", "2026-08-01T10:00:00.000Z", event_id=f"c{index}"),
        )
    ledger.append(
        paths.ledger_path(repo.path),
        _note("local one", "2026-08-05T10:00:00.000Z", event_id="L1"),
    )
    text = brief.compose(repo.path)
    assert "4 of 4" in text
    assert "local one" in text
    for index in range(3):
        assert f"committed {index}" in text


def test_compose_deduplicates_by_id_and_the_ledger_wins(repo):
    shared = "shared-id"
    decisions.append_entry(
        paths.decisions_path(repo.path),
        _note("same decision", "2026-08-01T00:00:00.000Z", event_id=shared),
    )
    ledger.append(
        paths.ledger_path(repo.path),
        _note(
            "same decision",
            "2026-08-01T15:42:07.123Z",
            event_id=shared,
            because="only the ledger copy has this",
        ),
    )
    text = brief.compose(repo.path)
    assert "1 of 1" in text
    assert text.count("same decision") == 1
    assert "only the ledger copy has this" in text


def test_compose_does_not_collapse_two_entries_that_lack_ids(repo):
    path = paths.decisions_path(repo.path)
    for decision in ("first idless", "second idless"):
        event = _note(decision, "2026-08-01T10:00:00.000Z")
        rendered = decisions.render_entry(event)
        stripped = "\n".join(
            line for line in rendered.splitlines() if "whyline-event" not in line
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(decisions.HEADING, encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + stripped + "\n")
    text = brief.compose(repo.path)
    assert "first idless" in text
    assert "second idless" in text
    assert "2 of 2" in text


def test_compose_discloses_sources_only_when_committed_entries_are_used(repo):
    decisions.append_entry(
        paths.decisions_path(repo.path),
        _note("from markdown", "2026-08-01T10:00:00.000Z", event_id="m1"),
    )
    assert "from committed decisions.md" in brief.compose(repo.path)


def test_compose_omits_the_sources_line_when_everything_is_local(repo):
    ledger.append(
        paths.ledger_path(repo.path),
        _note("local only", "2026-08-01T10:00:00.000Z", event_id="L9"),
    )
    text = brief.compose(repo.path)
    assert "local only" in text
    assert "Sources:" not in text
