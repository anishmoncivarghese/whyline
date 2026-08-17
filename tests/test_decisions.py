from whyline import decisions, events


def make_note() -> dict:
    event = events.new_event(
        events.NOTE,
        decision="Store absolute monotonic expiry",
        because="the constructor already injects a monotonic clock",
        alternatives=[{"option": "sleep in tests", "why_not": "slow and flaky"}],
        files=["cache.py"],
    )
    event["ts"] = "2026-08-09T10:00:00.000Z"
    return event


def test_render_entry_includes_decision_reason_and_alternatives():
    text = decisions.render_entry(make_note())
    assert "Store absolute monotonic expiry" in text
    assert "monotonic clock" in text
    assert "sleep in tests" in text
    assert "slow and flaky" in text
    assert "cache.py" in text
    assert "2026-08-09" in text


def test_render_entry_omits_empty_sections():
    event = events.new_event(events.NOTE, decision="Just a decision")
    event["ts"] = "2026-08-09T10:00:00.000Z"
    text = decisions.render_entry(event)
    assert "Rejected" not in text
    assert "Because" not in text


def test_append_entry_creates_the_file_with_a_heading(tmp_path):
    path = tmp_path / "decisions.md"
    decisions.append_entry(path, make_note())
    content = path.read_text()
    assert content.startswith("# Decisions")
    assert "Store absolute monotonic expiry" in content


def test_append_entry_is_append_only(tmp_path):
    path = tmp_path / "decisions.md"
    decisions.append_entry(path, make_note())
    second = make_note()
    second["decision"] = "A later decision"
    decisions.append_entry(path, second)
    content = path.read_text()
    assert content.count("# Decisions") == 1
    assert content.index("Store absolute") < content.index("A later decision")


def test_parse_entries_round_trips_with_render_entry(tmp_path):
    path = tmp_path / "decisions.md"
    notes = []
    for index in range(3):
        event = events.new_event(
            events.NOTE,
            decision=f"decision {index}",
            because=f"because {index}",
            alternatives=[{"option": f"option {index}", "why_not": f"why not {index}"}],
            files=[f"file{index}.py"],
        )
        event["ts"] = f"2026-08-0{index + 1}T10:00:00.000Z"
        notes.append(event)
        decisions.append_entry(path, event)

    parsed = decisions.parse_entries(path)

    assert len(parsed) == 3
    for original, entry in zip(notes, parsed):
        assert entry["decision"] == original["decision"]
        assert entry["because"] == original["because"]
        assert entry["alternatives"] == original["alternatives"]
        assert entry["files"] == original["files"]


def test_parse_entries_yields_empty_values_for_missing_sections(tmp_path):
    path = tmp_path / "decisions.md"
    path.write_text("## 2026-08-09 — Just a heading\n\n<!-- whyline-event: abc123 -->\n")

    parsed = decisions.parse_entries(path)

    assert len(parsed) == 1
    assert parsed[0]["decision"] == "Just a heading"
    assert parsed[0]["because"] == ""
    assert parsed[0]["alternatives"] == []
    assert parsed[0]["files"] == []
    assert parsed[0]["id"] == "abc123"


def test_parse_entries_tolerates_unexpected_prose_between_entries(tmp_path):
    path = tmp_path / "decisions.md"
    path.write_text(
        "# Decisions\n\n"
        "Someone hand-edited this file and left a note here.\n\n"
        "## 2026-08-09 — First decision\n\n"
        "**Because:** reasons\n\n"
        "<!-- whyline-event: first-id -->\n\n"
        "A stray paragraph an editor left behind, not a heading.\n\n"
        "## 2026-08-10 — Second decision\n\n"
        "<!-- whyline-event: second-id -->\n"
    )

    parsed = decisions.parse_entries(path)

    assert [entry["decision"] for entry in parsed] == ["First decision", "Second decision"]
    assert parsed[0]["because"] == "reasons"


def test_parse_entries_on_missing_path_returns_empty_list(tmp_path):
    assert decisions.parse_entries(tmp_path / "nonexistent.md") == []
