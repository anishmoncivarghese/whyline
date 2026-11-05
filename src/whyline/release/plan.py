"""Assemble the whole release plan: ready, version, notes, commit, checks, GitHub, after."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from whyline.release import github, notes
from whyline.release import ready as release_ready
from whyline.release import version as release_version
from whyline.release.config import ReleaseConfig
from whyline.release.engine import Plan, Step
from whyline.release.github import StepError

Say = Callable[[str], None]
# () -> (bot token, chat id), or None when the assistant's Telegram is not set up
TelegramTarget = Callable[[], "tuple[str, int] | None"]


def assistant_telegram() -> tuple[str, int] | None:
    """The assistant's bot token and its first allowed chat, or None."""
    from whyline.agents import telegram
    from whyline.ideas import store, telegram_in

    try:
        token = telegram.token_get()
        if not token:
            return None
        conn = store.connect()
        try:
            chats = telegram_in.allowed_chats(conn)
        finally:
            conn.close()
    except Exception:  # not set up on this Mac: skip quietly
        return None
    return (token, chats[0]) if chats else None


def default_ask_agent(root: Path) -> Callable[[str], str]:
    """Ask the agent chat would use; any failure makes notes fall back to the commit list."""

    def ask(prompt: str) -> str:
        from whyline.relaychat import agent_choice
        from whyline_relay import chat
        from whyline_relay import config as relay_config

        agent = agent_choice.pick(root, None).agent
        if agent is None:
            raise RuntimeError("no agent is available")
        record = chat.run_turn(
            root, agent=agent, prompt=prompt, settings=relay_config.load(root),
            attachments=[], timeout_seconds=300,
        )
        return str(record["response"])

    return ask


def changed_files(root: Path, cfg: ReleaseConfig) -> list[Path]:
    """The files a version bump touches, including lock files that exist."""
    found = release_version.files_to_change(root, cfg)
    for name in ("uv.lock", "package-lock.json"):
        if (root / name).is_file():
            found.append(root / name)
    return found


def notes_file(root: Path, cfg: ReleaseConfig, version: str) -> Path | None:
    return notes._notes_path(root, cfg, version)


def build(
    root: Path,
    cfg: ReleaseConfig,
    version: str,
    *,
    run: Callable[..., object] = release_ready.default_run,
    run_shell: github.RunShell = github.shell_runner,
    ask_agent: Callable[[str], str] | None = None,
    confirm_notes: Callable[[Path], bool] = lambda path: True,
    ready_check: Callable[[], list[release_ready.ReadyItem]] | None = None,
    telegram_target: TelegramTarget = assistant_telegram,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    on_progress: Callable[[str], None] | None = None,
    say: Say = print,
) -> Plan:
    root = Path(root)
    path = notes_file(root, cfg, version)
    detail = on_progress or (lambda text: None)

    def check_ready(cancel: threading.Event) -> None:
        items = ready_check() if ready_check else release_ready.check(root, cfg, version)
        bad = [i for i in items if not i.ok]
        if bad:
            raise StepError("Not ready: " + "; ".join(
                f"{i.text}. {i.fix}".strip() if i.fix else i.text for i in bad))

    def version_done() -> bool:
        try:
            return release_version.current(root, cfg) == version
        except release_version.VersionError:
            return False

    def bump(cancel: threading.Event) -> None:
        release_version.write(root, cfg, version, run=run)

    def notes_done() -> bool:
        return path is not None and path.is_file()

    def write_notes(cancel: threading.Event) -> None:
        text = notes.draft(root, cfg, version,
                           ask_agent=ask_agent or default_ask_agent(root), run=run)
        written = notes.write(root, cfg, version, text)
        if written is not None and cfg.mode == "ask":
            say(f"Release notes written to {written}")
            if not confirm_notes(written):
                raise StepError("You stopped to edit the release notes; resume when ready")

    def after(cancel: threading.Event) -> None:
        for command in cfg.after:
            code, lines = run_shell(command, root, lambda line: None)
            if code != 0:
                say(f"Warning: after command failed ({code}): {command}")
        target = telegram_target()
        if target is None:
            return
        from whyline.agents import telegram

        token, chat_id = target
        try:
            telegram.send_message(token, chat_id, f"Released v{version} of {root.name}")
        except Exception as error:
            say(f"Warning: could not send the Telegram message: "
                f"{str(error).replace(token, '•••')}")

    steps = [
        # a bumped version means an earlier run passed Ready; the tree is dirty by design now
        Step("ready", "Check ready", False, version_done, check_ready),
        Step("version", f"Set version {version}", False, version_done, bump),
        Step("notes", "Write release notes", False, notes_done, write_notes),
        *github.build_steps(
            root, cfg, version,
            changed_files=lambda: changed_files(root, cfg),
            notes_path=path, run=run, run_shell=run_shell, sleep=sleep, now=now,
            on_progress=detail,
        ),
        Step("after", "Run after steps", False, lambda: False, after),
    ]
    return Plan(version, steps)
