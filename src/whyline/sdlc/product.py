"""The product PRD: one living document under docs/product/, versioned as it is approved."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from whyline.sdlc import templates
from whyline.state import atomic_write_json

SCHEMA = 1
PRODUCT_DIR = "docs/product"
PRD_FILE = "prd.md"
META_FILE = "product.json"
CHANGELOG = "changelog.md"
HISTORY_DIR = "history"
NEW_PRD = "all (new PRD)"

_MARKER = re.compile(r"^<!-- product-prd v(\d+\.\d+) -->$")
_VERSION = re.compile(r"^(\d+)\.(\d+)$")


@dataclass(frozen=True)
class ProductPrd:
    version: str
    path: Path
    text: str
    sha256: str


def _folder(root: Path) -> Path:
    return Path(root) / PRODUCT_DIR


def _marker(version: str) -> str:
    return f"<!-- product-prd v{version} -->"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _meta(root: Path) -> dict:
    try:
        raw = json.loads((_folder(root) / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_meta(root: Path, meta: dict) -> None:
    meta["schema"] = SCHEMA
    atomic_write_json(_folder(root) / META_FILE, meta)


def body(text: str) -> str:
    """The PRD text without its version marker line."""
    first, _, rest = text.partition("\n")
    return rest if _MARKER.match(first) else text


def current(root: Path) -> ProductPrd | None:
    path = _folder(root) / PRD_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    found = _MARKER.match(text.partition("\n")[0])
    version = found.group(1) if found else str(_meta(root).get("version") or "1.0")
    return ProductPrd(version=version, path=path, text=text, sha256=_sha(text))


def next_version(version: str | None, *, major: bool = False) -> str:
    if not version:
        return "1.0"
    found = _VERSION.match(version)
    if not found:
        raise ValueError(f"Not a PRD version: {version!r}.")
    big, small = int(found.group(1)), int(found.group(2))
    return f"{big + 1}.0" if major else f"{big}.{small + 1}"


def _split(text: str) -> list[tuple[str, str]]:
    """(heading, body) for each `##` section, ignoring headings inside code fences."""
    found: list[tuple[str, list[str]]] = []
    fence = ""
    for line in text.splitlines():
        fenced = templates._FENCE.match(line)
        if fenced:
            marker = fenced.group(1)
            if not fence:
                fence = marker
            elif marker == fence:
                fence = ""
        elif not fence:
            heading = templates._HEADING.match(line)
            if heading:
                found.append((heading.group(1), []))
                continue
        if found:
            found[-1][1].append(line)
    return [(name, "\n".join(lines).strip()) for name, lines in found]


def _keyed(text: str) -> dict[tuple[str, int], str]:
    seen: dict[str, int] = {}
    keyed: dict[tuple[str, int], str] = {}
    for name, content in _split(text):
        seen[name] = seen.get(name, 0) + 1
        keyed[(name, seen[name])] = content
    return keyed


def changed_sections(old: str, new: str) -> list[str]:
    """Headings whose text differs, is new, or was removed; new order first, then removed."""
    before, after = _keyed(old), _keyed(new)
    names = [key[0] for key in after if before.get(key) != after[key]]
    names += [key[0] for key in before if key not in after]
    return names


def publish(
    root: Path,
    text: str,
    *,
    set_name: str,
    slug: str,
    approver: str,
    major: bool = False,
) -> str:
    """Write the next PRD version, its history copy, product.json and a changelog line."""
    from whyline.sdlc.docset import strip_header

    root = Path(root)
    old = current(root)
    version = next_version(old.version if old else None, major=major)
    text = strip_header(text)
    if old is None:
        sections = NEW_PRD
    else:
        sections = ", ".join(changed_sections(body(old.text), text)) or "none"
    full = _marker(version) + "\n" + text
    folder = _folder(root)
    history = folder / HISTORY_DIR / f"prd-v{version}.md"
    history.parent.mkdir(parents=True, exist_ok=True)
    (folder / PRD_FILE).write_text(full, encoding="utf-8")
    history.write_text(full, encoding="utf-8")
    now = datetime.now(timezone.utc)
    meta = _meta(root)
    meta.update(
        version=version,
        approved_by=approver,
        approved_at=now.isoformat(timespec="seconds"),
        sha256=_sha(full),
    )
    meta.setdefault("update_claim", None)
    _save_meta(root, meta)
    line = (
        f"v{version} · {now.date().isoformat()} · {set_name}"
        f" · changed: {sections} · approved by {approver}"
    )
    log = folder / CHANGELOG
    existing = log.read_text(encoding="utf-8") if log.is_file() else "# Changelog\n\n"
    if not existing.endswith("\n"):
        existing += "\n"
    log.write_text(existing + line + "\n", encoding="utf-8")
    return version


def _is_live(root: Path, slug: str) -> bool:
    """A claim stands while its set exists and its PRD is not yet approved."""
    from whyline.sdlc import docset

    try:
        found = docset.load(root, slug)
    except docset.DocSetError:
        return False
    prd = found.document("prd")
    return prd is not None and prd["status"] != docset.Status.APPROVED.value


def claim_holder(root: Path) -> str | None:
    slug = _meta(root).get("update_claim")
    if slug and _is_live(Path(root), slug):
        return slug
    return None


def claim_update(root: Path, slug: str) -> bool:
    """Take the one open update; False when another live set holds it."""
    holder = claim_holder(root)
    if holder is not None and holder != slug:
        return False
    meta = _meta(root)
    meta["update_claim"] = slug
    _save_meta(Path(root), meta)
    return True


def release_update(root: Path, slug: str) -> None:
    meta = _meta(root)
    if meta.get("update_claim") == slug:
        meta["update_claim"] = None
        _save_meta(Path(root), meta)


def moved(root: Path, docset) -> bool:
    """True when the product PRD has a version the set's PRD was not based on."""
    prd = docset.document("prd")
    now = current(root)
    if prd is None or now is None:
        return False
    return prd.get("based_on") != now.version
