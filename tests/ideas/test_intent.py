"""Deterministic routing: buttons, commands, settings, answers, ideas."""

import difflib

import pytest

from whyline.ideas.intent import (
    AGENTS,
    COMMANDS,
    AgentWord,
    Field,
    action,
    answer,
    capture,
    command,
    free,
    normalise_agent,
    request,
    route,
    settings,
)


def _route(text, callback=None, *, open_question=False):
    return route(text, callback, open_question=open_question)


@pytest.mark.parametrize(
    ("text", "name", "args"),
    [
        ("/new", "new", ()),
        ("new", "new", ()),
        ("NEW", "new", ()),
        ("/list", "list", ()),
        ("list", "list", ()),
        ("listt", "list", ()),
        ("/help", "help", ()),
        ("HELP", "help", ()),
        ("/excel", "excel", ()),
        ("excel", "excel", ()),
        ("exel", "excel", ()),
        ("/exel", "excel", ()),
        ("EXEL", "excel", ()),
        ("excell", "excel", ()),
        ("/status", "status", ()),
        ("status", "status", ()),
        ("/status 4", "status", ("4",)),
        ("status 4", "status", ("4",)),
        ("status agents", "status", ("agents",)),
        ("/status relay", "status", ("relay",)),
        ("status morning-brief", "status", ("morning-brief",)),
        ("run morning-brief", "run", ("morning-brief",)),
        ("/run morning-brief", "run", ("morning-brief",)),
        ("ask app where is config", "ask", ("app", "where", "is", "config")),
        ("/ask where is config", "ask", ("where", "is", "config")),
        (
            "remind tomorrow 9am buy milk",
            "remind",
            ("tomorrow", "9am", "buy", "milk"),
        ),
        ("/remind in 2h stretch", "remind", ("in", "2h", "stretch")),
        ("/staus", "status", ()),
        ("/staus 4", "status", ("4",)),
        ("STAUS 9", "status", ("9",)),
        ("statu", "status", ()),
        ("satus 2", "status", ("2",)),
        ("/brainstorm", "brainstorm", ()),
        ("brainstorm 3", "brainstorm", ("3",)),
        ("brainstrom", "brainstorm", ()),
        ("/Brainstorm 8", "brainstorm", ("8",)),
        ("/plan", "plan", ()),
        ("plan 2", "plan", ("2",)),
        ("/stop", "stop", ()),
        ("stop 1", "stop", ("1",)),
        ("stp", "stop", ()),
        ("/drop 5", "drop", ("5",)),
        ("drop 5", "drop", ("5",)),
        ("/DROP 12", "drop", ("12",)),
        ("drp 5", "drop", ("5",)),
    ],
)
def test_commands_and_near_misses(text, name, args):
    assert _route(text) == command(name, args)


@pytest.mark.parametrize(
    "text",
    [
        "help me think of a ledger",
        "plan a garden tracker",
        "new phone app for plants",
        "stop the nightly build idea",
        "list of things to cook",
        "excellent idea for a bot",
        "drop the garden idea",
        "hepl me decide",
    ],
)
def test_prose_that_starts_like_a_command_is_capture(text):
    assert _route(text) == capture(text)


@pytest.mark.parametrize("text", ["/drop", "drop", "/DROP", "DROP", "drp"])
def test_drop_without_the_required_id_is_capture(text):
    # `/drop <id>` is the grammar. A missing id is not command("drop", ()).
    assert _route(text) == capture(text)


def test_status_takes_only_one_target():
    text = "status morning brief"
    assert _route(text) == capture(text)


def test_run_keeps_extra_words_for_a_deterministic_refusal():
    assert _route("run morning-brief with a prompt") == command(
        "run", ("morning-brief", "with", "a", "prompt")
    )
    assert _route("run morning-brief\nextra prompt") == command(
        "run", ("morning-brief", "extra", "prompt")
    )


def test_ask_keeps_the_whole_question_for_the_command_handler():
    assert _route("ask app how does this work") == command(
        "ask", ("app", "how", "does", "this", "work")
    )


def test_command_near_miss_uses_the_spec_cutoff(monkeypatch):
    seen = {}
    real = difflib.get_close_matches

    def spy(word, possibilities, n=3, cutoff=0.6):
        seen["word"] = word
        seen["possibilities"] = tuple(possibilities)
        seen["cutoff"] = cutoff
        return real(word, possibilities, n=n, cutoff=cutoff)

    monkeypatch.setattr(difflib, "get_close_matches", spy)
    assert _route("exel") == command("excel", ())
    assert seen["word"] == "exel"
    assert seen["possibilities"] == COMMANDS
    assert seen["cutoff"] == 0.8


def test_a_far_word_is_not_a_command():
    assert difflib.get_close_matches("zzzz", COMMANDS, n=1, cutoff=0.8) == []
    assert _route("zzzz") == capture("zzzz")


