import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.release import targets
from whyline.release.config import HomebrewTarget as BrewOptions
from whyline.release.config import ReleaseConfig, Targets
from whyline.release.github import StepError
from whyline.release.targets import homebrew

ORIGIN = "git@github.com:Octo/Demo.git\n"
TARBALL = b"fixture tarball bytes"
SHA = hashlib.sha256(TARBALL).hexdigest()
URL = "https://github.com/Octo/Demo/archive/refs/tags/v1.2.3.tar.gz"
OLD = """class Demo < Formula
  include Language::Python::Virtualenv

  desc "Demo"
  url "https://github.com/Octo/Demo/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "aaaa"

  resource "requests" do
    url "https://files.example/requests-2.0.tar.gz"
    sha256 "bbbb"
  end

  test do
    system bin/"demo", "--version"
  end
end
"""
NO_RESOURCES = OLD.split("  resource")[0] + "  test do\n  end\nend\n"


def cfg(tap="", formula=""):
    return ReleaseConfig(targets=Targets(homebrew=True,
                                         homebrew_options=BrewOptions(tap=tap, formula=formula)))


def proc(code=0, out="", err=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


def project(tmp_path, name="demo"):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
    return tmp_path


def runner(tmp_path=None, calls=None, remote=OLD, exists=True, push="true", pull_fail=False):
    """A fake gh/git. `gh repo clone` creates the tap directory with the formula."""
    def run(args, cwd=None, **kw):
        if calls is not None:
            calls.append((list(args), cwd))
        if args[:3] == ["git", "remote", "get-url"]:
            return proc(0, ORIGIN)
        if args[:3] == ["gh", "repo", "view"]:
            return proc(0 if exists else 1)
        if args[:2] == ["gh", "api"] and ".permissions.push" in args:
            return proc(0, push)
        if args[:2] == ["gh", "api"] and "/contents/" in args[2]:
            if remote is None:
                return proc(1, err="Not Found")
            return proc(0, base64.encodebytes(remote.encode()).decode())
        if args[:3] == ["gh", "repo", "clone"]:
            dest = Path(args[4])
            (dest / ".git").mkdir(parents=True)
            (dest / "Formula").mkdir()
            (dest / "Formula" / "demo.rb").write_text(OLD)
            return proc(0)
        if args[:2] == ["git", "pull"]:
            return proc(1, err="conflict") if pull_fail else proc(0)
        return proc(0)
    return run


def target(brew=True, body=TARBALL, seen=None):
    def download(url):
        if seen is not None:
            seen.append(url)
        return body
    return homebrew.HomebrewTarget(download=download,
                                   which=lambda name: "/opt/homebrew/bin/brew" if brew else None)


def ready(tmp_path, config, run):
    return {i.key: i for i in homebrew.HomebrewTarget().ready_items(
        tmp_path, config, "1.2.3", run=run, fetch=None)}


def test_registered():
    assert targets.REGISTRY["homebrew"].key == "homebrew"


def test_defaults_and_install_lines(tmp_path):
    project(tmp_path)
    run = runner()
    assert homebrew.tap_repo(tmp_path, cfg(), run) == "Octo/homebrew-tap"
    assert homebrew.formula_name(tmp_path, cfg(), run) == "demo"
    assert homebrew.install_lines(tmp_path, cfg(), run) == [
        "brew tap Octo/tap", "brew install demo"]
    assert homebrew.tap_repo(tmp_path, cfg("me/tools", "x"), run) == "me/homebrew-tools"
    assert homebrew.formula_name(tmp_path, cfg("me/tools", "x"), run) == "x"


def test_create_tap_argv_is_public():
    calls = []
    assert homebrew.create_tap("octo", "tap", run=runner(calls=calls)) == "octo/homebrew-tap"
    assert calls[0][0] == ["gh", "repo", "create", "octo/homebrew-tap", "--public"]
    assert "public" in homebrew.PUBLIC_NOTE


def test_create_tap_failure_and_empty():
    with pytest.raises(StepError):
        homebrew.create_tap("", "tap", run=runner())
    with pytest.raises(StepError) as err:
        homebrew.create_tap("octo", "tap", run=lambda a, **k: proc(1, err="exists"))
    assert "exists" in str(err.value)


def test_replace_source_changes_only_the_two_lines():
    new = homebrew.replace_source(OLD, URL, SHA)
    old_lines, new_lines = OLD.splitlines(), new.splitlines()
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert len(old_lines) == len(new_lines) and len(changed) == 2
    assert new_lines[changed[0]] == f'  url "{URL}"'
    assert new_lines[changed[1]] == f'  sha256 "{SHA}"'
    assert 'url "https://files.example/requests-2.0.tar.gz"' in new
    assert 'sha256 "bbbb"' in new


def test_replace_source_needs_both_lines():
    with pytest.raises(StepError):
        homebrew.replace_source("class X < Formula\nend\n", URL, SHA)


def _run_step(tmp_path, tgt, run, config=None):
    [step] = tgt.steps(tmp_path, config or cfg(), "1.2.3", run=run, fetch=None)
    assert step.id == "homebrew" and step.irreversible
    step.run(None)
    return step


def test_step_hashes_the_tarball_and_pushes(tmp_path):
    project(tmp_path)
    calls, seen = [], []
    _run_step(tmp_path, target(seen=seen), runner(calls=calls))
    assert seen == [URL]
    clone = tmp_path / ".git" / "whyline-release" / "tap"
    text = (clone / "Formula" / "demo.rb").read_text()
    assert f'url "{URL}"' in text and f'sha256 "{SHA}"' in text
    argvs = [c[0] for c in calls]
    assert ["gh", "repo", "clone", "Octo/homebrew-tap", str(clone)] in argvs
    assert ["git", "commit", "-m", "demo 1.2.3"] in argvs
    assert argvs.index(["git", "commit", "-m", "demo 1.2.3"]) < argvs.index(["git", "push", "-u", "origin", "HEAD"])


def test_step_updates_resources_when_brew_exists(tmp_path):
    project(tmp_path)
    calls = []
    tgt = target(brew=True)
    _run_step(tmp_path, tgt, runner(calls=calls))
    formula = str(tmp_path / ".git" / "whyline-release" / "tap" / "Formula" / "demo.rb")
    assert ["brew", "update-python-resources", formula] in [c[0] for c in calls]
    assert tgt.warnings == []


def test_step_warns_and_keeps_resources_without_brew(tmp_path):
    project(tmp_path)
    calls = []
    tgt = target(brew=False)
    _run_step(tmp_path, tgt, runner(calls=calls))
    assert not any(c[0][0] == "brew" for c in calls)
    assert tgt.warnings == [homebrew.NO_BREW_NOTE]
    text = (tmp_path / ".git" / "whyline-release" / "tap" / "Formula" / "demo.rb").read_text()
    assert 'sha256 "bbbb"' in text
    ok, note = tgt.verify(tmp_path, cfg(), "1.2.3",
                          run=runner(remote=OLD.replace("v1.0.0", "v1.2.3")), fetch=None)
    assert ok and "brew is not installed" in note


def test_step_skips_brew_when_formula_has_no_resources(tmp_path):
    project(tmp_path)
    calls = []

    def run(args, cwd=None, **kw):
        res = runner(calls=calls)(args, cwd=cwd, **kw)
        if args[:3] == ["gh", "repo", "clone"]:
            (tmp_path / ".git" / "whyline-release" / "tap" / "Formula" / "demo.rb"
             ).write_text(NO_RESOURCES)
        return res

    tgt = target(brew=True)
    _run_step(tmp_path, tgt, run)
    assert not any(c[0][0] == "brew" for c in calls) and tgt.warnings == []


def test_step_reuses_the_clone_with_git_pull(tmp_path):
    project(tmp_path)
    clone = tmp_path / ".git" / "whyline-release" / "tap"
    (clone / ".git").mkdir(parents=True)
    (clone / "Formula").mkdir()
    (clone / "Formula" / "demo.rb").write_text(OLD)
    calls = []
    _run_step(tmp_path, target(), runner(calls=calls))
    argvs = [c[0] for c in calls]
    assert not any(a[:3] == ["gh", "repo", "clone"] for a in argvs)
    assert any(a[:2] == ["git", "pull"] for a in argvs)


def test_reused_clone_is_reset_before_pull(tmp_path):
    project(tmp_path)
    clone = tmp_path / ".git" / "whyline-release" / "tap"
    (clone / ".git").mkdir(parents=True)
    (clone / "Formula").mkdir()
    (clone / "Formula" / "demo.rb").write_text(OLD)
    calls = []
    _run_step(tmp_path, target(), runner(calls=calls))
    argvs = [c[0] for c in calls]
    assert argvs.index(["git", "reset", "--hard", "@{u}"]) < argvs.index(["git", "pull", "--ff-only"])
    assert ["git", "clean", "-fd"] in argvs


def test_clone_without_upstream_is_recreated(tmp_path):
    project(tmp_path)
    clone = tmp_path / ".git" / "whyline-release" / "tap"
    (clone / ".git").mkdir(parents=True)
    (clone / "stale.txt").write_text("x")
    calls = []
    base = runner(calls=calls)

    def run(args, cwd=None, **kw):
        if args[:2] == ["git", "reset"]:
            calls.append((list(args), cwd))
            return proc(1, err="no upstream")
        return base(args, cwd=cwd, **kw)
    _run_step(tmp_path, target(), run)
    assert any(c[0][:3] == ["gh", "repo", "clone"] for c in calls)
    assert not (clone / "stale.txt").exists()


def test_step_failures_do_not_push(tmp_path):
    project(tmp_path)
    clone = tmp_path / ".git" / "whyline-release" / "tap"
    (clone / ".git").mkdir(parents=True)
    calls = []
    [step] = target().steps(tmp_path, cfg(), "1.2.3", run=runner(calls=calls, pull_fail=True),
                            fetch=None)
    with pytest.raises(StepError):
        step.run(None)

    def broken(url):
        raise OSError("offline")
    tgt = homebrew.HomebrewTarget(download=broken)
    [step] = tgt.steps(tmp_path, cfg(), "1.2.3", run=runner(calls=calls), fetch=None)
    with pytest.raises(StepError):
        step.run(None)
    assert not any(c[0][:2] == ["git", "push"] for c in calls)


def test_done_check_is_the_new_url_on_the_remote(tmp_path):
    project(tmp_path)
    [step] = target().steps(tmp_path, cfg(), "1.2.3", run=runner(remote=OLD), fetch=None)
    assert step.done_check() is False
    [step] = target().steps(tmp_path, cfg(), "1.2.3",
                            run=runner(remote=OLD.replace("v1.0.0", "v1.2.3")), fetch=None)
    assert step.done_check() is True
    [step] = target().steps(tmp_path, cfg(), "1.2.3", run=runner(remote=None), fetch=None)
    assert step.done_check() is False


def test_verify_reads_the_remote_formula(tmp_path):
    project(tmp_path)
    tgt = target()
    assert tgt.verify(tmp_path, cfg(), "1.2.3",
                      run=runner(remote=OLD.replace("v1.0.0", "v1.2.3")), fetch=None) == (True, "")
    good, text = tgt.verify(tmp_path, cfg(), "1.2.3", run=runner(remote=OLD), fetch=None)
    assert not good and "v1.2.3" in text
    good, text = tgt.verify(tmp_path, cfg(), "1.2.3", run=runner(remote=None), fetch=None)
    assert not good and "could not read" in text


def test_verify_calls_the_contents_api(tmp_path):
    project(tmp_path)
    calls = []
    target().verify(tmp_path, cfg(), "1.2.3", run=runner(calls=calls), fetch=None)
    assert any(c[0][:3] == ["gh", "api", "repos/Octo/homebrew-tap/contents/Formula/demo.rb"]
               for c in calls)


def test_ready_all_good(tmp_path):
    project(tmp_path)
    items = ready(tmp_path, cfg(), runner())
    assert set(items) == {"homebrew-tap", "homebrew-formula", "homebrew-push"}
    assert all(i.ok for i in items.values())


def test_ready_missing_tap_stops_early(tmp_path):
    project(tmp_path)
    items = ready(tmp_path, cfg(), runner(exists=False))
    assert not items["homebrew-tap"].ok and "Create tap" in items["homebrew-tap"].fix
    assert "homebrew-formula" not in items


def test_ready_missing_formula_and_no_push(tmp_path):
    project(tmp_path)
    items = ready(tmp_path, cfg(), runner(remote=None, push="false"))
    assert items["homebrew-tap"].ok
    assert not items["homebrew-formula"].ok and "Draft formula" in items["homebrew-formula"].fix
    assert not items["homebrew-push"].ok


def test_draft_goes_through_ask_agent_and_is_not_written(tmp_path):
    project(tmp_path)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return "```ruby\nclass Demo < Formula\nend\n```"

    text = homebrew.draft_formula(tmp_path, ask_agent=ask)
    assert text == "class Demo < Formula\nend\n"
    for part in ("Language::Python::Virtualenv", "--version", "demo", "pyproject.toml"):
        assert part in prompts[0]
    assert not (tmp_path / "Formula").exists()
    assert not (tmp_path / ".git").exists()
    with pytest.raises(StepError):
        homebrew.draft_formula(tmp_path, ask_agent=lambda p: " ")


def test_push_draft_commits_only_when_called(tmp_path):
    project(tmp_path)
    calls = []
    run = runner(calls=calls)
    homebrew.draft_formula(tmp_path, ask_agent=lambda p: "class Demo < Formula\nend")
    assert calls == []
    homebrew.push_draft(tmp_path, "Octo/homebrew-tap", "demo", "class Demo < Formula\nend",
                        run=run)
    argvs = [c[0] for c in calls]
    assert ["git", "add", "Formula/demo.rb"] in argvs and ["git", "push", "-u", "origin", "HEAD"] in argvs
    clone = tmp_path / ".git" / "whyline-release" / "tap"
    assert (clone / "Formula" / "demo.rb").read_text() == "class Demo < Formula\nend\n"
    with pytest.raises(StepError):
        homebrew.push_draft(tmp_path, "Octo/homebrew-tap", "demo", "  ", run=run)


def test_setup_status_lines(tmp_path):
    project(tmp_path)
    lines = homebrew.HomebrewTarget().setup_status(tmp_path, cfg(), run=runner())
    assert "Tap: Octo/homebrew-tap (found)" in lines and "Formula: demo" in lines
    assert "Push access: yes" in lines
