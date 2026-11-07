"""The PyPI release target: a tag-triggered trusted-publishing workflow, then a check
that the version shows up on pypi.org."""

from __future__ import annotations

import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from whyline.release import config as release_config
from whyline.release import setup_github, targets, workflows
from whyline.release.config import ReleaseConfig
from whyline.release.engine import Step
from whyline.release.github import POLL_SECONDS, StepError
from whyline.release.ready import Fetch, ReadyItem, Run

KEY = "pypi"
# Any of these in a tag-triggered workflow means it already publishes to PyPI, so
# Set up offers no second workflow (two would race to upload the same version).
NEEDLE = ("pypa/gh-action-pypi-publish", "uv publish", "twine upload")
TEMPLATE_NAME = "release-pypi.yml"
ENVIRONMENT = "pypi"
PUBLISHING_URL = "https://pypi.org/manage/account/publishing/"
VERIFY_SECONDS = 5 * 60
HTTP_TIMEOUT = 15.0

# get(url) -> HTTP status code; raises OSError when PyPI cannot be reached
Get = Callable[[str], int]
Sleep = Callable[[float], None]


def http_status(url: str) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": "whyline-release"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:  # noqa: S310 - fixed https URL
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except urllib.error.URLError as error:
        raise OSError(str(error.reason)) from error


def template_text() -> str:
    return (Path(__file__).resolve().parent.parent / "templates" / TEMPLATE_NAME
            ).read_text(encoding="utf-8")


def project_name(root: Path) -> str:
    try:
        data = tomllib.loads((Path(root) / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    project = data.get("project")
    name = project.get("name") if isinstance(project, dict) else None
    return name.strip() if isinstance(name, str) else ""


def workflow_path(root: Path) -> Path | None:
    """The workflow that publishes to PyPI: an existing one, else release-pypi.yml."""
    found = workflows.find_publishing(root, NEEDLE)
    if found is not None:
        return found
    ours = Path(root) / ".github" / "workflows" / TEMPLATE_NAME
    return ours if ours.is_file() else None


def add_workflow(root: Path) -> Path:
    """Write release-pypi.yml (never over an existing file) and mark it as pending setup."""
    path = workflows.write_template(root, TEMPLATE_NAME, template_text())
    release_config.add_pending(root, path)
    return path


def _version_url(name: str, version: str) -> str:
    return f"https://pypi.org/pypi/{name}/{version}/json"


def _project_url(name: str) -> str:
    return f"https://pypi.org/pypi/{name}/json"


class PyPITarget:
    key = KEY
    title = "PyPI"

    def __init__(self, get: Get | None = None, sleep: Sleep = time.sleep) -> None:
        self._get = get
        self._sleep = sleep

    def get(self, url: str) -> int:
        return (self._get or http_status)(url)

    def ready_items(self, root: Path, cfg: ReleaseConfig, version: str, *,
                    run: Run, fetch: Fetch) -> list[ReadyItem]:
        root = Path(root)
        path = workflow_path(root)
        items = [
            ReadyItem("pypi-workflow", path is not None,
                      f"PyPI workflow is {path.relative_to(root).as_posix()}"
                      if path is not None else "No PyPI publishing workflow",
                      "" if path is not None else "Set up PyPI and choose Add workflow"),
        ]
        name = project_name(root)
        items.append(ReadyItem(
            "pypi-name", bool(name),
            f"PyPI project name is {name}" if name else "No project name in pyproject.toml",
            "" if name else "Add name under [project] in pyproject.toml"))
        if name:
            items.append(self._not_published(name, version))
        return items

    def _not_published(self, name: str, version: str) -> ReadyItem:
        try:
            status = self.get(_version_url(name, version))
        except OSError:
            return ReadyItem("pypi-version", False, "could not reach PyPI",
                             "Check your connection, then check again")
        if status == 404:
            return ReadyItem("pypi-version", True, f"{name} {version} is not on PyPI yet")
        if status == 200:
            return ReadyItem("pypi-version", False, f"{name} {version} is already on PyPI",
                             "Pick another version")
        return ReadyItem("pypi-version", False, f"PyPI answered {status}", "Try again later")

    def _published(self, root: Path, version: str) -> bool:
        name = project_name(root)
        if not name:
            return False
        try:
            return self.get(_version_url(name, version)) == 200
        except OSError:
            return False

    def steps(self, root: Path, cfg: ReleaseConfig, version: str, *,
              run: Run, fetch: Fetch) -> list[Step]:
        root = Path(root)

        def wait(cancel: threading.Event) -> bool | None:
            path = workflow_path(root)
            if path is None:
                raise StepError("No PyPI publishing workflow; set up PyPI and add one")
            return workflows.wait_for_tag_run(root, f"v{version}", path, run=run,
                                              sleep=self._sleep, cancel_event=cancel)

        return [Step(KEY, "Publish to PyPI", False, lambda: self._published(root, version),
                     wait)]

    def verify(self, root: Path, cfg: ReleaseConfig, version: str, *,
               run: Run, fetch: Fetch) -> tuple[bool, str]:
        """Wait up to 5 minutes for the version to appear: PyPI's index lags the upload."""
        root = Path(root)
        waited = 0.0
        while True:
            if self._published(root, version):
                return True, ""
            if waited >= VERIFY_SECONDS:
                return False, f"{version} is not on PyPI after 5 minutes"
            self._sleep(POLL_SECONDS)
            waited += POLL_SECONDS

    def setup_status(self, root: Path, cfg: ReleaseConfig, *, run: Run) -> list[str]:
        root = Path(root)
        path = workflow_path(root)
        lines = [f"Workflow: {path.relative_to(root).as_posix()}" if path is not None
                 else "Workflow: none yet"]
        name = project_name(root)
        exists: bool | None = None
        if name:
            try:
                exists = self.get(_project_url(name)) == 200
            except OSError:
                exists = None
        if not name:
            lines.append("Project: no name in pyproject.toml")
        elif exists is None:
            lines.append(f"Project {name}: could not reach PyPI")
        else:
            lines.append(f"Project {name}: " + ("on PyPI" if exists else "not on PyPI yet"))
        lines.append("For the trusted publisher form on pypi.org:")
        owner, _, repo = _owner_repo(root, run).partition("/")
        lines.append(f"  Owner: {owner or '(no GitHub origin)'}")
        lines.append(f"  Repository: {repo or '(no GitHub origin)'}")
        lines.append(f"  Workflow file name: {path.name if path is not None else TEMPLATE_NAME}")
        lines.append(f"  Environment: {ENVIRONMENT}")
        if exists is False:
            lines.append("New project: use Add a pending publisher")
        return lines


def _owner_repo(root: Path, run: Run) -> str:
    try:
        proc = run(["git", "remote", "get-url", "origin"], cwd=root)
    except OSError:
        return ""
    if getattr(proc, "returncode", 1) != 0:
        return ""
    return setup_github.owner_repo(str(getattr(proc, "stdout", "")).strip())


targets.register(PyPITarget())
