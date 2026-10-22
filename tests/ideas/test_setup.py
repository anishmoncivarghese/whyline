import argparse
import io
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from whyline import account
from whyline.console import relay_ops
from whyline.console.plan_job import AutoRunRequest
from whyline.ideas import bot, cli, paths, setup, store

CHAT = 42


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


@pytest.fixture
def fake_repo(tmp_path):
    repo_dir = tmp_path / "repo1"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo_dir, check=True)

    wl_dir = repo_dir / ".whyline"
    wl_dir.mkdir(parents=True, exist_ok=True)
    (wl_dir / "ledger.jsonl").write_text('{"event": "init"}\n')

    relay_dir = wl_dir / "relay"
    relay_dir.mkdir(parents=True, exist_ok=True)
    config_toml = """\
timeout_minutes = 45

[roles]
implementer = "codex"
reviewer = "claude"

[backup]
chain = ["codex"]

[planner]
draft = "codex"
review = "claude"
"""
    (relay_dir / "config.toml").write_text(config_toml)
    return repo_dir


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(bot.telegram, "token_get", lambda: "1234:TOKEN")
    return "1234:TOKEN"


def _seed_idea(conn, text="Build receipt parser", status="brainstormed", repo=None):
    idea = store.add(conn, text, source="telegram", source_ref=f"{CHAT}:1")
    if repo:
        store.set_repo(conn, idea.id, repo)
    if status != "captured":
        conn.execute("UPDATE ideas SET status = ? WHERE id = ?", (status, idea.id))
    # Give it a brainstorm path
    bs_file = paths.home() / "brainstorms" / f"{idea.id}.md"
    bs_file.parent.mkdir(parents=True, exist_ok=True)
    bs_file.write_text("## Final Synthesis\nReceipt parser idea")
    store.set_paths(conn, idea.id, brainstorm_path=str(bs_file))
    return store.get(conn, idea.id)


def _message(text, *, update_id=1, message_id=5):
    return {
        "update_id": update_id,
        "handled": 0,
        "chat_id": CHAT,
        "text": text,
        "callback_data": None,
        "reply_to_message_id": None,
        "at": "2026-10-20T10:00:00Z",
        "kind": "message",
        "raw": json.dumps({"message_id": message_id}),
    }


def _press(data, callback_id, *, update_id=2):
    return {
        "update_id": update_id,
        "handled": 0,
        "chat_id": CHAT,
        "text": None,
        "callback_data": data,
        "reply_to_message_id": None,
        "at": "2026-10-20T10:00:00Z",
        "kind": "callback",
        "raw": json.dumps({"id": callback_id}),
    }


def _outbox(conn, kind=None):
    if kind is None:
        return conn.execute("SELECT * FROM outbox ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM outbox WHERE kind = ? ORDER BY id", (kind,)
    ).fetchall()


def _mock_agents(monkeypatch, *, ag_trusted=True, grok_available=True):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"])
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root, which=None: {
            "claude": {"available": True},
            "codex": {"available": True},
            "grok": {"available": grok_available},
            "antigravity": {"available": True},
        },
    )
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted" if ag_trusted else "ask")


def test_repos_add_list_remove(conn, fake_repo, tmp_path):
    # Non-directory
    with pytest.raises(setup.SetupError, match="not a directory"):
        setup.add_repo(conn, "repo1", tmp_path / "nonexistent")

    # Non-git
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    with pytest.raises(setup.SetupError, match="not a git repository"):
        setup.add_repo(conn, "repo1", plain_dir)

    # Git repo but not initialised
    git_only = tmp_path / "git_only"
    git_only.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=git_only, check=True)
    with pytest.raises(setup.SetupError, match="whyline is not initialised"):
        setup.add_repo(conn, "repo1", git_only)

    # Success
    resolved = setup.add_repo(conn, "repo1", fake_repo)
    assert resolved == str(fake_repo.resolve())

    # Dotted repo name accepted
    setup.add_repo(conn, "api.v2", fake_repo)
    assert setup.list_repos(conn)["api.v2"] == str(fake_repo.resolve())
    setup.remove_repo(conn, "api.v2")

    # Name validation
    with pytest.raises(setup.SetupError, match="cannot contain whitespace or colons"):
        setup.add_repo(conn, "repo 1", fake_repo)

    # List
    repos = setup.list_repos(conn)
    assert repos == {"repo1": str(fake_repo.resolve())}

    # Remove
    assert setup.remove_repo(conn, "repo1") is True
    assert setup.remove_repo(conn, "repo1") is False
    assert setup.list_repos(conn) == {}


