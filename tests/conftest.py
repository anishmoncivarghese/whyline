import asyncio
import os
import subprocess
from pathlib import Path

import pytest


def _settled(app) -> bool:
    """True when the app has nothing left to do for its current screen: the
    screen is mounted, and no message, layout or repaint is pending for it or
    its widgets. A widget's region and the hit map come from the same layout, so
    they agree even while a newer layout is pending; this is what notices."""
    try:
        screen = app.screen
        if not screen.is_mounted:
            return False
        if any(
            getattr(screen, flag, False)
            for flag in ("_layout_required", "_scroll_required", "_repaint_required",
                         "_recompose_required", "_dirty_widgets")
        ):
            return False
        for pump in (app, screen):
            queue = getattr(pump, "_message_queue", None)
            if queue is not None and not queue.empty():
                return False
        return not any(
            getattr(w, "_layout_required", False) or getattr(w, "_repaint_required", False)
            or getattr(w, "_recompose_required", False)
            for w in screen.walk_children(with_self=False)
        )
    except Exception:
        return True  # no screen yet, or torn down: nothing to wait for


def _pause_until_settled() -> None:
    """Make a bare ``pilot.pause()`` return only once the app has settled (up
    to 1 s). Textual's own pause returns at the first idle moment, which on a
    slow runner comes before a pushed screen has composed, a result has been
    laid out, or a dismiss has finished. Hundreds of console tests check right
    after one bare pause; on windows-latest 3.11 a different one of them failed
    about one run in four, so this fixes the whole class in one place. On
    Windows it also keeps a short real delay, which a worker's result needs to
    land (``call_from_thread``) before the settle check can see it.
    ``pilot.pause(delay)`` with a delay is left alone: those are polling loops."""
    try:
        from textual.pilot import Pilot
    except ImportError:
        return
    original = Pilot.pause

    async def pause(self, delay=None):
        await original(self, delay)
        if delay is not None:
            return
        if os.name == "nt":
            await asyncio.sleep(0.05)
            await original(self)
        for _ in range(40):
            if _settled(self.app):
                return
            await original(self, 0.025)

    Pilot.pause = pause


_pause_until_settled()


def _click_where_the_widget_is() -> None:
    """Make ``pilot.click(target)`` wait until ``target`` is really at the spot
    the click will use. Textual computes that spot from the widget's last
    layout, and a test that clicks right after a change that moves things
    (a dialog closing, a result growing above a button) can click stale
    coordinates on a slow runner. The click then lands on another widget and is
    lost; Windows and Ubuntu 3.11 lost the same few clicks run after run. The
    region and the hit map share one layout, so they agree even while a newer
    one is pending: the check also waits for the screen to settle."""
    try:
        from textual.pilot import Pilot
        from textual.widget import Widget
    except ImportError:
        return
    original = Pilot.click

    def _under_cursor(pilot, widget, offset) -> bool:
        app = pilot.app
        try:
            target = widget if isinstance(widget, Widget) else app.query_one(widget)
            if not _settled(app):
                return False
            x, y = target.region.offset + offset
            found, _ = app.get_widget_at(x, y)
        except Exception:
            return False
        return found is target or target in found.ancestors_with_self

    async def click(self, widget=None, offset=(0, 0), *args, **kwargs):
        if widget is not None:
            for _ in range(100):  # up to 5 s; returns at once when already there
                if _under_cursor(self, widget, offset):
                    break
                await self.pause(0.05)
        return await original(self, widget, offset, *args, **kwargs)

    Pilot.click = click


_click_where_the_widget_is()


class Repo:
    """A temporary git repository with controllable commit timestamps."""

    def __init__(self, path: Path):
        self.path = path

    def _git(self, *args: str, env_extra: dict[str, str] | None = None) -> str:
        import os

        env = dict(os.environ)
        env.update(
            {
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@invalid",
            }
        )
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def commit(self, files: dict[str, str], message: str, epoch: int) -> str:
        for rel, content in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self._git("add", "-A")
        stamp = f"@{epoch} +0000"
        self._git(
            "commit",
            "-m",
            message,
            env_extra={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
        )
        return self._git("rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return Repo(tmp_path)


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path_factory, monkeypatch):
    """Point HOME at a fresh temporary folder so no test touches ~/.whyline.

    Tests that ask for their own ``home`` fixture override this afterwards.
    """
    fake = tmp_path_factory.mktemp("autohome")
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    return fake


@pytest.fixture(autouse=True)
def _no_real_telegram(monkeypatch):
    """Fail fast instead of calling the Telegram API from a test.

    Tests that send pass their own ``http`` or stub ``urlopen``. Without this,
    a test that reaches the real sender hangs in a no-network sandbox
    (60-second timeout, retried), as Ask agent's read-only runs did.
    """
    import urllib.request

    from whyline.agents import telegram

    real_urlopen = urllib.request.urlopen

    def _guarded(request, *args, **kwargs):
        url = request if isinstance(request, str) else request.full_url
        if "api.telegram.org" in url:
            raise telegram.TelegramError("tests may not call the Telegram API")
        return real_urlopen(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", _guarded)
