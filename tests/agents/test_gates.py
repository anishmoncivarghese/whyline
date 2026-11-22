import json
import os
import subprocess
from datetime import datetime, timedelta

import pytest

from whyline.agents import gates, pagefetch
from whyline.ideas.brief import Event, Message

NOW = datetime(2026, 11, 17, 10, 0)


def readers(**kw):
    base = dict(
        mail=lambda: [],
        events=lambda: [],
        reminders=lambda: [],
        repos=lambda: {"proj": "/tmp"},
    )
    base.update(kw)
    return gates.Readers(**base)


def msg(sender, subject, minute=0):
    return Message(sender, subject, NOW - timedelta(minutes=minute), "body")


def test_gate_reports_an_item_once():
    r = readers(mail=lambda: [msg("Ann <ann@x.com>", "Hello")])
    first = gates.check("mail-from", {"sender": "ann@x.com"}, {}, now=NOW, readers=r)
    assert [i.line for i in first.items] == ["Mail from Ann: Hello"]
    second = gates.check("mail-from", {"sender": "ann@x.com"}, first.state, now=NOW, readers=r)
    assert second.items == []
    assert len(second.state["seen"]) == 1


def test_seen_keeps_at_most_500_newest():
    r = readers(mail=lambda: [msg("a@x", f"s{n}", n) for n in range(600)])
    found = gates.check("mail-from", {"sender": "a@x"}, {}, now=NOW, readers=r)
    assert len(found.items) == 600
    assert len(found.state["seen"]) == 500
    assert found.state["seen"][-1] == found.items[-1].key


def test_mail_from_matches_sender_only():
    r = readers(mail=lambda: [msg("Bob <b@x.com>", "no"), msg("ANN <ann@x.com>", "yes")])
    found = gates.check("mail-from", {"sender": "ann"}, {}, now=NOW, readers=r)
    assert [i.line for i in found.items] == ["Mail from ANN: yes"]


def test_event_soon_uses_window_and_default():
    def ev(title, minutes, all_day=False):
        start = NOW + timedelta(minutes=minutes)
        return Event(title, start, start + timedelta(hours=1), "", all_day, "Work")

    r = readers(events=lambda: [ev("Soon", 10), ev("Later", 60), ev("Past", -5), ev("Day", 5, True)])
    found = gates.check("event-soon", {}, {}, now=NOW, readers=r)
    assert [i.line for i in found.items] == ["Event at 10:10: Soon"]
    wide = gates.check("event-soon", {"minutes": "90"}, {}, now=NOW, readers=r)
    assert len(wide.items) == 2


def test_reminder_overdue():
    r = readers(
        reminders=lambda: [
            ("Pay rent", "2026-11-17T09:00:00", "Home"),
            ("Later", "2026-11-17T18:00:00", "Home"),
            ("Bad", "nonsense", "Home"),
        ]
    )
    found = gates.check("reminder-overdue", {}, {}, now=NOW, readers=r)
    assert [i.line for i in found.items] == ["Overdue since 2026-11-17 09:00: Pay rent"]


