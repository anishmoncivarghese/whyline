import subprocess
from pathlib import Path

import pytest
from textual.css.query import NoMatches

from whyline.console import adapters, mac_input, plan_job, relay_ops, tui
from whyline.console.attachments_ui import AttachmentsField, summary_text
from whyline.console.relay_screens import RelayPlanScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
]

STATUS = {
    agent: {"available": agent in ("claude", "codex"), "label": "ok"}
    for agent in ("claude", "codex", "antigravity", "grok")
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / ".whyline").mkdir()
    (tmp_path / ".whyline" / ".gitignore").write_text("ledger.jsonl\n")
    monkeypatch.setattr(mac_input, "available", lambda: True)
    monkeypatch.setattr(relay_ops, "pending_draft", lambda root: None)
    monkeypatch.setattr(relay_ops, "brainstorm_docs", lambda root: [])
    monkeypatch.setattr(
        relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok"]
    )
    monkeypatch.setattr(relay_ops, "planner_agents", lambda root: ("codex", "claude"))
    monkeypatch.setattr(relay_ops, "delivery_for", lambda root, agent, kind: "path")
    return tmp_path


def test_summary_text_groups_agents():
    statuses = {
        "claude": "path",
        "codex": "native",
        "grok": "path-unverified",
        "antigravity": "path-unverified",
    }
    assert (
        summary_text(statuses)
        == "✓ claude, codex · ⚠ grok, antigravity get images as file paths only"
    )
    assert summary_text({"claude": "path"}) == "✓ claude"


def test_plan_requests_carry_attachments(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda *a: None)
    monkeypatch.setattr(
        relay_ops,
        "draft_plan",
        lambda root, description, attachments, progress: calls.append(list(attachments))
        or relay_ops.Draft(
            path=tmp_path / "d.md",
            text="- [ ] T-1: x\n",
            drafted_by="codex",
            source="planner",
        ),
    )
    (tmp_path / "d.md").write_text("- [ ] T-1: x\n")
    shot = tmp_path / "shot.png"
    request = plan_job.PlanRequest(
        "draft",
        "p",
        description="x",
        drafter="codex",
        reviewer="claude",
        attachments=(shot,),
        spec_first=False,
    )
    plan_job.run_request(tmp_path, request, lambda line: None)
    assert calls == [[shot]]


def test_brainstorm_passes_attachments_to_every_pass(tmp_path, monkeypatch):
    from whyline_relay import brainstorm

    seen = []
    for name in ("run_pass_zero", "run_review_pass", "run_final_synthesis"):
        monkeypatch.setattr(
            brainstorm,
            name,
            lambda *a, _n=name, **k: seen.append((_n, list(k.get("attachments", ()))))
            or ({} if _n != "run_final_synthesis" else {"agent": "claude", "response": "ok"}),
        )
    monkeypatch.setattr(brainstorm, "check_availability", lambda settings, models: [])
    monkeypatch.setattr(brainstorm, "merge_pass_zero", lambda *a, **k: None)
    monkeypatch.setattr(brainstorm, "temp_path", lambda root, key: tmp_path / "r.md")
    (tmp_path / "r.md").write_text("research")
    shot = tmp_path / "shot.png"
    adapters.run_brainstorm(
        tmp_path,
        topic="t",
        agents=["claude"],
        passes=1,
        final_agent="claude",
        attachments=[shot],
    )
    assert [s[1] for s in seen] == [[shot], [shot], [shot]]


@pytest.mark.asyncio
async def test_relay_plan_screen_attaches_files_and_omits_refs(repo, monkeypatch, tmp_path_factory):
    shot = tmp_path_factory.mktemp("files") / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    monkeypatch.setattr(mac_input, "pick_files", lambda: [shot])

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        screen = RelayPlanScreen(repo, STATUS, "claude")
        app.push_screen(screen, results.append)
        await pilot.pause()

        with pytest.raises(NoMatches):
            screen.query_one("#rp-refs")

        screen.query_one("#att-pick", tui.Button).press()  # by widget, not screen position
        for _ in range(100):
            if screen.query_one("#rp-attachments", AttachmentsField).pending.items:
                break
            await pilot.pause(0.05)

        screen.query_one("#rp-name", tui.Input).value = "Trading v1"
        screen.query_one("#rp-description").load_text("Build the PRD")
        screen.query_one("#rp-go", tui.Button).press()
        for _ in range(100):  # slow CI runners need more than one frame
            if results:
                break
            await pilot.pause(0.05)

    assert len(results) == 1
    req = results[0]
    assert isinstance(req, plan_job.PlanRequest)
    assert len(req.attachments) == 1
    assert req.attachments[0].name == "shot.png"


@pytest.mark.asyncio
async def test_relay_plan_screen_warns_on_unverified_attachments(
    repo, monkeypatch, tmp_path_factory
):
    shot = tmp_path_factory.mktemp("files") / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    monkeypatch.setattr(mac_input, "pick_files", lambda: [shot])
    monkeypatch.setattr(relay_ops, "delivery_for", lambda root, agent, kind: "path-unverified")

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        screen = RelayPlanScreen(repo, STATUS, "claude")
        app.push_screen(screen, results.append)
        await pilot.pause()

        screen.query_one("#att-pick", tui.Button).press()  # by widget, not screen position
        for _ in range(100):
            if screen.query_one("#rp-attachments", AttachmentsField).pending.items:
                break
            await pilot.pause(0.05)

        screen.query_one("#rp-description").load_text("Build the PRD")
        screen.query_one("#rp-go", tui.Button).press()
        for _ in range(100):  # slow CI runners need more than one frame
            if isinstance(app.screen, tui.ConfirmScreen):
                break
            await pilot.pause(0.05)

        assert isinstance(app.screen, tui.ConfirmScreen)
        app.screen.query_one("#confirm", tui.Button).press()  # by widget: no click geometry on slow runners
        await pilot.pause()
        await pilot.pause()

    assert len(results) == 1
    assert len(results[0].attachments) == 1


@pytest.mark.asyncio
async def test_brainstorm_screen_attaches_and_warns(repo, monkeypatch, tmp_path_factory):
    shot = tmp_path_factory.mktemp("files") / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    monkeypatch.setattr(mac_input, "pick_files", lambda: [shot])
    monkeypatch.setattr(relay_ops, "delivery_for", lambda root, agent, kind: "path-unverified")

    app = tui.WhylineConsoleApp(root=repo)
    async with app.run_test(size=(110, 50)) as pilot:
        results = []
        screen = tui.BrainstormScreen(STATUS, "claude")
        app.push_screen(screen, results.append)
        await pilot.pause()

        screen.query_one("#att-pick", tui.Button).press()  # by widget, not screen position
        for _ in range(100):
            if screen.query_one("#bs-attachments", AttachmentsField).pending.items:
                break
            await pilot.pause(0.05)

        assert screen.query_one("#bs-attachments", AttachmentsField).pending.items
        screen.query_one("#bs-topic", tui.Input).value = "Brainstorming topic"
        screen.query_one("#bs-start", tui.Button).press()  # by widget, not screen position
        for _ in range(100):  # slow CI runners need more than one frame
            if isinstance(app.screen, tui.ConfirmScreen):
                break
            await pilot.pause(0.05)

        assert isinstance(app.screen, tui.ConfirmScreen)
        app.screen.query_one("#confirm", tui.Button).press()  # by widget: no click geometry on slow runners
        await pilot.pause()
        await pilot.pause()

    assert len(results) == 1
    assert "attachments" in results[0]
    assert len(results[0]["attachments"]) == 1

