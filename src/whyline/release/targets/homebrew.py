"""The Homebrew release target: a formula in a tap repository that is bumped to the new
tag's tarball (url + sha256) and pushed, then a check that the remote formula has it."""

from __future__ import annotations

import base64
import hashlib
import re
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from whyline.release import targets
from whyline.release.config import ReleaseConfig
from whyline.release.engine import Step
from whyline.release.github import StepError
from whyline.release.ready import Fetch, ReadyItem, Run
from whyline.release.targets.pypi import _owner_repo, project_name

KEY = "homebrew"
TAP_PREFIX = "homebrew-"
DEFAULT_TAP_NAME = "tap"
CLONE_DIR = Path(".git") / "whyline-release" / "tap"
DOWNLOAD_TIMEOUT = 60.0
BREW_TIMEOUT = 600.0
GIT_TIMEOUT = 120.0
NO_BREW_NOTE = ("brew is not installed, so the formula's resource blocks were not updated; "
                "run brew update-python-resources on the formula")
PUBLIC_NOTE = "A tap must be a public repository so brew tap works without credentials."
TREE_LIMIT = 100
MANIFESTS = ("pyproject.toml", "setup.cfg", "setup.py", "requirements.txt", "uv.lock")
MANIFEST_CHARS = 3000

_URL_LINE = re.compile(r'^(  url\s+)"[^"\n]*"', re.MULTILINE)
_SHA_LINE = re.compile(r'^(  sha256\s+)"[^"\n]*"', re.MULTILINE)

AskAgent = Callable[[str], str]
# download(url) -> the response body; raises OSError when it cannot be fetched
Download = Callable[[str], bytes]
Which = Callable[[str], str | None]


def http_download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "whyline-release"})
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:  # noqa: S310 - https URL
            return response.read()
    except urllib.error.URLError as error:
        raise OSError(str(getattr(error, "reason", error))) from error


def tap_repo(root: Path, cfg: ReleaseConfig, run: Run) -> str:
    """The tap as `<owner>/homebrew-<name>`: configured, else `<owner>/homebrew-tap`."""
    tap = cfg.targets.homebrew_options.tap.strip()
    if not tap:
        tap = _owner_repo(Path(root), run).partition("/")[0] + "/"
    owner, _, name = tap.partition("/")
    owner = owner.strip()
    if not owner:
        return ""
    name = name.strip() or DEFAULT_TAP_NAME
    if not name.startswith(TAP_PREFIX):
        name = TAP_PREFIX + name
    return f"{owner}/{name}"


def brew_tap_name(repo: str) -> str:
    """`octo/homebrew-tap` -> `octo/tap`, what users type after `brew tap`."""
    owner, _, name = repo.partition("/")
    return f"{owner}/{name[len(TAP_PREFIX):] if name.startswith(TAP_PREFIX) else name}"


def formula_name(root: Path, cfg: ReleaseConfig, run: Run) -> str:
    name = cfg.targets.homebrew_options.formula.strip()
    if name:
        return name
    name = project_name(Path(root))
    if name:
        return name
    return _owner_repo(Path(root), run).partition("/")[2]


def install_lines(root: Path, cfg: ReleaseConfig, run: Run) -> list[str]:
    repo, formula = tap_repo(root, cfg, run), formula_name(root, cfg, run)
    if not repo or not formula:
        return []
    return [f"brew tap {brew_tap_name(repo)}", f"brew install {formula}"]


def source_url(root: Path, version: str, run: Run) -> str:
    return f"https://github.com/{_owner_repo(Path(root), run)}/archive/refs/tags/v{version}.tar.gz"


def create_tap(owner: str, name: str, *, run: Run) -> str:
    """Create `<owner>/homebrew-<name>` as a public repository; returns its full name."""
    owner, name = owner.strip(), name.strip()
    if not owner or not name:
        raise StepError("Enter the owner and the tap name")
    if name.startswith(TAP_PREFIX):
        name = name[len(TAP_PREFIX):]
    repo = f"{owner}/{TAP_PREFIX}{name}"
    proc = run(["gh", "repo", "create", repo, "--public"])
    if getattr(proc, "returncode", 1) != 0:
        detail = (str(getattr(proc, "stderr", "") or getattr(proc, "stdout", ""))
                  .strip().splitlines() or ["no output"])[-1]
        raise StepError(f"Could not create {repo}: {detail}")
    return repo


def replace_source(text: str, url: str, sha256: str) -> str:
    """Swap the formula's own `url` and `sha256` lines; resource blocks (indented
    deeper) and everything else stay as they were."""
    if not _URL_LINE.search(text) or not _SHA_LINE.search(text):
        raise StepError("The formula has no top-level url and sha256 lines")
    text = _URL_LINE.sub(lambda m: f'{m.group(1)}"{url}"', text, count=1)
    return _SHA_LINE.sub(lambda m: f'{m.group(1)}"{sha256}"', text, count=1)


