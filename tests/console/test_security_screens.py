import tomllib
from dataclasses import replace

import pytest
from textual.app import App
from textual.widgets import Button, Checkbox, Input, Select, Static

from whyline.console import security_screens as ss
from whyline.console import tui
from whyline.console.release_screens import ReleaseScreen
from whyline.release import config as release_config
from whyline.release.config import ReleaseConfig
from whyline.release.ready import ReadyItem
from whyline.security import scan
from whyline.security import settings as st
from whyline.security.findings import Finding
from whyline.security.settings import Decision, SecuritySettings

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

FULL_SECRET = "AKIAIOSFODNN7EXAMPLE"
SECRET = Finding("secret", "aws-key", "AWS key", "high", "app/conf.py", 7, "abcdef1234567",
                 "AK****LE", "fp-secret", "Move it to an env var.")
DEP = Finding("dependency", "osv", "requests 2.0 has a CVE", "critical", "uv.lock", 0, "",
              "", "fp-dep", "Upgrade to 2.31.")
CONTENT = Finding("contents", "env-file", ".env in the package", "medium", ".env", 0, "", "",
                  "fp-content", "Remove it from the build.")


def _report(*blocking, warnings=()):
    return scan.ScanReport("release", [*blocking, *warnings],
                           Decision(tuple(blocking), tuple(warnings)))


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    def on_mount(self):
        self.push_screen(self._screen)


def _screen(tmp_path, report=None, opened=None):
    def fake_scan(root, scope, settings, **kw):
        return report or _report(SECRET, DEP, warnings=[CONTENT])

    def open_file(path, line):
        if opened is not None:
            opened.append((path, line))
        return ""

    return ss.SecurityScreen(tmp_path, config=ReleaseConfig(), scan_run=fake_scan,
                             open_file=open_file)


async def _settle(pilot, n=15):
    for _ in range(n):
        await pilot.pause()


def _status(app):
    return str(app.screen.query_one("#sec-status", Static).renderable)


def _texts(app):
    return [str(w.renderable) for w in app.screen.query(".sec-text").results(Static)]


def test_grouping_and_badges():
    groups = ss.group_findings([CONTENT, DEP, SECRET])
    assert [title for title, _ in groups] == ["Secrets", "Dependencies", "Package contents"]
    assert ss.badge(DEP) == "[CRIT]" and ss.badge(SECRET) == "[HIGH]"
    text = ss.finding_text(SECRET)
    assert "[HIGH] AWS key" in text
    assert "app/conf.py:7" in text and "abcdef1" in text and "AK****LE" in text
    assert "Move it to an env var." in text
    assert "rotate this key" in text.lower()
    assert "rotate" not in ss.finding_text(DEP).lower()


