"""`whyline release check|run|status|resume|why|rerun`: a thin command line over the release engine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whyline.release import ci_failure
from whyline.release import config as release_config
from whyline.release import engine, github, plan as release_plan
from whyline.release import ready as release_ready
from whyline.release import setup_github
from whyline.release import state as release_state
from whyline.release import version as release_version

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

NOTES_PREVIEW_LINES = 40

VERBS = ("check", "run", "status", "resume", "why", "rerun", "ask", "setup")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whyline release", description="Release this project")
    sub = parser.add_subparsers(dest="release_command", required=True)
    check = sub.add_parser("check", help="Show what must be ready before a release")
    check.add_argument("--version", help="the version to check (default: next patch)")
    run = sub.add_parser("run", help="Run a release")
    group = run.add_mutually_exclusive_group()
    group.add_argument("--bump", choices=release_version.BUMPS, default=None,
                       help="patch, minor or major (default: the current version if it "
                            "is not released yet, else patch)")
    group.add_argument("--version", help="release exactly this version")
    run.add_argument("--mode", choices=release_config.MODES)
    run.add_argument("--yes", action="store_true", help="do not ask")
    run.add_argument("--no-bring-in", action="store_true",
                     help="do not merge main into this branch first")
    sub.add_parser("status", help="The release in progress, if any")
    setup = sub.add_parser("setup", help="Set up what releases need")
    setup_sub = setup.add_subparsers(dest="setup_target", required=True)
    github = setup_sub.add_parser("github", help="Sign in to GitHub and create the repository")
    github.add_argument("--create", metavar="NAME", help="create a repository with this name")
    github.add_argument("--public", action="store_true", help="make the new repository public")
    resume = sub.add_parser("resume", help="Continue a stopped release")
    resume.add_argument("--yes", action="store_true", help="do not ask")
    sub.add_parser("why", help="Why the stopped release failed")
    rerun = sub.add_parser("rerun", help="Rerun the failed CI jobs and continue the release")
    rerun.add_argument("--yes", action="store_true", help="do not ask")
    sub.add_parser("ask", help="Ask an agent why the stopped release failed")
    return parser


def _root() -> Path | None:
    from whyline import paths

    return paths.find_repo_root()


def _interactive() -> bool:
    return sys.stdin.isatty()


def _ask(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _edit(path: Path) -> None:
    """Open the file in the user's editor and wait for it to close."""
    import os
    import shlex
    import subprocess

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=False)
    except OSError as error:
        print(f"Could not open the editor: {error}", file=sys.stderr)


def _ask_current_instead(root: Path, cfg, current: str, args) -> bool:
    """A bump was chosen but the current version has notes and no tag: offer it instead."""
    if args.yes or not _interactive():
        return False
    path = release_plan.notes_file(root, cfg, current)
    if path is None or not path.is_file():
        return False
    if release_version.released(root, current, run=release_ready.default_run):
        return False
    answer = input(f"v{current} has notes and was never released. "
                   f"Release v{current} instead? [Y/n] ").strip().lower()
    return answer not in ("n", "no")


def _next_version(root: Path, cfg, args) -> str:
    if getattr(args, "version", None):
        return release_version.validate(args.version)
    current = release_version.current(root, cfg)
    kind = getattr(args, "bump", None)
    is_run = getattr(args, "release_command", "") == "run"
    if kind is None and is_run:
        if not release_version.released(root, current, run=release_ready.default_run):
            print(f"Using the current version {current}: it is not released yet.")
            return current
    elif kind is not None and is_run and _ask_current_instead(root, cfg, current, args):
        return current
    return release_version.bump(current, kind or "patch")


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


