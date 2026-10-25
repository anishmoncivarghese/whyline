import json

import pytest

from whyline.agents import deliver, deliveries as dl, definitions as d, state, telegram
from whyline.console import tui
from whyline.console.agents_screens import AgentForm, NewAgentScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


async def _until(pilot, condition, what):
    for _ in range(400):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


_CLIS = ("claude", "codex", "grok", "antigravity")
HINT = "Enable {agent} in Settings or choose another provider."


def _status(*, enabled=None, available=None):
    enabled = set(_CLIS) if enabled is None else set(enabled)
    available = set(_CLIS) if available is None else set(available)
    return {
        agent: {
            "enabled": agent in enabled,
            "available": agent in available,
            "label": "ok" if agent in enabled and agent in available else (
                "off in Settings" if agent not in enabled else "not installed"
            ),
        }
        for agent in _CLIS
    }


ENABLED_STATUS = _status()


def _runner_values(screen):
    return [
        value
        for _label, value in screen.query_one("#na-runner", tui.Select)._options
        if value is not tui.Select.BLANK
    ]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    monkeypatch.setattr(telegram, "known_chats", lambda: {-100: "Family (group)"})
    return folder


def _fill_basic(screen, work):
    screen.query_one("#na-kind", tui.Select).value = "personal"
    screen.query_one("#na-name", tui.Input).value = "jobs"
    screen.query_one("#na-instructions").text = "Scan."
    screen.query_one("#na-workdir", tui.Input).value = str(work)


async def _open_form(app, pilot, existing=None, status=None):
    result = []
    app.push_screen(
        NewAgentScreen(app.session.root, ENABLED_STATUS if status is None else status,
                       existing=existing),
        result.append,
    )
    await _until(
        pilot,
        lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-email"),
        "form shown",
    )
    return result


