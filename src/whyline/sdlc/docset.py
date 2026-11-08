"""The document set manifest: which documents a piece of work has, and their state."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from whyline.console.relay_ops import PLANS_DIR, plan_slug
from whyline.sdlc import workspace
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


HISTORY_DIR = "history"
REVIEW_LOG = "review-log.md"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _doc(docset: DocSet, kind: str) -> dict:
    doc = docset.document(kind)
    if doc is None:
        raise DocSetError(f"The document set {docset.slug!r} has no {kind!r} document.")
    return doc


def _history_path(root: Path, slug: str, kind: str, number: int) -> Path:
    return _folder(root, slug) / HISTORY_DIR / f"{kind}-v{number}.md"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def add_version(root: Path, docset: DocSet, kind: str, text: str, *, author: str, note: str) -> int:
    """Store a new version of a document and put it in review; returns its number.

    A fresh document is already at version 1 with nothing written, so its first
    text is v1; every later text is the next number.
    """
    root = Path(root)
    doc = _doc(docset, kind)
    number = int(doc["version"])
    if _history_path(root, docset.slug, kind, number).exists():
        number += 1
    if kind != "plan":
        _write(root / doc["path"], text)
    _write(_history_path(root, docset.slug, kind, number), text)
    doc["version"] = number
    doc["status"] = Status.IN_REVIEW.value
    doc["written_by"] = author
    doc["note"] = note
    save(root, docset)
    refresh(root, docset)
    return number


def log_review(
    root: Path,
    docset: DocSet,
    kind: str,
    *,
    actor: str,
    action: str,
    comment: str = "",
    section: str = "",
    changed_sections=(),
) -> None:
    """Append one entry to the set's review-log.md."""
    doc = _doc(docset, kind)
    today = datetime.now(timezone.utc).date().isoformat()
    lines = [f"### {today} · {kind} v{doc['version']} · {action} · {actor}", ""]
    if comment:
        lines += [comment, ""]
    if section:
        lines += [f"Section: {section}", ""]
    if changed_sections:
        lines += ["Changed: " + ", ".join(changed_sections), ""]
    path = _folder(root, docset.slug) / REVIEW_LOG
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    _write(path, existing + "\n".join(lines) + "\n")


def _current_text(root: Path, docset: DocSet, doc: dict) -> str:
    """A document's text: its file, or for an unapproved plan its history copy."""
    path = Path(root) / doc["path"]
    if path.is_file():
        return strip_header(path.read_text(encoding="utf-8"))
    copy = _history_path(root, docset.slug, doc["kind"], int(doc["version"]))
    return copy.read_text(encoding="utf-8") if copy.is_file() else ""