def _confirmers(args, bring_text: str = ""):
    def confirm(step) -> bool:
        if args.yes:
            return True
        if step.id == "bring-in-main" and bring_text:
            print(bring_text)
        return _ask(f"{step.title}?")

    def confirm_notes(path: Path) -> bool:
        if args.yes:
            return True
        while True:
            try:
                lines = Path(path).read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            print("\n".join(lines[:NOTES_PREVIEW_LINES]))
            if len(lines) > NOTES_PREVIEW_LINES:
                print(f"... {len(lines) - NOTES_PREVIEW_LINES} more lines in {path}")
            answer = input("Use these notes? [y/N/e] ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer not in ("e", "edit"):
                return False
            _edit(Path(path))

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
    if args.no_bring_in:
        cfg = release_config.ReleaseConfig(**{**cfg.__dict__, "bring_in_main": False})
    bring_text = ""
    if cfg.bring_in_main:
        try:
            bring_text = release_plan.bring_confirmation(root, cfg)
        except Exception:  # noqa: BLE001 - not a git checkout or no network: no line
            pass
        if bring_text:
            print(bring_text)
    plan = _plan(root, cfg, version, args)
    confirm, _ = _confirmers(args, bring_text)
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


def _why(args, root: Path, cfg) -> int:
    saved = release_state.load(root)
    failure = ci_failure.Failure.from_dict(saved.failure) if saved is not None else None
    if saved is None or saved.running or failure is None:
        print("The release isn't stopped")
        return EXIT_OK
    print(failure.text())
    return EXIT_OK


def _rerun(args, root: Path, cfg) -> int:
    saved = release_state.load(root)
    failure = ci_failure.Failure.from_dict(saved.failure) if saved is not None else None
    if saved is None or saved.running or failure is None or not failure.run_id:
        print("Nothing to rerun", file=sys.stderr)
        return EXIT_ERROR
    if failure.cause == ci_failure.TESTS and not args.yes:
        if not _interactive():
            print("No terminal to ask on. Run again with --yes.", file=sys.stderr)
            return EXIT_ERROR
        if not _ask("Tests failed. Rerunning won't fix a real failure. Rerun anyway?"):
            return EXIT_ERROR
    cfg = release_config.ReleaseConfig(**{**cfg.__dict__, "mode": saved.mode})
    plan = _plan(root, cfg, saved.version, args)
    confirm, _ = _confirmers(args)
    try:
        result = engine.rerun_and_resume(
            root, {s.id: s for s in plan.steps}, run=release_ready.default_run,
            confirm=confirm, on_progress=_progress_printer())
    except github.StepError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    if result.status == engine.NOTHING:
        print(result.message, file=sys.stderr)
        return EXIT_ERROR
    return _finish(result)


def _ask_agent(args, root: Path, cfg) -> int:
    saved = release_state.load(root)
    failure = ci_failure.Failure.from_dict(saved.failure) if saved is not None else None
    if saved is None or saved.running or failure is None:
        print("The release isn't stopped", file=sys.stderr)
        return EXIT_ERROR
    print("Asking the agent…", file=sys.stderr)
    try:
        answer = ci_failure.ask(root, failure, ask_agent=release_plan.default_ask_agent(root),
                                run=release_ready.default_run)
    except Exception as error:  # noqa: BLE001 - no agent or it failed: say so, don't crash
        print(f"The agent could not answer: {error}", file=sys.stderr)
        return EXIT_ERROR
    print(answer.text)
    if answer.needs_fix:
        print("The code needs a fix. Start a Fix session in the console: whyline console")
    return EXIT_OK


def _setup(args, root: Path, cfg) -> int:
    current = setup_github.status(root)
    print(f"GitHub CLI: {'installed' if current.gh_installed else 'not installed'}")
    if current.signed_in:
        print(f"Signed in as {current.user or 'unknown'}")
    else:
        print("Not signed in")
    if current.origin_url:
        kind = "GitHub" if current.origin_is_github else "not GitHub"
        print(f"Origin: {current.origin_url} ({kind})")
    else:
        print("Origin: none")
    if not current.gh_installed:
        print("Install the GitHub CLI from https://cli.github.com, then run this again.",
              file=sys.stderr)
        return EXIT_ERROR
    if not current.signed_in:
        if not _interactive():
            print("Sign in needs a terminal. Run: gh auth login", file=sys.stderr)
            return EXIT_ERROR
        print("Opening GitHub sign in. Enter the one-time code in your browser.")
        if setup_github.sign_in(on_line=print) != 0:
            print("Sign in did not finish.", file=sys.stderr)
            return EXIT_ERROR
    if args.create:
        try:
            url = setup_github.create_repo(root, args.create, private=not args.public)
        except setup_github.SetupError as error:
            print(str(error), file=sys.stderr)
            return EXIT_ERROR
        print(f"Created {url}")
    return EXIT_OK


_HANDLERS = {"check": _check, "run": _run, "status": _status, "resume": _resume,
             "why": _why, "rerun": _rerun, "ask": _ask_agent,
             "setup": _setup}


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
