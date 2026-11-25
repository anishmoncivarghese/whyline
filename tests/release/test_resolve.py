from __future__ import annotations

from types import SimpleNamespace

from whyline.release import resolve
from whyline.release.config import ReleaseConfig, Targets
from whyline.release.ready import ReadyItem


def _res(code=0, out=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr="")


def _run(table):
    """Fake run: the first key that is a prefix of the git args joined by spaces wins."""
    def run(args, **_kw):
        line = " ".join(args[1:])
        for prefix, result in table.items():
            if line.startswith(prefix):
                if isinstance(result, Exception):
                    raise result
                return result
        return _res(1)
    return run


def _fetch(root, branch):
    return None


def _explain(tmp_path, item, table=None, version="1.0.0", cfg=None, **kw):
    return resolve.explain(tmp_path, cfg or ReleaseConfig(), version, item,
                           run=_run(table or {}), fetch=kw.pop("fetch", _fetch), **kw)


def _ids(res):
    return [o.id for o in res.options]


def test_clean_lists_files_with_state(tmp_path):
    out = " M a.py\n?? b.py\n D c.py\n"
    res = _explain(tmp_path, ReadyItem("clean", False, "Uncommitted changes: a.py"),
                   {"status": _res(0, out)})
    assert res.facts == ("a.py (changed)", "b.py (new)", "c.py (deleted)")
    assert _ids(res) == ["commit", "stash", "open-files"]
    assert res.options[0].needs == "message"


def test_clean_caps_at_twenty(tmp_path):
    out = "".join(f"?? f{i}.py\n" for i in range(25))
    res = _explain(tmp_path, ReadyItem("clean", False, "x"), {"status": _res(0, out)})
    assert len(res.facts) == 21
    assert res.facts[-1] == "and 5 more"


def test_failing_git_says_couldnt_read_and_does_not_raise(tmp_path):
    res = _explain(tmp_path, ReadyItem("clean", False, "x"), {"status": _res(128)})
    assert res.facts == ("couldn't read the changed files",)
    assert res.options == ()
    boom = _explain(tmp_path, ReadyItem("clean", False, "x"), {"status": OSError("no git")})
    assert boom.facts == ("couldn't read the changed files",)
    assert boom.options == ()


def test_clean_staged_additions_are_new(tmp_path):
    out = "A  a.py\nAM b.py\nM  c.py\n"
    res = _explain(tmp_path, ReadyItem("clean", False, "x"), {"status": _res(0, out)})
    assert res.facts == ("a.py (new)", "b.py (new)", "c.py (changed)")


def test_next_version_checks_registries_without_target_flags(tmp_path):
    _pypi_project(tmp_path)
    (tmp_path / "package.json").write_text('{"name": "demo", "version": "1.0.0"}')
    table = {"ls-remote": _res(0, "")}

    def get(url):
        return 200 if ("1.0.1" in url and "pypi" in url) or ("1.0.2" in url and "npm" in url) \
            else 404

    res = _explain(tmp_path, ReadyItem("tag", False, "Tag v1.0.0 exists locally"),
                   {"rev-parse -q --verify refs/tags/v1.0.0": _res(0, "abc\n"), **table},
                   cfg=ReleaseConfig(), get=get)
    assert _ids(res) == ["version-1.0.3"]


def test_explain_survives_a_raising_fetch(tmp_path):
    def bad(root, branch):
        raise RuntimeError("offline")

    res = _explain(tmp_path, ReadyItem("synced", False, "x"), fetch=bad)
    assert res.facts == ("couldn't read origin/main",)
    assert res.options == ()


def test_synced_behind_on_release_branch(tmp_path):
    table = {"rev-parse --abbrev-ref": _res(0, "main\n"),
             "rev-list --count HEAD..": _res(0, "3\n"),
             "rev-list --count origin": _res(0, "0\n")}
    res = _explain(tmp_path, ReadyItem("synced", False, "behind"), table)
    assert res.facts == ("3 commits behind origin/main",)
    assert _ids(res) == ["pull"]


