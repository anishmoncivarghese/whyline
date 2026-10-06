import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    (root / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    return root