def test_ci_failed_gh_argv():
    calls = []

    def fake(argv, **kw):
        calls.append((argv, kw.get("cwd")))
        if argv[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(argv, 0, "trunk\n", "")
        out = [{"databaseId": 7, "displayTitle": "Build", "url": "http://u", "createdAt": "t"}]
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    found = gates.check("ci-failed", {"repo": "proj"}, {}, now=NOW, run=fake, readers=readers())
    assert calls[1][0] == [
        "gh", "run", "list", "--branch", "trunk", "--status", "failure", "--limit", "5",
        "--json", "databaseId,displayTitle,url,createdAt",
    ]
    assert calls[1][1] == "/tmp"
    assert [i.key for i in found.items] == ["ci|proj|7"]
    assert "Build" in found.items[0].line


def test_ci_failed_gh_error_is_gate_error():
    def fake(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "not logged in")

    with pytest.raises(gates.GateError, match="not logged in"):
        gates.check("ci-failed", {"repo": "proj"}, {}, now=NOW, run=fake, readers=readers())


def test_ci_failed_unknown_repo_refused():
    with pytest.raises(gates.GateError, match="not a repository"):
        gates.check("ci-failed", {"repo": "nope"}, {}, now=NOW, readers=readers())


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def test_changed_reports_newer_files(home):
    folder = home / "watch"
    folder.mkdir()
    old = folder / "old.txt"
    old.write_text("x")
    base = gates.check("changed", {"path": str(folder)}, {}, now=NOW, readers=readers())
    assert base.items == []
    since = base.state["checked"]
    new = folder / "new.txt"
    new.write_text("y")
    os.utime(new, (since + 100, since + 100))
    os.utime(old, (since - 100, since - 100))
    found = gates.check("changed", {"path": str(folder)}, base.state, now=NOW, readers=readers())
    assert [i.line for i in found.items] == [f"Changed: {new.resolve()}"]


def test_changed_examines_at_most_200_files(home):
    folder = home / "many"
    folder.mkdir()
    for n in range(250):
        (folder / f"f{n:03}.txt").write_text("x")
    state = {"checked": 0.0}
    found = gates.check("changed", {"path": str(folder)}, state, now=NOW, readers=readers())
    assert len(found.items) == 200


def test_path_outside_home_refused(home):
    with pytest.raises(gates.GateError, match="home folder"):
        gates.validate("changed", {"path": "/etc"})
    with pytest.raises(gates.GateError, match="home folder"):
        gates.check("changed", {"path": "/etc"}, {}, now=NOW, readers=readers())


def test_unknown_gate_and_bad_arguments_refused(home):
    with pytest.raises(gates.GateError, match="not a gate"):
        gates.validate("shell", {})
    with pytest.raises(gates.GateError, match="needed"):
        gates.validate("mail-from", {})
    with pytest.raises(gates.GateError, match="whole number"):
        gates.validate("event-soon", {"minutes": "soon"})
    with pytest.raises(gates.GateError, match="whole number"):
        gates.validate("event-soon", {"minutes": "0"})
    with pytest.raises(gates.GateError, match="no argument"):
        gates.validate("reminder-overdue", {"cmd": "rm -rf"})
    with pytest.raises(gates.GateError, match="does not exist"):
        gates.validate("changed", {"path": str(home / "missing")})


def test_validate_returns_cleaned_arguments(home):
    assert gates.validate("event-soon", {}) == {"minutes": "15"}
    assert gates.validate("mail-from", {"sender": "  ann "}) == {"sender": "ann"}
    assert gates.validate("reminder-overdue", {}) == {}
    assert gates.validate("changed", {"path": str(home)}) == {"path": str(home.resolve())}


def test_gates_list():
    assert list(gates.GATES) == [
        "mail-from", "event-soon", "ci-failed", "reminder-overdue", "changed", "page",
    ]
    assert gates.GATES["event-soon"].args[0].default == "15"


def test_write_found_file(tmp_path):
    found = gates.Found([gates.Item("a", "one"), gates.Item("b", "x" * 400)], {})
    run_dir = tmp_path / "run"
    assert gates.write(found, run_dir) == 2
    lines = (run_dir / "found.md").read_text().splitlines()
    assert lines[0] == "one"
    assert len(lines[1]) == 300
    assert gates.write(gates.Found([], {}), run_dir) == 0


def test_mail_reader_script_is_unread_only():
    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "ok\x1e\x1e", "")

    assert gates.read_mail(["INBOX"], run) == []
    source = seen["argv"][seen["argv"].index("-e") + 1]
    assert "flagged status" not in source
    assert "read status is false" in source
    assert seen["argv"][-1] == "INBOX"


def test_mail_reader_skips_without_mailboxes():
    def run(argv, **kw):
        raise AssertionError("must not run")

    assert gates.read_mail([], run) == []


