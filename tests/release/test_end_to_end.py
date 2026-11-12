"""The whole Release button against a real temp repository and a bare origin.

git is real. `gh`, `brew` and `docker`, the registry lookups, the tarball download and the
custom command are fakes that remember what they were asked, so the tests can say what
ran and what did not."""

import base64
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.release import engine, plan
from whyline.release import ready as release_ready
from whyline.release import state as release_state
from whyline.release import targets
from whyline.release.config import CustomTarget, ReleaseConfig, Targets
from whyline.release.targets.custom import CustomTarget as CustomRunner
from whyline.release.targets.docker import DockerTarget
from whyline.release.targets.homebrew import HomebrewTarget
from whyline.release.targets.npm import NpmTarget
from whyline.release.targets.pypi import PyPITarget

VERSION = "1.0.1"
TAG = f"v{VERSION}"
ORIGIN_URL = "git@github.com:Octo/Demo.git\n"
TAP = "Octo/homebrew-tap"
FORMULA = """class Demo < Formula
  desc "Demo"
  url "https://github.com/Octo/Demo/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "aaaa"

  resource "requests" do
    url "https://files.example/requests-2.0.tar.gz"
    sha256 "bbbb"
  end
end
"""
WORKFLOW = """name: {name}
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: {needle}
"""
WORKFLOWS = {
    "release-pypi.yml": "pypa/gh-action-pypi-publish@release/v1",
    "release-npm.yml": "run: npm publish",
    "release-docker.yml": "docker/build-push-action@v6",
}


