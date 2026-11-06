"""The optional pre-commit hook, against temp git repos and a real commit."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from whyline.security import cli, hook

KEY = "AKIA" + "QYLPMN5HHQKB3XZT"


def git(repo: Path, *args: str, env=None, check=True):
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True, env=env)


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    (work / "a.txt").write_text("hello\n")
    git(work, "add", ".")
    git(work, "commit", "-qm", "init")
    return work


@pytest.fixture
def hook_env(tmp_path):
    """A PATH where `whyline` runs this checkout's code."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "whyline"
    stub.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m whyline "$@"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    src = str(Path(hook.__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_install_writes_an_executable_hook(repo):
    assert not hook.installed(repo)
    path = hook.install(repo)
    assert path == repo / ".git" / "hooks" / "pre-commit"
    assert hook.COMMAND in path.read_text()
    assert path.stat().st_mode & stat.S_IXUSR
    assert hook.installed(repo)
    hook.install(repo)  # again is fine


def test_uninstall_removes_only_our_hook(repo):
    hook.install(repo)
    assert hook.uninstall(repo) is True
    assert not hook.installed(repo)
    assert hook.uninstall(repo) is False


def test_foreign_hook_is_kept(repo):
    path = repo / ".git" / "hooks" / "pre-commit"
    path.write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(hook.HookError) as err:
        hook.install(repo)
    assert hook.COMMAND in str(err.value)
    assert path.read_text() == "#!/bin/sh\necho mine\n"
    assert hook.foreign(repo) and not hook.installed(repo)
    assert hook.uninstall(repo) is False
    assert path.exists()
    assert hook.COMMAND in hook.set_installed(repo, True)


def test_not_a_git_repo(tmp_path):
    assert not hook.installed(tmp_path)
    with pytest.raises(hook.HookError):
        hook.install(tmp_path)


def test_cli_install_uninstall_status(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    import argparse

    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())

    def go(*argv):
        return cli.run(parser.parse_args(["security", "hook", *argv]))

    assert go("install") == 0 and hook.installed(repo)
    assert go("status") == 0 and "on" in capsys.readouterr().out
    assert go("uninstall") == 0 and not hook.installed(repo)


def test_commit_blocked_on_a_staged_secret_with_masked_output(repo, hook_env):
    hook.install(repo)
    (repo / "cfg.py").write_text(f'V = "{KEY}"\n')
    git(repo, "add", ".")
    done = git(repo, "commit", "-qm", "oops", env=hook_env, check=False)
    assert done.returncode != 0
    out = done.stdout + done.stderr
    assert hook.STOP_LINE in out
    assert "cfg.py" in out
    assert KEY not in out
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_commit_passes_on_a_clean_change(repo, hook_env):
    hook.install(repo)
    (repo / "b.txt").write_text("fine\n")
    git(repo, "add", ".")
    done = git(repo, "commit", "-qm", "clean", env=hook_env, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_hook_mode_prints_only_blocking_secrets(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    (repo / "cfg.py").write_text(f'V = "{KEY}"\n')
    git(repo, "add", ".")
    import argparse

    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    code = cli.run(parser.parse_args(["security", "scan", "--staged", "--hook"]))
    out = capsys.readouterr().out
    assert code == 1
    assert KEY not in out and "Summary:" not in out and "fingerprint" not in out
    assert out.rstrip().endswith(hook.STOP_LINE)


def test_hook_mode_off_setting_exits_zero_at_once(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    (repo / ".whyline").mkdir()
    (repo / ".whyline" / "release.toml").write_text('[security]\nsecrets = "off"\n')
    from whyline.release import config as release_config

    if not (repo / release_config.CONFIG_PATH).exists():
        (repo / release_config.CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
        (repo / release_config.CONFIG_PATH).write_text('[security]\nsecrets = "off"\n')
    (repo / "cfg.py").write_text(f'V = "{KEY}"\n')
    git(repo, "add", ".")
    import argparse

    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    assert cli.run(parser.parse_args(["security", "scan", "--staged", "--hook"])) == 0
    assert capsys.readouterr().out == ""


def test_hook_needs_staged(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    import argparse

    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    assert cli.run(parser.parse_args(["security", "scan", "--hook"])) == 1
