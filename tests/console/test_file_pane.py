from __future__ import annotations

import json
from pathlib import Path

import pytest

from whyline.console.file_pane import RepoTree, active_plan_file


def _write_config(root: Path, plan: str) -> None:
    dest = root / ".whyline" / "relay" / "config.toml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"plan = {json.dumps(plan)}\n", encoding="utf-8")


def _write_plan(root: Path, rel: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# plan\n", encoding="utf-8")
    return path


def _save_run(root: Path, plan: str) -> None:
    from whyline_relay import state

    state.save(
        root,
        state.RelayState(
            plan=plan,
            branch="relay/run",
            task_id="PANE-1",
            round=1,
            base_commit="",
            paused_reason="",
            log_path="",
        ),
    )


def test_run_plan_wins(tmp_path: Path) -> None:
    run = _write_plan(tmp_path, "plans/run.plan.md")
    _write_plan(tmp_path, "plans/configured.plan.md")
    _write_config(tmp_path, "plans/configured.plan.md")
    _save_run(tmp_path, "plans/run.plan.md")
    assert active_plan_file(tmp_path) == run


def test_missing_run_plan_does_not_fall_through(tmp_path: Path) -> None:
    _write_plan(tmp_path, "plans/configured.plan.md")
    _write_config(tmp_path, "plans/configured.plan.md")
    _save_run(tmp_path, "plans/missing.plan.md")
    assert active_plan_file(tmp_path) is None


def test_configured_plan_when_idle(tmp_path: Path) -> None:
    configured = _write_plan(tmp_path, "plans/configured.plan.md")
    _write_config(tmp_path, "plans/configured.plan.md")
    assert active_plan_file(tmp_path) == configured


def test_plan_outside_repo_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.plan.md"
    outside.write_text("# outside\n", encoding="utf-8")
    _write_config(tmp_path, str(outside))
    assert active_plan_file(tmp_path) is None

    link = tmp_path / "plans" / "link.plan.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    _write_config(tmp_path, "plans/link.plan.md")
    assert active_plan_file(tmp_path) is None


def test_no_plan(tmp_path: Path) -> None:
    assert active_plan_file(tmp_path) is None


def _repo_layout(root: Path) -> None:
    git = root / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    whyline = root / ".whyline"
    whyline.mkdir()
    (whyline / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    src = root / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hi')\n", encoding="utf-8")
    outside = root.parent / f"{root.name}-outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (root / "escape").symlink_to(outside)


def _child_names(node) -> set[str]:
    return {child.label.plain for child in node.children}


def _child(node, name: str):
    for child in node.children:
        if child.label.plain == name:
            return child
    raise AssertionError(f"no child named {name!r} in {_child_names(node)}")


@pytest.mark.asyncio
async def test_repo_tree_hides_git_keeps_ignored_and_rejects_outside_symlink(
    tmp_path: Path,
) -> None:
    pytest.importorskip("textual")
    from textual.app import App, ComposeResult
    from textual.widgets import DirectoryTree

    _repo_layout(tmp_path)
    ignored = tmp_path / "ignored.txt"
    selected: list[Path] = []

    class _TreeApp(App):
        def compose(self) -> ComposeResult:
            yield RepoTree(tmp_path)

        def on_directory_tree_file_selected(
            self, event: DirectoryTree.FileSelected
        ) -> None:
            selected.append(event.path)

    app = _TreeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        tree = app.query_one(RepoTree)
        await tree.reload()
        await pilot.pause()

        names = _child_names(tree.root)
        assert "src" in names
        assert "ignored.txt" in names
        assert ".whyline" in names
        assert ".git" not in names
        assert "escape" not in names

        src = _child(tree.root, "src")
        assert not src.is_expanded
        src.expand()
        await tree.reload_node(src)
        await pilot.pause()
        assert "main.py" in _child_names(src)

        tree.select_node(_child(tree.root, "ignored.txt"))
        await pilot.pause()
        assert selected
        assert selected[-1].resolve() == ignored.resolve()
        assert isinstance(selected[-1], Path)
