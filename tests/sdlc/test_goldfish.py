from __future__ import annotations

from types import SimpleNamespace

import pytest

from whyline.relaychat import agent_choice, ask
from whyline.sdlc import docset as docset_mod
from whyline.sdlc import goldfish, guard, lenses, workspace
from whyline.sdlc.docset import DocSetError

REQUEST = "SECRET-REQUEST build a trading journal"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    docs = tmp_path / "docs-root"
    docs.mkdir()
    monkeypatch.setattr(workspace, "docs_root", lambda root: docs)
    monkeypatch.setattr(guard, "docs_root", lambda root: docs)
    monkeypatch.setattr(guard, "check", lambda root: None)
    monkeypatch.setattr(agent_choice, "choices", lambda repo: ["claude", "codex"])
    monkeypatch.setattr(ask, "command", lambda repo, cli: [cli, "--read-only"])
    monkeypatch.setattr(ask, "extract", lambda repo, cli, raw, f: raw)
    monkeypatch.setattr("whyline.agents.runner._adapter", lambda defn, cli: None)
    found = docset_mod.create(docs, "Journal", "feature", "human",
                              prd_mode="new", roles={"writer": "claude"})
    found.description = REQUEST
    docset_mod.save(docs, found)
    docset_mod.add_version(docs, found, "prd", "# PRD\nbody\n", author="claude", note="n")
    docset_mod.approve(docs, found, "prd", approver="human")
    docset_mod.add_version(docs, found, "spec", "# Spec\nbody\n", author="claude", note="n")
    docset_mod.log_review(docs, found, "spec", actor="human", action="changes requested",
                          comment="EARLIER-REVIEW-COMMENT")
    (docs / "docs/sdlc" / found.slug / "reviews").mkdir(parents=True, exist_ok=True)
    (docs / "docs/sdlc" / found.slug / "reviews" / "spec-v0.md").write_text(
        "EARLIER-REVIEW-TEXT", encoding="utf-8")
    return SimpleNamespace(root=tmp_path, docs=docs, found=found)


def _runner(replies, seen):
    """replies: lens-name -> list of reply texts (or Exception / exit code tuple)."""
    counts: dict[str, int] = {}

    def run(command, text, **kwargs):
        seen.append((command, text, kwargs))
        lens = next(name for name in lenses.LENSES if lenses.lens_text(None_root, name)[:60] in text)
        at = counts.get(lens, 0)
        counts[lens] = at + 1
        queue = replies.get(lens, ["No findings."])
        reply = queue[min(at, len(queue) - 1)]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, tuple):
            return SimpleNamespace(exit_code=reply[0], output=reply[1])
        return SimpleNamespace(exit_code=0, output=reply)

    return run


None_root = None


def _review(setup, replies, seen, **kwargs):
    global None_root
    None_root = setup.root
    return goldfish.review_document(
        setup.root, setup.found, "spec", agent=kwargs.pop("agent", "codex"),
        progress=lambda msg: None, run_fn=_runner(replies, seen), **kwargs)


def test_prompt_holds_only_the_allowed_parts(setup):
    seen = []
    _review(setup, {}, seen)
    assert len(seen) == 3
    for command, text, kwargs in seen:
        assert "docs/sdlc/journal/spec.md" in text and "version 1" in text
        assert "docs/sdlc/journal/prd.md" in text
        assert goldfish.CODE_LINE in text
        for banned in (REQUEST, "EARLIER-REVIEW", "changes requested"):
            assert banned not in text
        assert "--resume" not in command
        assert kwargs["cwd"] == setup.docs


def test_one_process_per_lens_each_in_its_own_folder(setup):
    seen = []
    _review(setup, {}, seen)
    folders = {kwargs["log_path"].parent for _, _, kwargs in seen}
    assert len(folders) == 3


def test_configured_resume_is_stripped_from_the_review_command(setup, monkeypatch):
    monkeypatch.setattr(
        ask, "command",
        lambda repo, cli: [cli, "--resume", "abc", "--read-only", "--resume=def", "--continue"])
    seen = []
    _review(setup, {}, seen)
    assert seen
    for command, _, _ in seen:
        assert command == ["claude", "--read-only"] or command[1:] == ["--read-only"]
        assert not any("resume" in part or part == "--continue" for part in command)


