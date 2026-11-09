"""The stages a document set runs through, and the Stages line that shows them."""

from __future__ import annotations

from dataclasses import dataclass

from whyline.sdlc.docset import DocSet, PrdMode, Size, Status

STARTS = ("description", "brainstorm", "prd", "spec")

_LABELS = {
    "brainstorm": "Brainstorm",
    "home": "Project home",
    "prd": "PRD",
    "spec": "Spec",
    "design": "Design",
    "design-review": "Design review",
    "plan": "Plan + test plan",
    "implement": "Implement",
    "test": "Test",
    "review": "Review",
    "release": "Release",
    "build-record": "Build record",
    "done": "Done",
}
_BUILD = ("implement", "test", "review", "release")
# The stages that come before the one a start point supplies.
_BEFORE = {
    "description": (),
    "brainstorm": ("brainstorm",),
    "prd": ("brainstorm",),
    "spec": ("brainstorm", "prd"),
}
_START_REASON = {
    "brainstorm": "starting from a brainstorm",
    "prd": "starting from a PRD",
    "spec": "starting from a spec",
}
_DRAFTED = ("brainstorm", "prd", "spec", "design", "plan")
_REVIEWED = ("prd", "spec", "design", "plan")
_EXECUTION_ROLE = {
    "implement": "implementer",
    "test": "tester",
    "review": "code_reviewer",
    "release": "release",
}


@dataclass(frozen=True)
class Stage:
    kind: str
    label: str
    skipped: bool = False
    reason: str = ""


def plan_stages(
    size: Size | str,
    start: str,
    *,
    brainstorm_first: bool,
    build: bool,
    prd_mode: PrdMode | str = PrdMode.NEW,
) -> list[Stage]:
    """Every stage for a size and start point, skipped ones included with their reason."""
    size = Size(size)
    prd = PrdMode(prd_mode)
    if start not in STARTS:
        raise ValueError(f"Unknown start {start!r}: expected one of {', '.join(STARTS)}.")
    before = _BEFORE[start]

    kinds: list[str] = []
    if size is Size.LARGE or brainstorm_first or start == "brainstorm":
        kinds.append("brainstorm")
    kinds.append("home")
    kinds.append("prd")
    kinds.append("design" if size is Size.LARGE else "spec")
    if size is Size.LARGE:
        kinds.append("design-review")
    kinds.append("plan")
    if build:
        kinds += [*_BUILD, "build-record", "done"]

    stages: list[Stage] = []
    for kind in kinds:
        label = _LABELS[kind]
        reason = ""
        if kind == "home" and prd is not PrdMode.NEW:
            reason = "existing project"
        if kind == "prd":
            if prd is PrdMode.UPDATE:
                label = "PRD update"
            if size is Size.SMALL:
                reason = "Small has no PRD"
            elif prd is PrdMode.NONE:
                reason = "no PRD change"
        if not reason and kind in before:
            reason = _START_REASON[start]
        stages.append(Stage(kind, label, bool(reason), reason))
    return stages


def _approved(docset: DocSet, kind: str) -> bool:
    if kind == "home":
        # Not a document: choose_home records the user's choice on the set.
        return "home" in (getattr(docset, "skipped", None) or {})
    if kind == "design-review":
        # A separate architect review of the approved design, with its own marker.
        return bool(getattr(docset, "design_reviewed", False))
    if kind in _BUILD:
        built = docset.document("build-record")
        return bool(docset.build_base) or (
            built is not None and built["status"] == Status.APPROVED.value
        )
    if kind == "done":
        return getattr(docset, "state", None) in ("released", "built")
    doc = docset.document(kind)
    return doc is not None and doc["status"] == Status.APPROVED.value


def next_stage(docset: DocSet) -> Stage | None:
    """The first stage that isn't skipped and isn't approved."""
    stages = plan_stages(
        docset.size,
        "description",
        brainstorm_first=docset.document("brainstorm") is not None,
        build=docset.build,
        prd_mode=docset.prd_mode,
    )
    for stage in stages:
        document_kind = "design" if stage.kind == "design-review" else stage.kind
        has_document = document_kind in _DRAFTED + ("build-record",)
        if stage.skipped or (has_document and docset.document(document_kind) is None):
            continue
        if not _approved(docset, stage.kind):
            return stage
    return None


def _agents(stage: Stage, roles: dict) -> str:
    kind = stage.kind
    parts: list[str] = []
    if kind == "home":
        parts.append("you choose")
    elif kind == "design-review":
        parts.append(str(roles.get("architect_reviewer") or ""))
    elif kind in _DRAFTED:
        parts.append(str(roles.get("writer") or ""))
        if kind in _REVIEWED:
            reviewer = roles.get(f"{kind}_reviewer") or roles.get("reviewer")
            if reviewer:
                parts.append(f"reviewed by {reviewer}")
        if kind == "plan" and roles.get("test_planner"):
            parts.append(f"tests by {roles['test_planner']}")
    elif kind in _EXECUTION_ROLE:
        parts.append(str(roles.get(_EXECUTION_ROLE[kind]) or ""))
    return ", ".join(part for part in parts if part)


def stages_line(stages: list[Stage], roles: dict) -> str:
    """`PRD (claude, reviewed by codex) → Spec (claude) → …`; skipped stages read `Label — (reason)`."""
    pieces: list[str] = []
    for stage in stages:
        if stage.skipped:
            pieces.append(f"{stage.label} — ({stage.reason})" if stage.reason else f"{stage.label} —")
            continue
        agents = _agents(stage, roles)
        pieces.append(f"{stage.label} ({agents})" if agents else stage.label)
    return " → ".join(pieces)
