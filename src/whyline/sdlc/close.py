"""Close a feature once its build record is approved, and open its pull request."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from whyline import worktrees
from whyline.console.relay_ops import PLANS_DIR
from whyline.sdlc import docset as docset_mod, guard, product, record, workspace
from whyline.sdlc.docset import DocSet, Status

DONE_DIR = f"{PLANS_DIR}/done"


class CloseError(Exception):
    """A plain refusal the user can read."""


@dataclass
class CloseResult:
    done: bool = False
    error: str = ""
    state: str = ""
    version: str = ""
    tag: str = ""


def _move(docs: Path, docset: DocSet) -> list[str]:
    """`git mv` the plan and test plan into plans/done/; return every path to commit."""
    rels: list[str] = []
    (docs / DONE_DIR).mkdir(parents=True, exist_ok=True)
    for suffix in ("plan", "tests"):
        old = f"{PLANS_DIR}/{docset.slug}.{suffix}.md"
        new = f"{DONE_DIR}/{docset.slug}.{suffix}.md"
        if (docs / old).is_file():
            if workspace._dirty(docs, [old, new]):
                raise CloseError(
                    f"{old} has uncommitted changes. Commit or discard them, then close again."
                )
            worktrees._git(docs, "mv", old, new)
            rels += [old, new]
        elif (docs / new).is_file():
            rels.append(new)
    plan = docset.document("plan")
    if plan is not None:
        plan["path"] = f"{DONE_DIR}/{docset.slug}.plan.md"
    return rels


def close(root: Path, slug: str) -> CloseResult:
    """The done stage: archive the plans, mark the set released or built, commit in the docs checkout."""
    root = Path(root)
    refusal = guard.check(root)
    if refusal:
        return CloseResult(error=refusal)
    docs = workspace.docs_root(root)
    found = docset_mod.load(docs, slug)
    built = found.document("build-record")
    if built is not None and built["status"] != Status.APPROVED.value:
        return CloseResult(error="Approve the build record before closing the feature.")
    tag = record._release_tag(root, found.build_base)
    found.state = "released" if tag else "built"
    found.tag = tag
    found.version = tag.removeprefix("v")
    try:
        rels = _move(docs, found)
    except (CloseError, worktrees.WorktreeError) as error:
        return CloseResult(error=str(error))
    docset_mod.save(docs, found)
    product.release_update(docs, slug)
    docset_mod.refresh(docs, found)
    folder = Path(docset_mod.SDLC_DIR) / slug
    rels += [
        str(p.relative_to(docs)) for p in sorted((docs / folder).rglob("*")) if p.is_file()
    ]
    rels = list(dict.fromkeys(rels))
    moved = {rel for rel in rels if rel.startswith(PLANS_DIR)}
    written = {rel: (docs / rel).read_text() for rel in rels if rel not in moved}
    foreign = [r for r in workspace._dirty(docs, list(written)) if r not in written]
    if foreign:
        return CloseResult(error="These files have changes whyline did not write: " + ", ".join(foreign))
    # the renames are staged by git mv; add only what still exists on disk
    worktrees._git(docs, "add", "--", *[r for r in rels if (docs / r).exists()])
    worktrees._git(docs, "commit", "-m", f"docs: close {found.name}", "--", *rels)
    return CloseResult(done=True, state=found.state, version=found.version, tag=tag)


def _link(docs: Path, rel: str) -> str:
    return f"- [{Path(rel).name}]({rel})"


def pr_body(root: Path, docs: Path, docset: DocSet) -> str:
    """What was built, the traceability table, Known gaps and links to the set's documents."""
    folder = docs / docset_mod.SDLC_DIR / docset.slug
    built = folder / "build-record.md"
    text = built.read_text(encoding="utf-8") if built.is_file() else ""
    parts = [
        "## What was built",
        "",
        record._section(text, "What was built") or "The build record has no summary.",
        "",
        "## Requirements traceability",
        "",
        record.trace_table(root, docs, docset),
        "",
        "## Known gaps",
        "",
        record._section(text, "Known gaps") or "None recorded.",
        "",
        "## Documents",
        "",
    ]
    for doc in docset.documents:
        if (docs / doc["path"]).is_file() or doc["kind"] == "plan":
            parts.append(_link(docs, doc["path"]))
    tests = f"{DONE_DIR}/{docset.slug}.tests.md"
    if not (docs / tests).is_file():
        tests = f"{PLANS_DIR}/{docset.slug}.tests.md"
    if (docs / tests).is_file():
        parts.append(_link(docs, tests))
    return "\n".join(parts).rstrip() + "\n"


def _run_gh(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["gh", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        raise CloseError(
            "The GitHub CLI (gh) is not installed. Install it, then open the pull request again."
        ) from None


def open_pr(root: Path, docs: Path, slug: str, *, gh_fn=None) -> str:
    """Push the relay branch and open its pull request; only ever called by a user action.

    Raises CloseError with a plain message when it cannot. Merging stays on GitHub.
    """
    root, docs = Path(root), Path(docs)
    gh = gh_fn or _run_gh
    found = docset_mod.load(docs, slug)
    branch = worktrees._git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    default = worktrees._default_branch(root).removeprefix("origin/")
    if branch == default or branch == "HEAD":
        raise CloseError(
            f"The project is on {branch}, not a relay branch. Only the relay branch is pushed."
        )
    try:
        worktrees._git(root, "remote", "get-url", "origin")
    except Exception:
        raise CloseError(
            f"The branch {branch} has no remote. Add a GitHub remote named origin first."
        ) from None
    if gh(["auth", "status"], root).returncode != 0:
        raise CloseError("The GitHub CLI (gh) is not signed in. Run `gh auth login`, then try again.")
    worktrees._git(root, "push", "-u", "origin", branch)
    made = gh(
        ["pr", "create", "--base", default, "--head", branch, "--title", found.name,
         "--body", pr_body(root, docs, found)],
        root,
    )
    if made.returncode != 0:
        raise CloseError(f"GitHub refused the pull request: {(made.stderr or made.stdout).strip()}")
    url = (made.stdout or "").strip().splitlines()[-1] if (made.stdout or "").strip() else ""
    found = docset_mod.load(docs, slug)
    found.pr_url = url
    docset_mod.save(docs, found)
    kind = "build-record" if found.document("build-record") else found.documents[-1]["kind"]
    docset_mod.log_review(docs, found, kind, actor="whyline", action="pull request opened", comment=url)
    docset_mod.commit(docs, found, f"docs: pull request opened for {found.name}")
    return url
