from importlib import resources

import pytest

from whyline.sdlc.lenses import LENSES, lens_text, lenses_for, parse_findings

TABLE = [
    ("small", "spec", ["zoom-out", "readiness"]),
    ("small", "plan", ["readiness"]),
    ("feature", "brainstorm", ["zoom-out"]),
    ("feature", "prd", ["zoom-out", "comprehension"]),
    ("feature", "spec", ["comprehension", "codebase-fit", "design-critic"]),
    ("feature", "plan", ["readiness", "zoom-out"]),
    ("large", "brainstorm", ["zoom-out"]),
    ("large", "prd", ["zoom-out", "comprehension"]),
    ("large", "design", list(LENSES)),
    ("large", "plan", ["readiness", "zoom-out", "codebase-fit"]),
    ("small", "build-record", []),
    ("feature", "build-record", []),
    ("large", "build-record", []),
    ("small", "prd", []),
    ("small", "brainstorm", []),
    ("feature", "design", []),
    ("small", "design", []),
    ("large", "spec", []),
]


@pytest.mark.parametrize("size,kind,expected", TABLE)
def test_lenses_for(size, kind, expected):
    assert sorted(lenses_for(size, kind)) == sorted(expected)


def test_size_enum_accepted():
    from whyline.sdlc.docset import Size

    assert lenses_for(Size.SMALL, "plan") == ["readiness"]


def test_all_lenses_built_in_to_package():
    base = resources.files("whyline.sdlc")
    for name in LENSES:
        text = base.joinpath("lenses", f"{name}.md").read_text(encoding="utf-8")
        assert "No findings." in text
        assert "read-only" in text
        assert "[blocker|major|nit]" in text
    assert base.joinpath("lenses", "ATTRIBUTION.md").is_file()


def test_builtin_and_override(tmp_path):
    builtin = (
        resources.files("whyline.sdlc")
        .joinpath("lenses", "readiness.md")
        .read_text(encoding="utf-8")
    )
    assert lens_text(tmp_path, "readiness") == builtin
    d = tmp_path / ".whyline" / "sdlc" / "lenses"
    d.mkdir(parents=True)
    (d / "readiness.md").write_text("mine", encoding="utf-8")
    assert lens_text(tmp_path, "readiness") == "mine"
    assert lens_text(tmp_path, "zoom-out") != "mine"


def test_parse_three_severities():
    text = (
        "Intro chatter\n"
        "- [blocker] Goal — no goal — add one\n"
        "- [major] Steps — too many — split\n"
        "- [nit] Title — vague — rename\n"
    )
    found = parse_findings("zoom-out", text)
    assert [(f.severity, f.section, f.problem, f.fix) for f in found] == [
        ("blocker", "Goal", "no goal", "add one"),
        ("major", "Steps", "too many", "split"),
        ("nit", "Title", "vague", "rename"),
    ]
    assert all(f.lens == "zoom-out" for f in found)


def test_no_findings_and_chatter():
    assert parse_findings("x", "No findings.") == []
    assert parse_findings("x", "Looks fine to me, nothing to add.") is None
    assert parse_findings("x", "") is None


def test_fenced_lines_ignored():
    text = "```\n- [major] A — b — c\n```\n"
    assert parse_findings("x", text) is None
    text = "```\n- [major] A — b — c\n```\n- [nit] D — e — f\n"
    assert [f.section for f in parse_findings("x", text)] == ["D"]
