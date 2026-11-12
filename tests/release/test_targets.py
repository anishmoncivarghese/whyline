import json
import threading
from types import SimpleNamespace

import pytest

from whyline.release import plan as release_plan
from whyline.release import targets, workflows
from whyline.release.config import ReleaseConfig, Targets
from whyline.release.engine import Step
from whyline.release.github import StepError
from whyline.release.ready import ReadyItem

EVENT = threading.Event()


class FakeTarget:
    def __init__(self, key, verdict=(True, "")):
        self.key = key
        self.title = key.upper()
        self.verdict = verdict
        self.ready = [ReadyItem(key, True, f"{key} ok")]

    def ready_items(self, root, cfg, version, *, run, fetch):
        return self.ready

    def steps(self, root, cfg, version, *, run, fetch):
        return [Step(f"{self.key}_publish", f"Publish {self.key}", True, lambda: False,
                     lambda cancel: None)]

    def verify(self, root, cfg, version, *, run, fetch):
        return self.verdict

    def setup_status(self, root, cfg, *, run):
        return []


@pytest.fixture
def registry(monkeypatch):
    fake = {}
    monkeypatch.setattr(targets, "REGISTRY", fake)
    return fake


def test_enabled_order(registry):
    for key in ("custom", "homebrew", "docker", "npm", "pypi"):
        registry[key] = FakeTarget(key)
    cfg = ReleaseConfig(targets=Targets(pypi=True, npm=True, docker=True, homebrew=True))
    assert [t.key for t in targets.enabled(cfg)] == ["pypi", "npm", "docker", "homebrew"]
    only = ReleaseConfig(targets=Targets(npm=True, pypi=False))
    assert [t.key for t in targets.enabled(only)] == ["npm"]


def write_workflow(root, name, text):
    path = root / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


TAGGED = "on:\n  push:\n    tags:\n      - 'v*'\njobs:\n  x:\n    run: pypi-publish\n"
BRANCHY = "on:\n  push:\n    branches: [main]\njobs:\n  x:\n    run: pypi-publish\n"


def test_find_publishing_picks_tag_workflow(tmp_path):
    write_workflow(tmp_path, "a.yml", BRANCHY)
    wanted = write_workflow(tmp_path, "b.yml", TAGGED)
    write_workflow(tmp_path, "c.yml", TAGGED.replace("pypi-publish", "other"))
    assert workflows.find_publishing(tmp_path, "pypi-publish") == wanted


def test_find_publishing_ignores_branch_only_and_missing(tmp_path):
    assert workflows.find_publishing(tmp_path, "pypi-publish") is None
    write_workflow(tmp_path, "a.yml", BRANCHY)
    # tags: appears, but under pull_request-style sibling, not under push
    write_workflow(tmp_path, "b.yml",
                   "on:\n  push:\n    branches: [main]\n  release:\n    tags:\n      - x\n"
                   "jobs:\n  x:\n    run: pypi-publish\n")
    assert workflows.find_publishing(tmp_path, "pypi-publish") is None


def test_write_template_refuses_overwrite(tmp_path):
    path = workflows.write_template(tmp_path, "release.yml", "one")
    assert path.read_text() == "one"
    with pytest.raises(FileExistsError):
        workflows.write_template(tmp_path, "release.yml", "two")
    assert path.read_text() == "one"


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, n):
        self.sleeps.append(n)
        self.t += n


def gh_run(sequence, jobs=None):
    items = iter(sequence)
    calls = []

    def run(args, cwd=None, **kw):
        calls.append(args)
        if args[:3] == ["gh", "run", "list"]:
            try:
                data = next(items)
            except StopIteration:
                data = sequence[-1]
            return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr="")
        if args[:3] == ["gh", "run", "view"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"jobs": jobs or []}),
                                   stderr="")
        raise AssertionError(args)

    run.calls = calls
    return run


def wait(tmp_path, run, cancel=EVENT, clock=None):
    clock = clock or Clock()
    seen = []
    result = workflows.wait_for_tag_run(
        tmp_path, "v1.2.3", ".github/workflows/release.yml", run=run, sleep=clock.sleep,
        now=clock.now, cancel_event=cancel, on_detail=seen.append)
    return result, clock, seen