def test_synced_diverged_has_no_option(tmp_path):
    table = {"rev-parse --abbrev-ref": _res(0, "main\n"),
             "rev-list --count HEAD..": _res(0, "2\n"),
             "rev-list --count origin": _res(0, "1\n")}
    res = _explain(tmp_path, ReadyItem("synced", False, "behind"), table)
    assert res.facts == ("this branch and origin/main have both moved",)
    assert res.options == ()


def test_synced_other_branch_no_conflicts_offers_bring(tmp_path):
    table = {"rev-parse --abbrev-ref": _res(0, "feature\n"),
             "rev-list --count HEAD..": _res(0, "4\n"),
             "merge-tree": _res(0, "tree\n")}
    res = _explain(tmp_path, ReadyItem("synced", False, "behind"), table)
    assert res.facts[0] == "4 commits behind origin/main"
    assert _ids(res) == ["bring"]


def test_synced_other_branch_conflicts(tmp_path):
    table = {"rev-parse --abbrev-ref": _res(0, "feature\n"),
             "rev-list --count HEAD..": _res(0, "1\n"),
             "merge-tree": _res(1, "tree\na.py\nb.py\n")}
    res = _explain(tmp_path, ReadyItem("synced", False, "behind"), table)
    assert "a.py" in res.facts and "b.py" in res.facts
    assert _ids(res) == ["conflicts"]
    assert res.options[0].kind == "conflicts"


def test_synced_other_branch_unreadable_trial_merge(tmp_path):
    table = {"rev-parse --abbrev-ref": _res(0, "feature\n"),
             "rev-list --count HEAD..": _res(0, "1\n"),
             "merge-tree": _res(2)}
    res = _explain(tmp_path, ReadyItem("synced", False, "behind"), table)
    assert any(f.startswith("couldn't read") for f in res.facts)
    assert res.options == ()


def _pypi_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.0.0"\n')


def test_tag_taken_offers_next_free_version(tmp_path):
    table = {"rev-parse -q --verify refs/tags/v1.0.0": _res(0, "abc\n"),
             "ls-remote": _res(0, "")}
    res = _explain(tmp_path, ReadyItem("tag", False, "Tag v1.0.0 exists locally"), table)
    assert res.facts == ("Tag v1.0.0 exists locally",)
    assert _ids(res) == ["version-1.0.1"]
    assert res.options[0].kind == "version"


def test_next_version_skips_one_taken_on_pypi(tmp_path):
    _pypi_project(tmp_path)
    cfg = ReleaseConfig(targets=Targets(pypi=True))
    seen = []

    def get(url):
        seen.append(url)
        return 200 if url.endswith("/1.0.1/json") else 404

    table = {"rev-parse -q --verify refs/tags/v1.0.0": _res(0, "abc\n"),
             "ls-remote": _res(0, "")}
    res = _explain(tmp_path, ReadyItem("pypi-version", False, "demo 1.0.0 is already on PyPI"),
                   table, cfg=cfg, get=get)
    assert _ids(res) == ["version-1.0.2"]
    assert any("/1.0.1/" in u for u in seen)


def test_next_version_checks_npm_too(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "demo", "version": "1.0.0"}')
    cfg = ReleaseConfig(targets=Targets(npm=True))
    table = {"ls-remote": _res(0, "")}
    res = _explain(tmp_path, ReadyItem("npm-version", False, "demo 1.0.0 is already on npm"),
                   table, cfg=cfg, get=lambda url: 200 if "1.0.1" in url else 404)
    assert _ids(res) == ["version-1.0.2"]


def test_registry_unreachable_leaves_version_out(tmp_path):
    _pypi_project(tmp_path)
    cfg = ReleaseConfig(targets=Targets(pypi=True))

    def get(url):
        raise OSError("down")

    table = {"ls-remote": _res(0, "")}
    res = _explain(tmp_path, ReadyItem("pypi-version", False, "demo 1.0.0 is already on PyPI"),
                   table, cfg=cfg, get=get)
    assert "couldn't read PyPI" in res.facts
    assert res.options == ()


