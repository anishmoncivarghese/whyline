"""Provider Settings modal: transactional enablement, worker checks, layout."""

from __future__ import annotations

import threading

import pytest

from whyline.console import tui
from whyline.console.settings_screen import (
    PROVIDERS,
    ProviderSettingsScreen,
    _HINT,
    _NOT_CHECKED,
    _NOT_USED,
    _PATH_READY,
)

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


def _text(value) -> str:
    if value is None:
        return ""
    return value.plain if hasattr(value, "plain") else str(value)


def _plain(widget) -> str:
    label = getattr(widget, "label", None)
    text = _text(label)
    if text:
        return text
    return _text(getattr(widget, "renderable", None))


def _status(screen, agent: str) -> str:
    return _plain(screen.query_one(f"#ss-status-{agent}"))


def _records(**enabled: bool) -> dict:
    data = {}
    for agent in PROVIDERS:
        on = bool(enabled.get(agent, False))
        record = {"enabled": on, "available": on}
        if on and agent == "claude":
            record["plan"] = "max"
        if on and agent == "codex":
            record["plan"] = "plus"
        data[agent] = record
    return data


def _result(agent: str) -> dict:
    if agent in ("grok", "antigravity"):
        return {"plan": None, "available": True}
    if agent == "codex":
        return {"plan": "plus", "available": True}
    return {"plan": "max", "available": True}


class _Host(tui.App):
    """Minimal host so Settings can be pushed without the main console."""

    def compose(self):
        yield tui.Static("host")


async def _open(app, records, check, save, results=None, size=(80, 24)):
    screen = ProviderSettingsScreen(records, check, save)
    app.push_screen(screen, None if results is None else results.append)
    return screen


async def test_constructor_and_compose_do_not_check_providers():
    called = []
    screen = ProviderSettingsScreen(
        _records(claude=True, grok=True),
        lambda agent: called.append(agent) or _result(agent),
        lambda values, results=None: None,
    )
    assert called == []
    list(screen.compose())
    assert called == []


async def test_screen_appears_while_a_fake_check_is_blocked():
    started = threading.Event()
    release = threading.Event()
    called = []

    def check(agent):
        called.append(agent)
        started.set()
        release.wait(timeout=2)
        return _result(agent)

    app = _Host()
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await _open(app, _records(claude=True), check, lambda *_: None)
            await pilot.pause()
            assert started.wait(timeout=2.0)
            assert app.screen is screen
            assert _plain(screen.query_one("#ss-title")) == "Settings"
            assert _plain(screen.query_one("#ss-section")) == "AI subscriptions"
            assert _plain(screen.query_one("#ss-hint")) == _HINT
            assert [box.id for box in screen.query(tui.Checkbox)] == [
                f"ss-{agent}" for agent in PROVIDERS
            ]
            assert [_plain(box) for box in screen.query(tui.Checkbox)] == [
                "Claude",
                "Codex",
                "Grok",
                "Antigravity",
            ]
            assert _plain(screen.query_one("#ss-check-selected")) == "Check selected"
            assert _plain(screen.query_one("#ss-save")) == "Save"
            assert _plain(screen.query_one("#ss-cancel")) == "Cancel"
            for button_id in ("#ss-check-selected", "#ss-save", "#ss-cancel"):
                region = screen.query_one(button_id).region
                assert region.height > 0
                assert region.bottom <= 24
            assert called == ["claude"]
    finally:
        release.set()


async def test_only_staged_on_providers_are_called():
    called = []

    def check(agent):
        called.append(agent)
        return _result(agent)

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app, _records(claude=True, grok=True), check, lambda *_: None)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert called == ["claude", "grok"]
        assert _status(screen, "codex") == _NOT_USED
        assert _status(screen, "antigravity") == _NOT_USED
        assert _PATH_READY in _status(screen, "grok")


async def test_enabling_starts_only_that_provider():
    called = []

    def check(agent):
        called.append(agent)
        return _result(agent)

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app, _records(), check, lambda *_: None)
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert called == []
        await pilot.click("#ss-codex")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert called == ["codex"]
        assert screen.query_one("#ss-codex", tui.Checkbox).value is True
        assert "Plus" in _status(screen, "codex")


