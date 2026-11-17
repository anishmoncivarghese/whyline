from datetime import datetime
from types import SimpleNamespace

import pytest

from whyline.agents import definitions as d, gates, state, watch
from whyline.agents.watch import Memory, Watch

BASE = 'name = "w"\nrunner = "claude"\n'
PAGE = '[checkin]\ngate = "page"\n[checkin.gate_args]\nurl = "https://a.test/x"\nrule = "{rule}"\ntext = "Round 2 result"\n'


def _parse(repo, body):
    return d.parse(BASE + body, kind="repo", path=repo / ".whyline/agents/w.toml", repo_root=repo)


def _watch_toml(rule="always", instructions='instructions = "price"\n', table='[watch]\nvalue = "below 4000"\n'):
    return BASE + instructions + PAGE.format(rule=rule) + table


def test_whyline_compares_the_value():
    w = Watch(value="below 4000")
    # the answer says the price is below the limit, but the value is above it
    answer = "VALUE: 4500\nThe price is below the limit."
    assert watch.decide(w, watch.read_value(answer), Memory()) is None
    hit = watch.decide(w, watch.read_value("VALUE: 3799"), Memory())
    assert hit is not None and hit.value == 3799


@pytest.mark.parametrize("text,expected", [
    ("VALUE: ₹3,799.00", 3799.0),
    ("VALUE: $4,999", 4999.0),
    ("VALUE: Rs. 1299.5", 1299.5),
    ("VALUE: 12", 12.0),
    ("x\nVALUE: 1 299 INR", 1299.0),
    ("VALUE: 5\nVALUE: 7.25", 7.25),
])
def test_read_value_formats(text, expected):
    assert watch.read_value(text) == expected


def test_read_value_none():
    assert watch.read_value("no line") is None
    assert watch.read_value("VALUE: unknown") is None


def test_reset_after_going_back_over_the_limit():
    w, m = Watch(value="below 4000"), Memory()
    assert watch.decide(w, 3900, m) is not None and m.told == 3900
    assert watch.decide(w, 4100, m) is None and m.told is None
    assert watch.decide(w, 3950, m) is not None


def test_further_drop_is_a_hit_small_rise_is_not():
    w, m = Watch(value="below 4000"), Memory(told=3800)
    assert watch.decide(w, 3900, m) is None
    assert watch.decide(w, 3500, m) is not None


def test_above_mirror():
    w, m = Watch(value="above 100"), Memory()
    assert watch.decide(w, 150, m) is not None
    assert watch.decide(w, 120, m) is None
    assert watch.decide(w, 200, m) is not None
    assert watch.decide(w, 90, m) is None and m.told is None


def test_hit_line():
    m = Memory(values=[("2026-11-01T00:00:00", 4999.0)])
    hit = watch.decide(Watch(value="below 4000"), 3799, m)
    assert hit.line == "3,799, down from 4,999. Your limit is 4,000."
    assert watch.decide(Watch(value="below 4000"), 3799, Memory()).line == "3,799. Your limit is 4,000."
    m = Memory(values=[("t", 50.0)])
    assert watch.decide(Watch(value="above 100"), 150, m).line == "150, up from 50. Your limit is 100."


def test_value_cap_200():
    m = Memory()
    for i in range(250):
        watch.record(m, float(i), datetime(2026, 11, 17))
    assert len(m.values) == 200 and m.values[-1][1] == 249.0 and m.values[0][1] == 50.0


def test_memory_roundtrip_and_cap(home):
    conn = state.connect()
    assert state.watch_memory(conn, "a") == Memory()
    m = Memory(values=[("t", float(i)) for i in range(300)], told=3.5, last_message="hi", note="n")
    state.save_watch_memory(conn, "a", m)
    got = state.watch_memory(conn, "a")
    assert len(got.values) == 200 and got.told == 3.5 and got.note == "n" and got.last_message == "hi"
    state.remove(conn, "a")
    assert state.watch_memory(conn, "a") == Memory()


def test_note_and_strip():
    answer = "Hello\nVALUE: 5\nREMEMBER: old\nREMEMBER:  seen\tit  twice \nBye"
    assert watch.note(answer) == "seen it twice"
    assert watch.note("x" * 3) == ""
    assert len(watch.note("REMEMBER: " + "a" * 900)) == 500
    assert watch.strip(answer) == "Hello\nBye"


def test_last_md():
    m = Memory(values=[(f"2026-11-{i:02d}T10:00:00", float(i)) for i in range(1, 13)],
               last_message="sent it", note="be brief")
    text = watch.last_md(m)
    assert "sent it" in text and "be brief" in text
    assert "2026-11-12: 12" in text and "2026-11-03: 3" in text and "2026-11-02" not in text


@pytest.mark.parametrize("rule,line", [
    ("appears", 'The text "Round 2 result" is now on the page.'),
    ("gone", 'The text "Round 2 result" is no longer on the page.'),
    ("changed", "The page changed."),
])
def test_own_message(repo, rule, line):
    defn = _parse(repo, _watch_toml(rule, "", "[watch]\n")[len(BASE):])
    items = [gates.Item(f"k{i}", f"line {i}") for i in range(12)]
    out = watch.own_message(defn, gates.Found(items, {})).splitlines()
    assert out[0] == "w" and out[1] == line
    assert out[2:12] == [f"line {i}" for i in range(10)]
    assert out[-1] == "https://a.test/x" and len(out) == 13


def test_loads_and_renders(repo):
    defn = _parse(repo, _watch_toml(table='[watch]\nstop = "first"\nvalue = "below 4000"\nurgent = true\ndaily_cap = 5\n')[len(BASE):])
    assert defn.watch == Watch(stop="first", value="below 4000", urgent=True, daily_cap=5)
    again = d.parse(d.render(defn), kind="repo", path=defn.path, repo_root=repo)
    assert again.watch == defn.watch
    assert _parse(repo, _watch_toml(table="[watch]\n")[len(BASE):]).watch == Watch()


def test_no_watch_table_loads_as_before(repo):
    defn = _parse(repo, 'instructions = "x"\n')
    assert defn.watch is None and "[watch]" not in d.render(defn)


@pytest.mark.parametrize("body,message", [
    (BASE + 'instructions = "x"\n[watch]\n', "page gate"),
    (_watch_toml(table='[watch]\nstop = "twice"\n'), "stop"),
    (_watch_toml(table='[watch]\nvalue = "under 5"\n'), "below 4000"),
    (_watch_toml(table='[watch]\ndaily_cap = 0\n'), "daily_cap"),
    (_watch_toml(table='[watch]\ndaily_cap = 201\n'), "daily_cap"),
    (_watch_toml(table='[watch]\nurgent = "yes"\n'), "urgent"),
    (_watch_toml(instructions="", table='[watch]\nvalue = "below 5"\n'), "needs instructions"),
    (_watch_toml(rule="gone"), "gone rule"),
    (_watch_toml(rule="always", instructions="", table="[watch]\n"), "instructions are empty"),
    (_watch_toml(rule="changed", instructions=""), "instructions"),
])
def test_refusals(repo, body, message):
    with pytest.raises(d.DefinitionError, match=message):
        _parse(repo, body[len(BASE):])


def test_empty_instructions_without_watch_refused(repo):
    with pytest.raises(d.DefinitionError, match="instructions are empty"):
        _parse(repo, 'instructions = ""\n')