def test_repos_cli(conn, fake_repo):
    out = io.StringIO()
    err = io.StringIO()

    # List empty
    with redirect_stdout(out):
        assert cli.cmd_repos(argparse.Namespace(idea_repos_command="list")) == 0
    assert "No repositories configured." in out.getvalue()

    # Add
    out = io.StringIO()
    with redirect_stdout(out):
        assert (
            cli.cmd_repos(
                argparse.Namespace(
                    idea_repos_command="add", name="main", path=str(fake_repo)
                )
            )
            == 0
        )
    assert f"main  {fake_repo.resolve()}" in out.getvalue()

    # List with item
    out = io.StringIO()
    with redirect_stdout(out):
        assert cli.cmd_repos(argparse.Namespace(idea_repos_command="list")) == 0
    assert f"main  {fake_repo.resolve()}" in out.getvalue()

    # Remove
    out = io.StringIO()
    with redirect_stdout(out):
        assert (
            cli.cmd_repos(
                argparse.Namespace(idea_repos_command="remove", name="main")
            )
            == 0
        )
    assert "main  removed" in out.getvalue()


def test_card_shows_configured_roles_as_defaults(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "My new idea", status="brainstormed")

    # Tap Create spec and plan ("plan")
    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))

    # Skipped repo asking because only one repo allowlisted; sends Set up card
    fresh_idea = store.get(conn, idea.id)
    assert fresh_idea.status == "setup_configuring"
    assert fresh_idea.repo == "repo1"

    out = _outbox(conn, "message")
    assert len(out) == 1
    card_text = out[0]["text"]
    assert "Set up will use:" in card_text
    assert "repo: repo1" in card_text
    assert "implementer: codex" in card_text
    assert "tester: claude" in card_text
    assert "reviewer: claude" in card_text
    assert "release: human" in card_text
    assert "backup: codex" in card_text
    assert "timeout: 45" in card_text
    assert "drafter: codex" in card_text
    assert "plan_reviewer: claude" in card_text

    buttons = json.loads(out[0]["buttons_json"])
    labels = [cell["text"] for row in buttons for cell in row]
    assert labels == ["Confirm", "Edit", "Cancel"]
    assert buttons[0][0]["callback_data"] == f"confirm:{idea.id}:{fresh_idea.revision}"


def test_settings_edit_updates_card_and_bumps_revision(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "My idea", status="brainstormed")

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    rev1 = store.get(conn, idea.id).revision

    # Send settings edit
    bot.handle(conn, _message("implementer: grok\ntimeout: 60"))

    fresh = store.get(conn, idea.id)
    assert fresh.revision == rev1 + 1

    out = _outbox(conn, "message")
    card_text = out[0]["text"]
    assert "implementer: grok" in card_text
    assert "timeout: 60" in card_text

    buttons = json.loads(out[0]["buttons_json"])
    assert buttons[0][0]["callback_data"] == f"confirm:{idea.id}:{fresh.revision}"


def test_agent_not_logged_in_is_refused_naming_it(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch, grok_available=False)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "My idea", status="brainstormed")

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    rev1 = store.get(conn, idea.id).revision

    # Edit naming grok (which is not available)
    bot.handle(conn, _message("implementer: grok"))

    # Revision not bumped
    assert store.get(conn, idea.id).revision == rev1

    # Bot replied with refusal naming grok
    out = _outbox(conn, "message")
    latest_reply = out[-1]["text"]
    assert "grok: not logged in" in latest_reply


def test_untrusted_antigravity_refused_with_reason(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch, ag_trusted=False)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "My idea", status="brainstormed")

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    rev1 = store.get(conn, idea.id).revision

    # Try setting implementer to antigravity
    bot.handle(conn, _message("implementer: antigravity"))

    # Refused naming the reason
    assert store.get(conn, idea.id).revision == rev1
    out = _outbox(conn, "message")
    latest_reply = out[-1]["text"]
    assert "Antigravity is not trusted for this repo" in latest_reply


