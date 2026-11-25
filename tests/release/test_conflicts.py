import subprocess
from pathlib import Path

import pytest

from whyline.release import conflicts
from whyline.release.config import ReleaseConfig
from whyline.release.ready import default_run

CFG = ReleaseConfig()  # branch main
IDLE = lambda root: False  # noqa: E731


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout


def setup(tmp_path: Path, base: dict[str, str], ours: dict[str, str | None],
          theirs: dict[str, str | None]) -> Path:
    """main (as origin/main) and a feature branch both change `base` files."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@t")
    put(root, base)
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    git(root, "checkout", "-b", "feature")
    put(root, ours)
    git(root, "add", "-A")
    git(root, "commit", "-m", "ours")
    git(root, "checkout", "main")
    put(root, theirs)
    git(root, "add", "-A")
    git(root, "commit", "-m", "theirs")
    git(root, "update-ref", "refs/remotes/origin/main", "main")
    git(root, "checkout", "feature")
    return root


def put(root: Path, files: dict[str, str | None]) -> None:
    for name, text in files.items():
        if text is None:
            (root / name).unlink()
        else:
            (root / name).write_text(text, encoding="utf-8")


def one(tmp_path, base, ours, theirs) -> conflicts.Conflict:
    root = setup(tmp_path, {"f.md": base}, {"f.md": ours}, {"f.md": theirs})
    found = conflicts.read(root, "main", run=default_run)
    assert [c.path for c in found] == ["f.md"]
    return found[0]


TASKS = "- [ ] A\n- [ ] B\n- [ ] C\n"


def test_ticks_only_conflict_keeps_ticks(tmp_path):
    root = setup(tmp_path, {"p.md": TASKS},
                 {"p.md": "- [x] A\n- [ ] B\n- [ ] C\n"},
                 {"p.md": "- [ ] A\n- [x] B\n- [ ] C\n"})
    [c] = conflicts.read(root, "main", run=default_run)
    assert c.reading == conflicts.TICKS
    assert c.default == "ticks"
    assert c.choices == ("ticks", "ours", "theirs", "agent")
    text = conflicts.preview(root, "main", {"p.md": "ticks"}, run=default_run)["p.md"]
    assert text == "- [x] A\n- [x] B\n- [ ] C\n"


def test_ticks_on_this_branch_only_and_on_main_only(tmp_path):
    base = "- [ ] A\n- [ ] B\n"
    # the trailing space makes the other side a real change that still reads as ticks only
    for name, ours, theirs, want in (
            ("mine", "- [x] A\n- [x] B\n", "- [ ] A\n- [ ] B \n", "- [x] A\n- [x] B\n"),
            ("main", "- [ ] A\n- [ ] B \n", "- [x] A\n- [x] B\n", "- [x] A\n- [x] B \n")):
        (tmp_path / name).mkdir()
        root = setup(tmp_path / name, {"p.md": base}, {"p.md": ours}, {"p.md": theirs})
        [c] = conflicts.read(root, "main", run=default_run)
        assert c.reading == conflicts.TICKS
        text = conflicts.preview(root, "main", {"p.md": "ticks"}, run=default_run)["p.md"]
        assert text == want


def test_ticks_on_this_branch_and_on_main_in_one_place(tmp_path):
    root = setup(tmp_path, {"p.md": TASKS},
                 {"p.md": "- [x] A\n- [x] B\n- [ ] C\n"},
                 {"p.md": "- [ ] A\n- [ ] B\n- [x] C\n"})
    text = conflicts.preview(root, "main", {"p.md": "ticks"}, run=default_run)["p.md"]
    assert text == "- [x] A\n- [x] B\n- [x] C\n"


def test_reading_same_lines(tmp_path):
    c = one(tmp_path, "a\nb\n", "a\nnew  \nb\n", "a\nnew\nb\n")
    assert c.reading == conflicts.SAME
    assert c.default == ""
    assert c.choices == ("ours", "theirs", "agent")


def test_reading_version_only(tmp_path):
    c = one(tmp_path, 'name = "x"\nversion = "1.0"\n', 'name = "x"\nversion = "1.1"\n',
            'name = "x"\nversion = "1.2"\n')
    assert c.reading == conflicts.VERSION
    assert c.places == 1


def test_reading_none(tmp_path):
    c = one(tmp_path, "a\nb\n", "a\nours\n", "a\ntheirs\n")
    assert c.reading == ""
    assert c.kind == "lines"
    assert c.default == ""


def test_ours_and_theirs_touch_only_conflicting_places(tmp_path):
    base = "top\nx\nmid1\nmid2\nmid3\nmid4\nmid5\ny\nend\n"
    root = setup(tmp_path, {"f.txt": base},
                 {"f.txt": "top\nOURS1\nmid1\nmid2\nmid3\nmid4\nmid5\nOURS2\nend\n"},
                 {"f.txt": "top\nTHEIRS1\nmid1\nmid2\nmid3\nmid4\nmid5\nTHEIRS2\nend\n"})
    [c] = conflicts.read(root, "main", run=default_run)
    assert c.places == 2
    ours = conflicts.preview(root, "main", {"f.txt": "ours"}, run=default_run)["f.txt"]
    theirs = conflicts.preview(root, "main", {"f.txt": "theirs"}, run=default_run)["f.txt"]
    assert ours == "top\nOURS1\nmid1\nmid2\nmid3\nmid4\nmid5\nOURS2\nend\n"
    assert theirs == "top\nTHEIRS1\nmid1\nmid2\nmid3\nmid4\nmid5\nTHEIRS2\nend\n"


def test_preview_changes_nothing_and_omits_agent(tmp_path):
    root = setup(tmp_path, {"f.txt": "a\n"}, {"f.txt": "b\n"}, {"f.txt": "c\n"})
    before = git(root, "status", "--porcelain"), git(root, "for-each-ref")
    assert conflicts.preview(root, "main", {"f.txt": "agent"}, run=default_run) == {}
    assert (git(root, "status", "--porcelain"), git(root, "for-each-ref")) == before
    with pytest.raises(ValueError):
        conflicts.preview(root, "main", {"f.txt": "ticks"}, run=default_run)


def test_deleted_file_conflict_offers_agent_only(tmp_path):
    root = setup(tmp_path, {"f.txt": "a\nb\n"}, {"f.txt": "a\nours\n"}, {"f.txt": None})
    [c] = conflicts.read(root, "main", run=default_run)
    assert c.kind == "deleted"
    assert c.choices == ("agent",)
    assert c.default == ""
    out = conflicts.merge(root, CFG, "1.0", {"f.txt": "agent"}, run=default_run,
                          relay_running=IDLE)
    assert not out.ok and "f.txt" in out.text


def test_binary_conflict_offers_agent_only(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "b.bin").write_bytes(b"\0\1base")
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    git(root, "checkout", "-b", "feature")
    (root / "b.bin").write_bytes(b"\0\2ours")
    git(root, "commit", "-am", "ours")
    git(root, "checkout", "main")
    (root / "b.bin").write_bytes(b"\0\3theirs")
    git(root, "commit", "-am", "theirs")
    git(root, "update-ref", "refs/remotes/origin/main", "main")
    git(root, "checkout", "feature")
    [c] = conflicts.read(root, "main", run=default_run)
    assert (c.kind, c.choices) == ("binary", ("agent",))


def test_non_utf8_binary_conflict_is_binary(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "b.png").write_bytes(b"\x89PNG\r\n\x1a\nbase\xff")
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    git(root, "checkout", "-b", "feature")
    (root / "b.png").write_bytes(b"\x89PNG\r\n\x1a\nours\xff\xfe")
    git(root, "commit", "-am", "ours")
    git(root, "checkout", "main")
    (root / "b.png").write_bytes(b"\x89PNG\r\n\x1a\ntheirs\xff\xfe")
    git(root, "commit", "-am", "theirs")
    git(root, "update-ref", "refs/remotes/origin/main", "main")
    git(root, "checkout", "feature")
    [c] = conflicts.read(root, "main", run=default_run)
    assert (c.kind, c.choices) == ("binary", ("agent",))


def test_clean_merge_has_no_conflicts(tmp_path):
    root = setup(tmp_path, {"a.txt": "1\n", "b.txt": "1\n"}, {"a.txt": "2\n"}, {"b.txt": "2\n"})
    assert conflicts.read(root, "main", run=default_run) == []


def test_merge_commits_with_message_and_choice_lines(tmp_path):
    root = setup(tmp_path, {"p.md": TASKS, "f.txt": "a\n"},
                 {"p.md": "- [x] A\n- [ ] B\n- [ ] C\n", "f.txt": "ours\n"},
                 {"p.md": "- [ ] A\n- [x] B\n- [ ] C\n", "f.txt": "theirs\n"})
    out = conflicts.merge(root, CFG, "1.2.3", {"p.md": "ticks", "f.txt": "theirs"},
                          run=default_run, relay_running=IDLE)
    assert out.ok, out.text
    assert out.snapshot_id
    body = git(root, "log", "-1", "--format=%B").strip()
    assert body == ("merge: bring main into feature for v1.2.3\n\n"
                    "f.txt: theirs\np.md: ticks")
    assert len(git(root, "log", "-1", "--format=%P").split()) == 2
    assert (root / "p.md").read_text() == "- [x] A\n- [x] B\n- [ ] C\n"
    assert (root / "f.txt").read_text() == "theirs\n"
    assert git(root, "status", "--porcelain") == ""


def test_merge_refuses_without_a_choice_or_with_agent(tmp_path):
    root = setup(tmp_path, {"f.txt": "a\n"}, {"f.txt": "b\n"}, {"f.txt": "c\n"})
    head = git(root, "rev-parse", "HEAD")
    for choices in ({}, {"f.txt": "agent"}):
        out = conflicts.merge(root, CFG, "1", choices, run=default_run, relay_running=IDLE)
        assert not out.ok and "f.txt" in out.text
    assert git(root, "rev-parse", "HEAD") == head
    assert git(root, "status", "--porcelain") == ""


def test_merge_refuses_when_dirty_or_relay_running(tmp_path):
    root = setup(tmp_path, {"f.txt": "a\n"}, {"f.txt": "b\n"}, {"f.txt": "c\n"})
    (root / "stray.txt").write_text("x")
    out = conflicts.merge(root, CFG, "1", {"f.txt": "ours"}, run=default_run, relay_running=IDLE)
    assert not out.ok and out.text == "Commit or stash these first: stray.txt"
    (root / "stray.txt").unlink()
    out = conflicts.merge(root, CFG, "1", {"f.txt": "ours"}, run=default_run,
                          relay_running=lambda r: True)
    assert not out.ok and out.text == "A relay is running here; release when it finishes"


def _state(root: Path) -> tuple[str, str, str]:
    refs = "".join(line + "\n" for line in git(root, "for-each-ref").splitlines()
                   if "refs/whyline/fix/" not in line)  # the snapshot is kept on purpose
    return git(root, "status", "--porcelain"), refs, git(root, "ls-files", "-s")


def test_mismatch_aborts_and_changes_nothing(tmp_path):
    root = setup(tmp_path, {"f.txt": "a\n", "g.txt": "a\n"},
                 {"f.txt": "ours\n", "g.txt": "ours\n"},
                 {"f.txt": "theirs\n", "g.txt": "theirs\n"})
    before = _state(root)

    def corrupting(args, **kw):
        if args[:2] == ["git", "add"]:
            (root / "g.txt").write_text("corrupt\n")
        return default_run(args, **kw)

    out = conflicts.merge(root, CFG, "1", {"f.txt": "ours", "g.txt": "theirs"},
                          run=corrupting, relay_running=IDLE)
    assert not out.ok
    assert "Nothing was changed" in out.text
    assert _state(root) == before
    assert not (root / ".git" / "MERGE_HEAD").exists()
    assert (root / "g.txt").read_text() == "ours\n"
