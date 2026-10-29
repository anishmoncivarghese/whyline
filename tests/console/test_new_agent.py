import pytest

from whyline.agents import capabilities, deliveries as dl, state, telegram, templates
from whyline.console import mac_input, tui
from whyline.console.agents_screens import AgentTemplateScreen, NewAgentScreen, ReviewScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {a: {"available": True, "label": "ok"} for a in ("claude", "codex", "grok", "antigravity")}


async def _until(pilot, condition, what: str) -> None:
    for _ in range(400):
        await pilot.pause()
        if condition():
            return
        await pilot.pause(0.02)
    raise AssertionError(f"never happened: {what}")


def _status(*, enabled=None, available=None):
    all_clis = ("claude", "codex", "grok", "antigravity")
    enabled = set(all_clis) if enabled is None else set(enabled)
    available = set(all_clis) if available is None else set(available)
    return {
        cli: {
            "enabled": cli in enabled,
            "available": cli in available,
            "label": "ok" if cli in enabled and cli in available else (
                "off in Settings" if cli not in enabled else "not installed"
            ),
        }
        for cli in all_clis
    }


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    from whyline import account
    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(mac_input, "available", lambda: True)
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    return home


async def test_fill_review_and_save_a_repo_agent(tmp_path, monkeypatch):
    from whyline.console import relay_ops

    src = tmp_path / "repo" / "docs"
    src.mkdir(parents=True)
    monkeypatch.setattr(mac_input, "pick_files", lambda run=None: [src])
    backup_writes = []
    monkeypatch.setattr(relay_ops, "save_backup", lambda *args: backup_writes.append(args))
    app = tui.WhylineConsoleApp(root=tmp_path / "repo")
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path / "repo", STATUS), app._new_agent_done)
        await pilot.pause()
        s = app.screen
        s.query_one("#na-name", tui.Input).value = "digest"
        s.query_one("#na-instructions").load_text("Summarise what changed.")
        s.query_one("#na-runner", tui.Select).value = "claude"
        s.query_one("#na-backup-codex", tui.Checkbox).value = True
        s.query_one("#na-when", tui.Select).value = "weekdays"
        await pilot.pause()
        s.query_one("#na-at", tui.Input).value = "07:00"
        await pilot.click("#na-add-sources")
        for _ in range(50):
            if "docs" in str(s.query_one("#na-sources-list").renderable):
                break
            await pilot.pause(0.05)
        await pilot.click("#na-next")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        assert "Every weekday at 07:00" in str(app.screen.query_one("#rv-text").renderable)
        await pilot.click("#rv-save")
        await pilot.pause()
    saved = tmp_path / "repo/.whyline/agents/digest.toml"
    text = saved.read_text()
    assert saved.exists() and 'backup = ["codex"]' in text
    assert backup_writes == []
    assert 'sources = ["docs"]' in text
    assert state.all_activations(state.connect())[0].status == "active"


async def test_invalid_input_shows_the_reason_and_stays(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 100)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        app.screen.query_one("#na-name", tui.Input).value = "Bad Name"
        await pilot.click("#na-next")
        await pilot.pause()
        assert isinstance(app.screen, NewAgentScreen)
        assert "name" in str(app.screen.query_one("#na-error").renderable)


async def test_clis_not_cleared_for_unattended_are_marked(tmp_path, monkeypatch):
    monkeypatch.setattr(capabilities, "UNATTENDED_OK", frozenset({"claude"}))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        app.push_screen(NewAgentScreen(tmp_path, STATUS), app._new_agent_done)
        await pilot.pause()
        labels = dict(app.screen.query_one("#na-runner", tui.Select)._options)
        assert any("codex" in str(k) and "on demand only" in str(k) for k in labels)


async def test_chooser_lists_blank_and_templates(tmp_path, monkeypatch):
    from textual.widgets import DataTable

    shipped = templates.list_templates()
    assert any(item.name == "example-digest" for item in shipped)
    extra = [*shipped, templates.TemplateInfo("custom-scan", "Custom scan", "Scan local files.")]
    monkeypatch.setattr(templates, "list_templates", lambda: extra)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        app._main("#mode-agents", tui.Button).press()
        await _until(pilot, lambda: app.session.mode == "agents", "agents mode")
        app._main("#agents-new", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, AgentTemplateScreen) and app.screen.query("#nt-table"),
            "chooser shown",
        )
        table = app.screen.query_one("#nt-table", DataTable)
        assert table.row_count == 1 + len(extra)
        rows = [[str(cell) for cell in table.get_row_at(i)] for i in range(table.row_count)]
        assert rows[0][0] == "Blank agent"
        listed_names = [row[1] for row in rows[1:]]
        listed_titles = [row[0] for row in rows[1:]]
        assert listed_names == [item.name for item in extra]
        assert listed_titles == [item.title for item in extra]
        assert rows[-1][2] == "Scan local files."


