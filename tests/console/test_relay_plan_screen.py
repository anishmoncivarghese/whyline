import json
import subprocess
from pathlib import Path

import pytest

from whyline.console import auto_run, plan_job, relay_ops, tui
from whyline.console.chain_editor import OrderedChain
from whyline.console.relay_screens import PlanDraftScreen, RelayPlanScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]

STATUS = {
    agent: {"available": agent in ("claude", "codex"), "label": "ok"}
    for agent in ("claude", "codex", "antigravity", "grok")
}


class PlanExists(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def quiet_ops(monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(relay_ops, "plan_exists_error", lambda: PlanExists)
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok"]
    )
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude"))


# Antigravity's checkbox starts checked, so the research set names it.
NAMED = {
    agent: {"available": True, "label": "ok"}
    for agent in ("claude", "codex", "antigravity", "grok")
}


async def _open(app, pilot, status=None):
    results = []
    app.push_screen(RelayPlanScreen(app.session.root, status or STATUS, "claude"), results.append)
    await pilot.pause()
    return app.screen, results


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "initial")
    return path


def _repo_paths(root: Path) -> set[str]:
    found = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        suffix = "/" if path.is_dir() else ""
        found.add(relative.as_posix() + suffix)
    return found


def _settings(monkeypatch, directory: Path) -> Path:
    """Point Antigravity's settings at a file outside the repository."""
    from whyline_relay import antigravity

    path = directory / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"trustedWorkspaces": [], "permissions": {"allow": []}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(antigravity, "settings_path", lambda: path)
    return path


def _ignore_decline(repo: Path) -> None:
    exclude = repo / ".git" / "info" / "exclude"
    line = ".whyline/relay/antigravity-declined"
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if line in text.splitlines():
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as handle:
        if text and not text.endswith("\n"):
            handle.write("\n")
        handle.write(line + "\n")


def _spy_worker(monkeypatch) -> list:
    started = []
    monkeypatch.setattr(RelayPlanScreen, "_start_check_worker", lambda self: started.append(True))
    return started


def _spy_writers(monkeypatch) -> dict:
    calls = {"trust": 0, "decline": 0, "forget": 0}

    def trust(root):
        calls["trust"] += 1

    def decline(root):
        calls["decline"] += 1

    def forget(root):
        calls["forget"] += 1

    monkeypatch.setattr(relay_ops, "trust_antigravity", trust)
    monkeypatch.setattr(relay_ops, "decline_antigravity", decline)
    monkeypatch.setattr(relay_ops, "forget_antigravity_decline", forget)
    return calls


def _spy_ignore(monkeypatch) -> list:
    from whyline_relay import gitcheck

    calls = []
    monkeypatch.setattr(gitcheck, "ensure_relay_ignored", lambda root: calls.append(root))
    return calls


def _trust_message(root: Path) -> str:
    from whyline_relay import antigravity

    return (
        "Antigravity can only read and edit files in folders listed in "
        f"{antigravity.settings_path()}, a setting for the whole machine. Add "
        f"{root} to it, and allow Antigravity's file and command tools?"
    )


async def _open_auto(app, pilot, status=None):
    screen, results = await _open(app, pilot, status)
    screen.query_one("#rp-source", tui.Select).value = "auto"
    await pilot.pause()
    return screen, results


def _error_text(screen):
    return str(screen.query_one("#rp-error", tui.Static).renderable)