async def test_the_form_returns_the_delivery(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        result = await _open_form(app, pilot)
        screen = app.screen
        _fill_basic(screen, work)
        screen.query_one("#na-email", tui.Input).value = "a@example.com, b@example.com"
        screen.query_one("#na-subject", tui.Input).value = "Daily jobs"
        screen.query_one("#na-telegram", tui.Select).value = -100
        screen.query_one("#na-attach", tui.Select).value = "docx"
        screen.query_one("#na-on-failure", tui.Select).value = "alert"
        screen.query_one("#na-next", tui.Button).press()
        await _until(pilot, lambda: result, "submitted")
        form = result[0]
        assert isinstance(form, AgentForm) and form.defn.name == "jobs"
        assert form.delivery == dl.Delivery(email=("a@example.com", "b@example.com"),
                                            subject="Daily jobs", telegram_chat=-100,
                                            telegram_label="Family (group)")


async def test_a_bad_address_is_shown_in_the_form(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        result = await _open_form(app, pilot)
        _fill_basic(app.screen, work)
        app.screen.query_one("#na-email", tui.Input).value = "nope"
        app.screen.query_one("#na-next", tui.Button).press()
        await _until(pilot, lambda: "not an email address" in str(app.screen.query_one("#na-error").renderable),
                     "error shown")
        assert result == []


async def test_saving_writes_deliveries_and_review_mentions_them(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        text = f'name="jobs"\ninstructions="Scan."\nrunner="codex"\nworkdir={json.dumps(str(work))}\n'
        path = app.session.root / "jobs.toml"
        defn = d.parse(text, kind="personal", path=path)
        delivery = dl.Delivery(email=("a@example.com",))
        reviews = []
        from whyline.console import agents_screens

        real_review = agents_screens.ReviewScreen

        def capture(defn_, text_, scheduler_on):
            reviews.append(text_)
            return real_review(defn_, text_, scheduler_on)

        monkeypatch.setattr(agents_screens, "ReviewScreen", capture)
        app._new_agent_done(AgentForm(defn, delivery))
        await _until(pilot, lambda: reviews and app.screen.query("#rv-save"), "review shown")
        assert "email to a@example.com" in reviews[0]
        app.screen.query_one("#rv-save", tui.Button).press()
        await _until(pilot, lambda: dl.get(defn.agent_id) is not None, "delivery saved")


async def test_a_renamed_agent_moves_its_deliveries(tmp_path, home, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    old_path = home / ".whyline" / "agents" / "jobs.toml"
    old = d.parse(f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n',
                  kind="personal", path=old_path)
    d.save(old)
    state.accept(state.connect(), old)
    dl.save(old.agent_id, dl.Delivery(email=("a@example.com",)))
    new_path = home / ".whyline" / "agents" / "jobs2.toml"
    new = d.parse(f'name="jobs2"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n',
                  kind="personal", path=new_path)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        app._editing_agent_id = old.agent_id
        app._new_agent_done(AgentForm(new, dl.Delivery(email=("a@example.com",))))
        await _until(pilot, lambda: app.screen.query("#rv-save"), "review shown")
        app.screen.query_one("#rv-save", tui.Button).press()
        await _until(pilot, lambda: dl.get(new.agent_id) is not None, "moved")
        assert dl.get(old.agent_id) is None
        assert not old_path.exists() and new_path.is_file()
        names = [item.name for item in d.discover(tmp_path) if isinstance(item, d.AgentDef)]
        assert names == ["jobs2"]
        assert state.get(state.connect(), old.agent_id) is None
        saved = state.get(state.connect(), new.agent_id)
        assert saved is not None and saved.status == "active"


async def test_review_back_reopens_the_form_with_the_delivery(tmp_path, monkeypatch):
    from whyline import account

    work = tmp_path / "work"
    work.mkdir()
    defn = d.parse(f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n',
                   kind="personal", path=tmp_path / "jobs.toml")
    delivery = dl.Delivery(email=("a@example.com",), subject="Daily")
    monkeypatch.setattr(account, "agent_status", lambda root: ENABLED_STATUS)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        # Follow the real form -> review -> back path.  Calling the completion
        # callback directly can push Review while the base screen is still
        # mounting, a state users cannot produce and Textual does not support.
        app._open_new_agent(existing=defn, delivery=delivery, lock_name=True)
        await _until(
            pilot,
            lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-email"),
            "form shown",
        )
        app.screen.query_one("#na-next", tui.Button).press()
        await _until(pilot, lambda: app.screen.query("#rv-back"), "review shown")
        app.screen.query_one("#rv-back", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-name"),
            "form reopened",
        )
        name = app.screen.query_one("#na-name", tui.Input)
        assert name.value == "jobs" and name.disabled
        assert app.screen.query_one("#na-email", tui.Input).value == "a@example.com"
        assert app.screen.query_one("#na-subject", tui.Input).value == "Daily"


async def test_edit_renames_through_the_form_and_moves_deliveries(tmp_path, home, monkeypatch):
    from whyline import account

    work = tmp_path / "work"
    work.mkdir()
    path = home / ".whyline" / "agents" / "jobs.toml"
    text = f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n'
    old = d.parse(text, kind="personal", path=path)
    d.save(old)
    state.accept(state.connect(), old)
    kept = dl.Delivery(
        email=("a@example.com",), subject="Daily", attach="md", on_failure="silent",
    )
    dl.save(old.agent_id, kept)
    monkeypatch.setattr(account, "agent_status", lambda root: ENABLED_STATUS)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        app._open_new_agent(existing=old)
        await _until(
            pilot,
            lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-email"),
            "edit form shown",
        )
        name = app.screen.query_one("#na-name", tui.Input)
        assert not name.disabled and name.value == "jobs"
        assert app.screen.query_one("#na-email", tui.Input).value == "a@example.com"
        assert app.screen.query_one("#na-subject", tui.Input).value == "Daily"
        assert app.screen.query_one("#na-attach", tui.Select).value == "md"
        assert app.screen.query_one("#na-on-failure", tui.Select).value == "silent"
        name.value = "jobs2"
        app.screen.query_one("#na-next", tui.Button).press()
        await _until(pilot, lambda: app.screen.query("#rv-back"), "review shown")
        app.screen.query_one("#rv-back", tui.Button).press()
        await _until(
            pilot,
            lambda: (
                isinstance(app.screen, NewAgentScreen)
                and app.screen.query("#na-attach")
                and app.screen.query_one("#na-name", tui.Input).value == "jobs2"
                and app.screen.query_one("#na-attach", tui.Select).value == "md"
                and app.screen.query_one("#na-on-failure", tui.Select).value == "silent"
            ),
            "form restored",
        )
        name = app.screen.query_one("#na-name", tui.Input)
        assert name.value == "jobs2" and name.disabled
        assert app._editing_agent_id == old.agent_id
        assert app.screen.query_one("#na-email", tui.Input).value == "a@example.com"
        assert app.screen.query_one("#na-subject", tui.Input).value == "Daily"
        assert app.screen.query_one("#na-attach", tui.Select).value == "md"
        assert app.screen.query_one("#na-on-failure", tui.Select).value == "silent"
        app.screen.query_one("#na-next", tui.Button).press()
        await _until(pilot, lambda: app.screen.query("#rv-save"), "review shown again")
        app.screen.query_one("#rv-save", tui.Button).press()
        new_id = "personal:jobs2"
        await _until(pilot, lambda: dl.get(new_id) == kept, "delivery moved")
        assert dl.get(old.agent_id) is None
        new_path = home / ".whyline" / "agents" / "jobs2.toml"
        assert not path.exists() and new_path.is_file()
        names = [item.name for item in d.discover(tmp_path) if isinstance(item, d.AgentDef)]
        assert names == ["jobs2"]
        assert state.get(state.connect(), old.agent_id) is None
        saved = state.get(state.connect(), new_id)
        assert saved is not None and saved.status == "active"


async def test_send_test_shows_each_result(tmp_path, monkeypatch):
    monkeypatch.setattr(deliver, "send_test", lambda label, delivery, **k: [
        {"to": "email", "ok": True, "detail": ""},
        {"to": "telegram", "ok": False, "detail": "the bot can't reach Family (group)"}])
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open_form(app, pilot)
        _fill_basic(app.screen, work)
        app.screen.query_one("#na-email", tui.Input).value = "a@example.com"
        app.screen.query_one("#na-send-test", tui.Button).press()
        await _until(pilot, lambda: "telegram ✗" in str(app.screen.query_one("#na-test-result").renderable),
                     "results shown")
        assert "email ✓" in str(app.screen.query_one("#na-test-result").renderable)


async def test_set_up_telegram_from_the_form_and_back_does_not_crash(tmp_path, monkeypatch):
    # Reported: opening Set up Telegram from the agent form, then going back
    # while its chat check was still running, crashed the console.
    import threading

    from whyline.console.agents_screens import TelegramSetupScreen

    release, started = threading.Event(), threading.Event()
    chats = {}

    def slow_find(token):
        started.set()
        release.wait(5)
        return {-200: "Govt Jobs (group)"}

    monkeypatch.setattr(telegram, "token_get", lambda: "123:secret")
    monkeypatch.setattr(telegram, "check_token", lambda token: "@JobsBot")
    monkeypatch.setattr(telegram, "find_chats", slow_find)
    monkeypatch.setattr(telegram, "remember_chats", lambda found: chats.update(found) or dict(chats))
    monkeypatch.setattr(telegram, "known_chats", lambda: dict(chats))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open_form(app, pilot)
        form = app.screen
        assert "no chats yet" in str(form.query_one("#na-telegram", tui.Select)._options[0][0])
        form.query_one("#na-telegram-setup", tui.Button).press()
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup open")
        await _until(pilot, lambda: started.is_set(), "chat check running")
        app.screen.query_one("#tg-done", tui.Button).press()
        await _until(pilot, lambda: app.screen is form, "back to the form")
        release.set()
        for _ in range(20):
            await pilot.pause(0.05)
        assert app.is_running and app.screen is form
        # Reopening finds the chat the bot got in the meantime.
        form.query_one("#na-telegram-setup", tui.Button).press()
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup open again")
        await _until(pilot, lambda: "Govt Jobs" in str(app.screen.query_one("#tg-chats").renderable),
                     "chat found")
        app.screen.query_one("#tg-done", tui.Button).press()
        await _until(pilot, lambda: app.screen is form, "back again")
        assert form.query_one("#na-telegram", tui.Select).value == -200


async def test_new_agent_omits_a_disabled_provider(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open_form(app, pilot, status=_status(enabled={"codex", "grok"}))
        values = _runner_values(app.screen)
        assert "codex" in values and "grok" in values
        assert "claude" not in values
        with pytest.raises(tui.NoMatches):
            app.screen.query_one("#na-backup-claude", tui.Checkbox)


async def test_new_agent_omits_an_enabled_but_unusable_provider(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open_form(
            app,
            pilot,
            status=_status(
                enabled={"claude", "codex", "grok"},
                available={"codex", "grok"},
            ),
        )
        values = _runner_values(app.screen)
        assert "codex" in values and "grok" in values
        assert "claude" not in values
        with pytest.raises(tui.NoMatches):
            app.screen.query_one("#na-backup-claude", tui.Checkbox)


async def test_edit_keeps_an_unusable_runner_visible_and_cancel_is_lossless(tmp_path, home):
    work = tmp_path / "work"
    work.mkdir()
    path = home / ".whyline" / "agents" / "jobs.toml"
    text = (
        f'name="jobs"\ninstructions="x"\nrunner="claude"\nbackup=["codex"]\n'
        f'workdir={json.dumps(str(work))}\n'
    )
    existing = d.parse(text, kind="personal", path=path)
    d.save(existing)
    before = path.read_text()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open_form(
            app,
            pilot,
            existing=existing,
            status=_status(enabled={"claude", "codex"}, available={"codex"}),
        )
        screen = app.screen
        assert screen.query_one("#na-runner", tui.Select).value == "claude"
        assert "claude" in _runner_values(screen)
        box = screen.query_one("#na-backup-codex", tui.Checkbox)
        assert box.value is True
        screen.query_one("#na-cancel", tui.Button).press()
        await _until(pilot, lambda: not isinstance(app.screen, NewAgentScreen), "closed")
    assert path.read_text() == before


async def test_edit_keeps_a_disabled_runner_visible_and_cancel_is_lossless(tmp_path, home):
    work = tmp_path / "work"
    work.mkdir()
    path = home / ".whyline" / "agents" / "jobs.toml"
    text = (
        f'name="jobs"\ninstructions="x"\nrunner="claude"\nbackup=["codex"]\n'
        f'workdir={json.dumps(str(work))}\n'
    )
    existing = d.parse(text, kind="personal", path=path)
    d.save(existing)
    before = path.read_text()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open_form(
            app, pilot, existing=existing, status=_status(enabled={"codex"}),
        )
        screen = app.screen
        assert screen.query_one("#na-runner", tui.Select).value == "claude"
        assert "claude" in _runner_values(screen)
        labels = dict(screen.query_one("#na-runner", tui.Select)._options)
        assert any("claude" in str(label) and "unavailable" in str(label) for label in labels)
        box = screen.query_one("#na-backup-codex", tui.Checkbox)
        assert box.value is True
        screen.query_one("#na-cancel", tui.Button).press()
        await _until(pilot, lambda: not isinstance(app.screen, NewAgentScreen), "closed")
    assert path.read_text() == before


async def test_save_refuses_a_disabled_runner(tmp_path, home):
    work = tmp_path / "work"
    work.mkdir()
    path = home / ".whyline" / "agents" / "jobs.toml"
    text = (
        f'name="jobs"\ninstructions="x"\nrunner="claude"\n'
        f'workdir={json.dumps(str(work))}\n'
    )
    existing = d.parse(text, kind="personal", path=path)
    d.save(existing)
    before = path.read_text()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        result = await _open_form(
            app, pilot, existing=existing, status=_status(enabled={"codex"}),
        )
        app.screen.query_one("#na-next", tui.Button).press()
        await pilot.pause()
        assert isinstance(app.screen, NewAgentScreen)
        assert HINT.format(agent="claude") in str(app.screen.query_one("#na-error").renderable)
        assert result == []
    assert path.read_text() == before


async def test_enabling_restores_a_provider_to_new_agent_choices(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open_form(app, pilot, status=_status(enabled={"codex"}))
        assert "claude" not in _runner_values(app.screen)
        app.screen.query_one("#na-cancel", tui.Button).press()
        await _until(pilot, lambda: not isinstance(app.screen, NewAgentScreen), "closed")
        await _open_form(app, pilot, status=_status(enabled={"claude", "codex"}))
        assert "claude" in _runner_values(app.screen)
