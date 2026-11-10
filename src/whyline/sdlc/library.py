"""The library: document sets, the product PRD, and plans no set owns."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whyline import worktrees
from whyline.console.relay_ops import PLANS_DIR, _marker_fields
from whyline.sdlc import docset
from whyline.sdlc import product as prd

CHANGELOG_LINES = 10

_KIND_LABELS = {
    "brainstorm": "Brainstorm",
    "prd": "PRD",
    "spec": "Spec",
    "design": "Design",
    "plan": "Plan",
    "build-record": "Built",
}
_MARK_APPROVED = "✓"
_MARK_PENDING = "⏳"
_MARK_OUT_OF_DATE = "⚠"
_MARK_SUPERSEDED = "–"
_STATUS_MARKS = {
    docset.Status.APPROVED.value: _MARK_APPROVED,
    docset.Status.OUT_OF_DATE.value: _MARK_OUT_OF_DATE,
    docset.Status.SUPERSEDED.value: _MARK_SUPERSEDED,
}


@dataclass(frozen=True)
class SetSummary:
    slug: str
    name: str
    size: str
    created: str
    summary: str


@dataclass(frozen=True)
class ProductSummary:
    version: str
    approval: str
    changelog: list[str]


@dataclass(frozen=True)
class EarlierPlan:
    slug: str
    plan: Path
    test_plan: Path | None
    source: Path | None
    source_kind: str


def _summary(found: docset.DocSet) -> str:
    parts = [found.name, docset.Size(found.size).label]
    for doc in found.documents:
        mark = _STATUS_MARKS.get(doc["status"], _MARK_PENDING)
        label = _KIND_LABELS.get(doc["kind"], doc["kind"].replace("-", " ").capitalize())
        parts.append(f"{label} {mark}")
    if found.state == "released" and found.version:
        parts.append(f"Released v{found.version}")
    elif found.state in ("released", "built"):
        parts.append("Built")
    if found.pr_url:
        parts.append("PR open")
    return " · ".join(parts)


def location_line(docs: Path, root: Path | None = None) -> str:
    """`Documents: <docs checkout> (<default branch>)`; the branch is left out when it can't be read."""
    line = f"Documents: {docs}"
    try:
        branch = worktrees._default_branch(Path(root or docs)).removeprefix("origin/")
    except Exception:
        branch = ""
    return f"{line} ({branch})" if branch else line


def sets(root: Path) -> list[SetSummary]:
    """Every document set, newest first."""
    found = sorted(docset.all_sets(root), key=lambda s: (s.created, s.slug), reverse=True)
    return [SetSummary(s.slug, s.name, s.size, s.created, _summary(s)) for s in found]


def product(root: Path) -> ProductSummary | None:
    """The product PRD's version, approval and last changelog lines; None without a PRD."""
    now = prd.current(root)
    if now is None:
        return None
    meta = prd._meta(root)
    approval = ""
    if meta.get("approved_by"):
        approval = str(meta["approved_by"])
        if meta.get("approved_at"):
            approval += f" on {meta['approved_at']}"
    try:
        text = (prd._folder(root) / prd.CHANGELOG).read_text(encoding="utf-8")
    except OSError:
        text = ""
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    return ProductSummary(now.version, approval, lines[-CHANGELOG_LINES:])


def _sibling(folders: list[Path], name: str, first: Path) -> Path | None:
    for folder in [first, *folders]:
        if (folder / name).is_file():
            return folder / name
    return None


def _source(root: Path, plan: Path) -> tuple[Path | None, str]:
    try:
        first = plan.read_text(encoding="utf-8").split("\n", 1)[0]
    except (OSError, UnicodeDecodeError):
        return None, ""
    named = (_marker_fields(first) or {}).get("spec")
    if not named:
        return None, ""
    base = Path(root).resolve()
    path = (base / named).resolve()
    if base not in path.parents or not path.is_file():
        return None, ""
    shown = path.relative_to(base).as_posix().lower()
    return path, "brainstorm" if "brainstorm" in shown else "spec"


def earlier_plans(root: Path) -> list[EarlierPlan]:
    """Plans in plans/ and plans/done/ that no document set owns."""
    root = Path(root)
    owned = {s.slug for s in docset.all_sets(root)}
    folders = [root / PLANS_DIR, root / PLANS_DIR / "done"]
    found: list[EarlierPlan] = []
    seen: set[str] = set()
    for folder in folders:
        for path in sorted(folder.glob("*.plan.md")) if folder.is_dir() else []:
            slug = path.name.removesuffix(".plan.md")
            if slug in owned or slug in seen:
                continue
            seen.add(slug)
            tests = _sibling(folders, f"{slug}.tests.md", folder)
            source, kind = _source(root, path)
            found.append(EarlierPlan(slug, path, tests, source, kind))
    return found
