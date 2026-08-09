import json

from whyline import events, ledger


def test_append_creates_parent_directory_and_writes_one_line(tmp_path):
    path = tmp_path / ".whyline" / "ledger.jsonl"
    ledger.append(path, events.new_event(events.NOTE, decision="a"))
    assert path.read_text().count("\n") == 1


def test_append_is_deterministic_and_key_sorted(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, {"v": 1, "type": "Note", "id": "x", "ts": "t", "a": 1})
    line = path.read_text().strip()
    assert line == json.dumps(
        {"a": 1, "id": "x", "ts": "t", "type": "Note", "v": 1},
        sort_keys=True,
        separators=(",", ":"),
    )


def test_read_all_returns_events_in_order(tmp_path):
    path = tmp_path / "ledger.jsonl"
    for name in ("first", "second", "third"):
        ledger.append(path, events.new_event(events.NOTE, decision=name))
    found, skipped = ledger.read_all(path)
    assert [event["decision"] for event in found] == ["first", "second", "third"]
    assert skipped == 0


def test_read_all_skips_a_torn_final_line_from_a_crash(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, events.new_event(events.NOTE, decision="good"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"v":1,"type":"Not')
    found, skipped = ledger.read_all(path)
    assert [event["decision"] for event in found] == ["good"]
    assert skipped == 1


def test_read_all_on_a_missing_file_is_empty_not_an_error(tmp_path):
    assert ledger.read_all(tmp_path / "absent.jsonl") == ([], 0)


def test_read_all_ignores_blank_lines(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(path, events.new_event(events.NOTE, decision="a"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
    found, skipped = ledger.read_all(path)
    assert len(found) == 1
    assert skipped == 0
