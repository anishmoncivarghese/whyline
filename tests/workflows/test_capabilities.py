from pathlib import Path

from whyline.workflows import capabilities
from whyline.workflows import definitions as d

EXAMPLE = '''
name = "pr-digest"
version = 1

[trigger]
kind = "weekdays"
at = "08:00"

[[step]]
id = "summarise"
type = "agent"
runner = "claude"
backup = ["codex"]
instructions = "Summarise these PRs."
output = "text"

[[step]]
id = "send"
type = "deliver"
to = "telegram"
text = "{{ steps.summarise.output }}"

[layout]
summarise = [0, 0]
send = [1, 0]
'''


def load(text: str = EXAMPLE) -> d.Workflow:
    return d.parse(text, kind="personal", path=Path("w.toml"))


def test_summary_lists_trigger_agent_and_delivery():
    assert capabilities.summary(load()) == [
        "Trigger: weekdays at 08:00",
        "Agent summarise: runs claude, codex",
        "Deliver send: sends to telegram",
    ]


def test_diff_after_adding_a_recipient():
    old = capabilities.summary(load())
    extra = EXAMPLE.replace(
        "[layout]",
        '[[step]]\nid = "copy"\ntype = "deliver"\nto = "email"\n'
        'email = "boss@example.com"\ntext = "hi"\n\n[layout]')
    new = capabilities.summary(load(extra))
    assert capabilities.diff(old, new) == ["+ Deliver copy: sends to email boss@example.com"]
    assert capabilities.diff(new, old) == ["- Deliver copy: sends to email boss@example.com"]
