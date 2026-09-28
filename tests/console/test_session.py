from dataclasses import FrozenInstanceError
from pathlib import Path
import pytest
from whyline.console.session import ConsoleSession, SessionEvent


def test_session_event_holds_kind_and_text():
    event = SessionEvent(kind="output", text="hello")
    assert event.kind == "output"
    assert event.text == "hello"


def test_session_event_is_frozen():
    event = SessionEvent(kind="output", text="hello")
    with pytest.raises(FrozenInstanceError):
        event.text = "modified"  # type: ignore[misc]


def test_console_session_defaults(tmp_path):
    session = ConsoleSession(root=tmp_path)
    assert session.mode == "command"
    assert session.agent is None
    assert session.transcript == []


def test_console_session_transcripts_are_independent(tmp_path):
    session1 = ConsoleSession(root=tmp_path)
    session2 = ConsoleSession(root=tmp_path)
    assert session1.transcript is not session2.transcript
    session1.record(SessionEvent(kind="output", text="only in 1"))
    assert len(session1.transcript) == 1
    assert len(session2.transcript) == 0


def test_record_appends_and_returns_the_event(tmp_path):
    session = ConsoleSession(root=tmp_path)
    event = SessionEvent(kind="output", text="hi")
    returned = session.record(event)
    assert returned is event
    assert session.transcript == [event]


def test_record_preserves_order_across_multiple_events(tmp_path):
    session = ConsoleSession(root=tmp_path)
    first = session.record(SessionEvent(kind="output", text="one"))
    second = session.record(SessionEvent(kind="error", text="two"))
    assert session.transcript == [first, second]
