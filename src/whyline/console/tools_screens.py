"""The Tools library: Connectors (MCP servers), Skills, Knowledge and Credentials.
Every action calls the same function the `whyline tools` and `whyline cred`
commands call."""
from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static, TabbedContent, TabPane, TextArea, Tree

from whyline import credentials
from whyline.agents import capabilities
from whyline.console.agents_screens import tool_kind
from whyline.tools import knowledge, mcp, mcp_config, skills, users

_SETUP = (("grok", "Set up grok"), ("antigravity", "Set up Antigravity"))
_NO_CRED = "(none)"
_ORIGIN_LABEL = {
    "whyline": "whyline",
    "whyline-repo": "whyline · repo",
    "claude": "Claude",
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


class SkillScreen(ModalScreen):
    """Write a new whyline skill, or change the description and text of one."""

    DEFAULT_CSS = _CSS.format(name="SkillScreen") + "SkillScreen TextArea { height: 12; }"

    def __init__(self, edit: str | None = None, root: Path | None = None) -> None:
        super().__init__()
        self._edit = edit
        self._root = root
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
    ToolsScreen .tl-row { height: auto; margin-top: 1; }
    ToolsScreen Button { margin-right: 1; }
    ToolsScreen .tl-status { height: auto; }
    """

    def __init__(self, *, test_fn=None) -> None:
        super().__init__()
        self._test_fn = test_fn or mcp_config.test_server
        self._ready: dict[str, bool] = {}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Tools", id="tl-title")
            with TabbedContent(id="tl-tabs"):
                with TabPane("Connectors", id="tl-connectors"):
                    yield Tree("Connectors", id="tl-tree")
                    yield Horizontal(
                        Button("Add", id="tl-add"),
                        Button("Import…", id="tl-import"),
                        Button("Test", id="tl-test"),
                        Button("Remove", id="tl-remove", variant="error"),
                        classes="tl-row",
                    )
                    yield Horizontal(
                        *[Button(label, id=f"tl-setup-{cli}") for cli, label in _SETUP],
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
        self.query_one("#tl-skill-table", DataTable).add_columns("Origin", "Name", "Size", "Description")
        self._reload()
        self._reload_skills()
        self._reload_packs()
        self._reload_creds()
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
                    tree.move_cursor(node)

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
            table.add_row(_ORIGIN_LABEL.get(s.origin, s.origin), s.name, _size(s.size), detail, key=s.ref)
        if select:
            for index, s in enumerate(found):
                if s.ref == select:
                    table.move_cursor(row=index)
        if not found:
            self._skill_say("No skills yet. Write one, or copy one from Claude.")
        self._skill_buttons()

    def _skill_selected(self) -> str | None:
        table = self.query_one("#tl-skill-table", DataTable)
        if table.row_count == 0 or not table.is_valid_coordinate((table.cursor_row, 0)):
            return None
        return table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value

    def _skill_buttons(self) -> None:
        ref = self._skill_selected()
        claude = ref is not None and ref.startswith("claude")
        mine = ref is not None and not claude
        self.query_one("#tl-skill-copy", Button).disabled = not claude
        self.query_one("#tl-skill-edit", Button).disabled = not mine
        self.query_one("#tl-skill-remove", Button).disabled = not mine

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
        elif ref.startswith("claude"):
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
        elif button_id == "tl-test":
            self._test()
        elif button_id == "tl-remove":
            self._remove()
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
