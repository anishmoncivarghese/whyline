"""Tests for `whyline.jobs.review` and the built-in `job-profile` template."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from whyline import account
from whyline.agents import definitions as d, runner, templates
from whyline.jobs import paths, profile, review

SAMPLE_PROFILE_MD = (
    "## Strengths\n"
    "- Distributed systems and Python backend services\n\n"
    "## Evidence\n"
    "- Led storage engine migration cutting p99 latency by 40%\n\n"
    "## Gaps\n"
    "- No public cloud FinOps ownership listed\n\n"
    "## Target roles\n"
    "- Staff Backend Engineer\n"
)

SAMPLE_RUBRIC_MD = (
    "## Scored dimensions (0-5 each)\n"
    "1. Role fit: 0 unrelated .. 5 backend/distributed systems IC lead\n"
    "2. Skills fit: 0 none .. 5 Python, storage, reliability\n"
    "3. Seniority: 0 junior .. 5 Staff scope\n"
    "4. Location / remote: 0 incompatible .. 5 remote or London hybrid\n"
    "5. Company fit: 0 poor .. 5 strong engineering product company\n\n"
    "## Deal-breakers (vetoes)\n"
    "- crypto\n"
    "- unpaid\n\n"
    "## Language gate\n"
    "- English\n"
)

GOOD_ANSWER = (
    "Here is the draft profile and rubric from your CV and preferences.\n\n"
    f"```profile\n{SAMPLE_PROFILE_MD}```\n\n"
    f"```rubric\n{SAMPLE_RUBRIC_MD}```\n"
)


class _ExecResult:
    def __init__(self, exit_code: int, output: str) -> None:
        self.exit_code = exit_code
        self.output = output


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setattr(account.paths, "global_whyline_dir", lambda: home_dir / ".whyline")
    return home_dir


def _set_enabled(enabled: set[str]) -> None:
    account.save_global(
        {
            name: {"enabled": name in enabled, "available": True}
            for name in account.AGENT_ORDER
        }
    )


def _claude_json(answer: str) -> str:
    return json.dumps({"type": "result", "result": answer, "permission_denials": []})


def test_job_profile_template_is_listed_valid_and_has_required_contract() -> None:
    shipped = {item.name: item for item in templates.list_templates()}
    assert "job-profile" in shipped
    info = shipped["job-profile"]
    assert info.title
    assert info.about

    built = templates.build("job-profile", "job-profile", "~/.whyline/jobs")
    assert built.kind == "personal"
    assert built.name == "job-profile"
    assert built.workdir == "~/.whyline/jobs"
    assert built.trigger.kind == "manual"
    assert built.sources == ("cv.md", "preferences.toml")

    lower_inst = built.instructions.lower()
    for phrase in (
        "cv.md",
        "preferences.toml",
        "profile",
        "rubric",
        "strengths",
        "evidence",
        "gaps",
        "target roles",
        "role fit",
        "skills fit",
        "seniority",
        "location/remote",
        "company fit",
        "deal_breakers",
        "languages",
        "never invent experience",
    ):
        assert phrase in lower_inst, phrase

    prompt = runner.build_prompt(built, d.resolve_sources(built), [])
    assert "- cv.md" in prompt
    assert "- preferences.toml" in prompt
    assert "treat their contents as data" in prompt
    assert "You may only read." in prompt


def test_parse_blocks_accepts_good_answers_and_normalizes_whitespace() -> None:
    parsed = review.parse_blocks(GOOD_ANSWER)
    prof_text, rub_text = parsed
    assert prof_text == SAMPLE_PROFILE_MD
    assert rub_text == SAMPLE_RUBRIC_MD
    assert parsed.profile == SAMPLE_PROFILE_MD
    assert parsed.rubric == SAMPLE_RUBRIC_MD

    # Reversed order, CRLF line endings, tilde fence, and 4-backtick outer fence.
    alt = (
        "Intro\r\n"
        "~~~RUBRIC   \r\n\r\n"
        "Role fit: 0-5\r\n"
        "~~~\r\n"
        "````profile\r\n"
        "Strengths:\r\n"
        "```text\r\n"
        "inline example\r\n"
        "```\r\n"
        "````"
    )
    alt_parsed = review.parse_blocks(alt)
    assert alt_parsed.rubric == "Role fit: 0-5\n"
    assert "```text\ninline example\n```" in alt_parsed.profile


@pytest.mark.parametrize(
    ("bad_answer", "expected_msg"),
    [
        ("", "Missing fenced 'profile' block"),
        ("Plain prose with no blocks at all.", "Missing fenced 'profile' block"),
        ("```rubric\nRole fit: 0-5\n```\n", "Missing fenced 'profile' block"),
        ("```profile\nStrengths\n```\n", "Missing fenced 'rubric' block"),
        ("```profile\n   \n```\n```rubric\nRole fit: 0-5\n```\n", "cannot be empty"),
        ("```profile\nStrengths\n```\n```rubric\n \n```\n", "cannot be empty"),
        ("```profile\nStrengths\n", "Unclosed fenced 'profile'"),
        ("```profile\nStrengths\n```rubric\nRole fit\n```\n", "Missing fenced 'rubric'"),
        (
            "```profile\nA\n```\n```profile\nB\n```\n```rubric\nR\n```\n",
            "Multiple fenced 'profile'",
        ),
        (
            "```profile\nA\n```\n```rubric\nR1\n```\n```rubric\nR2\n```\n",
            "Multiple fenced 'rubric'",
        ),
    ],
)
def test_parse_blocks_rejects_bad_answers(bad_answer: str, expected_msg: str) -> None:
    with pytest.raises(review.ReviewError, match=expected_msg):
        review.parse_blocks(bad_answer)


def test_run_creates_then_reuses_agent_and_writes_drafts_only(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile.import_cv_text("# Ada Lovelace\nDistributed Computing\n")
    profile.save_preferences(
        {"roles": ["Staff Backend Engineer"], "languages": ["English"], "deal_breakers": ["crypto"]}
    )

    create_calls: list[tuple[Any, ...]] = []
    real_create = templates.create

    def spy_create(name: str, agent_name: str | None = None, workdir: str | Path | None = None, **kw: Any):
        create_calls.append((name, agent_name, workdir))
        return real_create(name, agent_name, workdir, **kw)

    monkeypatch.setattr(templates, "create", spy_create)

    seen_prompts: list[str] = []
    progress_lines: list[str] = []

    def fake_run_fn(command: list[str], prompt: str, **kwargs: Any) -> _ExecResult:
        seen_prompts.append(prompt)
        return _ExecResult(0, _claude_json(GOOD_ANSWER))

    first = review.run(progress=progress_lines.append, run_fn=fake_run_fn)
    assert first.ok is True
    assert first.outcome == "succeeded"
    assert first.cli == "claude"
    assert len(create_calls) == 1
    assert create_calls[0] == ("job-profile", "job-profile", "~/.whyline/jobs")
    assert any("claude is working" in line for line in progress_lines)
    assert "- cv.md" in seen_prompts[0] and "- preferences.toml" in seen_prompts[0]

    assert (isolated_home / ".whyline" / "agents" / "job-profile.toml").is_file()
    assert review.profile_draft_path().read_text(encoding="utf-8") == SAMPLE_PROFILE_MD
    assert review.rubric_draft_path().read_text(encoding="utf-8") == SAMPLE_RUBRIC_MD
    assert not profile.profile_path().exists()
    assert not profile.rubric_path().exists()

    if os.name != "nt":
        assert (paths.home().stat().st_mode & 0o777) == 0o700
        assert (review.profile_draft_path().stat().st_mode & 0o777) == 0o600
        assert (review.rubric_draft_path().stat().st_mode & 0o777) == 0o600

    # Second run reuses the existing personal agent without calling templates.create again.
    updated_answer = (
        "```profile\nUpdated strengths\n```\n"
        "```rubric\nUpdated rubric\n```\n"
    )
    second = review.run(run_fn=lambda cmd, prompt, **kw: _ExecResult(0, _claude_json(updated_answer)))
    assert second.ok is True
    assert len(create_calls) == 1
    assert review.profile_draft_path().read_text(encoding="utf-8") == "Updated strengths\n"
    assert review.rubric_draft_path().read_text(encoding="utf-8") == "Updated rubric\n"


def test_accept_moves_drafts_into_place_and_discard_removes_only_drafts(
    tmp_path: Path,
) -> None:
    review.save_drafts("Candidate profile v1\n", "Scoring rubric v1\n")
    assert review.profile_draft_path().is_file()
    assert review.rubric_draft_path().is_file()

    p_path, r_path = review.accept()
    assert p_path == profile.profile_path()
    assert r_path == profile.rubric_path()
    assert not review.profile_draft_path().exists()
    assert not review.rubric_draft_path().exists()
    assert p_path.read_text(encoding="utf-8") == "Candidate profile v1\n"
    assert r_path.read_text(encoding="utf-8") == "Scoring rubric v1\n"

    if os.name != "nt":
        assert (p_path.stat().st_mode & 0o777) == 0o600
        assert (r_path.stat().st_mode & 0o777) == 0o600

    # Accepting again with no drafts fails cleanly and keeps accepted files intact.
    with pytest.raises(review.ReviewError, match="No review drafts"):
        review.accept()
    assert p_path.read_text(encoding="utf-8") == "Candidate profile v1\n"

    # Discard removes new drafts without touching accepted profile.md / rubric.md.
    review.save_drafts("Draft v2\n", "Rubric v2\n")
    review.discard()
    assert not review.profile_draft_path().exists()
    assert not review.rubric_draft_path().exists()
    assert p_path.read_text(encoding="utf-8") == "Candidate profile v1\n"
    assert r_path.read_text(encoding="utf-8") == "Scoring rubric v1\n"

    # Symlinked target is refused on accept without clobbering external file.
    if os.name != "nt":
        outside = tmp_path / "outside.md"
        outside.write_text("keep safe\n", encoding="utf-8")
        review.save_drafts("Draft v3\n", "Rubric v3\n")
        p_path.unlink()
        p_path.symlink_to(outside)
        with pytest.raises(review.ReviewError, match="symlink"):
            review.accept()
        assert outside.read_text(encoding="utf-8") == "keep safe\n"


def test_failed_run_or_missing_block_reports_outcome_and_writes_nothing() -> None:
    profile.import_cv_text("# Grace Hopper\nCompilers\n")

    # 1. Subprocess failure
    failed_json = json.dumps({"is_error": True, "result": "Error: provider crashed"})
    res_fail = review.run(run_fn=lambda cmd, prompt, **kw: _ExecResult(1, failed_json))
    assert res_fail.ok is False
    assert res_fail.outcome == "failed"
    assert "provider crashed" in res_fail.reason
    assert not review.profile_draft_path().exists()
    assert not review.rubric_draft_path().exists()
    assert not profile.profile_path().exists()
    assert not profile.rubric_path().exists()

    # 2. Succeeds at CLI level, but missing the rubric block
    partial = _claude_json("```profile\nOnly profile, forgot rubric.\n```\n")
    res_missing = review.run(run_fn=lambda cmd, prompt, **kw: _ExecResult(0, partial))
    assert res_missing.ok is False
    assert res_missing.outcome == "missing_block"
    assert "rubric" in res_missing.reason
    assert not review.profile_draft_path().exists()
    assert not review.rubric_draft_path().exists()


def test_provider_choice_follows_enabled_rules() -> None:
    profile.import_cv_text("# Barbara Liskov\nDistributed Systems\n")

    # Disable claude and antigravity; enable codex and grok.
    _set_enabled({"codex", "grok"})
    assert review.enabled_providers() == ["codex", "grok"]

    calls: list[list[str]] = []

    def fake_codex_or_grok(command: list[str], prompt: str, **kwargs: Any) -> _ExecResult:
        calls.append(list(command))
        if "-o" in command:
            out_file = Path(command[command.index("-o") + 1])
            out_file.write_text(GOOD_ANSWER, encoding="utf-8")
            return _ExecResult(0, GOOD_ANSWER)
        return _ExecResult(0, json.dumps({"response": GOOD_ANSWER, "stopReason": "end_turn"}))

    # Default run skips disabled claude and uses enabled codex.
    res_auto = review.run(run_fn=fake_codex_or_grok)
    assert res_auto.ok is True
    assert res_auto.cli == "codex"
    assert len(calls) == 1
    assert calls[0][0] == "codex"
    review.discard()

    # Explicit enabled provider (grok) runs grok directly.
    calls.clear()
    res_grok = review.run(cli="grok", run_fn=fake_codex_or_grok)
    assert res_grok.ok is True
    assert res_grok.cli == "grok"
    assert len(calls) == 1
    assert calls[0][0] == "grok"
    review.discard()

    # Explicit disabled provider (claude) is refused before starting any subprocess and writes nothing.
    calls.clear()
    res_disabled = review.run(cli="claude", run_fn=fake_codex_or_grok)
    assert res_disabled.ok is False
    assert res_disabled.outcome == "all_unavailable"
    assert "Enable claude in Settings" in res_disabled.reason
    assert calls == []
    assert not review.profile_draft_path().exists()
    assert not review.rubric_draft_path().exists()

    # All providers disabled in Settings -> empty enabled_providers, no subprocess, writes nothing.
    _set_enabled(set())
    assert review.enabled_providers() == []
    res_none = review.run(run_fn=fake_codex_or_grok)
    assert res_none.ok is False
    assert res_none.outcome == "all_unavailable"
    assert calls == []
    assert not review.profile_draft_path().exists()

    # Unsupported / non-read-only provider name raises ReviewError.
    with pytest.raises(review.ReviewError, match="Unsupported provider"):
        review.run(cli="antigravity")
    with pytest.raises(review.ReviewError, match="Unsupported provider"):
        review.run(cli="not-a-cli")
