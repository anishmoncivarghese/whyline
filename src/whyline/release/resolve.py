"""Resolve: what is wrong with a failed Ready check and what can be done about it.

`explain` reads the facts itself, with git and the registries, and uses no model.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
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


# --- running an option ------------------------------------------------------
#
# Nothing below is ever chosen by a model: the argv is built here from the option's id.

LOG_LIMIT = 50
_RUNNABLE = ("commit", "stash", "pull", "bring")
_NEWER_COMMIT = "Something was committed after this; undo it by hand"


@dataclass(frozen=True)
class Preview:
    lines: tuple[str, ...]
    argv: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class Outcome:
    ok: bool
    text: str
    commits: int = 0
    snapshot_id: str = ""
    argv: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class Entry:
    time: str
    key: str
    option: str
    text: str
    commits: int
    result: str  # kept or undone
    snapshot_id: str = ""
    head: str = ""
    ok: bool = True


def _stash_name(head: str, files: list[str]) -> str:
    """Same for the same HEAD and files, so a preview and the apply after it agree."""
    digest = hashlib.sha1("\0".join([head, *files]).encode("utf-8")).hexdigest()[:12]
    return f"whyline-release-{digest}"


class _Recorder:
    """Wraps `run` and remembers every command it was asked to run."""

    def __init__(self, run: Run) -> None:
        self._run = run
        self.argv: list[tuple[str, ...]] = []

    def __call__(self, args, **kw):
        self.argv.append(tuple(args))
        return self._run(args, **kw)


def _listed(root: Path, run: Run) -> list[str] | None:
    """Every changed file Release doesn't itself commit later; None when git can't say."""
    out = _git_raw(run, root, "status", "--porcelain", "--untracked-files=all")
    if out is None:
        return None
    try:
        allowed = [p.as_posix() for p in release_config.pending(root)]
    except Exception:  # noqa: BLE001
        allowed = []
    files: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        paths = _dirty_paths(line)
        if paths and not _is_pending(paths[0], allowed):
            files.append(paths[0])
    return files


def _head(run: Run, root: Path) -> str:
    return _git_out(run, root, "rev-parse", "-q", "--verify", "HEAD") or ""


def _bring_message(cfg: ReleaseConfig, version: str, run: Run, root: Path) -> str:
    here = _git_out(run, root, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    return f"merge: bring {cfg.branch} into {here} for v{version}"


def preview(root: Path | str, cfg: ReleaseConfig, version: str, option: Option, *,
            message: str = "", run: Run) -> Preview:
    """What an option would do, and the git commands it would run. Changes nothing."""
    root = Path(root)
    if option.id not in _RUNNABLE:
        return Preview((option.label,))
    try:
        if option.id in ("commit", "stash"):
            files = _listed(root, run)
            if files is None:
                return Preview((_cant("the changed files"),))
            if option.id == "commit":
                lines = [f"Commit {_plural(len(files), 'file')} with the message: "
                         f"{message or '(type one)'}", *_capped(files)]
                argv = (("git", "add", "-A", "--", *files), ("git", "commit", "-m", message))
            else:
                lines = [f"Stash {_plural(len(files), 'file')}, new files too", *_capped(files)]
                argv = (("git", "stash", "push", "--include-untracked", "-m",
                         _stash_name(_head(run, root), files), "--", *files),)
        elif option.id == "pull":
            lines = [f"Move this branch forward to origin/{cfg.branch}; nothing is rewritten"]
            argv = (("git", "merge", "--ff-only", f"origin/{cfg.branch}"),)
        else:
            lines = [f"Merge origin/{cfg.branch} into this branch, "
                     "then move finished plans to done"]
            argv = (("git", "merge", "--no-ff", f"origin/{cfg.branch}", "-m",
                     _bring_message(cfg, version, run, root)),)
    except Exception:  # noqa: BLE001 - a preview never raises
        return Preview((_cant(option.label),))
    return Preview(tuple(lines), argv)


# --- the record -------------------------------------------------------------

def _log_path(run: Run, root: Path) -> Path:
    out = _git_out(run, root, "rev-parse", "--absolute-git-dir")
    return (Path(out) if out else root / ".git") / "whyline-release" / "resolve.log"


def _append(run: Run, root: Path, entry: Entry) -> None:
    path = _log_path(run, root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.__dict__) + "\n")
    except OSError:
        pass  # the record is best effort; the option itself already ran


def history(root: Path | str, *, run: Run | None = None) -> list[Entry]:
    """The log, newest first, at most 50."""
    from whyline.release.ready import default_run

    root = Path(root)
    try:
        text = _log_path(run or default_run, root).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return []
    names = set(Entry.__dataclass_fields__)
    entries: list[Entry] = []
    for line in text.splitlines():
        try:
            entries.append(Entry(**{k: v for k, v in json.loads(line).items() if k in names}))
        except (ValueError, TypeError, AttributeError):
            continue
    return entries[::-1][:LOG_LIMIT]


def _record(run: Run, root: Path, option_id: str, key: str, text: str, out: Outcome,
            result: str = "kept") -> None:
    _append(run, root, Entry(
        time=datetime.now(timezone.utc).isoformat(timespec="seconds"), key=key,
        option=option_id, text=text, commits=out.commits, result=result,
        snapshot_id=out.snapshot_id, head=_head(run, root), ok=out.ok))


def _note(run: Run, root: Path, option: Option, key: str, out: Outcome, files: list[str]) -> None:
    args = ["whyline", "note", f"Resolve {option.id} for the {key} check: {out.text}"[:200],
            "--because", "Run from Release's Resolve to clear a failed Ready check",
            "--actor", "release", "--role", "release", "--task", f"resolve-{key}"]
    for name in files[:MAX_FILES]:
        args += ["--file", name]
    try:
        run(args, cwd=root)
    except Exception:  # noqa: BLE001 - the note is best effort
        pass


# --- apply and undo ---------------------------------------------------------

def _failed(res, what: str) -> str:
    from whyline.release.ready import _short

    return _short(getattr(res, "stderr", "") or getattr(res, "stdout", "")) or f"{what} failed"


def _fail(res, what: str, snap_id: str) -> Outcome:
    return Outcome(False, _failed(res, what), 0, snap_id)


def apply(root: Path | str, cfg: ReleaseConfig, version: str, option: Option, *,
          message: str = "", run: Run, fetch: Fetch,
          relay_running: Callable[[Path], bool] | None = None,
          fix_run: Run | None = None, key: str = "") -> Outcome:
    """Run one option. `fix_run` is what fixmode's snapshot uses (subprocess.run style)."""
    root = Path(root)
    key = key or option.id
    if option.id not in _RUNNABLE:
        return Outcome(False, "This option isn't run here")
    if option.id == "commit" and not message.strip():
        return Outcome(False, "Type a commit message first")
    rec = _Recorder(run)
    files: list[str] = []
    snap_id = ""
    try:
        if option.id in ("commit", "stash"):
            listed = _listed(root, rec)
            if listed is None:
                return Outcome(False, _cant("the changed files"))
            files = listed
            if not files:
                return Outcome(False, f"There are no changed files to {option.id}")
        if option.id == "commit":
            from whyline.security import secrets

            found = secrets.scan_paths(root, files)
            if found:
                lines = [f"{f.path}:{f.line} {f.title}" for f in found[:MAX_FILES]]
                return Outcome(False, "Stopped, so nothing was committed. A secret may be in:\n"
                               + "\n".join(lines))
        before = _head(rec, root)
        if option.id != "stash":
            from whyline.console import fixmode

            snap_id = fixmode.snapshot(root, run=fix_run or subprocess.run).id
        out = _act(root, cfg, version, option, message, rec, fetch, relay_running, files,
                   snap_id, before)
    except Exception as exc:  # noqa: BLE001 - a failed option is reported, not raised
        out = Outcome(False, str(exc) or "it failed", 0, snap_id)
    out = Outcome(out.ok, out.text, out.commits, out.snapshot_id, tuple(rec.argv))
    _record(run, root, option.id, key, message, out)
    if out.ok and out.commits and option.id in ("commit", "bring"):
        _note(run, root, option, key, out, files)
    return out


