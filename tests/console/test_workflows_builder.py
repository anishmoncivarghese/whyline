import pytest
from textual.widgets import Select

from whyline import account
from whyline.console import tui
from whyline.console.workflows_screens import BuilderScreen, LibraryScreen
from whyline.workflows import definitions, service, state

pytestmark = [pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"), pytest.mark.asyncio]

TEXT = '''name = "daily"
version = 1

[trigger]
kind = "manual"

[[step]]
id = "start"
type = "set"

[step.values]
message = "hello"

[[step]]
id = "check"
type = "condition"
left = "a"
op = "eq"
right = "b"
then = "finish"

[[step]]
id = "finish"
type = "stop"
'''


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    folder = home / ".whyline" / "workflows"
    folder.mkdir(parents=True)
    (folder / "daily.toml").write_text(TEXT)
    return home


def ids(screen):
    return [s.id for s in screen._steps]


def status(screen):
    return str(screen.query_one("#wb-status").render())


def on_disk():
    return service.load("daily", None)


async def press(pilot, selector):
    await pilot.click(selector)
    await pilot.pause(0.3)


async def test_add_move_delete_and_save_round_trips(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(on_disk())
        app.push_screen(screen)
        await pilot.pause()
        outline = screen.query_one("#wb-outline")
        assert outline.row_count == 4  # trigger plus three steps
        await press(pilot, "#wb-add")
        assert ids(screen) == ["start", "check", "finish", "set_1"]
        await press(pilot, "#wb-up")
        assert ids(screen) == ["start", "check", "set_1", "finish"]
        await press(pilot, "#wb-down")
        assert ids(screen) == ["start", "check", "finish", "set_1"]
        await press(pilot, "#wb-up")
        outline.move_cursor(row=1)  # start
        await pilot.pause()
        await press(pilot, "#wb-delete")
        assert ids(screen) == ["check", "set_1", "finish"]
        await press(pilot, "#wb-save")
        assert "Saved." in status(screen)
        parsed = on_disk()
        assert [s.id for s in parsed.steps] == ids(screen)
        assert definitions.parse(definitions.render(parsed), kind="personal", path=parsed.path).raw == parsed.raw


async def test_deleting_a_routed_to_step_is_refused(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(on_disk())
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#wb-outline").move_cursor(row=3)  # finish
        await pilot.pause()
        await press(pilot, "#wb-delete")
        assert ids(screen) == ["start", "check", "finish"]
        assert "check" in status(screen) and "Cannot delete" in status(screen)


async def test_trigger_change_marks_needs_review_after_save(tmp_path, home):
    service.accept("daily", None)
    assert next(r for r in service.rows(None) if r.name == "daily").status == state.ACTIVE
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(on_disk())
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#wb-kind").value = "daily"
        await pilot.pause()
        screen.query_one("#wb-at").value = "08:30"
        await pilot.pause()
        await press(pilot, "#wb-save")
        assert status(screen) == "Saved. Review & accept to run the new version."
        assert on_disk().trigger.at == "08:30"
        assert next(r for r in service.rows(None) if r.name == "daily").status == state.NEEDS_REVIEW


async def test_cancel_with_changes_asks_first(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(on_disk())
        app.push_screen(screen)
        await pilot.pause()
        await press(pilot, "#wb-add")
        await press(pilot, "#wb-cancel")
        assert type(app.screen).__name__ == "ConfirmScreen"
        await pilot.click("#cancel")
        await pilot.pause(0.3)
        assert app.screen is screen
        await press(pilot, "#wb-cancel")
        await pilot.click("#confirm")
        await pilot.pause(0.3)
        assert app.screen is not screen
        assert [s.id for s in on_disk().steps] == ["start", "check", "finish"]


async def test_cancel_after_save_across_trigger_kind_change_closes(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(on_disk())
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#wb-kind").value = "daily"
        await pilot.pause()
        screen.query_one("#wb-at").value = "08:30"
        await pilot.pause()
        await press(pilot, "#wb-save")
        screen.query_one("#wb-kind").value = "manual"  # the at value stays in the form
        await pilot.pause()
        await press(pilot, "#wb-save")
        assert on_disk().trigger.kind == "manual"
        await press(pilot, "#wb-cancel")
        assert app.screen is not screen


async def test_cancel_without_changes_closes(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(on_disk())
        app.push_screen(screen)
        await pilot.pause()
        await press(pilot, "#wb-cancel")
        assert app.screen is not screen


async def test_library_edit_opens_builder(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#mode-workflows")
        await pilot.pause()
        await pilot.click("#workflows-library")
        await pilot.pause()
        assert isinstance(app.screen, LibraryScreen)
        await pilot.click("#wl-edit")
        await pilot.pause()
        assert isinstance(app.screen, BuilderScreen)


async def test_fits_80x24(tmp_path, home):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = BuilderScreen(on_disk())
        app.push_screen(screen)
        await pilot.pause()
        for button in screen.query("Button"):
            assert button.region.right <= 80 and button.region.bottom <= 24, button.id
        assert len({b.region.y for b in screen.query("Button")}) == 2  # two button rows
        await press(pilot, "#wb-add")
        assert len(screen._steps) == 4


WORK = '''name = "work"
version = 1

[trigger]
kind = "manual"

[[step]]
id = "ask"
type = "agent"
runner = "claude"
instructions = "old"

[[step]]
id = "pick"
type = "condition"
left = "a"
op = "eq"
right = "a"
then = "yes"
else = "no"

[[step]]
id = "yes"
type = "deliver"
to = "file"
text = "yes"

[[step]]
id = "no"
type = "deliver"
to = "file"
text = "no"
'''


@pytest.fixture
def work(home, monkeypatch):
    (home / ".whyline" / "workflows" / "work.toml").write_text(WORK)
    monkeypatch.setattr(account, "enabled_agents", lambda: {"claude", "codex"})
    return service.load("work", None)


def select_step(screen, step_id):
    screen.query_one("#wb-outline").move_cursor(row=ids(screen).index(step_id) + 1)


def offered(select):
    return [value for _label, value in select._options if value is not Select.BLANK]


async def test_editing_agent_instructions_and_runner_saves(tmp_path, work):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(work)
        app.push_screen(screen)
        await pilot.pause()
        select_step(screen, "ask")
        await pilot.pause(0.3)
        screen.query_one("#wf-instructions").value = "summarise the day"
        screen.query_one("#wf-runner").value = "codex"
        await pilot.pause(0.3)
        await press(pilot, "#wb-save")
        saved = service.load("work", None).steps[0]
        assert saved.fields["instructions"] == "summarise the day"
        assert saved.fields["runner"] == "codex"


async def test_routing_select_offers_only_later_steps(tmp_path, work):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(work)
        app.push_screen(screen)
        await pilot.pause()
        select_step(screen, "pick")
        await pilot.pause(0.3)
        assert offered(screen.query_one("#wf-then")) == ["yes", "no"]
        assert screen.query_one("#wf-else").value == "no"
        select_step(screen, "yes")
        await pilot.pause(0.3)
        assert screen._later(ids(screen).index("yes")) == ["no"]


async def test_template_in_to_shows_error_and_blocks_save(tmp_path, work):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(work)
        app.push_screen(screen)
        await pilot.pause()
        select_step(screen, "yes")
        await pilot.pause(0.3)
        screen._set_field("to", "{{ x }}")  # `to` is a select, so set it as the form would
        await press(pilot, "#wb-save")
        assert "Not saved" in status(screen)
        assert any("template" in m for m in screen._problems["yes"])
        assert "template" in str(screen.query_one("#wb-problems").render())
        assert service.load("work", None).steps[2].fields["to"] == "file"


async def test_dry_run_of_a_condition_shows_the_taken_branch(tmp_path, work):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(work)
        app.push_screen(screen)
        await pilot.pause()
        await press(pilot, "#wb-dryrun")
        assert type(app.screen).__name__ == "DryRunScreen"
        await press(pilot, "#wd-run")
        output = str(app.screen.query_one("#wd-output").render())
        assert "pick (condition)" in output and "goes to yes" in output


async def test_disabled_provider_is_not_offered_as_runner(tmp_path, work, monkeypatch):
    monkeypatch.setattr(account, "enabled_agents", lambda: {"claude"})
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = BuilderScreen(work)
        app.push_screen(screen)
        await pilot.pause()
        select_step(screen, "ask")
        await pilot.pause(0.3)
        assert offered(screen.query_one("#wf-runner")) == ["claude"]
