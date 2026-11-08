"""The document set manifest: which documents a piece of work has, and their state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from whyline.console.relay_ops import PLANS_DIR, plan_slug
from whyline.state import atomic_write_json

SCHEMA = 1
SDLC_DIR = "docs/sdlc"
PRODUCT_PRD = "docs/product/prd.md"
MANIFEST = "docset.json"


class DocSetError(Exception):
    """A document set that is missing or unreadable, in words for the user."""


class Size(str, Enum):
    SMALL = "small"
    FEATURE = "feature"
    LARGE = "large"

    @property
    def label(self) -> str:
        return _SIZE_LABELS[self]


class Mode(str, Enum):
    HUMAN = "human"
    AUTO = "auto"

    @property
    def label(self) -> str:
        return _MODE_LABELS[self]


class Status(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    OUT_OF_DATE = "out_of_date"
    SUPERSEDED = "superseded"

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]


class PrdMode(str, Enum):
    NEW = "new"
    UPDATE = "update"
    NONE = "none"

    @property
    def label(self) -> str:
        return _PRD_LABELS[self]


_SIZE_LABELS = {Size.SMALL: "Small", Size.FEATURE: "Feature", Size.LARGE: "Large"}
_MODE_LABELS = {Mode.HUMAN: "Human in the loop", Mode.AUTO: "Automatic"}
_STATUS_LABELS = {
    Status.DRAFT: "Draft",
    Status.IN_REVIEW: "In review",
    Status.CHANGES_REQUESTED: "Changes requested",
    Status.APPROVED: "Approved",
    Status.OUT_OF_DATE: "Out of date",
    Status.SUPERSEDED: "Superseded",
}
_PRD_LABELS = {
    PrdMode.NEW: "New project: write the PRD",
    PrdMode.UPDATE: "Update the product PRD",
    PrdMode.NONE: "No PRD change",
}


def documents_for(size: Size | str, brainstorm_first: bool, prd_mode: PrdMode | str) -> list[str]:
    """Document kinds for a size. `plan` stands for the plan and its test plan."""
    size = Size(size)
    prd = PrdMode(prd_mode)
    if size is Size.SMALL:
        return ["spec", "plan", "build-record"]
    if size is Size.FEATURE:
        kinds = ["prd", "spec", "plan", "build-record"]
        if brainstorm_first:
            kinds.insert(0, "brainstorm")
    else:
        kinds = ["brainstorm", "prd", "design", "plan", "build-record"]
    if prd is PrdMode.NONE:
        kinds.remove("prd")
    return kinds


@dataclass
class DocSet:
    name: str
    slug: str
    size: str
    mode: str
    prd_mode: str
    prd_major: bool = False
    build: bool = True
    roles: dict = field(default_factory=dict)
    created: str = ""
    documents: list[dict] = field(default_factory=list)
    schema: int = SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "name": self.name,
            "slug": self.slug,
            "size": self.size,
            "mode": self.mode,
            "prd_mode": self.prd_mode,
            "prd_major": self.prd_major,
            "build": self.build,
            "roles": self.roles,
            "created": self.created,
            "documents": self.documents,
        }

    def document(self, kind: str) -> dict | None:
        return next((d for d in self.documents if d["kind"] == kind), None)


def _folder(root: Path, slug: str) -> Path:
    return Path(root) / SDLC_DIR / slug


def _document_path(slug: str, kind: str) -> str:
    if kind == "plan":
        return f"{PLANS_DIR}/{slug}.plan.md"
    return f"{SDLC_DIR}/{slug}/{kind}.md"


def _new_document(slug: str, kind: str) -> dict:
    return {
        "kind": kind,
        "path": _document_path(slug, kind),
        "status": Status.DRAFT.value,
        "version": 1,
        "written_by": None,
        "reviewed_by": None,
        "approved_by": None,
        "approved_at": None,
        "upstream": {},
    }


def _free_slug(root: Path, name: str) -> str:
    base = plan_slug(name)
    slug, number = base, 2
    while _folder(root, slug).exists():
        slug = f"{base}-{number}"
        number += 1
    return slug


def create(
    root: Path,
    name: str,
    size: Size | str,
    mode: Mode | str,
    *,
    brainstorm_first: bool = False,
    prd_mode: PrdMode | str | None = None,
    prd_major: bool = False,
    build: bool = True,
    roles: dict,
) -> DocSet:
    root = Path(root)
    size = Size(size)
    mode = Mode(mode)
    if size is Size.SMALL:
        prd = PrdMode.NONE
    elif prd_mode is None:
        prd = PrdMode.UPDATE if (root / PRODUCT_PRD).is_file() else PrdMode.NEW
    else:
        prd = PrdMode(prd_mode)
    slug = _free_slug(root, name)
    docset = DocSet(
        name=name,
        slug=slug,
        size=size.value,
        mode=mode.value,
        prd_mode=prd.value,
        prd_major=prd_major,
        build=build,
        roles=dict(roles),
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        documents=[_new_document(slug, k) for k in documents_for(size, brainstorm_first, prd)],
    )
    save(root, docset)
    return docset


def load(root: Path, slug: str) -> DocSet:
    path = _folder(root, slug) / MANIFEST
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DocSetError(f"No document set named {slug!r}: {path} is missing.") from None
    except (OSError, ValueError) as error:
        raise DocSetError(f"The document set {slug!r} could not be read: {error}") from None
    try:
        if raw.get("schema") != SCHEMA:
            raise DocSetError(f"The document set {slug!r} uses an unknown schema: {raw.get('schema')!r}.")
        return DocSet(
            name=raw["name"],
            slug=raw["slug"],
            size=raw["size"],
            mode=raw["mode"],
            prd_mode=raw["prd_mode"],
            prd_major=bool(raw.get("prd_major", False)),
            build=bool(raw.get("build", True)),
            roles=dict(raw.get("roles", {})),
            created=raw.get("created", ""),
            documents=list(raw["documents"]),
            schema=raw["schema"],
        )
    except DocSetError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise DocSetError(f"The document set {slug!r} is damaged: {error!r}.") from None


def save(root: Path, docset: DocSet) -> None:
    atomic_write_json(_folder(root, docset.slug) / MANIFEST, docset.to_dict())


def all_sets(root: Path) -> list[DocSet]:
    base = Path(root) / SDLC_DIR
    found: list[DocSet] = []
    if not base.is_dir():
        return found
    for folder in sorted(base.iterdir()):
        if (folder / MANIFEST).is_file():
            try:
                found.append(load(root, folder.name))
            except DocSetError:
                continue
    return found
