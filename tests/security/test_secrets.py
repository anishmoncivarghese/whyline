"""The built-in secret scanner, against temp git repos.

Secrets are assembled from pieces so this file never holds a literal that a
secret scanner (GitHub push protection, or whyline's own) would flag.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import threading
from pathlib import Path

import pytest

from whyline.security.rules import Allowlist, Rule, RuleSet, load_rules
from whyline.security.secrets import (
    DENY_NAMES,
    ScanError,
    check_deny,
    entropy,
    scan_history,
    scan_paths,
    scan_range,
    scan_staged,
    scan_text,
)

KEY = "AKIA" + "QYLPMN5HHQKB3XZT"
LOW = "AKIA" + "AAAAAAAAAAAAAAAA"
SECRETS = (KEY, LOW)


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "readme.txt").write_text("hello\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def commit_file(repo: Path, name: str, text: str) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


def aws(findings):
    return [f for f in findings if f.rule == "aws-access-token"]


def assert_no_secret(*things) -> None:
    blob = "\n".join(repr(t) for t in things)
    for secret in SECRETS:
        assert secret not in blob


def test_range_finds_added_key_with_commit_and_line(repo):
    base = git(repo, "rev-parse", "HEAD")
    sha = commit_file(repo, "app/config.py", f"a = 1\nb = 2\nkey = '{KEY}'\n")
    found = aws(scan_range(repo, f"{base}..HEAD", run=subprocess.run))
    assert len(found) == 1
    assert (found[0].path, found[0].line, found[0].commit) == ("app/config.py", 3, sha)
    assert found[0].kind == "secret"
    assert found[0].preview and KEY not in found[0].preview
    assert_no_secret(found)


def test_removed_key_found_by_history_not_by_range(repo):
    sha = commit_file(repo, "leak.py", f"key = '{KEY}'\n")
    git(repo, "rm", "-q", "leak.py")
    git(repo, "commit", "-q", "-m", "remove")
    after_removal = git(repo, "rev-parse", "HEAD")
    assert aws(scan_range(repo, f"{after_removal}~1..{after_removal}")) == []
    progress = []
    found = aws(scan_history(repo, on_progress=lambda done, total: progress.append((done, total))))
    assert [(f.path, f.commit) for f in found] == [("leak.py", sha)]
    assert progress[-1] == (3, 3)


def test_history_dedupes_keeping_earliest_commit(repo):
    first = commit_file(repo, "a.py", f"k = '{KEY}'\n")
    commit_file(repo, "a.py", f"# top\nk = '{KEY}'\n")
    found = aws(scan_history(repo))
    assert [(f.path, f.commit) for f in found] == [("a.py", first)]


def test_history_can_be_cancelled(repo):
    commit_file(repo, "a.py", f"k = '{KEY}'\n")
    stop = threading.Event()
    stop.set()
    assert scan_history(repo, cancel_event=stop) == []


def test_staged_scope(repo):
    (repo / "new.py").write_text(f"x = 1\nk = '{KEY}'\n")
    git(repo, "add", "new.py")
    (repo / "unstaged.py").write_text(f"k = '{KEY}'\n")
    found = aws(scan_staged(repo))
    assert [(f.path, f.line, f.commit) for f in found] == [("new.py", 2, "")]
    assert_no_secret(found)


def test_keyword_miss_skips_the_regex(rules):
    class Spy:
        calls = 0

        def finditer(self, text):
            Spy.calls += 1
            return iter(())

    spy = Spy()
    rule = Rule(id="spy", description="spy", regex=spy, keywords=("zzkeyword",))
    only = RuleSet((rule,), Allowlist())
    assert scan_text("nothing here", "a.txt", only) == []
    assert Spy.calls == 0
    scan_text("has ZZKeyword inside", "a.txt", only)
    assert Spy.calls == 1


def test_low_entropy_is_ignored(rules):
    assert entropy(LOW[4:]) < 3 <= entropy(KEY[4:])
    assert aws(scan_text(f"k = '{LOW}'\n", "a.py", rules)) == []
    assert len(aws(scan_text(f"k = '{KEY}'\n", "a.py", rules))) == 1


def generic(findings):
    return [f for f in findings if f.rule == "generic-api-key"]


@pytest.mark.parametrize("line", [
    'ALLOW_KEY = "telegram_allow"\n',
    'if key == "salary_min":\n',
    "states = {key: UNAVAILABLE for key in PROTECTIONS}\n",
    "Whyline checks a release for leaked secrets, vulnerable dependencies and\n",
])
def test_generic_rule_judges_the_captured_value_not_the_whole_match(rules, line):
    """With no secretGroup, gitleaks uses the first non-empty capture group as
    the secret, so its entropy cut-off sees `telegram_allow`, not the whole
    `ALLOW_KEY = "telegram_allow"`."""
    assert generic(scan_text(line, "src/a.py", rules)) == []


def test_generic_rule_still_finds_a_random_looking_value(rules):
    token = "q8Zr" + "Tn3vX7pLw2Kc9Hs4Yb6Md1Fj"
    found = generic(scan_text(f'api_key = "{token}"\n', "src/a.py", rules))
    assert len(found) == 1
    assert token not in repr(found)


def test_rule_with_no_capture_group_still_uses_the_whole_match():
    rule = Rule(id="whole", description="whole", regex=re.compile(r"ZZ[0-9]{6}"))
    only = RuleSet((rule,), Allowlist())
    assert len(scan_text("x ZZ123456 y\n", "a.txt", only)) == 1


def test_allowlisted_paths_are_skipped(rules):
    allowing = dataclasses.replace(rules, allowlist=Allowlist(paths=(re.compile(r"(^|/)vendor/"),)))
    text = f"k = '{KEY}'\n"
    assert scan_text(text, "vendor/lib.py", allowing) == []
    assert aws(scan_text(text, "src/lib.py", allowing))


def test_rule_allowlist_stopword_clears_a_finding(rules):
    base = next(r for r in rules.rules if r.id == "aws-access-token")
    quiet = dataclasses.replace(base, allowlists=(Allowlist(stopwords=(KEY[-6:].lower(),)),))
    only = RuleSet((quiet,), Allowlist())
    assert scan_text(f"k = '{KEY}'\n", "a.py", only) == []


def test_scan_paths_skips_binary_and_large_files(repo):
    (repo / "bin.dat").write_bytes(b"\0" + f"k = '{KEY}'".encode())
    (repo / "big.txt").write_text(f"k = '{KEY}'\n" + "x" * (2 * 1024 * 1024))
    (repo / "ok.txt").write_text(f"k = '{KEY}'\n")
    found = aws(scan_paths(repo, [repo]))
    assert [f.path for f in found] == ["ok.txt"]
    assert_no_secret(found)


@pytest.mark.parametrize(
    "path, text, flagged",
    [
        (".env", "", True),
        (".env.local", "", True),
        (".env.example", "", False),
        (".env.sample", "", False),
        ("cfg/server.pem", "", True),
        ("server.key", "", True),
        ("store.p12", "", True),
        ("store.pfx", "", True),
        ("home/.ssh/id_rsa", "", True),
        ("id_ed25519", "", True),
        (".npmrc", "//r.example/:_authToken=abc\n", True),
        (".npmrc", "registry=https://r.example/\n", False),
        (".pypirc", "[pypi]\npassword = hunter2\n", True),
        (".pypirc", "[pypi]\nusername = me\n", False),
        ("credentials.toml", "", True),
        (".whyline/relay/logs/turn-1.log", "", True),
        ("src/main.py", "", False),
    ],
)
def test_deny_names(path, text, flagged):
    found = check_deny(path, text)
    assert bool(found) is flagged
    assert all(f.kind == "contents" and f.preview == "" for f in found)


def test_deny_names_listed_and_found_in_a_repo_scan(repo):
    assert ".env" in DENY_NAMES and ".whyline/relay/logs/" in DENY_NAMES
    (repo / ".env").write_text("A=1\n")
    (repo / ".env.example").write_text("A=\n")
    found = scan_paths(repo, [repo])
    assert [f.path for f in found if f.kind == "contents"] == [".env"]
    git(repo, "add", ".env")
    assert [f.path for f in scan_staged(repo) if f.kind == "contents"] == [".env"]


def test_no_output_or_error_contains_the_full_secret(repo, rules):
    base = git(repo, "rev-parse", "HEAD")
    commit_file(repo, ".env", f"TOKEN={KEY}\n")
    everything = [
        scan_text(f"k = '{KEY}'", "a.py", rules),
        scan_range(repo, f"{base}..HEAD"),
        scan_history(repo),
        scan_paths(repo, [repo]),
    ]
    assert any(everything)
    for findings in everything:
        for f in findings:
            assert KEY not in "".join(str(v) for v in dataclasses.asdict(f).values())
    assert_no_secret(everything)
    with pytest.raises(ScanError) as err:
        scan_range(repo, f"no-such-rev-{KEY}..HEAD")
    assert KEY not in str(err.value) and KEY not in repr(err.value)
