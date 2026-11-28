"""`whyline release check|run|status|resume|why|rerun`: a thin command line over the release engine."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from whyline.release import ci_failure
from whyline.release import config as release_config
from whyline.release import conflicts as release_conflicts
from whyline.release import engine, github, plan as release_plan
from whyline.release import notes as release_notes
from whyline.release import ready as release_ready
from whyline.release import resolve as release_resolve
from whyline.release import setup_github
from whyline.release import state as release_state
from whyline.release import version as release_version

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

NOTES_PREVIEW_LINES = 40

VERBS = ("check", "run", "status", "resume", "why", "rerun", "ask", "setup", "settings",
         "notes", "resolve")


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
    settings = sub.add_parser("settings", help="Show or change Release settings")
    settings.add_argument("--on-no-runner", choices=release_config.NO_RUNNER_CHOICES,
                          help="what to do when GitHub had no runner for a job")
    settings.add_argument("setting", nargs="?", choices=("notes-review", "notes-reviewer"))
    settings.add_argument("value", nargs="?")
    notes = sub.add_parser("notes", help="Check release notes")
    notes.add_argument("--check", type=Path, required=True, metavar="FILE",
                       help="lint a release-notes file")
    sub.add_parser("ask", help="Ask an agent why the stopped release failed")
    resolve = sub.add_parser("resolve", help="Fix what a failed Ready check or a stop found")
    resolve.add_argument("key", nargs="?", help="the failed check or stop to work on")
    resolve.add_argument("--version", help="the version to check (default: next patch)")
    resolve.add_argument("--do", metavar="OPTION", help="run this option (its id or number)")
    resolve.add_argument("--message", help="the commit message, for options that need one")
    resolve.add_argument("--yes", action="store_true", help="do not ask")
    resolve.add_argument("--conflicts", action="store_true",
                         help="show each conflicting file and how it reads")
    resolve.add_argument("--keep", action="append", default=[], metavar="FILE=CHOICE",
                         help="with --do merge: ours, theirs or ticks for one file")
    resolve.add_argument("--say", metavar="TEXT",
                         help="say what you want; an agent proposes steps")
    resolve.add_argument("--undo", action="store_true", help="undo the last option that can be")
    resolve.add_argument("--history", action="store_true", help="show what was resolved here")
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
    current = release_version.starting(root, cfg, run=release_ready.default_run)
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


def _notes_version(path: Path) -> str:
    """Best-effort version for linting a notes file named vX.Y.Z.md."""
    name = Path(path).stem
    return name[1:] if name.startswith("v") else name


def _fallback_notes(path: Path) -> str:
    from whyline import paths

    root = paths.find_repo_root(Path(path).parent)
    commits = release_notes.commits_since_last_tag(root) if root is not None else []
    return release_notes.fallback(_notes_version(path), commits)


def _confirmers(args, bring_text: str = ""):
    def confirm(step) -> bool:
        if args.yes:
            return True
        if step.id == "bring-in-main" and bring_text:
            print(bring_text)
        return _ask(f"{step.title}?")

    def confirm_notes(path: Path, checked=None) -> bool:
        if args.yes:
            return True
        if checked is not None and getattr(checked, "summary", ""):
            print(checked.summary)
        while True:
            try:
                lines = Path(path).read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            print("\n".join(lines[:NOTES_PREVIEW_LINES]))
            if len(lines) > NOTES_PREVIEW_LINES:
                print(f"... {len(lines) - NOTES_PREVIEW_LINES} more lines in {path}")
            answer = input("[a]pprove, [e]dit, [c]ommit list, [s]top: ").strip().lower()
            if answer in ("a", "approve"):
                text = "\n".join(lines) + ("\n" if lines else "")
                problems = release_notes.lint(text, version=_notes_version(Path(path)))
                if not problems:
                    return True
                for problem in problems:
                    print(f"line {problem.line}: {problem.reason}")
                choice = input(
                    "[a]pprove anyway, [r]emove these lines, [e]dit, [s]top: "
                ).strip().lower()
                if choice in ("a", "approve", "approve anyway"):
                    return True
                if choice in ("r", "remove", "remove these lines"):
                    Path(path).write_text(release_notes.clean(text, problems), encoding="utf-8")
                    return True
                if choice in ("e", "edit"):
                    _edit(Path(path))
                    continue
                return False
            if answer in ("e", "edit"):
                _edit(Path(path))
            elif answer in ("c", "commit", "commit list"):
                Path(path).write_text(_fallback_notes(Path(path)), encoding="utf-8")
            else:
                return False

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
                        on_progress=_progress_printer(), say=print)
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
                           confirm=confirm, on_progress=_progress_printer(), say=print)
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


def _settings(args, root: Path, cfg) -> int:
    if args.setting == "notes-review":
        if args.value not in ("on", "off"):
            print("notes-review needs on or off", file=sys.stderr)
            return EXIT_USAGE
        cfg = replace(cfg, notes_review=args.value == "on")
    elif args.setting == "notes-reviewer":
        if not args.value:
            print("notes-reviewer needs an agent name or any", file=sys.stderr)
            return EXIT_USAGE
        cfg = replace(cfg, notes_reviewer="" if args.value == "any" else args.value)
    if args.on_no_runner is not None:
        cfg = replace(cfg, on_no_runner=args.on_no_runner)
    if args.setting is not None or args.on_no_runner is not None:
        release_config.save(root, cfg)
    print(f"release.on_no_runner = {cfg.on_no_runner}")
    print(f"release.notes_review = {'on' if cfg.notes_review else 'off'}")
    print(f"release.notes_reviewer = {cfg.notes_reviewer or 'any'}")
    return EXIT_OK


def _notes(args, root: Path, cfg) -> int:
    text = args.check.read_text(encoding="utf-8")
    problems = release_notes.lint(text, version=_notes_version(args.check))
    for problem in problems:
        print(f"line {problem.line}: {problem.reason}")
    return EXIT_ERROR if problems else EXIT_OK


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


# --- resolve ----------------------------------------------------------------

MERGE = "merge"
KEEP_CHOICES = ("ours", "theirs", "ticks")
PREVIEW_LINES = 20


def _err(text: str) -> None:
    print(text, file=sys.stderr)


def _unknown(what: str, got: str, choices: list[str]) -> int:
    _err(f"Unknown {what} {got!r}. Choose one of: {', '.join(choices) or 'none'}")
    return EXIT_USAGE


def _gather(args, root: Path, cfg):
    """(resolutions, version, stopped): the stopped release if there is one, else Ready."""
    run, fetch = release_ready.default_run, release_ready.default_fetch
    saved = release_state.load(root)
    if saved is not None and not saved.running and saved.kind:
        found = release_resolve.explain_stop(root, cfg, saved.version, saved.kind, saved.data,
                                             saved.reason, run=run, fetch=fetch)
        return [found], saved.version, True
    version = _next_version(root, cfg, args)
    items = release_ready.check(root, cfg, version)
    found = [release_resolve.explain(root, cfg, version, item, run=run, fetch=fetch)
             for item in items if not item.ok]
    return found, version, False


def _show(res) -> None:
    print(f"✗ {res.title}")
    for fact in res.facts:
        print(f"    {fact}")
    for number, option in enumerate(res.options, 1):
        mark = " (recommended)" if option.recommended else ""
        print(f"  {number}. {option.label} [{option.id}]{mark}")
    if not res.options:
        print("  No option here; say what you want with --say")


def _option_names(res) -> list[str]:
    names = [o.id for o in res.options]
    if any(o.kind == "conflicts" for o in res.options):
        names.append(MERGE)
    return names


def _find_option(res, wanted: str):
    if wanted.isdigit() and 1 <= int(wanted) <= len(res.options):
        return res.options[int(wanted) - 1]
    for option in res.options:
        if wanted == option.id or (wanted == MERGE and option.kind == "conflicts"):
            return option
    return None


def _go_ahead(args, question: str) -> int | None:
    """None to go ahead, else the exit code to stop with."""
    if args.yes:
        return None
    if not _interactive():
        _err("No terminal to ask on. Run again with --yes.")
        return EXIT_ERROR
    if not _ask(question):
        print("Nothing was done.")
        return EXIT_ERROR
    return None


def _recheck(root: Path, cfg, version: str, key: str, stopped: bool) -> None:
    if stopped:
        print("Continue the stopped release with: whyline release resume")
        return
    for item in release_ready.check(root, cfg, version):
        if item.key == key:
            print(f"{'✓' if item.ok else '✗'} {item.text}")
            return
    print(f"✓ {key} is no longer in the Ready check")


def _history_lines(root: Path) -> int:
    entries = release_resolve.history(root, run=release_ready.default_run)
    if not entries:
        print("Nothing has been resolved here yet.")
    for entry in entries:
        text = f": {entry.text}" if entry.text else ""
        print(f"{entry.time} {entry.key} {entry.option} {entry.result}{text}")
    return EXIT_OK


def _undo_last(root: Path) -> int:
    run = release_ready.default_run
    undone: set[str] = set()
    target = ""
    for entry in release_resolve.history(root, run=run):  # newest first
        if not entry.snapshot_id:
            continue
        if entry.result == "undone":
            undone.add(entry.snapshot_id)
        elif entry.ok and entry.snapshot_id not in undone:
            target = entry.snapshot_id
            break
    if not target:
        _err("There is nothing to undo")
        return EXIT_ERROR
    text = release_resolve.undo(root, target, run=run)
    print(text)
    return EXIT_OK if text.startswith("Undone") else EXIT_ERROR


def _show_conflicts(root: Path, cfg) -> int:
    try:
        release_ready.default_fetch(root, cfg.branch)
    except Exception:  # noqa: BLE001 - read what is already here
        pass
    found = release_conflicts.read(root, cfg.branch, run=release_ready.default_run)
    if not found:
        print(f"Nothing conflicts with origin/{cfg.branch}")
        return EXIT_OK
    for item in found:
        places = f"{item.places} place{'s' if item.places != 1 else ''}"
        print(f"{item.path}: {places} ({item.kind})")
        if item.reading:
            print(f"    {item.reading}")
        print(f"    choices: {', '.join(item.choices)}")
    return EXIT_OK


def _parse_keep(root: Path, cfg, keep: list[str]) -> dict[str, str] | int:
    found = release_conflicts.read(root, cfg.branch, run=release_ready.default_run)
    files = {c.path: c for c in found}
    choices = {c.path: c.default for c in found if c.default}
    for spec in keep:
        path, _, choice = spec.rpartition("=")
        if not path or choice not in KEEP_CHOICES:
            _err(f"--keep needs FILE=CHOICE with CHOICE one of: {', '.join(KEEP_CHOICES)}")
            return EXIT_USAGE
        if path not in files:
            return _unknown("file", path, sorted(files))
        if choice not in files[path].choices:
            return _unknown(f"choice for {path}", choice, list(files[path].choices))
        choices[path] = choice
    return choices


def _do_merge(args, root: Path, cfg, version: str, key: str, stopped: bool) -> int:
    run = release_ready.default_run
    choices = _parse_keep(root, cfg, args.keep)
    if isinstance(choices, int):
        return choices
    if not choices:
        _err("Nothing to settle: give --keep FILE=ours|theirs|ticks for each file")
        return EXIT_USAGE
    try:
        texts = release_conflicts.preview(root, cfg.branch, choices, run=run)
    except ValueError as error:
        _err(str(error))
        return EXIT_USAGE
    for path, text in texts.items():
        lines = text.splitlines()
        print(f"{path}: keep {choices[path]}, {len(lines)} lines")
        for line in lines[:PREVIEW_LINES]:
            print(f"    {line}")
        if len(lines) > PREVIEW_LINES:
            print(f"    ... {len(lines) - PREVIEW_LINES} more lines")
    stop = _go_ahead(args, f"Merge origin/{cfg.branch} with these choices?")
    if stop is not None:
        return stop
    out = release_conflicts.merge(root, cfg, version, choices, run=run)
    release_resolve._record(run, root, MERGE, key, "", out)  # noqa: SLF001
    print(out.text)
    _recheck(root, cfg, version, key, stopped)
    return EXIT_OK if out.ok else EXIT_ERROR


def _do_option(args, root: Path, cfg, version: str, res, option, stopped: bool) -> int:
    run = release_ready.default_run
    if option.kind == "conflicts":
        if args.keep or args.do == MERGE:
            return _do_merge(args, root, cfg, version, res.key, stopped)
        return _show_conflicts(root, cfg)
    if args.keep:
        _err("--keep goes with --do merge")
        return EXIT_USAGE
    if option.kind == "recheck":
        _recheck(root, cfg, version, res.key, stopped)
        return EXIT_OK
    if option.kind == "version":
        print("Release it with: whyline release run --version "
              + option.id.removeprefix("version-"))
        return EXIT_OK
    if option.kind == "copy":
        print("\n".join(res.facts[1:] or res.facts))
        return EXIT_OK
    if option.kind != "run":
        print(f"{option.label}: open `whyline console` and use Resolve on this item")
        return EXIT_OK
    if option.needs == "message" and not (args.message or "").strip():
        _err(f'{option.label} needs --message "<text>"')
        return EXIT_USAGE
    message = args.message or ""
    shown = release_resolve.preview(root, cfg, version, option, message=message, run=run)
    print("\n".join(shown.lines))
    for argv in shown.argv:
        print(f"    $ {' '.join(argv)}")
    stop = _go_ahead(args, f"{option.label}?")
    if stop is not None:
        return stop
    out = release_resolve.apply(root, cfg, version, option, message=message, run=run,
                                fetch=release_ready.default_fetch, key=res.key)
    print(out.text)
    _recheck(root, cfg, version, res.key, stopped)
    return EXIT_OK if out.ok else EXIT_ERROR


def _fix_chain(root: Path) -> list[str]:
    from whyline.relaychat import agent_choice

    picked = agent_choice.pick(root, None).agent
    return [picked] if picked else []


def _say(args, root: Path, cfg, version: str, res, stopped: bool) -> int:
    from whyline.console import fixmode

    run = release_ready.default_run
    _err("Asking the agent…")
    try:
        proposal = release_resolve.propose(
            root, res, args.say, ask_agent=release_plan.default_ask_agent(root), run=run)
    except Exception as error:  # noqa: BLE001 - no agent or it failed: say so, don't crash
        _err(f"The agent could not answer: {error}")
        return EXIT_ERROR
    print(f"Cause: {proposal.cause or '(not known)'}")
    for number, step in enumerate(proposal.steps, 1):
        print(f"  {number}. {step}")
    for step in proposal.refused:
        print(f"  ✗ {release_resolve.refusal(step)}")
    if not proposal.steps:
        print("There are no steps to take.")
        return EXIT_ERROR
    if fixmode.fix_level(root) == fixmode.LEVEL_SUGGEST:
        _err("Your Fix level is Suggest, so the agent won't edit. "
             "Choose Fix with approval in Settings to let it.")
        return EXIT_ERROR
    chain = _fix_chain(root)
    if not chain:
        _err("No installed agent can run a guarded Fix.")
        return EXIT_ERROR
    stop = _go_ahead(args, "Let the agent make these changes?")
    if stop is not None:
        return stop
    session = fixmode.open_session(
        root, fixmode.pause_id(f"release-resolve-{res.key}", args.say), chain[0])
    session.turns.append(fixmode.Turn("you", release_resolve.fix_request(res, proposal, args.say)))
    fixed = fixmode.run_fix(root, session, agent_chain=chain, on_progress=print)
    release_resolve.record_fix(root, res, args.say, fixed.status, run=run)
    if fixed.status == "violation":
        for violation in fixed.violations:
            print(f"✗ {violation.message}")
        print("The agent broke a rule, so its changes were undone.")
        return EXIT_ERROR
    if fixed.status != "proposal":
        print("No agent could make a guarded fix.")
        return EXIT_ERROR
    for change in fixed.changes:
        added, removed = fixed.counts.get(change.path, (0, 0))
        print(f"  {change.kind} {change.path} (+{added} -{removed})")
    if not fixed.changes:
        print("The agent changed no files.")
    if fixed.changes and not args.yes and _interactive():
        if input("Keep? [Y/n] ").strip().lower() in ("n", "no"):
            try:
                restored = fixmode.undo(root, fixed.snapshot)
            except fixmode.FixModeError as error:
                _err(f"Could not undo the fix: {error}")
                return EXIT_ERROR
            print(f"Undone: {len(restored)} path(s) put back as they were")
            return EXIT_OK
    _recheck(root, cfg, version, res.key, stopped)
    return EXIT_OK


def _resolve(args, root: Path, cfg) -> int:
    if args.history:
        return _history_lines(root)
    if args.undo:
        return _undo_last(root)
    if args.key is None and (args.do or args.say or args.conflicts or args.keep or args.message):
        _err("Name the item first: whyline release resolve <key> ...")
        return EXIT_USAGE
    found, version, stopped = _gather(args, root, cfg)
    if args.key is None:
        if not found:
            print("Nothing to resolve: every check passed.")
        for res in found:
            _show(res)
        return EXIT_OK
    res = next((r for r in found if r.key == args.key), None)
    if res is None:
        return _unknown("key", args.key, [r.key for r in found])
    if args.say:
        return _say(args, root, cfg, version, res, stopped)
    if args.conflicts:
        if not any(o.kind == "conflicts" for o in res.options):
            return _unknown("option", "conflicts", _option_names(res))
        return _show_conflicts(root, cfg)
    if args.do:
        option = _find_option(res, args.do)
        if option is None:
            return _unknown("option", args.do, _option_names(res))
        return _do_option(args, root, cfg, version, res, option, stopped)
    _show(res)
    return EXIT_OK


_HANDLERS = {"check": _check, "run": _run, "status": _status, "resume": _resume,
             "why": _why, "rerun": _rerun, "ask": _ask_agent,
             "setup": _setup, "settings": _settings, "notes": _notes, "resolve": _resolve}


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
