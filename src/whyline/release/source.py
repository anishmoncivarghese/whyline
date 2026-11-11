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
