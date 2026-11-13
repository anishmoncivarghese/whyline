import json
from dataclasses import replace
from pathlib import Path

import pytest

from whyline.release import config
from whyline.release.config import (
    ConfigError,
    CustomTarget,
    DockerTarget,
    HomebrewTarget,
    ReleaseConfig,
    Targets,
)
from whyline.security.settings import SecuritySettings


def test_security_defaults_and_errors(tmp_path):
    assert config.load(tmp_path).security == SecuritySettings()
    for body in ('secrets = "maybe"', 'dependencies = "block-all"', "pre_commit = 1", "audit = 3"):
        write_toml(tmp_path, f"[security]\n{body}\n")
        with pytest.raises(ConfigError, match="security"):
            config.load(tmp_path)


def test_save_rejects_bad_security(tmp_path):
    bad = replace(ReleaseConfig(), security=SecuritySettings(contents="nope"))
    with pytest.raises(ConfigError, match="security.contents"):
        config.save(tmp_path, bad)


def write_toml(root: Path, text: str) -> None:
    path = root / ".whyline" / "release.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def full() -> ReleaseConfig:
    return ReleaseConfig(
        mode="auto",
        branch="trunk",
        start_after_plan=True,
        bring_in_main=False,
        checks=("uv run pytest -q", 'echo "quoted" \\ back'),
        ci_ignore=("test (windows-latest, 3.13)",),
        on_no_runner="rerun once",
        notes="notes/v{version}.md",
        version_files=("VERSION", "docs/v.txt"),
        after=("uv tool upgrade whyline",),
        security=SecuritySettings(
            secrets="warn",
            dependencies="off",
            contents="off",
            history_scanned="2026-11-01",
            pre_commit=True,
            audit="block-confirmed",
        ),
        targets=Targets(
            github=True,
            pypi=True,
            npm=True,
            docker=True,
            homebrew=True,
            docker_options=DockerTarget(registries=("ghcr", "dockerhub"), image="me/app"),
            homebrew_options=HomebrewTarget(tap="me/homebrew-tap", formula="app"),
            custom=(
                CustomTarget("docs", "make publish-docs", "make check-docs"),
                CustomTarget("tab\tname", 'say "hi"\nnow'),
            ),
        ),
    )


def test_defaults_when_file_missing(tmp_path):
    cfg = config.load(tmp_path)
    assert cfg == ReleaseConfig()
    assert cfg.mode == "ask"
    assert cfg.branch == "main"
    assert cfg.start_after_plan is False
    assert cfg.bring_in_main is True
    assert cfg.checks == ()
    assert cfg.notes == "docs/releases/v{version}.md"
    assert cfg.targets.github is True
    assert not (cfg.targets.pypi or cfg.targets.npm or cfg.targets.docker or cfg.targets.homebrew)
    assert cfg.targets.docker_options.registries == ("ghcr",)
    assert cfg.targets.custom == ()


def test_round_trip_every_field(tmp_path):
    cfg = full()
    config.save(tmp_path, cfg)
    assert config.load(tmp_path) == cfg


def test_round_trip_defaults(tmp_path):
    config.save(tmp_path, ReleaseConfig())
    assert config.load(tmp_path) == ReleaseConfig()


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    config.save(tmp_path, full())
    config.save(tmp_path, ReleaseConfig())
    names = [p.name for p in (tmp_path / ".whyline").iterdir()]
    assert names == ["release.toml"]


def test_save_rejects_bad_mode(tmp_path):
    with pytest.raises(ConfigError, match="release.mode"):
        config.save(tmp_path, replace(ReleaseConfig(), mode="fast"))
    assert not (tmp_path / ".whyline" / "release.toml").exists()


def test_error_bad_mode(tmp_path):
    write_toml(tmp_path, '[release]\nmode = "fast"\n')
    with pytest.raises(ConfigError, match="release.mode"):
        config.load(tmp_path)


def test_error_checks_not_a_list(tmp_path):
    write_toml(tmp_path, '[release]\nchecks = "pytest"\n')
    with pytest.raises(ConfigError, match="release.checks"):
        config.load(tmp_path)


def test_error_custom_without_name(tmp_path):
    write_toml(tmp_path, '[[targets.custom]]\nrun = "make"\n')
    with pytest.raises(ConfigError, match=r"targets.custom\[0\].name"):
        config.load(tmp_path)


def test_error_custom_without_run(tmp_path):
    write_toml(tmp_path, '[[targets.custom]]\nname = "docs"\n')
    with pytest.raises(ConfigError, match=r"targets.custom\[0\].run"):
        config.load(tmp_path)


def test_error_duplicate_custom_name(tmp_path):
    write_toml(
        tmp_path,
        '[[targets.custom]]\nname = "docs"\nrun = "a"\n\n'
        '[[targets.custom]]\nname = "docs"\nrun = "b"\n',
    )
    with pytest.raises(ConfigError, match="targets.custom.name"):
        config.load(tmp_path)


