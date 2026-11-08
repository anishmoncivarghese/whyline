"""The built-in secret scanner: bundled rules over text, diffs, files and history.

A finding never carries the secret itself: the preview is masked and the
fingerprint hashes the value. Findings are de-duplicated by fingerprint and keep
the earliest commit, so one key committed twice is reported once.
"""

from __future__ import annotations

import fnmatch
import math
import os
import re
import subprocess
import threading
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from whyline.security.findings import Finding, make_fingerprint, mask
from whyline.security.rules import Allowlist, Rule, RuleSet

MAX_FILE_BYTES = 2 * 1024 * 1024
_BINARY_PROBE = 8192
_COMMIT_MARK = "@@commit "
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Each entry: (rule id, filename glob, "*" if .example/.sample copies are fine, content
# test or None). A content test must hit the file's text for the name to count.
_PYPIRC_PASSWORD = re.compile(r"^\s*password\s*[:=]\s*\S", re.IGNORECASE | re.MULTILINE)
_DENY: tuple[tuple[str, str, str, Callable[[str], bool] | None], ...] = (
    ("deny-env", ".env", "", None),
    ("deny-env", ".env.*", "*", None),
    ("deny-pem", "*.pem", "", None),
    ("deny-key", "*.key", "", None),
    ("deny-p12", "*.p12", "", None),
    ("deny-pfx", "*.pfx", "", None),
    ("deny-ssh-rsa", "id_rsa", "", None),
    ("deny-ssh-ed25519", "id_ed25519", "", None),
    ("deny-npmrc-token", ".npmrc", "", lambda text: "_authToken" in text),
    ("deny-pypirc-password", ".pypirc", "", lambda text: bool(_PYPIRC_PASSWORD.search(text))),
    ("deny-credentials-toml", "credentials.toml", "", None),
)
_EXAMPLE_SUFFIXES = (".example", ".sample")
_LOG_DIR = ".whyline/relay/logs/"

# What the scanner treats as a file that must not be committed, for display.
DENY_NAMES = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    ".npmrc (with _authToken)",
    ".pypirc (with a password)",
    "credentials.toml",
    _LOG_DIR,
)


class ScanError(RuntimeError):
    """A scan could not run. The message never includes file contents."""


def entropy(value: str) -> float:
    """Shannon entropy in bits per character."""
    if not value:
        return 0.0
    total = len(value)
    return -sum(n / total * math.log2(n / total) for n in Counter(value).values())


def _allowed(allow: Allowlist, path: str, secret: str, match: str, line: str) -> bool:
    checks: list[bool] = []
    if allow.paths:
        checks.append(any(p.search(path) for p in allow.paths))
    if allow.regexes:
        target = {"match": match, "line": line}.get(allow.regex_target, secret)
        checks.append(any(r.search(target) for r in allow.regexes))
    if allow.stopwords:
        lowered = secret.lower()
        checks.append(any(word in lowered for word in allow.stopwords))
    if not checks:
        return False
    return all(checks) if allow.condition == "AND" else any(checks)


def _line_at(text: str, start: int, end: int) -> str:
    begin = text.rfind("\n", 0, start) + 1
    stop = text.find("\n", end)
    return text[begin : len(text) if stop == -1 else stop]


def _secret_finding(rule: Rule, path: str, line: int, commit: str, secret: str) -> Finding:
    return Finding(
        kind="secret",
        rule=rule.id,
        title=rule.description or rule.id,
        severity="high",
        path=path,
        line=line,
        commit=commit,
        preview=mask(secret) if secret else "",
        fingerprint=make_fingerprint("secret", rule.id, path, secret),
        fix_hint="Remove the value, rotate the credential, and load it from the environment.",
    )


def scan_text(
    text: str, path: str, rules: RuleSet, *, commit: str = "", first_line: int = 1
) -> list[Finding]:
    """Findings for `text`, which is the content of `path`.

    `first_line` is the line number of the text's first line, for chunks of a diff.
    """
    if any(p.search(path) for p in rules.allowlist.paths):
        return []
    lowered = text.lower()
    found: list[Finding] = []
    for rule in rules.rules:
        if rule.keywords and not any(word in lowered for word in rule.keywords):
            continue
        if rule.path is not None and not rule.path.search(path):
            continue
        if rule.regex is None:
            # A rule that matches on the path alone.
            if not _rule_allows_path(rule, path):
                found.append(_secret_finding(rule, path, 0, commit, ""))
            continue
        for match in rule.regex.finditer(text):
            group = _secret_group(rule, match)
            secret = match.group(group)
            if not secret:
                continue
            if rule.entropy is not None and entropy(secret) < rule.entropy:
                continue
            start = match.start(group)
            line_text = _line_at(text, match.start(), match.end())
            whole = match.group(0)
            lists = (*rule.allowlists, rules.allowlist)
            if any(_allowed(a, path, secret, whole, line_text) for a in lists):
                continue
            line = first_line + text.count("\n", 0, start)
            found.append(_secret_finding(rule, path, line, commit, secret))
    return found


