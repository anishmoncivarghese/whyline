"""Tests for `JobsHomeScreen` and the `Jobs` button in Agents mode."""

from __future__ import annotations

import datetime
import threading
from pathlib import Path
from typing import Any

import pytest

from whyline import account
from whyline.console import tui
from whyline.console.jobs_screens import JobsHomeScreen, PRIVACY_SENTENCE
from whyline.jobs import profile, review

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

EXPECTED_PRIVACY = (
    "Your CV stays in ~/.whyline/jobs on this Mac. It is sent to the AI "
    "provider you choose each time a job-search agent runs, and never to "
    "email or Telegram."
)


class _Host(tui.App):
    def compose(self):
        yield tui.Static("host")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setattr(account.paths, "global_whyline_dir", lambda: home_dir / ".whyline")
    return home_dir


async def _until(pilot: Any, condition: Any, what: str) -> None:
    for _ in range(300):
        await pilot.pause()
        if condition():
            return
        await pilot.pause(0.01)
    raise AssertionError(f"timed out waiting for: {what}")


def _plain(value: object) -> str:
    return value.plain if hasattr(value, "plain") else str(value)


async def test_agents_mode_jobs_button_opens_jobs_home_screen_within_80_cols(
    tmp_path: Path,
) -> None:
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#mode-agents")
        await pilot.pause()

        jobs_btn = app.query_one("#agents-jobs", tui.Button)
        assert jobs_btn.display is True
        assert str(jobs_btn.label) == "Jobs"
        shown = [b for b in app.query("#controls Button") if b.display]
        assert all(b.region.width > 0 and b.region.right <= 80 for b in shown)

        await pilot.click("#agents-jobs")
        await pilot.pause()
        assert isinstance(app.screen, JobsHomeScreen)

        await pilot.click("#jh-close")
        await pilot.pause()
        assert not isinstance(app.screen, JobsHomeScreen)


async def test_privacy_sentence_and_profile_section_are_shown_exactly() -> None:
    assert PRIVACY_SENTENCE == EXPECTED_PRIVACY
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = JobsHomeScreen()
        app.push_screen(screen)
        await pilot.pause()

        heading = _plain(screen.query_one("#jh-profile-heading", tui.Label).render())
        assert heading == "Profile"

        privacy = _plain(screen.query_one("#jh-privacy", tui.Static).render())
        assert privacy == EXPECTED_PRIVACY

        cv_status = _plain(screen.query_one("#jh-cv-status", tui.Static).render())
        assert "not imported" in cv_status


