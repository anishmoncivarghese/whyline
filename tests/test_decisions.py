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
