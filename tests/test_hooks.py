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