def test_wait_passes_after_polling(tmp_path):
    run = gh_run([[], [{"status": "in_progress", "conclusion": ""}],
                  [{"status": "completed", "conclusion": "success", "url": "u"}]])
    result, clock, seen = wait(tmp_path, run)
    assert result is None and clock.sleeps == [15, 15]
    assert run.calls[0] == ["gh", "run", "list", "--workflow", "release.yml", "--branch",
                            "v1.2.3", "--json", "status,conclusion,url,databaseId"]
    assert "release.yml is in_progress" in seen


def test_wait_failure_names_job_and_url(tmp_path):
    run = gh_run(
        [[{"status": "completed", "conclusion": "failure", "url": "u/1", "databaseId": 9}]],
        jobs=[{"name": "build", "conclusion": "success"},
              {"name": "publish", "conclusion": "failure"}])
    with pytest.raises(StepError) as exc:
        wait(tmp_path, run)
    assert "publish" in str(exc.value) and "u/1" in str(exc.value)
    assert ["gh", "run", "view", "9", "--json", "jobs,name,url,attempt"] in run.calls


def test_wait_times_out_resumably(tmp_path):
    run = gh_run([[{"status": "in_progress", "conclusion": ""}]])
    clock = Clock()
    with pytest.raises(StepError) as exc:
        wait(tmp_path, run, clock=clock)
    assert "45 minutes" in str(exc.value) and "resume" in str(exc.value)
    assert clock.t >= 45 * 60


def test_wait_cancel(tmp_path):
    cancel = threading.Event()
    cancel.set()
    result, _, _ = wait(tmp_path, gh_run([[]]), cancel=cancel)
    assert result is False


def build(tmp_path, cfg):
    return release_plan.build(tmp_path, cfg, "1.2.3", telegram_target=lambda: None)


def test_plan_build_inserts_target_steps_and_verify(tmp_path, registry):
    registry["pypi"] = FakeTarget("pypi")
    registry["npm"] = FakeTarget("npm")
    registry["docker"] = FakeTarget("docker")
    cfg = ReleaseConfig(targets=Targets(pypi=True, npm=True))
    ids = [s.id for s in build(tmp_path, cfg).steps]
    assert ids == ["ready", "version", "notes", "commit", "checks", "push", "ci", "tag",
                   "github_release", "pypi_publish", "npm_publish", "verify", "after"]
    verify = build(tmp_path, cfg).steps[-2]
    assert verify.done_check() is False and not verify.irreversible


def test_plan_build_without_targets_has_no_verify(tmp_path, registry):
    assert "verify" not in [s.id for s in build(tmp_path, ReleaseConfig()).steps]


def test_verify_lists_failures(tmp_path, registry):
    registry["pypi"] = FakeTarget("pypi", (False, "not on the index"))
    registry["npm"] = FakeTarget("npm")
    registry["docker"] = FakeTarget("docker", (False, ""))
    cfg = ReleaseConfig(targets=Targets(pypi=True, npm=True, docker=True))
    verify = next(s for s in build(tmp_path, cfg).steps if s.id == "verify")
    with pytest.raises(StepError) as exc:
        verify.run(EVENT)
    text = str(exc.value)
    assert "PYPI: not on the index" in text and "DOCKER" in text and "NPM" not in text


def test_verify_passes_when_all_pass(tmp_path, registry):
    registry["pypi"] = FakeTarget("pypi")
    cfg = ReleaseConfig(targets=Targets(pypi=True))
    verify = next(s for s in build(tmp_path, cfg).steps if s.id == "verify")
    assert verify.run(EVENT) is None


def test_ready_check_includes_target_items(tmp_path, registry):
    bad = FakeTarget("pypi")
    bad.ready = [ReadyItem("pypi", False, "no token", "Add one")]
    registry["pypi"] = bad
    cfg = ReleaseConfig(targets=Targets(pypi=True))
    plan = release_plan.build(tmp_path, cfg, "1.2.3", ready_check=lambda: [],
                              telegram_target=lambda: None)
    with pytest.raises(StepError) as exc:
        plan.steps[0].run(EVENT)
    assert "no token. Add one" in str(exc.value)