def test_defaults_offers_next_usable_when_antigravity_untrusted(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch, ag_trusted=False)
    # Configure repo with antigravity as implementer
    relay_dir = fake_repo / ".whyline" / "relay"
    config_toml = """\
[roles]
implementer = "antigravity"
reviewer = "claude"
"""
    (relay_dir / "config.toml").write_text(config_toml)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "My idea", status="brainstormed")

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))

    out = _outbox(conn, "message")
    card_text = out[0]["text"]
    # Card says so and offers next usable agent
    assert "Antigravity is not trusted for this repo" in card_text
    assert "implementer: " in card_text
    assert "implementer: antigravity" not in card_text


def test_release_codex_is_refused(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "My idea", status="brainstormed")

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    rev1 = store.get(conn, idea.id).revision

    bot.handle(conn, _message("release: codex"))

    assert store.get(conn, idea.id).revision == rev1
    out = _outbox(conn, "message")
    latest_reply = out[-1]["text"]
    assert "release other than 'human' is refused" in latest_reply


def test_cancel_returns_to_brainstormed(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "My idea", status="brainstormed")

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    configured = store.get(conn, idea.id)
    assert configured.status == "setup_configuring"

    # Tap Cancel
    bot.handle(conn, _press(f"cancel:{idea.id}:{configured.revision}", "cb2"))

    cancelled = store.get(conn, idea.id)
    assert cancelled.status == "brainstormed"
    out = _outbox(conn, "message")
    assert out[-1]["text"] == "Cancelled."


def test_request_round_trips_confirmed_values(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "My idea topic", status="brainstormed")

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    # Edit some fields
    bot.handle(conn, _message("implementer: grok\ntimeout: none\nbackup: codex, claude"))
    configured = store.get(conn, idea.id)

    # Tap Confirm
    bot.handle(conn, _press(f"confirm:{idea.id}:{configured.revision}", "cb2"))

    req = setup.request(conn, idea.id)
    assert isinstance(req, AutoRunRequest)
    assert req.name == idea.title
    assert req.topic == idea.original_text
    assert req.implementer == "grok"
    assert req.tester == "claude"
    assert req.reviewer_role == "claude"
    assert req.release == "human"
    assert req.chain == ("codex", "claude")
    assert req.timeout_minutes == 0  # 'none' maps to 0
    assert req.drafter == "codex"
    assert req.reviewer == "claude"
    assert req.attachments == (Path(idea.brainstorm_path),)


def test_multiple_repos_asks_for_repo_first(conn, token, fake_repo, tmp_path, monkeypatch):
    _mock_agents(monkeypatch)
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo2, check=True)
    wl_dir = repo2 / ".whyline"
    wl_dir.mkdir(parents=True, exist_ok=True)
    (wl_dir / "ledger.jsonl").write_text('{"event": "init"}\n')

    setup.add_repo(conn, "alpha", fake_repo)
    setup.add_repo(conn, "beta", repo2)
    idea = _seed_idea(conn, "Multi-repo idea", status="brainstormed")

    # Tap Create spec and plan
    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))

    # Shows repo selection buttons
    out = _outbox(conn, "message")
    assert "Which repository should this idea be planned into?" in out[0]["text"]
    buttons = json.loads(out[0]["buttons_json"])
    labels = [cell["text"] for row in buttons for cell in row]
    assert "alpha" in labels
    assert "beta" in labels

    # Tap alpha
    rev = store.get(conn, idea.id).revision
    bot.handle(conn, _press(f"repo_alpha:{idea.id}:{rev}", "cb2"))

    # Now Set up card is shown for alpha
    assert store.get(conn, idea.id).repo == "alpha"
    out2 = _outbox(conn, "message")
    card_text = out2[-1]["text"]
    assert "Set up will use:" in card_text
    assert "repo: alpha" in card_text


