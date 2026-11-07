import json
import threading
from types import SimpleNamespace

import pytest

from whyline.release import config as release_config
from whyline.release import targets
from whyline.release.config import DockerTarget as DockerOptions
from whyline.release.config import ReleaseConfig, Targets
from whyline.release.github import StepError
from whyline.release.targets import docker

EVENT = threading.Event()
ORIGIN = "https://github.com/Octo/Demo.git\n"
TAGGED = ("on:\n  push:\n    tags:\n      - 'v*'\njobs:\n  x:\n    steps:\n"
          "      - uses: docker/build-push-action@v6\n")


def cfg(*regs, image=""):
    return ReleaseConfig(targets=Targets(docker=True, docker_options=DockerOptions(
        registries=regs or ("ghcr",), image=image)))


def runner(secrets=None, calls=None, manifest=0):
    def run(args, cwd=None, **kw):
        if calls is not None:
            calls.append((list(args), kw))
        if args[:3] == ["git", "remote", "get-url"]:
            return SimpleNamespace(returncode=0, stdout=ORIGIN, stderr="")
        if args[:3] == ["gh", "secret", "list"]:
            if secrets is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="no")
            return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
                [{"name": n} for n in secrets]))
        if args[:3] == ["docker", "manifest", "inspect"]:
            return SimpleNamespace(returncode=manifest, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


def ready(tmp_path, config, run):
    return {i.key: i for i in docker.DockerTarget().ready_items(
        tmp_path, config, "1.2.3", run=run, fetch=None)}


def test_registered():
    assert targets.REGISTRY["docker"].key == "docker"


def test_template_with_ghcr_only(tmp_path):
    path = docker.add_workflow(tmp_path, cfg(), run=runner())
    text = path.read_text()
    assert path.name == "release-docker.yml"
    for part in ("- \"v*\"", "contents: read", "packages: write",
                 "docker/setup-buildx-action", "docker/login-action",
                 "secrets.GITHUB_TOKEN", "docker/metadata-action",
                 "type=semver,pattern=v{{version}}", "type=semver,pattern={{version}}",
                 "type=raw,value=latest", "docker/build-push-action", "push: true",
                 "ghcr.io/octo/demo"):
        assert part in text
    assert "DOCKERHUB" not in text and "@@" not in text
    assert release_config.pending(tmp_path)
    with pytest.raises(FileExistsError):
        docker.add_workflow(tmp_path, cfg(), run=runner())


def test_template_with_docker_hub_and_configured_image(tmp_path):
    path = docker.add_workflow(tmp_path, cfg("ghcr", "dockerhub", image="Me/Thing"),
                               run=runner())
    text = path.read_text()
    assert "secrets.DOCKERHUB_USERNAME" in text and "secrets.DOCKERHUB_TOKEN" in text
    assert "ghcr.io/me/thing" in text and "            me/thing\n" in text
    assert "@@" not in text


def test_template_docker_hub_only_has_no_ghcr(tmp_path):
    text = docker.render_template("me/thing", ("dockerhub",))
    assert "ghcr.io" not in text and "secrets.GITHUB_TOKEN" not in text
    assert "DOCKERHUB_TOKEN" in text


def test_ready_all_good(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "pub.yml").write_text(TAGGED)
    items = ready(tmp_path, cfg("ghcr", "dockerhub"),
                  runner(["DOCKERHUB_USERNAME", "DOCKERHUB_TOKEN"]))
    assert all(i.ok for i in items.values())
    assert set(items) == {"docker-file", "docker-workflow", "docker-secrets"}
    assert "pub.yml" in items["docker-workflow"].text


def test_ready_missing_everything(tmp_path):
    items = ready(tmp_path, cfg("dockerhub"), runner(["DOCKERHUB_USERNAME"]))
    assert not items["docker-file"].ok and "Draft Dockerfile" in items["docker-file"].fix
    assert not items["docker-workflow"].ok and "Add workflow" in items["docker-workflow"].fix
    assert not items["docker-secrets"].ok and "DOCKERHUB_TOKEN" in items["docker-secrets"].text


def test_ready_skips_secrets_for_ghcr_and_handles_gh_failure(tmp_path):
    assert "docker-secrets" not in ready(tmp_path, cfg(), runner())
    item = ready(tmp_path, cfg("dockerhub"), runner(None))["docker-secrets"]
    assert not item.ok and "could not list" in item.text


def test_secrets_go_on_stdin_never_in_argv(tmp_path):
    sentinel = "tok-SENTINEL-9f3a"
    calls = []
    docker.store_dockerhub_secrets(tmp_path, "octo", sentinel, run=runner(calls=calls))
    assert [c[0] for c in calls] == [["gh", "secret", "set", "DOCKERHUB_USERNAME"],
                                     ["gh", "secret", "set", "DOCKERHUB_TOKEN"]]
    assert [c[1]["input"] for c in calls] == ["octo", sentinel]
    assert sentinel not in json.dumps([c[0] for c in calls])


def test_store_secrets_refuses_empty_and_failure(tmp_path):
    with pytest.raises(StepError):
        docker.store_dockerhub_secrets(tmp_path, "", "x", run=runner())
    bad = lambda args, cwd=None, **kw: SimpleNamespace(returncode=1, stdout="", stderr="tok-X")
    with pytest.raises(StepError) as err:
        docker.store_dockerhub_secrets(tmp_path, "octo", "tok-X", run=bad)
    assert "tok-X" not in str(err.value)


def test_draft_goes_through_ask_agent_and_is_not_written(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "uv.lock").write_text("lock")
    (tmp_path / "app.py").write_text("print(1)\n")
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return "```dockerfile\nFROM python:3.13-slim\nUSER app\n```"

    text = docker.draft_dockerfile(tmp_path, ask_agent=ask)
    assert text == "FROM python:3.13-slim\nUSER app\n"
    assert len(prompts) == 1
    for part in ("non-root", "small", "app.py", "pyproject.toml", 'name = "demo"', "uv.lock"):
        assert part in prompts[0]
    assert not (tmp_path / "Dockerfile").exists()


def test_draft_empty_answer_raises(tmp_path):
    with pytest.raises(StepError):
        docker.draft_dockerfile(tmp_path, ask_agent=lambda p: "  ")


def test_step_waits_for_the_tag_run(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "pub.yml").write_text(TAGGED)
    calls = []

    def run(args, cwd=None, **kw):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
            [{"status": "completed", "conclusion": "success", "url": "u"}]))

    [step] = docker.DockerTarget().steps(tmp_path, cfg(), "1.2.3", run=run, fetch=None)
    assert step.id == "docker" and step.done_check() is False
    assert step.run(EVENT) is None
    assert calls[0][:6] == ["gh", "run", "list", "--workflow", "pub.yml", "--branch"]
    assert calls[0][6] == "v1.2.3"