def test_relay_running_and_paused(tmp_path, monkeypatch):
    from whyline_relay import state as relay_state

    saved = SimpleNamespace(plan="plans/x.plan.md", task_id="T-1", paused_reason="needs you")
    monkeypatch.setattr(relay_state, "load", lambda root: saved)
    running = _explain(tmp_path, ReadyItem("relay", False, "A relay is running"))
    assert running.facts == ("plan plans/x.plan.md", "task T-1")
    assert _ids(running) == ["open-relay"]
    paused = _explain(tmp_path, ReadyItem("relay", False, "A relay is paused on another task"))
    assert "paused: needs you" in paused.facts
    assert _ids(paused) == ["open-relay-resolve"]


def test_relay_state_unreadable(tmp_path, monkeypatch):
    from whyline_relay import state as relay_state

    monkeypatch.setattr(relay_state, "load", lambda root: None)
    res = _explain(tmp_path, ReadyItem("relay", False, "A relay is running"))
    assert res.facts == ("couldn't read the relay's state",)


def test_setup_keys_open_their_section(tmp_path):
    for key, section in [("gh-auth", "github"), ("origin", "github"),
                         ("pypi-workflow", "pypi"), ("npm-name", "npm"),
                         ("homebrew-tap", "homebrew"), ("docker-secrets", "docker")]:
        res = _explain(tmp_path, ReadyItem(key, False, "bad", "fix it"))
        assert _ids(res) == [f"open-setup-{section}"], key
        assert res.options[0].kind == "open"


def test_git_and_gh_copy_the_install_command(tmp_path):
    res = _explain(tmp_path, ReadyItem("gh", False, "gh is not installed",
                                       "Install the GitHub CLI: https://cli.github.com"))
    assert res.facts[-1] == "Install the GitHub CLI: https://cli.github.com"
    assert [o.kind for o in res.options] == ["copy"]
    assert _explain(tmp_path, ReadyItem("git", False, "git is not installed")).options == ()


def test_security_opens_the_security_screen(tmp_path):
    for key in ("security", "security-history"):
        res = _explain(tmp_path, ReadyItem(key, False, "found 2 secrets", "Open Security to review"))
        assert _ids(res) == ["open-security"]


def test_could_not_check_offers_recheck(tmp_path):
    for text in ("could not reach PyPI", "could not check: boom"):
        res = _explain(tmp_path, ReadyItem("pypi-version", False, text))
        assert _ids(res) == ["recheck"]
        assert res.options[0].kind == "recheck"


def test_unknown_key_shows_text_and_fix_only(tmp_path):
    res = _explain(tmp_path, ReadyItem("mystery", False, "Something odd", "Try X"))
    assert res.facts == ("Something odd", "Try X")
    assert res.options == ()


# --- running an option (RSO-2) -----------------------------------------------

import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

from whyline.release.ready import default_fetch  # noqa: E402

COMMIT = resolve.Option("commit", "Commit them", "run", needs="message")
STASH = resolve.Option("stash", "Stash them", "run")
PULL = resolve.Option("pull", "Pull origin/main", "run")
BRING = resolve.Option("bring", "Bring in main", "run")
CFG = ReleaseConfig()
FORBIDDEN = ("--force", "-f", "clean")
FORBIDDEN_PAIRS = (("tag", "-d"), ("branch", "-D"), ("reset", "--hard"), ("checkout", "--"))


class Real:
    """A real `run`: git for real, and `whyline note` calls remembered, not run."""

    def __init__(self):
        self.notes: list[list[str]] = []

    def __call__(self, args, **kw):
        if args[0] == "whyline":
            self.notes.append(list(args))
            return _res(0)
        kw.pop("timeout", None)
        kw.setdefault("capture_output", True)
        kw.setdefault("text", True)
        return subprocess.run(args, check=False, **kw)