def test_calendar_reader_looks_past_midnight():
    seen = {}
    payload = {
        "status": "ok",
        "date": "2026-11-17",
        "calendars": ["Work"],
        "events": [
            {
                "title": "Early call",
                "start": "2026-11-18T00:05:00",
                "end": "2026-11-18T00:30:00",
                "location": "",
                "allDay": False,
                "calendar": "Work",
            }
        ],
    }

    def run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    events = gates.read_events(run)
    source = seen["argv"][seen["argv"].index("-e") + 1]
    assert "now.getDate() + 2)" in source
    assert "now.getDate() + 1)" not in source
    late = datetime(2026, 11, 17, 23, 55)
    found = gates.check(
        "event-soon", {"minutes": "15"}, {}, now=late, readers=readers(events=lambda: events)
    )
    assert [i.line for i in found.items] == ["Event at 00:05: Early call"]


def test_calendar_reader_reports_denied():
    def run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, '{"status": "denied"}', "")

    with pytest.raises(gates.GateError):
        gates.read_events(run)


URL = "https://example.com/a"


def fake_pages(monkeypatch, pages):
    """pages maps a url to text, or to a (state, reason) pair."""

    def fetch(url, *, now, **kw):
        got = pages[url]
        if isinstance(got, tuple):
            return pagefetch.Page(url, got[0], reason=got[1])
        return pagefetch.Page(url, "ok", text=got)

    monkeypatch.setattr(pagefetch, "fetch", fetch)


def look(args, state, **kw):
    return gates.check("page", {"rule": "changed", **args}, state, now=NOW, readers=readers(), **kw)


def test_page_changed_first_then_diff(monkeypatch):
    pages = {URL: "one\ntwo"}
    fake_pages(monkeypatch, pages)
    first = look({"url": URL}, {})
    assert first.items == []
    pages[URL] = "one\nthree"
    second = look({"url": URL}, first.state)
    assert [i.line for i in second.items] == ["-two", "+three"]
    assert look({"url": URL}, second.state).items == []


def test_page_changed_reports_cycling_content_every_time(monkeypatch):
    pages = {URL: "a"}
    fake_pages(monkeypatch, pages)
    state = look({"url": URL}, {}).state
    for text, line in [("b", "+b"), ("a", "+a"), ("b", "+b"), ("a", "+a")]:
        pages[URL] = text
        got = look({"url": URL}, state)
        assert line in [i.line for i in got.items]
        state = got.state


def test_page_changed_caps_items_and_lines(monkeypatch):
    pages = {URL: "x"}
    fake_pages(monkeypatch, pages)
    first = look({"url": URL}, {})
    pages[URL] = "\n".join(["y" * 500] * 60)
    second = look({"url": URL}, first.state)
    assert len(second.items) == 40
    assert all(len(i.line) <= 300 for i in second.items)


def test_page_appears(monkeypatch):
    pages = {URL: "Sold   OUT"}
    fake_pages(monkeypatch, pages)
    args = {"url": URL, "rule": "appears", "text": "in stock"}
    first = look(args, {})
    assert first.items == []
    pages[URL] = "now IN  stock!"
    second = look(args, first.state)
    assert len(second.items) == 1
    assert look(args, second.state).items == []


def test_page_appears_already_there_on_first_check(monkeypatch):
    fake_pages(monkeypatch, {URL: "In stock"})
    found = look({"url": URL, "rule": "appears", "text": "in stock"}, {})
    assert len(found.items) == 1


def test_page_gone(monkeypatch):
    pages = {URL: "Sale on"}
    fake_pages(monkeypatch, pages)
    args = {"url": URL, "rule": "gone", "text": "sale on"}
    first = look(args, {})
    assert first.items == []
    assert look(args, first.state).items == []
    pages[URL] = "nothing"
    second = look(args, first.state)
    assert len(second.items) == 1
    assert look(args, second.state).items == []


def test_page_always_reports_every_check(monkeypatch):
    fake_pages(monkeypatch, {URL: "same"})
    args = {"url": URL, "rule": "always"}
    first = look(args, {})
    assert [i.line for i in first.items] == [f"checked {URL}"]
    later = gates.check("page", args, first.state, now=NOW + timedelta(hours=1), readers=readers())
    assert [i.line for i in later.items] == [f"checked {URL}"]


