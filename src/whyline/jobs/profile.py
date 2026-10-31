"""Personal job-search profile store in ~/.whyline/jobs/ (files mode 0600)."""
from __future__ import annotations

import datetime
import json
import math
import os
import re
import shlex
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

from whyline.jobs import paths

MAX_CV_BYTES = 200 * 1024
_MAX_DOCX_XML_BYTES = 10 * 1024 * 1024

CV_FILE = "cv.md"
PREFERENCES_FILE = "preferences.toml"
PROFILE_FILE = "profile.md"
RUBRIC_FILE = "rubric.md"
MANAGED_FILES = (CV_FILE, PREFERENCES_FILE, PROFILE_FILE, RUBRIC_FILE)

CV_EXTENSIONS = (".md", ".txt", ".docx")
REMOTE_MODES = ("any", "remote", "hybrid", "onsite")
KNOWN_PREFERENCE_KEYS = (
    "roles",
    "seniority",
    "locations",
    "remote",
    "salary_min",
    "currency",
    "languages",
    "deal_breakers",
    "notes",
)

_LIST_STR_KEYS = frozenset({"roles", "locations", "languages", "deal_breakers"})
_STR_KEYS = frozenset({"seniority", "currency", "notes"})
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TOML_INT_MIN = -(1 << 63)
_TOML_INT_MAX = (1 << 63) - 1


class ProfileError(ValueError):
    """Raised when a CV or preference value is invalid or cannot be stored."""


@dataclass(frozen=True)
class FileStatus:
    name: str
    path: Path
    exists: bool
    modified_at: datetime.datetime | None
    size_bytes: int = 0

    @property
    def changed_at(self) -> datetime.datetime | None:
        return self.modified_at

    @property
    def last_changed(self) -> datetime.datetime | None:
        return self.modified_at

    @property
    def mtime(self) -> float | None:
        return self.modified_at.timestamp() if self.modified_at is not None else None


def _fresh_defaults() -> dict[str, Any]:
    return {
        "roles": [],
        "seniority": "",
        "locations": [],
        "remote": "any",
        "salary_min": 0,
        "currency": "",
        "languages": [],
        "deal_breakers": [],
        "notes": "",
    }


def cv_path() -> Path:
    return paths.configured_home() / CV_FILE


def preferences_path() -> Path:
    return paths.configured_home() / PREFERENCES_FILE


def profile_path() -> Path:
    return paths.configured_home() / PROFILE_FILE


def rubric_path() -> Path:
    return paths.configured_home() / RUBRIC_FILE


