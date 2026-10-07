import json

import pytest

from whyline.agents import capabilities as c

CODEX = ["codex", "exec", "-s", "workspace-write", "--color", "never"]
CLAUDE = ["claude", "-p", "--permission-mode", "acceptEdits", "--output-format", "json",
          "--settings", ".whyline/relay/claude-settings.json"]
GROK = ["grok", "--output-format", "json", "--permission-mode", "dontAsk",
        "--deny", "Bash(git push:*)", "--allow", "Edit", "--allow", "Bash(git add:*)",
        "--allow", "Bash(git commit:*)", "--allow", "Bash(cat:*)", "--allow", "Bash(mkdir:*)",
        "--allow", "Bash(touch:*)", "-p"]


def test_codex_read_only():
    assert c.read_only_command("codex", CODEX) == ["codex", "exec", "-s", "read-only", "--color", "never"]


def test_claude_read_only():
    out = c.read_only_command("claude", CLAUDE)
    assert out[out.index("--permission-mode") + 1] == "plan"


# Spellings that grant a tool call. --deny Edit/Write does not cover Bash,
# and the always-approve aliases auto-approve whatever is not denied.
_GRANT_NAMES = (
    "--allow", "--allowedTools", "--tools",
    "--always-approve", "--yolo", "--dangerously-skip-permissions",
)


def _grants(out):
    """Every permission grant left in a grok command, in any spelling."""
    return [a for a in out if a.split("=", 1)[0] in _GRANT_NAMES]


def _only_as_deny(out, name):
    """name appears only as the value of a --deny pair, never as a leftover grant."""
    return all(out[i - 1] == "--deny" for i, token in enumerate(out) if token == name)


def test_grok_read_only_drops_write_allows_and_denies_edit():
    out = c.read_only_command("grok", GROK)
    assert _grants(out) == []
    assert ("--deny", "Edit") in zip(out, out[1:])
    for writer in ("Bash(git add:*)", "Bash(git commit:*)", "Bash(mkdir:*)", "Bash(touch:*)"):
        assert writer not in out
    # Grok runs cat, ls, grep and git log without a rule (its built-in
    # read-only list), so no allow survives, not even Bash(cat:*).
    assert _only_as_deny(out, "Edit") and _only_as_deny(out, "Write")
    assert out[-1] == "-p"


def test_a_cli_without_a_verified_setting_cannot_run():
    assert c.read_only_command("unknown", ["x"]) is None
    assert not c.can_run("unknown")


def test_codex_without_its_sandbox_flag_is_refused():
    assert c.read_only_command("codex", ["codex", "exec"]) is None


def test_codex_trailing_sandbox_flag_fails_closed():
    assert c.read_only_command("codex", ["codex", "exec", "-s"]) is None


def test_claude_trailing_permission_mode_is_completed_to_plan():
    assert c.read_only_command("claude", ["claude", "--permission-mode"]) == [
        "claude", "--permission-mode", "plan"]


def test_codex_rewrites_every_sandbox_value():
    command = ["codex", "exec", "-s", "workspace-write", "-s", "danger-full-access"]
    assert c.read_only_command("codex", command) == [
        "codex", "exec", "-s", "read-only", "-s", "read-only"]
    assert c.read_only_command(
        "codex", ["codex", "exec", "-s", "read-only", "--sandbox", "danger-full-access"]
    ) == ["codex", "exec", "-s", "read-only", "--sandbox", "read-only"]
    assert c.read_only_command("codex", ["codex", "exec", "--sandbox=workspace-write"]) == [
        "codex", "exec", "--sandbox=read-only"]
    assert c.read_only_command("codex", ["codex", "exec", "-s=danger-full-access"]) == [
        "codex", "exec", "-s=read-only"]


def test_codex_sandbox_flag_does_not_consume_the_next_option():
    assert c.read_only_command("codex", ["codex", "exec", "-s", "--color", "never"]) is None
    assert c.read_only_command("codex", ["codex", "exec", "-s", "-s", "danger-full-access"]) is None
    assert c.read_only_command("codex", ["codex", "exec", "--sandbox", "--color"]) is None
    assert c.read_only_command(
        "codex", ["codex", "exec", "-s", "workspace-write", "-s"]
    ) is None


def test_codex_drops_extra_writable_directories():
    assert c.read_only_command(
        "codex", ["codex", "exec", "-s", "workspace-write", "--add-dir", "/tmp", "--color", "never"]
    ) == ["codex", "exec", "-s", "read-only", "--color", "never"]
    assert c.read_only_command(
        "codex", ["codex", "exec", "-s", "read-only", "--add-dir=/tmp"]
    ) == ["codex", "exec", "-s", "read-only"]
    assert c.read_only_command(
        "codex", ["codex", "exec", "-s", "read-only", "--add-dir", "--color"]
    ) is None


def test_codex_flags_that_cancel_the_sandbox_are_refused():
    assert c.read_only_command(
        "codex",
        ["codex", "exec", "-s", "read-only", "--dangerously-bypass-approvals-and-sandbox"],
    ) is None
    assert c.read_only_command(
        "codex", ["codex", "exec", "-s", "read-only", "--approve-for-me"]
    ) is None


