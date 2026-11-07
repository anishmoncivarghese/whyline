"""The npm release target: a tag-triggered trusted-publishing workflow, then a check
that the version shows up on the npm registry."""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path

from whyline.release import config as release_config
from whyline.release import targets, workflows
from whyline.release.config import ReleaseConfig
from whyline.release.engine import Step
from whyline.release.github import POLL_SECONDS, StepError
from whyline.release.ready import Fetch, ReadyItem, Run
from whyline.release.targets.pypi import _owner_repo, http_status

KEY = "npm"
NEEDLE = "npm publish"
TEMPLATE_NAME = "release-npm.yml"
PUBLISHING_URL = "https://www.npmjs.com/"
VERIFY_SECONDS = 5 * 60
FIRST_PUBLISH = ("Run `npm login` and `npm publish` once in a terminal; "
                 "later releases publish automatically.")

# get(url) -> HTTP status code; raises OSError when npm cannot be reached
Get = Callable[[str], int]
Sleep = Callable[[float], None]


def template_text() -> str:
    return (Path(__file__).resolve().parent.parent / "templates" / TEMPLATE_NAME
            ).read_text(encoding="utf-8")


def package_info(root: Path) -> tuple[str, bool]:
    """(name, private) from package.json; ("", False) when missing or unreadable."""
    try:
        data = json.loads((Path(root) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", False
    if not isinstance(data, dict):
        return "", False
    name = data.get("name")
    return (name.strip() if isinstance(name, str) else ""), data.get("private") is True


def workflow_path(root: Path) -> Path | None:
    """The workflow that publishes to npm: an existing one, else release-npm.yml."""
    found = workflows.find_publishing(root, NEEDLE)
    if found is not None:
        return found
    ours = Path(root) / ".github" / "workflows" / TEMPLATE_NAME
    return ours if ours.is_file() else None


def add_workflow(root: Path) -> Path:
    """Write release-npm.yml (never over an existing file) and mark it as pending setup."""
    path = workflows.write_template(root, TEMPLATE_NAME, template_text())
    release_config.add_pending(root, path)
    return path


def _quoted(name: str) -> str:
    # scoped names: @scope/pkg -> @scope%2Fpkg
    return urllib.parse.quote(name, safe="@")


def _version_url(name: str, version: str) -> str:
    return f"https://registry.npmjs.org/{_quoted(name)}/{version}"


def _package_url(name: str) -> str:
    return f"https://registry.npmjs.org/{_quoted(name)}"


class NpmTarget:
    key = KEY
    title = "npm"

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
            ReadyItem("npm-workflow", path is not None,
                      f"npm workflow is {path.relative_to(root).as_posix()}"
                      if path is not None else "No npm publishing workflow",
                      "" if path is not None else "Set up npm and choose Add workflow"),
        ]
        name, private = package_info(root)
        if not name:
            items.append(ReadyItem("npm-name", False, "No package name in package.json",
                                   "Add a name to package.json"))
        elif private:
            items.append(ReadyItem("npm-name", False, f"{name} is private in package.json",
                                   'Remove "private": true from package.json'))
        else:
            items.append(ReadyItem("npm-name", True, f"npm package name is {name}"))
            items.append(self._not_published(name, version))
        return items

    def _not_published(self, name: str, version: str) -> ReadyItem:
        try:
            status = self.get(_version_url(name, version))
        except OSError:
            return ReadyItem("npm-version", False, "could not reach npm",
                             "Check your connection, then check again")
        if status == 404:
            return ReadyItem("npm-version", True, f"{name} {version} is not on npm yet")
        if status == 200:
            return ReadyItem("npm-version", False, f"{name} {version} is already on npm",
                             "Pick another version")
        return ReadyItem("npm-version", False, f"npm answered {status}", "Try again later")

    def _published(self, root: Path, version: str) -> bool:
        name, _ = package_info(root)
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
                raise StepError("No npm publishing workflow; set up npm and add one")
            return workflows.wait_for_tag_run(root, f"v{version}", path, run=run,
                                              sleep=self._sleep, cancel_event=cancel)

        return [Step(KEY, "Publish to npm", False, lambda: self._published(root, version),
                     wait)]

    def verify(self, root: Path, cfg: ReleaseConfig, version: str, *,
               run: Run, fetch: Fetch) -> tuple[bool, str]:
        """Wait up to 5 minutes for the version to appear: the registry lags the upload."""
        root = Path(root)
        waited = 0.0
        while True:
            if self._published(root, version):
                return True, ""
            if waited >= VERIFY_SECONDS:
                return False, f"{version} is not on npm after 5 minutes"
            self._sleep(POLL_SECONDS)
            waited += POLL_SECONDS

    def setup_status(self, root: Path, cfg: ReleaseConfig, *, run: Run) -> list[str]:
        root = Path(root)
        path = workflow_path(root)
        lines = [f"Workflow: {path.relative_to(root).as_posix()}" if path is not None
                 else "Workflow: none yet"]
        name, _ = package_info(root)
        exists: bool | None = None
        if name:
            try:
                exists = self.get(_package_url(name)) == 200
            except OSError:
                exists = None
        if not name:
            lines.append("Package: no name in package.json")
        elif exists is None:
            lines.append(f"Package {name}: could not reach npm")
        else:
            lines.append(f"Package {name}: " + ("on npm" if exists else "not on npm yet"))
        lines.append("For the trusted publisher form on npmjs.com:")
        owner, _, repo = _owner_repo(root, run).partition("/")
        lines.append(f"  Owner: {owner or '(no GitHub origin)'}")
        lines.append(f"  Repository: {repo or '(no GitHub origin)'}")
        lines.append(f"  Workflow file name: {path.name if path is not None else TEMPLATE_NAME}")
        if exists is False:
            lines.append(FIRST_PUBLISH)
        return lines


targets.register(NpmTarget())
