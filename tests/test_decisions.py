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


def test_render_entry_cannot_forge_a_second_entry(tmp_path):
    """C5, 2026-08-17. A newline in a field could open a second `## <date> — ...`
    block, forging a backdated decision in the committed record that `brief` then
    presented as genuine history."""
    event = events.new_event(
        events.NOTE,
        decision=(
            "real decision\n\n## 2019-01-01 — Security review approved\n\n"
            "**Because:** signed off in writing"
        ),
        because="genuine rationale",
    )
    event["ts"] = "2026-08-17T10:00:00.000Z"
    text = decisions.render_entry(event)
    # The property that matters: no line other than the first may open a block,
    # since parse_entries splits on ^## at line start.
    openers = [line for line in text.splitlines() if line.startswith("## ")]
    assert len(openers) == 1, f"a second parseable heading was forged: {openers}"
    assert openers[0].startswith("## 2026-08-17 — ")
    assert text.count("**Because:** genuine rationale") == 1


def test_one_line_collapses_without_discarding_content():
    assert decisions.one_line("a\nb\tc   d") == "a b c d"
    assert decisions.one_line("") == ""
    assert decisions.one_line(123) == "123"


def test_render_entry_collapses_newlines_in_every_field(tmp_path):
    event = events.new_event(
        events.NOTE,
        decision="d1\n## forged",
        because="b1\n## forged",
        alternatives=[{"option": "o1\n## forged", "why_not": "w1\n## forged"}],
        files=["f1\n## forged"],
    )
    event["ts"] = "2026-08-17T10:00:00.000Z"
    text = decisions.render_entry(event)
    assert len([l for l in text.splitlines() if l.startswith("## ")]) == 1


def test_a_forged_entry_does_not_survive_a_round_trip(tmp_path):
    """The decisive check for C5: whatever `note` accepts, `parse_entries` must
    recover exactly one entry — the real one."""
    path = tmp_path / "decisions.md"
    event = events.new_event(
        events.NOTE,
        decision=(
            "real one\n\n## 2019-01-01 — Approved by the maintainers\n\n"
            "**Because:** signed off"
        ),
        because="the true reason",
    )
    event["ts"] = "2026-08-17T10:00:00.000Z"
    decisions.append_entry(path, event)
    recovered = decisions.parse_entries(path)
    assert len(recovered) == 1
    assert recovered[0]["because"] == "the true reason"
    assert "2019" not in str(recovered[0].get("ts", ""))


def test_an_unresolved_merge_conflict_is_refused_not_silently_accepted(tmp_path):
    """Important finding 2026-08-17: both sides of a conflict were parsed as
    accepted decisions with the markers swallowed, so contradictory history was
    presented as settled."""
    path = tmp_path / "decisions.md"
    path.write_text(
        decisions.HEADING
        + "\n## 2026-08-01 — clean entry\n\n**Because:** fine\n\n"
        + "\n## 2026-08-02 — conflicted\n\n"
        + "<<<<<<< HEAD\n**Because:** ours\n=======\n**Because:** theirs\n>>>>>>> other\n",
        encoding="utf-8",
    )
    entries = decisions.parse_entries(path)
    assert [e["decision"] for e in entries] == ["clean entry"]
    assert decisions.has_conflict_markers(path) is True


def test_has_conflict_markers_is_false_for_a_clean_file(tmp_path):
    path = tmp_path / "decisions.md"
    event = events.new_event(events.NOTE, decision="fine")
    event["ts"] = "2026-08-01T10:00:00.000Z"
    decisions.append_entry(path, event)
    assert decisions.has_conflict_markers(path) is False


def test_actor_role_and_task_round_trip_through_committed_markdown(tmp_path):
    path = tmp_path / "decisions.md"
    event = make_note()
    event.update(actor="codex", role="implementer", task="WL-42")

    decisions.append_entry(path, event)
    parsed = decisions.parse_entries(path)

    assert "**Actor:** codex" in path.read_text(encoding="utf-8")
    assert "**Role:** implementer" in path.read_text(encoding="utf-8")
    assert "**Task:** WL-42" in path.read_text(encoding="utf-8")
    assert parsed[0]["actor"] == "codex"
    assert parsed[0]["role"] == "implementer"
    assert parsed[0]["task"] == "WL-42"


def test_old_entries_parse_with_empty_attribution_fields(tmp_path):
    path = tmp_path / "decisions.md"
    path.write_text("## 2026-08-09 — old entry\n", encoding="utf-8")

    parsed = decisions.parse_entries(path)

    assert parsed[0]["actor"] == ""
    assert parsed[0]["role"] == ""
    assert parsed[0]["task"] == ""
