"""Assistant actions, reminders, and recent request history for the console."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static

from whyline.ideas import actions, reminders, requests, store, telegram_in

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
    AssistantScreen #as-history { height: 12; min-height: 4; }
    AssistantScreen #as-error { height: auto; max-height: 3; color: $error; }
    AssistantScreen #as-error.-empty { display: none; }
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
                Label("History", classes="as-section", id="as-history-title"),
                table,
                id="as-body",
            ),
            Static("", id="as-error", markup=False, classes="-empty"),
            Horizontal(
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
