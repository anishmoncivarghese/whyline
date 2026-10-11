"""The ordered backup chain editor, before it is mounted on the bar."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox

from whyline.console import tui
from whyline.console.chain_editor import BackupChainScreen, OrderedChain

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

AGENTS = ["claude", "codex", "grok"]


class _ChainApp(App):
    def __init__(self, agents: list[str], fill=None) -> None:
        super().__init__()
        self.agents = list(agents)
        self.fill = fill

    def compose(self) -> ComposeResult:
        yield OrderedChain(self.agents, self.fill, id="chain")


class _ScreenApp(App):
    def __init__(self, screen: BackupChainScreen) -> None:
        super().__init__()
        self.opened = screen
        self.result: list[str] | None | str = "pending"

    def on_mount(self) -> None:
        self.push_screen(self.opened, self._done)

    def _done(self, result: list[str] | None) -> None:
        self.result = result


def _labels(chain: OrderedChain) -> list[str]:
    return [box.label.plain for box in chain.query("#chain-rows Checkbox")]


async def test_load_reads_back_the_checked_order_not_the_sorted_agent_list():
    app = _ChainApp(AGENTS)
    async with app.run_test(size=(90, 32)) as pilot:
        chain = app.query_one(OrderedChain)
        chain.load(["grok", "claude"])
        await pilot.pause()
        assert chain.order() == ["grok", "claude"]
        assert chain.order() != sorted(AGENTS)
        assert app.query_one("#chain-check-grok", Checkbox).value
        assert app.query_one("#chain-check-claude", Checkbox).value
        assert not app.query_one("#chain-check-codex", Checkbox).value


async def test_unknown_name_stays_visible_disabled_and_out_of_the_order():
    app = _ChainApp(AGENTS)
    async with app.run_test(size=(90, 32)) as pilot:
        chain = app.query_one(OrderedChain)
        chain.load(["grok", "retired", "claude"])
        await pilot.pause()
        retired = app.query_one("#chain-check-retired", Checkbox)
        assert _labels(chain)[-1] == "retired"
        assert retired.display
        assert retired.region.height > 0
        assert retired.disabled
        assert not retired.value
        assert app.query_one("#chain-up-retired", Button).disabled
        assert app.query_one("#chain-down-retired", Button).disabled
        assert chain.order() == ["grok", "claude"]
        assert "retired" not in chain.order()


async def test_up_moves_the_second_checked_agent_ahead_of_the_first():
    app = _ChainApp(AGENTS)
    async with app.run_test(size=(90, 32)) as pilot:
        chain = app.query_one(OrderedChain)
        chain.load(["grok", "claude"])
        await pilot.pause()
        await pilot.click("#chain-up-grok")
        await pilot.pause()
        assert chain.order() == ["grok", "claude"]
        assert await pilot.click("#chain-up-claude")
        await pilot.pause()
        assert chain.order() == ["claude", "grok"]


async def test_down_swaps_within_the_checked_order_and_stops_at_the_end():
    app = _ChainApp(AGENTS)
    async with app.run_test(size=(90, 32)) as pilot:
        chain = app.query_one(OrderedChain)
        chain.load(["grok", "claude"])
        await pilot.pause()
        await pilot.click("#chain-down-claude")
        await pilot.pause()
        assert chain.order() == ["grok", "claude"]
        assert await pilot.click("#chain-down-grok")
        await pilot.pause()
        assert chain.order() == ["claude", "grok"]


async def test_checking_appends_and_unchecking_removes():
    app = _ChainApp(AGENTS)
    async with app.run_test(size=(90, 32)) as pilot:
        chain = app.query_one(OrderedChain)
        chain.load(["grok"])
        await pilot.pause()
        assert await pilot.click("#chain-check-claude")
        await pilot.pause()
        assert chain.order() == ["grok", "claude"]
        assert await pilot.click("#chain-check-grok")
        await pilot.pause()
        assert chain.order() == ["claude"]


async def test_automatic_on_an_empty_widget_fills_the_provided_list():
    calls: list[str] = []

    def fill() -> list[str]:
        calls.append("fill")
        return ["grok", "codex"]

    app = _ChainApp(AGENTS, fill=fill)
    async with app.run_test(size=(90, 32)) as pilot:
        chain = app.query_one(OrderedChain)
        await pilot.pause()
        assert chain.order() == []
        assert await pilot.click("#chain-automatic")
        await pilot.pause()
        assert calls == ["fill"]
        assert chain.order() == ["grok", "codex"]


async def test_automatic_on_a_non_empty_widget_leaves_it():
    calls: list[str] = []

    def fill() -> list[str]:
        calls.append("fill")
        return ["codex"]

    app = _ChainApp(AGENTS, fill=fill)
    async with app.run_test(size=(90, 32)) as pilot:
        chain = app.query_one(OrderedChain)
        chain.load(["grok", "claude"])
        await pilot.pause()
        await pilot.click("#chain-automatic")
        await pilot.pause()
        assert chain.order() == ["grok", "claude"]
        assert calls == []


async def test_none_clears():
    app = _ChainApp(AGENTS)
    async with app.run_test(size=(90, 32)) as pilot:
        chain = app.query_one(OrderedChain)
        chain.load(["grok", "claude"])
        await pilot.pause()
        assert await pilot.click("#chain-none")
        await pilot.pause()
        assert chain.order() == []
        assert not any(box.value for box in chain.query("#chain-rows Checkbox"))


async def test_cancel_returns_none_and_writes_nothing():
    calls: list[str] = []

    def fill() -> list[str]:
        calls.append("fill")
        return ["codex"]

    screen = BackupChainScreen(
        AGENTS,
        ["grok", "claude"],
        fill=fill,
        busy=False,
        on_reset=lambda: calls.append("reset"),
    )
    app = _ScreenApp(screen)
    async with app.run_test(size=(90, 32)) as pilot:
        await pilot.pause()
        assert await pilot.click("#bc-cancel")
        await pilot.pause()
        assert app.result is None
        assert calls == []


async def test_save_dismisses_with_the_checked_order():
    app = _ScreenApp(BackupChainScreen(AGENTS, ["grok", "claude"], busy=False))
    async with app.run_test(size=(90, 32)) as pilot:
        await pilot.pause()
        assert await pilot.click("#bc-save")
        await pilot.pause()
        assert app.result == ["grok", "claude"]


@pytest.mark.parametrize("busy", [True, False])
async def test_reset_is_disabled_when_busy(busy: bool):
    calls: list[str] = []
    app = _ScreenApp(
        BackupChainScreen(
            AGENTS,
            ["grok"],
            busy=busy,
            on_reset=lambda: calls.append("reset"),
        )
    )
    async with app.run_test(size=(90, 32)) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#bc-reset", Button).disabled is busy
        await pilot.click("#bc-reset")
        await pilot.pause()
        if busy:
            assert calls == []
            assert app.result == "pending"
        else:
            assert calls == ["reset"]
            assert app.result == "pending"
            assert app.screen is app.opened
