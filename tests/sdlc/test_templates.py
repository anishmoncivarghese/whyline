from __future__ import annotations

from importlib import resources

import pytest

from whyline.sdlc import templates
from whyline.sdlc.docset import Size

RULE = 'Fill every section. Write "Not applicable — <reason>" rather than dropping one. No filler.'
NAMES = ["prd", "spec", "short-spec", "design", "build-record"]


@pytest.mark.parametrize("kind", ["prd", "spec", "design", "build-record"])
@pytest.mark.parametrize("size", ["small", "feature", "large"])
def test_every_kind_resolves(tmp_path, kind, size):
    text = templates.template_for(tmp_path, kind, size)
    assert text.startswith(RULE)
    assert templates.sections(text)


def test_small_spec_uses_short_spec(tmp_path):
    small = templates.template_for(tmp_path, "spec", "small")
    assert templates.sections(small) == ["What changes", "Why", "Files", "Testing", "Risks"]
    assert templates.template_for(tmp_path, "spec", Size.SMALL) == small
    assert "Approach" in templates.sections(templates.template_for(tmp_path, "spec", "feature"))


def test_unknown_kind_raises(tmp_path):
    with pytest.raises(ValueError):
        templates.template_for(tmp_path, "nope", "feature")


def test_override_wins(tmp_path):
    d = tmp_path / ".whyline" / "sdlc" / "templates"
    d.mkdir(parents=True)
    (d / "spec.md").write_text("## Mine\n", encoding="utf-8")
    assert templates.template_for(tmp_path, "spec", "feature") == "## Mine\n"
    assert templates.sections(templates.template_for(tmp_path, "spec", "small"))[0] == "What changes"


@pytest.mark.parametrize("name", NAMES)
def test_builtins_are_packaged_and_complete(name):
    path = resources.files("whyline.sdlc").joinpath("templates", f"{name}.md")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith(RULE)
    # Every heading is followed by a one-line description.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            assert lines[i + 1].strip()


def test_sections_ignores_fenced_code():
    text = "## One\n```\n## Not this\n```\n## Two\n~~~\n## Nor this\n~~~\n### Sub\n## Three ##\n"
    assert templates.sections(text) == ["One", "Two", "Three"]