def _ensure_utf8(value: str, label: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ProfileError(f"{label} contains invalid Unicode text.") from error


def _write_private_text(filename: str, text: str) -> Path:
    _ensure_utf8(text, filename)
    try:
        folder = paths.home()
    except OSError as error:
        raise ProfileError(f"Could not prepare jobs folder: {error}") from error
    target = folder / filename
    if target.is_symlink():
        raise ProfileError(f"Refusing to overwrite symlink: {target}")
    fd, raw_tmp = tempfile.mkstemp(dir=folder, prefix=f".{filename}.", suffix=".tmp")
    tmp_path = Path(raw_tmp)
    try:
        if os.name != "nt":
            os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if target.is_symlink():
            raise ProfileError(f"Refusing to overwrite symlink: {target}")
        os.replace(tmp_path, target)
        if os.name != "nt":
            os.chmod(target, 0o600)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def save_profile(text: str) -> Path:
    """Write accepted profile.md with mode 0600."""
    if not isinstance(text, str):
        raise ProfileError("Profile text must be a string.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return _write_private_text(PROFILE_FILE, normalized)


def save_rubric(text: str) -> Path:
    """Write accepted rubric.md with mode 0600."""
    if not isinstance(text, str):
        raise ProfileError("Rubric text must be a string.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return _write_private_text(RUBRIC_FILE, normalized)


def import_cv_text(text: str) -> Path:
    """Validate CV text against the 200 KB limit and write cv.md (mode 0600)."""
    if not isinstance(text, str):
        raise ProfileError("CV text must be a string.")
    _ensure_utf8(text, "CV text")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized.encode("utf-8")) > MAX_CV_BYTES:
        raise ProfileError("CV is over the 200 KB text limit.")
    return _write_private_text(CV_FILE, normalized)


def _local_tag(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _collect_inline(
    elem: ElementTree.Element,
    parts: list[str],
    nested_paragraphs: list[str],
) -> None:
    for child in elem:
        tag = _local_tag(child.tag)
        if tag == "del":
            continue
        if tag == "p":
            nested_paragraphs.extend(_extract_paragraphs(child))
            continue
        if tag == "t":
            if child.text:
                parts.append(
                    child.text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                )
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append(" ")
        else:
            _collect_inline(child, parts, nested_paragraphs)


def _extract_paragraphs(node: ElementTree.Element) -> list[str]:
    if _local_tag(node.tag) == "p":
        parts: list[str] = []
        nested: list[str] = []
        _collect_inline(node, parts, nested)
        return ["".join(parts), *nested]
    lines: list[str] = []
    for child in node:
        if _local_tag(child.tag) == "del":
            continue
        lines.extend(_extract_paragraphs(child))
    return lines


def _read_docx_text(source: Path) -> str:
    try:
        with zipfile.ZipFile(source) as archive:
            try:
                info = archive.getinfo("word/document.xml")
            except KeyError as error:
                raise ProfileError(
                    "Could not read .docx file: word/document.xml is missing."
                ) from error
            with archive.open(info) as doc_stream:
                xml_bytes = doc_stream.read(_MAX_DOCX_XML_BYTES + 1)
    except ProfileError:
        raise
    except (OSError, zipfile.BadZipFile) as error:
        raise ProfileError("Could not read .docx file: invalid Word document.") from error

    if len(xml_bytes) > _MAX_DOCX_XML_BYTES:
        raise ProfileError("CV is over the 200 KB text limit.")
    if b"<!ENTITY" in xml_bytes.upper():
        raise ProfileError("Could not read .docx file: XML entities are not allowed.")

    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as error:
        raise ProfileError(
            "Could not read .docx file: word/document.xml is not valid XML."
        ) from error

    paragraphs = _extract_paragraphs(root)
    return "\n".join(paragraphs)


def _read_plain_cv(source: Path) -> str:
    max_raw_bytes = MAX_CV_BYTES * 2 + 3  # CRLF -> LF + optional 3-byte UTF-8 BOM
    try:
        with source.open("rb") as handle:
            raw = handle.read(max_raw_bytes + 1)
    except OSError as error:
        raise ProfileError(f"Could not read CV file: {error}") from error
    if len(raw) > max_raw_bytes:
        raise ProfileError("CV is over the 200 KB text limit.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProfileError("CV file must be UTF-8 text.") from error
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def _pasted_path(raw: str) -> Path:
    """A path as typed or pasted: Finder's Copy as Pathname and drag-and-drop
    quote it ('…') or escape spaces (\\ ), and some apps paste a file:// URL.
    Never runs the text through a shell."""
    text = raw.strip()
    plain = Path(text).expanduser()
    if plain.exists():
        return plain
    if text.startswith("file://"):
        return Path(unquote(urlparse(text).path))
    try:
        tokens = shlex.split(text)
    except ValueError:  # an unbalanced quote: use the text as given
        return plain
    return Path(tokens[0]).expanduser() if len(tokens) == 1 else plain


def import_cv(path: str | Path) -> Path:
    """Import a CV from a .md, .txt, or .docx file into ~/.whyline/jobs/cv.md."""
    if not isinstance(path, (str, Path)):
        raise ProfileError("CV path must be a path or string.")
    source = _pasted_path(path) if isinstance(path, str) else path.expanduser()
    suffix = source.suffix.lower()
    if suffix not in CV_EXTENSIONS:
        shown = source.suffix or "<no extension>"
        raise ProfileError(
            f"Unsupported CV format '{shown}'; choose a .md, .txt, or .docx file."
        )
    if not source.exists() or not source.is_file():
        raise ProfileError(f"CV file not found: {source}")
    text = _read_docx_text(source) if suffix == ".docx" else _read_plain_cv(source)
    return import_cv_text(text)


def _validate_toml_value(value: Any, label: str) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not (_TOML_INT_MIN <= value <= _TOML_INT_MAX):
            raise ProfileError(f"{label} integer is out of TOML 64-bit range.")
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        _ensure_utf8(value, label)
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value
    if isinstance(value, list):
        return [
            _validate_toml_value(item, f"{label}[{idx}]")
            for idx, item in enumerate(value)
        ]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ProfileError(f"{label} table keys must be strings.")
            _ensure_utf8(k, f"{label} key")
            out[k] = _validate_toml_value(v, f"{label}.{k}")
        return out
    raise ProfileError(
        f"{label} has unsupported preference type {type(value).__name__}."
    )


def _validate_preferences(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ProfileError("Preferences must be a mapping.")
    for key in raw:
        if not isinstance(key, str):
            raise ProfileError("Preference keys must be strings.")
        _ensure_utf8(key, "Preference key")

    merged = {**_fresh_defaults(), **dict(raw)}
    validated: dict[str, Any] = {}

    for key in KNOWN_PREFERENCE_KEYS:
        value = merged[key]
        if key in _LIST_STR_KEYS:
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ProfileError(f"{key} must be a list of strings.")
            for item in value:
                _ensure_utf8(item, key)
            validated[key] = list(value)
        elif key in _STR_KEYS:
            if not isinstance(value, str):
                raise ProfileError(f"{key} must be a string.")
            _ensure_utf8(value, key)
            validated[key] = value
        elif key == "remote":
            if not isinstance(value, str) or value not in REMOTE_MODES:
                allowed = ", ".join(REMOTE_MODES)
                raise ProfileError(f"remote must be one of: {allowed}.")
            validated[key] = value
        elif key == "salary_min":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ProfileError("salary_min must be a whole number.")
            if value < 0 or value > _TOML_INT_MAX:
                raise ProfileError("salary_min must be zero or a positive whole number.")
            validated[key] = value

    for key, value in merged.items():
        if key not in validated:
            validated[key] = _validate_toml_value(value, key)

    return validated


def _read_raw_preferences() -> dict[str, Any]:
    target = preferences_path()
    if not target.exists():
        return {}
    if target.is_symlink() or not target.is_file():
        raise ProfileError("preferences.toml is not a regular file.")
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ProfileError(f"Could not read preferences.toml: {error}") from error
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise ProfileError(f"preferences.toml is not valid TOML: {error}") from error
    return parsed


def load_preferences() -> dict[str, Any]:
    """Load preferences.toml with defaults, validating known keys and keeping unknown keys."""
    raw = _read_raw_preferences()
    return _validate_preferences(raw)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_key(key: str) -> str:
    if key and _BARE_KEY_RE.match(key):
        return key
    return _toml_string(key)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items())
        return "{" + inner + "}"
    raise ProfileError(f"Unsupported preference value: {type(value).__name__}.")


def _render_subtables(prefix: tuple[str, ...], table: dict[str, Any], lines: list[str]) -> None:
    scalars = [(k, v) for k, v in table.items() if not isinstance(v, dict)]
    subtables = [(k, v) for k, v in table.items() if isinstance(v, dict)]
    if scalars or not subtables:
        header = ".".join(_toml_key(part) for part in prefix)
        if lines:
            lines.append("")
        lines.append(f"[{header}]")
        for k, v in scalars:
            lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
    for k, sub in subtables:
        _render_subtables((*prefix, k), sub, lines)


def _render_preferences(prefs: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in KNOWN_PREFERENCE_KEYS:
        lines.append(f"{_toml_key(key)} = {_toml_value(prefs[key])}")
    unknown_scalars = [
        (k, v)
        for k, v in prefs.items()
        if k not in KNOWN_PREFERENCE_KEYS and not isinstance(v, dict)
    ]
    unknown_tables = [
        (k, v)
        for k, v in prefs.items()
        if k not in KNOWN_PREFERENCE_KEYS and isinstance(v, dict)
    ]
    for k, v in unknown_scalars:
        lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
    for k, v in unknown_tables:
        _render_subtables((k,), v, lines)
    rendered = "\n".join(lines) + "\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise ProfileError(f"Failed to serialise preferences as TOML: {error}") from error
    return rendered


def save_preferences(prefs: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and save preferences.toml (mode 0600), keeping unknown keys."""
    if not isinstance(prefs, Mapping):
        raise ProfileError("Preferences must be a mapping.")
    existing = _read_raw_preferences()
    merged: dict[str, Any] = {**_fresh_defaults(), **existing, **dict(prefs)}
    validated = _validate_preferences(merged)
    rendered = _render_preferences(validated)
    _write_private_text(PREFERENCES_FILE, rendered)
    return _validate_preferences(validated)


def status() -> dict[str, FileStatus]:
    """Report which managed files exist in ~/.whyline/jobs/ and when each changed."""
    folder = paths.configured_home()
    report: dict[str, FileStatus] = {}
    for name in MANAGED_FILES:
        target = folder / name
        if not target.is_symlink() and target.is_file():
            st = target.stat()
            modified = datetime.datetime.fromtimestamp(
                st.st_mtime, tz=datetime.timezone.utc
            )
            report[name] = FileStatus(
                name=name,
                path=target,
                exists=True,
                modified_at=modified,
                size_bytes=st.st_size,
            )
        else:
            report[name] = FileStatus(
                name=name,
                path=target,
                exists=False,
                modified_at=None,
                size_bytes=0,
            )
    return report
