import json

import pytest

from whyline.ideas import report

# Independent of report.parse's walk, so a skipped field fails here.
FIELDS = (
    "title",
    "problem",
    "users",
    "usefulness",
    "complexity_mvp",
    "complexity_full",
    "verdict",
    "confidence",
    "existing",
    "sources",
    "deploy",
    "risks",
    "next_step",
)

SCORES = ("usefulness", "complexity_mvp", "complexity_full")


def _payload(**overrides):
    data = {
        "title": "Local idea inbox",
        "problem": "Ideas vanish before they are judged.",
        "users": "One person capturing ideas from their phone.",
        "usefulness": 7,
        "complexity_mvp": 4,
        "complexity_full": 8,
        "verdict": "YES",
        "confidence": "medium",
        "existing": [
            {
                "name": "Notion",
                "url": "https://notion.so",
                "how_it_differs": "A workspace, not a scored inbox tied to a planner.",
            }
        ],
        "sources": [{"url": "https://notion.so", "title": "Notion"}],
        "deploy": "On the user's Mac, beside Whyline.",
        "risks": ["The score is only as good as the pages the agent opened."],
        "next_step": "Ship capture and a single scored report.",
        "extra": "ignored",
    }
    data.update(overrides)
    return data


def _wrap(payload):
    return f"notes before\n```idea-report\n{json.dumps(payload)}\n```\nnotes after\n"


def test_valid_block_parses():
    parsed = report.parse(_wrap(_payload(usefulness=1, complexity_mvp=9)))
    assert parsed.title == "Local idea inbox"
    assert parsed.problem == "Ideas vanish before they are judged."
    assert parsed.users == "One person capturing ideas from their phone."
    assert parsed.usefulness == 1
    assert parsed.complexity_mvp == 9
    assert parsed.complexity_full == 8
    assert parsed.verdict == "YES"
    assert parsed.confidence == "medium"
    assert parsed.existing == (
        report.Existing(
            name="Notion",
            url="https://notion.so",
            how_it_differs="A workspace, not a scored inbox tied to a planner.",
        ),
    )
    assert parsed.sources == (report.Source(url="https://notion.so", title="Notion"),)
    assert parsed.deploy == "On the user's Mac, beside Whyline."
    assert parsed.risks == (
        "The score is only as good as the pages the agent opened.",
    )
    assert parsed.next_step == "Ship capture and a single scored report."


def test_last_of_two_blocks_wins():
    text = _wrap(_payload(title="First idea")) + _wrap(_payload(title="Later idea"))
    assert report.parse(text).title == "Later idea"


def test_last_block_is_the_one_validated():
    broken = "```idea-report\n{nope}\n```\n"
    with pytest.raises(report.ReportError, match="idea-report") as caught:
        report.parse(_wrap(_payload(title="Earlier idea")) + broken)
    assert caught.value.field == "idea-report"
    assert report.parse(broken + _wrap(_payload(title="The survivor"))).title == (
        "The survivor"
    )


def test_unclosed_tail_does_not_replace_a_closed_block():
    text = _wrap(_payload(title="Closed one")) + '```idea-report\n{"title": "cut"}\n'
    assert report.parse(text).title == "Closed one"


def test_json_fence_is_not_a_report():
    text = f"```json\n{json.dumps(_payload())}\n```\n"
    with pytest.raises(report.ReportError, match="idea-report") as caught:
        report.parse(text)
    assert caught.value.field == "idea-report"


@pytest.mark.parametrize("field", SCORES)
@pytest.mark.parametrize("value", [0, 10])
def test_out_of_range_score_names_the_field(field, value):
    with pytest.raises(report.ReportError, match=field) as caught:
        report.parse(_wrap(_payload(**{field: value})))
    assert caught.value.field == field


@pytest.mark.parametrize("value", [True, False, 7.0, "7"])
def test_non_integer_score_names_the_field(value):
    with pytest.raises(report.ReportError, match="usefulness") as caught:
        report.parse(_wrap(_payload(usefulness=value)))
    assert caught.value.field == "usefulness"


def test_unknown_verdict_names_the_field():
    with pytest.raises(report.ReportError, match="verdict") as caught:
        report.parse(_wrap(_payload(verdict="MAYBE")))
    assert caught.value.field == "verdict"


@pytest.mark.parametrize("field", FIELDS)
def test_missing_field_names_the_field(field):
    payload = _payload()
    del payload[field]
    with pytest.raises(report.ReportError, match=field) as caught:
        report.parse(_wrap(payload))
    assert caught.value.field == field


def test_first_bad_field_follows_contract_order():
    payload = _payload(usefulness=0, verdict="MAYBE")
    del payload["title"]
    with pytest.raises(report.ReportError) as caught:
        report.parse(_wrap(payload))
    assert caught.value.field == "title"


def test_title_length_boundary():
    assert report.parse(_wrap(_payload(title=" " + ("a" * 80) + " "))).title == "a" * 80
    with pytest.raises(report.ReportError, match="title") as caught:
        report.parse(_wrap(_payload(title="a" * 81)))
    assert caught.value.field == "title"


@pytest.mark.parametrize("verdict", ["YES", "NO", "NOT YET"])
def test_each_verdict_parses(verdict):
    assert report.parse(_wrap(_payload(verdict=verdict))).verdict == verdict


def test_empty_existing_is_allowed_when_sources_were_checked():
    parsed = report.parse(_wrap(_payload(existing=[])))
    assert parsed.existing == ()
    assert parsed.confidence == "medium"


def test_empty_existing_and_sources_names_existing():
    with pytest.raises(report.ReportError, match="existing") as caught:
        report.parse(_wrap(_payload(existing=[], sources=[])))
    assert caught.value.field == "existing"


def test_no_sources_forces_low_confidence():
    parsed = report.parse(
        _wrap(_payload(sources=[], confidence="high", risks=["A real risk."]))
    )
    assert parsed.confidence == "low"
    assert parsed.risks == ("A real risk.", "no sources were checked")


def test_no_sources_risk_is_not_duplicated():
    parsed = report.parse(
        _wrap(
            _payload(
                sources=[],
                confidence="medium",
                risks=["no sources were checked", "A second risk."],
            )
        )
    )
    assert parsed.confidence == "low"
    assert parsed.risks == ("no sources were checked", "A second risk.")


def test_rendered_report_quotes_the_original_text():
    original = "A bot that scores ideas from Telegram."
    parsed = report.parse(_wrap(_payload()))
    text = report.render_markdown(parsed, original)
    assert text.startswith(f"> {original}\n")
    assert "Sources checked" in text
    assert parsed.sources[0].title in text
    assert parsed.sources[0].url in text
    assert text.index(original) < text.index("Sources checked")


def test_rendered_report_quotes_each_line():
    original = "First line.\n\nSecond line."
    text = report.render_markdown(report.parse(_wrap(_payload())), original)
    assert text.startswith("> First line.\n>\n> Second line.\n")


def test_rubric_defines_every_band_for_both_scales():
    assert report.RUBRIC_VERSION == 1
    lowered = report.RUBRIC.lower()
    assert "usefulness" in lowered
    assert "complexity" in lowered
    for number in range(1, 10):
        assert lowered.count(f"\n{number}.") == 2
