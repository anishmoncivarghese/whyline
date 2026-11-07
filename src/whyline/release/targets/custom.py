"""Custom release targets: commands from `[[targets.custom]]` in release.toml. Each one
runs as an irreversible step with the version in its environment; an optional verify
command says whether it already happened and whether it worked."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from whyline.release import targets
from whyline.release.config import CustomTarget as Entry
from whyline.release.config import ReleaseConfig
from whyline.release.engine import Step
from whyline.release.github import StepError
from whyline.release.ready import Fetch, ReadyItem, Run

KEY = "custom"
TAIL_LINES = 20
NO_VERIFY = "no verify command"

# shell(command, root, env, on_line) -> (returncode, all output lines)
Shell = Callable[[str, Path, dict[str, str], Callable[[str], None]], "tuple[int, list[str]]"]
Which = Callable[[str], str | None]


def shell_run(command: str, root: Path, env: dict[str, str],
              on_line: Callable[[str], None]) -> tuple[int, list[str]]:
    proc = subprocess.Popen(
        command, shell=True, cwd=root, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        lines.append(line)
        on_line(line)
    return proc.wait(), lines


def release_env(version: str) -> dict[str, str]:
    return {**os.environ, "WHYLINE_RELEASE_VERSION": version,
            "WHYLINE_RELEASE_TAG": f"v{version}"}


class CustomTarget:
    key = KEY
    title = "Custom"

    def __init__(self, shell: Shell = shell_run, which: Which = shutil.which,
                 on_line: Callable[[str], None] | None = None) -> None:
        self._shell = shell
        self._which = which
        self.on_line = on_line or (lambda line: None)

    def _found(self, root: Path, command: str) -> tuple[bool, str]:
        try:
            words = shlex.split(command)
        except ValueError:
            return False, "the command cannot be parsed"
        if not words:
            return False, "the command is empty"
        first = words[0]
        if os.sep in first:
            path = Path(first).expanduser()
            return (root / path).exists(), first
        return self._which(first) is not None, first

    def ready_items(self, root: Path, cfg: ReleaseConfig, version: str, *,
                    run: Run, fetch: Fetch) -> list[ReadyItem]:
        root = Path(root)
        items = []
        for entry in cfg.targets.custom:
            found, first = self._found(root, entry.run)
            items.append(ReadyItem(
                f"custom-{entry.name}", found,
                f"{first} is available for {entry.name}" if found
                else f"{first} was not found for {entry.name}",
                "" if found else f"Install {first} or fix the run command of {entry.name}"))
        return items

    def _check(self, entry: Entry, root: Path, version: str) -> bool:
        code, _ = self._shell(entry.verify, root, release_env(version), lambda line: None)
        return code == 0

    def steps(self, root: Path, cfg: ReleaseConfig, version: str, *,
              run: Run, fetch: Fetch) -> list[Step]:
        root = Path(root)

        def build(entry: Entry) -> Step:
            def done() -> bool:
                return bool(entry.verify.strip()) and self._check(entry, root, version)

            def go(cancel) -> None:
                code, lines = self._shell(entry.run, root, release_env(version), self.on_line)
                if code != 0:
                    tail = "\n".join(lines[-TAIL_LINES:]) or "no output"
                    raise StepError(f"{entry.name} exited with {code}: {tail}")

            return Step(f"custom:{entry.name}", f"Run custom target {entry.name}", True, done, go)

        return [build(entry) for entry in cfg.targets.custom]

    def verify(self, root: Path, cfg: ReleaseConfig, version: str, *,
               run: Run, fetch: Fetch) -> tuple[bool, str]:
        root = Path(root)
        good, notes = True, []
        for entry in cfg.targets.custom:
            if not entry.verify.strip():
                notes.append(f"{entry.name}: {NO_VERIFY}")
            elif self._check(entry, root, version):
                notes.append(f"{entry.name}: verified")
            else:
                good = False
                notes.append(f"{entry.name}: verify command failed")
        return good, "; ".join(notes)

    def setup_status(self, root: Path, cfg: ReleaseConfig, *, run: Run) -> list[str]:
        if not cfg.targets.custom:
            return ["No custom targets yet"]
        return [f"{e.name}: {e.run}" + (f" (verify: {e.verify})" if e.verify else "")
                for e in cfg.targets.custom]


targets.register(CustomTarget())
