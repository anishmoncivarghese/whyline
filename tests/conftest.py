import asyncio
import os
import subprocess
from pathlib import Path

import pytest


def _pad_pilot_pauses_on_windows() -> None:
    """On Windows only, let a bare ``pilot.pause()`` also give the app a short
    real delay. Textual's idle check returns there before a pushed screen has
    mounted its children or a worker's result has landed, and the slow Windows
    3.11 runner failed a different handful of console tests every run.
    macOS and Linux keep Textual's own pause."""
    if os.name != "nt":
        return
    try:
        from textual.pilot import Pilot
    except ImportError:
        return
    original = Pilot.pause

    async def pause(self, delay=None):
        await original(self, delay)
        if delay is None:
            await asyncio.sleep(0.05)
            await original(self)

    Pilot.pause = pause


_pad_pilot_pauses_on_windows()


def _click_where_the_widget_is() -> None:
    """Make ``pilot.click(target)`` wait until ``target`` is really at the spot
    the click will use. Textual computes that spot from the widget's last
    layout, and a test that clicks right after a change that moves things
    (a dialog closing, a result growing above a button) can click stale
    coordinates on a slow runner. The click then lands on another widget and is
    lost; Windows and Ubuntu 3.11 lost the same few clicks run after run."""
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
