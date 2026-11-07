import json
import threading
from types import SimpleNamespace

import pytest

from whyline.release import config as release_config
from whyline.release import targets
from whyline.release.config import ReleaseConfig
from whyline.release.targets import npm

CFG = ReleaseConfig()
EVENT = threading.Event()
TAGGED = ("on:\n  push:\n    tags:\n      - 'v*'\njobs:\n  x:\n    steps:\n"
          "      - run: npm publish --provenance\n")


def package(root, name="demo", **extra):
    (root / "package.json").write_text(json.dumps({"name": name, "version": "1.2.3", **extra}))


def workflow(root, name, text):
    path = root / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def getter(status, calls=None):
    def get(url):
        if calls is not None:
            calls.append(url)
        if isinstance(status, Exception):
            raise status
        return status(url) if callable(status) else status
    return get


def ready(tmp_path, status):
    return {i.key: i for i in npm.NpmTarget(get=getter(status)).ready_items(
        tmp_path, CFG, "1.2.3", run=None, fetch=None)}


def test_registered():
    assert targets.REGISTRY["npm"].key == "npm"


def test_ready_all_good_on_404(tmp_path):
    package(tmp_path)
    workflow(tmp_path, "pub.yml", TAGGED)
    calls = []
    items = {i.key: i for i in npm.NpmTarget(get=getter(404, calls)).ready_items(
        tmp_path, CFG, "1.2.3", run=None, fetch=None)}
    assert all(i.ok for i in items.values())
    assert "pub.yml" in items["npm-workflow"].text
    assert calls == ["https://registry.npmjs.org/demo/1.2.3"]


def test_scoped_name_is_url_encoded(tmp_path):
    package(tmp_path, "@octo/demo")
    calls = []
    npm.NpmTarget(get=getter(404, calls)).ready_items(
        tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert calls == ["https://registry.npmjs.org/@octo%2Fdemo/1.2.3"]


def test_ready_fails_when_version_is_published(tmp_path):
    package(tmp_path)
    workflow(tmp_path, "pub.yml", TAGGED)
    item = ready(tmp_path, 200)["npm-version"]
    assert not item.ok and "already on npm" in item.text


def test_ready_network_error(tmp_path):
    package(tmp_path)
    item = ready(tmp_path, OSError("down"))["npm-version"]
    assert not item.ok and item.text == "could not reach npm"


def test_private_package_is_refused(tmp_path):
    package(tmp_path, private=True)
    calls = []
    items = {i.key: i for i in npm.NpmTarget(get=getter(404, calls)).ready_items(
        tmp_path, CFG, "1.2.3", run=None, fetch=None)}
    assert not items["npm-name"].ok and "private" in items["npm-name"].text
    assert "npm-version" not in items and calls == []


def test_ready_without_workflow_or_name(tmp_path):
    items = ready(tmp_path, 404)
    assert not items["npm-workflow"].ok and "Add workflow" in items["npm-workflow"].fix
    assert not items["npm-name"].ok
    assert "npm-version" not in items


def test_reuses_existing_publishing_workflow(tmp_path):
    package(tmp_path)
    existing = workflow(tmp_path, "publish.yml", TAGGED)
    assert npm.workflow_path(tmp_path) == existing
    status = npm.NpmTarget(get=getter(404)).setup_status(
        tmp_path, CFG, run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    assert "Workflow: .github/workflows/publish.yml" in status
    assert "  Workflow file name: publish.yml" in status


def test_add_workflow_writes_template_once_and_marks_pending(tmp_path):
    path = npm.add_workflow(tmp_path)
    text = path.read_text()
    assert path.name == "release-npm.yml"
    for part in ("id-token: write", "contents: read", "actions/setup-node",
                 "registry-url: https://registry.npmjs.org", "npm ci",
                 "npm publish --provenance --access public", "- \"v*\""):
        assert part in text
    assert release_config.pending(tmp_path) == [path.relative_to(tmp_path)] or \
        release_config.pending(tmp_path) == [path]
    with pytest.raises(FileExistsError):
        npm.add_workflow(tmp_path)
    assert npm.workflow_path(tmp_path) == path


def test_step_done_check_is_the_version_url(tmp_path):
    package(tmp_path)
    [step] = npm.NpmTarget(get=getter(200)).steps(tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert step.id == "npm" and step.done_check() is True
    [step] = npm.NpmTarget(get=getter(404)).steps(tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert step.done_check() is False
    [step] = npm.NpmTarget(get=getter(OSError("x"))).steps(
        tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert step.done_check() is False


def test_step_waits_for_the_tag_run(tmp_path):
    package(tmp_path)
    workflow(tmp_path, "pub.yml", TAGGED)
    calls = []

    def run(args, cwd=None, **kw):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
            [{"status": "completed", "conclusion": "success", "url": "u"}]))

    [step] = npm.NpmTarget(get=getter(404)).steps(tmp_path, CFG, "1.2.3", run=run, fetch=None)
    assert step.run(EVENT) is None
    assert calls[0][:6] == ["gh", "run", "list", "--workflow", "pub.yml", "--branch"]
    assert calls[0][6] == "v1.2.3"


def test_verify_retries_until_the_registry_catches_up(tmp_path):
    package(tmp_path)
    answers = iter([404, 404, 200])
    sleeps = []
    target = npm.NpmTarget(get=lambda url: next(answers), sleep=sleeps.append)
    assert target.verify(tmp_path, CFG, "1.2.3", run=None, fetch=None) == (True, "")
    assert sleeps == [15, 15]


def test_verify_gives_up_after_five_minutes(tmp_path):
    package(tmp_path)
    sleeps = []
    target = npm.NpmTarget(get=getter(404), sleep=sleeps.append)
    good, text = target.verify(tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert not good and "5 minutes" in text
    assert sum(sleeps) == 300


def test_setup_status_lines(tmp_path):
    package(tmp_path, "@octo/demo")

    def run(args, cwd=None, **kw):
        return SimpleNamespace(returncode=0, stdout="https://github.com/octo/demo.git\n")

    calls = []
    lines = npm.NpmTarget(get=getter(404, calls)).setup_status(tmp_path, CFG, run=run)
    assert calls == ["https://registry.npmjs.org/@octo%2Fdemo"]
    assert lines[0] == "Workflow: none yet"
    assert "Package @octo/demo: not on npm yet" in lines
    assert "  Owner: octo" in lines and "  Repository: demo" in lines
    assert "  Workflow file name: release-npm.yml" in lines
    assert lines[-1] == npm.FIRST_PUBLISH
    on_npm = npm.NpmTarget(get=getter(200)).setup_status(tmp_path, CFG, run=run)
    assert "Package @octo/demo: on npm" in on_npm
    assert npm.FIRST_PUBLISH not in on_npm
    down = npm.NpmTarget(get=getter(OSError("x"))).setup_status(tmp_path, CFG, run=run)
    assert "Package @octo/demo: could not reach npm" in down