async def test_paste_saves_a_valid_plan(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(
        relay_ops,
        "save_pasted_plan",
        lambda root, text, name, replace=False: saved.append((text, replace))
        or (root / "plans" / "plan.plan.md"),
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("- [ ] T-1: build it\n")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert saved == [("- [ ] T-1: build it\n", False)]
    assert results == [tmp_path / "plans" / "plan.plan.md"]


async def test_paste_shows_why_an_invalid_plan_is_refused(tmp_path, monkeypatch):
    def refuse(root, text, name, replace=False):
        raise ValueError("no tasks found -- write each task as `- [ ] ID: title`")

    monkeypatch.setattr(relay_ops, "save_pasted_plan", refuse)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("just prose")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert "no tasks found" in _error_text(screen)
        assert results == []


async def test_paste_over_an_existing_plan_asks_first(tmp_path, monkeypatch):
    calls = []

    def save(root, text, name, replace=False):
        calls.append(replace)
        if not replace:
            raise PlanExists("plan.plan.md already exists")
        return root / "plans" / "plan.plan.md"

    monkeypatch.setattr(relay_ops, "save_pasted_plan", save)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert calls == [False, True]
    assert results == [tmp_path / "plans" / "plan.plan.md"]


async def test_only_the_chosen_sources_fields_show(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        source_select = screen.query_one("#rp-source", tui.Select)
        assert source_select.value == "brainstorm"
        expected_options = [
            ("Brainstorm it", "brainstorm"),
            ("I'll describe it", "draft"),
            ("I have a plan already", "paste"),
            ("Auto — brainstorm to implementation", "auto"),
        ]
        assert source_select._options == expected_options
        assert screen.query_one("#rp-brainstorm-group").display
        assert screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-paste-group").display
        assert not screen.query_one("#rp-auto-group").display
        assert screen.query_one("#rp-drafter").display
        assert screen.query_one("#rp-reviewer").display
        assert screen.query_one("#rp-go").display
        assert not screen.query_one("#rp-check").display

        source_select.value = "draft"
        await pilot.pause()
        assert screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-brainstorm-group").display
        assert not screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-paste-group").display
        assert not screen.query_one("#rp-auto-group").display
        assert screen.query_one("#rp-spec-first", tui.Checkbox).value is True
        assert screen.query_one("#rp-drafter").display
        assert screen.query_one("#rp-reviewer").display

        source_select.value = "paste"
        await pilot.pause()
        assert screen.query_one("#rp-paste-group").display
        assert not screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-brainstorm-group").display
        assert not screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-auto-group").display
        assert not screen.query_one("#rp-drafter").display
        assert not screen.query_one("#rp-reviewer").display

        source_select.value = "auto"
        await pilot.pause()
        assert screen.query_one("#rp-auto-group").display
        assert screen.query_one("#rp-new-group").display
        assert not screen.query_one("#rp-brainstorm-group").display
        assert not screen.query_one("#rp-draft-group").display
        assert not screen.query_one("#rp-paste-group").display
        assert screen.query_one("#rp-drafter").display
        assert screen.query_one("#rp-reviewer").display
        assert not screen.query_one("#rp-go").display
        assert screen.query_one("#rp-check").display
        assert str(screen.query_one("#rp-check", tui.Button).label) == "Check"


async def test_plan_button_opens_the_popup_and_reports_the_saved_plan(tmp_path, monkeypatch):
    from whyline import account

    monkeypatch.setattr(account, "agent_status", lambda root: STATUS)
    monkeypatch.setattr(
        relay_ops,
        "save_pasted_plan",
        lambda root, text, name, replace=False: root / "plans" / "plan.plan.md",
    )
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app.session.mode = "relay"
        app._sync_mode_indicator()
        await pilot.pause()  # shown buttons need a layout pass before a click
        await pilot.click("#relay-plan")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        app.screen.query_one("#rp-source", tui.Select).value = "paste"
        await pilot.pause()
        app.screen.query_one("#rp-paste").load_text("- [ ] T-1: x\n")
        await pilot.click("#rp-go")
        await pilot.pause()
        lines = [str(line) for line in app.query_one("#transcript", tui.RichLog).lines]
        assert any(
            ("Saved plans/" in line or "Saved plan" in line) and "Set up" in line for line in lines
        )




async def test_draft_needs_a_description(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        await pilot.click("#rp-go")
        await pilot.pause()
        assert "Describe what the plan should build" in _error_text(screen)


async def test_an_unfinished_draft_can_be_discarded(tmp_path, monkeypatch):
    discarded = []
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build it")
    monkeypatch.setattr(relay_ops, "discard_draft", lambda root, draft: discarded.append(draft))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        await pilot.click("#rp-discard-draft")
        await pilot.pause()
        assert discarded == [None]
        assert _error_text(screen) == ""
        assert not screen.query_one("#rp-resume-draft").display


async def test_draft_dismisses_with_a_request_carrying_the_agents(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        screen.query_one("#rp-name", tui.Input).value = "Trading v1"
        screen.query_one("#rp-description").load_text("Build the PRD")
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest(
            "draft", "Trading v1", description="Build the PRD", drafter="grok", reviewer="claude", spec_first=True
        )
    ]


async def test_draft_spec_first_checkbox_controls_request(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        checkbox = screen.query_one("#rp-spec-first", tui.Checkbox)
        assert checkbox.value is True
        checkbox.value = False
        screen.query_one("#rp-name", tui.Input).value = "Trading v1"
        screen.query_one("#rp-description").load_text("Build the PRD")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest(
            "draft", "Trading v1", description="Build the PRD", drafter="codex", reviewer="claude", spec_first=False
        )
    ]


async def test_an_empty_name_comes_from_the_description(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        screen.query_one("#rp-description").load_text("Build the trading platform")
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results[0].name == "Build the trading platform"


async def test_an_existing_plan_name_asks_before_replacing(tmp_path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "p.plan.md").write_text("x")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "draft"
        await pilot.pause()
        screen.query_one("#rp-name", tui.Input).value = "p"
        screen.query_one("#rp-description").load_text("x")
        await pilot.click("#rp-go")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()
    assert results[0].replace is True


async def test_an_existing_brainstorm_becomes_a_request(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: ["topic-a"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        screen.query_one("#rp-from", tui.Select).value = "topic-a"
        await pilot.pause()
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest("existing", "topic-a", topic="topic-a", writer="claude", drafter="grok", reviewer="claude")
    ]


async def test_new_brainstorm_request_carries_drafter_and_reviewer(tmp_path, monkeypatch):
    from whyline.console import tui as console_tui

    choice = {
        "topic": "Search indexing",
        "models": ["claude"],
        "writer": "claude",
        "passes": 1,
        "timeout": 30,
        "attachments": (),
    }
    monkeypatch.setattr(console_tui, "collect_brainstorm", lambda query_fn: choice)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        assert screen.query_one("#rp-source", tui.Select).value == "brainstorm"
        screen.query_one("#rp-drafter", tui.Select).value = "grok"
        screen.query_one("#rp-reviewer", tui.Select).value = "codex"
        await pilot.click("#rp-go")
        await pilot.pause()
    assert results == [
        plan_job.PlanRequest(
            "brainstorm", "Search indexing", brainstorm=choice, drafter="grok", reviewer="codex"
        )
    ]


async def test_resume_dismisses_with_a_resume_request(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: "Build the PRD")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        screen, results = await _open(app, pilot)
        await pilot.click("#rp-resume-draft")
        await pilot.pause()
    assert results == [plan_job.PlanRequest("resume", "Build the PRD")]


async def test_plan_draft_screen_closes(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        app.push_screen(PlanDraftScreen("Draft text here"), results.append)
        await pilot.pause()
        assert isinstance(app.screen, PlanDraftScreen)
        await pilot.click("#pd-close")
        await pilot.pause()
        assert results == [None]


_EXECUTION = (
    "#rp-implementer",
    "#rp-tester",
    "#rp-exec-reviewer",
    "#rp-release",
    "#rp-chain",
    "#rp-committer",
    "#rp-replace",
    "#rp-continue-paths",
    "#rp-auto-summary",
)


async def test_other_sources_do_not_show_auto_execution_fields(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        auto = screen.query_one("#rp-auto-group")
        for widget_id in _EXECUTION:
            assert auto.query_one(widget_id)
        assert screen.query_one("#rp-replace", tui.Checkbox).value is False
        assert screen.query_one("#rp-continue-paths", tui.Checkbox).value is False
        assert str(screen.query_one("#rp-committer", tui.Static).renderable) == (
            "Committer: whyline (automatic)"
        )
        timeout = screen.query_one("#bs-timeout", tui.Select)
        assert timeout.value == 15
        assert [value for _label, value in timeout._options] == [
            *tui.BRAINSTORM_TIMEOUT_OPTIONS, "none",
        ]
        assert not screen.query_one("#rp-run").display
        assert not screen.query("#cb-timeout")
        for source in ("brainstorm", "draft", "paste"):
            screen.query_one("#rp-source", tui.Select).value = source
            await pilot.pause()
            assert not screen.query_one("#rp-auto-group").display
            for group in ("#rp-brainstorm-group", "#rp-draft-group", "#rp-paste-group"):
                assert not screen.query_one(group).query("#rp-replace")
                assert not screen.query_one(group).query("#rp-continue-paths")
                assert not screen.query_one(group).query("#rp-implementer")


async def test_pending_spec_keeps_resume_on_every_source(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "pending_spec", lambda root: "Write the spec")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        for source in ("brainstorm", "draft", "paste", "auto"):
            screen.query_one("#rp-source", tui.Select).value = source
            await pilot.pause()
            assert screen.query_one("#rp-resume-draft").display
            assert screen.query_one("#rp-discard-draft").display


async def test_auto_recommends_roles_and_reads_the_chain_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: False)
    monkeypatch.setattr(relay_ops, "usable_agents", lambda root, status: ["claude", "codex"])
    monkeypatch.setattr(relay_ops, "read_backup", lambda root: ["grok"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        assert screen.query_one("#rp-implementer", tui.Select).value == "codex"
        assert screen.query_one("#rp-tester", tui.Select).value == "claude"
        assert screen.query_one("#rp-exec-reviewer", tui.Select).value == "claude"
        assert screen.query_one("#rp-release", tui.Select).value == "human"
        assert screen.query_one("#rp-chain", OrderedChain).order() == ["grok"]


async def test_configured_roles_still_take_the_chain_from_read_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "roles_configured", lambda root: True)
    monkeypatch.setattr(
        relay_ops,
        "current_roles",
        lambda root: {
            "implementer": "grok",
            "tester": "claude",
            "reviewer": "codex",
            "backup": ["grok"],
        },
    )
    monkeypatch.setattr(relay_ops, "release_role", lambda root: "codex")
    monkeypatch.setattr(relay_ops, "read_backup", lambda root: ["claude"])
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rp-implementer", tui.Select).value == "grok"
        assert screen.query_one("#rp-tester", tui.Select).value == "claude"
        assert screen.query_one("#rp-exec-reviewer", tui.Select).value == "codex"
        assert screen.query_one("#rp-release", tui.Select).value == "codex"
        assert screen.query_one("#rp-chain", OrderedChain).order() == ["claude"]


async def test_an_unsaved_chain_opens_on_automatic(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "read_backup", lambda root: [])
    monkeypatch.setattr(relay_ops, "usable_agents", lambda root, status: ["claude", "codex", "grok"])
    from whyline import model

    model.set_default_agent(tmp_path, "codex")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        assert screen.query_one("#rp-chain", OrderedChain).order() == ["claude", "grok"]


async def test_drafter_follows_the_final_writer_only_while_it_still_matches(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        final = screen.query_one("#bs-final", tui.Select)
        drafter = screen.query_one("#rp-drafter", tui.Select)
        assert final.value == "claude"
        assert drafter.value == "codex"

        final.value = "grok"
        await pilot.pause()
        assert drafter.value == "codex"

        drafter.value = "grok"
        await pilot.pause()
        final.value = "claude"
        await pilot.pause()
        assert drafter.value == "claude"

        drafter.value = "codex"
        await pilot.pause()
        final.value = "grok"
        await pilot.pause()
        assert drafter.value == "codex"

        drafter.value = "grok"
        await pilot.pause()
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        final.value = "claude"
        await pilot.pause()
        assert drafter.value == "grok"


async def test_auto_summary_matches_the_form_and_a_custom_pipeline(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from whyline_relay import config

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        summary = str(screen.query_one("#rp-auto-summary", tui.Static).renderable)
        assert summary == relay_ops.auto_summary(screen._auto_view())
        assert "Backup: none." in summary
        await pilot.click("#rp-check")
        await pilot.pause()
        assert results == []
        assert isinstance(app.screen, RelayPlanScreen)

    request = SimpleNamespace(
        root=tmp_path,
        agents=("claude", "codex"),
        final_agent="claude",
        drafter="grok",
        reviewer="codex",
        implementer="grok",
        tester="claude",
        reviewer_role="codex",
        release="human",
        chain=("claude",),
    )
    assert relay_ops.auto_summary(request) == (
        "Claude + Codex research → Claude synthesizes → Grok drafts, Codex reviews → "
        "Grok implements, Claude tests, Codex reviews → whyline commits → you release. "
        "Backup: Claude."
    )
    assert "Backup: Claude → Codex." in relay_ops.auto_summary(
        SimpleNamespace(**{**request.__dict__, "chain": ("claude", "codex")})
    )
    assert relay_ops.auto_summary(SimpleNamespace(**{**request.__dict__, "chain": ()})) == (
        "Claude + Codex research → Claude synthesizes → Grok drafts, Codex reviews → "
        "Grok implements, Claude tests, Codex reviews → whyline commits → you release. "
        "Backup: none."
    )
    monkeypatch.setattr(config, "load", lambda root: SimpleNamespace(pipeline=object()))
    text = relay_ops.auto_summary(request)
    assert text.endswith(
        " This repo has a custom pipeline; Run updates the three role agents"
        " and leaves the other stages."
    )


def _fits(widget) -> bool:
    region = widget.region
    return region.height > 0 and region.bottom <= 24


async def test_auto_check_and_cancel_fit_on_80x24(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        assert _fits(screen.query_one("#rp-check"))
        assert _fits(screen.query_one("#rp-cancel"))
        assert _fits(screen.query_one("#rp-run"))


async def test_check_asks_before_the_worker_when_antigravity_is_unresolved(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    _settings(monkeypatch, tmp_path / "gemini")
    started = _spy_worker(monkeypatch)
    ignored = _spy_ignore(monkeypatch)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, tui.ConfirmScreen)
        assert type(dialog) is not tui.ConfirmScreen
        assert dialog.__class__.__dict__["BINDINGS"] == [("escape", "dismiss(None)", "Dismiss")]
        assert dialog._message == _trust_message(repo)
        assert str(dialog.query_one("#confirm", tui.Button).label) == "Trust it"
        assert str(dialog.query_one("#cancel", tui.Button).label) == "Not now"
        assert started == []
        assert ignored == []
        assert str(screen.query_one("#rp-checks", tui.Static).renderable) == ""


async def test_escape_writes_nothing_and_skips_the_worker(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    settings = _settings(monkeypatch, tmp_path / "gemini")
    started = _spy_worker(monkeypatch)
    writers = _spy_writers(monkeypatch)
    before_paths = _repo_paths(repo)
    before_settings = settings.read_text(encoding="utf-8")
    head = _git(repo, "rev-parse", "HEAD")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        assert results == []
        assert str(screen.query_one("#rp-checks", tui.Static).renderable) == ""
        assert "-empty" in screen.query_one("#rp-checks").classes
    assert started == []
    assert writers == {"trust": 0, "decline": 0, "forget": 0}
    assert _repo_paths(repo) == before_paths
    assert settings.read_text(encoding="utf-8") == before_settings
    assert _git(repo, "rev-parse", "HEAD") == head
    assert getattr(screen, "_check_fingerprint", None) is None


async def test_a_non_true_dismiss_does_not_decline(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    _settings(monkeypatch, tmp_path / "gemini")
    started = _spy_worker(monkeypatch)
    writers = _spy_writers(monkeypatch)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        app.screen.dismiss("later")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        assert str(screen.query_one("#rp-checks", tui.Static).renderable) == ""
    assert started == []
    assert writers == {"trust": 0, "decline": 0, "forget": 0}


async def test_trust_it_updates_settings_outside_the_repo_then_cancel_leaves_them(tmp_path, monkeypatch):
    from whyline_relay import antigravity

    repo = _repo(tmp_path / "repo")
    settings = _settings(monkeypatch, tmp_path / "gemini")
    started = _spy_worker(monkeypatch)
    ignored = _spy_ignore(monkeypatch)
    before_paths = _repo_paths(repo)
    before_settings = settings.read_text(encoding="utf-8")
    head = _git(repo, "rev-parse", "HEAD")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        assert started == []
        await pilot.click("#confirm")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        assert started == [True]
        assert ignored == []
        assert _repo_paths(repo) == before_paths
        assert not settings.resolve().is_relative_to(repo.resolve())
        updated = settings.read_text(encoding="utf-8")
        assert updated != before_settings
        assert str(repo.resolve()) in json.loads(updated)["trustedWorkspaces"]
        assert relay_ops.antigravity_state(repo) == "trusted"
        await pilot.click("#rp-cancel")
        await pilot.pause()
    assert results == [None]
    assert settings.read_text(encoding="utf-8") == updated
    assert relay_ops.antigravity_state(repo) == "trusted"
    assert antigravity.is_trusted(repo)
    assert _repo_paths(repo) == before_paths
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "status", "--porcelain") == ""


async def test_not_now_adds_only_the_decline_marker_and_cancel_leaves_it(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    settings = _settings(monkeypatch, tmp_path / "gemini")
    _ignore_decline(repo)
    started = _spy_worker(monkeypatch)
    ignored = _spy_ignore(monkeypatch)
    before_paths = _repo_paths(repo)
    before_settings = settings.read_text(encoding="utf-8")
    before_exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    before_status = _git(repo, "status", "--porcelain")
    head = _git(repo, "rev-parse", "HEAD")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        assert started == []
        await pilot.click("#cancel")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        marker = repo / ".whyline" / "relay" / "antigravity-declined"
        assert marker.is_file()
        assert started == [True]
        assert ignored == []
        added = _repo_paths(repo) - before_paths
        assert added == {
            ".whyline/",
            ".whyline/relay/",
            ".whyline/relay/antigravity-declined",
        }
        assert marker.read_text(encoding="utf-8") == (
            "The user chose not to trust this repository for Antigravity.\n"
        )
        assert settings.read_text(encoding="utf-8") == before_settings
        assert (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8") == before_exclude
        assert _git(repo, "status", "--porcelain") == before_status
        assert str(screen.query_one("#rp-checks", tui.Static).renderable) == ""
        await pilot.click("#rp-cancel")
        await pilot.pause()
    assert results == [None]
    assert marker.is_file()
    assert settings.read_text(encoding="utf-8") == before_settings
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "status", "--porcelain") == before_status


@pytest.mark.parametrize("state", ["trusted", "declined", "unnamed"])
async def test_settled_or_unnamed_antigravity_does_not_rewrite_trust(tmp_path, monkeypatch, state):
    repo = _repo(tmp_path / "repo")
    settings = _settings(monkeypatch, tmp_path / "gemini")
    if state == "trusted":
        payload = {
            "trustedWorkspaces": [str(repo.resolve())],
            "permissions": {"allow": []},
        }
        settings.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    marker = repo / ".whyline" / "relay" / "antigravity-declined"
    if state == "declined":
        marker.parent.mkdir(parents=True)
        marker.write_text("already\n", encoding="utf-8")
    started = _spy_worker(monkeypatch)
    writers = _spy_writers(monkeypatch)
    before_settings = settings.read_text(encoding="utf-8")
    status = STATUS if state == "unnamed" else NAMED
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        await _open_auto(app, pilot, status)
        await pilot.click("#rp-check")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        assert not isinstance(app.screen, tui.ConfirmScreen)
    assert started == [True]
    assert writers == {"trust": 0, "decline": 0, "forget": 0}
    assert settings.read_text(encoding="utf-8") == before_settings
    if state == "declined":
        assert marker.read_text(encoding="utf-8") == "already\n"
    else:
        assert not marker.exists()


async def test_trust_failure_is_one_fail_line_and_skips_the_worker(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    settings = _settings(monkeypatch, tmp_path / "gemini")
    started = _spy_worker(monkeypatch)
    declines = []

    def fail_trust(root):
        raise RuntimeError("settings.json is broken")

    monkeypatch.setattr(relay_ops, "trust_antigravity", fail_trust)
    monkeypatch.setattr(relay_ops, "decline_antigravity", lambda root: declines.append(root))

    def refuse_fingerprint(*args, **kwargs):
        raise AssertionError("fingerprint")

    monkeypatch.setattr(auto_run, "fingerprint", refuse_fingerprint)
    before_paths = _repo_paths(repo)
    before_settings = settings.read_text(encoding="utf-8")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        assert str(screen.query_one("#rp-checks", tui.Static).renderable) == "FAIL  settings.json is broken"
        assert "-empty" not in screen.query_one("#rp-checks").classes
    assert started == []
    assert declines == []
    assert _repo_paths(repo) == before_paths
    assert settings.read_text(encoding="utf-8") == before_settings
    assert getattr(screen, "_check_fingerprint", None) is None


async def test_decline_failure_is_one_fail_line_and_skips_the_worker(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    settings = _settings(monkeypatch, tmp_path / "gemini")
    started = _spy_worker(monkeypatch)
    trusts = []

    def fail_decline(root):
        raise RuntimeError("could not write the marker")

    monkeypatch.setattr(relay_ops, "decline_antigravity", fail_decline)
    monkeypatch.setattr(relay_ops, "trust_antigravity", lambda root: trusts.append(root))
    monkeypatch.setattr(
        auto_run,
        "fingerprint",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fingerprint")),
    )
    before_paths = _repo_paths(repo)
    before_settings = settings.read_text(encoding="utf-8")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        assert isinstance(app.screen, RelayPlanScreen)
        assert str(screen.query_one("#rp-checks", tui.Static).renderable) == (
            "FAIL  could not write the marker"
        )
    assert started == []
    assert trusts == []
    assert _repo_paths(repo) == before_paths
    assert settings.read_text(encoding="utf-8") == before_settings
    assert not (repo / ".whyline" / "relay" / "antigravity-declined").exists()
    assert getattr(screen, "_check_fingerprint", None) is None


_READY_CONFIG = """\
plan = "plans/saved-missing.plan.md"
timeout_minutes = 30

[roles]
implementer = "codex"
reviewer = "claude"
"""

_HEADINGS = (
    "Repository",
    "Agents and logins",
    "Inputs",
    "Planning",
    "Execution",
    "Concurrency",
    "Will write",
)

_CLEAN_STATUS = {
    "claude": {"available": True, "label": "ok"},
    "codex": {"available": True, "label": "ok"},
    "antigravity": {"available": False, "label": "off"},
    "grok": {"available": True, "label": "ok"},
}


def _ready(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    relay = path / ".whyline" / "relay"
    relay.mkdir(parents=True)
    (path / ".whyline" / "ledger.jsonl").write_text("", encoding="utf-8")
    (relay / "config.toml").write_text(_READY_CONFIG, encoding="utf-8")
    (relay / "claude-settings.json").write_text("{}\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "ready")
    return path


def _logins(monkeypatch, *, codex_out=False) -> None:
    status = {
        agent: {"available": True, "label": "ok", "hint": None}
        for agent in ("claude", "codex", "antigravity", "grok")
    }
    if codex_out:
        status["codex"] = {
            "available": False,
            "label": "not logged in",
            "hint": "Run /login codex",
        }
    monkeypatch.setattr("whyline.account.agent_status", lambda root, status=status: status)


def _ban_writes(monkeypatch) -> None:
    def banned(name):
        def _call(*args, **kwargs):
            raise AssertionError(name)

        return _call

    for name in (
        "save_roles",
        "save_release",
        "save_planner",
        "prepare_agents",
        "select_plan",
        "trust_antigravity",
        "decline_antigravity",
        "forget_antigravity_decline",
        "approve_plan",
        "approve_spec",
    ):
        monkeypatch.setattr(relay_ops, name, banned(name))


def _checks_text(screen) -> str:
    return str(screen.query_one("#rp-checks", tui.Static).renderable)


def _status_words(text: str) -> list[str]:
    words = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("ok", "warn", "FAIL")):
            words.append(stripped.split()[0])
    return words


async def _wait_for(pilot, condition, what: str, detail=lambda: "") -> None:
    for _ in range(600):  # 30 s ceiling; CI runners are slow
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what} {detail()}".rstrip())


async def _fill_auto(screen, pilot) -> None:
    screen.query_one("#bs-topic", tui.Input).value = "fresh topic"
    screen.query_one("#rp-name", tui.Input).value = "fresh-plan"
    await pilot.pause()


async def _run_check(pilot, screen) -> str:
    # Press rather than click: the form scrolls and earlier steps add and
    # remove rows, so a click by position missed Check on CI (ubuntu, twice)
    # and the result never came. A press still runs Check's real handler.
    screen.query_one("#rp-check", tui.Button).press()
    await _wait_for(
        pilot,
        lambda: _checks_text(screen) not in ("", "Checking…"),
        "check result",
        lambda: f"(checks={_checks_text(screen)!r}, screen={type(pilot.app.screen).__name__})",
    )
    return _checks_text(screen)


async def _open_filled(app, pilot, status=None):
    screen, _results = await _open_auto(app, pilot, status or _CLEAN_STATUS)
    await _fill_auto(screen, pilot)
    return screen


async def test_warning_keeps_its_hint_and_stores_a_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        relay_ops,
        "candidate_checks",
        lambda root, request: [
            relay_ops.CheckLine("ok", "tree is clean", None, "Repository"),
            relay_ops.CheckLine("warn", "same person reviews", "split the roles", "Execution"),
        ],
    )
    monkeypatch.setattr(auto_run, "fingerprint", lambda root, request: "ab" * 32)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen = await _open_filled(app, pilot)
        text = await _run_check(pilot, screen)
        assert "Execution" in text
        assert "warn  same person reviews" in text
        assert "fix: split the roles" in text
        assert "FAIL" not in _status_words(text)
        assert screen._check_fingerprint == "ab" * 32
        assert screen.query_one("#rp-run").disabled is False


async def test_a_fail_line_keeps_its_hint_and_stores_no_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        relay_ops,
        "candidate_checks",
        lambda root, request: [
            relay_ops.CheckLine("FAIL", "topic is empty", "enter a topic", "Inputs"),
            relay_ops.CheckLine("ok", "later", None, "Will write"),
        ],
    )
    monkeypatch.setattr(auto_run, "fingerprint", lambda root, request: "nope")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen = await _open_filled(app, pilot)
        text = await _run_check(pilot, screen)
        assert text.index("Inputs") < text.index("Will write")
        assert "FAIL  topic is empty" in text
        assert "fix: enter a topic" in text
        assert screen._check_fingerprint is None


async def test_editing_the_topic_after_a_clean_check_clears_it(tmp_path, monkeypatch):
    repo = _ready(tmp_path / "repo")
    _logins(monkeypatch)
    _ban_writes(monkeypatch)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen = await _open_filled(app, pilot)
        text = await _run_check(pilot, screen)
        assert _status_words(text).count("FAIL") == 0, text
        positions = [text.index(heading) for heading in _HEADINGS]
        assert positions == sorted(positions)
        assert screen._check_fingerprint
        assert screen.query_one("#rp-run").disabled is False
        screen.query_one("#bs-topic", tui.Input).value = "a different topic"
        await pilot.pause()
        assert _checks_text(screen) == ""
        assert "-empty" in screen.query_one("#rp-checks").classes
        assert screen._check_fingerprint is None
        assert screen.query_one("#rp-run").disabled is True


async def test_porcelain_change_does_not_match_the_stored_fingerprint(tmp_path, monkeypatch):
    repo = _ready(tmp_path / "repo")
    _logins(monkeypatch)
    _ban_writes(monkeypatch)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen = await _open_filled(app, pilot)
        await _run_check(pilot, screen)
        stored = screen._check_fingerprint
        assert stored
        assert stored == auto_run.fingerprint(repo, screen._auto_request())
        (repo / "extra.txt").write_text("y\n", encoding="utf-8")
        assert auto_run.fingerprint(repo, screen._auto_request()) != stored
        assert screen._check_fingerprint == stored


async def test_auto_edits_drop_the_stored_fingerprint(tmp_path, monkeypatch):
    from whyline.console.attachments import Attachment

    repo = _ready(tmp_path / "repo")
    _logins(monkeypatch)
    _ban_writes(monkeypatch)
    outside = tmp_path / "note.txt"
    outside.write_text("note\n", encoding="utf-8")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen = await _open_filled(app, pilot)

        async def passed() -> None:
            text = await _run_check(pilot, screen)
            assert "FAIL" not in _status_words(text), text
            assert screen._check_fingerprint

        await passed()
        screen.query_one("#rp-source", tui.Select).value = "brainstorm"
        await pilot.pause()
        assert _checks_text(screen) == ""
        assert screen._check_fingerprint is None
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        assert _checks_text(screen) == ""
        assert screen._check_fingerprint is None

        await passed()
        screen.query_one("#rp-replace", tui.Checkbox).value = True
        await pilot.pause()
        assert _checks_text(screen) == ""
        assert screen._check_fingerprint is None

        await passed()
        screen.query_one("#rp-continue-paths", tui.Checkbox).value = True
        await pilot.pause()
        assert screen._check_fingerprint is None
        assert _checks_text(screen) == ""

        await passed()
        # Flip it: an unsaved chain opens on Automatic, which may tick grok.
        grok = screen.query_one("#chain-check-grok", tui.Checkbox)
        grok.value = not grok.value
        await pilot.pause()
        assert screen._check_fingerprint is None
        assert _checks_text(screen) == ""

        await passed()
        screen.query_one("#bs-attachments").pending.add(
            Attachment("n1", "note.txt", outside, "file", 5, "picker")
        )
        assert _checks_text(screen) == ""
        assert screen._check_fingerprint is None


async def _button_failure(tmp_path, monkeypatch, setup, heading: str, needle: str, *, agents=None, codex_out=False):
    repo = _ready(tmp_path / "repo")
    _logins(monkeypatch, codex_out=codex_out)
    _ban_writes(monkeypatch)
    if agents is not None:
        monkeypatch.setattr(
            relay_ops, "relay_agents", lambda root=None, which=None, agents=agents: list(agents)
        )
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen = await _open_filled(app, pilot)
        setup(screen, repo, pilot, tmp_path)
        await pilot.pause()
        before = _git(repo, "status", "--porcelain")
        text = await _run_check(pilot, screen)
        assert heading in text
        assert needle in text
        assert screen._check_fingerprint is None
        assert _git(repo, "status", "--porcelain") == before
        assert isinstance(app.screen, RelayPlanScreen)


async def test_dirty_tree_from_the_button_leaves_git_status(tmp_path, monkeypatch):
    def setup(screen, repo, pilot, tmp_path):
        (repo / "notes.txt").write_text("dirty\n", encoding="utf-8")

    await _button_failure(
        tmp_path,
        monkeypatch,
        setup,
        "Repository",
        "FAIL  working tree has uncommitted changes: notes.txt\n      fix: commit or stash your changes",
    )


async def test_logged_out_agent_from_the_button_leaves_git_status(tmp_path, monkeypatch):
    def setup(screen, repo, pilot, tmp_path):
        return None

    await _button_failure(
        tmp_path,
        monkeypatch,
        setup,
        "Agents and logins",
        "FAIL  codex is not logged in\n      fix: Run /login codex",
        codex_out=True,
    )


async def test_missing_attachment_from_the_button_leaves_git_status(tmp_path, monkeypatch):
    from whyline.console.attachments import Attachment

    missing = tmp_path / "gone.pdf"

    def setup(screen, repo, pilot, tmp_path):
        screen.query_one("#bs-attachments").pending.add(
            Attachment("m1", "gone.pdf", missing, "file", 1, "picker")
        )

    await _button_failure(
        tmp_path,
        monkeypatch,
        setup,
        "Inputs",
        f"FAIL  Attachment is missing: {missing}",
    )


async def test_path_unverified_image_from_the_button_leaves_git_status(tmp_path, monkeypatch):
    from whyline.console.attachments import Attachment

    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    def setup(screen, repo, pilot, tmp_path):
        screen.query_one("#rp-drafter", tui.Select).value = "mystery"
        screen.query_one("#bs-attachments").pending.add(
            Attachment("img", "shot.png", image, "image", image.stat().st_size, "picker")
        )

    await _button_failure(
        tmp_path,
        monkeypatch,
        setup,
        "Inputs",
        "FAIL  mystery get images as file paths only and may not see them.",
        agents=["claude", "codex", "grok", "mystery"],
    )


async def test_slug_clash_from_the_button_leaves_git_status(tmp_path, monkeypatch):
    from whyline_relay import brainstorm, specs

    def setup(screen, repo, pilot, tmp_path):
        name = "My Topic"
        paths = (
            brainstorm.shared_path(repo, name),
            repo / "docs" / "specs" / f"{specs._slug(name)}.md",
            relay_ops.plan_path(repo, name),
        )
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("exists\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "clash")
        screen.query_one("#bs-topic", tui.Input).value = name
        screen.query_one("#rp-name", tui.Input).value = name

    await _button_failure(
        tmp_path,
        monkeypatch,
        setup,
        "Planning",
        "FAIL  plans/",
    )


async def test_live_relay_from_the_button_leaves_git_status(tmp_path, monkeypatch):
    import json
    import os
    from dataclasses import asdict

    from whyline_relay import running

    def setup(screen, repo, pilot, tmp_path):
        _ignore_decline(repo)
        exclude = repo / ".git" / "info" / "exclude"
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if ".whyline/relay/running.json" not in text.splitlines():
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write(".whyline/relay/running.json\n")
        marker = running.Running(
            agent="codex",
            task="T1",
            round=1,
            started="2026-10-11T00:00:00+00:00",
            pid=os.getpid(),
            role="implementer",
        )
        path = repo / ".whyline" / "relay" / "running.json"
        path.write_text(json.dumps(asdict(marker)), encoding="utf-8")

    await _button_failure(
        tmp_path,
        monkeypatch,
        setup,
        "Concurrency",
        "another relay is running here",
    )


async def test_not_now_fails_the_trust_line_and_stores_no_fingerprint(tmp_path, monkeypatch):
    repo = _ready(tmp_path / "repo")
    _settings(monkeypatch, tmp_path / "gemini")
    _ignore_decline(repo)
    _logins(monkeypatch)
    calls = {"trust": 0, "decline": 0}
    real_trust = relay_ops.trust_antigravity
    real_decline = relay_ops.decline_antigravity

    def trust(root):
        calls["trust"] += 1
        return real_trust(root)

    def decline(root):
        calls["decline"] += 1
        return real_decline(root)

    _ban_writes(monkeypatch)
    monkeypatch.setattr(relay_ops, "trust_antigravity", trust)
    monkeypatch.setattr(relay_ops, "decline_antigravity", decline)
    before = _git(repo, "status", "--porcelain")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _results = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        assert isinstance(app.screen, tui.ConfirmScreen)
        await pilot.click("#cancel")
        await _wait_for(
            pilot,
            lambda: "Antigravity is not trusted for this repo" in _checks_text(screen),
            "trust fail",
        )
        text = _checks_text(screen)
        assert "Agents and logins" in text
        assert "FAIL  Antigravity is not trusted for this repo" in text
        assert screen._check_fingerprint is None
        assert _git(repo, "status", "--porcelain") == before
    assert calls == {"trust": 0, "decline": 1}


async def test_trust_it_marks_the_trust_line_ok(tmp_path, monkeypatch):
    repo = _ready(tmp_path / "repo")
    _settings(monkeypatch, tmp_path / "gemini")
    _logins(monkeypatch)
    calls = {"trust": 0, "decline": 0}
    real_trust = relay_ops.trust_antigravity
    real_decline = relay_ops.decline_antigravity

    def trust(root):
        calls["trust"] += 1
        return real_trust(root)

    def decline(root):
        calls["decline"] += 1
        return real_decline(root)

    _ban_writes(monkeypatch)
    monkeypatch.setattr(relay_ops, "trust_antigravity", trust)
    monkeypatch.setattr(relay_ops, "decline_antigravity", decline)
    before = _git(repo, "status", "--porcelain")
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _results = await _open_auto(app, pilot, NAMED)
        await pilot.click("#rp-check")
        await pilot.pause()
        await pilot.click("#confirm")
        await _wait_for(
            pilot,
            lambda: "Antigravity is trusted for this repo" in _checks_text(screen),
            "trust ok",
        )
        text = _checks_text(screen)
        assert text.index("Agents and logins") < text.index("Antigravity is trusted for this repo")
        assert "ok    Antigravity is trusted for this repo" in text
        assert "Antigravity is not trusted for this repo" not in text
        assert "Antigravity trust is not resolved" not in text
        assert _git(repo, "status", "--porcelain") == before
    assert calls == {"trust": 1, "decline": 0}


def _auto_request(**overrides) -> plan_job.AutoRunRequest:
    fields = dict(
        name="resume-test",
        topic="my-topic",
        replace=False,
        continue_paths=False,
        agents=("codex",),
        passes=1,
        final_agent="codex",
        timeout_minutes=15,
        attachments=(),
        drafter="claude",
        reviewer="codex",
        implementer="grok",
        tester="claude",
        reviewer_role="codex",
        release="human",
        chain=("codex",),
    )
    fields.update(overrides)
    return plan_job.AutoRunRequest(**fields)


async def test_untracked_file_makes_run_refuse_with_out_of_date_line(tmp_path, monkeypatch):
    repo = _ready(tmp_path / "repo")
    _logins(monkeypatch)
    _ban_writes(monkeypatch)
    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen = await _open_filled(app, pilot)
        text = await _run_check(pilot, screen)
        assert _status_words(text).count("FAIL") == 0
        assert screen._check_fingerprint is not None
        assert screen.query_one("#rp-run").disabled is False

        (repo / "untracked.txt").write_text("hello\n", encoding="utf-8")
        screen.query_one("#rp-run").scroll_visible()
        await pilot.pause()
        await pilot.click("#rp-run")
        await pilot.pause()

        assert app.screen is screen
        assert screen._check_fingerprint is None
        assert screen.query_one("#rp-run").disabled is True

        lines = [str(line) for line in app.screen_stack[0].query_one("#transcript", tui.RichLog).lines]
        assert any("This check is out of date. Check again." in line for line in lines)


async def test_clean_check_run_dismisses_with_request_and_fingerprint(tmp_path, monkeypatch):
    repo = _ready(tmp_path / "repo")
    _logins(monkeypatch)
    _ban_writes(monkeypatch)
    app = tui.WhylineConsoleApp(root=repo)
    dismissed = []
    async with app.run_test(size=(110, 40)) as pilot:
        screen = await _open_filled(app, pilot)
        screen.dismiss = lambda result: dismissed.append(result)
        text = await _run_check(pilot, screen)
        assert _status_words(text).count("FAIL") == 0
        stored = screen._check_fingerprint
        assert stored is not None

        screen.query_one("#rp-run").scroll_visible()
        await pilot.pause()
        await pilot.click("#rp-run")
        await pilot.pause()

        assert len(dismissed) == 1
        req, fp = dismissed[0]
        assert isinstance(req, plan_job.AutoRunRequest)
        assert fp == stored


async def test_checkpoint_loaded_when_paused_and_enabled_if_fresh_match(tmp_path, monkeypatch):
    from whyline.state import atomic_write_json
    from whyline_relay import gitcheck

    repo = _ready(tmp_path / "repo")
    gitcheck.ensure_relay_ignored(repo)
    _logins(monkeypatch)
    _ban_writes(monkeypatch)

    req = _auto_request()
    doc = auto_run.document(repo, req)
    fp = auto_run.fingerprint(repo, req)
    checkpoint = {
        "schema": 1,
        "phase": "paused",
        "fingerprint": fp,
        "request": auto_run._form_view(doc),
        "pause": {"reason": "paused for test", "actions": ["resume", "cancel"]},
    }
    cp_path = auto_run.checkpoint_path(repo)
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cp_path, checkpoint)

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()

        run_btn = screen.query_one("#rp-run", tui.Button)
        assert str(run_btn.label) == "Resume"
        assert run_btn.disabled is False
        assert screen.query_one("#rp-name", tui.Input).value == "resume-test"
        assert screen.query_one("#bs-topic", tui.Input).value == "my-topic"


async def test_checkpoint_dirty_tree_disables_resume(tmp_path, monkeypatch):
    from whyline.state import atomic_write_json
    from whyline_relay import gitcheck

    repo = _ready(tmp_path / "repo")
    gitcheck.ensure_relay_ignored(repo)
    _logins(monkeypatch)
    _ban_writes(monkeypatch)

    req = _auto_request()
    doc = auto_run.document(repo, req)
    fp = auto_run.fingerprint(repo, req)
    checkpoint = {
        "schema": 1,
        "phase": "paused",
        "fingerprint": fp,
        "request": auto_run._form_view(doc),
        "pause": {"reason": "paused for test", "actions": ["resume", "cancel"]},
    }
    cp_path = auto_run.checkpoint_path(repo)
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cp_path, checkpoint)

    (repo / "dirty.txt").write_text("modified\n")

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()

        run_btn = screen.query_one("#rp-run", tui.Button)
        assert str(run_btn.label) == "Resume"
        assert run_btn.disabled is True


async def test_relay_plan_screen_with_no_agents(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: [])
    from whyline.console.relay_screens import NO_AGENTS_PLAN

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, results = await _open(app, pilot)
        # Brainstorm / draft mode: roles row shows NO_AGENTS_PLAN
        assert any(NO_AGENTS_PLAN in str(label.renderable) for label in screen.query(tui.Label))
        assert screen.query_one("#rp-check", tui.Button).disabled
        assert screen.query_one("#rp-go", tui.Button).disabled

        # Switch to Auto: auto widgets also show NO_AGENTS_PLAN
        screen.query_one("#rp-source", tui.Select).value = "auto"
        await pilot.pause()
        assert any(NO_AGENTS_PLAN in str(label.renderable) for label in screen.query(tui.Label))
        assert screen.query_one("#rp-check", tui.Button).disabled
        assert screen.query_one("#rp-run", tui.Button).disabled

        # Cancel works
        assert not screen.query_one("#rp-cancel", tui.Button).disabled
        screen.query_one("#rp-cancel", tui.Button).press()
        await pilot.pause()
        assert results == [None]


async def test_relay_plan_screen_with_one_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["codex"])
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "codex"))

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        screen, _ = await _open(app, pilot)
        # Selects are present and enabled
        drafter = screen.query_one("#rp-drafter", tui.Select)
        assert drafter.value == "codex"
        assert not screen.query_one("#rp-go", tui.Button).disabled



