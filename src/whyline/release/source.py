"""Where a release comes from: the branch being released and how it sits against main."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whyline.console import relay_ops
from whyline.release.config import ReleaseConfig
from whyline.release.ready import _git, _short

Run = Callable[..., object]
Fetch = Callable[[Path, str], None]


@dataclass(frozen=True)
class Source:
    branch: str
    on_release_branch: bool
    ahead: int
    behind: int
    finished_plans: tuple[Path, ...] = ()

    def line(self) -> str:
        text = f"Releasing {self.branch}"
        if self.on_release_branch:
            return text
        text += f" · {self.ahead} commits"
        if self.behind:
            text += f" · main has {self.behind} commits this branch doesn't"
        return text


def _out(root: Path, run: Run, *args: str) -> str:
    res = _git(run, root, *args)
    if getattr(res, "returncode", 1) != 0:
        raise RuntimeError(_short(getattr(res, "stderr", "")) or f"git {args[0]} failed")
    return (getattr(res, "stdout", "") or "").strip()


def _finished_plans(root: Path) -> tuple[Path, ...]:
    plans_dir = (root / relay_ops.PLANS_DIR).resolve()
    return tuple(
        info.path
        for info in relay_ops.list_plans(root)
        if info.total > 0
        and info.done == info.total
        and info.path.resolve().parent == plans_dir
    )


def _relay_running(root: Path) -> bool:
    from whyline_relay import running

    # errors propagate: if relay state cannot be read, the merge must not proceed
    return running.live(root) is not None


def confirmation(src: Source, root: Path) -> str:
    text = src.line()
    if src.finished_plans:
        names = ", ".join(p.name for p in src.finished_plans)
        text += f"\nMoves to {relay_ops.PLANS_DIR}/done: {names}"
    return text


def bring_in_main(
    root: Path,
    cfg: ReleaseConfig,
    version: str,
    *,
    run: Run,
    fetch: Fetch,
    relay_running: Callable[[Path], bool] = _relay_running,
) -> str:
    """Merge main into the release branch and archive finished plans; returns a summary."""
    from whyline.release.github import StepError

    root = Path(root)
    if relay_running(root):
        raise StepError("A relay is running here; release when it finishes")
    dirty = [line[3:] for line in _out(root, run, "status", "--porcelain").splitlines() if line]
    if dirty:
        raise StepError("Commit or stash these first: " + ", ".join(dirty))
    src = source(root, cfg, run=run, fetch=fetch)
    parts: list[str] = []
    if src.behind > 0:
        res = _git(run, root, "merge", "--no-ff", f"origin/{cfg.branch}", "-m",
                   f"merge: bring {cfg.branch} into {src.branch} for v{version}")
        if getattr(res, "returncode", 1) != 0:
            files = _git(run, root, "diff", "--name-only", "--diff-filter=U")
            names = (getattr(files, "stdout", "") or "").split()
            _git(run, root, "merge", "--abort")
            raise StepError(
                f"Merge {cfg.branch} into {src.branch} yourself (or ask an agent), "
                f"then resume the release. Conflicts: {', '.join(names)}")
        parts.append(f"merged {src.behind} commits from {cfg.branch}")
    moved: list[str] = []
    done_dir = root / relay_ops.PLANS_DIR / "done"
    for plan in _finished_plans(root):
        done_dir.mkdir(parents=True, exist_ok=True)
        sources = [plan]
        tests = plan.with_name(plan.name.removesuffix(".plan.md") + ".tests.md")
        if tests.is_file():
            sources.append(tests)
        for path in sources:
            _out(root, run, "mv", str(path), str(done_dir / path.name))
        moved.append(plan.name)
    if moved:
        _out(root, run, "commit", "-m", "chore: move finished plans to plans/done")
        parts.append("moved to plans/done: " + ", ".join(moved))
    return "; ".join(parts) or f"{cfg.branch} already merged"


def source(root: Path, cfg: ReleaseConfig, *, run: Run, fetch: Fetch) -> Source:
    root = Path(root)
    branch = _out(root, run, "rev-parse", "--abbrev-ref", "HEAD")
    fetch(root, cfg.branch)
    counts = _out(root, run, "rev-list", "--left-right", "--count", f"HEAD...origin/{cfg.branch}")
    try:
        ahead, behind = (int(n) for n in counts.split())
    except ValueError as exc:
        raise RuntimeError(f"unexpected git rev-list output: {counts!r}") from exc
    return Source(branch, branch == cfg.branch, ahead, behind, _finished_plans(root))
