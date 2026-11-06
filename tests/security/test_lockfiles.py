from __future__ import annotations

from pathlib import Path

from whyline.security.lockfiles import Dependency, normalize_pypi, read_all, read_report

FIXTURES = Path(__file__).parent / "fixtures" / "lockfiles"


def _by_name(root: str) -> dict[str, Dependency]:
    return {d.name: d for d in read_all(FIXTURES / root)}


def test_normalize_pypi_follows_pep_503() -> None:
    assert normalize_pypi("Django_Rest.Framework") == "django-rest-framework"
    assert normalize_pypi("a--b__c") == "a-b-c"


def test_uv_lock_public_private_and_root_skipped() -> None:
    deps = _by_name("uv")
    assert "myapp" not in deps
    assert deps["requests"].public and deps["requests"].version == "2.32.0"
    assert deps["typing-extensions"].public
    for private in ("internal-lib", "local-tool", "gitdep", "pathdep"):
        assert not deps[private].public
    assert {d.ecosystem for d in deps.values()} == {"PyPI"}
    assert {d.source_file for d in deps.values()} == {"uv.lock"}


def test_poetry_lock() -> None:
    deps = _by_name("poetry")
    assert deps["django-rest-framework"].public
    assert not deps["corp-lib"].public
    assert not deps["gitpkg"].public


def test_requirements_pins_and_unpinned_report() -> None:
    report = read_report(FIXTURES / "reqs")
    deps = {d.name: d for d in report.dependencies}
    assert deps["flask-login"].version == "0.6.3"
    assert deps["requests"].version == "2.31.0"
    assert deps["pytest"].version == "8.0.0"
    assert deps["pytest"].source_file == "requirements-dev.txt"
    assert all(d.public for d in deps.values())
    unpinned = {u.line for u in report.unpinned}
    assert unpinned == {
        "numpy>=1.26",
        "-e ./local",
        "git+https://github.com/example/x.git#egg=x",
        "pandas==2.*",
    }
    assert all(u.note.endswith("unpinned, not checked") for u in report.unpinned)


def test_package_lock_v3() -> None:
    deps = _by_name("npm")
    assert "webapp" not in deps
    assert deps["left-pad"].public
    assert deps["@scope/pkg"].public
    assert deps["nested"].public and deps["nested"].version == "0.1.0"
    assert not deps["corp"].public
    assert not deps["shared"].public  # link: true
    assert not deps["localdep"].public  # file:
    assert {d.ecosystem for d in deps.values()} == {"npm"}


def test_pnpm_lock() -> None:
    deps = _by_name("pnpm")
    assert deps["left-pad"].public and deps["left-pad"].version == "1.3.0"
    assert deps["@scope/pkg"].version == "2.0.0" and deps["@scope/pkg"].public
    assert not deps["corp"].public
    assert not deps["localdep"].public
    assert len([d for d in read_all(FIXTURES / "pnpm") if d.name == "left-pad"]) == 1


def test_yarn_classic_lock() -> None:
    deps = _by_name("yarn")
    assert deps["@scope/pkg"].version == "2.0.1" and deps["@scope/pkg"].public
    assert deps["left-pad"].public
    assert not deps["corp"].public
    assert "version" not in deps  # nested dependency lists are not packages


def test_yarn_berry_lock_skips_workspace_root() -> None:
    deps = _by_name("yarn_berry")
    assert set(deps) == {"left-pad"}
    assert deps["left-pad"].public


def test_read_all_walks_and_skips_vendored_dirs(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "package-lock.json").write_text(
        '{"packages": {"node_modules/y": {"version": "1", "resolved": "https://registry.npmjs.org/y"}}}'
    )
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "requirements.txt").write_text("foo==1.0\n")
    (tmp_path / "poetry.lock").write_text("not [valid toml")
    deps = read_all(tmp_path)
    assert [(d.name, d.source_file) for d in deps] == [("foo", "sub/requirements.txt")]
