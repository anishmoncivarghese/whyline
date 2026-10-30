"""Tests for `whyline.jobs.apply.interview` and the `job-interview` template."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from whyline import account, cli
from whyline.agents import templates
from whyline.jobs import apply, fetch, paths, tracker

ANSWER = """## Likely questions
### Tell me about a hard migration
- Situation: billing ran on a legacy system (Acme).
- Task: move it.
- Action: wrote the migration.
- Result: no downtime.

## Questions to ask
- How does the team ship?

## Gaps to prepare
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


def _insert(status: str) -> dict:
    conn = tracker.connect()
    with conn:
        conn.execute(
            "INSERT INTO tracked (uid, company, title, url, score, verdict, reason, status,"
            " updated_at) VALUES ('u1', 'Acme Corp', 'Senior Engineer', 'https://acme.example/1',"
            " 20, 'shortlist', 'Strong fit', ?, '2026-10-30T00:00:00+00:00')",
            (status,),
        )
    conn.close()
    return tracker.list_rows()[0]


@pytest.fixture
def job() -> dict:
    return _insert("interview")


def _ok(answer: str = ANSWER):
    def run_fn(argv, prompt, **kwargs):
        run_fn.prompt = prompt
        payload = {"type": "result", "result": answer, "permission_denials": []}
        return _ExecResult(0, json.dumps(payload))

    return run_fn


def test_template_contract_and_prompt() -> None:
    built = templates.build("job-interview", "job-interview", "~/.whyline/jobs")
    assert built.trigger.kind == "manual"
    assert built.sources == ("cv.md", "profile.md", "preferences.toml")
    text = built.instructions.lower()
    for phrase in ("star", "only on evidence in `cv.md`", "questions to ask", "gaps to prepare"):
        assert phrase in text, phrase


def test_interview_writes_markdown_and_docx_in_the_application_folder(job: dict) -> None:
    fn = _ok()
    res = apply.interview("u1", run_fn=fn)
    assert res.ok, res.reason
    folder = paths.configured_home() / "applications" / FOLDER
    assert res.folder == folder
    assert sorted(p.name for p in folder.iterdir()) == [
        "interview.docx", "interview.md", "posting.md",
    ]
    assert "Gaps to prepare" in (folder / "interview.md").read_text(encoding="utf-8")
    assert f"applications/{FOLDER}/posting.md" in fn.prompt
    with zipfile.ZipFile(folder / "interview.docx") as archive:
        assert b"Kubernetes" in archive.read("word/document.xml")


def test_interview_by_row_number(job: dict) -> None:
    assert apply.interview(str(job["row"]), run_fn=_ok()).ok


def test_job_not_in_interview_status_is_refused_with_a_plain_message() -> None:
    _insert("shortlisted")
    fn = _ok()
    with pytest.raises(apply.ApplyError) as caught:
        apply.interview("u1", run_fn=fn)
    assert "is shortlisted, not interview" in str(caught.value)
    assert not (paths.configured_home() / "applications").exists()
    assert not hasattr(fn, "prompt")


def test_answer_missing_a_section_writes_nothing(job: dict) -> None:
    res = apply.interview("u1", run_fn=_ok("## Likely questions\nOnly this.\n"))
    assert not res.ok
    assert res.outcome == "malformed_answer"
    folder = paths.configured_home() / "applications" / FOLDER
    assert not (folder / "interview.md").exists()


def test_cli_refuses_other_status_and_writes_files(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _insert("applied")
    assert cli.main(["jobs", "interview", "u1"]) != 0
    assert "not interview" in capsys.readouterr().err

    conn = tracker.connect()
    with conn:
        conn.execute("UPDATE tracked SET status = 'interview'")
    conn.close()
    real = apply.interview
    monkeypatch.setattr(
        apply, "interview", lambda ref, cli_name=None, **kw: real(ref, cli_name, run_fn=_ok(), **kw)
    )
    assert cli.main(["jobs", "interview", "u1"]) == 0
    out = capsys.readouterr().out
    assert "interview.md" in out and "interview.docx" in out


@pytest.mark.asyncio
async def test_console_button_calls_apply_interview(tmp_path: Path) -> None:
    pytest.importorskip("textual")
    from whyline.console import tui
    from whyline.console.jobs_screens import JobsHomeScreen

    if not tui.TUI_AVAILABLE:
        pytest.skip("textual not installed")

    calls: list[str] = []
    done = tmp_path / "applications" / "acme_role"

    def interview_fn(ref: str, progress: Any = None) -> Any:
        calls.append(ref)

        class _Res:
            ok = True
            folder = done

        return _Res()

    jobs = [{
        "row": 1, "uid": "u1", "company": "Acme", "title": "Role", "status": "interview",
        "score": 20, "url": "https://acme.example/1", "notes": "",
    }]

    class _Host(tui.App):
        def compose(self):
            yield tui.Static("host")

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = JobsHomeScreen(jobs_list_fn=lambda **_: jobs, interview_fn=interview_fn)
        app.push_screen(screen)
        await pilot.pause()
        open_btn = screen.query_one("#jh-jobs-open-folder", tui.Button)
        screen.query_one("#jh-jobs-interview", tui.Button).press()
        for _ in range(300):
            await pilot.pause()
            if not open_btn.disabled:
                break
            await pilot.pause(0.01)
        assert calls == ["u1"]
        assert not open_btn.disabled


def test_console_default_is_apply_interview() -> None:
    import inspect

    from whyline.console import jobs_screens

    source = inspect.getsource(jobs_screens.JobsHomeScreen._start_draft)
    assert "apply.interview" in source
