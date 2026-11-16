import re
import tomllib
from pathlib import Path

import pytest

from whyline import cliargs
from whyline.agents import runner
from whyline.ideas import analyse
from whyline.release.plan import absolute_settings

ROOT = Path(__file__).resolve().parent.parent
LONG_TEXT = "x" * 300


def _antigravity() -> list[str]:
    from whyline_relay.recipes import RECIPES

    return list(RECIPES["antigravity"])


def test_settings_file_inline_json_and_paths():
    assert cliargs.settings_file('{"a": 1}') is None
    assert cliargs.settings_file('  {"a": 1}') is None
    assert cliargs.settings_file("a/b.json") == Path("a/b.json")
    assert cliargs.settings_file("~/s.json") == Path("~/s.json").expanduser()


def test_is_file_counts_oserror_as_false(tmp_path):
    (tmp_path / "s.json").write_text("{}")
    assert cliargs.is_file(tmp_path / "s.json")
    assert not cliargs.is_file(tmp_path / "nope.json")
    assert not cliargs.is_file(tmp_path / (LONG_TEXT * 5))


@pytest.mark.parametrize(
    "fn", [runner._without_missing_settings, analyse._without_missing_settings]
)
def test_inline_settings_pass_through_unchanged(fn, tmp_path):
    command = _antigravity()
    assert len(command[command.index("--settings") + 1]) > 700
    assert fn(command, tmp_path) == command
    equals = ["agy", "--settings=" + command[command.index("--settings") + 1], "-p"]
    assert fn(equals, tmp_path) == equals


def test_inline_settings_unchanged_by_absolute_settings(tmp_path):
    command = _antigravity()
    assert absolute_settings(command, tmp_path) == command
    equals = ["agy", "--settings=" + command[command.index("--settings") + 1], "-p"]
    assert absolute_settings(equals, tmp_path) == equals


@pytest.mark.parametrize(
    "fn", [runner._without_missing_settings, analyse._without_missing_settings]
)
def test_long_non_json_value_dropped_without_error(fn, tmp_path):
    assert fn(["c", "--settings", LONG_TEXT, "-p"], tmp_path) == ["c", "-p"]
    assert fn(["c", f"--settings={LONG_TEXT}", "-p"], tmp_path) == ["c", "-p"]


@pytest.mark.parametrize(
    "fn", [runner._without_missing_settings, analyse._without_missing_settings]
)
def test_real_file_kept_and_missing_file_dropped(fn, tmp_path):
    (tmp_path / "s.json").write_text("{}")
    assert fn(["c", "--settings", "s.json", "-p"], tmp_path) == ["c", "--settings", "s.json", "-p"]
    assert fn(["c", "--settings=s.json", "-p"], tmp_path) == ["c", "--settings=s.json", "-p"]
    assert fn(["c", "--settings", "no.json", "-p"], tmp_path) == ["c", "-p"]
    assert fn(["c", "--settings=no.json", "-p"], tmp_path) == ["c", "-p"]


def test_absolute_settings_makes_real_paths_absolute(tmp_path):
    assert absolute_settings(["c", "--settings", "s.json"], tmp_path) == [
        "c", "--settings", str(tmp_path / "s.json")]
    assert absolute_settings(["c", "--settings=s.json"], tmp_path) == [
        "c", f"--settings={tmp_path / 's.json'}"]


def test_pyproject_requires_relay_0_2_44_or_newer():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    specs = list(data["project"]["dependencies"])
    for group in data.get("dependency-groups", {}).values():
        specs += [s for s in group if isinstance(s, str)]
    for group in data["project"].get("optional-dependencies", {}).values():
        specs += group
    found = [s for s in specs if s.startswith("whyline-relay")]
    assert found
    for spec in found:
        match = re.search(r">=\s*(\d+)\.(\d+)\.(\d+)", spec)
        assert match, spec
        assert tuple(map(int, match.groups())) >= (0, 2, 44), spec
