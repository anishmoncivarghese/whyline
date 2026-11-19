"""A folder and file picker for the console.

``PathPickScreen`` dismisses with a ``Path``, a list of ``Path`` (many files),
or ``None``. It only ever returns a path that exists and is of the kind asked
for.
"""

from __future__ import annotations

import os
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

MAX_ENTRIES = 500

_NO_FOLDER = "No such folder"
_NO_PATH = "No such file or folder"
_CANT_OPEN = "Can't open this folder"


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _list_folder(folder: Path, *, files: bool, hidden: bool) -> tuple[list[Path], int]:
    """The entries to show (folders first) and how many there are in all.

    Raises OSError when the folder can't be read.
    """
    folders: list[Path] = []
    others: list[Path] = []
    with os.scandir(folder) as scan:
        for entry in scan:
            if not hidden and entry.name.startswith("."):
                continue
            path = folder / entry.name
            if _is_dir(path):
                folders.append(path)
            elif files and _is_file(path):
                others.append(path)
    folders.sort(key=lambda p: p.name.casefold())
    others.sort(key=lambda p: p.name.casefold())
    everything = folders + others
    return everything[:MAX_ENTRIES], len(everything)


def new_folder_problem(parent: Path, name: str) -> str | None:
    """Why ``name`` can't be a new folder inside ``parent``, or None."""
    if not name.strip():
        return "Type a name"
    if "/" in name or os.sep in name:
        return "A folder name can't contain /"
    if name.strip() in (".", ".."):
        return "That is not a folder name"
    if os.path.lexists(parent / name):
        return "That name is already taken"
    return None


class _NewFolderScreen(ModalScreen):
    """Asks for a name and creates the folder. Dismisses with its path."""

    DEFAULT_CSS = """
    _NewFolderScreen { align: center middle; }
    _NewFolderScreen > Vertical {
        width: 60; max-width: 100%; height: auto;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    _NewFolderScreen Horizontal { height: auto; margin-top: 1; }
    _NewFolderScreen Button { margin-right: 1; }
    _NewFolderScreen #pp-new-message { color: $error; height: auto; }
    """

    def __init__(self, parent: Path) -> None:
        super().__init__()
        self._parent_dir = parent

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("New folder name")
            yield Input(id="pp-new-name")
            yield Static("", id="pp-new-message")
            with Horizontal():
                yield Button("Create", id="pp-new-create", variant="primary")
                yield Button("Cancel", id="pp-new-cancel")

    def on_mount(self) -> None:
        self.query_one("#pp-new-name", Input).focus()

    def _create(self) -> None:
        name = self.query_one("#pp-new-name", Input).value.strip()
        message = self.query_one("#pp-new-message", Static)
        problem = new_folder_problem(self._parent_dir, name)
        if problem is None:
            target = self._parent_dir / name
            try:
                target.mkdir()
            except OSError:
                problem = "Can't create that folder"
            else:
                self.dismiss(target)
                return
        message.update(problem)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "pp-new-create":
            self._create()
        else:
            self.dismiss(None)