async def test_template_prefills_form_in_memory_and_follows_enabled_providers(
    tmp_path, env, monkeypatch
):
    from textual.widgets import DataTable
    from whyline import account

    # Disable claude (the template's default runner); enable codex and grok.
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root: _status(
            enabled={"codex", "grok"},
            available={"claude", "codex", "grok"},
        ),
    )

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        app._open_new_agent()
        await _until(
            pilot,
            lambda: isinstance(app.screen, AgentTemplateScreen) and app.screen.query("#nt-table"),
            "chooser shown",
        )
        table = app.screen.query_one("#nt-table", DataTable)
        digest_row = next(
            i for i in range(table.row_count)
            if "example-digest" in [str(c) for c in table.get_row_at(i)]
        )
        table.move_cursor(row=digest_row)
        app.screen.query_one("#nt-continue", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-workdir"),
            "template form shown",
        )
        screen = app.screen
        assert screen.query_one("#na-kind", tui.Select).value == "personal"
        assert screen.query_one("#na-workdir", tui.Input).value == "~/.whyline/example-digest"
        name_input = screen.query_one("#na-name", tui.Input)
        assert name_input.value == "example-digest" and not name_input.disabled
        assert "Read the source files" in screen.query_one("#na-instructions", tui.TextArea).text
        assert "notes.md" in str(screen.query_one("#na-sources-list").renderable)

        # Enabled-provider rules: disabled claude is omitted; runner falls back to codex.
        runner_values = [
            v for _label, v in screen.query_one("#na-runner", tui.Select)._options
            if v is not tui.Select.BLANK
        ]
        assert runner_values == ["codex", "grok"]
        assert screen.query_one("#na-runner", tui.Select).value == "codex"
        assert screen.query_one("#na-backup-grok", tui.Checkbox).value is False
        with pytest.raises(tui.NoMatches):
            screen.query_one("#na-backup-claude", tui.Checkbox)

        # Nothing has been saved or copied yet.
        assert not (env / ".whyline" / "example-digest").exists()
        assert not (env / ".whyline" / "agents" / "example-digest.toml").exists()

        # Back returns to the chooser without writing anything.
        screen.query_one("#na-back", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, AgentTemplateScreen) and app.screen.query("#nt-table"),
            "returned to chooser",
        )
        assert not (env / ".whyline" / "example-digest").exists()
        assert not (env / ".whyline" / "agents" / "example-digest.toml").exists()

        # Also verify when the template's backup (codex) is disabled, codex is omitted.
        monkeypatch.setattr(
            account,
            "agent_status",
            lambda root: _status(
                enabled={"claude", "grok"},
                available={"claude", "codex", "grok"},
            ),
        )
        table = app.screen.query_one("#nt-table", DataTable)
        table.move_cursor(row=digest_row)
        app.screen.query_one("#nt-continue", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-runner"),
            "template form shown again",
        )
        assert app.screen.query_one("#na-runner", tui.Select).value == "claude"
        with pytest.raises(tui.NoMatches):
            app.screen.query_one("#na-backup-codex", tui.Checkbox)