def test_claude_rewrites_every_permission_mode():
    command = [
        "claude", "-p", "--permission-mode", "plan", "--output-format", "json",
        "--permission-mode", "acceptEdits",
    ]
    assert c.read_only_command("claude", command) == [
        "claude", "-p", "--permission-mode", "plan", "--output-format", "json",
        "--permission-mode", "plan",
    ]
    assert c.read_only_command("claude", ["claude", "--permission-mode=acceptEdits"]) == [
        "claude", "--permission-mode=plan"]


def test_claude_permission_mode_does_not_consume_the_next_option():
    assert c.read_only_command(
        "claude", ["claude", "--permission-mode", "--output-format", "json"]
    ) == ["claude", "--permission-mode", "plan", "--output-format", "json"]
    assert c.read_only_command(
        "claude", ["claude", "--permission-mode", "--permission-mode", "acceptEdits"]
    ) == ["claude", "--permission-mode", "plan", "--permission-mode", "plan"]


def test_claude_skip_permissions_is_removed_and_plan_mode_remains():
    assert c.read_only_command(
        "claude", ["claude", "--dangerously-skip-permissions", "-p"]
    ) == ["claude", "--permission-mode", "plan", "-p"]
    assert c.read_only_command(
        "claude",
        ["claude", "--permission-mode", "acceptEdits", "--dangerously-skip-permissions"],
    ) == ["claude", "--permission-mode", "plan"]


def test_denials():
    assert c.denied("claude", json.dumps({"result": "ok", "permission_denials": [{"tool_name": "Write"}]}))
    assert not c.denied("claude", json.dumps({"result": "ok", "permission_denials": []}))
    assert c.denied("grok", json.dumps({"text": "", "stopReason": "cancelled"}))
    assert not c.denied("grok", json.dumps({"text": "ok", "stopReason": "end_turn"}))


def test_unattended_list():
    assert all(c.can_run_unattended(x) for x in ("claude", "codex", "grok"))
    assert not c.can_run("antigravity")  # spike: --mode plan still wrote files


# Every way around a blocklist found while reviewing AG-4. The read-only grok
# command keeps no grant at all, so none of them can survive.
GROK_ESCAPES = [
    ["--allow=Edit"],                                  # attached form
    ["--allow=Write"],
    ["--allow=Bash(mkdir:*)"],
    ["--allow=Edit,Write"],
    ["--allow", "Edit,Write"],
    ["--allow", "Bash(python3:*)"],                    # writes through a shell
    ["--allow", "Bash(uv run:*)"],
    ["--allow", "Bash(uv:*)"],
    ["--allow", "Bash(*)"],
    ["--allowedTools", "Edit"],                        # Claude spelling of --tools
    ["--allowedTools=Write"],
    ["--tools", "Edit"],                               # canonical flag
    ["--tools=Edit,Write"],
    ["--tools=Bash(mkdir:*)"],
    ["--always-approve"],
    ["--always-approve=true"],
    ["--yolo"],                                        # alias of --always-approve
    ["--yolo=true"],
    ["--dangerously-skip-permissions"],                # Claude alias of --always-approve
    ["--dangerously-skip-permissions=true"],
]


@pytest.mark.parametrize("escape", GROK_ESCAPES, ids=lambda e: " ".join(e))
def test_grok_read_only_keeps_no_permission_grant(escape):
    out = c.read_only_command("grok", ["grok", "--output-format", "json", *escape, "-p"])
    assert _grants(out) == []
    denied = {out[i + 1] for i, a in enumerate(out[:-1]) if a == "--deny"}
    kept = [a for a in out if a not in denied]
    assert not any(token in kept for token in escape if not token.startswith("-"))
    assert _only_as_deny(out, "Edit") and _only_as_deny(out, "Write")
    assert out[-1] == "-p"


@pytest.mark.parametrize("mode", [
    "bypassPermissions", "always-approve", "acceptEdits", "auto", "default", "plan",
])
def test_grok_permission_mode_is_forced_to_dont_ask(mode):
    for command in (
        ["grok", "--permission-mode", mode, "-p"],
        ["grok", f"--permission-mode={mode}", "-p"],
    ):
        out = c.read_only_command("grok", command)
        modes = [out[i + 1] for i, a in enumerate(out) if a == "--permission-mode"]
        modes += [a.split("=", 1)[1] for a in out if a.startswith("--permission-mode=")]
        assert modes == ["dontAsk"]


def test_grok_without_a_permission_mode_gets_dont_ask():
    out = c.read_only_command("grok", ["grok", "--output-format", "json", "-p"])
    assert ("--permission-mode", "dontAsk") in zip(out, out[1:])
    assert out[-1] == "-p"


def test_grok_keeps_deny_rules_and_other_options():
    out = c.read_only_command("grok", GROK)
    assert ("--deny", "Bash(git push:*)") in zip(out, out[1:])
    assert ("--output-format", "json") in zip(out, out[1:])
