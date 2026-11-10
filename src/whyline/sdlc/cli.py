"""`whyline docs`: write, review and approve a document set from the command line.

Exit codes: 0 on success, 1 when an action is refused or fails, 2 on bad usage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

_DOC_KINDS = ("brainstorm", "prd", "spec", "design", "plan", "build-record")
_START_KINDS = ("brainstorm", "prd", "spec")
_NAME_CHARS = 60


def add_parser(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser("docs", help="Document sets: brainstorm, PRD, spec, plan")
    sub = parser.add_subparsers(dest="docs_command", required=True)

    sub.add_parser("list", help="Every document set, newest first")

    show = sub.add_parser("show", help="A set's summary, or one of its documents")
    show.add_argument("slug")
    show.add_argument("doc", nargs="?", default=None, choices=_DOC_KINDS)

    start = sub.add_parser("start", help="Start a document set and run its first stages")
    source = start.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-description", metavar="TEXT", help="What to build")
    source.add_argument("--from-file", metavar="PATH", help="A .md, .txt, .pdf or .docx file")
    start.add_argument("--as", dest="as_kind", choices=_START_KINDS, default=None,
                       help="Import the file as this document instead of using it as the description")
    start.add_argument("--size", choices=("small", "feature", "large"), default="feature")
    start.add_argument("--prd", choices=("new", "update", "none"), default=None,
                       help="What the set does to the product PRD (default: from the repository)")
    start.add_argument("--major", action="store_true", help="Publish the PRD update as a major version")
    start.add_argument("--auto", action="store_true", help="Approve each document automatically")
    start.add_argument("--name", default=None, help="Name of the set (default: from the description)")

    prd = sub.add_parser("prd", help="The product PRD's version and approval")
    prd.add_argument("--history", action="store_true", help="Also print the changelog")

    resume = sub.add_parser("resume", help="Run the set's next stages")
    resume.add_argument("slug")

    for name, text in (("approve", "Approve a document"), ("redo", "Redo a document to match what comes before it")):
        item = sub.add_parser(name, help=text)
        item.add_argument("slug")
        item.add_argument("doc", choices=_DOC_KINDS)

    change = sub.add_parser("change", help="Ask for changes to a document")
    change.add_argument("slug")
    change.add_argument("doc", choices=_DOC_KINDS)
    change.add_argument("comments")
    change.add_argument("--section", default="", help="Change only this section")

    answer = sub.add_parser("answer", help="Answer the questions a stage asked")
    answer.add_argument("slug")
    answer.add_argument("doc", choices=_DOC_KINDS)
    answer.add_argument("answers")

    mode = sub.add_parser("mode", help="Human in the loop, or automatic")
    mode.add_argument("slug")
    mode.add_argument("mode", choices=("human", "auto"))

    for name, text in (
        ("review", "Run a fresh-eyes review of a document"),
        ("findings", "The latest fresh-eyes review of a document"),
    ):
        item = sub.add_parser(name, help=text)
        item.add_argument("slug")
        item.add_argument("doc", choices=_DOC_KINDS)

    names = sub.add_parser("names", help="Suggest names for the project")
    names.add_argument("slug")

    home = sub.add_parser("home", help="Choose where the project lives")
    place = home.add_mutually_exclusive_group(required=True)
    place.add_argument("--here", action="store_true", help="Use this repository")
    place.add_argument("--new", action="store_true", help="Create a new project folder")
    home.add_argument("slug")
    home.add_argument("--name", default=None, help="Project name (default: the first suggestion)")
    home.add_argument("--folder", default=None, help="Folder name (default: from the name)")
    home.add_argument("--parent", default=None, metavar="DIR", help="Where to create it (default: the last one used)")

    github = sub.add_parser("github", help="Create a GitHub repository for the project")
    github.add_argument("slug")
    github.add_argument("--public", action="store_true", help="Make it public (default: private)")
    github.add_argument("--owner", default=None, help="Account or organisation (default: your login)")
    github.add_argument("--name", default=None, help="Repository name (default: the folder name)")
    github.add_argument("--yes", action="store_true", help="Do not ask for confirmation")

    export = sub.add_parser("export", help="Write the set as a Word file and a PDF")
    export.add_argument("slug")
    export.add_argument("--out", default=None, metavar="DIR", help="Folder (default: ~/Downloads)")


def _root() -> Path | None:
    from whyline import paths

    return paths.find_repo_root()


def _fail(message: str) -> int:
    print(f"whyline docs: {message}", file=sys.stderr)
    return EXIT_ERROR


def _progress(line) -> None:
    text = str(line).strip()
    if text:
        print(text)


def _docs(root: Path) -> Path:
    from whyline.sdlc import workspace

    return workspace.docs_root(root)


def _list(root: Path, args) -> int:
    from whyline.sdlc import library

    found = library.sets(_docs(root))
    if not found:
        print("No document sets yet.")
    for item in found:
        print(f"{item.slug}: {item.summary}")
    return EXIT_OK


def _show(root: Path, args) -> int:
    from whyline.sdlc import docset

    docs = _docs(root)
    found = docset.load(docs, args.slug)
    if args.doc is None:
        print(f"{found.name} ({found.slug})")
        print(f"Size: {docset.Size(found.size).label}")
        print(f"Mode: {docset.Mode(found.mode).label}")
        for doc in found.documents:
            print(f"{doc['kind']}: {docset.Status(doc['status']).label}, v{doc['version']}")
        for kind, questions in found.pending_questions.items():
            for question in questions:
                print(f"Question ({kind}): {question}")
        return EXIT_OK
    doc = found.document(args.doc)
    if doc is None:
        return _fail(f"The document set {args.slug!r} has no {args.doc!r} document.")
    print(docset._current_text(docs, found, doc))
    return EXIT_OK


def _unique_name(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first.lstrip("#").strip()[:_NAME_CHARS] or "Untitled"


def _start(root: Path, args) -> int:
    from whyline.console import relay_ops
    from whyline.sdlc import docset, importer, runner

    docs = _docs(root)
    if args.as_kind and not args.from_file:
        return _fail("--as needs --from-file.")
    description = args.from_description or ""
    if args.from_file and not args.as_kind:
        description = importer.read_source(args.from_file)
    size = docset.Size(args.size)
    if args.as_kind and size is docset.Size.SMALL and args.as_kind != "spec":
        return _fail(f"A small set has no {args.as_kind}; use --as spec or a bigger --size.")
    created = docset.create(
        docs,
        args.name or _unique_name(description or Path(args.from_file).stem),
        size,
        docset.Mode.AUTO if args.auto else docset.Mode.HUMAN,
        brainstorm_first=args.as_kind == "brainstorm",
        prd_mode=args.prd,
        prd_major=args.major,
        roles=relay_ops.current_roles(docs),
    )
    created.description = description
    docset.save(docs, created)
    print(f"Started {created.slug}")
    if args.as_kind:
        if created.document(args.as_kind) is None:
            return _fail(f"This set has no {args.as_kind} document to import into.")
        number = importer.import_as(docs, created, args.as_kind, args.from_file, actor="user")
        print(f"Imported {args.as_kind} v{number}")
    return _print_outcome(runner.run(root, created.slug, progress=_progress))


def _resume(root: Path, args) -> int:
    from whyline.sdlc import docset, runner

    docset.load(_docs(root), args.slug)
    return _print_outcome(runner.run(root, args.slug, progress=_progress))


def _print_outcome(outcome) -> int:
    stage = f" at {outcome.stage}" if outcome.stage else ""
    if outcome.state == "error":
        return _fail(outcome.message or f"Stopped{stage}.")
    print(f"State: {outcome.state}{stage}")
    for question in outcome.questions:
        print(f"Question: {question}")
    if outcome.message:
        print(outcome.message)
    if outcome.state == "paused":
        return EXIT_ERROR
    return EXIT_OK


def _prd(root: Path, args) -> int:
    from whyline.sdlc import library

    found = library.product(_docs(root))
    if found is None:
        print("No product PRD yet.")
        return EXIT_OK
    print(f"Product PRD v{found.version}")
    print(f"Approved by {found.approval}" if found.approval else "Not approved yet")
    if args.history:
        for line in found.changelog:
            print(line)
    return EXIT_OK


def _approve(root: Path, args) -> int:
    from whyline.sdlc import record, review

    approver = record._git_user(root)
    following = review.approve(root, args.slug, args.doc, approver=approver)
    print(f"Approved {args.doc} for {args.slug}")
    print(f"Next: {following.label}" if following is not None else "Next: nothing")
    return EXIT_OK


def _print_changed(changed) -> None:
    if changed:
        print("Also changed: " + ", ".join(changed))


def _change(root: Path, args) -> int:
    from whyline.sdlc import review

    changed = review.ask_for_changes(
        root, args.slug, args.doc, args.comments, section=args.section, progress=_progress
    )
    print(f"Revised {args.doc} for {args.slug}")
    _print_changed(changed)
    return EXIT_OK


def _redo(root: Path, args) -> int:
    from whyline.sdlc import review

    _print_changed(review.redo(root, args.slug, args.doc, progress=_progress))
    print(f"Redid {args.doc} for {args.slug}")
    return EXIT_OK


def _answer(root: Path, args) -> int:
    from whyline.sdlc import review

    changed = review.answer_questions(
        root, args.slug, args.doc, args.answers, progress=_progress
    )
    print(f"Answered the questions on {args.doc} for {args.slug}")
    _print_changed(changed)
    return EXIT_OK


def _mode(root: Path, args) -> int:
    from whyline.sdlc import docset, review

    found = review.set_mode(root, args.slug, args.mode)
    print(f"{found.slug}: {docset.Mode(found.mode).label}")
    return EXIT_OK


def _review(root: Path, args) -> int:
    from whyline.sdlc import review

    result = review.review_again(root, args.slug, args.doc, progress=_progress)
    try:
        first = result.path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        first = ""
    print(first)
    print(result.path)
    return EXIT_OK


def _findings(root: Path, args) -> int:
    from whyline.sdlc import docset, goldfish

    found = docset.load(_docs(root), args.slug)
    if found.document(args.doc) is None:
        return _fail(f"The document set {args.slug!r} has no {args.doc!r} document.")
    latest = goldfish.latest_review(root, found, args.doc)
    if latest is None:
        print(f"No fresh-eyes review of the {args.doc} yet.")
        return EXIT_OK
    for item in latest.findings:
        print(f"{item.severity}: {item.section} — {item.problem} — {item.fix} (lenses: {item.lens})")
    if not latest.findings:
        print("No findings.")
    print("Not run: " + (", ".join(latest.not_run) if latest.not_run else "none"))
    return EXIT_OK


def _export(root: Path, args) -> int:
    from whyline.sdlc import export

    result = export.export_pack(_docs(root), args.slug, Path(args.out).expanduser() if args.out else None)
    for path in result.files:
        print(f"Wrote {path}")
    for note in result.notes:
        print(note)
    return EXIT_OK if result.files else EXIT_ERROR


def _agents(found) -> list[str]:
    return sorted({str(a) for a in found.roles.values() if a}) or ["claude"]


def _names(root: Path, args) -> int:
    from whyline.sdlc import docset, home

    found = docset.load(_docs(root), args.slug)
    agent = found.roles.get("writer") or "claude"
    for idea in home.suggest_names(root, found, agent=agent):
        print(f"{idea.name} ({idea.folder}) — {idea.reason}")
    return EXIT_OK


def _home(root: Path, args) -> int:
    from whyline.sdlc import docset, home, runner

    found = docset.load(_docs(root), args.slug)
    name = folder = parent = None
    if args.new:
        name = args.name or home.suggest_names(
            root, found, agent=found.roles.get("writer") or "claude")[0].name
        folder = args.folder or home.folder_name(name)
        parent = Path(args.parent).expanduser() if args.parent else home.last_parent()
    try:
        target = runner.choose_home(
            root, args.slug, choice="new" if args.new else "here", parent=parent,
            folder=folder, name=name, agents=_agents(found), progress=_progress)
    except home.HomeError as error:
        return _fail(str(error))
    print(f"Project home: {target}")
    if Path(target).resolve() != Path(root).resolve():
        print(f"Next: cd {target} && whyline docs resume {args.slug}")
    else:
        print(f"Next: whyline docs resume {args.slug}")
    return EXIT_OK


def _github(root: Path, args) -> int:
    from whyline.sdlc import docset, github_repo, home

    found = docset.load(_docs(root), args.slug)
    owner = args.owner or github_repo.default_owner(root)
    if not owner:
        return _fail("Could not find your GitHub login; pass --owner.")
    name = args.name or home.folder_name(found.name)
    private = not args.public
    print(github_repo.describe(owner, name, private))
    if not args.yes:
        try:
            answer = input("Continue? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing created.")
            return EXIT_ERROR
    try:
        url = github_repo.create_repo(root, owner=owner, name=name, private=private, slug=args.slug)
    except github_repo.GithubRepoError as error:
        return _fail(str(error))
    print(url)
    return EXIT_OK


_COMMANDS = {
    "names": _names, "home": _home, "github": _github,
    "list": _list, "show": _show, "start": _start, "prd": _prd, "resume": _resume,
    "approve": _approve, "change": _change, "redo": _redo, "answer": _answer,
    "mode": _mode, "review": _review, "findings": _findings, "export": _export,
}


def run(args: argparse.Namespace) -> int:
    from whyline.sdlc.docset import DocSetError

    handler = _COMMANDS.get(getattr(args, "docs_command", None) or "")
    if handler is None:
        print("usage: whyline docs " + "|".join(_COMMANDS), file=sys.stderr)
        return EXIT_USAGE
    root = _root()
    if root is None:
        return _fail("This is not a git repository.")
    try:
        return handler(root, args)
    except (DocSetError, ValueError, OSError) as error:
        return _fail(str(error))
