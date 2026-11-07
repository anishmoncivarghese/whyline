"""The Docker release target: a tag-triggered workflow that pushes the image to GHCR
and/or Docker Hub, then a check that the tag can be pulled."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from whyline.release import config as release_config
from whyline.release import targets, workflows
from whyline.release.config import ReleaseConfig
from whyline.release.engine import Step
from whyline.release.github import StepError
from whyline.release.ready import Fetch, ReadyItem, Run
from whyline.release.targets.pypi import _owner_repo

KEY = "docker"
NEEDLE = "docker/build-push-action"
TEMPLATE_NAME = "release-docker.yml"
REGISTRIES = ("ghcr", "dockerhub")
REGISTRY_HOSTS = {"ghcr": "ghcr.io/", "dockerhub": ""}
SECRET_NAMES = ("DOCKERHUB_USERNAME", "DOCKERHUB_TOKEN")
NO_DOCKER_NOTE = "docker is not installed, so the tag run's success is the check"
TREE_LIMIT = 200
MANIFESTS = ("pyproject.toml", "package.json", "go.mod", "Cargo.toml", "Gemfile",
             "requirements.txt", "pom.xml", "build.gradle", "composer.json",
             "uv.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
             "poetry.lock", "Cargo.lock", "go.sum", "Gemfile.lock")
MANIFEST_CHARS = 3000

_GHCR_LOGIN = """      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}"""
_HUB_LOGIN = """      - uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}"""

AskAgent = Callable[[str], str]


def template_text() -> str:
    return (Path(__file__).resolve().parent.parent / "templates" / TEMPLATE_NAME
            ).read_text(encoding="utf-8")


def registries(cfg: ReleaseConfig) -> tuple[str, ...]:
    chosen = tuple(r for r in cfg.targets.docker_options.registries if r in REGISTRIES)
    return chosen or ("ghcr",)


def image_name(root: Path, cfg: ReleaseConfig, run: Run) -> str:
    """The configured image, else `<owner>/<repo>` from origin; always lowercase."""
    name = cfg.targets.docker_options.image.strip() or _owner_repo(Path(root), run)
    return name.lower()


def render_template(image: str, regs: tuple[str, ...]) -> str:
    logins = []
    if "ghcr" in regs:
        logins.append(_GHCR_LOGIN)
    if "dockerhub" in regs:
        logins.append(_HUB_LOGIN)
    images = "\n".join(f"            {REGISTRY_HOSTS[r]}{image}" for r in regs)
    return (template_text().replace("@@LOGINS@@", "\n".join(logins))
            .replace("@@IMAGES@@", images))


def workflow_path(root: Path) -> Path | None:
    found = workflows.find_publishing(root, NEEDLE)
    if found is not None:
        return found
    ours = Path(root) / ".github" / "workflows" / TEMPLATE_NAME
    return ours if ours.is_file() else None


def add_workflow(root: Path, cfg: ReleaseConfig, *, run: Run) -> Path:
    """Write release-docker.yml (never over an existing file) and mark it pending."""
    image = image_name(root, cfg, run)
    if not image:
        raise OSError("No image name: set one, or add a GitHub origin")
    text = render_template(image, registries(cfg))
    path = workflows.write_template(root, TEMPLATE_NAME, text)
    release_config.add_pending(root, path)
    return path


def _secret_names(root: Path, run: Run) -> set[str] | None:
    try:
        proc = run(["gh", "secret", "list", "--json", "name"], cwd=root)
    except OSError:
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    try:
        data = json.loads(str(getattr(proc, "stdout", "")) or "[]")
    except ValueError:
        return None
    return {str(d.get("name")) for d in data if isinstance(d, dict)}


def store_dockerhub_secrets(root: Path, username: str, token: str, *, run: Run) -> None:
    """Set both secrets with the value on stdin; it never appears in argv."""
    if not username.strip() or not token:
        raise StepError("Enter the Docker Hub username and an access token")
    for name, value in zip(SECRET_NAMES, (username.strip(), token)):
        proc = run(["gh", "secret", "set", name], cwd=Path(root), input=value)
        if getattr(proc, "returncode", 1) != 0:
            raise StepError(f"Could not store {name}")


def stdin_run(args: list[str], *, cwd: Path | str | None = None, input: str | None = None,
              timeout: float = 30.0) -> subprocess.CompletedProcess:
    """A `run` that can feed stdin; the default one cannot."""
    return subprocess.run(args, cwd=cwd, input=input, capture_output=True, text=True,
                          timeout=timeout, check=False)


def _tree(root: Path) -> str:
    try:
        proc = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True,
                              timeout=30, check=False)
        names = proc.stdout.splitlines() if proc.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        names = []
    if not names:
        names = sorted(p.name for p in Path(root).iterdir() if not p.name.startswith("."))
    extra = len(names) - TREE_LIMIT
    return "\n".join(names[:TREE_LIMIT]) + (f"\n… and {extra} more" if extra > 0 else "")


def draft_dockerfile(root: Path, *, ask_agent: AskAgent) -> str:
    """Ask the main agent for a Dockerfile. Returns text only; nothing is written."""
    root = Path(root)
    parts = ["Write a Dockerfile for this project. Work out the language, the entry point "
             "and the lockfile from the file list and manifests below. It must be small "
             "(slim or multi-stage base, no build tools left behind) and run as a non-root "
             "user. Answer with only the Dockerfile contents, no commentary. Do not run "
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
        raise StepError("The agent returned no Dockerfile")
    return text + "\n"


class DockerTarget:
    key = KEY
    title = "Docker"

    def __init__(self, sleep: Callable[[float], None] | None = None,
                 which: Callable[[str], str | None] = shutil.which) -> None:
        import time
        self._sleep = sleep or time.sleep
        self._which = which

    def ready_items(self, root: Path, cfg: ReleaseConfig, version: str, *,
                    run: Run, fetch: Fetch) -> list[ReadyItem]:
        root = Path(root)
        has_file = (root / "Dockerfile").is_file()
        path = workflow_path(root)
        items = [
            ReadyItem("docker-file", has_file,
                      "Dockerfile found" if has_file else "No Dockerfile",
                      "" if has_file else "Set up Docker and choose Draft Dockerfile"),
            ReadyItem("docker-workflow", path is not None,
                      f"Docker workflow is {path.relative_to(root).as_posix()}"
                      if path is not None else "No Docker publishing workflow",
                      "" if path is not None else "Set up Docker and choose Add workflow"),
        ]
        if "dockerhub" in registries(cfg):
            names = _secret_names(root, run)
            if names is None:
                items.append(ReadyItem("docker-secrets", False,
                                       "could not list GitHub secrets",
                                       "Check gh is signed in, then check again"))
            else:
                missing = [n for n in SECRET_NAMES if n not in names]
                items.append(ReadyItem(
                    "docker-secrets", not missing,
                    "Docker Hub secrets are set" if not missing
                    else f"Missing GitHub secrets: {', '.join(missing)}",
                    "" if not missing else "Set up Docker and choose Store as GitHub secrets"))
        return items

    def steps(self, root: Path, cfg: ReleaseConfig, version: str, *,
              run: Run, fetch: Fetch) -> list[Step]:
        root = Path(root)

        def wait(cancel: threading.Event) -> bool | None:
            path = workflow_path(root)
            if path is None:
                raise StepError("No Docker publishing workflow; set up Docker and add one")
            return workflows.wait_for_tag_run(root, f"v{version}", path, run=run,
                                              sleep=self._sleep, cancel_event=cancel)

        return [Step(KEY, "Publish the Docker image", False, lambda: False, wait)]

    def _ref(self, root: Path, cfg: ReleaseConfig, run: Run) -> str:
        image = image_name(root, cfg, run)
        return REGISTRY_HOSTS[registries(cfg)[0]] + image

    def verify(self, root: Path, cfg: ReleaseConfig, version: str, *,
               run: Run, fetch: Fetch) -> tuple[bool, str]:
        """`docker manifest inspect` when docker is installed; otherwise the tag run's
        success (the step already waited for it) counts, with a note."""
        if not self._which("docker"):
            return True, NO_DOCKER_NOTE
        ref = f"{self._ref(Path(root), cfg, run)}:{version}"
        try:
            proc = run(["docker", "manifest", "inspect", ref], cwd=Path(root))
        except OSError as exc:
            return False, f"could not run docker: {exc}"
        if getattr(proc, "returncode", 1) == 0:
            return True, ""
        return False, f"{ref} is not on the registry"

    def setup_status(self, root: Path, cfg: ReleaseConfig, *, run: Run) -> list[str]:
        root = Path(root)
        path = workflow_path(root)
        regs = registries(cfg)
        lines = ["Dockerfile: " + ("found" if (root / "Dockerfile").is_file() else "none yet"),
                 f"Workflow: {path.relative_to(root).as_posix()}" if path is not None
                 else "Workflow: none yet",
                 "Registries: " + ", ".join("GHCR" if r == "ghcr" else "Docker Hub"
                                            for r in regs),
                 f"Image: {image_name(root, cfg, run) or '(no GitHub origin)'}"]
        if "dockerhub" in regs:
            names = _secret_names(root, run)
            if names is None:
                lines.append("Docker Hub secrets: could not check")
            else:
                missing = [n for n in SECRET_NAMES if n not in names]
                lines.append("Docker Hub secrets: " + ("set" if not missing
                                                       else "missing " + ", ".join(missing)))
        return lines


targets.register(DockerTarget())