def approve(root: Path, docset: DocSet, kind: str, *, approver: str) -> None:
    root = Path(root)
    doc = _doc(docset, kind)
    upstream: dict[str, str] = {}
    for other in docset.documents:
        if other["kind"] == kind:
            break
        if other["status"] == Status.APPROVED.value:
            upstream[other["kind"]] = _sha(_current_text(root, docset, other))
    doc["status"] = Status.APPROVED.value
    doc["approved_by"] = approver
    doc["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc["upstream"] = upstream
    log_review(root, docset, kind, actor=approver, action="approved")
    save(root, docset)
    refresh(root, docset)


def commit(root: Path, docset: DocSet, message: str) -> bool:
    """Commit the set's own files in the docs checkout; False when nothing changed.

    docs_commit only accepts a dirty path when it is a file whyline wrote, so
    the set's folder is listed file by file.
    """
    docs = workspace.docs_root(Path(root))
    rels = [
        str(p.relative_to(docs))
        for p in sorted(_folder(docs, docset.slug).rglob("*"))
        if p.is_file()
    ]
    extra = [f"{PLANS_DIR}/{docset.slug}.plan.md", f"{PLANS_DIR}/{docset.slug}.tests.md"]
    if docset.prd_mode != PrdMode.NONE.value:
        extra.insert(0, PRODUCT_PRD)
    rels += [rel for rel in extra if (docs / rel).is_file()]
    written = {rel: (docs / rel).read_text() for rel in rels}
    return workspace.docs_commit(docs, rels, message, written)


HEADER_START = "<!-- docset-header -->"
HEADER_END = "<!-- /docset-header -->"
INDEX = "index.md"


def _kind_title(kind: str) -> str:
    return kind.replace("-", " ").capitalize()


def _link(from_dir: str, target: str) -> str:
    return os.path.relpath(target, from_dir or ".").replace(os.sep, "/")


def _neighbours(docset: DocSet, kind: str) -> tuple[dict | None, dict | None]:
    kinds = [d["kind"] for d in docset.documents]
    at = kinds.index(kind)
    before = docset.documents[at - 1] if at > 0 else None
    after = docset.documents[at + 1] if at + 1 < len(kinds) else None
    return before, after


def render_header(docset: DocSet, kind: str) -> str:
    """The block shown at the top of a document; plan files never get one."""
    doc = _doc(docset, kind)
    folder = os.path.dirname(doc["path"])
    before, after = _neighbours(docset, kind)

    def nav(other: dict | None) -> str:
        if other is None:
            return "none"
        return f"[{_kind_title(other['kind'])}]({_link(folder, other['path'])})"

    approved = "not yet"
    if doc.get("approved_by"):
        approved = doc["approved_by"]
        if doc.get("approved_at"):
            approved += f" on {doc['approved_at']}"
    lines = [
        HEADER_START,
        f"**Status:** {Status(doc['status']).label} · **Version:** v{doc['version']}",
        f"**Written by:** {doc.get('written_by') or 'nobody yet'}"
        f" · **Reviewed by:** {doc.get('reviewed_by') or 'nobody yet'}",
        f"**Approved by:** {approved}",
        f"**Before:** {nav(before)} · **After:** {nav(after)}",
        HEADER_END,
    ]
    return "\n".join(lines) + "\n"


def _block_span(text: str) -> tuple[int, int] | None:
    start = text.find(HEADER_START)
    if start < 0:
        return None
    end = text.find(HEADER_END, start)
    if end < 0:
        return None
    end += len(HEADER_END)
    if text.startswith("\n", end):
        end += 1
    return start, end


def apply_header(text: str, header: str) -> str:
    """Replace the header block, or put one at the top; nothing else changes."""
    span = _block_span(text)
    if span is None:
        return header + "\n" + text
    return text[: span[0]] + header + text[span[1] :]


def strip_header(text: str) -> str:
    """The text as apply_header found it: the block and its blank line removed."""
    span = _block_span(text)
    if span is None:
        return text
    rest = text[span[1] :]
    if text[: span[0]] == "" and rest.startswith("\n"):
        rest = rest[1:]
    return text[: span[0]] + rest


def render_index(docset: DocSet) -> str:
    """The set's index.md: name, size, mode, every document, and the plan links."""
    folder = f"{SDLC_DIR}/{docset.slug}"
    lines = [
        f"# {docset.name}",
        "",
        f"- **Size:** {Size(docset.size).label}",
        f"- **Mode:** {Mode(docset.mode).label}",
        "",
        "| Document | Status | Version | Approval |",
        "| --- | --- | --- | --- |",
    ]
    for doc in docset.documents:
        approval = "—"
        if doc.get("approved_by"):
            approval = f"{doc['approved_by']} on {doc.get('approved_at') or '?'}"
        lines.append(
            f"| [{_kind_title(doc['kind'])}]({_link(folder, doc['path'])})"
            f" | {Status(doc['status']).label} | v{doc['version']} | {approval} |"
        )
    if docset.document("plan") is not None:
        lines += [
            "",
            f"- [Plan]({_link(folder, _document_path(docset.slug, 'plan'))})",
            f"- [Test plan]({_link(folder, f'{PLANS_DIR}/{docset.slug}.tests.md')})",
        ]
    return "\n".join(lines) + "\n"


def refresh(root: Path, docset: DocSet) -> None:
    """Rewrite every written document's header and the set's index.md."""
    root = Path(root)
    for doc in docset.documents:
        if doc["kind"] == "plan":
            continue
        path = root / doc["path"]
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        updated = apply_header(text, render_header(docset, doc["kind"]))
        if updated != text:
            path.write_text(updated, encoding="utf-8")
    _write(_folder(root, docset.slug) / INDEX, render_index(docset))
