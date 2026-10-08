import json
import os

from whyline.agents import definitions as d, deliveries as dl, paths, telegram


def test_settings_live_in_their_own_folder_and_are_not_agents(home):
    dl.save("personal:jobs", dl.Delivery(email=("a@example.com",)))
    telegram.remember_chats({11: "Anish V (private)"})
    settings = home / ".whyline/agents/settings"
    assert dl.path() == settings / "deliveries.toml" and dl.path().is_file()
    assert (settings / "telegram-chats.toml").is_file()
    assert [item for item in d.discover(None) if isinstance(item, d.Broken)] == []
    if os.name != "nt":
        assert (settings.stat().st_mode & 0o777) == 0o700


def test_older_settings_files_move_into_the_settings_folder(home):
    # 0.3.38 builds before this fix kept them beside the personal agents,
    # where they were listed as broken agents.
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "telegram-chats.toml").write_text('[chats]\n"11" = "Anish V (private)"\n', encoding="utf-8")
    (folder / "deliveries.toml").write_text(
        '["personal:jobs"]\nemail = ["a@example.com"]\n', encoding="utf-8")
    assert telegram.known_chats() == {11: "Anish V (private)"}
    assert dl.get("personal:jobs").email == ("a@example.com",)
    assert not (folder / "telegram-chats.toml").exists() and not (folder / "deliveries.toml").exists()
    assert [item for item in d.discover(None) if isinstance(item, d.Broken)] == []


def test_an_agent_named_like_a_settings_file_does_not_clash(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "deliveries.toml").write_text(
        f'name="deliveries"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n',
        encoding="utf-8")
    dl.save("personal:jobs", dl.Delivery(email=("a@example.com",)))
    names = [item.name for item in d.discover(None) if isinstance(item, d.AgentDef)]
    assert names == ["deliveries"]
    assert dl.get("personal:jobs").email == ("a@example.com",)
