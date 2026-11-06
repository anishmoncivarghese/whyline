"""Check what each package would actually publish: built wheels and sdists, the
`npm pack` file list, and the Docker build context. Every file is scanned for
secrets and for names that should never ship (see `check_deny`).

Findings use `path` of the form `<artifact>:<member>`. A build that fails is one
warn-level finding, not an error, so a missing tool never blocks a release check.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Callable
from pathlib import Path

from whyline.security.findings import Finding, make_fingerprint
from whyline.security.rules import RuleSet
from whyline.security.secrets import (
    _BINARY_PROBE,
    MAX_FILE_BYTES,
    check_deny,
    scan_text,
)

_WARN = "medium"
_BUILD_DIR = ".git/whyline-release/build"


def check(root: Path, *, run: Callable = subprocess.run, rules: RuleSet | None = None) -> list[Finding]:
    """`contents` findings for every package kind found under `root`."""
    root = Path(root)
    if rules is None:
        from whyline.security.rules import load_rules

        rules = load_rules()
    found: list[Finding] = []
    if _is_python_project(root):
        found.extend(_check_python(root, run, rules))
    if _is_npm_project(root):
        found.extend(_check_npm(root, run, rules))
    if (root / "Dockerfile").is_file():
        found.extend(_check_docker(root, run, rules))
    return found


# --- shared -------------------------------------------------------------------


def _scan_member(artifact: str, member: str, data: bytes, rules: RuleSet) -> list[Finding]:
    """Name check always; the text scan only for non-binary files under the size cap."""
    binary = b"\0" in data[:_BINARY_PROBE]
    text = "" if binary or len(data) > MAX_FILE_BYTES else data.decode("utf-8", errors="replace")
    found = check_deny(member, text)
    if text:
        found.extend(scan_text(text, member, rules))
    return [dataclasses.replace(f, path=f"{artifact}:{member}") for f in found]


def _build_failed(kind: str, detail: str) -> Finding:
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    last = lines[-1] if lines else "no output"
    return Finding(
        kind="contents",
        rule="build-failed",
        title=f"could not build {kind}: {last}",
        severity=_WARN,
        path=kind,
        fingerprint=make_fingerprint("contents", "build-failed", kind),
        fix_hint=f"Fix the {kind} build so its contents can be checked.",
    )


def _call(run: Callable, args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        done = run(args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", f"{args[0]} could not run ({type(exc).__name__})"
    return getattr(done, "returncode", 1), done.stdout or "", done.stderr or ""


def _read_tree_file(root: Path, rel: str) -> bytes | None:
    path = root / rel
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return b"" if path.is_file() else None
        return path.read_bytes()
    except OSError:
        return None


# --- python -------------------------------------------------------------------


def _is_python_project(root: Path) -> bool:
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return "project" in data


def _check_python(root: Path, run: Callable, rules: RuleSet) -> list[Finding]:
    base = root / _BUILD_DIR
    try:
        base.mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(dir=base))
    except OSError:
        out = Path(tempfile.mkdtemp())
    try:
        code, stdout, stderr = _call(run, ["uv", "build", "--out-dir", str(out)], root)
        if code != 0:
            return [_build_failed("python package", stderr or stdout)]
        found: list[Finding] = []
        for dist in sorted(out.iterdir()):
            try:
                if dist.suffix == ".whl":
                    found.extend(_scan_wheel(dist, rules))
                elif dist.name.endswith(".tar.gz"):
                    found.extend(_scan_sdist(dist, rules))
            except (OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
                found.append(_build_failed("python package", f"{dist.name} unreadable ({type(exc).__name__})"))
        return found
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _scan_wheel(path: Path, rules: RuleSet) -> list[Finding]:
    found: list[Finding] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = b"" if info.file_size > MAX_FILE_BYTES else archive.read(info)
            found.extend(_scan_member(path.name, info.filename, data, rules))
    return found


def _scan_sdist(path: Path, rules: RuleSet) -> list[Finding]:
    found: list[Finding] = []
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            data = b"" if handle is None or member.size > MAX_FILE_BYTES else handle.read()
            found.extend(_scan_member(path.name, member.name, data, rules))
    return found


# --- npm ----------------------------------------------------------------------


def _is_npm_project(root: Path) -> bool:
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and not data.get("private")


def _check_npm(root: Path, run: Callable, rules: RuleSet) -> list[Finding]:
    code, stdout, stderr = _call(run, ["npm", "pack", "--dry-run", "--json"], root)
    if code != 0:
        return [_build_failed("npm package", stderr or stdout)]
    try:
        packed = json.loads(stdout)
        entries = packed if isinstance(packed, list) else [packed]
        names = [
            str(item["path"]) for entry in entries for item in entry.get("files", [])
        ]
    except (ValueError, AttributeError, KeyError, TypeError):
        return [_build_failed("npm package", "npm pack gave unreadable output")]
    found: list[Finding] = []
    for name in names:
        data = _read_tree_file(root, name)
        found.extend(_scan_member("npm", name, data if data is not None else b"", rules))
    return found


# --- docker -------------------------------------------------------------------


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """One .dockerignore pattern as a regex over a posix path from the context root.

    `*` stays inside a path segment, `**` crosses them, and a match on a directory
    also covers everything below it.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        out.append("[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch))
        i += 1
    return re.compile("".join(out) + r"(?:/.*)?\Z", re.DOTALL)


def parse_dockerignore(text: str) -> list[tuple[bool, re.Pattern[str]]]:
    """(negated, regex) per pattern line, in order."""
    patterns: list[tuple[bool, re.Pattern[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:].strip()
        line = line.lstrip("/").rstrip("/")
        if line:
            patterns.append((negated, _pattern_regex(line)))
    return patterns


def dockerignored(path: str, patterns: list[tuple[bool, re.Pattern[str]]]) -> bool:
    """True if the last matching pattern excludes `path`."""
    ignored = False
    for negated, regex in patterns:
        if regex.match(path):
            ignored = not negated
    return ignored


def docker_context(root: Path, run: Callable = subprocess.run) -> list[str] | None:
    """Files a `docker build .` would send, or None if git could not list them."""
    code, stdout, _ = _call(
        run,
        ["git", "-c", "core.quotepath=off", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        root,
    )
    if code != 0:
        return None
    names = sorted({name for name in stdout.split("\0") if name})
    try:
        patterns = parse_dockerignore((root / ".dockerignore").read_text(encoding="utf-8"))
    except OSError:
        return names
    return [name for name in names if not dockerignored(name, patterns)]


def _check_docker(root: Path, run: Callable, rules: RuleSet) -> list[Finding]:
    found: list[Finding] = []
    if not (root / ".dockerignore").is_file():
        found.append(
            Finding(
                kind="contents",
                rule="no-dockerignore",
                title="Dockerfile has no .dockerignore, so the whole repository is sent as build context",
                severity=_WARN,
                path="docker:.dockerignore",
                fingerprint=make_fingerprint("contents", "no-dockerignore", "docker"),
                fix_hint="Add a .dockerignore that excludes .git, .env files and local state.",
            )
        )
    names = docker_context(root, run)
    if names is None:
        found.append(_build_failed("docker context", "git ls-files failed"))
        return found
    for name in names:
        data = _read_tree_file(root, name)
        if data is not None:
            found.extend(_scan_member("docker", name, data, rules))
    return found
