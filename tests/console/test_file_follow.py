"""Tests for file following and change detection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from whyline.console.file_follow import (
    MAX_BYTES,
    SAMPLE_BYTES,
    FollowUpdate,
    Snap,
    classify,
    display_path,
    first_changed_line,
    is_ignored,
    parse_porcelain_z,
    poll,
    porcelain_argv,
)


def test_porcelain_argv_lists_untracked_files_individually(tmp_path: Path) -> None:
    assert porcelain_argv() == ["status", "--porcelain", "-z", "--untracked-files=all"]

    # Verify against real git behavior with untracked directory
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)

    untracked_dir = repo / "some_dir"
    untracked_dir.mkdir()
    (untracked_dir / "a.txt").write_text("file a\n", encoding="utf-8")
    (untracked_dir / "b.txt").write_text("file b\n", encoding="utf-8")

    proc = subprocess.run(
        ["git", *porcelain_argv()],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    paths = parse_porcelain_z(proc.stdout)
    assert sorted(paths) == ["some_dir/a.txt", "some_dir/b.txt"]


def test_parse_porcelain_z_rename_record_keeps_new_path() -> None:
    # Rename record: R <dst>\0<src>\0
    blob = b"R  new_name.py\x00old_name.py\x00"
    assert parse_porcelain_z(blob) == ["new_name.py"]

    # Copy record: C <dst>\0<src>\0
    copy_blob = b"C  copied.py\x00original.py\x00"
    assert parse_porcelain_z(copy_blob) == ["copied.py"]

    # Mixed records: rename followed by normal untracked
    mixed = b"RM renamed.py\x00source.py\x00?? untracked.py\x00"
    assert parse_porcelain_z(mixed) == ["renamed.py", "untracked.py"]

    # Modified record
    mod_blob = b"M  modified.py\x00"
    assert parse_porcelain_z(mod_blob) == ["modified.py"]

    # Non-UTF8 path with surrogateescape
    surrogate_blob = b"?? bad_\xff.txt\x00"
    assert parse_porcelain_z(surrogate_blob) == ["bad_\udcff.txt"]

    # Empty blob
    assert parse_porcelain_z(b"") == []


def test_whyline_and_git_are_ignored() -> None:
    assert is_ignored(".whyline") is True
    assert is_ignored(".whyline/") is True
    assert is_ignored(".whyline/ledger.jsonl") is True
    assert is_ignored(".whyline/sub/file.txt") is True
    assert is_ignored(".git") is True
    assert is_ignored(".git/") is True
    assert is_ignored(".git/HEAD") is True
    assert is_ignored(".git/objects/12/34") is True
    assert is_ignored("./.whyline") is True
    assert is_ignored("./.whyline/foo") is True
    assert is_ignored("./.git") is True

    # Not ignored
    assert is_ignored(".gitignore") is False
    assert is_ignored(".gitattributes") is False
    assert is_ignored(".github") is False
    assert is_ignored(".github/workflows/ci.yml") is False
    assert is_ignored("src/whyline/console/file_follow.py") is False
    assert is_ignored("src/.git") is False
    assert is_ignored("tests/test_whyline.py") is False
    assert is_ignored("") is False


def test_classify_binary_oversize_and_non_utf8() -> None:
    # Oversize
    large_bytes = b"a" * (MAX_BYTES + 1)
    assert classify(large_bytes) == f"too large to show ({MAX_BYTES + 1} bytes)"

    # Exactly MAX_BYTES is allowed
    assert classify(b"a" * MAX_BYTES) is None

    # Binary: NUL in first SAMPLE_BYTES
    nul_early = b"hello\x00world"
    assert classify(nul_early) == "binary, not shown"

    # NUL after SAMPLE_BYTES does not classify as binary (valid utf-8)
    nul_late = b"a" * SAMPLE_BYTES + b"\x00"
    assert classify(nul_late) is None

    # Not UTF-8
    invalid_utf8 = b"\xff\xfe\xfa"
    assert classify(invalid_utf8) == "not UTF-8, not shown"

    # Valid utf-8 text
    assert classify(b"hello world\n") is None


def test_first_changed_line() -> None:
    # Equal strings return 1
    assert first_changed_line("a\nb\nc", "a\nb\nc") == 1
    assert first_changed_line("", "") == 1

    # Differing lines
    assert first_changed_line("a\nb\nc", "a\nB\nc") == 2
    assert first_changed_line("old\nb", "new\nb") == 1

    # Prefix: before is prefix of after -> min(len) + 1
    assert first_changed_line("a\nb", "a\nb\nc") == 3

    # Prefix: after is prefix of before -> min(len) + 1
    assert first_changed_line("a\nb\nc", "a\nb") == 3

    # New file (before is empty) -> line 1
    assert first_changed_line("", "first line\nsecond line") == 1


def test_display_path_prefixes_another_repository_name() -> None:
    root = Path("/workspace/main-repo")
    repo = Path("/workspace/main-repo")
    assert display_path(root, repo, "src/foo.py") == "src/foo.py"

    other_repo = Path("/workspace/secondary-repo")
    assert display_path(root, other_repo, "src/bar.py") == "secondary-repo:src/bar.py"


def test_path_already_dirty_in_baseline_is_not_a_write_until_snap_changes() -> None:
    snap1 = Snap(mtime_ns=1000, size=50)
    baseline = {"file.py": snap1}
    found = {"file.py": (snap1, b"original content")}

    base, update = poll(baseline, found, hints=[], head={})
    assert update is None
    assert base == {"file.py": snap1}

    # When snap changes, it becomes a write
    snap2 = Snap(mtime_ns=2000, size=60)
    found_changed = {"file.py": (snap2, b"new content\nline 2")}

    base, update = poll(baseline, found_changed, hints=[], head={})
    assert update is not None
    assert update.path == "file.py"
    assert update.text == "new content\nline 2"
    assert update.notice is None
    assert base == {"file.py": snap2}


def test_unchanged_hint_is_not_a_write() -> None:
    # Hint in baseline and found, but snap unchanged
    snap = Snap(mtime_ns=1000, size=20)
    baseline = {"read_only.py": snap}
    found = {"read_only.py": (snap, b"read only text")}
    hints = ["read_only.py"]

    base, update = poll(baseline, found, hints=hints, head={})
    assert update is None
    assert base == {"read_only.py": snap}

    # Hint in hints but NOT in found
    base, update = poll(baseline, {}, hints=hints, head={})
    assert update is None
    assert base == baseline


def test_binary_oversize_and_non_utf8_produce_notices_and_no_text() -> None:
    snap = Snap(mtime_ns=1000, size=10)

    # Binary
    bin_found = {"bin.dat": (snap, b"abc\x00def")}
    base, update = poll({}, bin_found, hints=[], head={})
    assert update is not None
    assert update.path == "bin.dat"
    assert update.text is None
    assert update.notice == "binary, not shown"
    assert update.changed_line == 1

    # Oversize
    big_raw = b"x" * (MAX_BYTES + 5)
    big_snap = Snap(mtime_ns=2000, size=len(big_raw))
    big_found = {"big.log": (big_snap, big_raw)}
    base, update = poll({}, big_found, hints=[], head={})
    assert update is not None
    assert update.path == "big.log"
    assert update.text is None
    assert update.notice == f"too large to show ({len(big_raw)} bytes)"
    assert update.changed_line == 1

    # Non-UTF8
    bad_found = {"bad.txt": (snap, b"\xff\xfe")}
    base, update = poll({}, bad_found, hints=[], head={})
    assert update is not None
    assert update.path == "bad.txt"
    assert update.text is None
    assert update.notice == "not UTF-8, not shown"
    assert update.changed_line == 1


def test_newest_mtime_wins_and_all_candidates_update_baseline() -> None:
    s1 = Snap(mtime_ns=100, size=10)
    s2 = Snap(mtime_ns=300, size=10)
    s3 = Snap(mtime_ns=200, size=10)

    found = {
        "f1.py": (s1, b"file 1"),
        "f2.py": (s2, b"file 2"),
        "f3.py": (s3, b"file 3"),
    }

    base, update = poll({}, found, hints=[], head={})
    assert update is not None
    assert update.path == "f2.py"  # newest mtime 300 wins
    assert update.text == "file 2"

    # All candidate snaps are in baseline
    assert base == {
        "f1.py": s1,
        "f2.py": s2,
        "f3.py": s3,
    }


def test_first_changed_line_measured_against_head() -> None:
    snap = Snap(mtime_ns=500, size=30)

    # New file (absent from head) starts at line 1
    found_new = {"brand_new.py": (snap, b"line1\nline2\n")}
    base, update = poll({}, found_new, hints=[], head={})
    assert update is not None
    assert update.changed_line == 1

    # Existing file with diff at line 2
    head = {"existing.py": "line1\nold line 2\nline3\n"}
    found_existing = {"existing.py": (snap, b"line1\nNEW line 2\nline3\n")}
    base, update = poll({}, found_existing, hints=[], head=head)
    assert update is not None
    assert update.changed_line == 2