async def test_findings_are_listed_in_groups(tmp_path):
    async with Host(_screen(tmp_path)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        texts = _texts(pilot.app)
        assert len(texts) == 3
        assert "AWS key" in texts[0] and "requests 2.0" in texts[1] and ".env" in texts[2]
        labels = [str(w.renderable) for w in pilot.app.screen.query(".sec-group")]
        assert labels == ["Secrets", "Dependencies", "Package contents"]


async def test_fix_opens_the_file_at_the_line(tmp_path):
    opened = []
    async with Host(_screen(tmp_path, opened=opened)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        pilot.app.screen.query_one("#sec-fix-0", Button).press()
        await _settle(pilot)
        assert opened == [(tmp_path / "app/conf.py", 7)]
        assert "doesn't remove it from history" in _status(pilot.app)


async def test_allow_needs_a_reason_and_writes_through_allow(tmp_path):
    async with Host(_screen(tmp_path)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        screen = pilot.app.screen
        screen.query_one("#sec-allow-0", Button).press()
        await _settle(pilot)
        screen.query_one("#sec-allow-ok", Button).press()
        await _settle(pilot)
        assert _status(pilot.app) == ss.REASON_NEEDED
        assert not (tmp_path / st.ALLOW_PATH).exists()
        screen.query_one("#sec-reason", Input).value = "test fixture key"
        screen.query_one("#sec-allow-ok", Button).press()
        await _settle(pilot)
        entries = tomllib.loads((tmp_path / st.ALLOW_PATH).read_text())["allow"]
        assert entries[0]["fingerprint"] == "fp-secret"
        assert entries[0]["reason"] == "test fixture key"
        assert len(_texts(pilot.app)) == 2


TEST_SECRET = Finding("secret", "aws-key", "AWS key", "high", "tests/test_x.py", 3, "", "AK****LE",
                      "fp-test", "Move it to an env var.")
PKG_TEST_SECRET = Finding("secret", "aws-key", "AWS key", "high",
                          "pkg-0.3.69.tar.gz:pkg-0.3.69/tests/x.py", 3, "", "AK****LE", "fp-pkg", "")


def test_secret_in_a_test_gets_one_extra_line():
    assert ss.finding_text(TEST_SECRET).splitlines()[-1] == (
        '    This is in a test. If it is a fake value, Allow it with the reason '
        '"Fake value in a test".')
    assert ss.TEST_NOTE in ss.finding_text(PKG_TEST_SECRET)
    assert ss.TEST_NOTE in ss.finding_text(replace(PKG_TEST_SECRET, path="pkg-1.whl:tests/x.py"))
    assert ss.TEST_NOTE not in ss.finding_text(SECRET)
    assert ss.TEST_NOTE not in ss.finding_text(replace(TEST_SECRET, kind="contents"))


async def test_allow_in_a_test_prefills_an_editable_required_reason(tmp_path):
    report = _report(TEST_SECRET, SECRET)
    async with Host(_screen(tmp_path, report)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        screen = pilot.app.screen
        screen.query_one("#sec-allow-0", Button).press()
        await _settle(pilot)
        reason = screen.query_one("#sec-reason", Input)
        assert reason.value == ss.TEST_REASON
        reason.value = ""
        screen.query_one("#sec-allow-ok", Button).press()
        await _settle(pilot)
        assert _status(pilot.app) == ss.REASON_NEEDED
        screen.query_one("#sec-allow-cancel", Button).press()
        screen.query_one("#sec-allow-1", Button).press()
        await _settle(pilot)
        assert screen.query_one("#sec-reason", Input).value == ""


async def test_ignore_once_records_and_removes(tmp_path):
    async with Host(_screen(tmp_path)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        pilot.app.screen.query_one("#sec-ignore-1", Button).press()
        await _settle(pilot)
        assert st.is_ignored_once(scan.state_dir(tmp_path), DEP)
        assert not st.is_allowed(tmp_path, DEP)
        assert len(_texts(pilot.app)) == 2


async def test_history_scan_progress_and_stop(tmp_path):
    seen = {}

    def slow_scan(root, scope, settings, **kw):
        if scope == "history":
            kw["on_progress"](3, 10)
            seen["cancel"] = kw["cancel_event"]
            assert kw["cancel_event"].wait(5)
            return scan.ScanReport("history", cancelled=True)
        return _report()

    screen = ss.SecurityScreen(tmp_path, config=ReleaseConfig(), scan_run=slow_scan,
                               open_file=lambda p, n: "")
    async with Host(screen).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        screen.query_one("#sec-history", Button).press()
        for _ in range(200):
            await pilot.pause()
            if "commits 3 of 10" in _status(pilot.app):
                break
        assert _status(pilot.app) == "commits 3 of 10"
        assert not screen.query_one("#sec-stop", Button).disabled
        screen.query_one("#sec-stop", Button).press()
        for _ in range(200):
            await pilot.pause()
            if "partial" in _status(pilot.app):
                break
        assert seen["cancel"].is_set()
        assert "partial" in _status(pilot.app)
        assert screen.query_one("#sec-stop", Button).disabled


def test_report_has_masked_values_only():
    leaky = Finding("secret", "aws-key", "AWS key", "high", "a.py", 1, "abcdef1234",
                    "AK****LE", "fp", "Move it.")
    text = ss.report_text([leaky, DEP])
    assert FULL_SECRET not in text and "AK****LE" in text
    assert "Secrets:" in text and "Dependencies:" in text
    assert ss.report_text([]) == "No findings."


async def test_copy_report(tmp_path):
    async with Host(_screen(tmp_path)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        pilot.app.screen.query_one("#sec-copy", Button).press()
        await _settle(pilot)
        assert "AK****LE" in pilot.app.clipboard
        assert FULL_SECRET not in pilot.app.clipboard


# -- Release screen: the buttons and the Set up section --------------------------


def _release(tmp_path, cfg=None, items=None, factory=None):
    return ReleaseScreen(
        tmp_path, start_release=lambda c: None, config=cfg or ReleaseConfig(),
        current_version="0.3.64", ready_check=lambda v: items or [],
        steps=lambda v: [], security_screen=factory)


async def test_release_opens_security(tmp_path):
    made = []

    def factory():
        made.append(1)
        return _screen(tmp_path)

    async with Host(_release(tmp_path, factory=factory)).run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        pilot.app.screen.query_one("#release-security", Button).press()
        await _settle(pilot)
        assert made and isinstance(pilot.app.screen, ss.SecurityScreen)


async def test_failed_security_item_offers_the_fix(tmp_path):
    items = [ReadyItem("security", False, "1 blocking findings", "Open Security to review")]
    host = Host(_release(tmp_path, items=items, factory=lambda: _screen(tmp_path)))
    async with host.run_test(size=(120, 50)) as pilot:
        await _settle(pilot)
        release = pilot.app.screen
        fix = release.query_one("#release-fix-security", Button)
        assert fix.has_class("-hidden")
        release.query_one("#release-check", Button).press()
        await _settle(pilot, 40)
        assert not fix.has_class("-hidden")
        fix.press()
        await _settle(pilot)
        assert isinstance(pilot.app.screen, ss.SecurityScreen)


async def test_setup_security_round_trip(tmp_path):
    cfg = ReleaseConfig(security=SecuritySettings(secrets="warn", dependencies="block",
                                                  contents="off", pre_commit=True,
                                                  audit="warn"))
    async with Host(_release(tmp_path, cfg=cfg)).run_test(size=(120, 60)) as pilot:
        await _settle(pilot)
        screen = pilot.app.screen
        assert screen.query_one("#rs-sec-secrets", Select).value == "warn"
        assert screen.query_one("#rs-sec-dependencies", Select).value == "block"
        assert screen.query_one("#rs-sec-contents", Select).value == "off"
        assert screen.query_one("#rs-sec-pre-commit", Checkbox).value is True
        assert screen.query_one("#rs-sec-audit", Select).value == "warn"
        assert "Rules: v" in str(screen.query_one("#rs-sec-rules", Static).renderable)
        screen.query_one("#rs-sec-secrets", Select).value = "off"
        screen.query_one("#rs-sec-dependencies", Select).value = "block-high"
        screen.query_one("#rs-sec-pre-commit", Checkbox).value = False
        screen.query_one("#rs-sec-audit", Select).value = "block-confirmed"
        await _settle(pilot)
        screen._save_setup()
        saved = release_config.load(tmp_path).security
        assert (saved.secrets, saved.dependencies, saved.contents) == ("off", "block-high", "off")
        assert saved.pre_commit is False and saved.audit == "block-confirmed"


def test_tools_text_shows_the_brew_hint_when_missing():
    text, missing = ss.tools_text({"gitleaks": "/bin/gitleaks"})
    assert missing and "brew install gitleaks osv-scanner" in text
    assert "gitleaks: /bin/gitleaks" in text
    text, missing = ss.tools_text({"gitleaks": "a", "betterleaks": "b", "osv-scanner": "c"})
    assert not missing and "brew" not in text
