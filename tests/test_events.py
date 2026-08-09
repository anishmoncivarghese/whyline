from whyline import events


def test_new_event_carries_schema_version_id_and_timestamp():
    event = events.new_event(events.NOTE, decision="use redis")
    assert event["v"] == events.SCHEMA_VERSION
    assert event["type"] == events.NOTE
    assert event["decision"] == "use redis"
    assert len(event["id"]) == 32
    assert event["ts"].endswith("Z")


def test_new_event_ids_are_unique():
    first = events.new_event(events.NOTE, decision="a")
    second = events.new_event(events.NOTE, decision="b")
    assert first["id"] != second["id"]


def test_parse_rejected_splits_on_the_first_colon_only():
    assert events.parse_rejected(["in-memory LRU: lost on deploy: really"]) == [
        {"option": "in-memory LRU", "why_not": "lost on deploy: really"}
    ]


def test_parse_rejected_handles_missing_reason():
    assert events.parse_rejected(["CDN edge cache"]) == [
        {"option": "CDN edge cache", "why_not": ""}
    ]


def test_parse_rejected_returns_empty_for_no_items():
    assert events.parse_rejected([]) == []
