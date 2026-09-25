import pytest

from whyline import runner


def test_build_argv_puts_the_brief_before_the_task():
    argv = runner.build_argv(
        "claude", "fix the cache", "<whyline-context>ctx</whyline-context>"
    )
    assert argv[0] == "claude"
    prompt = argv[-1]
    assert prompt.index("ctx") < prompt.index("fix the cache")


def test_build_argv_supports_codex():
    assert runner.build_argv("codex", "task", "ctx")[0] == "codex"


def test_build_argv_supports_antigravity():
    # "agy" is the real binary; Gemini CLI itself is dead (its free personal
    # tier was withdrawn), and Antigravity is the account's actual working path.
    assert runner.build_argv("antigravity", "task", "ctx")[0] == "agy"


def test_build_argv_gives_antigravity_the_interactive_prompt_flag():
    # `agy` needs -i/--prompt-interactive to seed a session with a prompt and
    # then hand over the terminal -- the same shape a bare `claude "<prompt>"`
    # or `codex "<prompt>"` already gets for free. Verified against `agy --help`.
    assert runner.build_argv("antigravity", "task", "ctx") == ["agy", "-i", "ctx\n\ntask"]


def test_build_argv_rejects_an_unknown_agent():
    with pytest.raises(runner.UnknownAgent):
        runner.build_argv("gemini", "task", "ctx")


def test_build_argv_never_adds_permission_bypass_flags():
    for agent in ("claude", "codex", "antigravity", "grok"):
        argv = runner.build_argv(agent, "task", "ctx")
        joined = " ".join(argv)
        for forbidden in (
            "--dangerously-skip-permissions",
            "--yolo",
            "--dangerously-bypass-hook-trust",
            "--approval-mode",
            "--permission-mode",
        ):
            assert forbidden not in joined, f"{agent}: {joined}"


def test_build_argv_without_a_brief_passes_the_task_alone():
    assert runner.build_argv("claude", "just the task", "") == ["claude", "just the task"]


def test_launch_execs_the_agent_binary():
    calls = []

    def fake_exec(binary, argv):
        calls.append((binary, argv))

    runner.launch(
        "claude",
        "task",
        "ctx",
        which=lambda name: f"/usr/bin/{name}",
        exec_fn=fake_exec,
    )
    # Assert on the literal expected argv, not on build_argv's own output —
    # deriving the expectation from the function under test made half of this
    # assertion tautological (flagged 2026-08-17).
    assert calls == [("claude", ["claude", "ctx\n\ntask"])]


def test_launch_execs_antigravity_with_the_interactive_flag():
    calls = []

    def fake_exec(binary, argv):
        calls.append((binary, argv))

    runner.launch(
        "antigravity",
        "task",
        "ctx",
        which=lambda name: f"/usr/bin/{name}",
        exec_fn=fake_exec,
    )
    assert calls == [("agy", ["agy", "-i", "ctx\n\ntask"])]


def test_launch_raises_when_the_binary_is_absent():
    with pytest.raises(runner.AgentMissing):
        runner.launch("codex", "task", "ctx", which=lambda name: None, exec_fn=None)


def test_launch_does_not_exec_when_the_binary_is_absent():
    """The agent must never be invoked if we could not find it — an exec attempt
    on a missing binary would surface as a confusing OSError instead of our
    clear message."""
    calls = []

    def fake_exec(binary, argv):  # pragma: no cover - must not run
        calls.append(binary)

    with pytest.raises(runner.AgentMissing):
        runner.launch("codex", "task", "ctx", which=lambda name: None, exec_fn=fake_exec)
    assert calls == []


def test_launch_rejects_an_unknown_agent_before_touching_the_filesystem():
    def explode(name):  # pragma: no cover - must not run
        raise AssertionError("which() must not be consulted for an unknown agent")

    with pytest.raises(runner.UnknownAgent):
        runner.launch("gemini", "task", "ctx", which=explode, exec_fn=None)


