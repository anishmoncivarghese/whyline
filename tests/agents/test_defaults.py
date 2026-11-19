from pathlib import Path

import pytest

from whyline import cli
from whyline.agents import defaults, paths


def _stored() -> str:
    return paths.settings_file("defaults.toml").read_text(encoding="utf-8")


def test_default_with_no_file_is_home(home):
    assert defaults.folder() == home


def test_missing_folder_falls_back_to_home(home):
    target = home / "work"
    target.mkdir()
    defaults.set_folder(target)
    assert defaults.folder() == target
    target.rmdir()
    assert defaults.folder() == home


def test_refuses_a_path_that_is_not_a_folder(home):
    a_file = home / "file.txt"
    a_file.write_text("x")
    for bad in (home / "nope", a_file):
        with pytest.raises(defaults.DefaultsError):
            defaults.set_folder(bad)
    assert not paths.settings_file("defaults.toml").exists()


def test_stores_tilde_for_the_home_folder(home):
    (home / "work").mkdir()
    defaults.set_folder(home / "work")
    assert 'default_folder = "~/work"' in _stored()
    defaults.set_folder(home)
    assert 'default_folder = "~"' in _stored()
    assert defaults.folder() == home


def test_folder_outside_home_stored_as_is(home, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    defaults.set_folder(outside)
    assert str(outside) in _stored()
    assert defaults.folder() == outside


def test_cli_prints_and_sets(home, capsys):
    (home / "work").mkdir()
    assert cli.main(["agents", "settings", "default-folder"]) == 0
    assert capsys.readouterr().out.strip() == str(home)
    assert cli.main(["agents", "settings", "default-folder", "~/work"]) == 0
    capsys.readouterr()
    assert cli.main(["agents", "settings", "default-folder"]) == 0
    assert capsys.readouterr().out.strip() == str(home / "work")


def test_cli_refuses_a_missing_folder(home, capsys):
    assert cli.main(["agents", "settings", "default-folder", str(home / "nope")]) != 0
    assert "not a folder" in capsys.readouterr().err
    assert defaults.folder() == Path(home)
