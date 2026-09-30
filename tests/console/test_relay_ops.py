import subprocess
from pathlib import Path
import pytest
from whyline.console import adapters, relay_ops


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def test_save_pasted_plan_commits_plan_md(repo):
    path = relay_ops.save_pasted_plan(repo, "- [ ] T-1: build it")
    assert path == repo / "plan.md"
    assert path.read_text() == "- [ ] T-1: build it\n"
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["plan.md"]
    assert not (repo / ".whyline" / "relay" / "pasted-plan.md").exists()


def test_save_pasted_plan_rejects_prose(repo):
    with pytest.raises(ValueError, match="no tasks"):
        relay_ops.save_pasted_plan(repo, "just words")


def test_save_pasted_plan_asks_before_replacing(repo):
    (repo / "plan.md").write_text("- [ ] OLD-1: old\n")
    with pytest.raises(relay_ops.plan_exists_error()):
        relay_ops.save_pasted_plan(repo, "- [ ] T-1: new\n")
    relay_ops.save_pasted_plan(repo, "- [ ] T-1: new\n", replace=True)
    assert (repo / "plan.md").read_text() == "- [ ] T-1: new\n"


def test_missing_references_resolves_home_relative_and_spaces(
    repo, monkeypatch, tmp_path_factory
):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # what expanduser reads on Windows
    (home / "PRD one.md").write_text("x")
    (repo / "docs").mkdir()
    (repo / "docs" / "brief.md").write_text("x")
    absolute = repo / "README.md"
    refs = ["~/PRD one.md", "docs/brief.md", str(absolute), "docs/nope.md"]
    assert relay_ops.missing_references(repo, refs) == ["docs/nope.md"]


def test_draft_description_lists_the_references():
    text = relay_ops.draft_description("Build the PRD", ["PRD.md", "docs/b.md"])
    assert text == (
        "Build the PRD\n\nRead these reference documents before planning:\n"
        "- PRD.md\n- docs/b.md"
    )
    assert relay_ops.draft_description("Build it", []) == "Build it"


def test_brainstorm_docs_lists_stems(repo):
    folder = repo / "docs" / "brainstorm"
    folder.mkdir(parents=True)
    (folder / "b-topic.md").write_text("x")
    (folder / "a-topic.md").write_text("x")
    (folder / "notes.txt").write_text("x")
    assert relay_ops.brainstorm_docs(repo) == ["a-topic", "b-topic"]
    assert relay_ops.brainstorm_docs(repo / "missing") == []


def test_current_roles_defaults_then_reads_config(repo):
    assert relay_ops.current_roles(repo) == {
        "implementer": "codex",
        "tester": "claude",
        "reviewer": "claude",
        "backup": [],
    }
    relay_ops.save_roles(repo, "claude", "codex", "codex", ["claude"])
    assert relay_ops.current_roles(repo) == {
        "implementer": "claude",
        "tester": "codex",
        "reviewer": "codex",
        "backup": ["claude"],
    }


def test_relay_agents_are_the_relay_builtins():
    from whyline_relay import adapters as relay_adapters

    assert relay_ops.relay_agents() == sorted(relay_adapters.BUILTIN)


def test_run_checks_returns_plain_lines(repo, monkeypatch):
    from whyline_relay import preflight

    monkeypatch.setattr(
        preflight,
        "run",
        lambda root: [
            preflight.Check("ok", "fine"),
            preflight.Check("FAIL", "bad", "fix it"),
        ],
    )
    assert relay_ops.run_checks(repo) == [
        relay_ops.CheckLine("ok", "fine", None),
        relay_ops.CheckLine("FAIL", "bad", "fix it"),
    ]


def test_live_run_names_the_task_and_agent(repo, monkeypatch):
    from whyline_relay import running

    monkeypatch.setattr(
        running,
        "live",
        lambda root: running.Running(
            agent="codex",
            task="T3",
            round=1,
            started="2026-09-30T10:00:00",
            pid=1,
            role="implementer",
        ),
    )
    assert relay_ops.live_run(repo) == "T3, codex"
    monkeypatch.setattr(running, "live", lambda root: None)
    assert relay_ops.live_run(repo) is None


def test_classify_relay_output_keeps_run_relay_oneshot_behaviour(tmp_path):
    assert (
        adapters.classify_relay_output(tmp_path, "Plan complete: 2 task(s)\n", 0).kind
        == "output"
    )
    assert adapters.classify_relay_output(tmp_path, "boom\n", 2).kind == "error"