def test_failed_lens_is_retried_once_then_listed_as_not_run(setup):
    seen = []
    review = _review(setup, {"codebase-fit": [(1, "boom")], "comprehension": ["garbage text"]}, seen)
    assert sorted(review.not_run) == ["codebase-fit", "comprehension"]
    assert len(seen) == 2 + 2 + 1
    first = review.path.read_text(encoding="utf-8").splitlines()[0]
    assert "Not run: comprehension, codebase-fit" in first
    assert first.startswith("Blockers: 0 · Major: 0 · Nits: 0")


def test_retry_that_answers_counts(setup):
    seen = []
    ok = "- [major] Goals — vague — name one"
    review = _review(setup, {"design-critic": [RuntimeError("x"), ok]}, seen)
    assert review.not_run == []
    assert [f.severity for f in review.findings] == ["major"]


def test_read_only_cancel_twice_is_not_run(setup, monkeypatch):
    monkeypatch.setattr(ask, "cancelled_turn", lambda cli, raw: raw == "CANCELLED")
    seen = []
    review = _review(setup, {"comprehension": ["CANCELLED"]}, seen)
    assert review.not_run == ["comprehension"]


def test_report_first_line_grouping_and_merge(setup):
    seen = []
    replies = {
        "comprehension": ["- [major] Goals — Too vague — name one\n- [nit] Title — Long — shorten"],
        "codebase-fit": ["- [blocker] Data — Missing table — add it\n- [major] goals — too VAGUE — name one"],
    }
    review = _review(setup, replies, seen)
    text = review.path.read_text(encoding="utf-8")
    assert review.path == setup.docs / "docs/sdlc/journal/reviews/spec-v1.md"
    lines = text.splitlines()
    assert lines[0] == ("Blockers: 1 · Major: 1 · Nits: 1 · Not run: none · Reviewer: codex")
    assert text.index("## Blockers") < text.index("## Major") < text.index("## Nits")
    assert text.count("Too vague") == 1
    assert "(lenses: comprehension, codebase-fit)" in text
    log = (setup.docs / "docs/sdlc/journal/review-log.md").read_text(encoding="utf-8")
    assert "fresh review · codex" in log and lines[0] in log

    back = goldfish.latest_review(setup.root, setup.found, "spec")
    assert back.agent == "codex" and back.not_run == []
    assert len(back.findings) == 3
    assert goldfish.latest_review(setup.root, setup.found, "plan") is None


def test_writer_is_swapped_for_another_read_only_agent(setup):
    seen = []
    review = _review(setup, {}, seen, agent="claude")
    assert review.agent == "codex"
    assert all(command[0] == "codex" for command, _, _ in seen)
    assert goldfish.WRITER_NOTE not in review.path.read_text(encoding="utf-8")


def test_writer_reviews_when_no_other_agent_is_installed(setup, monkeypatch):
    monkeypatch.setattr(agent_choice, "choices", lambda repo: ["claude"])
    seen = []
    review = _review(setup, {}, seen, agent="claude")
    assert review.agent == "claude"
    assert goldfish.WRITER_NOTE in review.path.read_text(encoding="utf-8")


def test_agent_without_read_only_mode_is_refused(setup):
    with pytest.raises(DocSetError):
        _review(setup, {}, [], agent="grok")


def test_guard_refusal_stops_before_any_process(setup, monkeypatch):
    monkeypatch.setattr(guard, "check", lambda root: "A relay is running.")
    seen = []
    with pytest.raises(DocSetError, match="A relay is running."):
        _review(setup, {}, seen)
    assert seen == []


def test_prd_update_prompt_has_a_diff_and_the_judging_line(setup, monkeypatch):
    from types import SimpleNamespace as NS

    setup.found.prd_mode = "update"
    monkeypatch.setattr(
        goldfish.product, "current",
        lambda docs: NS(version="1.0", text="<!-- product-prd v1.0 -->\n# PRD\nold line\n"))
    monkeypatch.setattr(lenses, "lenses_for", lambda size, kind: ["zoom-out"])
    seen = []
    global None_root
    None_root = setup.root
    goldfish.review_document(setup.root, setup.found, "prd", agent="codex",
                             progress=lambda m: None, run_fn=_runner({}, seen))
    text = seen[0][1]
    assert "-old line" in text and "+body" in text
    assert goldfish.PRD_DIFF_LINE in text
