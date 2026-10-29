"""Tests for `JobsHomeScreen` and the `Jobs` button in Agents mode."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import pytest

from whyline.console import tui
from whyline.console.jobs_screens import JobsHomeScreen, PRIVACY_SENTENCE
from whyline.jobs import profile

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
    return home_dir


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
