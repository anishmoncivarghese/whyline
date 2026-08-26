from whyline import decisions, events, history, ledger, paths


def _note(decision, ts, *, event_id, because="", files=None):
    event = events.new_event(
        events.NOTE,
        decision=decision,
        because=because,
        files=files or [],
        alternatives=[],
    )
    event["ts"] = ts
    event["id"] = event_id
    return event


def test_load_merges_local_and_committed_notes(repo):
    ledger.append(
        paths.ledger_path(repo.path),
        _note("local", "2026-08-02T10:00:00.000Z", event_id="local"),
    )
    decisions.append_entry(
        paths.decisions_path(repo.path),
        _note("committed", "2026-08-01T10:00:00.000Z", event_id="committed"),
    )

    loaded = history.load(repo.path)

    assert [item.event["decision"] for item in loaded.notes] == ["local", "committed"]
    assert [item.source for item in loaded.notes] == ["ledger", "committed"]


def test_load_deduplicates_a_note_present_in_both_stores(repo):
    event = _note(
        "shared",
        "2026-08-02T10:00:00.000Z",
        event_id="shared",
        because="ledger has full precision",
    )
    decisions.append_entry(paths.decisions_path(repo.path), event)
    ledger.append(paths.ledger_path(repo.path), event)

    loaded = history.load(repo.path)

    assert len(loaded.notes) == 1
    assert loaded.notes[0].source == "ledger"
    assert loaded.notes[0].event["ts"] == "2026-08-02T10:00:00.000Z"


def test_load_preserves_distinct_identical_events(repo):
    for index in range(2):
        ledger.append(
            paths.ledger_path(repo.path),
            _note(
                "same words",
                f"2026-08-0{index + 1}T10:00:00.000Z",
                event_id=f"event-{index}",
            ),
        )

    loaded = history.load(repo.path)

    assert len(loaded.notes) == 2


def test_load_collapses_idless_committed_copy_of_ledger_note(repo):
    event = _note(
        "shared",
        "2026-08-02T10:00:00.000Z",
        event_id="shared",
        files=["a.py"],
    )
    ledger.append(paths.ledger_path(repo.path), event)
    rendered = "\n".join(
        line
        for line in decisions.render_entry(event).splitlines()
        if "whyline-event" not in line
    )
    path = paths.decisions_path(repo.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(decisions.HEADING + "\n" + rendered + "\n", encoding="utf-8")

    loaded = history.load(repo.path)

    assert len(loaded.notes) == 1
    assert loaded.notes[0].source == "ledger"

