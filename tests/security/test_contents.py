"""What each package would publish, with fake build tools.

Secrets are assembled from pieces so this file never holds a literal that a
secret scanner would flag.
"""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.security.contents import check, dockerignored, parse_dockerignore
from whyline.security.rules import load_rules

KEY = "AKIA" + "QYLPMN5HHQKB3XZT"


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def done(code=0, out="", err=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


def make_wheel(out: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(out / "pkg-1.0-py3-none-any.whl", "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)


def make_sdist(out: Path, members: dict[str, str]) -> None:
    with tarfile.open(out / "pkg-1.0.tar.gz", "w:gz") as archive:
        for name, text in members.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def python_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "pkg"\n')
    return tmp_path


def uv_runner(wheel=None, sdist=None):
    def run(args, **kwargs):
        assert args[:2] == ["uv", "build"]
        out = Path(args[args.index("--out-dir") + 1])
        assert out.parent.as_posix().endswith(".git/whyline-release/build")
        if wheel is not None:
            make_wheel(out, wheel)
        if sdist is not None:
            make_sdist(out, sdist)
        return done()

    return run


def test_wheel_with_env_file(tmp_path, rules):
    root = python_root(tmp_path)
    found = check(root, run=uv_runner(wheel={"pkg/__init__.py": "x = 1\n", "pkg/.env": "A=1\n"}), rules=rules)
    assert [(f.kind, f.rule, f.path) for f in found] == [
        ("contents", "deny-env", "pkg-1.0-py3-none-any.whl:pkg/.env")
    ]


def test_sdist_with_key_in_text_file(tmp_path, rules):
    root = python_root(tmp_path)
    found = check(root, run=uv_runner(sdist={"pkg-1.0/notes.txt": f"aws = {KEY}\n"}), rules=rules)
    assert len(found) == 1
    assert found[0].kind == "secret"
    assert found[0].path == "pkg-1.0.tar.gz:pkg-1.0/notes.txt"
    assert KEY not in found[0].preview


def test_build_dir_is_cleaned_up(tmp_path, rules):
    root = python_root(tmp_path)
    check(root, run=uv_runner(wheel={"pkg/a.py": "x\n"}), rules=rules)
    assert list((root / ".git/whyline-release/build").iterdir()) == []


def test_build_failure_is_one_warn_finding(tmp_path, rules):
    root = python_root(tmp_path)

    def run(args, **kwargs):
        return done(2, err="Building pkg\n\nerror: backend exploded\n")

    found = check(root, run=run, rules=rules)
    assert len(found) == 1
    assert found[0].title == "could not build python package: error: backend exploded"
    assert found[0].severity == "medium"
    assert found[0].kind == "contents"


def test_missing_tool_is_a_build_failure(tmp_path, rules):
    root = python_root(tmp_path)

    def run(args, **kwargs):
        raise FileNotFoundError("uv")

    found = check(root, run=run, rules=rules)
    assert [f.rule for f in found] == ["build-failed"]
    assert "could not build python package" in found[0].title


def test_no_project_files_means_no_findings(tmp_path, rules):
    (tmp_path / "pyproject.toml").write_text("[tool.x]\na = 1\n")
    assert check(tmp_path, run=uv_runner(), rules=rules) == []


def npm_runner(files):
    def run(args, **kwargs):
        assert args == ["npm", "pack", "--dry-run", "--json"]
        return done(out=json.dumps([{"files": [{"path": f} for f in files]}]))

    return run


def test_npm_pack_lists_npmrc(tmp_path, rules):
    (tmp_path / "package.json").write_text('{"name": "p"}')
    (tmp_path / "index.js").write_text("module.exports = 1\n")
    (tmp_path / ".npmrc").write_text("//registry.npmjs.org/:_authToken=abc\n")
    found = check(tmp_path, run=npm_runner(["package.json", "index.js", ".npmrc"]), rules=rules)
    assert [(f.rule, f.path) for f in found] == [("deny-npmrc-token", "npm:.npmrc")]


def test_private_npm_package_is_skipped(tmp_path, rules):
    (tmp_path / "package.json").write_text('{"name": "p", "private": true}')

    def run(args, **kwargs):
        raise AssertionError("npm must not run")

    assert check(tmp_path, run=run, rules=rules) == []


def test_npm_failure(tmp_path, rules):
    (tmp_path / "package.json").write_text('{"name": "p"}')

    def run(args, **kwargs):
        return done(1, err="npm ERR! boom\n")

    found = check(tmp_path, run=run, rules=rules)
    assert [f.title for f in found] == ["could not build npm package: npm ERR! boom"]


def ignored(patterns: str, path: str) -> bool:
    return dockerignored(path, parse_dockerignore(patterns))


def test_dockerignore_matching():
    assert ignored(".git\n", ".git/config")
    assert ignored("*.log\n", "a.log")
    assert not ignored("*.log\n", "sub/a.log")
    assert ignored("**/*.log\n", "sub/deep/a.log")
    assert ignored("**/*.log\n", "a.log")
    assert ignored("/build\n", "build/out.bin")
    assert not ignored("/build\n", "src/build/out.bin")
    assert ignored("# note\n\ndocs\n", "docs/readme.md")
    assert not ignored("docs\n", "docsify.md")


def test_dockerignore_negation_last_match_wins():
    text = "*.md\n!README.md\n"
    assert ignored(text, "CHANGELOG.md")
    assert not ignored(text, "README.md")
    assert ignored("!README.md\n*.md\n", "README.md")


def git_runner(files):
    def run(args, **kwargs):
        assert "ls-files" in args
        return done(out="\0".join(files) + "\0")

    return run


def test_docker_context_respects_dockerignore(tmp_path, rules):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / ".dockerignore").write_text(".env\nsecrets/\n!secrets/ok.txt\n")
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / "app.env.pem").write_text("x\n")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/ok.txt").write_text("fine\n")
    (tmp_path / "secrets/key.pem").write_text("x\n")
    files = ["Dockerfile", ".dockerignore", ".env", "app.env.pem", "secrets/ok.txt", "secrets/key.pem"]
    found = check(tmp_path, run=git_runner(files), rules=rules)
    assert [(f.rule, f.path) for f in found] == [("deny-pem", "docker:app.env.pem")]


def test_docker_without_dockerignore_warns(tmp_path, rules):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / ".env").write_text("A=1\n")
    found = check(tmp_path, run=git_runner(["Dockerfile", ".env"]), rules=rules)
    assert {(f.rule, f.severity) for f in found} == {("no-dockerignore", "medium"), ("deny-env", "high")}


def test_docker_git_failure(tmp_path, rules):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / ".dockerignore").write_text("\n")

    def run(args, **kwargs):
        raise subprocess.SubprocessError("no git")

    found = check(tmp_path, run=run, rules=rules)
    assert [f.title for f in found] == ["could not build docker context: git ls-files failed"]