def test_page_needs_text_for_appears_and_gone():
    for rule in ("appears", "gone"):
        with pytest.raises(gates.GateError, match="Text to look for"):
            gates.validate("page", {"url": URL, "rule": rule})
        with pytest.raises(gates.GateError, match="Text to look for"):
            gates.validate("page", {"url": URL, "rule": rule, "text": "x"})
    with pytest.raises(gates.GateError, match="one of"):
        gates.validate("page", {"url": URL, "rule": "sometimes"})
    with pytest.raises(gates.GateError, match="at most 3"):
        gates.validate("page", {"url": " ".join([URL] * 4)})
    assert gates.validate("page", {"url": URL}) == {"url": URL, "rule": "changed"}


def test_page_between_texts(monkeypatch):
    pages = {URL: "head [start]price 5[end] tail 1"}
    fake_pages(monkeypatch, pages)
    args = {"url": URL, "start": "[start]", "end": "[end]"}
    first = look(args, {})
    assert first.state["pages"][URL]["text"] == "price 5"
    pages[URL] = "head [start]price 6[end] tail 2"
    assert [i.line for i in look(args, first.state).items] == ["-price 5", "+price 6"]


def test_page_between_texts_missing_fails(monkeypatch):
    fake_pages(monkeypatch, {URL: "no markers"})
    state = {}
    for _ in range(3):
        found = look({"url": URL, "start": "[a]", "end": "[b]"}, state)
        state = found.state
    assert found.notice == f"couldn't read {URL}: the start or end text isn't on the page"
    assert "hash" not in state["pages"][URL]


def test_blocked_is_not_a_change(monkeypatch):
    pages = {URL: "one"}
    fake_pages(monkeypatch, pages)
    first = look({"url": URL}, {})
    pages[URL] = ("blocked", "the site is blocking automated checks")
    blocked = look({"url": URL}, first.state)
    assert blocked.items == []
    assert blocked.state["pages"][URL]["text"] == "one"
    assert blocked.state["pages"][URL]["hash"] == first.state["pages"][URL]["hash"]
    assert blocked.state["pages"][URL]["failures"] == 1


def test_three_failures_one_message(monkeypatch):
    pages = {URL: "one"}
    fake_pages(monkeypatch, pages)
    state = look({"url": URL}, {}).state
    pages[URL] = ("failed", "timed out")
    notices = []
    for _ in range(4):
        found = look({"url": URL}, state)
        state = found.state
        notices.append(found.notice)
    assert notices == ["", "", f"couldn't read {URL}: timed out", ""]
    pages[URL] = "one"
    back = look({"url": URL}, state)
    assert back.notice == f"{URL} can be read again"
    assert back.items == []
    assert look({"url": URL}, back.state).notice == ""


def test_page_three_addresses_one_failing(monkeypatch):
    a, b, c = (f"https://example.com/{n}" for n in "abc")
    pages = {a: "1", b: ("failed", "boom"), c: "3"}
    fake_pages(monkeypatch, pages)
    args = {"url": f"{a} {b} {c}", "rule": "always"}
    found = look(args, {})
    assert [i.line for i in found.items] == [f"checked {a}", f"checked {c}"]
    assert found.state["pages"][b]["failures"] == 1


def test_write_page_files(tmp_path, monkeypatch):
    pages = {URL: "old"}
    fake_pages(monkeypatch, pages)
    first = look({"url": URL}, {})
    pages[URL] = "new"
    second = look({"url": URL}, first.state)
    gates.write(second, tmp_path)
    assert (tmp_path / "page.md").read_text() == "new"
    assert (tmp_path / "before.md").read_text() == "old"
    assert (tmp_path / "found.md").exists()
    other = tmp_path / "other"
    gates.write(gates.Found([], {}), other)
    assert not (other / "page.md").exists()