@pytest.mark.parametrize(
    ("data", "name", "idea_id", "revision"),
    [
        ("brainstorm:3:1", "brainstorm", 3, 1),
        ("drop:4:0", "drop", 4, 0),
        ("quick_score:12:2", "quick_score", 12, 2),
        ("start-now:1:7", "start-now", 1, 7),
    ],
)
def test_callback_parses_exactly(data, name, idea_id, revision):
    assert _route("the card text", data) == action(name, idea_id, revision)


@pytest.mark.parametrize(
    "data",
    [
        "brainstorm:1",
        "brainstorm:x:1",
        "brainstorm:1:y",
        "brainstorm:1:2:3",
        ":1:2",
        "brainstorm::1",
        "not a callback",
        "brainstorm:1:2 ",
        "brainstorm: 1:2",
        " brainstorm:1:2",
    ],
)
def test_malformed_callback_is_free(data):
    assert _route("idea text", data) == free(data)


@pytest.mark.parametrize(
    ("data", "name", "request_id", "code"),
    [
        ("req:ok:7:abcdefgh", "ok", 7, "abcdefgh"),
        ("req:no:12:xyz23456", "no", 12, "xyz23456"),
        ("req:ok:1:ABCDEFGH", "ok", 1, "abcdefgh"),
    ],
)
def test_request_callback_parses(data, name, request_id, code):
    assert _route("the card text", data) == request(name, request_id, code)


@pytest.mark.parametrize(
    "data",
    [
        "req:ok:7",
        "req:yes:7:abcdefgh",
        "req:ok:x:abcdefgh",
        "req:ok:7:abcd efg",
        "req:ok:7:abcdefgh:x",
        "req:ok:7:",
        "req::7:abcdefgh",
    ],
)
def test_malformed_request_callback_is_free(data):
    assert _route("idea text", data) == free(data)


def test_a_request_callback_wins_over_an_open_question():
    assert _route(
        "ignore", "req:ok:4:abcdefgh", open_question=True
    ) == request("ok", 4, "abcdefgh")


def test_empty_callback_falls_through_to_the_text():
    assert _route("Ship a local idea inbox", "") == capture("Ship a local idea inbox")
    assert _route("Ship a local idea inbox", None) == capture("Ship a local idea inbox")


def test_settings_parse_and_normalise_typos():
    text = "\n".join([
        "MODELS: claude, banana, grock",
        "passes: 2",
        "Final: cluade",
        "backup: agy",
        "timeout: 30m",
        "repo: AgentDock",
        "implementer: codx",
        "tester: claud",
        "reviewer: grok",
        "release: human",
        "drafter: claude",
        "plan_reviewer: antigravity",
    ])
    got = _route(text)
    assert got == settings({
        "models": Field(
            raw="claude, banana, grock",
            value=(
                AgentWord("claude", "claude"),
                AgentWord("banana", None),
                AgentWord("grock", "grok"),
            ),
        ),
        "passes": Field(raw="2", value=2),
        "final": Field(raw="cluade", value=AgentWord("cluade", "claude")),
        "backup": Field(raw="agy", value=(AgentWord("agy", "antigravity"),)),
        "timeout": Field(raw="30m", value="30"),
        "repo": Field(raw="AgentDock", value="AgentDock"),
        "implementer": Field(raw="codx", value=AgentWord("codx", "codex")),
        "tester": Field(raw="claud", value=AgentWord("claud", "claude")),
        "reviewer": Field(raw="grok", value=AgentWord("grok", "grok")),
        "release": Field(raw="human", value=AgentWord("human", "human")),
        "drafter": Field(raw="claude", value=AgentWord("claude", "claude")),
        "plan_reviewer": Field(
            raw="antigravity",
            value=AgentWord("antigravity", "antigravity"),
        ),
    })
    banana = got.fields["models"].value[1]
    assert banana == AgentWord("banana", None)
    assert banana.raw == "banana"


def test_banana_is_kept_when_it_is_the_only_model():
    got = _route("models: banana")
    assert got.kind == "settings"
    assert got.fields["models"].value == (AgentWord("banana", None),)


def test_backup_none_is_an_empty_list_and_the_word_is_kept():
    got = _route("backup: none")
    assert got.fields["backup"] == Field(raw="none", value=())


def test_release_human_is_not_an_unknown_agent():
    assert _route("release: Human").fields["release"] == Field(
        raw="Human",
        value=AgentWord("Human", "human"),
    )
    assert _route("release: grock").fields["release"] == Field(
        raw="grock",
        value=AgentWord("grock", "grok"),
    )
    assert _route("release: banana").fields["release"] == Field(
        raw="banana",
        value=AgentWord("banana", None),
    )


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("15", "15"),
        ("30", "30"),
        ("45", "45"),
        ("60", "60"),
        ("none", "none"),
        ("15m", "15"),
        ("30M", "30"),
        ("45m", "45"),
        ("60m", "60"),
        ("nonem", "none"),
        ("30 m", "30"),
        ("NONE", "none"),
        ("90", None),
        ("10", None),
        ("an hour", None),
    ],
)
def test_timeout_accepts_the_five_values_with_or_without_m(raw, value):
    got = _route(f"timeout: {raw}")
    assert got.kind == "settings"
    assert got.fields["timeout"] == Field(raw=raw, value=value)