def test_defaults_substitutes_untrusted_antigravity_for_all_roles(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch, ag_trusted=False)
    relay_dir = fake_repo / ".whyline" / "relay"
    config_toml = """\
[roles]
implementer = "antigravity"
reviewer = "claude"

[backup]
chain = ["antigravity", "codex"]

[planner]
draft = "antigravity"
review = "antigravity"
"""
    (relay_dir / "config.toml").write_text(config_toml)
    setup.add_repo(conn, "repo1", fake_repo)

    idea = _seed_idea(conn, "Idea with untrusted AG", status="brainstormed")
    setup._kv_set(
        conn,
        f"telegram_settings:{idea.id}",
        json.dumps({"models": ["antigravity", "codex"], "final": "antigravity", "passes": 1}),
    )

    req, notes = setup.defaults(conn, idea.id, "repo1", fake_repo)
    assert req.implementer != "antigravity"
    assert req.drafter != "antigravity"
    assert req.plan_reviewer != "antigravity"
    assert "antigravity" not in req.models
    assert req.final != "antigravity"
    assert "antigravity" not in req.backup

    notes_text = "\n".join(notes)
    assert "Antigravity is not trusted for this repo; offered" in notes_text
    assert "implementer" in notes_text
    assert "drafter" in notes_text
    assert "plan_reviewer" in notes_text
    assert "models" in notes_text
    assert "final" in notes_text
    assert "Antigravity is not trusted for this repo; removed from backup" in notes_text

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    out = _outbox(conn, "message")
    card_text = out[0]["text"]
    assert "implementer: antigravity" not in card_text
    assert "drafter: antigravity" not in card_text
    assert "plan_reviewer: antigravity" not in card_text
    assert "final: antigravity" not in card_text
    assert "models: antigravity" not in card_text
    assert "Antigravity is not trusted for this repo" in card_text


def test_defaults_substitutes_unusable_agents_for_all_roles(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch, grok_available=False)
    relay_dir = fake_repo / ".whyline" / "relay"
    config_toml = """\
[roles]
implementer = "grok"
reviewer = "claude"

[backup]
chain = ["grok", "codex"]

[planner]
draft = "grok"
review = "grok"
"""
    (relay_dir / "config.toml").write_text(config_toml)
    setup.add_repo(conn, "repo1", fake_repo)

    idea = _seed_idea(conn, "Idea with unavailable grok", status="brainstormed")
    setup._kv_set(
        conn,
        f"telegram_settings:{idea.id}",
        json.dumps({"models": ["grok", "codex"], "final": "grok", "passes": 1}),
    )

    req, notes = setup.defaults(conn, idea.id, "repo1", fake_repo)
    assert req.implementer != "grok"
    assert req.drafter != "grok"
    assert req.plan_reviewer != "grok"
    assert "grok" not in req.models
    assert req.final != "grok"
    assert "grok" not in req.backup

    notes_text = "\n".join(notes)
    assert "grok: not installed or logged in; offered" in notes_text
    assert "implementer" in notes_text
    assert "drafter" in notes_text
    assert "plan_reviewer" in notes_text
    assert "final" in notes_text
    assert "grok: not installed or logged in; removed from backup" in notes_text

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    out = _outbox(conn, "message")
    card_text = out[0]["text"]
    assert "implementer: grok" not in card_text
    assert "drafter: grok" not in card_text
    assert "plan_reviewer: grok" not in card_text
    assert "final: grok" not in card_text
    assert "grok: not installed or logged in" in card_text


def test_settings_edit_refuses_untrusted_antigravity_for_every_role(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch, ag_trusted=False)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Edit AG test", status="brainstormed")
    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    rev1 = store.get(conn, idea.id).revision

    for edit in (
        "drafter: antigravity",
        "plan_reviewer: antigravity",
        "final: antigravity",
        "models: antigravity, codex",
        "backup: antigravity",
    ):
        bot.handle(conn, _message(edit))
        assert store.get(conn, idea.id).revision == rev1
        out = _outbox(conn, "message")
        assert "Antigravity is not trusted for this repo" in out[-1]["text"]


def test_settings_edit_refuses_unusable_agent_for_every_role(conn, token, fake_repo, monkeypatch):
    _mock_agents(monkeypatch, grok_available=False)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "Edit grok test", status="brainstormed")
    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    rev1 = store.get(conn, idea.id).revision

    for edit in (
        "drafter: grok",
        "plan_reviewer: grok",
        "final: grok",
        "models: grok, codex",
        "backup: grok",
    ):
        bot.handle(conn, _message(edit))
        assert store.get(conn, idea.id).revision == rev1
        out = _outbox(conn, "message")
        assert "grok: not logged in" in out[-1]["text"]