async def test_screen_imports_pastes_and_saves_through_stubbed_profile_functions(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cv_exists = {"present": False}
    calls: dict[str, list[Any]] = {
        "import_cv": [],
        "import_cv_text": [],
        "save_preferences": [],
    }

    def fake_status() -> dict[str, profile.FileStatus]:
        cv_target = isolated_home / ".whyline" / "jobs" / "cv.md"
        if cv_exists["present"]:
            cv_entry = profile.FileStatus(
                name="cv.md",
                path=cv_target,
                exists=True,
                modified_at=datetime.datetime(2026, 10, 29, 8, 30, tzinfo=datetime.timezone.utc),
                size_bytes=512,
            )
        else:
            cv_entry = profile.FileStatus(
                name="cv.md",
                path=cv_target,
                exists=False,
                modified_at=None,
                size_bytes=0,
            )
        return {"cv.md": cv_entry}

    def fake_load_preferences() -> dict[str, Any]:
        return {
            "roles": ["Platform Engineer"],
            "seniority": "Senior",
            "locations": ["San Francisco, CA", "London"],
            "remote": "remote",
            "salary_min": 120000,
            "currency": "USD",
            "languages": ["English"],
            "deal_breakers": ["unpaid"],
            "notes": "Initial note",
        }

    def fake_import_cv(path: str | Path) -> Path:
        calls["import_cv"].append(str(path))
        cv_exists["present"] = True
        return isolated_home / ".whyline" / "jobs" / "cv.md"

    def fake_import_cv_text(text: str) -> Path:
        calls["import_cv_text"].append(text)
        cv_exists["present"] = True
        return isolated_home / ".whyline" / "jobs" / "cv.md"

    def fake_save_preferences(prefs: dict[str, Any]) -> None:
        calls["save_preferences"].append(dict(prefs))

    monkeypatch.setattr(profile, "status", fake_status)
    monkeypatch.setattr(profile, "load_preferences", fake_load_preferences)
    monkeypatch.setattr(profile, "import_cv", fake_import_cv)
    monkeypatch.setattr(profile, "import_cv_text", fake_import_cv_text)
    monkeypatch.setattr(profile, "save_preferences", fake_save_preferences)

    app = _Host()
    async with app.run_test(size=(100, 32)) as pilot:
        screen = JobsHomeScreen()
        app.push_screen(screen)
        await pilot.pause()

        # Loaded preferences prefill the form (including embedded commas in locations)
        assert screen.query_one("#jh-roles", tui.Input).value == "Platform Engineer"
        assert screen.query_one("#jh-seniority", tui.Input).value == "Senior"
        assert screen.query_one("#jh-remote", tui.Select).value == "remote"
        assert screen.query_one("#jh-salary-min", tui.Input).value == "120000"
        assert "not imported" in _plain(screen.query_one("#jh-cv-status", tui.Static).render())

        # 1. Import CV… opens the path input and imports via profile.import_cv
        screen.query_one("#jh-import-cv", tui.Button).press()
        await pilot.pause()
        assert not screen.query_one("#jh-import-panel").has_class("-hidden")
        screen.query_one("#jh-cv-path", tui.Input).value = "~/Documents/resume.docx"
        screen.query_one("#jh-cv-import-confirm", tui.Button).press()
        await pilot.pause()

        assert calls["import_cv"] == ["~/Documents/resume.docx"]
        assert screen.query_one("#jh-import-panel").has_class("-hidden")
        cv_text = _plain(screen.query_one("#jh-cv-status", tui.Static).render())
        assert "present" in cv_text and "512 bytes" in cv_text

        # 2. Paste CV… opens the TextArea and saves via profile.import_cv_text
        cv_exists["present"] = False
        screen.query_one("#jh-paste-cv", tui.Button).press()
        await pilot.pause()
        assert not screen.query_one("#jh-paste-panel").has_class("-hidden")
        area = screen.query_one("#jh-cv-text", tui.TextArea)
        area.load_text("# Barbara Liskov\nMIT CSAIL\n")
        screen.query_one("#jh-cv-paste-confirm", tui.Button).press()
        await pilot.pause()

        assert calls["import_cv_text"] == ["# Barbara Liskov\nMIT CSAIL\n"]
        assert screen.query_one("#jh-paste-panel").has_class("-hidden")
        assert "present" in _plain(screen.query_one("#jh-cv-status", tui.Static).render())

        # 3. Editing preferences and pressing Save calls profile.save_preferences
        screen.query_one("#jh-roles", tui.Input).value = "Staff Engineer, Principal Engineer"
        screen.query_one("#jh-seniority", tui.Input).value = "Staff"
        screen.query_one("#jh-remote", tui.Select).value = "hybrid"
        screen.query_one("#jh-salary-min", tui.Input).value = "160000"
        screen.query_one("#jh-currency", tui.Input).value = "GBP"
        screen.query_one("#jh-languages", tui.Input).value = "English, French"
        screen.query_one("#jh-deal-breakers", tui.Input).value = "crypto"
        screen.query_one("#jh-notes", tui.Input).value = "Devtools preferred"

        screen.query_one("#jh-save", tui.Button).press()
        await pilot.pause()

        assert calls["save_preferences"] == [
            {
                "roles": ["Staff Engineer", "Principal Engineer"],
                "seniority": "Staff",
                "locations": ["San Francisco, CA", "London"],
                "remote": "hybrid",
                "salary_min": 160000,
                "currency": "GBP",
                "languages": ["English", "French"],
                "deal_breakers": ["crypto"],
                "notes": "Devtools preferred",
            }
        ]
        assert "Preferences saved." in _plain(screen.query_one("#jh-status", tui.Static).render())


async def test_validation_and_profile_errors_display_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse_import(_path: str | Path) -> Path:
        raise profile.ProfileError("Unsupported CV format '.pdf'")

    monkeypatch.setattr(profile, "import_cv", refuse_import)

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = JobsHomeScreen()
        app.push_screen(screen)
        await pilot.pause()

        screen.query_one("#jh-import-cv", tui.Button).press()
        await pilot.pause()
        screen.query_one("#jh-cv-path", tui.Input).value = "~/resume.pdf"
        screen.query_one("#jh-cv-import-confirm", tui.Button).press()
        await pilot.pause()
        assert "Unsupported CV format" in _plain(screen.query_one("#jh-error", tui.Static).render())

        screen.query_one("#jh-salary-min", tui.Input).value = "not-a-number"
        screen.query_one("#jh-save", tui.Button).press()
        await pilot.pause()
        assert "whole number" in _plain(screen.query_one("#jh-error", tui.Static).render())
        assert app.screen is screen


async def test_jobs_home_screen_fits_80x24() -> None:
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = JobsHomeScreen()
        app.push_screen(screen)
        await pilot.pause()

        # Key controls and privacy text are visible in the initial 80x24 viewport
        for selector in (
            "#jh-privacy",
            "#jh-cv-status",
            "#jh-import-cv",
            "#jh-paste-cv",
            "#jh-save",
            "#jh-close",
        ):
            reg = screen.query_one(selector).region
            assert reg.width > 0 and reg.right <= 80, selector
            assert reg.height > 0 and reg.bottom <= 24, selector

        # Opening Import CV… keeps Save and Close pinned inside 80x24
        await pilot.click("#jh-import-cv")
        await pilot.pause()
        for selector in ("#jh-cv-path", "#jh-save", "#jh-close"):
            reg = screen.query_one(selector).region
            assert reg.width > 0 and reg.right <= 80, selector
            assert reg.height > 0 and reg.bottom <= 24, selector

        # Opening Paste CV… TextArea also keeps Save and Close pinned inside 80x24
        await pilot.click("#jh-paste-cv")
        await pilot.pause()
        for selector in ("#jh-save", "#jh-close"):
            reg = screen.query_one(selector).region
            assert reg.width > 0 and reg.right <= 80, selector
            assert reg.height > 0 and reg.bottom <= 24, selector

        # Every displayed widget stays horizontally within 80 columns
        for widget in screen.query("*"):
            if widget.display and widget.region.width > 0:
                assert 0 <= widget.region.x and widget.region.right <= 80, widget


async def test_review_cv_shows_progress_edits_accept_saves_edited_text_and_discard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress_reported = threading.Event()
    finish_worker = threading.Event()
    chosen_clis: list[str | None] = []

    account.save_global(
        {
            "claude": {"enabled": False, "available": True},
            "codex": {"enabled": True, "available": True},
            "grok": {"enabled": True, "available": True},
            "antigravity": {"enabled": True, "available": True},
        }
    )

    def gated_run(cli: str | None = None, progress=None) -> review.ReviewResult:
        chosen_clis.append(cli)
        if progress is not None:
            progress(f"{cli} is working")
        progress_reported.set()
        finish_worker.wait(timeout=5)
        p_draft, r_draft = review.save_drafts(
            "Initial drafted profile\n",
            "Initial drafted rubric\n",
        )
        return review.ReviewResult(
            ok=True,
            outcome="succeeded",
            cli=cli or "codex",
            profile="Initial drafted profile\n",
            rubric="Initial drafted rubric\n",
            profile_draft_path=p_draft,
            rubric_draft_path=r_draft,
        )

    monkeypatch.setattr(review, "run", gated_run)

    app = _Host()
    async with app.run_test(size=(100, 36)) as pilot:
        screen = JobsHomeScreen()
        app.push_screen(screen)
        await pilot.pause()

        # Disabled claude and non-read-only antigravity are never offered.
        offered = [
            v
            for _label, v in screen.query_one("#jh-review-cli", tui.Select)._options
            if v is not tui.Select.BLANK
        ]
        assert offered == ["codex", "grok"]
        assert screen.query_one("#jh-review-cli", tui.Select).value == "codex"
        assert screen.query_one("#jh-review-panel").has_class("-hidden")

        # Select grok and press Review my CV -> progress shows while worker runs.
        screen.query_one("#jh-review-cli", tui.Select).value = "grok"
        screen.query_one("#jh-review-cv", tui.Button).press()

        await _until(
            pilot,
            lambda: progress_reported.is_set()
            and "grok is working"
            in _plain(screen.query_one("#jh-review-progress", tui.Static).render()),
            "worker progress shown",
        )
        assert screen.query_one("#jh-review-cv", tui.Button).disabled is True

        finish_worker.set()
        await _until(
            pilot,
            lambda: not screen.query_one("#jh-review-panel").has_class("-hidden"),
            "drafts panel shown",
        )
        assert chosen_clis == ["grok"]
        assert screen.query_one("#jh-review-progress", tui.Static).has_class("-empty")
        assert screen.query_one("#jh-review-cv", tui.Button).disabled is False

        prof_area = screen.query_one("#jh-profile-draft", tui.TextArea)
        rub_area = screen.query_one("#jh-rubric-draft", tui.TextArea)
        assert prof_area.text == "Initial drafted profile\n"
        assert rub_area.text == "Initial drafted rubric\n"

        # User edits both TextAreas and presses Accept -> saves edited text to profile.md and rubric.md.
        prof_area.load_text("# Edited Profile\nStrengths: Rust & Python\n")
        rub_area.load_text("# Edited Rubric\nRole fit: 0-5\nVeto: crypto\n")
        screen.query_one("#jh-review-accept", tui.Button).press()
        await pilot.pause()

        assert screen.query_one("#jh-review-panel").has_class("-hidden")
        assert (
            profile.profile_path().read_text(encoding="utf-8")
            == "# Edited Profile\nStrengths: Rust & Python\n"
        )
        assert (
            profile.rubric_path().read_text(encoding="utf-8")
            == "# Edited Rubric\nRole fit: 0-5\nVeto: crypto\n"
        )
        assert not review.profile_draft_path().exists()
        assert not review.rubric_draft_path().exists()

        # Re-running and pressing Discard removes drafts and preserves accepted files.
        screen.query_one("#jh-review-cv", tui.Button).press()
        await _until(
            pilot,
            lambda: not screen.query_one("#jh-review-panel").has_class("-hidden"),
            "second drafts panel shown",
        )
        assert review.profile_draft_path().is_file()
        screen.query_one("#jh-review-discard", tui.Button).press()
        await pilot.pause()

        assert screen.query_one("#jh-review-panel").has_class("-hidden")
        assert not review.profile_draft_path().exists()
        assert not review.rubric_draft_path().exists()
        assert (
            profile.profile_path().read_text(encoding="utf-8")
            == "# Edited Profile\nStrengths: Rust & Python\n"
        )


async def test_failed_review_in_console_reports_outcome_and_writes_nothing_within_80x24(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        review,
        "run",
        lambda cli=None, progress=None: review.ReviewResult(
            ok=False,
            outcome="missing_block",
            reason="Missing fenced 'rubric' block in agent answer.",
        ),
    )

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = JobsHomeScreen()
        app.push_screen(screen)
        await pilot.pause()

        reg_btn = screen.query_one("#jh-review-cv").region
        assert reg_btn.width > 0 and reg_btn.right <= 80 and reg_btn.bottom <= 24

        screen.query_one("#jh-review-cv", tui.Button).press()
        await _until(
            pilot,
            lambda: "missing_block"
            in _plain(screen.query_one("#jh-error", tui.Static).render()),
            "failure outcome reported",
        )
        assert screen.query_one("#jh-review-panel").has_class("-hidden")
        assert not review.profile_draft_path().exists()
        assert not review.rubric_draft_path().exists()
        assert not profile.profile_path().exists()
        assert not profile.rubric_path().exists()

        for selector in ("#jh-save", "#jh-close"):
            reg = screen.query_one(selector).region
            assert reg.width > 0 and reg.right <= 80 and reg.bottom <= 24
        for widget in screen.query("*"):
            if widget.display and widget.region.width > 0:
                assert 0 <= widget.region.x and widget.region.right <= 80, widget


async def test_open_review_drafts_panel_fits_80x24() -> None:
    review.save_drafts("Strengths: Go, Python\n", "Role fit: 0-5\n")
    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = JobsHomeScreen()
        app.push_screen(screen)
        await pilot.pause()

        assert not screen.query_one("#jh-review-panel").has_class("-hidden")
        for selector in ("#jh-save", "#jh-close"):
            reg = screen.query_one(selector).region
            assert reg.width > 0 and reg.right <= 80 and reg.bottom <= 24

        actions = screen.query_one("#jh-review-actions")
        actions.scroll_visible(animate=False)
        await pilot.pause()
        for selector in ("#jh-review-accept", "#jh-review-discard"):
            reg = screen.query_one(selector).region
            assert reg.width > 0 and reg.right <= 80 and reg.bottom <= 24, selector

        for widget in screen.query("*"):
            if widget.display and widget.region.width > 0:
                assert 0 <= widget.region.x and widget.region.right <= 80, widget
