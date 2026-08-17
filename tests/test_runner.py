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


def test_build_argv_rejects_an_unknown_agent():
    with pytest.raises(runner.UnknownAgent):
        runner.build_argv("gemini", "task", "ctx")


def test_build_argv_never_adds_permission_bypass_flags():
    argv = runner.build_argv("claude", "task", "ctx")
    joined = " ".join(argv)
    for forbidden in (
        "--dangerously-skip-permissions",
        "--yolo",
        "--dangerously-bypass-hook-trust",
        "--approval-mode",
    ):
        assert forbidden not in joined


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
    assert calls == [
        ("claude", ["claude", runner.build_argv("claude", "task", "ctx")[-1]])
    ]


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
