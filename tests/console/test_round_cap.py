import subprocess
import tomllib
from pathlib import Path

import pytest

from whyline import cli
from whyline.console import recovery, relay_ops, tui

# Importing `ops` brings the screen tests' autouse stubs (agents, live_run) along.
from .test_relay_setup_screen import (  # noqa: F401
    _REAL_SAVE_MAX_ROUNDS,
    _checks,
    _checks_text,
    _open,
    _wait_for,
    ops,
)


@pytest.fixture(autouse=True)
def real_saver(ops, monkeypatch):
    # The screen tests' `ops` stubs the saver; these tests need the real one.
    monkeypatch.setattr(relay_ops, "save_max_rounds", _REAL_SAVE_MAX_ROUNDS)


def _repo(tmp_path: Path, config: str | None) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    (relay / "config.toml").write_text(config or 'plan = "plan.md"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _saved(root: Path) -> dict:
    return tomllib.loads((root / ".whyline" / "relay" / "config.toml").read_text(encoding="utf-8"))


def _last_subject(root: Path) -> str:
    return subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_setup_rounds_is_saved_value_or_24(tmp_path):
    root = _repo(tmp_path, 'plan = "plan.md"\nmax_rounds = 9\n')
    assert relay_ops.setup_max_rounds(root) == 9
    assert relay_ops.saved_max_rounds(root) == 9


def test_setup_rounds_defaults_to_24_when_config_has_none(tmp_path):
    root = _repo(tmp_path, None)
    assert relay_ops.saved_max_rounds(root) is None
    assert relay_ops.setup_max_rounds(root) == relay_ops.DEFAULT_SETUP_ROUNDS == 24


def test_save_max_rounds_commits_a_setup_commit(tmp_path):
    root = _repo(tmp_path, None)
    assert relay_ops.save_max_rounds(root, 12) == 12
    assert _saved(root)["max_rounds"] == 12
    assert _last_subject(root) == "setup: max_rounds 12"


@pytest.mark.parametrize("bad", [0, 100, "abc", "", "-3", "1.5", "٣"])
def test_save_max_rounds_rejects_out_of_range_and_text(tmp_path, bad):
    root = _repo(tmp_path, None)
    with pytest.raises(ValueError):
        relay_ops.save_max_rounds(root, bad)
    assert "max_rounds" not in _saved(root)


@pytest.mark.parametrize("good", [1, 99, "7"])
def test_save_max_rounds_accepts_the_ends(tmp_path, good):
    root = _repo(tmp_path, None)
    assert relay_ops.save_max_rounds(root, good) == int(good)


def test_round_cap_check_line_and_low_cap_warning():
    ok = relay_ops.round_cap_checks(24)
    assert [(c.status, c.message) for c in ok] == [("ok", "Round cap: 24")]
    low = relay_ops.round_cap_checks(5)
    assert [c.status for c in low] == ["ok", "warn"]
    assert low[0].message == "Round cap: 5"
    assert low[1].message == "A cap under 6 pauses most tasks after one or two send-backs."
    assert len(relay_ops.round_cap_checks(6)) == 1


def test_more_rounds_goes_through_the_one_saver(tmp_path, monkeypatch):
    root = _repo(tmp_path, 'plan = "plan.md"\nmax_rounds = 18\n')
    calls = []
    real = relay_ops.save_max_rounds

    def spy(r, n, **kw):
        calls.append((n, kw))
        return real(r, n, **kw)

    monkeypatch.setattr(relay_ops, "save_max_rounds", spy)
    assert recovery._raise_max_rounds(root) == 24
    assert calls == [(24, {"commit": True})]
    assert _last_subject(root) == "setup: max_rounds 24"


def test_more_rounds_stops_at_99(tmp_path):
    root = _repo(tmp_path, 'plan = "plan.md"\nmax_rounds = 97\n')
    assert recovery._raise_max_rounds(root) == 99


def test_cli_rounds_prints_and_saves(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path, None)
    monkeypatch.chdir(root)
    assert cli.main(["relay", "rounds"]) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "Round cap: 24"
    assert cli.main(["relay", "rounds", "10"]) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "Round cap: 10"
    assert _saved(root)["max_rounds"] == 10
    assert _last_subject(root) == "setup: max_rounds 10"
    assert cli.main(["relay", "rounds"]) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "Round cap: 10"


def test_cli_rounds_rejects_bad_values(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path, None)
    monkeypatch.chdir(root)
    for bad in ("0", "100", "many"):
        assert cli.main(["relay", "rounds", bad]) == cli.EXIT_ERROR
    assert "max_rounds" not in _saved(root)
    assert cli.main(["relay", "rounds", "1", "2"]) == cli.EXIT_ERROR


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_field_shows_saved_value(tmp_path):
    root = _repo(tmp_path, 'plan = "plan.md"\nmax_rounds = 9\n')
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        field = screen.query_one("#rs-rounds", tui.Input)
        assert field.value == "9"
        assert str(screen.query_one("#rs-rounds-note", tui.Static).renderable) == ""
        hint = str(screen.query_one("#rs-rounds-hint", tui.Static).renderable)
        assert hint == (
            "Rounds per task before the relay pauses. Each review or test send-back uses one."
        )


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_field_shows_24_and_a_note_when_none_saved(tmp_path):
    root = _repo(tmp_path, None)
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rs-rounds", tui.Input).value == "24"
        note = str(screen.query_one("#rs-rounds-note", tui.Static).renderable)
        assert note == "(not saved yet; the relay's own default is 3)"


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_check_saves_the_default_and_shows_the_round_cap(tmp_path, monkeypatch):
    root = _repo(tmp_path, None)
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        start = screen.query_one("#rs-start", tui.Button)
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(pilot, lambda: not start.disabled, "check")
        assert "Round cap: 24" in _checks_text(screen)
        assert str(screen.query_one("#rs-rounds-note", tui.Static).renderable) == ""
    assert _saved(root)["max_rounds"] == 24
    assert "setup: max_rounds 24" in subprocess.run(
        ["git", "log", "--format=%s"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.splitlines()


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_check_saves_a_changed_cap_and_warns_when_low(tmp_path, monkeypatch):
    root = _repo(tmp_path, 'plan = "plan.md"\nmax_rounds = 9\n')
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        start = screen.query_one("#rs-start", tui.Button)
        field = screen.query_one("#rs-rounds", tui.Input)
        field.value = "4"
        await pilot.pause()
        assert start.disabled
        screen.query_one("#rs-check", tui.Button).press()
        await _wait_for(pilot, lambda: not start.disabled, "check")
        text = _checks_text(screen)
        assert "Round cap: 4" in text
        assert "A cap under 6 pauses most tasks after one or two send-backs." in text
    assert _saved(root)["max_rounds"] == 4


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_field_only_takes_digits_and_bad_values_stop_the_check(tmp_path, monkeypatch):
    root = _repo(tmp_path, 'plan = "plan.md"\nmax_rounds = 9\n')
    monkeypatch.setattr(relay_ops, "run_checks", _checks("ok"))
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        field = screen.query_one("#rs-rounds", tui.Input)
        field.focus()
        await pilot.press("a", "b")
        assert field.value == "9"  # restrict rejects typed letters
        field.value = "0"
        await pilot.pause()
        screen.query_one("#rs-check", tui.Button).press()
        await pilot.pause(0.2)
        assert screen.query_one("#rs-start", tui.Button).disabled
        assert _checks_text(screen) == ""
    assert _saved(root)["max_rounds"] == 9


@pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")
@pytest.mark.asyncio
async def test_field_is_read_only_while_a_relay_runs(tmp_path, monkeypatch):
    root = _repo(tmp_path, 'plan = "plan.md"\nmax_rounds = 9\n')
    monkeypatch.setattr(relay_ops, "live_run", lambda r: "RCAP-1, claude")
    app = tui.WhylineConsoleApp(root=root)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rs-rounds", tui.Input).disabled
        note = str(screen.query_one("#rs-rounds-note", tui.Static).renderable)
        assert note == "Takes effect on the next run or resume."