def test_error_target_flag_not_bool(tmp_path):
    write_toml(tmp_path, '[targets]\npypi = "yes"\n')
    with pytest.raises(ConfigError, match="targets.pypi"):
        config.load(tmp_path)


def test_error_invalid_toml(tmp_path):
    write_toml(tmp_path, "[release\n")
    with pytest.raises(ConfigError, match="release.toml"):
        config.load(tmp_path)


def test_detect_python_uv_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
    (tmp_path / "uv.lock").write_text("")
    cfg = config.detect(tmp_path)
    assert cfg.targets.github and cfg.targets.pypi
    assert not (cfg.targets.npm or cfg.targets.docker)
    assert cfg.checks == ("uv run pytest -q",)


def test_detect_uv_by_tool_table(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n[tool.uv]\n')
    assert config.detect(tmp_path).checks == ("uv run pytest -q",)


def test_detect_pyproject_without_project_table(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.black]\nline-length = 88\n")
    cfg = config.detect(tmp_path)
    assert not cfg.targets.pypi
    assert cfg.checks == ()


def test_detect_npm_with_test_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    cfg = config.detect(tmp_path)
    assert cfg.targets.npm
    assert cfg.checks == ("npm test",)


def test_detect_private_npm_package_is_not_published(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"private": True}))
    cfg = config.detect(tmp_path)
    assert not cfg.targets.npm
    assert cfg.checks == ()


def test_detect_npm_without_test_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    cfg = config.detect(tmp_path)
    assert cfg.targets.npm
    assert cfg.checks == ()


def test_detect_docker(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    cfg = config.detect(tmp_path)
    assert cfg.targets.docker and cfg.targets.github
    assert not (cfg.targets.pypi or cfg.targets.npm)


def test_detect_empty_project_is_github_only(tmp_path):
    cfg = config.detect(tmp_path)
    assert cfg == ReleaseConfig()


def test_normalise_ticks_github_when_any_target_is_ticked():
    for name in ("pypi", "npm", "docker", "homebrew"):
        cfg = ReleaseConfig(targets=Targets(github=False, **{name: True}))
        assert config.normalise(cfg).targets.github is True
    custom = ReleaseConfig(targets=Targets(github=False, custom=(CustomTarget("a", "b"),)))
    assert config.normalise(custom).targets.github is True


def test_normalise_leaves_other_configs_alone():
    cfg = ReleaseConfig(targets=Targets(github=False))
    assert config.normalise(cfg) == cfg
    assert config.normalise(full()) == full()


def test_pending_add_read_clear(tmp_path):
    (tmp_path / ".git").mkdir()
    wf = tmp_path / ".github" / "workflows" / "release.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("on: push\n")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")

    assert config.pending(tmp_path) == []
    config.add_pending(tmp_path, wf)  # absolute path is stored relative
    config.add_pending(tmp_path, "Dockerfile")
    config.add_pending(tmp_path, "Dockerfile")  # no duplicates
    assert config.pending(tmp_path) == [Path(".github/workflows/release.yml"), Path("Dockerfile")]

    config.clear_pending(tmp_path)
    assert config.pending(tmp_path) == []
    config.clear_pending(tmp_path)  # clearing twice is fine


def test_pending_drops_a_missing_path(tmp_path):
    (tmp_path / ".git").mkdir()
    keep = tmp_path / "Dockerfile"
    keep.write_text("FROM scratch\n")
    gone = tmp_path / "ci.yml"
    gone.write_text("x")
    config.add_pending(tmp_path, keep)
    config.add_pending(tmp_path, gone)
    gone.unlink()

    assert config.pending(tmp_path) == [Path("Dockerfile")]
    stored = json.loads((tmp_path / ".git" / "whyline-release" / "pending.json").read_text())
    assert stored == ["Dockerfile"]


def test_pending_ignores_a_corrupt_file(tmp_path):
    path = tmp_path / ".git" / "whyline-release" / "pending.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json")
    assert config.pending(tmp_path) == []


def test_bring_in_main_key(tmp_path):
    write_toml(tmp_path, "[release]\nbring_in_main = false\n")
    assert config.load(tmp_path).bring_in_main is False
    config.save(tmp_path, ReleaseConfig(bring_in_main=False))
    assert "bring_in_main = false" in (tmp_path / ".whyline" / "release.toml").read_text()
    write_toml(tmp_path, '[release]\nbring_in_main = "no"\n')
    with pytest.raises(config.ConfigError, match="release.bring_in_main"):
        config.load(tmp_path)


def test_on_no_runner_defaults_to_ask_and_rejects_other_values(tmp_path):
    assert config.load(tmp_path).on_no_runner == "ask"
    write_toml(tmp_path, '[release]\non_no_runner = "sometimes"\n')
    with pytest.raises(ConfigError, match="release.on_no_runner"):
        config.load(tmp_path)
    with pytest.raises(ConfigError, match="release.on_no_runner"):
        config.save(tmp_path, ReleaseConfig(on_no_runner="sometimes"))
