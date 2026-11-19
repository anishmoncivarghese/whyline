"""The folder and file picker: what it lists, where it goes, what it returns."""

import os
from pathlib import Path

import pytest

from whyline.console import pickers, tui
from whyline.console.pickers import PathPickScreen, _NewFolderScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

_UNSET = object()


class _Host(tui.App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.result = _UNSET

    def on_mount(self) -> None:
        self.push_screen(self._screen, self._got)

    def _got(self, value) -> None:
        self.result = value


def _plain(widget) -> str:
    return str(widget.render())


def _names(screen) -> list[str]:
    return [
        str(getattr(w, "label", "")).lstrip("> ") for w in screen._rows
    ]


def _row(screen, name: str):
    for widget, path in screen._rows.items():
        if path.name == name:
            return widget
    raise AssertionError(f"{name} not listed: {_names(screen)}")


async def _press(pilot, screen, selector: str):
    screen.query_one(selector).press()
    await pilot.pause()
    await pilot.pause()


async def _type_path(pilot, screen, text: str):
    box = screen.query_one("#pp-path", tui.Input)
    box.value = text
    await box.action_submit()
    await pilot.pause()
    await pilot.pause()


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "beta").mkdir(parents=True)
    (root / "Alpha").mkdir()
    (root / ".hidden").mkdir()
    (root / "b.txt").write_text("b")
    (root / "a.txt").write_text("a")
    (root / ".secret").write_text("s")
    return root


def _screen(start, **kwargs):
    kwargs.setdefault("title", "Pick")
    return PathPickScreen(start, **kwargs)


async def test_picker_returns_only_real_folders(tree):
    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert _names(screen) == ["Alpha/", "beta/"]
        await _type_path(pilot, screen, str(tree / "nope"))
        assert _plain(screen.query_one("#pp-message")) == "No such folder"
        assert app.result is _UNSET
        await _type_path(pilot, screen, str(tree / "a.txt"))
        assert _plain(screen.query_one("#pp-message")) == "No such folder"
        assert app.result is _UNSET
        await _type_path(pilot, screen, str(tree / "beta"))
        assert _plain(screen.query_one("#pp-message")) == ""
        await _press(pilot, screen, "#pp-choose")
    assert app.result == tree / "beta"


async def test_choose_returns_current_folder_and_cancel_none(tree):
    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _press(pilot, screen, "#pp-choose")
    assert app.result == tree

    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _press(pilot, screen, "#pp-cancel")
    assert app.result is None


async def test_clicking_a_folder_enters_it_and_up_leaves(tree):
    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        _row(screen, "beta").press()
        await pilot.pause()
        await pilot.pause()
        assert screen._cwd == tree / "beta"
        assert _names(screen) == []
        await _press(pilot, screen, "#pp-up")
        assert screen._cwd == tree
        assert _names(screen) == ["Alpha/", "beta/"]


async def test_up_at_the_filesystem_root_stays(tmp_path):
    root = Path(tmp_path.anchor)
    screen = _screen(root)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _press(pilot, screen, "#pp-up")
        assert screen._cwd == root


async def test_home_goes_to_the_home_folder(tree, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "docs").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _press(pilot, screen, "#pp-home")
        assert screen._cwd == home
        assert _names(screen) == ["docs/"]


async def test_path_box_accepts_tilde(tree, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "docs").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _type_path(pilot, screen, "~/docs")
        assert screen._cwd == home / "docs"
        await _type_path(pilot, screen, "~/missing")
        assert _plain(screen.query_one("#pp-message")) == "No such folder"
        assert screen._cwd == home / "docs"


async def test_hidden_entries_follow_the_checkbox(tree):
    screen = _screen(tree, files=True)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert _names(screen) == ["Alpha/", "beta/", "a.txt", "b.txt"]
        screen.query_one("#pp-hidden", tui.Checkbox).value = True
        await pilot.pause()
        await pilot.pause()
        assert ".hidden/" in _names(screen)
        assert ".secret" in _names(screen)
        screen.query_one("#pp-hidden", tui.Checkbox).value = False
        await pilot.pause()
        await pilot.pause()
        assert ".hidden/" not in _names(screen)


async def test_unreadable_folder_stays_where_it_was(tree):
    locked = tree / "beta"
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("permissions are not enforced here")
        screen = _screen(tree)
        app = _Host(screen)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            _row(screen, "beta").press()
            await pilot.pause()
            await pilot.pause()
            assert _plain(screen.query_one("#pp-message")) == "Can't open this folder"
            assert screen._cwd == tree
            assert _names(screen) == ["Alpha/", "beta/"]
            await _type_path(pilot, screen, str(tree / "Alpha"))
            assert _plain(screen.query_one("#pp-message")) == ""
    finally:
        locked.chmod(0o755)