async def test_unchecking_suppresses_a_late_row_update():
    started = threading.Event()
    release = threading.Event()

    def check(agent):
        started.set()
        release.wait(timeout=2)
        return {"plan": "max", "available": True}

    app = _Host()
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await _open(app, _records(claude=True), check, lambda *_: None)
            await pilot.pause()
            assert started.wait(timeout=2.0)
            await pilot.click("#ss-claude")
            await pilot.pause()
            assert screen.query_one("#ss-claude", tui.Checkbox).value is False
            assert _status(screen, "claude") == _NOT_USED
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _status(screen, "claude") == _NOT_USED
            assert "Max" not in _status(screen, "claude")
            assert "Ready" not in _status(screen, "claude")
    finally:
        release.set()


async def test_a_second_refresh_ignores_the_first_token():
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    calls = []

    def check(agent):
        calls.append(agent)
        if len(calls) == 1:
            first_started.set()
            first_release.wait(timeout=2)
            return {"plan": "old-plan", "available": True}
        second_started.set()
        return {"plan": "new-plan", "available": True}

    app = _Host()
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await _open(app, _records(claude=True), check, lambda *_: None)
            await pilot.pause()
            assert first_started.wait(timeout=2.0)
            await pilot.click("#ss-check-selected")
            assert second_started.wait(timeout=2.0)
            first_release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = _status(screen, "claude")
            assert "New-plan" in text or "new-plan" in text
            assert "old-plan" not in text.lower()
    finally:
        first_release.set()


async def test_cancel_writes_nothing():
    saved = []
    dismissed = []

    def check(agent):
        return _result(agent)

    def save(values, results=None):
        saved.append((dict(values), dict(results or {})))

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        await _open(app, _records(claude=True), check, save, results=dismissed)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.click("#ss-cancel")
        await pilot.pause()
    assert saved == []
    assert dismissed == [None]


async def test_save_passes_all_four_booleans_once():
    saved = []
    dismissed = []

    def check(agent):
        return _result(agent)

    def save(values, results=None):
        saved.append((dict(values), dict(results or {})))

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(
            app, _records(claude=True, grok=True), check, save, results=dismissed
        )
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.click("#ss-claude")
        await pilot.click("#ss-codex")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert screen.query_one("#ss-claude", tui.Checkbox).value is False
        assert screen.query_one("#ss-codex", tui.Checkbox).value is True
        await pilot.click("#ss-save")
        await pilot.pause()
    assert len(saved) == 1
    values, results = saved[0]
    assert values == {
        "claude": False,
        "codex": True,
        "grok": True,
        "antigravity": False,
    }
    assert set(values) == set(PROVIDERS)
    assert all(isinstance(flag, bool) for flag in values.values())
    assert dismissed == [{"codex", "grok"}]
    assert "codex" in results
    assert "grok" in results


async def test_save_failure_stays_open():
    dismissed = []

    def check(agent):
        return _result(agent)

    def save(values, results=None):
        raise OSError("disk full")

    app = _Host()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await _open(app, _records(claude=True), check, save, results=dismissed)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.click("#ss-save")
        await pilot.pause()
        assert app.screen is screen
        assert dismissed == []
        assert screen.query_one("#ss-save", tui.Button).disabled is False
        assert "disk full" in _plain(screen.query_one("#ss-error"))
        assert screen.query_one("#ss-claude", tui.Checkbox).value is True


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_buttons_stay_reachable(size):
    width, height = size

    def check(agent):
        return _result(agent)

    app = _Host()
    async with app.run_test(size=size) as pilot:
        screen = await _open(app, _records(claude=True, grok=True), check, lambda *_: None)
        await pilot.pause()
        for button_id in ("#ss-check-selected", "#ss-save", "#ss-cancel"):
            region = screen.query_one(button_id).region
            assert region.height > 0
            assert region.bottom <= height
            assert region.x >= 0
            assert region.right <= width
        error = screen.query_one("#ss-error").region
        assert error.bottom <= height
        hint = screen.query_one("#ss-hint").region
        assert hint.height > 0
        assert hint.bottom <= height


async def test_enabling_shows_not_checked_yet_before_a_blocked_result():
    started = threading.Event()
    release = threading.Event()

    def check(agent):
        started.set()
        release.wait(timeout=2)
        return _result(agent)

    app = _Host()
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await _open(app, _records(), check, lambda *_: None)
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.click("#ss-grok")
            assert started.wait(timeout=2.0)
            assert _status(screen, "grok") in (_NOT_CHECKED, "Checking…")
            assert screen.query_one("#ss-grok", tui.Checkbox).value is True
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _status(screen, "grok") == _PATH_READY
    finally:
        release.set()