def _act(root: Path, cfg: ReleaseConfig, version: str, option: Option, message: str,
         rec: _Recorder, fetch: Fetch, relay_running, files: list[str], snap_id: str,
         before: str) -> Outcome:
    if option.id == "commit":
        res = _git(rec, root, "add", "-A", "--", *files)
        if getattr(res, "returncode", 1) != 0:
            return _fail(res, "git add", snap_id)
        res = _git(rec, root, "commit", "-m", message)
        if getattr(res, "returncode", 1) != 0:
            return _fail(res, "git commit", snap_id)
        return Outcome(True, f"Committed {_plural(len(files), 'file')}", 1, snap_id)
    if option.id == "stash":
        name = _stash_name(before, files)
        res = _git(rec, root, "stash", "push", "--include-untracked", "-m", name, "--", *files)
        if getattr(res, "returncode", 1) != 0:
            return _fail(res, "git stash", snap_id)
        if "No local changes" in (getattr(res, "stdout", "") or ""):
            return Outcome(False, "There were no changes to stash")
        return Outcome(True, f"Stashed {_plural(len(files), 'file')} as {name}. "
                       "Get them back with: git stash pop")
    if option.id == "pull":
        res = _git(rec, root, "merge", "--ff-only", f"origin/{cfg.branch}")
        if getattr(res, "returncode", 1) != 0:
            return _fail(res, "git merge", snap_id)
        summary = f"Moved forward to origin/{cfg.branch}"
    else:
        from whyline.release import source

        extra = {} if relay_running is None else {"relay_running": relay_running}
        try:
            summary = source.bring_in_main(root, cfg, version, run=rec, fetch=fetch, **extra)
        except Exception as exc:  # noqa: BLE001 - a StepError says what to do
            return Outcome(False, str(exc), 0, snap_id)
        summary = summary or f"Brought in {cfg.branch}"
    own = (_count(rec, root, f"{before}..HEAD") or 0) if before else 0
    return Outcome(True, summary, own, snap_id)


