from __future__ import annotations

import pytest

from whyline.workflows.expr import TemplateError, references, render, value

CTX = {
    "trigger": {"name": "  Ada  ", "tags": ["a", "b", "c"], "empty": [], "n": 3},
    "inputs": {"flag": True},
    "steps": {"s1": {"items": [{"id": 7}, {"id": 8}]}},
    "run": {"id": "r1"},
}


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{{ trigger.name | trim }}", "Ada"),
        ("{{ trigger.name | trim | lower }}", "ada"),
        ("{{ trigger.name | trim | upper }}", "ADA"),
        ("{{ trigger.tags | length }}", "3"),
        ("{{ trigger.name | length }}", "7"),
        ("{{ trigger.tags | first }}", "a"),
        ('{{ trigger.tags | join(", ") }}', "a, b, c"),
        ("{{ trigger.tags | json }}", '["a", "b", "c"]'),
        ('{{ trigger.nope | default("x") }}', "x"),
        ("{{trigger.n}}", "3"),
        ("{{ inputs.flag }}", "true"),
        ("id={{ steps.s1.items.1.id }}!", "id=8!"),
        ("{{ run.id }}-{{ run.id }}", "r1-r1"),
        ("no tags, a lone } and {", "no tags, a lone } and {"),
        ('{{ trigger.tags | join("}}") }}', "a}}b}}c"),
    ],
)
def test_render(template, expected):
    assert render(template, CTX) == expected


def test_whole_template_keeps_type():
    assert value("{{ trigger.n }}", CTX) == 3
    assert value("{{ trigger.tags }}", CTX) == ["a", "b", "c"]
    assert value("{{ inputs.flag }}", CTX) is True
    assert value("{{ trigger.tags | length }}", CTX) == 3
    assert value("n={{ trigger.n }}", CTX) == "n=3"
    assert value("{{ trigger.n }} ", CTX) == "3 "


def test_missing_path_errors():
    with pytest.raises(TemplateError, match=r"trigger\.nope is not available"):
        render("{{ trigger.nope }}", CTX)
    with pytest.raises(TemplateError, match=r"trigger\.tags\.9 is not available"):
        render("{{ trigger.tags.9 }}", CTX)
    with pytest.raises(TemplateError, match=r"trigger\.nope is not available"):
        render("{{ trigger.nope | upper }}", CTX)
    with pytest.raises(TemplateError, match="is empty"):
        render("{{ trigger.empty | first }}", CTX)


def test_default_only_replaces_missing():
    assert value('{{ trigger.nope | default("x") | upper }}', CTX) == "X"
    assert value('{{ trigger.n | default("x") }}', CTX) == 3


@pytest.mark.parametrize(
    "template",
    [
        "{{ trigger.__class__ }}",
        "{{ _private }}",
        "{{ trigger.name.upper() }}",
        "{{ trigger.name | upper() }}",
        '{{ trigger["name"] }}',
        '{{ trigger[ "x" ] }}',
        "{{ trigger.tags[0] }}",
        "{{ 1 + 2 }}",
        "{{ trigger.n * 2 }}",
        "{{ trigger.n - 1 }}",
        "{% if x %}y{% endif %}",
        "a {% for x in y %}",
        "{{ trigger.name | nope }}",
        "{{ trigger.name | join }}",
        "{{ trigger.tags | join(',') }}",
        '{{ trigger.tags | join("a", "b") }}',
        "{{ trigger. }}",
        "{{ }}",
        "{{ trigger.name",
        '{{ trigger.name | default("x }}',
        "{{ trigger.1x }}",
    ],
)
def test_refused(template):
    with pytest.raises(TemplateError):
        render(template, CTX)
    with pytest.raises(TemplateError):
        references(template)


def test_error_names_position():
    with pytest.raises(TemplateError, match="position 15"):
        render("abc {{ a }} {{ trigger.__x }}", CTX)


def test_references():
    template = '{{ trigger.name | trim }} and {{ steps.s1.items.0.id }} {{ trigger.name | default("") }}'
    assert references(template) == ["trigger.name", "steps.s1.items.0.id"]
    assert references("plain") == []


def test_large_string_renders():
    big = "x" * (1024 * 1024)
    assert render(big, CTX) == big
    assert render(big + "{{ run.id }}" + big, CTX) == big + "r1" + big
    assert render("{{ s | length }}", {"s": big}) == str(len(big))
    many = "{{ run.id }}" * 20000
    assert render(many, CTX) == "r1" * 20000
