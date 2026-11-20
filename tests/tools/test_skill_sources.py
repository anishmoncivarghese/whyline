import os
import subprocess

import pytest

from whyline.tools import skill_sources
from whyline.tools.skill_sources import Source


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def _skill(folder, name, description="does a thing", extra=""):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{extra}", encoding="utf-8")


def _clone(home, source, *, stamp=True):
    base = home / ".whyline" / "skill-sources" / source.name
    base.mkdir(parents=True, exist_ok=True)
    if stamp:
        (home / ".whyline" / "skill-sources" / f"{source.name}.fetched").write_text(
            "2026-11-20T00:00:00Z", encoding="utf-8")
    return base


def test_no_fetch_without_asking(home):
    calls = []

    def run(*a, **k):
        calls.append(a)
        raise AssertionError("git must not run")

    source = skill_sources.add("mine", "https://github.com/me/skills", "skills")
    _skill(_clone(home, source) / "skills" / "pdf", "pdf")
    skill_sources.load()
    skill_sources.index(source)
    skill_sources.search("pdf")
    assert calls == []


def test_fetch_argv_for_new_and_existing_clone(home):
    calls = []

    class Done:
        returncode = 0
        stdout = "abc123\n"
        stderr = ""

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Done()

    source = Source("mine", "https://github.com/me/skills", branch="dev")
    assert skill_sources.fetch(source, run=run) == "abc123"
    dest = str(home / ".whyline" / "skill-sources" / "mine")
    hook = ["git", "-c", "core.hooksPath=/dev/null"]
    assert calls[0][0] == [*hook, "clone", "--depth", "1", "--branch", "dev", "--",
                           "https://github.com/me/skills", dest]
    assert calls[1][0] == [*hook, "-C", dest, "rev-parse", "HEAD"]
    for _, kwargs in calls:
        assert kwargs["timeout"] == 120
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert skill_sources.fetched(source)

    (home / ".whyline" / "skill-sources" / "mine" / ".git").mkdir(parents=True)
    calls.clear()
    skill_sources.fetch(source, run=run)
    assert calls[0][0] == [*hook, "-C", dest, "fetch", "--depth", "1", "origin", "dev"]
    assert calls[1][0] == [*hook, "-C", dest, "reset", "--hard", "FETCH_HEAD"]


def test_fetch_failure_raises(home):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 128, "", "fatal: nope\n")

    with pytest.raises(RuntimeError, match="nope"):
        skill_sources.fetch(Source("mine", "https://github.com/me/skills"), run=run)
    assert skill_sources.fetched(Source("mine", "https://github.com/me/skills")) is None


@pytest.mark.parametrize("url", [
    "http://github.com/me/skills", "git@github.com:me/skills.git", "file:///tmp/x",
    "https://github.com", "https://github.com/", "https:///me/skills",
    "https://user:pw@github.com/me/skills", "ssh://github.com/me/skills",
])
def test_bad_url_refused(home, url):
    with pytest.raises(ValueError):
        skill_sources.add("mine", url)
    assert not (home / ".whyline" / "skill-sources.toml").exists()


def test_bad_name_path_and_branch_refused(home):
    url = "https://github.com/me/skills"
    for kwargs in ({"name": "Bad Name"}, {"path": "../x"}, {"path": "/abs"}, {"branch": "--upload-pack=x"}):
        with pytest.raises(ValueError):
            skill_sources.add(**{"name": "mine", "url": url, **kwargs})
    with pytest.raises(ValueError):
        skill_sources.add("anthropic", url)


def test_add_load_remove(home):
    skill_sources.add("mine", "https://github.com/me/skills", "a/b", "main")
    mine = [s for s in skill_sources.load() if not s.builtin]
    assert mine == [Source("mine", "https://github.com/me/skills", "a/b", "main")]
    assert skill_sources.remove("mine") is True
    assert skill_sources.remove("mine") is False
    assert [s for s in skill_sources.load() if not s.builtin] == []


def test_builtins(home):
    by_name = {s.name: s for s in skill_sources.load()}
    assert by_name["anthropic"].path == "skills" and by_name["anthropic"].licence == ""
    assert by_name["agentic"].licence == "MIT, text CC BY 4.0"
    assert by_name["composio"].path == ""
    assert [s.kind for s in by_name.values()].count("directory") == 2
    assert all(s.builtin for s in by_name.values())