def _stdout(proc: object) -> str:
    return str(getattr(proc, "stdout", "") or "")


def _ok(proc: object) -> bool:
    return getattr(proc, "returncode", 1) == 0


def _fail(proc: object) -> str:
    lines = (str(getattr(proc, "stderr", "") or _stdout(proc))).strip().splitlines()
    return lines[-1] if lines else "no output"


def remote_formula(repo: str, formula: str, run: Run) -> str | None:
    """The formula's text on the remote, or None when it cannot be read."""
    try:
        proc = run(["gh", "api", f"repos/{repo}/contents/Formula/{formula}.rb",
                    "--jq", ".content"])
    except OSError:
        return None
    if not _ok(proc):
        return None
    try:
        return base64.b64decode(_stdout(proc).strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _git(clone: Path, run: Run, *args: str) -> object:
    return run(["git", *args], cwd=clone, timeout=GIT_TIMEOUT)


def _recover(clone: Path, run: Run) -> bool:
    """Throw away local edits and unpushed commits in a reused clone. False when the
    clone cannot be reset to its upstream (an empty tap, say), so it is recreated."""
    for args in (("fetch", "origin"), ("reset", "--hard", "@{u}"), ("clean", "-fd")):
        if not _ok(_git(clone, run, *args)):
            return False
    return True


def sync_clone(root: Path, repo: str, *, run: Run) -> Path:
    """The scratch clone of the tap under .git/whyline-release/tap: cloned the first
    time; after that reset to origin and `git pull`, so a failed earlier run cannot
    leave it dirty or ahead."""
    clone = Path(root) / CLONE_DIR
    if (clone / ".git").is_dir() and _recover(clone, run):
        proc = _git(clone, run, "pull", "--ff-only")
        if not _ok(proc):
            raise StepError(f"git pull in the tap clone failed: {_fail(proc)}")
        return clone
    if clone.exists():
        shutil.rmtree(clone)
    clone.parent.mkdir(parents=True, exist_ok=True)
    proc = run(["gh", "repo", "clone", repo, str(clone)], cwd=Path(root), timeout=GIT_TIMEOUT)
    if not _ok(proc):
        raise StepError(f"Could not clone {repo}: {_fail(proc)}")
    return clone


def _commit_and_push(clone: Path, formula: str, version: str, run: Run) -> None:
    path = f"Formula/{formula}.rb"
    for args in (("add", path), ("commit", "-m", f"{formula} {version}"), ("push", "-u", "origin", "HEAD")):
        proc = _git(clone, run, *args)
        if not _ok(proc):
            raise StepError(f"git {args[0]} failed: {_fail(proc)}")


def _tree(root: Path) -> str:
    names = sorted(p.name for p in Path(root).iterdir() if not p.name.startswith("."))
    return "\n".join(names[:TREE_LIMIT])


def draft_formula(root: Path, *, ask_agent: AskAgent, formula: str = "", url: str = "") -> str:
    """Ask the main agent for a first formula. Returns text only; nothing is written."""
    root = Path(root)
    cli = formula or project_name(root) or root.name
    parts = ["Write a Homebrew formula for this project. For a Python project use a "
             "`Language::Python::Virtualenv` formula (include `resource` blocks for the "
             "dependencies if you can work them out; `brew update-python-resources` will "
             "refresh them). The test block must run the command-line tool with "
             f"`--version` (the tool is `{cli}` unless the manifests say otherwise). "
             "Use a `desc`, `homepage`, `license` and a top-level `url` and `sha256` line "
             "with two-space indentation"
             + (f"; the url is {url}" if url else "")
             + ". Answer with only the Ruby file contents, no commentary. Do not run "
             "commands and do not change files.", "", "Files:", _tree(root)]
    for name in MANIFESTS:
        path = root / name
        if path.is_file():
            try:
                body = path.read_text(encoding="utf-8")[:MANIFEST_CHARS]
            except (OSError, UnicodeDecodeError):
                continue
            parts += ["", f"--- {name} ---", body]
    text = (ask_agent("\n".join(parts)) or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        raise StepError("The agent returned no formula")
    return text + "\n"


def push_draft(root: Path, repo: str, formula: str, text: str, *, run: Run) -> None:
    """Commit a reviewed draft as Formula/<formula>.rb in the tap and push it."""
    if not text.strip():
        raise StepError("There is no draft to push")
    clone = sync_clone(root, repo, run=run)
    path = clone / "Formula" / f"{formula}.rb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    _commit_and_push(clone, formula, "first formula", run)


class HomebrewTarget:
    key = KEY
    title = "Homebrew"

    def __init__(self, download: Download | None = None, which: Which = shutil.which) -> None:
        self._download = download or http_download
        self._which = which
        self.warnings: list[str] = []

    def ready_items(self, root: Path, cfg: ReleaseConfig, version: str, *,
                    run: Run, fetch: Fetch) -> list[ReadyItem]:
        root = Path(root)
        repo, formula = tap_repo(root, cfg, run), formula_name(root, cfg, run)
        if not repo or not formula:
            return [ReadyItem("homebrew-tap", False, "No tap or formula name",
                              "Set up Homebrew and enter the tap and formula")]
        exists = self._succeeds(run, ["gh", "repo", "view", repo], root)
        items = [ReadyItem("homebrew-tap", exists,
                           f"Tap {repo} exists" if exists else f"Tap {repo} not found",
                           "" if exists else "Set up Homebrew and choose Create tap")]
        if not exists:
            return items
        has_formula = remote_formula(repo, formula, run) is not None
        items.append(ReadyItem(
            "homebrew-formula", has_formula,
            f"Formula/{formula}.rb is in the tap" if has_formula
            else f"Formula/{formula}.rb is not in the tap",
            "" if has_formula else "Set up Homebrew and choose Draft formula"))
        can_push = self._can_push(run, repo, root)
        items.append(ReadyItem(
            "homebrew-push", can_push,
            f"You can push to {repo}" if can_push else f"You cannot push to {repo}",
            "" if can_push else "Sign in to gh with an account that owns the tap"))
        return items

    @staticmethod
    def _succeeds(run: Run, args: list[str], root: Path) -> bool:
        try:
            return _ok(run(args, cwd=root))
        except OSError:
            return False

    @staticmethod
    def _can_push(run: Run, repo: str, root: Path) -> bool:
        try:
            proc = run(["gh", "api", f"repos/{repo}", "--jq", ".permissions.push"], cwd=root)
        except OSError:
            return False
        return _ok(proc) and _stdout(proc).strip() == "true"

    def steps(self, root: Path, cfg: ReleaseConfig, version: str, *,
              run: Run, fetch: Fetch) -> list[Step]:
        root = Path(root)
        repo, formula = tap_repo(root, cfg, run), formula_name(root, cfg, run)
        url = source_url(root, version, run)

        def done() -> bool:
            text = remote_formula(repo, formula, run) if repo and formula else None
            return text is not None and f'"{url}"' in text

        def bump(cancel) -> None:
            if not repo or not formula:
                raise StepError("No tap or formula name; set up Homebrew first")
            self.warnings = []
            try:
                body = self._download(url)
            except OSError as exc:
                raise StepError(f"Could not download {url}: {exc}") from exc
            sha256 = hashlib.sha256(body).hexdigest()
            clone = sync_clone(root, repo, run=run)
            path = clone / "Formula" / f"{formula}.rb"
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise StepError(f"Formula/{formula}.rb is not in the tap: {exc}") from exc
            path.write_text(replace_source(text, url, sha256), encoding="utf-8")
            if 'resource "' in text:
                if self._which("brew"):
                    proc = run(["brew", "update-python-resources", str(path)], cwd=clone,
                               timeout=BREW_TIMEOUT)
                    if not _ok(proc):
                        raise StepError(f"brew update-python-resources failed: {_fail(proc)}")
                else:
                    self.warnings.append(NO_BREW_NOTE)
            _commit_and_push(clone, formula, version, run)

        return [Step(KEY, "Update the Homebrew formula", True, done, bump)]

    def verify(self, root: Path, cfg: ReleaseConfig, version: str, *,
               run: Run, fetch: Fetch) -> tuple[bool, str]:
        root = Path(root)
        repo, formula = tap_repo(root, cfg, run), formula_name(root, cfg, run)
        text = remote_formula(repo, formula, run) if repo and formula else None
        if text is None:
            return False, f"could not read Formula/{formula}.rb from {repo or 'the tap'}"
        url = source_url(root, version, run)
        if f'"{url}"' not in text:
            return False, f"the tap's formula does not point at v{version}"
        return True, "; ".join(self.warnings)

    def setup_status(self, root: Path, cfg: ReleaseConfig, *, run: Run) -> list[str]:
        root = Path(root)
        repo, formula = tap_repo(root, cfg, run), formula_name(root, cfg, run)
        if not repo:
            return ["Tap: (no GitHub origin; enter owner/homebrew-tap)"]
        exists = self._succeeds(run, ["gh", "repo", "view", repo], root)
        lines = [f"Tap: {repo} ({'found' if exists else 'not created yet'})",
                 f"Formula: {formula or '(none)'}"]
        if exists and formula:
            lines.append("Formula in tap: " + (
                "found" if remote_formula(repo, formula, run) is not None else "none yet"))
            lines.append("Push access: " + ("yes" if self._can_push(run, repo, root) else "no"))
        lines.append(PUBLIC_NOTE)
        return lines


targets.register(HomebrewTarget())
