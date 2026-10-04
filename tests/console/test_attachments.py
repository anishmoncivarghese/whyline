import os
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

from whyline.console import attachments as att

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / ".whyline").mkdir()
    (tmp_path / ".whyline" / ".gitignore").write_text("ledger.jsonl\n")
    return tmp_path


def _file(path: Path, data: bytes = b"hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_stage_copies_into_an_ignored_session_folder(repo, tmp_path_factory):
    src = _file(tmp_path_factory.mktemp("x") / "My Shot (1).png", PNG)
    a = att.stage(repo, src, session="20261004-101200", source="picker")
    assert a.name == "My-Shot--1-.png" and a.kind == "image" and a.size == len(PNG)
    assert a.path == repo / ".whyline/attachments/20261004-101200" / a.id / "My-Shot--1-.png"
    assert a.path.read_bytes() == PNG and len(a.id) == 8
    assert "attachments/" in (repo / ".whyline/.gitignore").read_text().splitlines()
    assert subprocess.run(["git", "check-ignore", "-q", str(a.path)], cwd=repo).returncode == 0


def test_stage_refuses_folders_and_oversized_files(repo, tmp_path_factory, monkeypatch):
    folder = tmp_path_factory.mktemp("folder")
    with pytest.raises(att.AttachmentError, match="Folders can't be attached yet"):
        att.stage(repo, folder, session="s", source="drop")
    monkeypatch.setattr(att, "MAX_FILE_BYTES", 4)
    big = _file(folder / "PRD.pdf", b"12345")
    with pytest.raises(att.AttachmentError, match="PRD.pdf is .* the limit is .* per file"):
        att.stage(repo, big, session="s", source="picker")


def test_pending_enforces_message_limits(repo, tmp_path_factory, monkeypatch):
    src = tmp_path_factory.mktemp("y")
    pending = att.PendingAttachments()
    monkeypatch.setattr(att, "MAX_FILES", 2)
    for n in range(2):
        pending.add(att.stage(repo, _file(src / f"{n}.txt"), session="s", source="picker", pending=pending))
    with pytest.raises(att.AttachmentError, match="at most 2 files"):
        att.stage(repo, _file(src / "3.txt"), session="s", source="picker", pending=pending)
    first = pending.items[0].id
    pending.remove(first)
    assert [a.id for a in pending.items] != [first] and len(pending.items) == 1

    # Check total message bytes limit
    monkeypatch.setattr(att, "MAX_FILES", 10)
    monkeypatch.setattr(att, "MAX_MESSAGE_BYTES", 15)
    f1 = _file(src / "f1.txt", b"1234567890")  # 10 bytes
    pending.clear()
    assert pending.items == []
    assert pending.total_bytes == 0
    assert pending.paths() == []
    a1 = att.stage(repo, f1, session="s", source="picker", pending=pending)
    pending.add(a1)
    assert pending.total_bytes == 10
    assert pending.paths() == [a1.path]
    f2 = _file(src / "f2.txt", b"123456")  # 6 bytes (10 + 6 = 16 > 15)
    with pytest.raises(att.AttachmentError, match="would go over .* for one message"):
        att.stage(repo, f2, session="s", source="picker", pending=pending)


def test_secret_looking_names_get_a_warning(repo, tmp_path_factory):
    src = _file(tmp_path_factory.mktemp("z") / ".env.local")
    assert att.stage(repo, src, session="s", source="drop").warning == "looks like a secret"


def test_session_name_and_safe_name():
    dt = datetime(2026, 10, 4, 15, 30, 45)
    assert att.session_name(dt) == "20261004-153045"
    assert len(att.session_name()) == 15

    assert att.safe_name("normal_name.txt") == "normal_name.txt"
    assert att.safe_name("weird name (1) [test] #3.png") == "weird-name--1---test---3.png"
    assert att.safe_name("noext") == "noext"
    assert att.safe_name(".png") == "file.png"
    assert att.safe_name("???") == "---"
    assert att.safe_name("") == "file"
    long_name = "a" * 100 + ".txt"
    safe_long = att.safe_name(long_name)
    assert len(safe_long) <= 80
    assert safe_long.endswith(".txt")
    long_ext = "a." + "x" * 100
    safe_long_ext = att.safe_name(long_ext)
    assert len(safe_long_ext) <= 80
    assert safe_long_ext.startswith("a.")
    assert safe_long_ext.endswith("x")


def test_dropped_paths(tmp_path):
    a = _file(tmp_path / "My Shot.png")
    b = _file(tmp_path / "PRD.pdf")
    # each OS's terminal drops paths its own way
    escaped = f'"{a}"' if os.name == "nt" else str(a).replace(" ", "\\ ")
    assert att.dropped_paths(f"{escaped} {b}") == [a, b]
    assert att.dropped_paths(f"'{a}'") == [a]
    assert att.dropped_paths(a.as_uri()) == [a]
    assert att.dropped_paths(f"look at {b} please") is None
    assert att.dropped_paths(str(tmp_path / "missing.png")) is None
    assert att.dropped_paths(str(tmp_path)) is None  # a folder
    assert att.dropped_paths("") is None
    assert att.dropped_paths("it's") is None  # unbalanced quote


def test_clean_old_removes_only_old_session_folders(repo):
    base = repo / ".whyline" / "attachments"
    old = _file(base / "20260901-000000" / "aaaaaaaa" / "x.txt").parent.parent
    new = _file(base / "20261004-000000" / "bbbbbbbb" / "y.txt").parent.parent
    other = _file(base / "keep-me" / "z.txt").parent
    outside = _file(repo / "precious.txt")
    link = base / "20260902-000000"
    link.symlink_to(repo)
    eight_days = time.time() - 8 * 86400
    for path in (old, other):
        os.utime(path, (eight_days, eight_days))
    removed = att.clean_old(repo)
    assert removed == [old] and not old.exists()
    assert new.exists() and other.exists() and outside.exists() and link.is_symlink()


def test_stage_symlinks_and_missing_files(repo, tmp_path_factory):
    src_dir = tmp_path_factory.mktemp("symlinks")
    target = _file(src_dir / "target.txt", b"content")
    link = src_dir / "link.txt"
    link.symlink_to(target)

    # Valid symlink stages successfully
    a = att.stage(repo, link, session="s", source="picker")
    assert a.name == "link.txt"
    assert a.path.read_bytes() == b"content"

    # Broken symlink raises AttachmentError
    broken = src_dir / "broken.txt"
    broken.symlink_to(src_dir / "nonexistent.txt")
    with pytest.raises(att.AttachmentError, match="Can't read broken.txt"):
        att.stage(repo, broken, session="s", source="picker")

    # Symlink to directory raises AttachmentError
    dir_target = tmp_path_factory.mktemp("target_dir")
    dir_link = src_dir / "dir_link"
    dir_link.symlink_to(dir_target)
    with pytest.raises(att.AttachmentError, match="Folders can't be attached yet"):
        att.stage(repo, dir_link, session="s", source="picker")


def test_secrets_pattern_matching(repo, tmp_path_factory):
    d = tmp_path_factory.mktemp("secrets")
    secret_names = [".env", ".env.prod", "server.pem", "id_rsa", "id_rsa.pub", "id_ed25519", "api.key", "my_credentials.json"]
    for name in secret_names:
        f = _file(d / name)
        assert att.stage(repo, f, session="s", source="drop").warning == "looks like a secret"

    safe_f = _file(d / "normal.json")
    assert att.stage(repo, safe_f, session="s", source="drop").warning == ""


def test_ensure_ignored_fails_when_git_check_ignore_fails(repo, monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(att.AttachmentError, match="isn't ignored by git"):
        att.ensure_ignored(repo)


def test_clean_old_when_dir_missing_or_symlink(tmp_path):
    assert att.clean_old(tmp_path) == []

    att_dir = tmp_path / ".whyline" / "attachments"
    att_dir.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "somewhere"
    target.mkdir()
    att_dir.symlink_to(target)
    assert att.clean_old(tmp_path) == []



def test_ensure_ignored_commits_its_own_gitignore_change(repo):
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    (repo / "mine.txt").write_text("the user's, uncommitted\n")
    att.ensure_ignored(repo)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert ".whyline/.gitignore" not in status  # committed, so a relay start isn't blocked
    assert "mine.txt" in status  # the user's own files are never committed
    last = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout
    assert last.strip() == "chore: ignore whyline attachments"
    att.ensure_ignored(repo)  # a second call changes nothing and commits nothing
    again = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout
    assert again == last
