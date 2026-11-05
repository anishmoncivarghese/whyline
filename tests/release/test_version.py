import json
from pathlib import Path

import pytest

from whyline.release.config import ReleaseConfig
from whyline.release.version import (
    VersionError,
    bump,
    current,
    files_to_change,
    validate,
    write,
)

PYPROJECT = '[project]\nname = "my-pkg"\nversion = "1.2.3"\ndependencies = ["x==1.2.3"]\n'


class FakeRun:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, argv, cwd=None):
        self.calls.append((list(argv), cwd))


def _src_project(root: Path) -> None:
    (root / "pyproject.toml").write_text(PYPROJECT)
    pkg = root / "src" / "my_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""Doc 1.2.3."""\n__version__ = "1.2.3"\n')


def test_current_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    assert current(tmp_path, ReleaseConfig()) == "1.2.3"


def test_current_from_package_json(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"version": "4.5.6"}))
    assert current(tmp_path, ReleaseConfig()) == "4.5.6"


def test_current_missing(tmp_path):
    with pytest.raises(VersionError, match="No version found"):
        current(tmp_path, ReleaseConfig())


@pytest.mark.parametrize(
    "kind,expected", [("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0")]
)
def test_bump(kind, expected):
    assert bump("1.2.3", kind) == expected


def test_bump_refuses_prerelease():
    with pytest.raises(VersionError, match="pre-release"):
        bump("1.2.3rc1", "patch")


def test_validate():
    for ok in ("1.2.3", "1.2.3rc1", "1.2.3-rc.2"):
        assert validate(ok) == ok
    for bad in ("1.2", "v1.2.3", "1.2.3-beta"):
        with pytest.raises(VersionError):
            validate(bad)


def test_files_to_change_src_layout(tmp_path):
    _src_project(tmp_path)
    (tmp_path / "package.json").write_text('{\n  "version": "1.2.3"\n}\n')
    (tmp_path / "VERSION").write_text("1.2.3\n")
    cfg = ReleaseConfig(version_files=("VERSION",))
    assert files_to_change(tmp_path, cfg) == [
        tmp_path / "pyproject.toml",
        tmp_path / "src" / "my_pkg" / "__init__.py",
        tmp_path / "package.json",
        tmp_path / "VERSION",
    ]


def test_write_changes_only_known_lines_and_locks(tmp_path):
    _src_project(tmp_path)
    (tmp_path / "package.json").write_text('{\n  "name": "x",\n  "version": "1.2.3"\n}\n')
    (tmp_path / "uv.lock").write_text("lock")
    (tmp_path / "package-lock.json").write_text("{}")
    run = FakeRun()
    changed = write(tmp_path, ReleaseConfig(), "1.3.0", run=run)
    pyproject = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "1.3.0"' in pyproject
    assert "x==1.2.3" in pyproject
    init = (tmp_path / "src" / "my_pkg" / "__init__.py").read_text()
    assert '__version__ = "1.3.0"' in init and "Doc 1.2.3." in init
    assert json.loads((tmp_path / "package.json").read_text())["version"] == "1.3.0"
    assert run.calls == [
        (["uv", "lock"], tmp_path),
        (["npm", "install", "--package-lock-only"], tmp_path),
    ]
    assert tmp_path / "uv.lock" in changed and tmp_path / "pyproject.toml" in changed


def test_write_version_files_first_matching_line(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    (tmp_path / "VERSION").write_text("v1.2.3 and 1.2.3\n")
    write(tmp_path, ReleaseConfig(version_files=("VERSION",)), "1.2.4", run=FakeRun())
    assert (tmp_path / "VERSION").read_text() == "v1.2.4 and 1.2.3\n"


def test_missing_old_version_leaves_everything_untouched(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    (tmp_path / "VERSION").write_text("0.0.1\n")
    run = FakeRun()
    with pytest.raises(VersionError, match="VERSION"):
        write(tmp_path, ReleaseConfig(version_files=("VERSION",)), "1.2.4", run=run)
    assert (tmp_path / "pyproject.toml").read_text() == PYPROJECT
    assert (tmp_path / "VERSION").read_text() == "0.0.1\n"
    assert run.calls == []
