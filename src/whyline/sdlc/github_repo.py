"""Create a GitHub repository for a project. Only a user action calls this."""

from __future__ import annotations

import json
from pathlib import Path

from whyline.release import ready
from whyline.sdlc import docset as docset_mod
from whyline.sdlc import workspace
from whyline.worktrees import WorktreeError

CREATE_TIMEOUT = 120.0


class GithubRepoError(RuntimeError):
    pass


def gh_ready(root, *, run=None) -> str | None:
    """The fix text when gh is missing or signed out, else None."""
    run = run or ready.default_run
    for check in (ready._gh_installed, ready._gh_auth):
        item = check(Path(root), None, "", run)
        if not item.ok:
            return item.fix or item.text
    return None


def default_owner(root, *, run=None) -> str | None:
    run = run or ready.default_run
    try:
        res = run(["gh", "api", "user", "--jq", ".login"], cwd=Path(root),
                  env=ready._git_env())
    except OSError:
        return None
    login = (res.stdout or "").strip()
    return login if res.returncode == 0 and login else None


def describe(owner: str, name: str, private: bool) -> str:
    kind = "private" if private else "public"
    return f"Create github.com/{owner}/{name} ({kind}), add it as origin, and push main?"


def _origin(root: Path, run) -> str | None:
    res = run(["git", "remote", "get-url", "origin"], cwd=root, env=ready._git_env())
    url = (res.stdout or "").strip()
    return url if res.returncode == 0 and url else None


def _find_slug(docs: Path, slug: str | None) -> str | None:
    if slug:
        return slug
    found = docset_mod.all_sets(docs)
    return found[0].slug if len(found) == 1 else None


def _record(root: Path, slug: str | None, url: str, private: bool) -> None:
    docs = workspace.docs_root(root)
    slug = _find_slug(docs, slug)
    if not slug:
        return
    folder = docset_mod._folder(docs, slug)
    manifest = folder / docset_mod.MANIFEST
    log = folder / docset_mod.REVIEW_LOG
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["github"] = {"url": url, "private": private}
    manifest_text = json.dumps(data, indent=2) + "\n"
    manifest.write_text(manifest_text, encoding="utf-8")
    existing = log.read_text(encoding="utf-8") if log.is_file() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    log_text = existing + f"GitHub repository created: {url}\n"
    log.write_text(log_text, encoding="utf-8")
    rels = [manifest.relative_to(docs).as_posix(), log.relative_to(docs).as_posix()]
    try:
        workspace.docs_commit(docs, rels, f"docs: GitHub repository created for {slug}",
                              {rels[0]: manifest_text, rels[1]: log_text})
    except WorktreeError as error:
        raise GithubRepoError(str(error)) from None


def create_repo(root, *, owner: str, name: str, private: bool = True, run=None,
                slug: str | None = None) -> str:
    """Create the repository, add it as origin, push, and record it. Returns its URL."""
    root = Path(root)
    name = (name or "").strip()
    owner = (owner or "").strip()
    if not name or not owner:
        raise GithubRepoError("Give the repository a name.")
    fix = gh_ready(root, run=run)
    if fix:
        raise GithubRepoError(fix)
    check = run or ready.default_run
    remote = _origin(root, check)
    if remote:
        raise GithubRepoError(f"This project already has a remote: {remote}")
    if run is None:
        def run(args, **kwargs):
            return ready.default_run(args, timeout=CREATE_TIMEOUT, **kwargs)
    res = run(["gh", "repo", "create", f"{owner}/{name}",
               "--private" if private else "--public",
               "--source", str(root), "--remote", "origin", "--push"],
              cwd=root, env=ready._git_env())
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()
        raise GithubRepoError("GitHub could not create the repository"
                              + (f": {detail[0]}" if detail else "."))
    lines = (res.stdout or "").strip().splitlines()
    url = lines[-1].strip() if lines else ""
    if not url.startswith("http"):
        url = f"https://github.com/{owner}/{name}"
    _record(root, slug, url, private)
    return url
