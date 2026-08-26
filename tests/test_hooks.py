import json

import pytest

from whyline import hooks


def test_install_creates_settings_when_absent(tmp_path):
    path = tmp_path / "settings.json"
    assert hooks.install(path, "whyline-hook") == "installed"
    data = json.loads(path.read_text())
    assert "PostToolUse" in data["hooks"]


def test_install_preserves_unrelated_keys_and_existing_hooks(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "PostToolUse": [
                        {"hooks": [{"type": "command", "command": "other-tool"}]}
                    ],
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "another"}]}
                    ],
                },
            }
        )
    )
    assert hooks.install(path, "whyline-hook") == "installed"
    data = json.loads(path.read_text())
    assert data["model"] == "opus"
    commands = [
        entry["command"]
        for group in data["hooks"]["PostToolUse"]
        for entry in group["hooks"]
    ]
    assert "other-tool" in commands
    assert "whyline-hook" in commands
    session_commands = [
        entry["command"]
        for group in data["hooks"]["SessionStart"]
        for entry in group["hooks"]
    ]
    assert "another" in session_commands


def test_install_is_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    hooks.install(path, "whyline-hook")
    assert hooks.install(path, "whyline-hook") == "already-present"
    data = json.loads(path.read_text())
    commands = [
        entry["command"]
        for group in data["hooks"]["PostToolUse"]
        for entry in group["hooks"]
    ]
    assert commands.count("whyline-hook") == 1


def test_install_refuses_unparseable_settings_without_modifying_them(tmp_path):
    path = tmp_path / "settings.json"
    original = "{ this is not json"
    path.write_text(original)
    with pytest.raises(hooks.SettingsUnreadable):
        hooks.install(path, "whyline-hook")
    assert path.read_text() == original


def test_install_refuses_non_object_settings_without_modifying_them(tmp_path):
    path = tmp_path / "settings.json"
    original = "[]\n"
    path.write_text(original)
    with pytest.raises(hooks.SettingsUnreadable):
        hooks.install(path, "whyline-hook")
    assert path.read_text() == original


def test_install_refuses_null_event_groups_without_modifying_them(tmp_path):
    path = tmp_path / "settings.json"
    original = '{"hooks":{"PostToolUse":null}}\n'
    path.write_text(original)
    with pytest.raises(hooks.SettingsUnreadable):
        hooks.install(path, "whyline-hook")
    assert path.read_text() == original


def test_codex_install_uses_an_explicit_agent_and_all_lifecycle_events(tmp_path):
    path = tmp_path / ".codex" / "hooks.json"

    assert hooks.install_codex(path) == "installed"

    data = json.loads(path.read_text())
    for event in hooks.EVENTS:
        commands = [
            entry["command"]
            for group in data["hooks"][event]
            for entry in group["hooks"]
        ]
        assert hooks.CODEX_HOOK_COMMAND in commands


def test_claude_and_codex_installers_are_idempotent_independently(tmp_path):
    claude = tmp_path / ".claude" / "settings.json"
    codex = tmp_path / ".codex" / "hooks.json"
    hooks.install_claude(claude)
    hooks.install_codex(codex)

    assert hooks.install_claude(claude) == "already-present"
    assert hooks.install_codex(codex) == "already-present"
