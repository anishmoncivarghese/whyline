import subprocess
from pathlib import Path

import pytest


class Repo:
    """A temporary git repository with controllable commit timestamps."""

    def __init__(self, path: Path):
        self.path = path

    def _git(self, *args: str, env_extra: dict[str, str] | None = None) -> str:
        import os

        env = dict(os.environ)
        env.update(
            {
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@invalid",
            }
        )
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def commit(self, files: dict[str, str], message: str, epoch: int) -> str:
        for rel, content in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self._git("add", "-A")
        stamp = f"@{epoch} +0000"
        self._git(
            "commit",
            "-m",
            message,
            env_extra={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
        )
        return self._git("rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return Repo(tmp_path)
