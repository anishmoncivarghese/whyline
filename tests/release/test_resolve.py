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
