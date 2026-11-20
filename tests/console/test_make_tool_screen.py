import pytest

from whyline.console import tui
from whyline.console.tools_screens import MakeToolScreen, TestToolScreen, ToolsScreen
from whyline.tools import made

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]

ANSWER = """```toml
name = "weather"
about = "Weather for a city"
method = "GET"
url = "https://api.example.com/v1/{city}"
credential = "weather-key"
credential_in = "header:Authorization"
pick = "summary"
risk = "reads"

[[inputs]]
name = "city"
type = "string"
about = "City"
required = true
```"""


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr("shutil.which", lambda binary: None)


class Net:
    def __init__(self):
        self.sent = []

    def resolve(self, host):
        return ["93.184.216.34"]

    def request(self, method, url, headers, body, **kw):
        self.sent.append((method, url, dict(headers)))
        return 200, {}, b'{"summary": "sunny"}'


async def _drafted(app, pilot, answer=ANSWER):
    asked = []
    net = Net()
    screen = MakeToolScreen("weather by city", ask_agent=lambda q: asked.append(q) or answer,
                            get_credential=lambda n: "s3cr3t", resolve=net.resolve, request=net.request)
    app.push_screen(screen)
    await pilot.pause()
    assert not screen.query_one("#mk-form").display
    screen.query_one("#mk-draft").press()
    await pilot.pause()
    await screen.workers.wait_for_complete()
    await pilot.pause()
    return screen, net, asked


async def test_description_then_drafting_then_the_form_with_every_field(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        screen, _net, asked = await _drafted(app, pilot)
        assert "weather by city" in asked[0]
        assert screen.query_one("#mk-form").display
        assert screen.query_one("#mk-name").value == "weather"
        assert screen.query_one("#mk-url").value == "https://api.example.com/v1/{city}"
        assert screen.query_one("#mk-credential").value == "weather-key"
        assert screen.query_one("#mk-inputs").text == "city | string | required | City"
        assert str(screen.query_one("#mk-send").render()) == "This will send a GET request to api.example.com"
        assert not screen.query_one("#mk-accept").disabled


async def test_accept_is_disabled_until_valid(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        screen, _net, _ = await _drafted(app, pilot)
        screen.query_one("#mk-url").value = "http://api.example.com/{city}"
        await pilot.pause()
        assert screen.query_one("#mk-accept").disabled and screen.query_one("#mk-test").disabled
        assert "https" in str(screen.query_one("#mk-status").render())
        screen.query_one("#mk-url").value = "https://api.example.com/{city}"
        await pilot.pause()
        assert not screen.query_one("#mk-accept").disabled


async def test_a_failed_draft_says_why_and_shows_no_form(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        screen, _net, asked = await _drafted(app, pilot, answer="no idea")
        assert len(asked) == 2
        assert not screen.query_one("#mk-form").display
        assert "Could not draft it" in str(screen.query_one("#mk-status").render())


async def test_test_shows_the_masked_request_and_sends_only_after_yes(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        screen, net, _ = await _drafted(app, pilot)
        screen.query_one("#mk-test").press()
        await pilot.pause()
        test = app.screen
        assert isinstance(test, TestToolScreen)
        test.query_one("#tt-in-0").value = "Paris"
        test.query_one("#tt-show").press()
        await pilot.pause()
        shown = str(test.query_one("#tt-request").render())
        assert "GET https://api.example.com/v1/Paris" in shown
        assert "Authorization: •••" in shown and "s3cr3t" not in shown
        assert shown.rstrip().endswith("Send it?")
        assert str(test.query_one("#tt-warn").render()) == ""
        assert net.sent == []
        test.query_one("#tt-send").press()
        await pilot.pause()
        await test.workers.wait_for_complete()
        await pilot.pause()
        assert str(test.query_one("#tt-answer").render()) == "sunny"
        assert [s[:2] for s in net.sent] == [("GET", "https://api.example.com/v1/Paris")]


async def test_a_tool_above_reads_warns_before_sending(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        net = Net()
        tool = made.MadeTool(name="mail", method="POST", risk="writes", url="https://api.example.com/send",
                             body='{"to": "{to}"}', inputs=[made.ToolInput("to")])
        app.push_screen(TestToolScreen(tool, get_credential=lambda n: None, resolve=net.resolve,
                                       request=net.request))
        await pilot.pause()
        test = app.screen
        test.query_one("#tt-in-0").value = "a@b.c"
        test.query_one("#tt-show").press()
        await pilot.pause()
        assert str(test.query_one("#tt-warn").render()) == "This test really does it"
        assert net.sent == []


async def test_accept_saves_and_accepts_and_it_can_be_opened_again(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        screen, _net, _ = await _drafted(app, pilot)
        screen.query_one("#mk-accept").press()
        await pilot.pause()
        assert made.accepted(made.load("weather"))

        again = MakeToolScreen(edit="weather")
        app.push_screen(again)
        await pilot.pause()
        assert again.query_one("#mk-form").display and not again.query_one("#mk-desc").display
        assert str(again.query_one("#mk-status").render()) == "Accepted."

        again.query_one("#mk-about").value = "Changed"
        await pilot.pause()
        assert "Not accepted yet" in str(again.query_one("#mk-status").render())
        again.query_one("#mk-save").press()
        await pilot.pause()
        reloaded = made.load("weather")
        assert reloaded.about == "Changed" and reloaded.accepted_hash == ""
        assert not made.accepted(reloaded)
        again.query_one("#mk-accept").press()
        await pilot.pause()
        assert made.accepted(made.load("weather"))


async def test_connectors_tab_lists_made_tools_and_opens_make_a_tool(tmp_path):
    made.save(made.MadeTool(name="weather", url="https://api.example.com/x"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(140, 90)) as pilot:
        app.push_screen(ToolsScreen())
        await pilot.pause()
        screen = app.screen
        table = screen.query_one("#tl-made")
        assert table.row_count == 1
        screen.query_one("#tl-make").press()
        await pilot.pause()
        assert isinstance(app.screen, MakeToolScreen)
        assert not app.screen.query_one("#mk-form").display