def test_environment_is_never_inspected_by_the_runner():
    """Constraint: whyline never reads credentials. The runner must not touch
    os.environ at all — exec inherits it untouched."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(runner))
    for node in ast.walk(tree):
        # os.environ / os.getenv appear as attribute access on `os`
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            raise AssertionError(f"runner touches os.{node.attr}")
        if isinstance(node, ast.Name) and node.id in ("environ", "getenv"):
            raise AssertionError(f"runner references {node.id}")


def test_patching_the_module_attribute_actually_takes_effect(monkeypatch):
    """Regression for 2026-08-17: `which=shutil.which` as a default argument
    bound the function at import time, so patching runner.shutil.which had no
    effect and launch exec'd the real agent — replacing the pytest process
    mid-suite and spending real vendor quota. Resolution must happen at call
    time."""
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    with pytest.raises(runner.AgentMissing):
        runner.launch("claude", "task", "ctx")


def test_launch_never_execs_a_real_agent_when_which_is_patched(monkeypatch):
    """The dangerous half of the same bug: prove no exec is attempted."""
    execs = []
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.setattr(runner.os, "execvp", lambda b, a: execs.append(b))
    with pytest.raises(runner.AgentMissing):
        runner.launch("codex", "task", "ctx")
    assert execs == []


def test_the_indirection_resolves_at_call_time_not_at_import(monkeypatch):
    """2026-08-18. A Minor cleanup cached `_which = shutil.which` at import,
    which recreated the late-binding defect: the cached reference ignored the
    patch, launch exec'd the real agent, and a pytest run hung because the
    process had been replaced by Claude Code. Both patch points must work."""
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    with pytest.raises(runner.AgentMissing):
        runner.launch("claude", "task", "ctx")


def test_patching_the_indirection_directly_also_works(monkeypatch):
    monkeypatch.setattr(runner, "_which", lambda name: None)
    with pytest.raises(runner.AgentMissing):
        runner.launch("codex", "task", "ctx")


def test_no_code_path_can_reach_the_real_execvp_during_tests(monkeypatch):
    """Belt and braces: poison os.execvp and assert every launch path raises
    before reaching it, with both agents genuinely on PATH."""

    def poisoned(binary, argv):  # pragma: no cover - must never run
        raise AssertionError(f"real execvp reached with {binary}")

    monkeypatch.setattr(runner.os, "execvp", poisoned)
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    for agent in ("claude", "codex", "antigravity", "grok"):
        with pytest.raises(runner.AgentMissing):
            runner.launch(agent, "task", "ctx")
    with pytest.raises(runner.UnknownAgent):
        runner.launch("gemini", "task", "ctx")


def test_build_argv_appends_the_model_flag_when_given():
    argv = runner.build_argv("codex", "task", "ctx", model="gpt-5-codex")
    assert argv == ["codex", "--model", "gpt-5-codex", "ctx\n\ntask"]


def test_build_argv_with_no_model_is_unchanged():
    assert runner.build_argv("codex", "task", "ctx") == ["codex", "ctx\n\ntask"]


def test_build_argv_appends_the_model_flag_for_antigravity():
    argv = runner.build_argv("antigravity", "task", "ctx", model="gemini-3-pro")
    assert argv == ["agy", "-i", "--model", "gemini-3-pro", "ctx\n\ntask"]


def test_launch_passes_the_model_through_to_build_argv():
    calls = []
    runner.launch(
        "codex",
        "task",
        "ctx",
        which=lambda name: f"/usr/bin/{name}",
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
        model="gpt-5-codex",
    )
    assert calls == [("codex", ["codex", "--model", "gpt-5-codex", "ctx\n\ntask"])]


def test_build_argv_supports_grok():
    assert runner.build_argv("grok", "task", "ctx")[0] == "grok"


def test_build_argv_gives_grok_the_prompt_directly_no_special_flag():
    # Unlike Antigravity's -i, grok's own --help documents that a bare
    # `grok "<prompt>"` already starts an interactive session with it.
    assert runner.build_argv("grok", "task", "ctx") == ["grok", "ctx\n\ntask"]


def test_build_argv_appends_the_model_flag_for_grok():
    argv = runner.build_argv("grok", "task", "ctx", model="grok-4.6")
    assert argv == ["grok", "--model", "grok-4.6", "ctx\n\ntask"]


def test_launch_execs_grok_directly():
    calls = []
    runner.launch(
        "grok",
        "task",
        "ctx",
        which=lambda name: f"/usr/bin/{name}",
        exec_fn=lambda binary, argv: calls.append((binary, argv)),
    )
    assert calls == [("grok", ["grok", "ctx\n\ntask"])]
