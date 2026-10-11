"""Ordered backup chain: the checked order, not the installed-agent list.

Unknown config names stay on screen and disabled, so opening a chain does
not hide a name this install cannot run. They are not part of ``order()``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label

_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _slug(name: str) -> str:
    """A Textual id fragment. Agent names already fit; config names may not."""
    if _ID.fullmatch(name):
        return name
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"n-{cleaned}" if cleaned else "n"
    return cleaned


def _slugs(names: list[str]) -> dict[str, str]:
    used: set[str] = set()
    out: dict[str, str] = {}
    for name in names:
        base = _slug(name)
        slug = base
        number = 2
        while slug in used:
            slug = f"{base}-{number}"
            number += 1
        used.add(slug)
        out[name] = slug
    return out


class _ChainCheck(Checkbox):
    def __init__(self, agent: str, slug: str, *, value: bool, disabled: bool) -> None:
        super().__init__(agent, value=value, disabled=disabled, id=f"chain-check-{slug}")
        self.agent_name = agent


class _ChainButton(Button):
    def __init__(self, label: str, agent: str, kind: str, slug: str, *, disabled: bool) -> None:
        super().__init__(label, id=f"chain-{kind}-{slug}", disabled=disabled)
        self.agent_name = agent
        self.kind = kind


class OrderedChain(Vertical):
    """One row per installed agent, plus unknown names parked at the end.

    Checking appends. Unchecking removes. Up and Down swap inside the
    checked order and do nothing at the ends. ``order()`` is that checked
    order. Automatic asks ``fill`` only while the order is empty. None
    clears the checks and leaves unknown names where they are.
    """

    DEFAULT_CSS = """
    OrderedChain { height: auto; width: 1fr; }
    OrderedChain Horizontal { height: auto; }
    OrderedChain #chain-rows { height: auto; }
    OrderedChain Checkbox { border: none; height: 1; padding: 0 1; margin: 0; width: 1fr; }
    OrderedChain Checkbox:focus { border: none; }
    OrderedChain .chain-row Button { min-width: 8; width: auto; margin-left: 1; }
    OrderedChain #chain-actions { margin-top: 1; }
    OrderedChain #chain-actions Button { margin-right: 1; }
    """

    def __init__(
        self,
        agents: list[str],
        fill: Callable[[], list[str]] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self._agents = list(dict.fromkeys(agents))
        self._agent_set = set(self._agents)
        self._fill = fill
        self._order: list[str] = []
        self._unknown: list[str] = []

    def compose(self) -> ComposeResult:
        yield Vertical(id="chain-rows")
        yield Horizontal(
            Button("Automatic", id="chain-automatic"),
            Button("None", id="chain-none"),
            id="chain-actions",
        )

    def on_mount(self) -> None:
        self._sync()

    def load(self, chain: list[str]) -> None:
        """Check ``chain`` in that order. Unknown names stay visible, disabled, last."""
        known: list[str] = []
        unknown: list[str] = []
        seen: set[str] = set()
        for agent in chain:
            if agent in seen:
                continue
            seen.add(agent)
            if agent in self._agent_set:
                known.append(agent)
            else:
                unknown.append(agent)
        self._order = known
        self._unknown = unknown
        self._sync()

    def order(self) -> list[str]:
        """Checked agents, in the order they were checked or moved."""
        return list(self._order)

    def on_checkbox_changed(self, event: "Checkbox.Changed") -> None:
        box = event.control
        if not isinstance(box, _ChainCheck):
            return
        agent = box.agent_name
        if agent not in self._agent_set:
            return
        checked = agent in self._order
        if event.value == checked:
            return
        if event.value:
            self._order.append(agent)
        else:
            self._order.remove(agent)
        self._sync()

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        button = event.button
        if isinstance(button, _ChainButton):
            event.stop()
            self._move(button.agent_name, -1 if button.kind == "up" else 1)
            return
        if button.id == "chain-automatic":
            event.stop()
            self._automatic()
        elif button.id == "chain-none":
            event.stop()
            self._clear()

    def _display_names(self) -> list[str]:
        checked = [agent for agent in self._order if agent in self._agent_set]
        rest = [agent for agent in self._agents if agent not in self._order]
        return checked + rest + list(self._unknown)

    def _move(self, agent: str, delta: int) -> None:
        if agent not in self._order:
            return
        index = self._order.index(agent)
        target = index + delta
        if target < 0 or target >= len(self._order):
            return
        self._order[index], self._order[target] = self._order[target], self._order[index]
        self._sync()

    def _automatic(self) -> None:
        if self._order or self._fill is None:
            return
        self.load(list(self._fill()))

    def _clear(self) -> None:
        self._order = []
        self._sync()

    def _sync(self) -> None:
        if not self.is_mounted:
            return
        rows = self.query_one("#chain-rows", Vertical)
        # remove_children prunes on the next beat. Detach now so the new
        # rows can reuse the same ids. Same sequence as AttachmentTray.
        rows.remove_children()
        for child in list(rows.children):
            rows._nodes._remove(child)
        names = self._display_names()
        slugs = _slugs(names)
        last = len(self._order) - 1
        for agent in names:
            known = agent in self._agent_set
            checked = agent in self._order
            index = self._order.index(agent) if checked else -1
            rows.mount(
                Horizontal(
                    _ChainCheck(agent, slugs[agent], value=checked, disabled=not known),
                    _ChainButton(
                        "Up",
                        agent,
                        "up",
                        slugs[agent],
                        disabled=not checked or index == 0,
                    ),
                    _ChainButton(
                        "Down",
                        agent,
                        "down",
                        slugs[agent],
                        disabled=not checked or index == last,
                    ),
                    id=f"chain-row-{slugs[agent]}",
                    classes="chain-row",
                )
            )


class BackupChainScreen(ModalScreen[list[str] | None]):
    """Edit a backup chain. Save returns the order. Cancel returns nothing.

    Reset is disabled while ``busy`` is true. It does not write config and
    does not close the screen; the bar owns failover and passes ``on_reset``.
    """

    DEFAULT_CSS = """
    BackupChainScreen { align: center middle; }
    BackupChainScreen > Vertical {
        width: 78; max-width: 100%; height: auto; max-height: 100%;
        padding: 0 2; border: thick $accent; background: $surface;
    }
    BackupChainScreen Vertical, BackupChainScreen Horizontal { height: auto; }
    BackupChainScreen #bc-buttons { margin-top: 1; }
    BackupChainScreen #bc-buttons Button { margin-right: 1; }
    """

    def __init__(
        self,
        agents: list[str],
        chain: list[str] | None = None,
        fill: Callable[[], list[str]] | None = None,
        *,
        busy: bool,
        on_reset: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._agents = list(agents)
        self._chain = list(chain or [])
        self._fill = fill
        self._busy = busy
        self._on_reset = on_reset

    def compose(self) -> ComposeResult:
        chain = OrderedChain(self._agents, self._fill, id="bc-chain")
        chain.load(self._chain)
        yield Vertical(
            Label("Backup, used when an agent fails:"),
            chain,
            Horizontal(
                Button("Reset failover", id="bc-reset", disabled=self._busy),
                Button("Save", id="bc-save", variant="success"),
                Button("Cancel", id="bc-cancel"),
                id="bc-buttons",
            ),
        )

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        button_id = event.button.id
        if button_id == "bc-cancel":
            event.stop()
            self.dismiss(None)
        elif button_id == "bc-save":
            event.stop()
            self.dismiss(self.query_one(OrderedChain).order())
        elif button_id == "bc-reset":
            event.stop()
            if self._busy or self._on_reset is None:
                return
            self._on_reset()
