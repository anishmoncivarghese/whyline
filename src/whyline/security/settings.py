"""`[security]` settings, the committed allowlist, and the block/warn decision."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from whyline.security.findings import Finding

SECRETS = ("block", "warn", "off")
DEPENDENCIES = ("block", "block-high", "warn", "off")
CONTENTS = ("block", "warn", "off")
AUDIT = ("off", "warn", "block-confirmed")

ALLOW_PATH = Path(".whyline") / "security-allow.toml"
IGNORE_FILE = "security-ignore-once.json"

_HIGH = ("critical", "high")
DEFAULT_SKIP_PATHS = ("tests/**/fixtures/**",)


class SettingsError(ValueError):
    """A bad `[security]` value or allowlist; the message names the key."""


@dataclass(frozen=True)
class SecuritySettings:
    secrets: str = "block"
    dependencies: str = "block-high"
    contents: str = "block"
    history_scanned: str = ""
    pre_commit: bool = False
    audit: str = "off"
    skip_paths: tuple[str, ...] = DEFAULT_SKIP_PATHS


_CHOICES = {
    "secrets": SECRETS,
    "dependencies": DEPENDENCIES,
    "contents": CONTENTS,
    "audit": AUDIT,
}


def validate(settings: SecuritySettings) -> None:
    for key, choices in _CHOICES.items():
        value = getattr(settings, key)
        if value not in choices:
            raise SettingsError(f"security.{key} must be one of {', '.join(choices)}, not {value!r}")
    if not isinstance(settings.history_scanned, str):
        raise SettingsError("security.history_scanned must be a string")
    if not isinstance(settings.pre_commit, bool):
        raise SettingsError("security.pre_commit must be true or false")
    if not isinstance(settings.skip_paths, tuple) or not all(
        isinstance(p, str) for p in settings.skip_paths
    ):
        raise SettingsError("security.skip_paths must be a list of strings")


def parse(table: object) -> SecuritySettings:
    if not isinstance(table, dict):
        raise SettingsError("security must be a table")
    base = SecuritySettings()
    values = {}
    for key in ("secrets", "dependencies", "contents", "history_scanned", "audit"):
        value = table.get(key, getattr(base, key))
        if not isinstance(value, str):
            raise SettingsError(f"security.{key} must be a string")
        values[key] = value
    pre_commit = table.get("pre_commit", base.pre_commit)
    if not isinstance(pre_commit, bool):
        raise SettingsError("security.pre_commit must be true or false")
    skip = table.get("skip_paths", list(base.skip_paths))
    if not isinstance(skip, list) or not all(isinstance(p, str) for p in skip):
        raise SettingsError("security.skip_paths must be a list of strings")
    settings = SecuritySettings(
        pre_commit=pre_commit, skip_paths=tuple(p.strip() for p in skip if p.strip()), **values
    )
    validate(settings)
    return settings


# --- the allowlist -------------------------------------------------------------


def _read_allow(root: Path) -> list[dict]:
    path = Path(root) / ALLOW_PATH
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{ALLOW_PATH.as_posix()} is not valid TOML: {exc}") from exc
    entries = data.get("allow", [])
    if not isinstance(entries, list):
        raise SettingsError("allow must be a list of tables")
    return [e for e in entries if isinstance(e, dict)]


def _render_allow(entries: list[dict]) -> str:
    from whyline.release.config import _quote

    lines: list[str] = []
    for e in entries:
        if lines:
            lines.append("")
        lines.append("[[allow]]")
        for key in ("fingerprint", "rule", "path", "reason", "added"):
            lines.append(f"{key} = {_quote(str(e.get(key, '')))}")
    return "\n".join(lines) + "\n"


def allow(root: Path, finding: Finding, reason: str) -> None:
    """Add the finding to the committed allowlist. A reason is required."""
    if not reason or not reason.strip():
        raise SettingsError("an allowlist entry needs a reason")
    if not finding.fingerprint:
        raise SettingsError("this finding has no fingerprint to allow")
    from whyline.release.config import _write_atomic

    entries = [e for e in _read_allow(root) if e.get("fingerprint") != finding.fingerprint]
    entries.append(
        {
            "fingerprint": finding.fingerprint,
            "rule": finding.rule,
            "path": finding.path,
            "reason": reason.strip(),
            "added": date.today().isoformat(),
        }
    )
    _write_atomic(Path(root) / ALLOW_PATH, _render_allow(entries))
    # The release commit must include the new entry, and the clean-tree check must accept it.
    from whyline.release.config import add_pending

    add_pending(Path(root), ALLOW_PATH)


def matches_entry(entry: dict, finding: Finding) -> bool:
    """An allowlist entry covers a finding by fingerprint. An older entry made
    for a versioned package path (`pkg-0.3.69.tar.gz:pkg-0.3.69/x`) also covers
    that exact path, rule and value."""
    if not finding.fingerprint:
        return False
    if entry.get("fingerprint") == finding.fingerprint:
        return True
    # The older fingerprint hashed the value too, so a changed secret stays blocking.
    return bool(
        finding.legacy_fingerprint
        and entry.get("fingerprint") == finding.legacy_fingerprint
        and entry.get("path") == finding.path
        and entry.get("rule") == finding.rule
    )


def is_allowed(root: Path, finding: Finding) -> bool:
    return any(matches_entry(e, finding) for e in _read_allow(root))


# --- ignore once (this release run only) ---------------------------------------


def _ignored(state_dir: Path) -> list[str]:
    try:
        data = json.loads((Path(state_dir) / IGNORE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [f for f in data if isinstance(f, str)] if isinstance(data, list) else []


def ignore_once(state_dir: Path, finding: Finding) -> None:
    """Remember the finding under the release state dir (`.git/whyline-release/`)
    until `clear_ignored` runs at the end of the release."""
    from whyline.release.config import _write_atomic

    ids = _ignored(state_dir)
    if finding.fingerprint and finding.fingerprint not in ids:
        ids.append(finding.fingerprint)
    _write_atomic(Path(state_dir) / IGNORE_FILE, json.dumps(ids) + "\n")


def is_ignored_once(state_dir: Path, finding: Finding) -> bool:
    return bool(finding.fingerprint) and finding.fingerprint in _ignored(state_dir)


def clear_ignored(state_dir: Path) -> None:
    (Path(state_dir) / IGNORE_FILE).unlink(missing_ok=True)


# --- deciding ------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    blocking: tuple[Finding, ...] = ()
    warnings: tuple[Finding, ...] = ()
    allowed: tuple[Finding, ...] = ()


def _level(finding: Finding, settings: SecuritySettings) -> str:
    """`block`, `warn` or `off` for one finding."""
    if finding.kind == "secret":
        return settings.secrets
    if finding.kind == "contents":
        return settings.contents
    if finding.kind == "dependency":
        if settings.dependencies == "block-high":
            return "block" if finding.severity in _HIGH else "warn"
        return settings.dependencies
    # audit: findings that reach here are the confirmed ones
    return "block" if settings.audit == "block-confirmed" else settings.audit


def decide(
    findings: Iterable[Finding],
    settings: SecuritySettings,
    is_exempt: Callable[[Finding], bool] | None = None,
) -> Decision:
    """Sort findings into blocking, warnings and allowed. `is_exempt` marks
    findings on the allowlist or ignored once; those never block."""
    blocking: list[Finding] = []
    warnings: list[Finding] = []
    allowed: list[Finding] = []
    for finding in findings:
        level = _level(finding, settings)
        if level == "off":
            continue
        if is_exempt is not None and is_exempt(finding):
            allowed.append(finding)
        elif level == "block":
            blocking.append(finding)
        else:
            warnings.append(finding)
    return Decision(tuple(blocking), tuple(warnings), tuple(allowed))