def _g(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _out(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return res.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _g(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _g(tmp_path, "clone", "-q", str(origin), str(work))
    _g(work, "config", "user.email", "t@example.com")
    _g(work, "config", "user.name", "T")
    _g(work, "checkout", "-q", "-b", "main")
    (work / "a.txt").write_text("one\n")
    _g(work, "add", "a.txt")
    _g(work, "commit", "-q", "-m", "first")
    _g(work, "push", "-q", "origin", "main")
    return work


def _advance_origin(repo, name="up.txt"):
    other = repo.parent / "other"
    if not other.exists():
        _g(repo.parent, "clone", "-q", str(repo.parent / "origin.git"), str(other))
        _g(other, "config", "user.email", "t@example.com")
        _g(other, "config", "user.name", "T")
    (other / name).write_text("from origin\n")
    _g(other, "add", name)
    _g(other, "commit", "-q", "-m", f"add {name}")
    _g(other, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin", "main")


def _dirty(repo, tag=""):
    (repo / "a.txt").write_text(f"one changed{tag}\n")
    (repo / "new.txt").write_text(f"brand new{tag}\n")


def _apply(repo, option, run, message="", **kw):
    return resolve.apply(repo, CFG, "1.0.0", option, message=message, run=run,
                         fetch=default_fetch, relay_running=lambda _r: False, **kw)


def _has_forbidden(argv):
    for cmd in argv:
        args = list(cmd[1:])
        if args[:1] == ["push"] or any(a in FORBIDDEN for a in args):  # `stash push` is fine
            return True
        for first, second in FORBIDDEN_PAIRS:
            if first in args and second in args[args.index(first) + 1:]:
                return True
    return False


def test_commit_commits_the_listed_files_and_notes_it(repo):
    run = Real()
    _dirty(repo)
    out = _apply(repo, COMMIT, run, "tidy up")
    assert out.ok and out.commits == 1 and out.snapshot_id
    assert _out(repo, "status", "--porcelain") == ""
    assert _out(repo, "log", "-1", "--format=%s") == "tidy up"
    assert ("git", "commit", "-m", "tidy up") in out.argv
    assert len(run.notes) == 1 and run.notes[0][run.notes[0].index("--role") + 1] == "release"


def test_empty_message_is_refused_and_nothing_changes(repo):
    _dirty(repo)
    before = _out(repo, "rev-parse", "HEAD")
    for message in ("", "   "):
        out = _apply(repo, COMMIT, Real(), message)
        assert not out.ok and "message" in out.text
        assert out.argv == ()
    assert _out(repo, "rev-parse", "HEAD") == before
    assert (repo / "a.txt").read_text() == "one changed\n"


def test_secret_stops_the_commit_without_showing_the_value(repo):
    token = "ghp_" + "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7cF0hJ3kL6"
    (repo / "creds.txt").write_text(f'token = "{token}"\n')
    before = _out(repo, "rev-parse", "HEAD")
    out = _apply(repo, COMMIT, Real(), "add creds")
    assert not out.ok
    assert "creds.txt" in out.text and token not in out.text
    assert _out(repo, "rev-parse", "HEAD") == before
    assert _out(repo, "diff", "--cached", "--name-only") == ""


def test_stash_names_the_stash_and_pop_brings_files_back(repo):
    _dirty(repo)
    out = _apply(repo, STASH, Real())
    assert out.ok and "Get them back with: git stash pop" in out.text
    assert out.snapshot_id == ""
    assert _out(repo, "status", "--porcelain") == ""
    name = out.text.split(" as ")[1].split(".")[0]
    assert name in _out(repo, "stash", "list")
    _g(repo, "stash", "pop", "-q")
    assert (repo / "a.txt").read_text() == "one changed\n"
    assert (repo / "new.txt").read_text() == "brand new\n"


def test_pull_moves_forward_and_keeps_unrelated_dirty_files(repo):
    _advance_origin(repo)
    (repo / "a.txt").write_text("mine\n")
    out = _apply(repo, PULL, Real())
    assert out.ok and out.commits == 1 and out.snapshot_id
    assert (repo / "up.txt").read_text() == "from origin\n"
    assert (repo / "a.txt").read_text() == "mine\n"


def test_pull_refuses_when_both_moved(repo):
    _advance_origin(repo)
    (repo / "mine.txt").write_text("x\n")
    _g(repo, "add", "mine.txt")
    _g(repo, "commit", "-q", "-m", "mine")
    out = _apply(repo, PULL, Real())
    assert not out.ok and not (repo / "up.txt").exists()


def test_bring_merges_main_into_the_release_branch(repo):
    _g(repo, "checkout", "-q", "-b", "release/x")
    _advance_origin(repo)
    out = _apply(repo, BRING, Real())
    assert out.ok and out.snapshot_id and out.commits >= 1
    assert (repo / "up.txt").exists()
    assert _out(repo, "log", "-1", "--format=%s").startswith("merge: bring main into release/x")


def test_bring_refuses_over_dirty_files_and_leaves_them(repo):
    _g(repo, "checkout", "-q", "-b", "release/x")
    _advance_origin(repo)
    _dirty(repo)
    out = _apply(repo, BRING, Real())
    assert not out.ok and "Commit or stash" in out.text
    assert (repo / "a.txt").read_text() == "one changed\n"


def test_preview_argv_is_what_apply_ran(repo):
    run = Real()
    for n, (option, message) in enumerate(((COMMIT, "msg"), (STASH, ""))):
        _dirty(repo, n)
        pre = resolve.preview(repo, CFG, "1.0.0", option, message=message, run=run)
        out = _apply(repo, option, run, message)
        assert out.ok and pre.argv, option.id
        assert out.argv[-len(pre.argv):] == pre.argv, option.id
        if option is STASH:
            _g(repo, "stash", "pop", "-q")
            _g(repo, "add", "-A")
            _g(repo, "commit", "-q", "-m", "keep")
    _advance_origin(repo)
    pre = resolve.preview(repo, CFG, "1.0.0", PULL, run=run)
    assert _apply(repo, PULL, run).argv[-1:] == pre.argv
    _g(repo, "checkout", "-q", "-b", "release/x")
    _advance_origin(repo, "more.txt")
    pre = resolve.preview(repo, CFG, "1.0.0", BRING, run=run)
    assert pre.argv[0] in _apply(repo, BRING, run).argv


def test_options_without_argv_have_none_and_are_not_run_here(repo):
    for kind in ("open", "copy", "version", "recheck", "conflicts"):
        opt = resolve.Option(f"x-{kind}", "Do x", kind)
        pre = resolve.preview(repo, CFG, "1.0.0", opt, run=Real())
        assert pre.argv == () and pre.lines
        assert not _apply(repo, opt, Real()).ok


def test_no_destructive_argv(repo):
    run = Real()
    seen: list[tuple[str, ...]] = []
    _dirty(repo)
    for option in (COMMIT, STASH, PULL, BRING):
        seen.extend(resolve.preview(repo, CFG, "1.0.0", option, message="m", run=run).argv)
    seen.extend(_apply(repo, COMMIT, run, "m").argv)
    _g(repo, "push", "-q", "origin", "main")
    _dirty(repo, 2)
    seen.extend(_apply(repo, STASH, run).argv)
    _advance_origin(repo)
    seen.extend(_apply(repo, PULL, run).argv)
    _g(repo, "checkout", "-q", "-b", "release/x")
    _advance_origin(repo, "more.txt")
    seen.extend(_apply(repo, BRING, run).argv)
    assert len(seen) > 6
    assert not _has_forbidden(seen), seen
    assert _has_forbidden([("git", "push")]) and _has_forbidden([("git", "reset", "--hard")])


def test_dirty_files_survive_every_option(repo):
    run = Real()
    _dirty(repo)  # commit: the content is in HEAD
    assert _apply(repo, COMMIT, run, "m").ok
    assert _out(repo, "show", "HEAD:a.txt") == "one changed"
    assert _out(repo, "show", "HEAD:new.txt") == "brand new"
    _g(repo, "push", "-q", "origin", "main")
    (repo / "a.txt").write_text("stashed\n")  # stash: in the named stash, and comes back
    assert _apply(repo, STASH, run).ok
    assert _out(repo, "show", "stash@{0}:a.txt") == "stashed"
    _g(repo, "stash", "pop", "-q")
    assert (repo / "a.txt").read_text() == "stashed\n"
    _advance_origin(repo)  # pull leaves it alone; bring refuses before touching it
    assert _apply(repo, PULL, run).ok
    assert (repo / "a.txt").read_text() == "stashed\n"
    _g(repo, "checkout", "-q", "-b", "release/x")
    _advance_origin(repo, "more.txt")
    assert not _apply(repo, BRING, run).ok
    assert (repo / "a.txt").read_text() == "stashed\n"


def test_undo_a_commit_puts_the_files_back_dirty(repo):
    run = Real()
    _dirty(repo)
    start = _out(repo, "rev-parse", "HEAD")
    out = _apply(repo, COMMIT, run, "m")
    assert resolve.undo(repo, out.snapshot_id, run=run).startswith("Undone")
    assert _out(repo, "rev-parse", "HEAD") == start
    assert (repo / "a.txt").read_text() == "one changed\n"
    assert (repo / "new.txt").read_text() == "brand new\n"
    assert resolve.undo(repo, out.snapshot_id, run=run) == "That was already undone"


def test_undo_a_pull_goes_back(repo):
    run = Real()
    start = _out(repo, "rev-parse", "HEAD")
    _advance_origin(repo)
    out = _apply(repo, PULL, run)
    assert resolve.undo(repo, out.snapshot_id, run=run).startswith("Undone")
    assert _out(repo, "rev-parse", "HEAD") == start
    assert not (repo / "up.txt").exists()


def test_undo_refuses_when_something_was_committed_after(repo):
    run = Real()
    _dirty(repo)
    out = _apply(repo, COMMIT, run, "m")
    (repo / "later.txt").write_text("later\n")
    _g(repo, "add", "later.txt")
    _g(repo, "commit", "-q", "-m", "later")
    head = _out(repo, "rev-parse", "HEAD")
    assert resolve.undo(repo, out.snapshot_id, run=run) == \
        "Something was committed after this; undo it by hand"
    assert _out(repo, "rev-parse", "HEAD") == head


def test_stash_preview_and_apply_agree_across_a_clock_tick(repo):
    run = Real()
    _dirty(repo)
    pre = resolve.preview(repo, CFG, "1.0.0", STASH, run=run)
    time.sleep(1.1)
    out = _apply(repo, STASH, run)
    assert out.ok and out.argv[-1:] == pre.argv


def test_refused_undo_on_another_branch_changes_nothing(repo):
    run = Real()
    _dirty(repo)
    out = _apply(repo, COMMIT, run, "m")
    _g(repo, "checkout", "-q", "-b", "other")
    (repo / "wip.txt").write_text("wip\n")
    _g(repo, "add", "wip.txt")
    state = (_out(repo, "rev-parse", "HEAD"), _out(repo, "rev-parse", "main"),
             _out(repo, "status", "--porcelain"), _out(repo, "symbolic-ref", "HEAD"))
    text = resolve.undo(repo, out.snapshot_id, run=run)
    assert text.startswith("Nothing was undone")
    assert state == (_out(repo, "rev-parse", "HEAD"), _out(repo, "rev-parse", "main"),
                     _out(repo, "status", "--porcelain"), _out(repo, "symbolic-ref", "HEAD"))
    assert (repo / "wip.txt").read_text() == "wip\n"


def test_log_has_one_line_per_apply_and_undo(repo):
    run = Real()
    _dirty(repo)
    out = _apply(repo, COMMIT, run, "the message", key="clean")
    resolve.undo(repo, out.snapshot_id, run=run)
    lines = (repo / ".git" / "whyline-release" / "resolve.log").read_text().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["key"] == "clean" and first["option"] == "commit"
    assert first["text"] == "the message" and first["commits"] == 1
    assert first["result"] == "kept" and first["time"]
    assert second["result"] == "undone" and second["option"] == "commit"
    assert [e.result for e in resolve.history(repo, run=run)] == ["undone", "kept"]


def test_history_is_newest_first_and_capped_at_fifty(repo):
    run = Real()
    path = repo / ".git" / "whyline-release"
    path.mkdir()
    rows = [json.dumps({"time": "t", "key": "k", "option": "stash", "text": str(i),
                        "commits": 0, "result": "kept"}) for i in range(60)]
    (path / "resolve.log").write_text("\n".join(rows) + "\nnot json\n")
    entries = resolve.history(repo, run=run)
    assert len(entries) == 50
    assert entries[0].text == "59" and entries[-1].text == "10"
    assert resolve.history(repo.parent / "nowhere", run=run) == []


# --- explain_stop ------------------------------------------------------------

def _stop(tmp_path, kind, data=None, table=None, reason="stopped", **kw):
    return resolve.explain_stop(tmp_path, kw.pop("cfg", ReleaseConfig()), "1.0.0", kind,
                                data or {}, reason, run=_run(table or {}),
                                fetch=kw.pop("fetch", _fetch), **kw)


def test_stop_merge_conflict_lists_files(tmp_path):
    res = _stop(tmp_path, "merge-conflict", {"files": ["a.py", "b.py"]})
    assert res.facts == ("bringing it in conflicts in:", "a.py", "b.py")
    assert _ids(res) == ["conflicts"]


def test_stop_dirty_is_the_clean_check(tmp_path):
    res = _stop(tmp_path, "dirty", table={"status": _res(0, " M a.py\n")})
    assert res.facts == ("a.py (changed)",)
    assert _ids(res) == ["commit", "stash", "open-files"]


def test_stop_check_failed_keeps_last_forty_lines_and_offers_only_rerun(tmp_path):
    tail = "\n".join(f"line{i}" for i in range(60))
    res = _stop(tmp_path, "check-failed", {"command": "pytest", "tail": tail})
    assert res.facts[0] == "pytest failed"
    assert res.facts[1:] == tuple(f"line{i}" for i in range(20, 60))
    assert _ids(res) == ["rerun"] and res.options[0].kind == "run"


def test_stop_push_behind_with_and_without_conflicts(tmp_path):
    table = {"rev-parse --abbrev-ref": _res(0, "x\n"), "rev-list --count": _res(0, "3\n"),
             "merge-tree": _res(0)}
    res = _stop(tmp_path, "push-behind", table=table)
    assert res.facts == ("3 commits behind origin/main", "bringing it in would not conflict")
    assert _ids(res) == ["bring"]
    table["merge-tree"] = _res(1, "tree\na.py\n")
    res = _stop(tmp_path, "push-behind", table=table)
    assert res.facts[-2:] == ("bringing it in would conflict in:", "a.py")
    assert _ids(res) == ["conflicts"]


def _tag_table(head):
    return {"rev-parse -q --verify refs/tags/v1.0.0": _res(0, "abc1234567\n"),
            "rev-parse HEAD": _res(0, head + "\n")}


def test_stop_tag_exists_on_this_releases_own_commit_has_no_option(tmp_path):
    for kind in ("tag-exists", "release-exists"):
        res = _stop(tmp_path, kind, table=_tag_table("abc1234567"))
        assert res.facts == ("v1.0.0 points at abc1234",
                             "It is this release's own, so resuming is safe")
        assert res.options == ()


def test_stop_tag_exists_on_another_commit_offers_a_version(tmp_path):
    table = {**_tag_table("def7654321"), "ls-remote --tags origin": _res(0, "")}
    res = _stop(tmp_path, "tag-exists", table=table, get=lambda url: 404)
    assert res.facts[0] == "v1.0.0 points at abc1234"
    assert _ids(res) == ["version-1.0.1"]


def test_stop_publish_failed_uses_each_targets_own_completion_check(tmp_path, monkeypatch):
    from whyline.release import targets
    from whyline.release.config import CustomTarget as Entry
    from whyline.release.engine import Step
    from whyline.release.targets.custom import CustomTarget

    class Brew:  # production shape: no _published, only a step's done_check
        key = "homebrew"
        title = "Homebrew"

        def steps(self, root, cfg, version, *, run, fetch):
            return [Step("homebrew", "Update the Homebrew formula", True, lambda: True,
                         lambda cancel: None)]

    def shell(command, root, env, on_line):
        return (0 if command == "ok" else 1), []

    cfg = ReleaseConfig(targets=Targets(custom=(Entry(name="a", run="r", verify="ok"),
                                                Entry(name="b", run="r", verify="bad"))))
    monkeypatch.setattr(targets, "enabled", lambda c: [Brew(), CustomTarget(shell=shell)])
    res = resolve.explain_stop(tmp_path, cfg, "1.0.0", "publish-failed", {}, "stopped",
                               run=_run({}), fetch=_fetch)
    assert res.facts == ("Update the Homebrew formula: published",
                         "Run custom target a: published",
                         "Run custom target b: not published", "Resume continues from Verify")
    assert res.options == ()


def test_stop_check_rerun_runs_that_one_command_and_shows_its_tail(tmp_path):
    cfg = ReleaseConfig(checks=("pytest -q",))
    res = resolve.explain_stop(tmp_path, cfg, "1.0.0", "check-failed",
                               {"command": "pytest -q", "tail": "x"}, "stopped",
                               run=_run({}), fetch=_fetch)
    option = res.options[0]
    assert option.command == "pytest -q"
    seen = []

    def shell(command, root, on_line):
        seen.append(command)
        return 1, [f"line{i}" for i in range(60)]

    out = resolve.apply(tmp_path, cfg, "1.0.0", option, run=_run({}), fetch=_fetch,
                        run_shell=shell)
    assert seen == ["pytest -q"] and not out.ok
    assert out.text.splitlines() == ["pytest -q failed", *[f"line{i}" for i in range(20, 60)]]
    assert "pytest -q" in resolve.preview(tmp_path, cfg, "1.0.0", option, run=_run({})).lines[0]


def test_rerun_refuses_a_command_that_is_not_a_configured_check(tmp_path):
    cfg = ReleaseConfig(checks=("pytest -q",))
    option = resolve.Option("rerun", "x", "run", command="rm -rf /")

    def shell(*a):
        raise AssertionError("must not run")

    out = resolve.apply(tmp_path, cfg, "1.0.0", option, run=_run({}), fetch=_fetch,
                        run_shell=shell)
    assert not out.ok
    assert "not one of" in resolve.preview(tmp_path, cfg, "1.0.0", option, run=_run({})).lines[0]


def test_stop_without_a_kind_gives_the_reason(tmp_path):
    res = _stop(tmp_path, "", reason="Build failed: boom")
    assert res.facts == ("Build failed: boom",) and res.options == ()


def _stop_real(repo, kind):
    return resolve.explain_stop(repo, ReleaseConfig(), "1.0.0", kind, {}, "stopped",
                                run=Real(), fetch=_fetch, get=lambda url: 404)


def test_stop_tag_on_head_after_merging_main_is_own(repo):
    _g(repo, "commit", "-q", "--allow-empty", "-m", "chore: release v1.0.0")
    _g(repo, "tag", "v1.0.0")
    _g(repo, "checkout", "-q", "-b", "side")
    _advance_origin(repo)
    _g(repo, "fetch", "-q", "origin")
    _g(repo, "merge", "-q", "--no-ff", "-m", "Merge main", "origin/main")
    _g(repo, "tag", "-f", "v1.0.0")
    res = _stop_real(repo, "tag-exists")
    assert res.facts[-1] == "It is this release's own, so resuming is safe"
    assert res.options == ()


def test_stop_remote_tag_on_an_older_commit_beats_the_new_local_tag(repo):
    _g(repo, "tag", "-a", "-m", "old", "v1.0.0")
    _g(repo, "push", "-q", "origin", "v1.0.0")
    _g(repo, "commit", "-q", "--allow-empty", "-m", "chore: release v1.0.0")
    _g(repo, "tag", "-f", "v1.0.0")
    res = _stop_real(repo, "tag-exists")
    assert "It is this release's own, so resuming is safe" not in res.facts
    assert _ids(res) == ["version-1.0.1"]


def test_stop_tag_on_an_older_ancestor_is_not_own(repo):
    _g(repo, "commit", "-q", "--allow-empty", "-m", "chore: release v1.0.0")
    _g(repo, "tag", "v1.0.0")
    _g(repo, "commit", "-q", "--allow-empty", "-m", "later work")
    res = _stop_real(repo, "tag-exists")
    assert "It is this release's own, so resuming is safe" not in res.facts
    assert _ids(res) == ["version-1.0.1"]