def test_repo_only_edit_revalidates_carried_agents_for_new_repo(conn, token, fake_repo, tmp_path, monkeypatch):
    _mock_agents(monkeypatch)
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo2, check=True)
    (repo2 / ".whyline").mkdir()
    (repo2 / ".whyline" / "ledger.jsonl").write_text('{"event": "init"}\n')
    (fake_repo / ".whyline" / "relay" / "config.toml").write_text(
        '[roles]\nimplementer = "antigravity"\nreviewer = "claude"\n'
    )
    setup.add_repo(conn, "alpha", fake_repo)
    setup.add_repo(conn, "beta", repo2)
    # Antigravity is trusted only in alpha.
    monkeypatch.setattr(
        relay_ops,
        "antigravity_state",
        lambda root: "trusted" if Path(root).resolve() == fake_repo.resolve() else "ask",
    )
    idea = _seed_idea(conn, "Repo switch idea", status="brainstormed")
    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))
    rev = store.get(conn, idea.id).revision
    bot.handle(conn, _press(f"repo_alpha:{idea.id}:{rev}", "cb2"))
    assert "implementer: antigravity" in _outbox(conn, "message")[-1]["text"]
    rev1 = store.get(conn, idea.id).revision

    bot.handle(conn, _message("repo: beta"))
    assert store.get(conn, idea.id).revision == rev1
    assert store.get(conn, idea.id).repo == "alpha"
    assert "Antigravity is not trusted for this repo" in _outbox(conn, "message")[-1]["text"]

    # An agent logged in only for alpha is refused, naming it, on the switch.
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted")
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root, which=None: {
            "claude": {"available": True},
            "codex": {"available": True},
            "grok": {"available": True},
            "antigravity": {"available": Path(root).resolve() == fake_repo.resolve()},
        },
    )
    bot.handle(conn, _message("repo: beta", update_id=3, message_id=6))
    assert store.get(conn, idea.id).revision == rev1
    assert "antigravity: not logged in" in _outbox(conn, "message")[-1]["text"]

    # Switching together with a usable replacement is accepted.
    bot.handle(
        conn,
        _message("repo: beta\nimplementer: codex\ndrafter: codex", update_id=4, message_id=7),
    )
    assert store.get(conn, idea.id).repo == "beta"
    assert store.get(conn, idea.id).revision > rev1


def _mock_status(monkeypatch, available, *, ag_trusted=False):
    monkeypatch.setattr(relay_ops, "relay_agents", lambda root=None, which=None: ["claude", "codex", "grok", "antigravity"])
    monkeypatch.setattr(
        account,
        "agent_status",
        lambda root, which=None: {
            name: {"available": name in available}
            for name in ("claude", "codex", "grok", "antigravity")
        },
    )
    monkeypatch.setattr(relay_ops, "antigravity_state", lambda root: "trusted" if ag_trusted else "ask")


@pytest.mark.parametrize(
    ("available", "reason"),
    [
        ((), "no agent is installed and logged in"),
        (("antigravity",), "Antigravity is the only logged-in agent and it is not trusted"),
    ],
)
def test_no_usable_agent_refuses_setup_card(conn, token, fake_repo, monkeypatch, available, reason):
    _mock_status(monkeypatch, available)
    setup.add_repo(conn, "repo1", fake_repo)
    idea = _seed_idea(conn, "No agents idea", status="brainstormed")

    with pytest.raises(setup.SetupError, match=reason):
        setup.defaults(conn, idea.id, "repo1")

    bot.handle(conn, _press(f"plan:{idea.id}:{idea.revision}", "cb1"))

    texts = [r["text"] for r in _outbox(conn, "message")]
    assert any("No usable agent for repo1" in t and reason in t for t in texts)
    # No Set up card offering agents that are not usable was sent.
    assert not any("implementer:" in t for t in texts)
    assert store.get(conn, idea.id).status == "brainstormed"
