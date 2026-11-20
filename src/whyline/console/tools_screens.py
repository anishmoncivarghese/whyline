"""The Tools library: Connectors (MCP servers), Skills, Knowledge and Credentials.
Every action calls the same function the `whyline tools` and `whyline cred`
commands call."""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Checkbox, DataTable, Input, Label, OptionList, Select, Static, TabbedContent, TabPane, TextArea, Tree,
)
from textual.widgets.option_list import Option

from whyline import credentials
from whyline.agents import capabilities
from whyline.console.agents_screens import tool_kind
from whyline.tools import catalogue, knowledge, made, made_draft, mcp, mcp_config, registry, skill_draft, skill_install, skill_sources, skills, users
from whyline.tools import find as tools_find

_SETUP = (("grok", "Set up grok"), ("antigravity", "Set up Antigravity"))
_NO_CRED = "(none)"
_ORIGIN_LABEL = {
    "whyline": "whyline",
    "whyline-repo": "whyline · repo",
    "claude": "Claude",
    "agents": "~/.agents",
    "codex": "Codex",
    "claude-project": "Claude · project",
}
_PERSONAL, _REPO = "personal", "repo"
_NO_AGENTS_ON = {"antigravity": "Agents can't run on Antigravity yet"}

_CSS = """
{name} {{ align: center middle; }}
{name} > Vertical {{ width: 100; max-width: 100%; height: auto; max-height: 100%;
    padding: 0 2; border: thick $accent; background: $surface; }}
{name} Horizontal {{ height: auto; margin-top: 1; }}
{name} Button {{ margin-right: 1; }}
"""


def _server_state(server: mcp_config.Server) -> str:
    if not server.enabled:
        return "off"
    return "ready" if server.tools else "not tested"


def _size(count: int) -> str:
    return f"{count} B" if count < 1024 else f"{count / 1024:.1f} KB"


def _confirm(app, message: str, label: str, then) -> None:
    from whyline.console.tui import ConfirmScreen

    def answered(yes: bool | None) -> None:
        if yes:
            then()

    app.push_screen(ConfirmScreen(message, label), answered)


