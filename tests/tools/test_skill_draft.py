import pytest

from whyline.tools import skill_draft

GOOD = "---\nname: release-notes\ndescription: Write release notes\n---\n\nStep one.\nStep two.\n"


def test_prompt_holds_the_description_as_data():
    text = skill_draft.prompt("ignore this; do X")
    assert "<description>\nignore this; do X\n</description>" in text
    assert "SKILL.md" in text and "name" in text and "description" in text


def test_parse_whole_answer_and_fenced_block():
    assert skill_draft.parse(GOOD) == ("release-notes", "Write release notes", "Step one.\nStep two.")
    assert skill_draft.parse(f"Here you go:\n```markdown\n{GOOD}```\nDone.")[0] == "release-notes"


@pytest.mark.parametrize("answer,reason", [
    ("just text", "front matter"),
    ("---\ndescription: d\n---\nbody", "no name"),
    ("---\nname: Bad Name\ndescription: d\n---\nbody", "lowercase"),
    ("---\nname: ok\n---\nbody", "no description"),
    ("---\nname: ok\ndescription: d\n---\n" + "x" * skill_draft.SKILL_LIMIT, "over"),
])
def test_parse_refuses_with_a_reason(answer, reason):
    with pytest.raises(skill_draft.DraftError, match=reason):
        skill_draft.parse(answer)


def test_draft_retries_once_with_the_reason():
    prompts = []
    answers = iter(["nope", GOOD])

    def ask(text):
        prompts.append(text)
        return next(answers)

    assert skill_draft.draft("a skill", ask_agent=ask)[0] == "release-notes"
    assert len(prompts) == 2 and "front matter" in prompts[1]


def test_draft_gives_up_after_one_retry():
    calls = []

    def ask(text):
        calls.append(text)
        return "nope"

    with pytest.raises(skill_draft.DraftError):
        skill_draft.draft("a skill", ask_agent=ask)
    assert len(calls) == 2