def _secret_group(rule: Rule, match: re.Match[str]) -> int:
    """The group that holds the secret, as gitleaks picks it: `secretGroup` when
    the rule sets one, else the first capture group that matched, else the whole
    match. Measuring entropy on the whole match (`key = "telegram_allow"`)
    instead of the value made ordinary names look like keys."""
    if rule.secret_group:
        try:
            match.group(rule.secret_group)
            return rule.secret_group
        except IndexError:
            return 0
    for index in range(1, (match.re.groups or 0) + 1):
        if match.group(index):
            return index
    return 0


def _rule_allows_path(rule: Rule, path: str) -> bool:
    return any(_allowed(a, path, "", "", "") for a in rule.allowlists if a.paths)


def check_deny(path: str, text: str = "", commit: str = "") -> list[Finding]:
    """`contents` findings for a path that should not be in the repository."""
    posix = path.replace("\\", "/")
    name = posix.rsplit("/", 1)[-1]
    found: list[Finding] = []
    if posix.startswith(_LOG_DIR) or f"/{_LOG_DIR}" in posix:
        found.append(_deny_finding("deny-relay-logs", posix, commit, "relay log"))
    for rule, glob, skip, test in _DENY:
        if not fnmatch.fnmatchcase(name, glob):
            continue
        if skip and name.endswith(_EXAMPLE_SUFFIXES):
            continue
        if test is not None and not test(text):
            continue
        found.append(_deny_finding(rule, posix, commit, glob))
        break
    return found


def _deny_finding(rule: str, path: str, commit: str, label: str) -> Finding:
    return Finding(
        kind="contents",
        rule=rule,
        title=f"{label} file should not be committed",
        severity="high",
        path=path,
        commit=commit,
        fingerprint=make_fingerprint("contents", rule, path),
        fix_hint="Remove it from git and add it to .gitignore.",
    )


def _dedupe(findings: Iterable[Finding]) -> list[Finding]:
    """One finding per fingerprint. Input is newest commit first (git log order),
    so a later duplicate is an earlier commit and replaces the one kept."""
    kept: dict[str, Finding] = {}
    for finding in findings:
        kept[finding.fingerprint or id(finding)] = finding
    return list(kept.values())


# --- diffs ------------------------------------------------------------------


class _Diff:
    """Collects the added lines of a `git log -p` / `git diff` stream per file."""

    def __init__(self, rules: RuleSet) -> None:
        self.rules = rules
        self.found: list[Finding] = []
        self.commit = ""
        self.commits = 0
        self._path: str | None = None
        self._in_hunk = False
        self._next = 0
        self._chunks: list[tuple[int, list[str]]] = []
        self._run: list[str] | None = None

    def feed(self, raw: str) -> None:
        line = raw.rstrip("\n").rstrip("\r")
        if line.startswith(_COMMIT_MARK):
            self._finish_file()
            self.commit = line[len(_COMMIT_MARK) :].strip()
            self.commits += 1
            return
        if line.startswith("diff --git "):
            self._finish_file()
            return
        if not self._in_hunk and line.startswith("+++ "):
            target = line[4:].split("\t")[0]
            self._path = target[2:] if target.startswith("b/") else None
            return
        hunk = _HUNK.match(line)
        if hunk:
            self._close_run()
            self._in_hunk = True
            self._next = int(hunk.group(1))
            return
        if not self._in_hunk:
            return
        if line.startswith("+"):
            if self._run is None:
                self._run = []
                self._chunks.append((self._next, self._run))
            self._run.append(line[1:])
            self._next += 1
        else:
            self._close_run()

    def _close_run(self) -> None:
        self._run = None

    def _finish_file(self) -> None:
        path, chunks = self._path, self._chunks
        self._path, self._chunks, self._run, self._in_hunk = None, [], None, False
        if path is None:
            return
        added = "\n".join("\n".join(lines) for _, lines in chunks)
        self.found.extend(check_deny(path, added, self.commit))
        for first, lines in chunks:
            self.found.extend(
                scan_text("\n".join(lines), path, self.rules, commit=self.commit, first_line=first)
            )

    def close(self) -> list[Finding]:
        self._finish_file()
        return _dedupe(self.found)


