"""`whyline release check|run|status|resume`: a thin command line over the release engine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whyline.release import config as release_config
from whyline.release import engine, plan as release_plan
from whyline.release import ready as release_ready
from whyline.release import state as release_state
from whyline.release import version as release_version

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

VERBS = ("check", "run", "status", "resume")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whyline release", description="Release this project")
    sub = parser.add_subparsers(dest="release_command", required=True)
    check = sub.add_parser("check", help="Show what must be ready before a release")
    check.add_argument("--version", help="the version to check (default: next patch)")
    run = sub.add_parser("run", help="Run a release")
    group = run.add_mutually_exclusive_group()
    group.add_argument("--bump", choices=release_version.BUMPS, default="patch")
    group.add_argument("--version", help="release exactly this version")
    run.add_argument("--mode", choices=release_config.MODES)
    run.add_argument("--yes", action="store_true", help="do not ask")
    sub.add_parser("status", help="The release in progress, if any")
    resume = sub.add_parser("resume", help="Continue a stopped release")
    resume.add_argument("--yes", action="store_true", help="do not ask")
    return parser


def _root() -> Path | None:
    from whyline import paths

    return paths.find_repo_root()


def _interactive() -> bool:
    return sys.stdin.isatty()


def _ask(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _next_version(root: Path, cfg, args) -> str:
    if getattr(args, "version", None):
        return release_version.validate(args.version)
    return release_version.bump(release_version.current(root, cfg),
                                getattr(args, "bump", None) or "patch")


def _check(args, root: Path, cfg) -> int:
    items = release_ready.check(root, cfg, _next_version(root, cfg, args))
    for item in items:
        print(f"{'✓' if item.ok else '✗'} {item.text}")
        if not item.ok and item.fix:
            print(f"    {item.fix}")
    return EXIT_OK if release_ready.ok(items) else EXIT_ERROR


def _may_ask(args, mode: str) -> bool:
    """Whether the run may go ahead: asking needs a terminal unless --yes or auto."""
    return args.yes or mode == "auto" or _interactive()


def _confirmers(args):
    def confirm(step) -> bool:
        return True if args.yes else _ask(f"{step.title}?")

    def confirm_notes(path: Path) -> bool:
        return True if args.yes else _ask("Notes written. Continue?")

    return confirm, confirm_notes


def _progress_printer():
    last: list[tuple] = []

    def show(progress: engine.Progress) -> None:
        key = (progress.title, progress.detail)
        if last and last[-1] == key:
            return
        last[:] = [key]
        print(f"[{progress.step_index + 1}/{progress.total}] {progress.title}: {progress.detail}")

    return show


def _finish(result: engine.Result) -> int:
    if result.status == engine.DONE:
        print(result.message)
        return EXIT_OK
    stream = sys.stdout if result.status == engine.PAUSED else sys.stderr
    print(result.message, file=stream)
    print("Continue with: whyline release resume", file=stream)
    return EXIT_ERROR


def _plan(root: Path, cfg, version: str, args):
    _, confirm_notes = _confirmers(args)
    return release_plan.build(root, cfg, version, confirm_notes=confirm_notes,
                              on_progress=lambda text: print(f"  {text}"))


def _run(args, root: Path, cfg) -> int:
    mode = args.mode or cfg.mode
    if not _may_ask(args, mode):
        print("No terminal to ask on. Run again with --yes or --mode auto.", file=sys.stderr)
        return EXIT_ERROR
    version = _next_version(root, cfg, args)
    cfg = release_config.ReleaseConfig(**{**cfg.__dict__, "mode": mode})
    plan = _plan(root, cfg, version, args)
    confirm, _ = _confirmers(args)
    result = engine.run(root, plan, mode=mode, confirm=confirm,
                        on_progress=_progress_printer())
    return _finish(result)


def _status(args, root: Path, cfg) -> int:
    saved = release_state.load(root)
    if saved is None:
        print("No release in progress.")
        return EXIT_OK
    if saved.running:
        word = "running"
    elif saved.failed_id:
        word = f"failed at {saved.failed_id}"
    else:
        word = "stopped"
    print(f"Release v{saved.version}: {word} ({len(saved.done)} of {len(saved.step_ids)} steps done)")
    if saved.reason:
        print(saved.reason)
    return EXIT_OK


def _resume(args, root: Path, cfg) -> int:
    saved = release_state.load(root)
    if saved is None:
        print("There is no stopped release to resume.", file=sys.stderr)
        return EXIT_ERROR
    if not _may_ask(args, saved.mode):
        print("No terminal to ask on. Run again with --yes.", file=sys.stderr)
        return EXIT_ERROR
    cfg = release_config.ReleaseConfig(**{**cfg.__dict__, "mode": saved.mode})
    plan = _plan(root, cfg, saved.version, args)
    confirm, _ = _confirmers(args)
    result = engine.resume(root, {s.id: s for s in plan.steps}, version=saved.version,
                           confirm=confirm, on_progress=_progress_printer())
    return _finish(result)


_HANDLERS = {"check": _check, "run": _run, "status": _status, "resume": _resume}


def run(args: argparse.Namespace) -> int:
    root = _root()
    if root is None:
        print("Not inside a git repository.", file=sys.stderr)
        return EXIT_ERROR
    try:
        cfg = release_config.load(root)
        return _HANDLERS[args.release_command](args, root, cfg)
    except (release_config.ConfigError, release_version.VersionError, engine.AlreadyReleasing,
            engine.VersionMismatch, FileNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR


def main(argv: list[str]) -> int:
    return run(build_parser().parse_args(argv))
