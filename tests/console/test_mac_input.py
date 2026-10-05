import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from whyline.console import mac_input


def _result(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


def test_available(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/osascript" if cmd == "osascript" else None)
    assert mac_input.available() is True

    monkeypatch.setattr(sys, "platform", "linux")
    assert mac_input.available() is False

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    assert mac_input.available() is False


def test_pick_files_returns_the_chosen_paths():
    run = lambda argv, **kw: _result(0, "/picked/x.png\n/picked/My Doc.pdf\n")
    assert mac_input.pick_files(run=run) == [Path("/picked/x.png"), Path("/picked/My Doc.pdf")]


def test_cancelling_the_picker_returns_nothing():
    run = lambda argv, **kw: _result(1, "", "execution error: User canceled. (-128)")
    assert mac_input.pick_files(run=run) == []


def test_other_picker_errors_raise():
    run = lambda argv, **kw: _result(1, "", "boom")
    with pytest.raises(mac_input.PickerError, match="boom"):
        mac_input.pick_files(run=run)


def test_paste_image_writes_the_target(tmp_path):
    target = tmp_path / "shot.png"

    def run(argv, **kw):
        target.write_bytes(b"\x89PNG")
        return _result(0)

    assert mac_input.paste_image(target, run=run) is True
    assert target.exists()


def test_no_image_on_the_clipboard_leaves_nothing_behind(tmp_path):
    target = tmp_path / "shot.png"

    def run(argv, **kw):
        target.write_bytes(b"")
        return _result(1, "", "Can't make some data into the expected type. (-1700)")

    assert mac_input.paste_image(target, run=run) is False
    assert not target.exists()


def test_the_target_path_is_passed_as_an_argument_not_spliced_into_the_script(tmp_path):
    seen = []
    target = tmp_path / "a 'b.png"  # a quote that is legal on every OS
    mac_input.paste_image(target, run=lambda argv, **kw: seen.append(argv) or _result(1))
    assert str(target) == seen[0][-1]
