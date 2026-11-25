"""Resolve: what is wrong with a failed Ready check and what can be done about it.

`explain` reads the facts itself, with git and the registries, and uses no model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whyline.release import config as release_config
from whyline.release import version as release_version
from whyline.release.config import ReleaseConfig
from whyline.release.ready import Fetch, ReadyItem, Run, _dirty_paths, _git, _is_pending

MAX_OPTIONS = 4
MAX_FILES = 20
_NEXT_TRIES = 20
_SETUP_SUFFIXES = ("-workflow", "-name", "-tap", "-secrets")


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    kind: str  # run, open, copy, version, conflicts, recheck
    needs: str = ""  # "" or "message"
    recommended: bool = False


@dataclass(frozen=True)
class Resolution:
    key: str
    title: str
    facts: tuple[str, ...] = ()
    options: tuple[Option, ...] = ()


Get = Callable[[str], int]


def _cant(what: str) -> str:
    return f"couldn't read {what}"


def _git_raw(run: Run, root: Path, *args: str) -> str | None:
    """Stdout of a git call; None when it fails or cannot run."""
    try:
        res = _git(run, root, *args)
    except Exception:  # noqa: BLE001 - a fact that can't be read is reported, not raised
        return None
    if getattr(res, "returncode", 1) != 0:
        return None
    return getattr(res, "stdout", "") or ""


def _git_out(run: Run, root: Path, *args: str) -> str | None:
    out = _git_raw(run, root, *args)
    return None if out is None else out.strip()


def _count(run: Run, root: Path, spec: str) -> int | None:
    out = _git_out(run, root, "rev-list", "--count", spec)
    try:
        return int(out) if out is not None else None
    except ValueError:
        return None


def _capped(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_FILES:
        return lines
    return [*lines[:MAX_FILES], f"and {len(lines) - MAX_FILES} more"]


def _plural(n: int, word: str = "commit") -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _opts(*options: Option) -> tuple[Option, ...]:
    return options[:MAX_OPTIONS]


# --- clean ------------------------------------------------------------------

def _state_word(code: str) -> str:
    if code == "??":
        return "new"
    if "D" in code:
        return "deleted"
    if "A" in code:
        return "new"
    return "changed"


def _clean(root: Path, cfg: ReleaseConfig, item: ReadyItem, run: Run) -> Resolution:
    out = _git_raw(run, root, "status", "--porcelain", "--untracked-files=all")
    open_it = Option("open-files", "Open the changed files", "open")
    if out is None:
        return Resolution(item.key, item.text, (_cant("the changed files"),))
    try:
        allowed = [p.as_posix() for p in release_config.pending(root)]
    except Exception:  # noqa: BLE001
        allowed = []
    rows: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        paths = _dirty_paths(line)
        if not paths or _is_pending(paths[0], allowed):
            continue
        rows.append(f"{paths[0]} ({_state_word(line[:2])})")
    if not rows:
        return Resolution(item.key, item.text, ("no changed files found",), _opts(open_it))
    return Resolution(
        item.key, item.text, tuple(_capped(rows)),
        _opts(Option("commit", "Commit them", "run", needs="message", recommended=True),
              Option("stash", "Stash them", "run"),
              open_it))


# --- synced -----------------------------------------------------------------

def _synced(root: Path, cfg: ReleaseConfig, item: ReadyItem, run: Run,
            fetch: Fetch) -> Resolution:
    branch = cfg.branch
    facts: list[str] = []
    try:
        fetch(root, branch)
    except Exception:  # noqa: BLE001
        return Resolution(item.key, item.text, (_cant(f"origin/{branch}"),))
    current = _git_out(run, root, "rev-parse", "--abbrev-ref", "HEAD")
    if current is None:
        return Resolution(item.key, item.text, (_cant("the current branch"),))
    behind = _count(run, root, f"HEAD..origin/{branch}")
    if behind is None:
        return Resolution(item.key, item.text, (_cant(f"origin/{branch}"),))

    if current in ("", "HEAD", branch):
        ahead = _count(run, root, f"origin/{branch}..HEAD")
        if ahead is None:
            return Resolution(item.key, item.text, (_cant(f"origin/{branch}"),))
        if behind and ahead:
            facts.append(f"this branch and origin/{branch} have both moved")
            return Resolution(item.key, item.text, tuple(facts))
        facts.append(f"{_plural(behind)} behind origin/{branch}")
        options = (_opts(Option("pull", f"Pull origin/{branch}", "run", recommended=True))
                   if behind else ())
        return Resolution(item.key, item.text, tuple(facts), options)

    facts.append(f"{_plural(behind)} behind origin/{branch}")
    conflicts = _trial(run, root, branch)
    if conflicts is None:
        facts.append(_cant("whether bringing it in would conflict"))
        return Resolution(item.key, item.text, tuple(facts))
    if conflicts:
        facts.append("bringing it in would conflict in:")
        facts.extend(_capped(conflicts))
        return Resolution(item.key, item.text, tuple(facts),
                          _opts(Option("conflicts", "Settle the conflicts", "conflicts",
                                       recommended=True)))
    facts.append("bringing it in would not conflict")
    return Resolution(item.key, item.text, tuple(facts),
                      _opts(Option("bring", f"Bring in {branch}", "run", recommended=True)))


def _trial(run: Run, root: Path, branch: str) -> list[str] | None:
    from whyline.release import source

    try:
        return source.trial_merge(root, branch, run=run)
    except Exception:  # noqa: BLE001
        return None


# --- taken versions ---------------------------------------------------------

def _pypi_taken(root: Path, version: str, get: Get) -> bool | None:
    from whyline.release.targets import pypi

    name = pypi.project_name(root)
    if not name:
        return False
    try:
        status = get(pypi._version_url(name, version))
    except Exception:  # noqa: BLE001
        return None
    return True if status == 200 else False if status == 404 else None


def _npm_taken(root: Path, version: str, get: Get) -> bool | None:
    from whyline.release.targets import npm

    name, private = npm.package_info(root)
    if not name or private:
        return False
    try:
        status = get(npm._version_url(name, version))
    except Exception:  # noqa: BLE001
        return None
    return True if status == 200 else False if status == 404 else None


def _next_free(root: Path, cfg: ReleaseConfig, version: str, run: Run,
               get: Get) -> tuple[str | None, list[str]]:
    """The next patch version free as a tag and on each switched-on registry."""
    unread: list[str] = []
    try:
        candidate = release_version.bump(version, "patch")
    except Exception:  # noqa: BLE001 - pre-release suffix: no patch bump
        return None, [_cant("the next version")]
    for _ in range(_NEXT_TRIES):
        taken = release_version.released(root, candidate, run=run)
        if not taken:
            state = _pypi_taken(root, candidate, get)
            if state is None:
                unread.append(_cant("PyPI"))
                return None, unread
            taken = state
        if not taken:
            state = _npm_taken(root, candidate, get)
            if state is None:
                unread.append(_cant("npm"))
                return None, unread
            taken = state
        if not taken:
            return candidate, unread
        candidate = release_version.bump(candidate, "patch")
    return None, [_cant("a free version")]


def _taken(root: Path, cfg: ReleaseConfig, version: str, item: ReadyItem, run: Run,
           get: Get) -> Resolution:
    facts = [item.text]
    free, unread = _next_free(root, cfg, version, run, get)
    facts.extend(unread)
    if free is None:
        return Resolution(item.key, item.text, tuple(facts))
    return Resolution(item.key, item.text, tuple(facts),
                      _opts(Option(f"version-{free}", f"Use {free}", "version",
                                   recommended=True)))


# --- relay ------------------------------------------------------------------

def _relay(root: Path, item: ReadyItem) -> Resolution:
    paused = "paused" in item.text.lower()
    label = "Open the relay's Resolve" if paused else "Open the relay"
    option = Option("open-relay-resolve" if paused else "open-relay", label, "open",
                    recommended=True)
    try:
        from whyline_relay import state as relay_state

        saved = relay_state.load(root)
    except Exception:  # noqa: BLE001
        saved = None
    if saved is None:
        return Resolution(item.key, item.text, (_cant("the relay's state"),), _opts(option))
    facts = [f"plan {saved.plan}", f"task {saved.task_id}"]
    if paused and saved.paused_reason:
        facts.append(f"paused: {saved.paused_reason}")
    return Resolution(item.key, item.text, tuple(facts), _opts(option))


# --- the rest ---------------------------------------------------------------

def _setup_section(key: str) -> str:
    if key in ("gh-auth", "origin"):
        return "github"
    return key.rsplit("-", 1)[0]


def _generic(item: ReadyItem) -> Resolution:
    facts = tuple(line for line in (item.text, item.fix) if line)
    return Resolution(item.key, item.text, facts)


def explain(root: Path | str, cfg: ReleaseConfig, version: str, item: ReadyItem, *,
            run: Run, fetch: Fetch, get: Get | None = None) -> Resolution:
    try:
        return _explain(Path(root), cfg, version, item, run, fetch, get)
    except Exception:  # noqa: BLE001 - explain never raises
        return Resolution(item.key, item.text, (_cant(item.key),))


def _explain(root: Path, cfg: ReleaseConfig, version: str, item: ReadyItem, run: Run,
             fetch: Fetch, get: Get | None) -> Resolution:
    key = item.key
    if item.text.startswith(("could not reach", "could not check")):
        return Resolution(key, item.text, (item.text,),
                          _opts(Option("recheck", "Check again", "recheck", recommended=True)))
    if item.ok:
        return Resolution(key, item.text, (item.text,))
    if key == "clean":
        return _clean(root, cfg, item, run)
    if key == "synced":
        return _synced(root, cfg, item, run, fetch)
    if key in ("tag", "pypi-version", "npm-version"):
        taken = ("exists" in item.text if key == "tag" else "already on" in item.text)
        if taken:
            from whyline.release.targets.pypi import http_status

            return _taken(root, cfg, version, item, run, get or http_status)
        return _generic(item)
    if key == "relay":
        return _relay(root, item)
    if key in ("gh-auth", "origin") or key.endswith(_SETUP_SUFFIXES):
        section = _setup_section(key)
        facts = tuple(line for line in (item.text, item.fix) if line)
        return Resolution(key, item.text, facts,
                          _opts(Option(f"open-setup-{section}", "Open Set up", "open",
                                       recommended=True)))
    if key in ("git", "gh"):
        facts = tuple(line for line in (item.text, item.fix) if line)
        options = (_opts(Option(f"copy-{key}-install", "Copy the install command", "copy",
                                recommended=True)) if item.fix else ())
        return Resolution(key, item.text, facts, options)
    if key in ("security", "security-history"):
        return Resolution(key, item.text, (item.text,),
                          _opts(Option("open-security", "Open Security", "open",
                                       recommended=True)))
    return _generic(item)
