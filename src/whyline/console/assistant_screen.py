"""Assistant actions, reminders, and recent request history for the console."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static

from whyline.ideas import actions, memory, reminders, requests, store, telegram_in

NO_ALLOWED_CHAT = "No allowed Telegram chat to deliver reminders."


def _cell(value: object) -> Text:
    """Render database values literally rather than as Rich markup."""
    return Text("" if value is None else str(value), no_wrap=True, end="")


def _approvals(action: actions.Action) -> list[tuple[str, str]]:
    allowed = actions.APPROVALS
    if action.writes or action.min_approval == "tap":
        allowed = ("tap",)
    return [(value, value) for value in allowed]


class AssistantScreen(ModalScreen):
    """Stage assistant policy changes, reminders, and show recent requests."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    AssistantScreen { align: center middle; }
    AssistantScreen > Vertical {
        width: 110; max-width: 100%; height: 100%; max-height: 100%;
        padding: 0 1; border: thick $accent; background: $surface;
    }
    AssistantScreen #as-body { height: 1fr; }
    AssistantScreen .as-section { text-style: bold; margin-top: 1; }
    AssistantScreen .as-action { height: 3; }
    AssistantScreen .as-action Checkbox {
        width: 23; height: 1; border: none; padding: 0 1; margin: 1 0;
    }
    AssistantScreen .as-action Checkbox:focus { border: none; }
    AssistantScreen .as-summary { width: 1fr; height: 3; padding: 1 1; }
    AssistantScreen .as-action Select { width: 12; }
    AssistantScreen .as-reminder-row { height: 3; }
    AssistantScreen .as-reminder-due { width: 18; padding: 1 1; }
    AssistantScreen .as-reminder-text { width: 1fr; padding: 1 1; }
    AssistantScreen .as-reminder-cancel { min-width: 8; width: auto; margin-right: 1; }
    AssistantScreen #as-reminders-empty { padding: 1 1; color: $text-muted; }
    AssistantScreen #as-reminder-add-row { height: auto; margin-top: 1; }
    AssistantScreen #as-reminder-when { width: 22; margin-right: 1; }
    AssistantScreen #as-reminder-text { width: 1fr; margin-right: 1; }
    AssistantScreen #as-reminder-add { min-width: 8; width: auto; margin-right: 1; }
    AssistantScreen #as-reminder-error { height: auto; max-height: 3; color: $error; }
    AssistantScreen #as-reminder-error.-empty { display: none; }
    AssistantScreen .as-memory-row { height: 3; }
    AssistantScreen .as-memory-num { width: 4; padding: 1 0; }
    AssistantScreen .as-memory-text { width: 1fr; padding: 1 1; }
    AssistantScreen .as-memory-edit-input { width: 1fr; margin-right: 1; }
    AssistantScreen .as-memory-edit { min-width: 8; width: auto; margin-right: 1; }
    AssistantScreen .as-memory-forget { min-width: 8; width: auto; margin-right: 1; }
    AssistantScreen .as-memory-save { min-width: 8; width: auto; margin-right: 1; }
    AssistantScreen .as-memory-cancel-edit { min-width: 8; width: auto; margin-right: 1; }
    AssistantScreen #as-memory-empty { padding: 1 1; color: $text-muted; }
    AssistantScreen #as-memory-controls { height: auto; margin-top: 1; }
    AssistantScreen #as-memory-add-text { width: 1fr; margin-right: 1; }
    AssistantScreen #as-memory-add { min-width: 8; width: auto; margin-right: 1; }
    AssistantScreen #as-memory-clear { min-width: 10; width: auto; margin-right: 1; }
    AssistantScreen #as-memory-error { height: auto; max-height: 3; color: $error; }
    AssistantScreen #as-memory-error.-empty { display: none; }
    AssistantScreen #as-history { height: 12; min-height: 4; }
    AssistantScreen #as-error { height: auto; max-height: 3; color: $error; }
    AssistantScreen #as-error.-empty { display: none; }
    AssistantScreen #as-check-result { height: auto; max-height: 12; }
    AssistantScreen #as-check-result.-empty { display: none; }
    AssistantScreen #as-buttons { height: auto; margin-top: 1; }
    AssistantScreen #as-buttons Button { min-width: 8; width: auto; margin-right: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        conn = store.connect()
        try:
            self._initial = actions.policy(conn)
            self._history = requests.history(conn, limit=50)
            self._reminders = reminders.pending(conn)
            self._memory = memory.show()
            self._editing_memory_line: int | None = None
        finally:
            conn.close()

    def _make_reminder_row(self, reminder: reminders.Reminder) -> Horizontal:
        due = reminder.due_at.replace("T", " ")[:16]
        return Horizontal(
            Static(due, classes="as-reminder-due", markup=False),
            Static(reminder.text, classes="as-reminder-text", markup=False),
            Button(
                "Cancel",
                id=f"as-reminder-cancel-{reminder.id}",
                classes="as-reminder-cancel",
            ),
            id=f"as-reminder-{reminder.id}",
            classes="as-reminder-row",
        )

    def _make_memory_row(self, i: int, fact: str) -> Horizontal:
        if self._editing_memory_line == i:
            return Horizontal(
                Static(f"{i}.", classes="as-memory-num", markup=False),
                Input(value=fact, id=f"as-memory-edit-input-{i}", classes="as-memory-edit-input"),
                Button("Save", id=f"as-memory-save-{i}", classes="as-memory-save"),
                Button("Cancel", id=f"as-memory-cancel-edit-{i}", classes="as-memory-cancel-edit"),
                id=f"as-memory-{i}",
                classes="as-memory-row",
            )
        return Horizontal(
            Static(f"{i}.", classes="as-memory-num", markup=False),
            Static(fact, id=f"as-memory-text-{i}", classes="as-memory-text", markup=False),
            Button("Edit", id=f"as-memory-edit-{i}", classes="as-memory-edit"),
            Button("Forget", id=f"as-memory-forget-{i}", classes="as-memory-forget"),
            id=f"as-memory-{i}",
            classes="as-memory-row",
        )

    def reminder_cancel_button(self, reminder_id: int) -> Button:
        try:
            return self.query_one(f"#as-reminder-cancel-{reminder_id}", Button)
        except Exception:
            return self.query_one(f"#as-cancel-reminder-{reminder_id}", Button)

    def reminder_add_button(self) -> Button:
        try:
            return self.query_one("#as-reminder-add", Button)
        except Exception:
            return self.query_one("#as-add-reminder", Button)

    def memory_forget_button(self, n: int) -> Button:
        try:
            return self.query_one(f"#as-memory-forget-{n}", Button)
        except Exception:
            return self.query_one(f"#as-forget-memory-{n}", Button)

    def memory_edit_button(self, n: int) -> Button:
        try:
            return self.query_one(f"#as-memory-edit-{n}", Button)
        except Exception:
            return self.query_one(f"#as-edit-memory-{n}", Button)

    def memory_save_button(self, n: int) -> Button:
        try:
            return self.query_one(f"#as-memory-save-{n}", Button)
        except Exception:
            return self.query_one(f"#as-save-memory-{n}", Button)

    def memory_clear_button(self) -> Button:
        try:
            return self.query_one("#as-memory-clear", Button)
        except Exception:
            return self.query_one("#as-clear-memory", Button)

    def memory_add_button(self) -> Button:
        try:
            return self.query_one("#as-memory-add", Button)
        except Exception:
            return self.query_one("#as-add-memory", Button)

    def compose(self) -> ComposeResult:
        action_rows = []
        for name, action in actions.REGISTRY.items():
            saved = self._initial[name]
            action_rows.append(
                Horizontal(
                    Checkbox(name, value=saved["enabled"], id=f"as-enabled-{name}"),
                    Static(action.summary, markup=False, classes="as-summary"),
                    Select(
                        _approvals(action),
                        value=saved["approval"],
                        allow_blank=False,
                        id=f"as-approval-{name}",
                    ),
                    id=f"as-action-{name}",
                    classes="as-action",
                )
            )

        reminder_rows = []
        if not self._reminders:
            reminder_rows.append(
                Static("No reminders.", id="as-reminders-empty", markup=False)
            )
        else:
            for item in self._reminders:
                reminder_rows.append(self._make_reminder_row(item))

        memory_rows = []
        if not self._memory:
            memory_rows.append(
                Static("No memory.", id="as-memory-empty", markup=False)
            )
        else:
            for i, fact in enumerate(self._memory, 1):
                memory_rows.append(self._make_memory_row(i, fact))

        table = DataTable(id="as-history", cursor_type="row")
        table.add_column("Time", key="time")
        table.add_column("Channel", key="channel")
        table.add_column("Action", key="action")
        table.add_column("State", key="state")
        table.add_column("Error / result", key="outcome")
        for request in self._history:
            table.add_row(
                _cell(request.created_at),
                _cell(request.channel),
                _cell(request.action),
                _cell(request.state),
                _cell(request.error or request.result_path),
                key=str(request.id),
            )

        yield Vertical(
            Label("Assistant", id="as-title"),
            VerticalScroll(
                Label("Actions", classes="as-section", id="as-actions-title"),
                *action_rows,
                Label("Reminders", classes="as-section", id="as-reminders-title"),
                Vertical(*reminder_rows, id="as-reminders"),
                Horizontal(
                    Input(placeholder="When", id="as-reminder-when"),
                    Input(placeholder="Text", id="as-reminder-text"),
                    Button("Add", id="as-reminder-add"),
                    id="as-reminder-add-row",
                ),
                Static("", id="as-reminder-error", markup=False, classes="-empty"),
                Label("Memory", classes="as-section", id="as-memory-title"),
                Vertical(*memory_rows, id="as-memory"),
                Horizontal(
                    Input(placeholder="Fact", id="as-memory-add-text"),
                    Button("Add", id="as-memory-add"),
                    Button("Clear all", id="as-memory-clear"),
                    id="as-memory-controls",
                ),
                Static("", id="as-memory-error", markup=False, classes="-empty"),
                Label("History", classes="as-section", id="as-history-title"),
                table,
                id="as-body",
            ),
            Static("", id="as-error", markup=False, classes="-empty"),
            Static("", id="as-check-result", markup=False, classes="-empty"),
            Horizontal(
                Button("Check", id="as-check"),
                Button("Save", id="as-save", variant="success"),
                Button("Cancel", id="as-cancel"),
                id="as-buttons",
            ),
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "as-cancel":
            event.stop()
            self.action_cancel()
        elif button_id == "as-check":
            event.stop()
            self._check()
        elif button_id == "as-save":
            event.stop()
            self._save()
        elif button_id in ("as-reminder-add", "as-add-reminder"):
            event.stop()
            self._add_reminder()
        elif button_id.startswith("as-reminder-cancel-") or button_id.startswith(
            "as-cancel-reminder-"
        ):
            event.stop()
            parts = button_id.split("-")
            try:
                reminder_id = int(parts[-1])
                self._cancel_reminder(reminder_id)
            except ValueError:
                pass
        elif button_id in ("as-memory-add", "as-add-memory"):
            event.stop()
            self._add_memory()
        elif button_id in ("as-memory-clear", "as-clear-memory"):
            event.stop()
            self._clear_all_memory()
        elif button_id.startswith("as-memory-edit-") or button_id.startswith("as-edit-memory-"):
            event.stop()
            parts = button_id.split("-")
            try:
                n = int(parts[-1])
                self._start_edit_memory(n)
            except ValueError:
                pass
        elif button_id.startswith("as-memory-save-") or button_id.startswith("as-save-memory-"):
            event.stop()
            parts = button_id.split("-")
            try:
                n = int(parts[-1])
                self._save_memory_edit(n)
            except ValueError:
                pass
        elif button_id.startswith("as-memory-cancel-edit-"):
            event.stop()
            self._cancel_edit_memory()
        elif button_id.startswith("as-memory-forget-") or button_id.startswith("as-forget-memory-"):
            event.stop()
            parts = button_id.split("-")
            try:
                n = int(parts[-1])
                self._forget_memory(n)
            except ValueError:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "as-reminder-when":
            event.stop()
            text_input = self.query_one("#as-reminder-text", Input)
            if not text_input.value.strip():
                text_input.focus()
                return
            self._add_reminder()
        elif event.input.id == "as-reminder-text":
            event.stop()
            self._add_reminder()
        elif event.input.id == "as-memory-add-text":
            event.stop()
            self._add_memory()
        elif event.input.id and event.input.id.startswith("as-memory-edit-input-"):
            event.stop()
            n = int(event.input.id.removeprefix("as-memory-edit-input-"))
            self._save_memory_edit(n)

    def _check(self) -> None:
        from whyline.ideas import cli as ideas_cli

        # The same function `whyline idea doctor` runs. Read-only, so it
        # does not create a ledger the way store.connect would.
        conn = ideas_cli._read_only_conn()
        try:
            checks = ideas_cli.assistant_doctor(conn)
        finally:
            if conn is not None:
                conn.close()
        result = self.query_one("#as-check-result", Static)
        result.update(
            "\n".join(f"{c.level:<6} {c.name}: {c.detail}" for c in checks)
        )
        result.set_class(False, "-empty")

    def _set_error(self, message: str) -> None:
        error = self.query_one("#as-error", Static)
        error.update(message)
        error.set_class(not message, "-empty")

    def _set_reminder_error(self, message: str) -> None:
        try:
            error = self.query_one("#as-reminder-error", Static)
            error.update(message)
            error.set_class(not message, "-empty")
        except Exception:
            pass

    def _add_reminder(self) -> None:
        when_input = self.query_one("#as-reminder-when", Input)
        text_input = self.query_one("#as-reminder-text", Input)
        when_text = when_input.value.strip()
        text_text = text_input.value.strip()

        if not when_text:
            self._set_reminder_error(reminders.BAD_TIME)
            return

        now = datetime.now().astimezone().replace(tzinfo=None)
        try:
            due, rest = reminders.parse_when(when_text, now)
        except (reminders.TimeParseError, ValueError) as exc:
            self._set_reminder_error(str(exc))
            return

        body = (f"{rest} {text_text}" if rest else text_text).strip()
        if not body:
            self._set_reminder_error(reminders.BAD_TIME)
            return

        conn = store.connect()
        try:
            chats = telegram_in.allowed_chats(conn)
            if not chats:
                self._set_reminder_error(NO_ALLOWED_CHAT)
                return
            chat_id = chats[0]
            reminders.create(conn, chat_id, due, body, now=now)
        except (reminders.TimeParseError, ValueError) as exc:
            self._set_reminder_error(str(exc))
            return
        except Exception as exc:
            self._set_reminder_error(str(exc))
            return
        finally:
            conn.close()

        when_input.value = ""
        text_input.value = ""
        self._set_reminder_error("")
        self._refresh_reminders()

    def _cancel_reminder(self, reminder_id: int) -> None:
        conn = store.connect()
        try:
            reminders.cancel(conn, reminder_id)
        finally:
            conn.close()
        self._refresh_reminders()

    def _refresh_reminders(self) -> None:
        conn = store.connect()
        try:
            self._reminders = reminders.pending(conn)
        finally:
            conn.close()
        container = self.query_one("#as-reminders", Vertical)
        container.remove_children()
        for child in list(container.children):
            container._nodes._remove(child)
        if not self._reminders:
            container.mount(
                Static("No reminders.", id="as-reminders-empty", markup=False)
            )
        else:
            for item in self._reminders:
                container.mount(self._make_reminder_row(item))

    def _set_memory_error(self, message: str) -> None:
        try:
            error = self.query_one("#as-memory-error", Static)
            error.update(message)
            error.set_class(not message, "-empty")
        except Exception:
            pass

    def _add_memory(self) -> None:
        text_input = self.query_one("#as-memory-add-text", Input)
        text = text_input.value.strip()
        if not text:
            return
        try:
            memory.add(text)
        except Exception as exc:
            self._set_memory_error(str(exc))
            return
        text_input.value = ""
        self._set_memory_error("")
        self._refresh_memory()

    def _forget_memory(self, n: int) -> None:
        try:
            memory.forget(n)
        except Exception as exc:
            self._set_memory_error(str(exc))
            return
        self._set_memory_error("")
        self._refresh_memory()

    def _start_edit_memory(self, n: int) -> None:
        self._editing_memory_line = n
        self._set_memory_error("")
        self._refresh_memory()

    def _save_memory_edit(self, n: int) -> None:
        try:
            edit_input = self.query_one(f"#as-memory-edit-input-{n}", Input)
            text = edit_input.value.strip()
            memory.edit(n, text)
        except Exception as exc:
            self._set_memory_error(str(exc))
            return
        self._editing_memory_line = None
        self._set_memory_error("")
        self._refresh_memory()

    def _cancel_edit_memory(self) -> None:
        self._editing_memory_line = None
        self._set_memory_error("")
        self._refresh_memory()

    def _clear_all_memory(self) -> None:
        from whyline.console.tui import ConfirmScreen

        def confirmed(yes: bool) -> None:
            if yes:
                try:
                    memory.clear()
                except Exception as exc:
                    self._set_memory_error(str(exc))
                    return
                self._set_memory_error("")
                self._refresh_memory()

        self.app.push_screen(
            ConfirmScreen("Clear all memory?", "Clear all"), confirmed
        )

    def _refresh_memory(self) -> None:
        self._memory = memory.show()
        container = self.query_one("#as-memory", Vertical)
        container.remove_children()
        for child in list(container.children):
            container._nodes._remove(child)
        if not self._memory:
            container.mount(
                Static("No memory.", id="as-memory-empty", markup=False)
            )
        else:
            for i, fact in enumerate(self._memory, 1):
                container.mount(self._make_memory_row(i, fact))

    def _save(self) -> None:
        changed = []
        for name in actions.REGISTRY:
            enabled = self.query_one(f"#as-enabled-{name}", Checkbox).value
            approval = self.query_one(f"#as-approval-{name}", Select).value
            current = {"enabled": bool(enabled), "approval": str(approval)}
            if current != self._initial[name]:
                changed.append((name, current))

        conn = store.connect()
        try:
            for name, current in changed:
                actions.set_policy(
                    conn,
                    name,
                    enabled=current["enabled"],
                    approval=current["approval"],
                )
                self._initial[name] = current
        except Exception as error:
            self._set_error(str(error) or error.__class__.__name__)
            return
        finally:
            conn.close()
        self.dismiss(True)