def test_step_without_workflow_raises(tmp_path):
    [step] = docker.DockerTarget().steps(tmp_path, cfg(), "1.2.3", run=runner(), fetch=None)
    with pytest.raises(StepError):
        step.run(EVENT)


def test_verify_with_docker_inspects_the_manifest(tmp_path):
    calls = []
    target = docker.DockerTarget(which=lambda name: "/usr/bin/docker")
    assert target.verify(tmp_path, cfg(), "1.2.3", run=runner(calls=calls),
                         fetch=None) == (True, "")
    assert calls[-1][0] == ["docker", "manifest", "inspect", "ghcr.io/octo/demo:1.2.3"]
    good, text = target.verify(tmp_path, cfg("dockerhub"), "1.2.3",
                               run=runner(manifest=1), fetch=None)
    assert not good and "octo/demo:1.2.3" in text


def test_verify_without_docker_trusts_the_tag_run_with_a_note(tmp_path):
    calls = []
    target = docker.DockerTarget(which=lambda name: None)
    good, note = target.verify(tmp_path, cfg(), "1.2.3", run=runner(calls=calls), fetch=None)
    assert good and "tag run" in note
    assert not any(c[0][0] == "docker" for c in calls)


def test_setup_status_lines(tmp_path):
    lines = docker.DockerTarget().setup_status(
        tmp_path, cfg("ghcr", "dockerhub"), run=runner(["DOCKERHUB_TOKEN"]))
    assert "Dockerfile: none yet" in lines and "Workflow: none yet" in lines
    assert "Registries: GHCR, Docker Hub" in lines and "Image: octo/demo" in lines
    assert "Docker Hub secrets: missing DOCKERHUB_USERNAME" in lines
