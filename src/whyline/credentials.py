"""Named credentials for agent tools. Metadata (never the value) lives in
~/.whyline/credentials.toml (0600); the secret lives in the macOS Keychain or
the Linux Secret Service, and is only ever passed on stdin, never in argv."""
from __future__ import annotations

import base64
import json
import os
import platform
import re
import shutil
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "whyline-cred"
KINDS = ("bearer", "header", "basic", "query", "env")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_ORIGIN = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?$")


class Locked(RuntimeError):
    """No secure store is available, or it refused the request."""


@dataclass(frozen=True)
class Credential:
    name: str
    kind: str
    header_name: str = ""
    query_param: str = ""
    origins: tuple[str, ...] = ()
    created: str = ""
    last_used: str = ""
    last_tested: str = ""


def _file() -> Path:
    return Path.home() / ".whyline" / "credentials.toml"


def _validate(cred: Credential) -> None:
    if not _NAME.match(cred.name):
        raise ValueError("a credential name is lowercase letters, digits and hyphens")
    if cred.kind not in KINDS:
        raise ValueError(f"credential kind must be one of {', '.join(KINDS)}")
    if cred.kind == "env" and cred.origins:
        raise ValueError("an env credential has no origins")
    for origin in cred.origins:
        if not _ORIGIN.match(origin):
            raise ValueError(f"origin {origin!r} must look like https://host[:port]")


def _load() -> dict[str, Credential]:
    try:
        raw = tomllib.loads(_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}
    found = {}
    for name, entry in raw.get("credentials", {}).items():
        found[name] = Credential(
            name=name,
            kind=str(entry.get("kind", "bearer")),
            header_name=str(entry.get("header_name", "")),
            query_param=str(entry.get("query_param", "")),
            origins=tuple(str(o) for o in entry.get("origins", [])),
            created=str(entry.get("created", "")),
            last_used=str(entry.get("last_used", "")),
            last_tested=str(entry.get("last_tested", "")),
        )
    return found


def _store(creds: dict[str, Credential]) -> None:
    lines: list[str] = []
    for name in sorted(creds):
        data = asdict(creds[name])
        data.pop("name")
        lines.append(f"[credentials.{name}]")
        for key, val in data.items():
            lines.append(f"{key} = {json.dumps(list(val) if isinstance(val, tuple) else val)}")
        lines.append("")
    target = _file()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    if os.name != "nt":
        os.chmod(target, 0o600)


def list_all() -> list[Credential]:
    return [c for _, c in sorted(_load().items())]


def get(name: str) -> Credential | None:
    return _load().get(name)


def _backend(which=shutil.which, system: str | None = None) -> str:
    system = system or platform.system()
    if system == "Darwin" and which("security"):
        return "mac"
    if system == "Linux" and which("secret-tool"):
        return "linux"
    raise Locked("no secure credential store on this system")


def available(*, which=shutil.which, system: str | None = None) -> tuple[bool, str]:
    try:
        _backend(which, system)
    except Locked as error:
        return False, str(error)
    return True, ""


def security_quote(value: str) -> str:
    """Quote ``value`` for one line of ``security -i``. A line break can't be
    carried in one command line, so it is refused rather than mangled."""
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError("a secret can't contain a line break")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _put(name: str, value: str, run, which, system) -> None:
    kind = _backend(which, system)
    if kind == "mac":
        result = run(
            ["security", "-i"],
            input=f"add-generic-password -U -s {SERVICE} -a {name} -w {security_quote(value)}\n",
            capture_output=True, text=True,
        )
    else:
        result = run(
            ["secret-tool", "store", f"--label={SERVICE}", "service", SERVICE, "account", name],
            input=value, capture_output=True, text=True,
        )
    if result.returncode != 0:
        raise Locked("the secure credential store refused the secret")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save(cred: Credential, value: str, *, run=subprocess.run, which=shutil.which,
         system: str | None = None) -> None:
    _validate(cred)
    if not value:
        raise ValueError("a credential needs a value")
    _put(cred.name, value, run, which, system)
    creds = _load()
    creds[cred.name] = Credential(**{**asdict(cred), "origins": tuple(cred.origins),
                                     "created": cred.created or _now()})
    _store(creds)


def rotate(name: str, value: str, *, run=subprocess.run, which=shutil.which,
           system: str | None = None) -> None:
    if name not in _load():
        raise KeyError(name)
    if not value:
        raise ValueError("a credential needs a value")
    _put(name, value, run, which, system)


def value(name: str, *, run=subprocess.run, which=shutil.which, system: str | None = None) -> str:
    kind = _backend(which, system)
    if kind == "mac":
        argv = ["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"]
    else:
        argv = ["secret-tool", "lookup", "service", SERVICE, "account", name]
    result = run(argv, capture_output=True, text=True)
    secret = (result.stdout or "").rstrip("\n") if result.returncode == 0 else ""
    if not secret:
        raise Locked(f"no stored value for credential {name!r}")
    return secret


def remove(name: str, *, run=subprocess.run, which=shutil.which,
           system: str | None = None) -> None:
    try:
        kind = _backend(which, system)
    except Locked:
        kind = ""
    if kind == "mac":
        run(["security", "delete-generic-password", "-s", SERVICE, "-a", name],
            capture_output=True, text=True)
    elif kind == "linux":
        run(["secret-tool", "clear", "service", SERVICE, "account", name],
            capture_output=True, text=True)
    creds = _load()
    if creds.pop(name, None) is not None:
        _store(creds)


def redaction_values(names, *, run=subprocess.run, which=shutil.which,
                     system: str | None = None) -> list[str]:
    """Secret values (and base64 for ``basic``) to scrub from outputs."""
    out: list[str] = []
    creds = _load()
    for name in names:
        try:
            secret = value(name, run=run, which=which, system=system)
        except Locked:
            continue
        out.append(secret)
        cred = creds.get(name)
        if cred and cred.kind == "basic":
            out.append(base64.b64encode(secret.encode("utf-8")).decode("ascii"))
    return out
