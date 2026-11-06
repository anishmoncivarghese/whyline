"""Read dependency lockfiles into a flat list of pinned packages.

Each entry says whether it came from a public registry (so an advisory database
can know it) or is private (editable, path, git, a private registry). Ecosystem
names are OSV's. YAML and yarn files are read with small line parsers so no
YAML dependency is needed.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

PYPI = "PyPI"
NPM = "npm"

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)
_NPM_HOSTS = frozenset({"registry.npmjs.org", "registry.yarnpkg.com"})
_PYPI_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})
_PEP503 = re.compile(r"[-_.]+")
_REQ_PIN = re.compile(
    r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?:\[[^\]]*\])?\s*==\s*([^\s;,#=*]+)\s*(?:;.*)?$"
)


@dataclass(frozen=True)
class Dependency:
    name: str
    version: str
    ecosystem: str
    source_file: str
    public: bool


@dataclass(frozen=True)
class Unpinned:
    """A requirements line that is not a plain `name==version` pin."""

    line: str
    source_file: str

    @property
    def note(self) -> str:
        return f"{self.line}: unpinned, not checked"


@dataclass
class LockfileReport:
    dependencies: list[Dependency] = field(default_factory=list)
    unpinned: list[Unpinned] = field(default_factory=list)


def normalize_pypi(name: str) -> str:
    return _PEP503.sub("-", name).lower()


def read_all(root: str | Path) -> list[Dependency]:
    return read_report(root).dependencies


def read_report(root: str | Path) -> LockfileReport:
    """Find and parse every supported lockfile under `root`."""
    base = Path(root)
    report = LockfileReport()
    for path in _find_files(base):
        rel = path.relative_to(base).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            _parse(path.name, text, rel, report)
        except (ValueError, OSError):
            continue  # an unreadable or malformed lockfile must not hide the others
    return report


def _find_files(base: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name in _FIXED or (name.startswith("requirements") and name.endswith(".txt")):
                found.append(Path(dirpath) / name)
    return found


def _parse(name: str, text: str, rel: str, report: LockfileReport) -> None:
    if name.startswith("requirements"):
        _requirements(text, rel, report)
    else:
        report.dependencies.extend(_FIXED[name](text, rel))


# --- Python ---------------------------------------------------------------


def _uv_lock(text: str, rel: str) -> list[Dependency]:
    out: list[Dependency] = []
    for pkg in tomllib.loads(text).get("package", []):
        source = pkg.get("source") or {}
        if source.get("editable") == "." or source.get("virtual") == ".":
            continue  # the project itself
        registry = source.get("registry")
        public = isinstance(registry, str) and urlparse(registry).hostname == "pypi.org"
        out.append(
            Dependency(
                normalize_pypi(pkg["name"]), str(pkg.get("version", "")), PYPI, rel, public
            )
        )
    return out


def _poetry_lock(text: str, rel: str) -> list[Dependency]:
    out: list[Dependency] = []
    for pkg in tomllib.loads(text).get("package", []):
        source = pkg.get("source")
        if source is None:
            public = True  # no [package.source] means the default PyPI
        else:
            url = str(source.get("url", ""))
            public = source.get("type") == "legacy" and urlparse(url).hostname in _PYPI_HOSTS
        out.append(
            Dependency(
                normalize_pypi(pkg["name"]), str(pkg.get("version", "")), PYPI, rel, public
            )
        )
    return out


def _requirements(text: str, rel: str, report: LockfileReport) -> None:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-") and not line.startswith(("-e ", "-e\t")):
            continue  # -r, -c and index options are not packages
        match = _REQ_PIN.match(re.sub(r"\s+#.*$", "", line))
        if match:
            report.dependencies.append(
                Dependency(normalize_pypi(match.group(1)), match.group(2), PYPI, rel, True)
            )
        else:
            report.unpinned.append(Unpinned(line, rel))


# --- npm ------------------------------------------------------------------


def _package_lock(text: str, rel: str) -> list[Dependency]:
    data = json.loads(text)
    out: list[Dependency] = []
    for key, entry in (data.get("packages") or {}).items():
        if key == "" or not isinstance(entry, dict) or "node_modules/" not in key:
            continue  # "" is the root project; other keys are workspace folders
        name = entry.get("name") or key.rsplit("node_modules/", 1)[1]
        resolved = entry.get("resolved")
        public = (
            not entry.get("link")
            and isinstance(resolved, str)
            and urlparse(resolved).hostname == "registry.npmjs.org"
        )
        out.append(Dependency(name, str(entry.get("version", "")), NPM, rel, bool(public)))
    return out


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _split_spec(spec: str) -> tuple[str, str] | None:
    """Split `name@rest`, allowing a leading `@scope/`."""
    at = spec.find("@", 1)
    if at <= 0:
        return None
    return spec[:at], spec[at + 1 :]


def _pnpm_key(key: str) -> tuple[str, str] | None:
    key = re.sub(r"\(.*$", "", key.lstrip("/"))  # peer suffix: name@1.0.0(react@18)
    split = _split_spec(key)
    if split:
        name, version = split
    else:  # lockfile v5: /name/1.0.0 or /@scope/name/1.0.0_peer
        name, _, version = key.rpartition("/")
        if not name:
            return None
    return name, version.split("_", 1)[0] if re.match(r"^\d", version) else version


def _pnpm_lock(text: str, rel: str) -> list[Dependency]:
    entries: list[tuple[str, str, str]] = []  # name, version, resolution line
    current: list[str] | None = None
    in_packages = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith(" "):
            in_packages = raw.rstrip() == "packages:"
            current = None
            continue
        if not in_packages:
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 2 and stripped.endswith(":"):
            parsed = _pnpm_key(_unquote(stripped[:-1]))
            current = [parsed[0], parsed[1], ""] if parsed else None
            if current:
                entries.append((current[0], current[1], ""))
        elif indent == 4 and stripped.startswith("resolution:") and current and entries:
            name, version, _ = entries[-1]
            entries[-1] = (name, version, stripped)
    out: list[Dependency] = []
    seen: set[tuple[str, str]] = set()
    for name, version, resolution in entries:
        if (name, version) in seen:
            continue
        seen.add((name, version))
        private = version.startswith(("file:", "link:")) or any(
            marker in resolution for marker in ("directory:", "repo:", "type: git")
        )
        tarball = re.search(r"tarball:\s*['\"]?([^\s,'\"}]+)", resolution)
        if tarball and urlparse(tarball.group(1)).hostname not in _NPM_HOSTS:
            private = True
        out.append(Dependency(name, version, NPM, rel, not private))
    return out


def _yarn_lock(text: str, rel: str) -> list[Dependency]:
    out: list[Dependency] = []
    seen: set[tuple[str, str]] = set()
    name = version = resolved = resolution = None

    def flush() -> None:
        if resolution and resolution.endswith("@workspace:."):
            return  # berry's entry for the project itself
        if name and version and (name, version) not in seen:
            seen.add((name, version))
            if resolution is not None:  # berry
                public = "@npm:" in resolution
            else:
                public = bool(resolved) and urlparse(resolved).hostname in _NPM_HOSTS
            out.append(Dependency(name, version, NPM, rel, bool(public)))

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith(" "):
            flush()
            name = version = resolved = resolution = None
            header = raw.rstrip()
            if header.endswith(":") and not header.startswith("__metadata"):
                first = _unquote(header[:-1].split(",")[0])
                split = _split_spec(first)
                name = split[0] if split else None
            continue
        if len(raw) - len(raw.lstrip()) != 2:
            continue  # nested dependency lists
        key, _, value = raw.strip().partition(" ")
        key = key.rstrip(":")
        value = _unquote(value.strip())
        if key == "version":
            version = value
        elif key == "resolved":
            resolved = value
        elif key == "resolution":
            resolution = value
    flush()
    return out


_FIXED = {
    "uv.lock": _uv_lock,
    "poetry.lock": _poetry_lock,
    "package-lock.json": _package_lock,
    "pnpm-lock.yaml": _pnpm_lock,
    "yarn.lock": _yarn_lock,
}
