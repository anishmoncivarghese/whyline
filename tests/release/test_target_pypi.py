import json
import threading
from types import SimpleNamespace

import pytest

from whyline.release import config as release_config
from whyline.release import targets
from whyline.release.config import ReleaseConfig
from whyline.release.targets import pypi

CFG = ReleaseConfig()
EVENT = threading.Event()
TAGGED = ("on:\n  push:\n    tags:\n      - 'v*'\njobs:\n  x:\n    steps:\n"
          "      - uses: pypa/gh-action-pypi-publish@release/v1\n")


def project(root, name="demo"):
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "1.2.3"\n')


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
    return {i.key: i for i in pypi.PyPITarget(get=getter(status)).ready_items(
        tmp_path, CFG, "1.2.3", run=None, fetch=None)}


def test_registered():
    assert targets.REGISTRY["pypi"].key == "pypi"


def test_ready_all_good_on_404(tmp_path):
    project(tmp_path)
    workflow(tmp_path, "pub.yml", TAGGED)
    calls = []
    items = {i.key: i for i in pypi.PyPITarget(get=getter(404, calls)).ready_items(
        tmp_path, CFG, "1.2.3", run=None, fetch=None)}
    assert all(i.ok for i in items.values())
    assert "pub.yml" in items["pypi-workflow"].text
    assert calls == ["https://pypi.org/pypi/demo/1.2.3/json"]


def test_ready_fails_when_version_is_published(tmp_path):
    project(tmp_path)
    workflow(tmp_path, "pub.yml", TAGGED)
    item = ready(tmp_path, 200)["pypi-version"]
    assert not item.ok and "already on PyPI" in item.text


def test_ready_network_error(tmp_path):
    project(tmp_path)
    workflow(tmp_path, "pub.yml", TAGGED)
    item = ready(tmp_path, OSError("down"))["pypi-version"]
    assert not item.ok and item.text == "could not reach PyPI"


def test_ready_without_workflow_or_name(tmp_path):
    items = ready(tmp_path, 404)
    assert not items["pypi-workflow"].ok and "Add workflow" in items["pypi-workflow"].fix
    assert not items["pypi-name"].ok
    assert "pypi-version" not in items


def test_reuses_existing_publishing_workflow(tmp_path):
    project(tmp_path)
    existing = workflow(tmp_path, "publish.yml", TAGGED)
    assert pypi.workflow_path(tmp_path) == existing
    status = pypi.PyPITarget(get=getter(404)).setup_status(
        tmp_path, CFG, run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    assert "Workflow: .github/workflows/publish.yml" in status
    assert "  Workflow file name: publish.yml" in status


def test_add_workflow_writes_template_once_and_marks_pending(tmp_path):
    path = pypi.add_workflow(tmp_path)
    text = path.read_text()
    assert path.name == "release-pypi.yml"
    for part in ("environment: pypi", "id-token: write", "contents: read", "astral-sh/setup-uv",
                 "uv build", "pypa/gh-action-pypi-publish", "- \"v*\""):
        assert part in text
    assert release_config.pending(tmp_path) == [path.relative_to(tmp_path)] or \
        release_config.pending(tmp_path) == [path]
    with pytest.raises(FileExistsError):
        pypi.add_workflow(tmp_path)
    assert pypi.workflow_path(tmp_path) == path


def test_step_done_check_is_the_version_json(tmp_path):
    project(tmp_path)
    target = pypi.PyPITarget(get=getter(200))
    [step] = target.steps(tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert step.id == "pypi" and step.done_check() is True
    [step] = pypi.PyPITarget(get=getter(404)).steps(tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert step.done_check() is False
    [step] = pypi.PyPITarget(get=getter(OSError("x"))).steps(
        tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert step.done_check() is False


def test_step_waits_for_the_tag_run(tmp_path):
    project(tmp_path)
    workflow(tmp_path, "pub.yml", TAGGED)
    calls = []

    def run(args, cwd=None, **kw):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
            [{"status": "completed", "conclusion": "success", "url": "u"}]))

    [step] = pypi.PyPITarget(get=getter(404)).steps(tmp_path, CFG, "1.2.3", run=run, fetch=None)
    assert step.run(EVENT) is None
    assert calls[0][:6] == ["gh", "run", "list", "--workflow", "pub.yml", "--branch"]
    assert calls[0][6] == "v1.2.3"


def test_verify_retries_until_the_index_catches_up(tmp_path):
    project(tmp_path)
    answers = iter([404, 404, 200])
    sleeps = []
    target = pypi.PyPITarget(get=lambda url: next(answers), sleep=sleeps.append)
    assert target.verify(tmp_path, CFG, "1.2.3", run=None, fetch=None) == (True, "")
    assert sleeps == [15, 15]


def test_verify_gives_up_after_five_minutes(tmp_path):
    project(tmp_path)
    sleeps = []
    target = pypi.PyPITarget(get=getter(404), sleep=sleeps.append)
    good, text = target.verify(tmp_path, CFG, "1.2.3", run=None, fetch=None)
    assert not good and "5 minutes" in text
    assert sum(sleeps) == 300


def test_setup_status_lines(tmp_path):
    project(tmp_path)

    def run(args, cwd=None, **kw):
        return SimpleNamespace(returncode=0, stdout="https://github.com/octo/demo.git\n")

    lines = pypi.PyPITarget(get=getter(404)).setup_status(tmp_path, CFG, run=run)
    assert lines[0] == "Workflow: none yet"
    assert "Project demo: not on PyPI yet" in lines
    assert "  Owner: octo" in lines and "  Repository: demo" in lines
    assert "  Environment: pypi" in lines
    assert lines[-1] == "New project: use Add a pending publisher"
    on_pypi = pypi.PyPITarget(get=getter(200)).setup_status(tmp_path, CFG, run=run)
    assert "Project demo: on PyPI" in on_pypi
    assert not any("pending publisher" in line for line in on_pypi)
    down = pypi.PyPITarget(get=getter(OSError("x"))).setup_status(tmp_path, CFG, run=run)
    assert "Project demo: could not reach PyPI" in down