def _git_args(*args: str) -> list[str]:
    return ["git", "-c", "core.quotepath=off", *args]


def _git_text(root: Path, run: Callable, args: list[str]) -> str:
    try:
        done = run(
            _git_args(*args), cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScanError(f"git {args[0]} could not run ({type(exc).__name__})") from None
    if getattr(done, "returncode", 1) != 0:
        raise ScanError(f"git {args[0]} failed")
    return done.stdout or ""


def _scan_diff_text(output: str, rules: RuleSet) -> list[Finding]:
    diff = _Diff(rules)
    for line in output.splitlines():
        diff.feed(line)
    return diff.close()


def scan_range(root: Path, rev_range: str, *, run: Callable = subprocess.run,
               rules: RuleSet | None = None) -> list[Finding]:
    """Secrets on lines added by the commits in `rev_range` (e.g. `main..HEAD`)."""
    rules = rules or _default_rules()
    output = _git_text(
        root, run,
        ["log", "-p", "--no-color", "--unified=0", "--no-ext-diff", f"--format={_COMMIT_MARK}%H", rev_range],
    )
    return _scan_diff_text(output, rules)


def scan_staged(root: Path, *, run: Callable = subprocess.run,
                rules: RuleSet | None = None) -> list[Finding]:
    """Secrets on lines staged for the next commit."""
    rules = rules or _default_rules()
    output = _git_text(root, run, ["diff", "--cached", "-U0", "--no-color", "--no-ext-diff"])
    return _scan_diff_text(output, rules)


def _default_rules() -> RuleSet:
    from whyline.security.rules import load_rules

    return load_rules()


# --- whole files --------------------------------------------------------------


def _files(root: Path, paths: Iterable[Path | str]) -> Iterator[Path]:
    for item in paths:
        path = Path(item)
        path = path if path.is_absolute() else root / path
        if path.is_dir():
            for base, dirs, names in os.walk(path):
                dirs[:] = [d for d in dirs if d != ".git"]
                for name in names:
                    yield Path(base) / name
        elif path.is_file():
            yield path


def scan_paths(root: Path, paths: Iterable[Path | str], *, rules: RuleSet | None = None) -> list[Finding]:
    """Secrets in whole files. Binary files and files over 2 MB are skipped."""
    rules = rules or _default_rules()
    found: list[Finding] = []
    for file in _files(root, paths):
        try:
            rel = file.relative_to(root).as_posix()
        except ValueError:
            rel = file.as_posix()
        try:
            if file.stat().st_size > MAX_FILE_BYTES:
                continue
            with file.open("rb") as handle:
                data = handle.read(MAX_FILE_BYTES + 1)
        except OSError:
            continue
        if b"\0" in data[:_BINARY_PROBE]:
            continue
        text = data.decode("utf-8", errors="replace")
        found.extend(check_deny(rel, text))
        found.extend(scan_text(text, rel, rules))
    return _dedupe(found)


# --- history ------------------------------------------------------------------


def scan_history(
    root: Path,
    *,
    run: Callable = subprocess.run,
    popen: Callable = subprocess.Popen,
    on_progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    rules: RuleSet | None = None,
) -> list[Finding]:
    """Secrets on every line ever added in any commit, streamed from `git log -p --all`.

    `on_progress(done, total)` is called per commit. If `cancel_event` is set the
    scan stops and returns what it has found so far.
    """
    rules = rules or _default_rules()
    try:
        total = int(_git_text(root, run, ["rev-list", "--all", "--count"]).strip() or 0)
    except ValueError:
        total = 0
    command = _git_args(
        "log", "-p", "--all", "--no-color", "--unified=0", "--no-ext-diff", f"--format={_COMMIT_MARK}%H"
    )
    try:
        proc = popen(command, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                     text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScanError(f"git log could not run ({type(exc).__name__})") from None
    diff = _Diff(rules)
    done = 0
    try:
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                break
            starts = line.startswith(_COMMIT_MARK)
            diff.feed(line)
            if starts:
                done += 1
                if on_progress is not None:
                    on_progress(done, total)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        proc.wait()
    return diff.close()