def test_builtin_turned_off_not_removed(home):
    with pytest.raises(ValueError):
        skill_sources.remove("anthropic")
    skill_sources.set_enabled("anthropic", False)
    by_name = {s.name: s for s in skill_sources.load()}
    assert by_name["anthropic"].enabled is False and by_name["agentic"].enabled
    _skill(_clone(home, by_name["anthropic"]) / "skills" / "pdf", "pdf")
    assert skill_sources.search("pdf") == []
    skill_sources.set_enabled("anthropic", True)
    assert [e.name for e in skill_sources.search("pdf")] == ["pdf"]


def test_index_skips_symlinks_and_folders_without_manifest(home):
    source = skill_sources.add("mine", "https://github.com/me/skills", "skills")
    base = _clone(home, source)
    top = base / "skills"
    _skill(top / "good", "good", "a good one")
    (top / "good" / "ref.txt").write_text("hello", encoding="utf-8")
    (top / "empty").mkdir()
    (top / "empty" / "notes.md").write_text("x", encoding="utf-8")
    outside = home / "outside"
    _skill(outside, "outside")
    os.symlink(outside, top / "linked")
    _skill(top / "manifest-link", "ml")
    (top / "manifest-link" / "SKILL.md").unlink()
    os.symlink(outside / "SKILL.md", top / "manifest-link" / "SKILL.md")
    _skill(top / "huge", "huge", extra="x" * 1_000_001)
    (top / "good" / "leak").symlink_to(outside)

    found = skill_sources.index(source)
    assert [e.name for e in found] == ["good"]
    entry = found[0]
    assert entry.source == "mine" and entry.description == "a good one"
    assert entry.path == "skills/good"
    assert entry.files == ("SKILL.md", "ref.txt")
    assert entry.size == sum(len(p.read_bytes()) for p in (top / "good").iterdir() if p.is_file() and not p.is_symlink())


def test_index_of_directory_kind_or_missing_clone_is_empty(home):
    directory = next(s for s in skill_sources.load() if s.kind == "directory")
    assert skill_sources.index(directory) == []
    assert skill_sources.index(Source("mine", "https://github.com/me/skills")) == []


def test_search_order_and_cap(home):
    source = skill_sources.add("mine", "https://github.com/me/skills")
    base = _clone(home, source)
    _skill(base / "b-notes", "b-notes", "works with a pdf file")
    _skill(base / "pdf-tools", "pdf-tools", "merge things")
    _skill(base / "a-pdf", "a-pdf", "other")
    _skill(base / "unrelated", "unrelated", "nothing")
    assert [e.name for e in skill_sources.search("pdf")] == ["a-pdf", "pdf-tools", "b-notes"]
    assert [e.name for e in skill_sources.search("PDF merge")] == ["pdf-tools"]
    assert skill_sources.search("") == []
    assert skill_sources.search("zebra") == []

    for i in range(250):
        _skill(base / f"bulk-{i:03}", f"bulk-{i:03}", "many")
    assert len(skill_sources.search("bulk")) == 200


def test_search_ignores_sources_never_fetched(home):
    source = skill_sources.add("mine", "https://github.com/me/skills")
    _skill(_clone(home, source, stamp=False) / "pdf", "pdf")
    assert skill_sources.search("pdf") == []


def test_fetch_default_branch(home):
    calls = []

    class Done:
        returncode = 0
        stdout = "commit999\n"
        stderr = ""

    def run(argv, **kwargs):
        calls.append(argv)
        return Done()

    source = Source("mine", "https://github.com/me/skills")
    assert skill_sources.fetch(source, run=run) == "commit999"
    dest = str(home / ".whyline" / "skill-sources" / "mine")
    hook = ["git", "-c", "core.hooksPath=/dev/null"]
    assert calls[0] == [*hook, "clone", "--depth", "1", "--",
                        "https://github.com/me/skills", dest]
    assert calls[1] == [*hook, "-C", dest, "rev-parse", "HEAD"]

    (home / ".whyline" / "skill-sources" / "mine" / ".git").mkdir(parents=True)
    calls.clear()
    assert skill_sources.fetch(source, run=run) == "commit999"
    assert calls[0] == [*hook, "-C", dest, "fetch", "--depth", "1", "origin", "HEAD"]
    assert calls[1] == [*hook, "-C", dest, "reset", "--hard", "FETCH_HEAD"]


def test_set_enabled_unknown_raises(home):
    with pytest.raises(ValueError, match="not a built-in"):
        skill_sources.set_enabled("nonexistent", False)


def test_load_corrupt_toml(home):
    toml = home / ".whyline" / "skill-sources.toml"
    toml.parent.mkdir(parents=True, exist_ok=True)
    toml.write_text("invalid [[ toml syntax", encoding="utf-8")
    loaded = skill_sources.load()
    assert len(loaded) == len(skill_sources.BUILTIN)

