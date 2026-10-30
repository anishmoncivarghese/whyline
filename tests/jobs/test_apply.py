"""Tests for `whyline.jobs.apply` and the `job-apply` template."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from whyline import account, cli
from whyline.agents import definitions as d, runner, templates
from whyline.jobs import apply, fetch, paths, tracker

ANSWER = """## Tailored CV summary
Backend engineer with Python and Postgres evidence.

## CV bullet edits
- Built billing APIs (Acme).

## Cover letter
Dear hiring team, I would like to join.

## Gaps (not added)
- Kubernetes
"""

FOLDER = "acme-corp_senior-engineer"


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
    account.save_global(
        {name: {"enabled": name == "claude", "available": True} for name in account.AGENT_ORDER}
    )

    def no_board(*_a: object, **_k: object) -> list:
        raise fetch.FetchError("offline")

    monkeypatch.setattr(fetch, "board_jobs", no_board)
    return home_dir


@pytest.fixture
def job() -> dict:
    conn = tracker.connect()
    with conn:
        conn.execute(
            "INSERT INTO tracked (uid, company, title, url, score, verdict, reason, status,"
            " updated_at) VALUES ('u1', 'Acme Corp', 'Senior Engineer', 'https://acme.example/1',"
            " 20, 'shortlist', 'Strong fit', 'shortlisted', '2026-10-30T00:00:00+00:00')"
        )
    conn.close()
    return tracker.list_rows()[0]


def _ok(answer: str = ANSWER):
    def run_fn(argv, prompt, **kwargs):
        run_fn.prompt = prompt
        payload = {"type": "result", "result": answer, "permission_denials": []}
        return _ExecResult(0, json.dumps(payload))

    return run_fn


def test_template_contract_and_prompt() -> None:
    built = templates.build("job-apply", "job-apply", "~/.whyline/jobs")
    assert built.trigger.kind == "manual"
    assert built.sources == ("cv.md", "profile.md", "preferences.toml")
    text = built.instructions.lower()
    for phrase in ("350 words", "gaps (not added)", "never invent", "rephrase or reorder"):
        assert phrase in text, phrase
    assert "- cv.md" in runner.build_prompt(built, d.resolve_sources(built), [])


def test_draft_writes_the_folder_layout_docx_and_note(job: dict) -> None:
    fn = _ok()
    res = apply.draft("u1", run_fn=fn)
    assert res.ok, res.reason
    folder = paths.configured_home() / "applications" / FOLDER
    assert res.folder == folder
    assert sorted(p.name for p in folder.iterdir()) == ["draft.docx", "draft.md", "posting.md"]
    assert "Gaps (not added)" in (folder / "draft.md").read_text(encoding="utf-8")
    assert "Senior Engineer" in (folder / "posting.md").read_text(encoding="utf-8")
    assert f"applications/{FOLDER}/posting.md" in fn.prompt
    with zipfile.ZipFile(folder / "draft.docx") as archive:
        assert b"Kubernetes" in archive.read("word/document.xml")
    row = tracker.list_rows()[0]
    assert row["notes"] == "draft ready"
    assert row["status"] == "shortlisted"


def test_draft_by_row_number(job: dict) -> None:
    assert apply.draft(str(job["row"]), run_fn=_ok()).ok


def test_failed_run_writes_no_draft(job: dict) -> None:
    def broken(argv, prompt, **kwargs):
        return _ExecResult(1, "boom")

    res = apply.draft("u1", run_fn=broken)
    assert not res.ok
    folder = paths.configured_home() / "applications" / FOLDER
    assert not (folder / "draft.md").exists()
    assert not (folder / "draft.docx").exists()
    assert tracker.list_rows()[0]["notes"] == ""


def test_answer_without_gaps_section_writes_no_draft(job: dict) -> None:
    res = apply.draft("u1", run_fn=_ok("## Cover letter\nHello"))
    assert not res.ok and res.outcome == "malformed_answer"
    folder = paths.configured_home() / "applications" / FOLDER
    assert not (folder / "draft.md").exists()


def test_unknown_job_raises(job: dict) -> None:
    with pytest.raises(apply.ApplyError):
        apply.draft("nope", run_fn=_ok())


def test_cli_draft(
    job: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original = apply.draft
    monkeypatch.setattr(
        apply, "draft", lambda ref, cli=None, **kw: original(ref, cli, run_fn=_ok(), **kw)
    )
    assert cli.main(["jobs", "draft", "u1"]) == 0
    out = capsys.readouterr().out
    assert "draft.md" in out and "draft.docx" in out
    assert cli.main(["jobs", "draft", "missing"]) == 1
    assert "No tracked job" in capsys.readouterr().err


def _enable(*names: str) -> None:
    account.save_global(
        {name: {"enabled": name in names, "available": True} for name in account.AGENT_ORDER}
    )


def _two_turn(calls: list):
    """claude drafts and revises, codex reviews; records (argv[0], prompt) per turn."""

    def run_fn(argv, prompt, **kwargs):
        calls.append((argv[0], prompt))
        if argv[0] == "codex":
            text = "1. [Tone] Too stiff."
        elif any(c == "codex" for c, _p in calls):
            text = ANSWER.replace("Kubernetes", "Kafka")
        else:
            text = ANSWER
        payload = {"type": "result", "result": text, "permission_denials": []}
        return _ExecResult(0, json.dumps(payload))

    return run_fn


def test_pick_reviewer_skips_drafter_and_disabled() -> None:
    chain = ["claude", "codex", "grok"]

    def yes(_c: str) -> bool:
        return True

    assert apply.pick_reviewer(chain, "claude", ["claude", "codex", "grok"], yes) == "codex"
    assert apply.pick_reviewer(chain, "claude", ["claude", "grok"], yes) == "grok"
    assert apply.pick_reviewer(chain, "claude", ["claude"], yes) is None
    assert apply.pick_reviewer(chain, "claude", ["claude", "codex"], lambda c: c != "codex") is None


def test_no_second_provider_skips_with_note(job: dict) -> None:
    res = apply.draft("u1", run_fn=_ok(), unattended_fn=lambda _c: True)
    assert res.ok and res.review_note == "No second provider for review"
    folder = paths.configured_home() / "applications" / FOLDER
    assert not (folder / "review.md").exists() and not (folder / "final.md").exists()


def test_disabled_provider_never_reviews(job: dict) -> None:
    _enable("claude", "grok")
    calls: list = []
    res = apply.draft("u1", run_fn=_two_turn(calls), unattended_fn=lambda c: c != "grok")
    assert res.review_note == "No second provider for review"
    assert all(cmd != "codex" for cmd, _p in calls)


def test_review_uses_other_provider_and_writes_final_files(job: dict) -> None:
    _enable("claude", "codex")
    calls: list = []
    res = apply.draft("u1", run_fn=_two_turn(calls), unattended_fn=lambda _c: True)
    assert res.ok, res.reason
    assert [cmd for cmd, _p in calls] == ["claude", "codex", "claude"]
    assert res.reviewer == "codex" and res.reviewer != res.cli
    assert "draft.md" in calls[1][1] and "cv.md" in calls[1][1]
    assert "Too stiff" in calls[2][1]
    folder = paths.configured_home() / "applications" / FOLDER
    assert "Too stiff" in (folder / "review.md").read_text(encoding="utf-8")
    assert "Kafka" in (folder / "final.md").read_text(encoding="utf-8")
    assert "Kubernetes" in (folder / "draft.md").read_text(encoding="utf-8")
    with zipfile.ZipFile(folder / "final.docx") as archive:
        assert b"Kafka" in archive.read("word/document.xml")