def proc(code=0, out="", err=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


class Fakes:
    """One `run` for git (real), gh, brew and docker, plus the lookups the targets inject."""

    def __init__(self, root: Path, tap: Path) -> None:
        self.root = root
        self.tap = tap
        self.calls: list[list[str]] = []
        self.shell_calls: list[str] = []
        self.fail_workflows: set[str] = set()
        self.passed: set[str] = set()
        self.release_created = False
        self.announced = False

    def count(self, *prefix: str) -> int:
        return sum(1 for args in self.calls if args[:len(prefix)] == list(prefix))

    def used(self, program: str) -> bool:
        return any(args[0] == program for args in self.calls)

    def run(self, args, cwd=None, env=None, timeout=30.0, input=None):
        args = list(args)
        self.calls.append(args)
        if args[:4] == ["git", "remote", "get-url", "origin"]:
            return proc(0, ORIGIN_URL)
        if args[0] == "git":
            done = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                                  check=False)
            return proc(done.returncode, done.stdout, done.stderr)
        if args[0] == "gh":
            return self._gh(args)
        return proc(0)  # brew, docker

    def _gh(self, args):
        if args[:2] == ["gh", "run"] and args[2] == "list":
            if "--commit" in args:
                return proc(0, json.dumps([{"name": "ci", "status": "completed",
                                            "conclusion": "success", "url": "u"}]))
            name = args[args.index("--workflow") + 1]
            if name in self.fail_workflows:
                return proc(0, json.dumps([{"status": "completed", "conclusion": "failure",
                                            "url": "https://ci/7", "databaseId": 7}]))
            self.passed.add(name)
            return proc(0, json.dumps([{"status": "completed", "conclusion": "success",
                                        "url": "u", "databaseId": 8}]))
        if args[:3] == ["gh", "run", "view"]:
            return proc(0, json.dumps({"jobs": [{"name": "publish", "conclusion": "failure"}]}))
        if args[:3] == ["gh", "release", "view"]:
            return proc(0 if self.release_created else 1)
        if args[:3] == ["gh", "release", "create"]:
            self.release_created = True
            return proc(0)
        if args[:3] == ["gh", "repo", "clone"]:
            return self._clone(args[4])
        if args[:2] == ["gh", "api"] and args[2].endswith("/contents/Formula/demo.rb"):
            text = git(self.tap, "show", "HEAD:Formula/demo.rb")
            return proc(0, base64.encodebytes(text.encode()).decode())
        if args[:2] == ["gh", "api"] and ".permissions.push" in args:
            return proc(0, "true")
        return proc(0)  # gh --version, auth status, repo view

    def _clone(self, dest):
        done = subprocess.run(["git", "clone", str(self.tap), dest], capture_output=True,
                              text=True, check=False)
        return proc(done.returncode, done.stdout, done.stderr)

    def run_shell(self, command, root, on_line):
        self.shell_calls.append(command)
        return 0, []

    def custom_shell(self, command, root, env, on_line):
        self.shell_calls.append(command)
        if command == "announce-tool":
            assert env["WHYLINE_RELEASE_TAG"] == TAG
            self.announced = True
            return 0, []
        return (0 if self.announced else 1), []

    def status(self, url):
        name = "release-pypi.yml" if "pypi.org" in url else "release-npm.yml"
        return 200 if name in self.passed else 404

    def targets(self):
        nap = lambda seconds: None  # noqa: E731 - no waiting in tests
        return {
            "pypi": PyPITarget(get=self.status, sleep=nap),
            "npm": NpmTarget(get=self.status, sleep=nap),
            "docker": DockerTarget(sleep=nap, which=lambda name: "/usr/bin/docker"),
            "homebrew": HomebrewTarget(download=lambda url: b"tarball",
                                       which=lambda name: "/opt/homebrew/bin/brew"),
            "custom": CustomRunner(shell=self.custom_shell, which=lambda name: f"/bin/{name}"),
        }


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
                       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}.items():
        monkeypatch.setenv(key, value)
    origin, tap, root = tmp_path / "origin.git", tmp_path / "tap.git", tmp_path / "demo"
    for bare in (origin, tap):
        git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "tap-seed"
    git(tmp_path, "clone", str(tap), str(seed))
    (seed / "Formula").mkdir()
    (seed / "Formula" / "demo.rb").write_text(FORMULA)
    git(seed, "add", ".")
    git(seed, "commit", "-m", "formula")
    git(seed, "push", "origin", "HEAD:main")

    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.0.0"\n')
    (root / "package.json").write_text('{\n  "name": "demo-js",\n  "version": "1.0.0"\n}\n')
    (root / "Dockerfile").write_text("FROM scratch\n")
    for name, needle in WORKFLOWS.items():
        (root / ".github" / "workflows" / name).write_text(
            WORKFLOW.format(name=name, needle=needle))
    git(root, "init", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-m", "start")
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-u", "origin", "main")

    fakes = Fakes(root, tap)
    for key, target in fakes.targets().items():
        monkeypatch.setitem(targets.REGISTRY, key, target)
    monkeypatch.setattr(release_ready, "_TARGET_CHECKS", {})  # the security scan is not under test
    return SimpleNamespace(root=root, origin=origin, tap=tap, fakes=fakes)


ALL = Targets(pypi=True, npm=True, docker=True, homebrew=True,
              custom=(CustomTarget("announce", "announce-tool", "check-announce"),))


def config(chosen=ALL):
    return ReleaseConfig(mode="auto", checks=("make check",), after=("notify-team",),
                         targets=chosen)


def build(env, cfg):
    fakes = env.fakes
    return plan.build(
        env.root, cfg, VERSION, run=fakes.run, run_shell=fakes.run_shell,
        ask_agent=lambda prompt: f"<notes>\n# {TAG}\n- everything\n</notes>",
        ready_check=lambda: release_ready.check(env.root, cfg, VERSION, run=fakes.run,
                                                fetch=lambda root, branch: None),
        fetch=lambda root, branch: None, telegram_target=lambda: None,
        sleep=lambda seconds: None, say=lambda text: None)


def go(env, cfg):
    return engine.run(env.root, build(env, cfg), mode=cfg.mode)


def test_every_target_runs_to_the_end(env):
    cfg = config()
    result = go(env, cfg)
    assert result.status == engine.DONE, result.message
    fakes = env.fakes
    ids = [s.id for s in build(env, cfg).steps]
    assert ids == ["ready", "version", "notes", "commit", "checks", "push", "ci", "tag",
                   "github_release", "pypi", "npm", "docker", "homebrew", "custom:announce",
                   "verify", "after"]
    assert release_state.load(env.root) is None
    assert git(env.origin, "tag", "--list") == TAG
    assert git(env.origin, "log", "-1", "--format=%s", "main") == f"chore: release {TAG}"
    assert 'version = "1.0.1"' in (env.root / "pyproject.toml").read_text()
    assert (env.root / "docs" / "releases" / f"v{VERSION}.md").is_file()
    assert fakes.count("gh", "release", "create") == 1
    assert fakes.count("brew", "update-python-resources") == 1
    assert fakes.count("docker", "manifest", "inspect") == 1
    assert git(env.tap, "show", "HEAD:Formula/demo.rb").count(f"refs/tags/{TAG}.tar.gz") == 1
    # checks first, then the custom run between its two verify checks, the after command last
    assert fakes.shell_calls == ["make check", "check-announce", "announce-tool",
                                 "check-announce", "notify-team"]


def test_a_second_run_is_refused_as_already_released(env):
    cfg = config()
    assert go(env, cfg).status == engine.DONE
    fakes = env.fakes
    items = release_ready.check(env.root, cfg, VERSION, run=fakes.run,
                                fetch=lambda root, branch: None)
    tag = next(i for i in items if i.key == "tag")
    assert not tag.ok
    assert "exists" in tag.text and TAG in tag.text
    assert not release_ready.ok(items)
    # the registries say so too
    pypi = [i for i in targets.REGISTRY["pypi"].ready_items(
        env.root, cfg, VERSION, run=fakes.run, fetch=None) if i.key == "pypi-version"]
    assert pypi and not pypi[0].ok and "already on PyPI" in pypi[0].text


def test_a_run_failed_at_pypi_resumes_without_repeating_the_tag_or_release(env):
    cfg = config()
    fakes = env.fakes
    fakes.fail_workflows.add("release-pypi.yml")
    first = go(env, cfg)
    assert first.status == engine.FAILED and first.failed_id == "pypi"
    assert "release-pypi.yml failed in job publish" in first.message
    saved = release_state.load(env.root)
    assert "github_release" in saved.done and "pypi" not in saved.done
    assert fakes.count("gh", "release", "create") == 1

    fakes.fail_workflows.clear()
    again = build(env, cfg)
    result = engine.resume(env.root, {s.id: s for s in again.steps}, version=VERSION,
                           mode="auto")
    assert result.status == engine.DONE, result.message
    assert fakes.count("gh", "release", "create") == 1
    assert fakes.count("git", "tag") == 1
    assert fakes.count("git", "push", "origin", f"refs/tags/{TAG}") == 1
    assert fakes.count("git", "commit", "-m", f"chore: release {TAG}") == 1
    assert release_state.load(env.root) is None
    assert fakes.passed == set(WORKFLOWS)


def test_an_unticked_target_has_no_steps_and_runs_nothing(env):
    cfg = config(Targets(pypi=True))
    result = go(env, cfg)
    assert result.status == engine.DONE, result.message
    ids = [s.id for s in build(env, cfg).steps]
    assert "pypi" in ids
    for gone in ("npm", "docker", "homebrew", "custom:announce"):
        assert gone not in ids
    fakes = env.fakes
    assert not fakes.used("brew") and not fakes.used("docker")
    assert fakes.count("gh", "repo", "clone") == 0
    assert not any("release-npm.yml" in a or "release-docker.yml" in a
                   for args in fakes.calls for a in args)
    assert not any(c in ("announce-tool", "check-announce") for c in fakes.shell_calls)
    assert not any("api" in args[:2] for args in fakes.calls)
    assert git(env.tap, "log", "--format=%s") == "formula"