def undo(root: Path | str, snapshot_id: str, *, run: Run, fix_run: Run | None = None) -> str:
    """Put things back as they were before an option; refuses when later commits exist."""
    from whyline.console import fixmode

    root = Path(root)
    fix = fix_run or subprocess.run
    mine = [e for e in history(root, run=run) if e.snapshot_id == snapshot_id]
    if not mine:
        return "There is nothing recorded to undo"
    last = mine[0]
    if last.result == "undone":
        return "That was already undone"
    if last.head and _head(run, root) != last.head:
        return _NEWER_COMMIT
    try:
        snap = fixmode.load_snapshot(root, snapshot_id, run=fix)
        if snap is None:
            return "That snapshot is gone, so it can't be undone"
        if snap.head and _head(run, root) != snap.head:
            if fixmode._branch(root, fix) != snap.branch:  # noqa: SLF001
                return ("Nothing was undone: the branch changed since the snapshot "
                        f"({snap.branch or 'detached'}); switch back first")
            res = _git(run, root, "reset", "-q", snap.head)
            if getattr(res, "returncode", 1) != 0:
                return _failed(res, "git reset")
        restored = fixmode.undo(root, snap, run=fix)
    except Exception as exc:  # noqa: BLE001
        return f"Nothing was undone: {exc}"
    _record(run, root, last.option, last.key, last.text,
            Outcome(True, "", last.commits, snapshot_id), "undone")
    return f"Undone: {_plural(len(restored), 'file')} put back as they were"