async def test_unreadable_folder_via_listing_error(tree, monkeypatch):
    real = pickers._list_folder

    def fake(folder, **kwargs):
        if folder.name == "Alpha":
            raise PermissionError("no")
        return real(folder, **kwargs)

    monkeypatch.setattr(pickers, "_list_folder", fake)
    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        _row(screen, "Alpha").press()
        await pilot.pause()
        await pilot.pause()
        assert _plain(screen.query_one("#pp-message")) == "Can't open this folder"
        assert screen._cwd == tree
        await _press(pilot, screen, "#pp-choose")
    assert app.result == tree


async def test_more_than_500_entries_shows_500_and_says_so(tmp_path):
    big = tmp_path / "big"
    big.mkdir()
    for i in range(520):
        (big / f"d{i:04d}").mkdir()
    screen = _screen(big)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert len(screen._rows) == 500
        assert _plain(screen.query_one("#pp-note")) == "Showing the first 500 of 520 entries."


async def test_exactly_500_entries_has_no_note(tmp_path):
    big = tmp_path / "big"
    big.mkdir()
    for i in range(500):
        (big / f"d{i:04d}").mkdir()
    screen = _screen(big)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert len(screen._rows) == 500
        assert _plain(screen.query_one("#pp-note")) == ""


async def _new_folder(pilot, app, name: str):
    await pilot.pause()
    sub = app.screen
    assert isinstance(sub, _NewFolderScreen)
    sub.query_one("#pp-new-name", tui.Input).value = name
    sub.query_one("#pp-new-create", tui.Button).press()
    await pilot.pause()
    await pilot.pause()
    return sub


async def test_new_folder_creates_and_enters_it(tree):
    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _press(pilot, screen, "#pp-new")
        await _new_folder(pilot, app, "fresh")
        assert (tree / "fresh").is_dir()
        assert app.screen is screen
        assert screen._cwd == tree / "fresh"


@pytest.mark.parametrize("name", ["a/b", "..", ".", "beta", "", "  "])
async def test_new_folder_refuses_bad_names(tree, name):
    screen = _screen(tree)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _press(pilot, screen, "#pp-new")
        sub = await _new_folder(pilot, app, name)
        assert app.screen is sub
        assert _plain(sub.query_one("#pp-new-message")) != ""
        assert sorted(p.name for p in tree.iterdir() if p.is_dir()) == [
            ".hidden", "Alpha", "beta"
        ]
        assert screen._cwd == tree
        sub.query_one("#pp-new-cancel", tui.Button).press()
        await pilot.pause()
        assert app.screen is screen


async def test_new_folder_problem_messages(tree):
    assert pickers.new_folder_problem(tree, "ok") is None
    assert pickers.new_folder_problem(tree, "a/b")
    assert pickers.new_folder_problem(tree, "..")
    assert pickers.new_folder_problem(tree, "beta")


async def test_files_mode_lists_files_and_returns_the_selected_one(tree):
    screen = _screen(tree, files=True)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _press(pilot, screen, "#pp-choose")
        assert _plain(screen.query_one("#pp-message")) == "Pick a file"
        _row(screen, "b.txt").press()
        await pilot.pause()
        await _press(pilot, screen, "#pp-choose")
    assert app.result == tree / "b.txt"


async def test_files_mode_path_box_accepts_a_file_but_not_a_missing_one(tree):
    screen = _screen(tree, files=True)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await _type_path(pilot, screen, str(tree / "missing.txt"))
        assert _plain(screen.query_one("#pp-message")) == "No such file or folder"
        assert app.result is _UNSET
        await _type_path(pilot, screen, str(tree / "a.txt"))
    assert app.result == tree / "a.txt"


async def test_many_mode_returns_the_ticked_files(tree):
    screen = _screen(tree, files=True, many=True)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert isinstance(_row(screen, "a.txt"), tui.Checkbox)
        assert isinstance(_row(screen, "beta"), tui.Button)
        await _press(pilot, screen, "#pp-choose")
        assert _plain(screen.query_one("#pp-message")) == "Tick at least one file"
        _row(screen, "b.txt").value = True
        _row(screen, "a.txt").value = True
        await pilot.pause()
        await _press(pilot, screen, "#pp-choose")
    assert app.result == [tree / "a.txt", tree / "b.txt"]


async def test_many_mode_drops_a_file_deleted_before_choose(tree):
    screen = _screen(tree, files=True, many=True)
    app = _Host(screen)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        _row(screen, "a.txt").value = True
        await pilot.pause()
        (tree / "a.txt").unlink()
        await _press(pilot, screen, "#pp-choose")
        assert app.result is _UNSET
        assert _plain(screen.query_one("#pp-message")) == "A ticked file no longer exists"