async def test_template_save_calls_templates_create_and_copies_files(tmp_path, env, monkeypatch):
    from textual.widgets import DataTable

    calls = []
    real_create = templates.create

    def spy_create(name, agent_name=None, workdir=None, **kwargs):
        calls.append((name, agent_name, workdir, kwargs.get("defn")))
        return real_create(name, agent_name, workdir, **kwargs)

    monkeypatch.setattr(templates, "create", spy_create)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        app._open_new_agent()
        await _until(
            pilot,
            lambda: isinstance(app.screen, AgentTemplateScreen) and app.screen.query("#nt-table"),
            "chooser shown",
        )
        table = app.screen.query_one("#nt-table", DataTable)
        digest_row = next(
            i for i in range(table.row_count)
            if "example-digest" in [str(c) for c in table.get_row_at(i)]
        )
        table.move_cursor(row=digest_row)
        app.screen.query_one("#nt-continue", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-runner"),
            "form shown",
        )
        screen = app.screen
        # Template's own runner/backup prefilled when enabled.
        assert screen.query_one("#na-runner", tui.Select).value == "claude"
        assert screen.query_one("#na-backup-codex", tui.Checkbox).value is True

        # User edits runner, backup, schedule, and delivery.
        screen.query_one("#na-runner", tui.Select).value = "codex"
        await pilot.pause()
        screen.query_one("#na-backup-grok", tui.Checkbox).value = True
        screen.query_one("#na-when", tui.Select).value = "weekdays"
        await pilot.pause()
        screen.query_one("#na-at", tui.Input).value = "07:30"
        screen.query_one("#na-email", tui.Input).value = "me@example.com"

        assert calls == []
        assert not (env / ".whyline" / "example-digest").exists()

        screen.query_one("#na-next", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, ReviewScreen) and app.screen.query("#rv-save"),
            "review shown",
        )
        assert calls == []
        assert not (env / ".whyline" / "example-digest").exists()

        # Review -> Back restores the edited template form (still keeping Back to chooser),
        # and Review -> Save still saves through templates.create.
        app.screen.query_one("#rv-back", tui.Button).press()
        await _until(
            pilot,
            lambda: (
                isinstance(app.screen, NewAgentScreen)
                and app.screen.query("#na-back")
                and app.screen.query_one("#na-runner", tui.Select).value == "codex"
            ),
            "form restored from review",
        )
        assert app.screen.query_one("#na-email", tui.Input).value == "me@example.com"
        app.screen.query_one("#na-next", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, ReviewScreen) and app.screen.query("#rv-save"),
            "review shown again",
        )

        app.screen.query_one("#rv-save", tui.Button).press()
        saved_toml = env / ".whyline" / "agents" / "example-digest.toml"
        await _until(pilot, lambda: saved_toml.is_file(), "agent saved")

    assert len(calls) == 1
    tpl_name, agent_name, workdir, passed_defn = calls[0]
    assert tpl_name == "example-digest"
    assert agent_name == "example-digest"
    assert workdir == "~/.whyline/example-digest"
    assert passed_defn is not None
    assert passed_defn.runner == "codex"
    assert passed_defn.backup == ("grok",)
    assert passed_defn.trigger.kind == "weekdays"
    assert passed_defn.trigger.at == "07:30"

    assert (env / ".whyline" / "example-digest" / "notes.md").is_file()
    text = saved_toml.read_text(encoding="utf-8")
    assert 'runner = "codex"' in text
    assert 'backup = ["grok"]' in text
    assert 'kind = "weekdays"' in text
    assert 'at = "07:30"' in text
    assert dl.get("personal:example-digest") == dl.Delivery(email=("me@example.com",))
    conn = state.connect()
    try:
        assert state.status_of(conn, passed_defn) == "active"
    finally:
        conn.close()


async def test_blank_keeps_todays_flow_without_templates_create(tmp_path, monkeypatch):
    def forbid_create(*_args, **_kwargs):
        raise AssertionError("Blank agent must not call templates.create")

    monkeypatch.setattr(templates, "create", forbid_create)
    repo = tmp_path / "repo"
    repo.mkdir()
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(100, 40)) as pilot:
        app._open_new_agent()
        await _until(
            pilot,
            lambda: isinstance(app.screen, AgentTemplateScreen) and app.screen.query("#nt-continue"),
            "chooser shown",
        )
        # First row is Blank agent.
        app.screen.query_one("#nt-continue", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-name"),
            "blank form shown",
        )
        screen = app.screen
        assert screen.query_one("#na-kind", tui.Select).value == "repo"
        assert screen.query_one("#na-name", tui.Input).value == ""
        screen.query_one("#na-name", tui.Input).value = "blank-check"
        screen.query_one("#na-instructions", tui.TextArea).load_text("Check repo notes.")
        screen.query_one("#na-next", tui.Button).press()
        await _until(
            pilot,
            lambda: isinstance(app.screen, ReviewScreen) and app.screen.query("#rv-save"),
            "review shown",
        )
        app.screen.query_one("#rv-save", tui.Button).press()
        saved = repo / ".whyline" / "agents" / "blank-check.toml"
        await _until(pilot, lambda: saved.is_file(), "blank agent saved")
    assert 'name = "blank-check"' in saved.read_text(encoding="utf-8")


async def test_template_chooser_and_form_fit_80x24(tmp_path, monkeypatch):
    many = [
        templates.TemplateInfo(f"tpl-{i:02d}", f"Template {i}", f"Description for template {i}.")
        for i in range(18)
    ]
    monkeypatch.setattr(templates, "list_templates", lambda: [templates.list_templates.__wrapped__() if hasattr(templates.list_templates, "__wrapped__") else templates.TemplateInfo("example-digest", "Example digest", "Summary"), *many])

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app._open_new_agent()
        await _until(
            pilot,
            lambda: isinstance(app.screen, AgentTemplateScreen) and app.screen.query("#nt-continue"),
            "chooser shown",
        )
        for btn_id in ("#nt-continue", "#nt-cancel"):
            reg = app.screen.query_one(btn_id).region
            assert reg.width > 0 and reg.right <= 80
            assert reg.height > 0 and reg.bottom <= 24

        app.screen.dismiss("example-digest")
        await _until(
            pilot,
            lambda: isinstance(app.screen, NewAgentScreen) and app.screen.query("#na-next"),
            "form shown",
        )
        for btn_id in ("#na-next", "#na-back", "#na-cancel"):
            reg = app.screen.query_one(btn_id).region
            assert reg.width > 0 and reg.right <= 80
            assert reg.height > 0 and reg.bottom <= 24