def test_an_unaccepted_timeout_is_reported():
    got = _route("timeout: 90\nmodels: claude")
    assert got.kind == "settings"
    assert got.fields["timeout"] == Field(raw="90", value=None)
    assert got.fields["models"].value == (AgentWord("claude", "claude"),)


def test_a_colon_in_an_idea_is_not_settings():
    text = "Idea: a bot that files grocery receipts"
    assert _route(text) == capture(text)


def test_a_known_settings_key_mixed_with_an_unknown_one_is_free():
    text = "models: claude\ncolour: blue"
    assert _route(text) == free(text)


def test_duplicate_settings_key_keeps_the_later_value():
    got = _route("timeout: 15\ntimeout: 60m")
    assert got.fields["timeout"] == Field(raw="60m", value="60")


def test_blank_lines_do_not_stop_a_settings_message():
    got = _route("models: grok\n\npasses: 1\n")
    assert got.kind == "settings"
    assert got.fields["passes"] == Field(raw="1", value=1)


@pytest.mark.parametrize(
    ("word", "name"),
    [
        ("agy", "antigravity"),
        ("claud", "claude"),
        ("cluade", "claude"),
        ("codx", "codex"),
        ("grock", "grok"),
        ("Claude", "claude"),
        ("codex", "codex"),
        ("antigravity", "antigravity"),
        ("GROK", "grok"),
        ("gork", "grok"),
        ("grokk", "grok"),
        ("cladue", "claude"),
        ("banana", None),
        ("", None),
    ],
)
def test_normalise_agent(word, name):
    assert normalise_agent(word) == name


def test_agy_is_an_alias_because_the_fuzzy_cutoff_misses_it():
    assert difflib.get_close_matches("agy", AGENTS, n=1, cutoff=0.75) == []
    assert normalise_agent("agy") == "antigravity"


def test_exact_and_alias_win_before_the_fuzzy_pass(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("fuzzy match should not run")

    monkeypatch.setattr(difflib, "get_close_matches", fail)
    assert normalise_agent("claude") == "claude"
    assert normalise_agent("agy") == "antigravity"
    assert normalise_agent("claud") == "claude"
    assert normalise_agent("cluade") == "claude"
    assert normalise_agent("codx") == "codex"
    assert normalise_agent("grock") == "grok"


def test_fuzzy_agent_uses_the_spec_cutoff(monkeypatch):
    seen = {}
    real = difflib.get_close_matches

    def spy(word, possibilities, n=3, cutoff=0.6):
        seen["possibilities"] = tuple(possibilities)
        seen["cutoff"] = cutoff
        return real(word, possibilities, n=n, cutoff=cutoff)

    monkeypatch.setattr(difflib, "get_close_matches", spy)
    assert normalise_agent("gork") == "grok"
    assert seen["possibilities"] == AGENTS
    assert seen["cutoff"] == 0.75


def test_a_reply_to_an_open_question_is_an_answer():
    text = "Ship the ledger first, then the bot."
    assert _route(text, open_question=True) == answer(text)
    assert _route(text, open_question="What should I change?") == answer(text)


def test_an_open_question_does_not_swallow_a_button_or_a_command():
    assert _route("ignore", "drop:4:1", open_question=True) == action("drop", 4, 1)
    assert _route("/stop", open_question=True) == command("stop", ())
    assert _route("models: grok\ntimeout: 60", open_question=True).kind == "settings"


def test_an_instruction_while_a_question_is_open_is_the_answer():
    text = "use grok to implement and give it an hour"
    assert _route(text, open_question=True) == answer(text)


def test_plain_prose_is_capture():
    text = "Ship a local idea inbox that scores what I text it."
    assert _route(f"  {text}  ") == capture(text)
    longer = "Ship a local idea inbox.\nIt should score what I text it."
    assert _route(longer) == capture(longer)


def test_an_idea_that_mentions_an_agent_is_still_capture():
    text = "A notebook that syncs with the grok API."
    assert _route(text) == capture(text)


def test_prose_about_time_is_capture():
    text = "Give users an hour of offline maps."
    assert _route(text) == capture(text)


def test_the_word_code_does_not_make_prose_an_instruction():
    # "code" is within 0.75 of "codex". Prose must not use that fuzzy pass.
    assert normalise_agent("code") == "codex"
    text = "Use the code to implement a local ledger."
    assert _route(text) == capture(text)


def test_an_operational_instruction_is_free():
    text = "use grok to implement and give it an hour"
    assert _route(text) == free(text)
    assert _route("give it an hour") == free("give it an hour")
    assert _route("set the timeout to 30 minutes") == free("set the timeout to 30 minutes")
    assert _route("use grock to implement this") == free("use grock to implement this")


def test_a_blank_message_is_free():
    assert _route("   ") == free("")
    assert _route(None) == free("")
    assert _route("???", open_question=True) == free("???")


def test_a_lone_agent_name_is_free():
    assert _route("grok") == free("grok")