class AddServerScreen(ModalScreen):
    """Name, command, arguments and one environment variable filled from a credential."""

    DEFAULT_CSS = _CSS.format(name="AddServerScreen")

    def compose(self) -> ComposeResult:
        options = [(_NO_CRED, _NO_CRED)] + [(c.name, c.name) for c in credentials.list_all()]
        yield Vertical(
            Label("Add a connector"),
            Input(placeholder="name, for example github", id="as-name"),
            Input(placeholder="command, for example npx", id="as-command"),
            Input(placeholder="arguments, space separated", id="as-args"),
            Input(placeholder="environment variable, for example GITHUB_TOKEN", id="as-var"),
            Select(options, value=_NO_CRED, allow_blank=False, id="as-cred"),
            Static("", id="as-status", markup=False),
            Horizontal(Button("Add", id="as-add", variant="primary"), Button("Cancel", id="as-cancel")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "as-cancel":
            self.dismiss(None)
            return
        var = self.query_one("#as-var", Input).value.strip()
        cred = str(self.query_one("#as-cred", Select).value)
        env: dict[str, str] = {}
        if var or cred != _NO_CRED:
            if not var or cred == _NO_CRED:
                self._say("Give both the environment variable and the credential, or neither.")
                return
            env[var] = cred
        try:
            args = tuple(shlex.split(self.query_one("#as-args", Input).value))
            server = mcp_config.Server(
                name=self.query_one("#as-name", Input).value.strip(),
                command=self.query_one("#as-command", Input).value.strip(),
                args=args, env=env,
            )
            mcp_config.save_server(server)
        except ValueError as error:
            self._say(str(error))
            return
        self.dismiss(server.name)

    def _say(self, text: str) -> None:
        self.query_one("#as-status", Static).update(text)


class ImportServersScreen(ModalScreen):
    """A checklist of servers found in other tools' configs; only ticked ones are added."""

    DEFAULT_CSS = _CSS.format(name="ImportServersScreen") + "ImportServersScreen VerticalScroll { height: auto; max-height: 20; }"

    def __init__(self) -> None:
        super().__init__()
        self._candidates = mcp_config.import_candidates()

    def compose(self) -> ComposeResult:
        rows: list = []
        for index, c in enumerate(self._candidates):
            line = f"{c.name}  ({c.source})"
            if c.command:
                line += "  " + " ".join([c.command, *c.args])
            notes = c.notes()
            if notes:
                line += f"  [{'; '.join(notes)}]"
            rows.append(Checkbox(Text(line), id=f"im-{index}", disabled=bool(c.refused)))
        if not rows:
            rows.append(Label("No MCP servers found in Claude or Codex config."))
        yield Vertical(
            Label("Import connectors"),
            VerticalScroll(*rows),
            Static("", id="im-status", markup=False),
            Horizontal(Button("Import ticked", id="im-go", variant="primary"), Button("Cancel", id="im-cancel")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "im-cancel":
            self.dismiss(None)
            return
        added: list[str] = []
        for index, c in enumerate(self._candidates):
            if c.refused or not self.query_one(f"#im-{index}", Checkbox).value:
                continue
            mcp_config.save_server(mcp_config.Server(
                name=c.name, command=c.command, args=c.args, cwd=c.cwd))
            added.append(c.name)
        self.dismiss(added)


class CredentialScreen(ModalScreen):
    """Add a credential, or rotate one's value. The value goes in a masked field."""

    DEFAULT_CSS = _CSS.format(name="CredentialScreen")

    def __init__(self, rotate: str | None = None) -> None:
        super().__init__()
        self._rotate = rotate

    def compose(self) -> ComposeResult:
        title = f"Rotate {self._rotate}" if self._rotate else "Add a credential"
        body: list = [Label(title)]
        if not self._rotate:
            body.append(Input(placeholder="name, for example github-token", id="cr-name"))
        body.append(Input(placeholder="value", password=True, id="cr-value"))
        body.append(Static("", id="cr-status", markup=False))
        body.append(Horizontal(Button("Save", id="cr-save", variant="primary"), Button("Cancel", id="cr-cancel")))
        yield Vertical(*body)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "cr-cancel":
            self.dismiss(None)
            return
        field = self.query_one("#cr-value", Input)
        secret = field.value
        field.value = ""
        try:
            if self._rotate:
                credentials.rotate(self._rotate, secret)
                name = self._rotate
            else:
                name = self.query_one("#cr-name", Input).value.strip()
                credentials.save(credentials.Credential(name=name, kind="env"), secret)
        except (ValueError, KeyError, credentials.Locked) as error:
            self.query_one("#cr-status", Static).update(str(error))
            return
        self.dismiss(name)


class DraftScreen(ModalScreen):
    """A box for what the skill should do; the agent drafts it in a worker. Dismisses with
    (name, description, body) and saves nothing."""

    DEFAULT_CSS = _CSS.format(name="DraftScreen") + "DraftScreen TextArea { height: 8; }"

    def __init__(self, root: Path | None = None, ask_agent=None) -> None:
        super().__init__()
        self._root = root
        self._ask = ask_agent
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Draft a skill from a description"),
            TextArea("", id="dr-text"),
            Static("", id="dr-status", markup=False),
            Horizontal(Button("Draft", id="dr-go", variant="primary"), Button("Cancel", id="dr-cancel")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "dr-cancel":
            self.dismiss(None)
            return
        description = self.query_one("#dr-text", TextArea).text.strip()
        if self._busy:
            return
        if not description:
            self._say("Say what the skill should do.")
            return
        self._busy = True
        self._say("Drafting…")

        def in_thread() -> None:
            try:
                ask = self._ask
                if ask is None:
                    from whyline.release import plan as release_plan

                    ask = release_plan.default_ask_agent(self._root or Path.cwd())
                result, error = skill_draft.draft(description, ask_agent=ask), ""
            except Exception as failure:  # noqa: BLE001 - any failure is shown, never crashes the console
                result, error = None, str(failure) or type(failure).__name__
            self.app.call_from_thread(self._done, result, error)

        self.run_worker(in_thread, thread=True, group="dr-draft")

    def _done(self, result, error: str) -> None:
        self._busy = False
        if result is None:
            self._say(f"Could not draft it: {error}")
            return
        self.dismiss(result)

    def _say(self, text: str) -> None:
        self.query_one("#dr-status", Static).update(text)


class SkillScreen(ModalScreen):
    """Write a new whyline skill, or change the description and text of one."""

    DEFAULT_CSS = _CSS.format(name="SkillScreen") + "SkillScreen TextArea { height: 12; }"

    def __init__(self, edit: str | None = None, root: Path | None = None, ask_agent=None) -> None:
        super().__init__()
        self._edit = edit
        self._root = root
        self._ask = ask_agent
        self._skill = skills.get(edit, root) if edit else None

    def compose(self) -> ComposeResult:
        body: list = [Label(f"Edit {self._edit}" if self._edit else "New skill")]
        description, text = "", ""
        if self._skill is not None:
            description = self._skill.description
            try:
                text = skills.body_of((self._skill.path / "SKILL.md").read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                text = ""
        else:
            body.append(Button("Draft from a description…", id="sk-draft"))
            body.append(Input(placeholder="name, for example release-notes", id="sk-name"))
            where = [("Personal (all repositories)", _PERSONAL)]
            if self._root is not None:
                where.append(("This repository", _REPO))
            body.append(Select(where, value=_PERSONAL, allow_blank=False, id="sk-where"))
        body.append(Input(value=description, placeholder="description, one line", id="sk-description"))
        body.append(TextArea(text, id="sk-body"))
        body.append(Static("", id="sk-status", markup=False))
        body.append(Horizontal(Button("Save", id="sk-save", variant="primary"), Button("Cancel", id="sk-cancel")))
        yield Vertical(*body)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "sk-cancel":
            self.dismiss(None)
            return
        if event.button.id == "sk-draft":
            self.app.push_screen(DraftScreen(self._root, self._ask), self._drafted)
            return
        description = self.query_one("#sk-description", Input).value
        text = self.query_one("#sk-body", TextArea).text
        try:
            if self._edit:
                skill = skills.edit(self._edit, self._root, description=description, body=text)
            else:
                repo = self._root if self.query_one("#sk-where", Select).value == _REPO else None
                skill = skills.create(self.query_one("#sk-name", Input).value.strip(), description,
                                      text, repo_root=repo)
        except (ValueError, KeyError, OSError) as error:
            self.query_one("#sk-status", Static).update(str(error))
            return
        self.dismiss(skill.ref)

    def _drafted(self, result) -> None:
        if not result:
            return
        name, description, body = result
        self.query_one("#sk-name", Input).value = name
        self.query_one("#sk-description", Input).value = description
        self.query_one("#sk-body", TextArea).text = body
        self.query_one("#sk-status", Static).update("Drafted. Check it, then Save.")


class PackScreen(ModalScreen):
    """A new knowledge pack: a name and what it is for."""

    DEFAULT_CSS = _CSS.format(name="PackScreen")

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("New knowledge pack"),
            Input(placeholder="name, for example api-docs", id="pk-name"),
            Input(placeholder="description (optional)", id="pk-description"),
            Static("", id="pk-status", markup=False),
            Horizontal(Button("Create", id="pk-save", variant="primary"), Button("Cancel", id="pk-cancel")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "pk-cancel":
            self.dismiss(None)
            return
        name = self.query_one("#pk-name", Input).value.strip()
        try:
            if knowledge.valid_name(name):
                try:
                    knowledge.get_pack(name)
                except KeyError:
                    pass
                else:
                    raise ValueError(f"A knowledge pack named {name} already exists.")
            knowledge.save_pack(knowledge.Pack(name, self.query_one("#pk-description", Input).value.strip()))
        except ValueError as error:
            self.query_one("#pk-status", Static).update(str(error))
            return
        self.dismiss(name)


class PackItemScreen(ModalScreen):
    """Add files or folders (paths, space separated) or one web page address to a pack."""

    DEFAULT_CSS = _CSS.format(name="PackItemScreen")

    def __init__(self, pack: str, page: bool) -> None:
        super().__init__()
        self._pack = pack
        self._page = page

    def compose(self) -> ComposeResult:
        label = f"Add a web page to {self._pack}" if self._page else f"Add files to {self._pack}"
        hint = "address, starting http:// or https://" if self._page else "file or folder paths, space separated"
        yield Vertical(
            Label(label),
            Input(placeholder=hint, id="pi-value"),
            Static("", id="pi-status", markup=False),
            Horizontal(Button("Add", id="pi-add", variant="primary"), Button("Cancel", id="pi-cancel")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "pi-cancel":
            self.dismiss(None)
            return
        raw = self.query_one("#pi-value", Input).value.strip()
        try:
            if self._page:
                if not raw.lower().startswith(("http://", "https://")):
                    raise ValueError("A web page address starts with http:// or https://.")
                added = [raw]
            else:
                added = [str(Path(p).expanduser().resolve()) for p in shlex.split(raw)]
                if not added:
                    raise ValueError("Give at least one file or folder.")
                missing = [p for p in added if not Path(p).exists()]
                if missing:
                    raise ValueError(f"Not found: {', '.join(missing)}")
            pack = knowledge.get_pack(self._pack)
            items = pack.items + tuple(i for i in added if i not in pack.items)
            knowledge.save_pack(knowledge.Pack(pack.name, pack.description, items))
        except KeyError:
            self.query_one("#pi-status", Static).update(f"No knowledge pack named {self._pack}.")
            return
        except ValueError as error:
            self.query_one("#pi-status", Static).update(str(error))
            return
        self.dismiss(added)


_LINK_FORM = "https://github.com/<owner>/<repo>/tree/<branch>/<path to one skill folder>"
_LINK = re.compile(
    r"^https://github\.com/([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9._-]+)/tree/([^/\s]+)/([^\s]+?)/?$")
_FETCH_ERRORS = (RuntimeError, OSError, ValueError, subprocess.SubprocessError)


def parse_link(text: str) -> tuple[str, str, str, str]:
    """(owner, repo, branch, folder) from a GitHub link to one skill folder."""
    match = _LINK.match(text.strip())
    if match is None or ".." in match.group(4).split("/"):
        raise ValueError(f"Expected a link like {_LINK_FORM}")
    owner, repo, branch, folder = match.groups()
    return owner, repo.removesuffix(".git"), branch, folder


def _when(source: skill_sources.Source) -> str:
    if source.kind != "skills":
        return "not fetched (opens in the browser)"
    return skill_sources.fetched(source) or "never"


class AddSourceScreen(ModalScreen):
    """A skill source of your own: a name, a repository URL and the folder holding the skills."""

    DEFAULT_CSS = _CSS.format(name="AddSourceScreen")

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Add a skill source"),
            Input(placeholder="name, for example my-skills", id="ss-name"),
            Input(placeholder="https:// repository URL", id="ss-url"),
            Input(placeholder="folder with the skills (optional)", id="ss-path"),
            Static("", id="ss-status", markup=False),
            Horizontal(Button("Add", id="ss-add", variant="primary"), Button("Cancel", id="ss-cancel")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "ss-cancel":
            self.dismiss(None)
            return
        name = self.query_one("#ss-name", Input).value.strip()
        try:
            skill_sources.add(name, self.query_one("#ss-url", Input).value.strip(),
                              self.query_one("#ss-path", Input).value.strip())
        except (ValueError, OSError) as error:
            self.query_one("#ss-status", Static).update(str(error))
            return
        self.dismiss(name)


class SourcesScreen(ModalScreen):
    """Where skills come from: each source with its kind, licence and last fetch."""

    DEFAULT_CSS = _CSS.format(name="SourcesScreen") + "SourcesScreen DataTable { height: 10; }"

    def __init__(self) -> None:
        super().__init__()
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Skill sources"),
            DataTable(id="so-table", cursor_type="row"),
            Horizontal(
                Button("Add…", id="so-add"),
                Button("Turn off", id="so-toggle"),
                Button("Remove", id="so-remove", variant="error"),
                Button("Refresh", id="so-refresh"),
                Button("Open in browser", id="so-open"),
            ),
            Static("", id="so-status", markup=False),
            Horizontal(Button("Close", id="so-close")),
        )

    def on_mount(self) -> None:
        self.query_one("#so-table", DataTable).add_columns("Name", "Kind", "Licence", "Last fetch", "State")
        self._reload()

    def _say(self, text: str) -> None:
        self.query_one("#so-status", Static).update(text)

    def _reload(self, select: str | None = None) -> None:
        table = self.query_one("#so-table", DataTable)
        table.clear()
        found = skill_sources.load()
        for s in found:
            kind = f"{s.kind} · {'built-in' if s.builtin else 'yours'}"
            table.add_row(s.name, kind, s.licence or "not stated", _when(s),
                          "on" if s.enabled else "off", key=s.name)
        for index, s in enumerate(found):
            if s.name == select:
                table.move_cursor(row=index)
        self._buttons()

    def _selected(self) -> skill_sources.Source | None:
        table = self.query_one("#so-table", DataTable)
        if table.row_count == 0 or not table.is_valid_coordinate((table.cursor_row, 0)):
            return None
        name = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        return next((s for s in skill_sources.load() if s.name == name), None)

    def _buttons(self) -> None:
        source = self._selected()
        toggle = self.query_one("#so-toggle", Button)
        toggle.disabled = source is None or not source.builtin
        toggle.label = "Turn on" if source is not None and not source.enabled else "Turn off"
        self.query_one("#so-remove", Button).disabled = source is None or source.builtin
        self.query_one("#so-refresh", Button).disabled = source is None or source.kind != "skills" or self._busy
        self.query_one("#so-open", Button).disabled = source is None or source.kind != "directory"

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "so-table":
            self._buttons()

    def _add(self) -> None:
        def added(name: str | None) -> None:
            if name:
                self._reload(name)
                self._say(f"Added {name}. Refresh it to fetch its skills.")

        self.app.push_screen(AddSourceScreen(), added)

    def _toggle(self) -> None:
        source = self._selected()
        if source is None:
            return
        try:
            skill_sources.set_enabled(source.name, not source.enabled)
        except (ValueError, OSError) as error:
            self._say(str(error))
            return
        self._reload(source.name)
        self._say(f"Turned {source.name} {'off' if source.enabled else 'on'}.")

    def _remove(self) -> None:
        source = self._selected()
        if source is None:
            return
        try:
            skill_sources.remove(source.name)
        except (ValueError, OSError) as error:
            self._say(f"Not removed: {error}")
            return
        shutil.rmtree(skill_sources.clone_dir(source), ignore_errors=True)
        skill_sources._stamp(source).unlink(missing_ok=True)
        self._reload()
        self._say(f"Removed {source.name}.")

    def _refresh(self) -> None:
        source = self._selected()
        if source is None or self._busy:
            return
        self._busy = True
        self._buttons()
        self._say(f"Fetching {source.name}…")

        def in_thread() -> None:
            try:
                skill_sources.fetch(source)
                message = f"Fetched {source.name}."
            except _FETCH_ERRORS as error:
                message = f"Couldn't fetch {source.name}: {error}"
            self.app.call_from_thread(self._refreshed, source.name, message)

        self.run_worker(in_thread, thread=True, group="so-fetch")

    def _refreshed(self, name: str, message: str) -> None:
        if not self.is_attached:
            return
        self._busy = False
        self._reload(name)
        self._say(message)

    def _open(self) -> None:
        source = self._selected()
        if source is not None and source.kind == "directory":
            webbrowser.open(source.url)
            self._say(f"Opened {source.url} in your browser.")

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "so-close":
            self.dismiss(None)
        elif button_id == "so-add":
            self._add()
        elif button_id == "so-toggle":
            self._toggle()
        elif button_id == "so-remove":
            self._remove()
        elif button_id == "so-refresh":
            self._refresh()
        elif button_id == "so-open":
            self._open()


class LinkScreen(ModalScreen):
    """A link to one skill folder on GitHub."""

    DEFAULT_CSS = _CSS.format(name="LinkScreen")

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Add a skill from a link"),
            Input(placeholder=_LINK_FORM, id="lk-link"),
            Static("", id="lk-status", markup=False),
            Horizontal(Button("Add", id="lk-add", variant="primary"), Button("Cancel", id="lk-cancel")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "lk-cancel":
            self.dismiss(None)
            return
        try:
            parsed = parse_link(self.query_one("#lk-link", Input).value)
        except ValueError as error:
            self.query_one("#lk-status", Static).update(str(error))
            return
        self.dismiss(parsed)


class PreviewScreen(ModalScreen):
    """What a skill holds, before it is installed: warnings first, then the whole SKILL.md."""

    DEFAULT_CSS = _CSS.format(name="PreviewScreen") + "PreviewScreen VerticalScroll { height: 14; border: round $primary; }"

    def __init__(self, entry: skill_sources.Entry, preview: skill_install.Preview) -> None:
        super().__init__()
        self._entry = entry
        self._preview = preview

    def compose(self) -> ComposeResult:
        p = self._preview
        warnings = "\n".join(f"Warning: {w}" for w in p.warnings) or "No warnings."
        files = ", ".join(f"{name} ({_size(size)})" for name, size in p.files)
        yield Vertical(
            Label(f"{self._entry.name} · {self._entry.source}"),
            Static(warnings, id="pv-warnings", markup=False),
            Static(f"Licence: {p.licence}", id="pv-licence", markup=False),
            Static(f"Size: {_size(p.size)}", id="pv-size", markup=False),
            Static(f"Files: {files}", id="pv-files", markup=False),
            VerticalScroll(Static(p.skill_md, id="pv-text", markup=False)),
            Input(value=self._entry.name, id="pv-name"),
            Static("", id="pv-status", markup=False),
            Horizontal(
                Button("Install", id="pv-install", variant="primary"),
                Button("Install as…", id="pv-as"),
                Button("Close", id="pv-close"),
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#pv-name", Input).display = False

    def _install(self, name: str | None) -> None:
        try:
            skill = skill_install.install(self._entry, name=name)
        except (ValueError, KeyError, OSError, RuntimeError) as error:
            self.query_one("#pv-status", Static).update(f"Not installed: {error}")
            return
        self.dismiss(skill)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "pv-close":
            self.dismiss(None)
        elif button_id == "pv-install":
            self._install(None)
        elif button_id == "pv-as":
            field = self.query_one("#pv-name", Input)
            if not field.display:
                field.display = True
                field.focus()
                self.query_one("#pv-status", Static).update("Pick a name, then press Install as… again.")
            else:
                self._install(field.value.strip())


class UpdateScreen(ModalScreen):
    """The difference between an installed skill and its source."""

    DEFAULT_CSS = _CSS.format(name="UpdateScreen") + "UpdateScreen VerticalScroll { height: 20; border: round $primary; }"

    def __init__(self, name: str, diff: str) -> None:
        super().__init__()
        self._name = name
        self._diff = diff

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"Update {self._name}"),
            VerticalScroll(Static(self._diff, id="up-diff", markup=False)),
            Static("", id="up-status", markup=False),
            Horizontal(Button("Update", id="up-update", variant="primary"), Button("Cancel", id="up-cancel")),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "up-cancel":
            self.dismiss(None)
            return
        try:
            skill = skill_install.update(self._name)
        except (ValueError, KeyError, OSError, RuntimeError) as error:
            self.query_one("#up-status", Static).update(f"Not updated: {error}")
            return
        self.dismiss(skill)


class BrowseScreen(ModalScreen):
    """Search the skills in every turned-on source and open one to read before installing."""

    DEFAULT_CSS = _CSS.format(name="BrowseScreen") + "BrowseScreen OptionList { height: 16; }"

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[skill_sources.Entry] = []
        self._cancel = threading.Event()

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Browse skills"),
            Input(placeholder="search by name or description", id="br-search"),
            OptionList(id="br-results"),
            Static("", id="br-status", markup=False),
            Horizontal(
                Button("Add from a link…", id="br-link"),
                Button("Cancel", id="br-cancel"),
                Button("Close", id="br-close"),
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#br-cancel", Button).display = False
        todo = [s for s in skill_sources.load()
                if s.enabled and s.kind == "skills" and skill_sources.fetched(s) is None]
        if todo:
            self._fetch(todo)
        else:
            self._show()

    def _say(self, text: str) -> None:
        self.query_one("#br-status", Static).update(text)

    def _show(self) -> None:
        text = self.query_one("#br-search", Input).value
        if text.split():
            self._entries = skill_sources.search(text)
        else:
            self._entries = []
            for source in skill_sources.load():
                if source.enabled and skill_sources.fetched(source) is not None:
                    self._entries.extend(skill_sources.index(source))
            self._entries = self._entries[:skill_sources.MAX_RESULTS]
        licences = {s.name: s.licence or "no licence stated" for s in skill_sources.load()}
        results = self.query_one("#br-results", OptionList)
        results.clear_options()
        for e in self._entries:
            head = Text(f"{e.name} · {e.source} · {licences.get(e.source, '')}", style="bold")
            results.add_option(Option(Text("\n").join([head, Text(e.description)])))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "br-search":
            self._show()

    def _start(self, work, first: str) -> None:
        """Run ``work(cancel)`` in a worker with Cancel showing; nothing it reports after Cancel is used."""
        self._cancel = cancel = threading.Event()
        self.query_one("#br-cancel", Button).display = True
        self._say(f"Fetching {first}…")
        self.run_worker(lambda: work(cancel), thread=True, group="br-fetch")

    def _fetch(self, todo: list[skill_sources.Source]) -> None:
        def work(cancel: threading.Event) -> None:
            failed: list[str] = []
            for source in todo:
                if cancel.is_set():
                    return
                self.app.call_from_thread(self._fetching, cancel, source.name)
                try:
                    skill_sources.fetch(source)
                except _FETCH_ERRORS as error:
                    failed.append(f"Couldn't fetch {source.name}: {error}")
            if not cancel.is_set():
                self.app.call_from_thread(self._fetched, cancel, failed)

        self._start(work, todo[0].name)

    def _fetching(self, cancel: threading.Event, name: str) -> None:
        if self.is_attached and not cancel.is_set():
            self._say(f"Fetching {name}…")

    def _fetched(self, cancel: threading.Event, failed: list[str]) -> None:
        if not self.is_attached or cancel.is_set():
            return
        self.query_one("#br-cancel", Button).display = False
        self._say("\n".join(failed))
        self._show()

    def _stop(self) -> None:
        self._cancel.set()
        self.query_one("#br-cancel", Button).display = False

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if 0 <= event.option_index < len(self._entries):
            self._preview(self._entries[event.option_index])

    def _preview(self, entry: skill_sources.Entry) -> None:
        try:
            shown = skill_install.preview(entry)
        except (ValueError, OSError, RuntimeError) as error:
            self._say(f"Can't open {entry.name}: {error}")
            return

        def closed(skill) -> None:
            if skill is not None:
                self.dismiss(skill.ref)

        self.app.push_screen(PreviewScreen(entry, shown), closed)

    def _link(self) -> None:
        def given(parsed) -> None:
            if parsed:
                self._from_link(*parsed)

        self.app.push_screen(LinkScreen(), given)

    def _from_link(self, owner: str, repo: str, branch: str, folder: str) -> None:
        name = f"{owner}-{repo}".lower()
        try:
            if not any(s.name == name for s in skill_sources.load()):
                skill_sources.add(name, f"https://github.com/{owner}/{repo}", folder.rpartition("/")[0], branch)
        except (ValueError, OSError) as error:
            self._say(f"Not added: {error}")
            return
        source = next(s for s in skill_sources.load() if s.name == name)

        def work(cancel: threading.Event) -> None:
            try:
                skill_sources.fetch(source)
                error = ""
            except _FETCH_ERRORS as caught:
                error = f"Couldn't fetch {name}: {caught}"
            if not cancel.is_set():
                self.app.call_from_thread(self._linked, cancel, source, folder, error)

        self._start(work, name)

    def _linked(self, cancel: threading.Event, source: skill_sources.Source, folder: str, error: str) -> None:
        if not self.is_attached or cancel.is_set():
            return
        self.query_one("#br-cancel", Button).display = False
        self._say(error)
        self._show()
        if not error:
            self._preview(skill_sources.Entry(source.name, folder.rpartition("/")[2], "", folder, 0, ()))

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "br-close":
            self._stop()
            self.dismiss(None)
        elif button_id == "br-cancel":
            self._stop()
            self._say("Cancelled. Showing what is already there.")
            self._show()
        elif button_id == "br-link":
            self._link()


class CataloguePickScreen(ModalScreen):
    """The connector catalogue with a search box. Picking one dismisses with its name."""

    DEFAULT_CSS = _CSS.format(name="CataloguePickScreen") + "CataloguePickScreen OptionList { height: 16; }"

    def __init__(self) -> None:
        super().__init__()
        self._shown: list[catalogue.Entry] = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Add from catalogue"),
            Input(placeholder="search", id="cp-search"),
            OptionList(id="cp-list"),
            Horizontal(Button("Search more…", id="cp-more"), Button("Cancel", id="cp-cancel")),
        )

    def on_mount(self) -> None:
        self._fill("")

    def _fill(self, text: str) -> None:
        self._shown = catalogue.search(text)
        listing = self.query_one("#cp-list", OptionList)
        listing.clear_options()
        for e in self._shown:
            state = "added" if catalogue.added(e) else e.status
            listing.add_option(Option(Text(f"{e.title}  {state}  {e.about}")))

    def on_input_changed(self, event: "Input.Changed") -> None:
        event.stop()
        self._fill(event.value)

    def on_option_list_option_selected(self, event: "OptionList.OptionSelected") -> None:
        event.stop()
        self.dismiss(self._shown[event.option_index].name)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        if event.button.id == "cp-more":
            def picked(entry: "catalogue.Entry | None") -> None:
                if entry:
                    self.dismiss(entry)

            self.app.push_screen(RegistrySearchScreen(), picked)
            return
        self.dismiss(None)


class RegistrySearchScreen(ModalScreen):
    """Results from the public registry, not checked by whyline. Picking a usable one
    dismisses with its entry; refused results show their reason and cannot be picked."""

    DEFAULT_CSS = _CSS.format(name="RegistrySearchScreen") + "RegistrySearchScreen OptionList { height: 16; }"

    def __init__(self, *, search_fn=None) -> None:
        super().__init__()
        self._search_fn = search_fn or registry.search
        self._shown: list[catalogue.Entry] = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(registry.HEADING, id="rs-heading"),
            Input(placeholder="search, then press Enter", id="rs-search"),
            Static("", id="rs-note", markup=False),
            OptionList(id="rs-list"),
            Horizontal(Button("Cancel", id="rs-cancel")),
        )

    def on_input_submitted(self, event: "Input.Submitted") -> None:
        event.stop()
        text = event.value
        self.query_one("#rs-note", Static).update("Searching…")

        def in_thread() -> None:
            found = self._search_fn(text)
            self.app.call_from_thread(self._found, found, registry.last_error())

        self.run_worker(in_thread, thread=True, group="rs-search")

    def _found(self, found: list[catalogue.Entry], error: str) -> None:
        if not self.is_attached:
            return
        self._shown = found
        self.query_one("#rs-note", Static).update(error or ("" if found else "Nothing matches."))
        listing = self.query_one("#rs-list", OptionList)
        listing.clear_options()
        for e in found:
            if e.refused:
                listing.add_option(Option(Text(f"{e.title}  {e.refused}  {e.about}"), disabled=True))
            else:
                listing.add_option(Option(Text(f"{e.title}  {e.status}  {e.about}")))

    def on_option_list_option_selected(self, event: "OptionList.OptionSelected") -> None:
        event.stop()
        entry = self._shown[event.option_index]
        if not entry.refused:
            self.dismiss(entry)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        self.dismiss(None)


class CatalogueEntryScreen(ModalScreen):
    """One catalogue entry: what it runs, its tools, a box per credential, Test, the
    result. Add stays off until a Test has passed."""

    DEFAULT_CSS = _CSS.format(name="CatalogueEntryScreen") + (
        "CatalogueEntryScreen VerticalScroll { height: auto; max-height: 30; }")

    def __init__(self, entry: catalogue.Entry, *, test_fn=None) -> None:
        super().__init__()
        self._entry = entry
        self._test_fn = test_fn or mcp_config.test_server
        self._passed = False

    def compose(self) -> ComposeResult:
        e = self._entry
        tools = "\n".join(f"  {t.name}  {t.risk}" for t in e.tools) or "  (none listed)"
        rows: list = []
        for index, c in enumerate(e.credentials):
            rows.append(Label(Text(f"{c.label} ({c.var})")))
            rows.append(Static(c.where, markup=False))
            rows.append(Horizontal(
                Input(placeholder=c.var, password=True, id=f"ce-cred-{index}"),
                Button("Open", id=f"ce-open-{index}"),
            ))
        yield Vertical(
            Label(Text(e.title)),
            Static(f"Will run: {catalogue.command_line(e)}\nTools:\n{tools}", id="ce-about", markup=False),
            VerticalScroll(*rows),
            Static("", id="ce-result", markup=False),
            Horizontal(
                Button("Test", id="ce-test"),
                Button("Add", id="ce-add", variant="primary", disabled=True),
                Button("Cancel", id="ce-cancel"),
            ),
        )

    def _values(self) -> dict[str, str]:
        return {c.var: self.query_one(f"#ce-cred-{i}", Input).value
                for i, c in enumerate(self._entry.credentials)}

    def on_input_changed(self, event: "Input.Changed") -> None:
        event.stop()
        self._passed = False
        self.query_one("#ce-add", Button).disabled = True

    def _test(self) -> None:
        values = self._values()
        self.query_one("#ce-result", Static).update("Testing…")

        def in_thread() -> None:
            try:
                passed, message = catalogue.check(self._entry, values, test=self._test_fn)
            except (ValueError, KeyError, credentials.Locked) as error:
                passed, message = False, str(error)
            self.app.call_from_thread(self._tested, passed, message)

        self.run_worker(in_thread, thread=True, group="ce-test")

    def _tested(self, passed: bool, message: str) -> None:
        if not self.is_attached:
            return
        self._passed = passed
        self.query_one("#ce-add", Button).disabled = not passed
        self.query_one("#ce-result", Static).update(
            f"Passed: {message}" if passed else f"Test failed: {message}")

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id == "ce-cancel":
            self.dismiss(None)
        elif button_id == "ce-test":
            self._test()
        elif button_id.startswith("ce-open-"):
            webbrowser.open(self._entry.credentials[int(button_id.removeprefix("ce-open-"))].where)
        elif button_id == "ce-add" and self._passed:
            catalogue.enable(self._entry.name)
            self.dismiss(self._entry.name)


_FIND_BUTTON = {
    "connector": "Tick its tools", "catalogue": "Add…", "skill": "Add skill",
    "remote-skill": "Preview…", "registry": "Add…",
}
_FIND_HEADING = {
    "connector": "Connectors you have", "catalogue": "Catalogue", "skill": "Your skills",
    "remote-skill": "Skills in your sources", "registry": "Public registry (not checked by whyline)",
}
_COMING = "Coming in this release"


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _pairs(text: str, sep: str, what: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in _lines(text):
        key, found_sep, value = line.partition(sep)
        if not found_sep or not key.strip():
            raise made.MadeToolError(f"Write each {what} as name{sep}value, not {line!r}.")
        found[key.strip()] = value.strip()
    return found


def _inputs_from(text: str) -> list[made.ToolInput]:
    items = []
    for line in _lines(text):
        name, type_, required, about = ([*(p.strip() for p in line.split("|", 3)), "", "", ""][:4])
        items.append(made.ToolInput(name, type_ or "string", about, required.lower() != "optional"))
    return items


def _inputs_text(items: list[made.ToolInput]) -> str:
    return "\n".join(
        f"{i.name} | {i.type} | {'required' if i.required else 'optional'} | {i.about}" for i in items
    )


def _stored_credential(name: str) -> str | None:
    try:
        return credentials.value(name)
    except (KeyError, ValueError, credentials.Locked):
        return None


class TestToolScreen(ModalScreen):
    """Ask for a value per input, show the exact request, ask `Send it?`, show the answer."""

    __test__ = False
    DEFAULT_CSS = _CSS.format(name="TestToolScreen") + "TestToolScreen .tt-box { height: auto; }"

    def __init__(self, tool: made.MadeTool, *, get_credential=None, resolve=None, request=None) -> None:
        super().__init__()
        self._tool = tool
        self._get = get_credential or _stored_credential
        self._send_kw = {k: v for k, v in (("resolve", resolve), ("request", request)) if v}
        self._values: dict = {}
        self._busy = False

    def compose(self) -> ComposeResult:
        rows: list = [Label(f"Test {self._tool.name}"), Static(made_draft.send_line(self._tool), markup=False)]
        for i, item in enumerate(self._tool.inputs):
            rows.append(Input(placeholder=f"{item.name} ({item.type}) {item.about}".strip(), id=f"tt-in-{i}"))
        rows += [
            Static("", id="tt-request", markup=False, classes="tt-box"),
            Static("", id="tt-warn", markup=False, classes="tt-box"),
            Static("", id="tt-answer", markup=False, classes="tt-box"),
            Horizontal(
                Button("Show request", id="tt-show", variant="primary"),
                Button("Yes, send it", id="tt-send", disabled=True),
                Button("Close", id="tt-close"),
            ),
        ]
        yield Vertical(*rows)

    def _say(self, widget: str, text: str) -> None:
        self.query_one(widget, Static).update(text)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button = event.button.id
        if button == "tt-close":
            self.dismiss(None)
        elif button == "tt-show":
            self._show()
        elif button == "tt-send" and not self._busy:
            self._send()

    def _show(self) -> None:
        values = {}
        for i, item in enumerate(self._tool.inputs):
            text = self.query_one(f"#tt-in-{i}", Input).value
            if text or item.required:
                values[item.name] = text
        self.query_one("#tt-send", Button).disabled = True
        self._say("#tt-answer", "")
        try:
            shown = made_draft.preview(self._tool, values)
        except made.MadeToolError as error:
            self._say("#tt-request", str(error))
            self._say("#tt-warn", "")
            return
        self._values = values
        self._say("#tt-request", f"{shown}\n\nSend it?")
        self._say("#tt-warn", made_draft.really_does_it(self._tool))
        self.query_one("#tt-send", Button).disabled = False

    def _send(self) -> None:
        self._busy = True
        self.query_one("#tt-send", Button).disabled = True
        self._say("#tt-answer", "Sending…")

        def in_thread() -> None:
            try:
                answer = made_draft.send_test(self._tool, self._values, get_credential=self._get,
                                              **self._send_kw)
            except Exception as failure:  # noqa: BLE001 - shown, never crashes the console
                answer = f"It failed: {failure}"
            self.app.call_from_thread(self._answered, answer)

        self.run_worker(in_thread, thread=True, group="tt-send")

    def _answered(self, answer: str) -> None:
        self._busy = False
        self._say("#tt-answer", answer)


class MakeToolScreen(ModalScreen):
    """Describe a tool, let the agent draft it, edit every field, Test it, then Accept it.
    ``edit`` opens a saved tool instead. Dismisses with the tool name once saved."""

    DEFAULT_CSS = _CSS.format(name="MakeToolScreen") + """
    MakeToolScreen > Vertical { height: 100%; }
    MakeToolScreen TextArea { height: 5; }
    MakeToolScreen #mk-form { height: 1fr; }
    """

    def __init__(self, description: str = "", *, edit: str | None = None, root: Path | None = None,
                 ask_agent=None, get_credential=None, resolve=None, request=None) -> None:
        super().__init__()
        self._description = description
        self._edit = edit
        self._root = root
        self._ask = ask_agent
        self._test_kw = dict(get_credential=get_credential, resolve=resolve, request=request)
        self._old_name = edit or ""
        self._saved: made.MadeTool | None = made.load(edit) if edit else None
        self._ready = False
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Make a tool"),
            Label("What should the tool do?"),
            TextArea(self._description, id="mk-desc"),
            Horizontal(Button("Draft", id="mk-draft", variant="primary"), id="mk-draft-row"),
            VerticalScroll(
                Input(placeholder="name", id="mk-name"),
                Input(placeholder="what it does", id="mk-about"),
                Select([(m, m) for m in made.METHODS], value="GET", allow_blank=False, id="mk-method"),
                Input(placeholder="https://api.example.com/v1/{input}", id="mk-url"),
                Label("Headers, one per line: Name: value"),
                TextArea("", id="mk-headers"),
                Label("Query, one per line: name=value"),
                TextArea("", id="mk-query"),
                Label("Body (JSON, or empty)"),
                TextArea("", id="mk-body"),
                Label("Inputs, one per line: name | string, number or boolean | required or optional | about"),
                TextArea("", id="mk-inputs"),
                Input(placeholder="credential name (never its value)", id="mk-credential"),
                Input(placeholder="where it goes: header:Authorization or query:key", id="mk-credential-in"),
                Input(placeholder="pick: dotted path into the answer, or empty", id="mk-pick"),
                Select([(r, r) for r in made.RISKS], value="reads", allow_blank=False, id="mk-risk"),
                id="mk-form",
            ),
            Static("", id="mk-send", markup=False),
            Static("", id="mk-status", markup=False),
            Horizontal(
                Button("Test…", id="mk-test"),
                Button("Save", id="mk-save"),
                Button("Accept", id="mk-accept", variant="primary", disabled=True),
                Button("Cancel", id="mk-cancel"),
                id="mk-buttons",
            ),
        )

    def on_mount(self) -> None:
        for widget in ("#mk-form", "#mk-send", "#mk-buttons"):
            self.query_one(widget).display = False
        if self._saved is not None:
            self.query_one("#mk-desc").display = False
            self.query_one("#mk-draft-row").display = False
            self._fill(self._saved)
        elif self._description.strip():
            self.query_one("#mk-draft", Button).focus()

    # form <-> tool --------------------------------------------------------

    def _fill(self, tool: made.MadeTool) -> None:
        self._ready = False
        self.query_one("#mk-name", Input).value = tool.name
        self.query_one("#mk-about", Input).value = tool.about
        self.query_one("#mk-method", Select).value = tool.method if tool.method in made.METHODS else "GET"
        self.query_one("#mk-url", Input).value = tool.url
        self.query_one("#mk-headers", TextArea).text = "\n".join(f"{k}: {v}" for k, v in tool.headers.items())
        self.query_one("#mk-query", TextArea).text = "\n".join(f"{k}={v}" for k, v in tool.query.items())
        self.query_one("#mk-body", TextArea).text = tool.body
        self.query_one("#mk-inputs", TextArea).text = _inputs_text(tool.inputs)
        self.query_one("#mk-credential", Input).value = tool.credential
        self.query_one("#mk-credential-in", Input).value = tool.credential_in
        self.query_one("#mk-pick", Input).value = tool.pick
        self.query_one("#mk-risk", Select).value = tool.risk if tool.risk in made.RISKS else "reads"
        for widget in ("#mk-form", "#mk-send", "#mk-buttons"):
            self.query_one(widget).display = True
        self._ready = True
        self._refresh()

    def _tool(self) -> made.MadeTool:
        text = lambda w: self.query_one(w, TextArea).text  # noqa: E731
        value = lambda w: self.query_one(w, Input).value.strip()  # noqa: E731
        return made.MadeTool(
            name=value("#mk-name"),
            about=value("#mk-about"),
            method=str(self.query_one("#mk-method", Select).value),
            url=value("#mk-url"),
            headers=_pairs(text("#mk-headers"), ":", "header"),
            query=_pairs(text("#mk-query"), "=", "query"),
            body=text("#mk-body").strip(),
            inputs=_inputs_from(text("#mk-inputs")),
            credential=value("#mk-credential"),
            credential_in=value("#mk-credential-in"),
            pick=value("#mk-pick"),
            risk=str(self.query_one("#mk-risk", Select).value),
            accepted_hash=self._saved.accepted_hash if self._saved else "",
        )

    def _check(self) -> tuple[made.MadeTool | None, str]:
        try:
            tool = self._tool()
            made.validate(tool)
        except made.MadeToolError as error:
            return None, str(error)
        return tool, ""

    def _refresh(self) -> None:
        if not self._ready:
            return
        tool, problem = self._check()
        self.query_one("#mk-accept", Button).disabled = tool is None
        self.query_one("#mk-test", Button).disabled = tool is None
        self.query_one("#mk-send", Static).update(made_draft.send_line(tool) if tool else "")
        if tool is None:
            self._say(problem)
        elif made.accepted(tool):
            self._say("Accepted.")
        else:
            self._say("Not accepted yet. Test it, then press Accept.")

    def on_input_changed(self, event: "Input.Changed") -> None:
        self._refresh()

    def on_text_area_changed(self, event: "TextArea.Changed") -> None:
        self._refresh()

    def on_select_changed(self, event: "Select.Changed") -> None:
        self._refresh()

    def _say(self, text: str) -> None:
        self.query_one("#mk-status", Static).update(text)

    # actions --------------------------------------------------------------

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button = event.button.id
        if button == "mk-cancel":
            self.dismiss(None)
        elif button == "mk-draft":
            self._draft()
        elif button == "mk-test":
            tool, problem = self._check()
            if tool is None:
                self._say(problem)
            else:
                self.app.push_screen(TestToolScreen(tool, **{k: v for k, v in self._test_kw.items() if v}))
        elif button in ("mk-save", "mk-accept"):
            self._save(accept=button == "mk-accept")

    def _save(self, *, accept: bool) -> None:
        tool, problem = self._check()
        if tool is None:
            self._say(problem)
            return
        try:
            saved = made_draft.save_edit(tool, self._old_name)
            if accept:
                saved = made.accept(saved.name)
        except (made.MadeToolError, OSError) as error:
            self._say(str(error))
            return
        self._saved = saved
        self._old_name = saved.name
        if accept:
            self.dismiss(saved.name)
        else:
            self._refresh()
            self._say("Saved. Not accepted until you press Accept." if not made.accepted(saved) else "Saved.")

    def _draft(self) -> None:
        description = self.query_one("#mk-desc", TextArea).text.strip()
        if self._busy:
            return
        if not description:
            self._say("Say what the tool should do.")
            return
        self._busy = True
        self._say("Drafting…")

        def in_thread() -> None:
            try:
                ask = self._ask
                if ask is None:
                    from whyline.release import plan as release_plan

                    ask = release_plan.default_ask_agent(self._root or Path.cwd())
                result, error = made_draft.draft(description, ask_agent=ask), ""
            except Exception as failure:  # noqa: BLE001 - any failure is shown, never crashes the console
                result, error = None, str(failure) or type(failure).__name__
            self.app.call_from_thread(self._drafted, result, error)

        self.run_worker(in_thread, thread=True, group="mk-draft")

    def _drafted(self, result, error: str) -> None:
        self._busy = False
        if result is None:
            self._say(f"Could not draft it: {error}")
            return
        self._fill(result)
        self._say("Drafted. Check every field, Test it, then Accept.")


class FindBox(Vertical):
    """`What should the agent be able to do?` One search over connectors, catalogue,
    skills and sources. Nothing goes to the network until the registry button is pressed.
    ``on_hit(hit)`` does the host's action and may return a line to show."""

    DEFAULT_CSS = """
    FindBox { height: auto; border: round $primary; padding: 0 1; }
    FindBox Horizontal, FindBox HorizontalGroup { height: auto; }
    FindBox Button { margin-right: 1; }
    FindBox .fb-hits { height: auto; max-height: 12; }
    FindBox .fb-line { width: 1fr; }
    FindBox .fb-note { height: auto; }
    """

    def __init__(self, on_hit, *, prefix: str = "fb", registry_search=None, root=None,
                 on_make=None) -> None:
        super().__init__()
        self._on_hit = on_hit
        self._on_make = on_make
        self._p = prefix
        self._registry_search = registry_search or registry.search
        self._root = root or (lambda: None)
        self._hits: list[tools_find.Hit] = []

    def compose(self) -> ComposeResult:
        p = self._p
        yield Label("What should the agent be able to do?")
        yield Horizontal(
            Input(placeholder="for example: send email, read a spreadsheet", id=f"{p}-q"),
            Button("Find", id=f"{p}-find", variant="primary"),
            Button("Search the registry too", id=f"{p}-reg"),
        )
        yield VerticalScroll(id=f"{p}-hits", classes="fb-hits")
        yield Static("", id=f"{p}-note", markup=False, classes="fb-note")

    def _say(self, text: str) -> None:
        self.query_one(f"#{self._p}-note", Static).update(text)

    async def _show(self, hits: list[tools_find.Hit], note: str = "") -> None:
        self._hits = hits
        box = self.query_one(f"#{self._p}-hits", VerticalScroll)
        await box.remove_children()
        widgets: list = []
        last = ""
        for i, hit in enumerate(hits):
            if hit.kind != last:
                last = hit.kind
                widgets.append(Static(_FIND_HEADING[hit.kind], markup=False))
            widgets.append(HorizontalGroup(
                Static(f"{hit.title}  {hit.about}", classes="fb-line", markup=False),
                Button(_FIND_BUTTON[hit.kind], id=f"{self._p}-hit-{i}"),
            ))
        if not hits:
            make = Button("Make a tool…", id=f"{self._p}-make", disabled=self._on_make is None)
            widgets.append(Static(tools_find.NOTHING, id=f"{self._p}-none", markup=False))
            if self._on_make is None:
                make.tooltip = _COMING
                widgets.append(HorizontalGroup(make, Static(_COMING, markup=False)))
            else:
                widgets.append(HorizontalGroup(make))
        await box.mount(*widgets)
        self._say(note)

    async def _find(self, *, registry_too: bool) -> None:
        text = self.query_one(f"#{self._p}-q", Input).value.strip()
        if not text:
            self._say("Say what it should do first.")
            return
        hits = tools_find.match(text, root=self._root())
        if not registry_too:
            await self._show(hits)
            return
        await self._show(hits, "Searching the public registry…")

        def in_thread() -> None:
            found = tools_find.match(text, registry_search=self._registry_search, root=self._root())
            self.app.call_from_thread(self._found, found, registry.last_error())

        self.run_worker(in_thread, thread=True, group=f"{self._p}-search")

    async def _found(self, hits: list[tools_find.Hit], error: str) -> None:
        if self.is_attached:
            await self._show(hits, error)

    async def on_input_submitted(self, event: "Input.Submitted") -> None:
        event.stop()
        await self._find(registry_too=False)

    async def on_button_pressed(self, event: "Button.Pressed") -> None:
        button_id = event.button.id or ""
        if not button_id.startswith(f"{self._p}-"):
            return
        event.stop()
        if button_id == f"{self._p}-find":
            await self._find(registry_too=False)
        elif button_id == f"{self._p}-reg":
            await self._find(registry_too=True)
        elif button_id == f"{self._p}-make" and self._on_make is not None:
            text = self.query_one(f"#{self._p}-q", Input).value.strip()
            self._say(self._on_make(text) or "")
        elif "-hit-" in button_id:
            hit = self._hits[int(button_id.rsplit("-", 1)[1])]
            self._say(self._on_hit(hit) or "")


def open_entry(screen, entry: catalogue.Entry, test_fn, done) -> str:
    """The four-part screen for a catalogue or registry entry; ``done(name)`` runs once
    it is added. Returns a line to show when there is nothing to open."""
    if catalogue.added(entry):
        return f"{entry.title} is already added."
    screen.app.push_screen(CatalogueEntryScreen(entry, test_fn=test_fn), done)
    return ""


def open_preview(screen, entry: skill_sources.Entry, done) -> str:
    """Preview a skill in a source; ``done(skill)`` runs when it is installed."""
    try:
        shown = skill_install.preview(entry)
    except (ValueError, OSError, RuntimeError) as error:
        return f"Can't open {entry.name}: {error}"
    screen.app.push_screen(PreviewScreen(entry, shown), lambda skill: done(skill) if skill else None)
    return ""


class ToolsScreen(ModalScreen):
    """Connectors, Skills, Knowledge and Credentials in one place."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    ToolsScreen { align: center middle; }
    ToolsScreen > Vertical {
        width: 110; max-width: 100%; height: 100%; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    ToolsScreen TabbedContent { height: 1fr; }
    ToolsScreen Tree, ToolsScreen DataTable { height: 1fr; }
    ToolsScreen #tl-made { height: 6; }
    ToolsScreen .tl-row { height: auto; margin-top: 1; }
    ToolsScreen Button { margin-right: 1; }
    ToolsScreen .tl-status { height: auto; }
    """

    def __init__(self, *, test_fn=None, ask_agent=None) -> None:
        super().__init__()
        self._test_fn = test_fn or mcp_config.test_server
        self._ask_agent = ask_agent
        self._ready: dict[str, bool] = {}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Tools", id="tl-title")
            yield FindBox(self._found_hit, prefix="tl-find", root=self._root, on_make=self._make_tool)
            with TabbedContent(id="tl-tabs"):
                with TabPane("Connectors", id="tl-connectors"):
                    yield Tree("Connectors", id="tl-tree")
                    yield Horizontal(
                        Button("Add", id="tl-add"),
                        Button("Import…", id="tl-import"),
                        Button("Add from catalogue…", id="tl-catalogue"),
                        Button("Test", id="tl-test"),
                        Button("Remove", id="tl-remove", variant="error"),
                        classes="tl-row",
                    )
                    yield Horizontal(
                        *[Button(label, id=f"tl-setup-{cli}") for cli, label in _SETUP],
                        classes="tl-row",
                    )
                    yield DataTable(id="tl-made", cursor_type="row")
                    yield Horizontal(
                        Button("Make a tool…", id="tl-make"),
                        Button("Open", id="tl-made-open"),
                        Button("Remove", id="tl-made-remove", variant="error"),
                        classes="tl-row",
                    )
                    yield Static("", id="tl-setup-note", markup=False, classes="tl-status")
                    yield Static("", id="tl-status", markup=False, classes="tl-status")
                with TabPane("Skills", id="tl-skills"):
                    yield DataTable(id="tl-skill-table", cursor_type="row")
                    yield Horizontal(
                        Button("New skill", id="tl-skill-new"),
                        Button("Copy to whyline", id="tl-skill-copy"),
                        Button("Edit", id="tl-skill-edit"),
                        Button("Remove", id="tl-skill-remove", variant="error"),
                        classes="tl-row",
                    )
                    yield Horizontal(
                        Button("Browse…", id="tl-skill-browse"),
                        Button("Sources…", id="tl-skill-sources"),
                        Button("Update…", id="tl-skill-update"),
                        classes="tl-row",
                    )
                    yield Static("", id="tl-skill-status", markup=False, classes="tl-status")
                with TabPane("Knowledge", id="tl-knowledge"):
                    yield Tree("Knowledge", id="tl-pack-tree")
                    yield Horizontal(
                        Button("New pack", id="tl-pack-new"),
                        Button("Add files", id="tl-pack-files"),
                        Button("Add web page", id="tl-pack-page"),
                        Button("Remove", id="tl-pack-remove", variant="error"),
                        classes="tl-row",
                    )
                    yield Static("", id="tl-pack-status", markup=False, classes="tl-status")
                with TabPane("Credentials", id="tl-credentials"):
                    yield DataTable(id="tl-creds", cursor_type="row")
                    yield Horizontal(
                        Button("Add", id="tl-cred-add"),
                        Button("Rotate", id="tl-cred-rotate"),
                        Button("Remove", id="tl-cred-remove", variant="error"),
                        classes="tl-row",
                    )
                    yield Static("", id="tl-cred-status", markup=False, classes="tl-status")
            yield Horizontal(Button("Close", id="tl-close"), classes="tl-row")

    def on_mount(self) -> None:
        self.query_one("#tl-creds", DataTable).add_columns("Name", "Kind", "Last used")
        self.query_one("#tl-made", DataTable).add_columns("Tool you made", "State", "About")
        self.query_one("#tl-skill-table", DataTable).add_columns("Origin", "Name", "Size", "Description")
        self._reload()
        self._reload_skills()
        self._reload_packs()
        self._reload_creds()
        self._reload_made()
        self._setup_buttons()

    def action_close(self) -> None:
        self.dismiss(None)

    # Connectors ---------------------------------------------------------

    def _say(self, text: str) -> None:
        self.query_one("#tl-status", Static).update(text)

    def _reload(self, select: str | None = None) -> None:
        tree = self.query_one("#tl-tree", Tree)
        tree.clear()
        servers = mcp_config.load()
        for name, server in sorted(servers.items()):
            node = tree.root.add(
                f"{name}  {_server_state(server)}  {len(server.tools)} tools", data=name)
            for tool in server.tools:
                node.add_leaf(f"{tool.name}  {tool_kind(tool)}", data=name)
        tree.root.expand()
        if not servers:
            self._say("No connectors yet. Add one, or import from Claude or Codex.")
        if select:
            for node in tree.root.children:
                if node.data == select:
                    self.call_after_refresh(tree.move_cursor, node)

    def _selected(self) -> str | None:
        node = self.query_one("#tl-tree", Tree).cursor_node
        if node is None or node.data is None:
            return None
        return str(node.data)

    def _add(self) -> None:
        def added(name: str | None) -> None:
            if name:
                self._reload(name)
                self._say(f"Added MCP server {name}.")

        self.app.push_screen(AddServerScreen(), added)

    def _catalogue(self) -> None:
        def chosen(picked: "str | catalogue.Entry | None") -> None:
            if isinstance(picked, catalogue.Entry):
                entry = picked
            else:
                entry = next((e for e in catalogue.load() if e.name == picked), None)
            if entry is not None:
                self._add_entry(entry)

        self.app.push_screen(CataloguePickScreen(), chosen)

    def _add_entry(self, entry: catalogue.Entry) -> str:
        def done(added: str | None) -> None:
            if added:
                self._reload(added)
                self._say(f"Added MCP server {added}.")

        said = open_entry(self, entry, self._test_fn, done)
        if said:
            self._reload(entry.name)
            self._say(said)
        return said

    def _open_tab(self, tab: str) -> None:
        self.query_one("#tl-tabs", TabbedContent).active = tab

    def _found_hit(self, hit: "tools_find.Hit") -> str:
        """The button on a Find result."""
        if hit.kind == "connector":
            self._open_tab("tl-connectors")
            self._reload(hit.ref)
            return f"{hit.ref} is in Connectors. Tick its tools when you add tools to an agent."
        if hit.kind in ("catalogue", "registry"):
            self._open_tab("tl-connectors")
            return self._add_entry(hit.item)
        if hit.kind == "skill":
            self._open_tab("tl-skills")
            self._reload_skills(hit.ref)
            return f"{hit.title} is already in your skills. Tick it when you add skills to an agent."

        def installed(skill) -> None:
            self._open_tab("tl-skills")
            self._reload_skills(skill.ref)
            self._skill_say(f"Installed {skill.ref}.")

        return open_preview(self, hit.item, installed)

    def _import(self) -> None:
        def done(names: list[str] | None) -> None:
            if names is None:
                return
            self._reload(names[0] if names else None)
            self._say(f"Added MCP server {', '.join(names)}." if names else "Nothing ticked, nothing added.")

        self.app.push_screen(ImportServersScreen(), done)

    def _test(self) -> None:
        name = self._selected()
        if name is None:
            self._say("Pick a connector first.")
            return
        self._say(f"Testing {name}…")

        def in_thread() -> None:
            try:
                message = f"{name}: {self._test_fn(name)}"
            except KeyError:
                message = f"No MCP server named {name}."
            except mcp.McpError as error:
                message = f"Test failed: {error}"
            except Exception as error:
                message = f"Test failed: {error}"
            self.app.call_from_thread(self._tested, name, message)

        self.run_worker(in_thread, thread=True, group="tl-test")

    def _tested(self, name: str, message: str) -> None:
        if not self.is_attached:
            return
        self._reload(name)
        self._say(message)

    def _remove(self) -> None:
        name = self._selected()
        if name is None:
            self._say("Pick a connector first.")
            return
        try:
            mcp_config.remove_server(name)
        except KeyError:
            self._say(f"No MCP server named {name}.")
        except ValueError as error:
            self._say(f"Not removed: {error}.")
        else:
            self._reload()
            self._say(f"Removed MCP server {name}.")

    # Set up grok / Antigravity ------------------------------------------

    def _setup_buttons(self) -> None:
        notes: list[str] = []
        for cli, _label in _SETUP:
            button = self.query_one(f"#tl-setup-{cli}", Button)
            binary = capabilities._SAVED_BINARY[cli]
            if shutil.which(binary) is None:
                button.disabled = True
                notes.append(f"{binary} is not installed, so there is nothing to set up.")
            else:
                notes.append(f"{binary}: checking…")
            if cli in _NO_AGENTS_ON and not capabilities.can_run(cli):
                notes.append(_NO_AGENTS_ON[cli] + ". You can still save the entry ahead.")
        self.query_one("#tl-setup-note", Static).update("\n".join(notes))
        for cli, _label in _SETUP:
            if shutil.which(capabilities._SAVED_BINARY[cli]) is not None:
                self._check_ready(cli)

    def _check_ready(self, cli: str) -> None:
        def in_thread() -> None:
            ready = capabilities.saved_ready(cli)
            self.app.call_from_thread(self._checked, cli, ready)

        self.run_worker(in_thread, thread=True, group=f"tl-ready-{cli}")

    def _checked(self, cli: str, ready: bool) -> None:
        if not self.is_attached:
            return
        self._ready[cli] = ready
        notes: list[str] = []
        for name, _label in _SETUP:
            binary = capabilities._SAVED_BINARY[name]
            if shutil.which(binary) is None:
                notes.append(f"{binary} is not installed, so there is nothing to set up.")
            elif name in self._ready:
                notes.append(f"{binary}: whyline's tools are "
                             f"{'saved' if self._ready[name] else 'not saved yet'}.")
            else:
                notes.append(f"{binary}: checking…")
            if name in _NO_AGENTS_ON and not capabilities.can_run(name):
                notes.append(_NO_AGENTS_ON[name] + ". You can still save the entry ahead.")
        self.query_one("#tl-setup-note", Static).update("\n".join(notes))

    def _setup(self, cli: str) -> None:
        binary = capabilities._SAVED_BINARY[cli]
        if self._ready.get(cli):
            self._say(f"whyline is already set up in {binary}.")
            return
        _confirm(self.app, f"Add whyline's tools to {binary}'s saved MCP servers?", "Add",
                 lambda: self._run_setup(cli))

    def _run_setup(self, cli: str) -> None:
        def in_thread() -> None:
            try:
                message = capabilities.saved_setup(cli)
            except ValueError as error:
                message = str(error)
            self.app.call_from_thread(self._set_up, cli, message)

        self._say("Setting up…")
        self.run_worker(in_thread, thread=True, group=f"tl-setup-{cli}")

    def _set_up(self, cli: str, message: str) -> None:
        if not self.is_attached:
            return
        self._say(message)
        self._check_ready(cli)

    # Made tools ---------------------------------------------------------

    def _reload_made(self, select: str | None = None) -> None:
        table = self.query_one("#tl-made", DataTable)
        table.clear()
        for tool in made.load_all():
            table.add_row(tool.name, "Accepted" if made.accepted(tool) else "Not accepted", tool.about,
                          key=tool.name)
        if select and select in {t.name for t in made.load_all()}:
            table.move_cursor(row=table.get_row_index(select))

    def _made_selected(self) -> str | None:
        table = self.query_one("#tl-made", DataTable)
        if table.row_count == 0 or not table.is_valid_coordinate((table.cursor_row, 0)):
            return None
        return table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value

    def _make_tool(self, description: str, edit: str | None = None) -> str:
        """Open the Make a tool screen; returns a line to show."""
        def done(name: str | None) -> None:
            self._reload_made(name)
            if name:
                self._open_tab("tl-connectors")
                self._say(f"Accepted made tool {name}.")

        self.app.push_screen(
            MakeToolScreen(description, edit=edit, root=self._root(), ask_agent=self._ask_agent), done)
        return ""

    def _open_made(self) -> None:
        name = self._made_selected()
        if name is None:
            self._say("Pick a made tool first.")
            return
        self._make_tool("", edit=name)

    def _remove_made(self) -> None:
        name = self._made_selected()
        if name is None:
            self._say("Pick a made tool first.")
            return
        made.remove(name)
        self._reload_made()
        self._say(f"Removed made tool {name}.")

    # Skills -------------------------------------------------------------

    def _root(self) -> Path | None:
        root = getattr(getattr(self.app, "session", None), "root", None)
        return Path(root) if root is not None else None

    def _skill_say(self, text: str) -> None:
        self.query_one("#tl-skill-status", Static).update(text)

    def _reload_skills(self, select: str | None = None) -> None:
        table = self.query_one("#tl-skill-table", DataTable)
        table.clear()
        found = skills.find(self._root())
        for s in found:
            detail = f"broken: {s.problem}" if s.broken else s.description
            origin = skill_install.source_of(s.name) if s.origin == "whyline" else None
            if origin and origin.get("source"):
                detail = f"from {origin['source']} · {detail}"
            table.add_row(_ORIGIN_LABEL.get(s.origin, s.origin), s.name, _size(s.size), detail, key=s.ref)
        if select:
            for index, s in enumerate(found):
                if s.ref == select:
                    table.move_cursor(row=index)
        if not found:
            self._skill_say("No skills yet. Write one, or copy one from another tool.")
        self._skill_buttons()

    def _skill_selected(self) -> str | None:
        table = self.query_one("#tl-skill-table", DataTable)
        if table.row_count == 0 or not table.is_valid_coordinate((table.cursor_row, 0)):
            return None
        return table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value

    def _skill_buttons(self) -> None:
        ref = self._skill_selected()
        mine = ref is not None and ref.partition(":")[0] in skills.OWN_ORIGINS
        other = ref is not None and not mine
        self.query_one("#tl-skill-copy", Button).disabled = not other
        self.query_one("#tl-skill-edit", Button).disabled = not mine
        self.query_one("#tl-skill-remove", Button).disabled = not mine
        self.query_one("#tl-skill-update", Button).disabled = not (
            ref is not None and ref.startswith("whyline:") and skill_install.source_of(ref.partition(":")[2]))

    def _skill_browse(self) -> None:
        def installed(ref: str | None) -> None:
            self._reload_skills(ref)
            if ref:
                self._skill_say(f"Installed {ref.partition(':')[2]}. Add it to an agent in New agent → Add skills.")

        self.app.push_screen(BrowseScreen(), installed)

    def _skill_sources(self) -> None:
        self.app.push_screen(SourcesScreen())

    def _skill_update(self) -> None:
        ref = self._skill_selected()
        if ref is None:
            self._skill_say("Pick a skill first.")
            return
        name = ref.partition(":")[2]
        try:
            diff = skill_install.update_diff(name)
        except (ValueError, OSError) as error:
            self._skill_say(f"Not updated: {error}")
            return
        if not diff:
            self._skill_say("Already up to date")
            return

        def updated(skill) -> None:
            if skill is not None:
                self._reload_skills(skill.ref)
                self._skill_say(f"Updated {skill.name}.")

        self.app.push_screen(UpdateScreen(name, diff), updated)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "tl-skill-table":
            self._skill_buttons()

    def _skill_form(self, edit: str | None) -> None:
        def saved(ref: str | None) -> None:
            if ref:
                self._reload_skills(ref)
                self._skill_say(f"{'Updated' if edit else 'Created'} {ref}.")

        try:
            form = SkillScreen(edit, self._root())
        except (KeyError, ValueError):
            self._skill_say(f"No skill {edit}.")
            return
        self.app.push_screen(form, saved)

    def _skill_copy(self) -> None:
        ref = self._skill_selected()
        if ref is None:
            self._skill_say("Pick a skill first.")
            return
        try:
            skill = skills.copy_to_whyline(ref, self._root())
        except (KeyError, ValueError, OSError) as error:
            self._skill_say(f"Not copied: {error}")
            return
        self._reload_skills(skill.ref)
        self._skill_say(f"Copied to {skill.ref}.")

    def _skill_edit(self) -> None:
        ref = self._skill_selected()
        if ref is None:
            self._skill_say("Pick a skill first.")
        elif ref.partition(":")[0] not in skills.OWN_ORIGINS:
            self._skill_say(skills.CLAUDE_REFUSAL)
        else:
            self._skill_form(ref)

    def _skill_remove(self) -> None:
        ref = self._skill_selected()
        if ref is None:
            self._skill_say("Pick a skill first.")
            return
        try:
            skills.remove(ref, self._root())
        except (KeyError, ValueError, OSError) as error:
            self._skill_say(f"Not removed: {error}")
            return
        self._reload_skills()
        self._skill_say(f"Removed {ref}.")

    # Knowledge ----------------------------------------------------------

    def _pack_say(self, text: str) -> None:
        self.query_one("#tl-pack-status", Static).update(text)

    def _reload_packs(self, select: str | None = None) -> None:
        tree = self.query_one("#tl-pack-tree", Tree)
        tree.clear()
        found = knowledge.list_packs()
        for pack in found:
            node = tree.root.add(f"{pack.name}  {len(pack.items)} items"
                                 + (f"  {pack.description}" if pack.description else ""), data=pack.name)
            for item in pack.items:
                node.add_leaf(item, data=pack.name)
        tree.root.expand()
        if not found:
            self._pack_say("No knowledge packs yet. Create one, then add files or web pages.")
        if select:
            for node in tree.root.children:
                if node.data == select:
                    node.expand()
                    self.call_after_refresh(tree.move_cursor, node)

    def _pack_selected(self) -> str | None:
        node = self.query_one("#tl-pack-tree", Tree).cursor_node
        if node is None or node.data is None:
            return None
        return str(node.data)

    def _pack_new(self) -> None:
        def made(name: str | None) -> None:
            if name:
                self._reload_packs(name)
                self._pack_say(f"Created knowledge pack {name}.")

        self.app.push_screen(PackScreen(), made)

    def _pack_add(self, page: bool) -> None:
        name = self._pack_selected()
        if name is None:
            self._pack_say("Pick a pack first.")
            return

        def added(items: list[str] | None) -> None:
            if items:
                self._reload_packs(name)
                self._pack_say(f"Added {', '.join(items)} to {name}.")

        self.app.push_screen(PackItemScreen(name, page), added)

    def _pack_remove(self) -> None:
        name = self._pack_selected()
        if name is None:
            self._pack_say("Pick a pack first.")
            return
        try:
            knowledge.remove_pack(name)
        except KeyError:
            self._pack_say(f"No knowledge pack named {name}.")
        except ValueError as error:
            self._pack_say(f"Not removed: {error}.")
        else:
            self._reload_packs()
            self._pack_say(f"Removed knowledge pack {name}.")

    # Credentials --------------------------------------------------------

    def _cred_say(self, text: str) -> None:
        self.query_one("#tl-cred-status", Static).update(text)

    def _reload_creds(self) -> None:
        table = self.query_one("#tl-creds", DataTable)
        table.clear()
        found = credentials.list_all()
        for c in found:
            table.add_row(c.name, c.kind, c.last_used or "never", key=c.name)
        if not found:
            self._cred_say("No credentials stored.")

    def _cred_selected(self) -> str | None:
        table = self.query_one("#tl-creds", DataTable)
        if table.row_count == 0 or not table.is_valid_coordinate((table.cursor_row, 0)):
            return None
        return table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value

    def _cred_form(self, rotate: str | None) -> None:
        def saved(name: str | None) -> None:
            if name:
                self._reload_creds()
                self._cred_say(f"{'Rotated' if rotate else 'Stored'} credential {name}.")

        self.app.push_screen(CredentialScreen(rotate), saved)

    def _cred_remove(self) -> None:
        name = self._cred_selected()
        if name is None:
            self._cred_say("Pick a credential first.")
            return
        in_use = users.of("credential", name)
        if in_use:
            self._cred_say(f"Not removed: {name} is used by {', '.join(in_use)}.")
            return
        credentials.remove(name)
        self._reload_creds()
        self._cred_say(f"Removed credential {name}.")

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id == "tl-close":
            self.dismiss(None)
        elif button_id == "tl-add":
            self._add()
        elif button_id == "tl-import":
            self._import()
        elif button_id == "tl-catalogue":
            self._catalogue()
        elif button_id == "tl-test":
            self._test()
        elif button_id == "tl-remove":
            self._remove()
        elif button_id == "tl-make":
            self._say(self._make_tool(""))
        elif button_id == "tl-made-open":
            self._open_made()
        elif button_id == "tl-made-remove":
            self._remove_made()
        elif button_id.startswith("tl-setup-"):
            self._setup(button_id.removeprefix("tl-setup-"))
        elif button_id == "tl-skill-new":
            self._skill_form(None)
        elif button_id == "tl-skill-copy":
            self._skill_copy()
        elif button_id == "tl-skill-edit":
            self._skill_edit()
        elif button_id == "tl-skill-remove":
            self._skill_remove()
        elif button_id == "tl-skill-browse":
            self._skill_browse()
        elif button_id == "tl-skill-sources":
            self._skill_sources()
        elif button_id == "tl-skill-update":
            self._skill_update()
        elif button_id == "tl-pack-new":
            self._pack_new()
        elif button_id == "tl-pack-files":
            self._pack_add(False)
        elif button_id == "tl-pack-page":
            self._pack_add(True)
        elif button_id == "tl-pack-remove":
            self._pack_remove()
        elif button_id == "tl-cred-add":
            self._cred_form(None)
        elif button_id == "tl-cred-rotate":
            name = self._cred_selected()
            if name is None:
                self._cred_say("Pick a credential first.")
            else:
                self._cred_form(name)
        elif button_id == "tl-cred-remove":
            self._cred_remove()