class PathPickScreen(ModalScreen):
    """Pick a folder, a file, or several files."""

    DEFAULT_CSS = """
    PathPickScreen { align: center middle; }
    PathPickScreen > Vertical {
        width: 100%; max-width: 100%; height: auto; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    PathPickScreen #pp-list { height: auto; max-height: 12; }
    PathPickScreen #pp-nav, PathPickScreen #pp-buttons { height: auto; margin-top: 1; }
    PathPickScreen Button { margin-right: 1; }
    PathPickScreen #pp-list Button {
        border: none; height: 1; min-width: 0; width: 1fr;
        background: transparent; text-align: left;
    }
    PathPickScreen Checkbox { border: none; height: 1; padding: 0 1; margin: 0; width: 1fr; }
    PathPickScreen Checkbox:focus { border: none; }
    PathPickScreen #pp-folder, PathPickScreen #pp-note { height: auto; }
    PathPickScreen #pp-message { color: $error; height: auto; }
    """

    def __init__(
        self,
        start: Path,
        *,
        files: bool = False,
        many: bool = False,
        title: str,
    ) -> None:
        super().__init__()
        self._files = files
        self._many = many and files
        self._title = title
        self._cwd = Path(start).expanduser()
        self._hidden = False
        self._rows: dict[object, Path] = {}
        self._ticked: set[Path] = set()
        self._selected: Path | None = None
        self._start_error = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(escape(self._title), id="pp-title")
            yield Static("", id="pp-folder")
            with Horizontal(id="pp-nav"):
                yield Button("Up", id="pp-up")
                yield Button("Home", id="pp-home")
                yield Button("New folder…", id="pp-new")
                yield Checkbox("Show hidden", id="pp-hidden")
            yield Input(id="pp-path", placeholder="Paste or type a path")
            yield VerticalScroll(id="pp-list")
            yield Static("", id="pp-note")
            yield Static("", id="pp-message")
            with Horizontal(id="pp-buttons"):
                yield Button("Choose", id="pp-choose", variant="primary")
                yield Button("Cancel", id="pp-cancel")

    async def on_mount(self) -> None:
        if not await self._show(self._cwd):
            self.query_one("#pp-message", Static).update(_CANT_OPEN)
        self.query_one("#pp-path", Input).focus()

    # -- listing ------------------------------------------------------------

    def _say(self, text: str = "") -> None:
        self.query_one("#pp-message", Static).update(escape(text))

    async def _show(self, folder: Path) -> bool:
        """List ``folder`` and make it the current one. False (and nothing
        changes, bar the empty listing at start) when it can't be read."""
        try:
            entries, total = _list_folder(folder, files=self._files, hidden=self._hidden)
        except OSError:
            return False
        self._cwd = folder
        self._selected = None
        await self._fill(entries, total)
        self.query_one("#pp-folder", Static).update(escape(str(folder)))
        self.query_one("#pp-path", Input).value = str(folder)
        return True

    async def _fill(self, entries: list[Path], total: int) -> None:
        box = self.query_one("#pp-list", VerticalScroll)
        await box.remove_children()
        self._rows = {}
        widgets = []
        for path in entries:
            is_folder = _is_dir(path)
            label = escape(path.name + ("/" if is_folder else ""))
            if self._many and not is_folder:
                widget = Checkbox(label, value=path in self._ticked)
            else:
                widget = Button(label)
            self._rows[widget] = path
            widgets.append(widget)
        if widgets:
            await box.mount(*widgets)
        note = ""
        if total > len(entries):
            note = f"Showing the first {len(entries)} of {total} entries."
        self.query_one("#pp-note", Static).update(note)

    # -- moving around ------------------------------------------------------

    async def _enter(self, folder: Path) -> None:
        if await self._show(folder):
            self._say()
        else:
            self._say(_CANT_OPEN)

    async def _go_to_text(self, text: str) -> None:
        text = text.strip()
        miss = _NO_PATH if self._files else _NO_FOLDER
        if not text:
            self._say(miss)
            return
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = self._cwd / path
        path = Path(os.path.normpath(path))
        if _is_dir(path):
            await self._enter(path)
        elif self._files and _is_file(path):
            self.dismiss([path] if self._many else path)
        else:
            self._say(miss)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.input.id == "pp-path":
            await self._go_to_text(event.value)

    async def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        if event.checkbox.id == "pp-hidden":
            self._hidden = event.value
            await self._enter(self._cwd)
            return
        path = self._rows.get(event.checkbox)
        if path is None:
            return
        if event.value:
            self._ticked.add(path)
        else:
            self._ticked.discard(path)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button = event.button
        if button in self._rows:
            await self._row_pressed(self._rows[button], button)
            return
        match button.id:
            case "pp-up":
                parent = self._cwd.parent
                if parent != self._cwd:
                    await self._enter(parent)
            case "pp-home":
                await self._enter(Path.home())
            case "pp-new":
                self.app.push_screen(_NewFolderScreen(self._cwd), self._new_folder_made)
            case "pp-choose":
                self._choose()
            case "pp-cancel":
                self.dismiss(None)

    async def _row_pressed(self, path: Path, button: Button) -> None:
        if _is_dir(path):
            await self._enter(path)
            return
        self._selected = path
        for widget, other in self._rows.items():
            if isinstance(widget, Button):
                name = escape(other.name + ("/" if _is_dir(other) else ""))
                widget.label = f"> {name}" if other == path else name
        self._say()

    async def _new_folder_made(self, created: Path | None) -> None:
        if created is not None:
            await self._enter(created)

    # -- result -------------------------------------------------------------

    def _choose(self) -> None:
        if not self._files:
            if _is_dir(self._cwd):
                self.dismiss(self._cwd)
            else:
                self._say(_NO_FOLDER)
            return
        if self._many:
            chosen = sorted(self._ticked)
            if not chosen:
                self._say("Tick at least one file")
                return
            if not all(_is_file(p) for p in chosen):
                self._say("A ticked file no longer exists")
                return
            self.dismiss(chosen)
            return
        if self._selected is None:
            self._say("Pick a file")
        elif not _is_file(self._selected):
            self._say("That file no longer exists")
        else:
            self.dismiss(self._selected)
