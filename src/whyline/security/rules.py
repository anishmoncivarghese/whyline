"""The bundled secret rules: gitleaks' default config, loaded for Python's `re`.

gitleaks is written in Go, whose regex dialect differs from Python's in two ways
that matter here: `\\z` for end of text, and inline flag groups such as `(?i)` in
the middle of a pattern (Python only accepts those at the very start). `translate`
rewrites both. Anything else Python lacks is left to fail, and a rule whose regex
still does not compile is skipped and listed in `RuleSet.skipped`.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

_FLAG_GROUP = re.compile(r"\(\?([A-Za-z]*(?:-[A-Za-z]*)?)\)")
_GROUP_PREFIX = re.compile(r"\(\?(?:P?<[A-Za-z_]\w*>|<=|<!|[:=!>]|[A-Za-z]*(?:-[A-Za-z]*)?:)")


def translate(go_regex: str) -> str:
    """Rewrite the Go regex constructs Python rejects; leave everything else as is.

    `\\z` becomes `\\Z`. A flag group like `(?i)` that is not at the very start
    becomes a scoped group `(?i:…)` running to the end of its enclosing group, and
    it is closed and reopened around any `|` at its own level so the alternation
    keeps its shape (Go applies the flags to every later branch).
    """
    out: list[str] = []
    # One frame per open group: the flag groups opened inside it, still unclosed.
    frames: list[list[str]] = [[]]
    i = 0
    n = len(go_regex)
    while i < n:
        c = go_regex[i]
        if c == "\\":
            if go_regex.startswith("\\Q", i):
                end = go_regex.find("\\E", i + 2)
                end = n if end == -1 else end + 2
                out.append(go_regex[i:end])
                i = end
                continue
            out.append("\\Z" if go_regex.startswith("\\z", i) else go_regex[i : i + 2])
            i += 2
            continue
        if c == "[":
            j = i + 1
            if j < n and go_regex[j] == "^":
                j += 1
            if j < n and go_regex[j] == "]":
                j += 1
            while j < n and go_regex[j] != "]":
                if go_regex[j] == "\\":
                    j += 1
                elif go_regex.startswith("[:", j):
                    close = go_regex.find(":]", j + 2)
                    if close != -1:
                        j = close + 1
                j += 1
            out.append(go_regex[i : j + 1])
            i = j + 1
            continue
        if c == "(":
            flag = _FLAG_GROUP.match(go_regex, i)
            if flag and flag.group(1):
                if i == 0:
                    out.append(flag.group(0))
                else:
                    out.append(f"(?{flag.group(1)}:")
                    frames[-1].append(flag.group(1))
                i = flag.end()
                continue
            frames.append([])
            prefix = _GROUP_PREFIX.match(go_regex, i)
            end = prefix.end() if prefix else i + 1
            out.append(go_regex[i:end])
            i = end
            continue
        if c == ")":
            if len(frames) > 1:
                out.append(")" * len(frames.pop()))
            out.append(c)
            i += 1
            continue
        if c == "|":
            out.append(")" * len(frames[-1]) + "|")
            out.extend(f"(?{flags}:" for flags in frames[-1])
            i += 1
            continue
        out.append(c)
        i += 1
    out.append(")" * len(frames[0]))
    return "".join(out)


def _compile(go_regex: str) -> re.Pattern[str] | None:
    try:
        return re.compile(translate(go_regex))
    except (re.error, RecursionError, OverflowError):
        return None


@dataclass(frozen=True)
class Allowlist:
    """What a rule (or the whole file) lets through.

    `condition` is "OR" (any of regexes/stopwords/paths clears the finding) or
    "AND" (all that are present must). `regex_target` is what `regexes` run
    against: the "secret" (default), the whole "match", or the whole "line".
    """

    description: str = ""
    condition: str = "OR"
    regex_target: str = "secret"
    regexes: tuple[re.Pattern[str], ...] = ()
    stopwords: tuple[str, ...] = ()
    paths: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    regex: re.Pattern[str] | None  # None for a rule that matches on `path` alone
    secret_group: int = 0
    entropy: float | None = None
    keywords: tuple[str, ...] = ()
    path: re.Pattern[str] | None = None
    allowlists: tuple[Allowlist, ...] = ()


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    allowlist: Allowlist
    # Ids of rules whose regex does not compile in Python even after `translate`.
    skipped: tuple[str, ...] = ()
    # Allowlist regexes dropped for the same reason, as "<rule id or *>: <regex>".
    # Dropping one only makes a scan stricter, so it never hides a finding.
    skipped_allow: tuple[str, ...] = ()


def _allowlist(raw: dict, owner: str, dropped: list[str]) -> Allowlist:
    def patterns(key: str) -> tuple[re.Pattern[str], ...]:
        found = []
        for source in raw.get(key, []):
            pattern = _compile(source)
            if pattern is None:
                dropped.append(f"{owner}: {source}")
            else:
                found.append(pattern)
        return tuple(found)

    return Allowlist(
        description=raw.get("description", ""),
        condition=str(raw.get("condition", "OR")).upper(),
        regex_target=raw.get("regexTarget", "secret"),
        regexes=patterns("regexes"),
        stopwords=tuple(word.lower() for word in raw.get("stopwords", [])),
        paths=patterns("paths"),
    )


def _parse(data: dict) -> RuleSet:
    dropped: list[str] = []
    skipped: list[str] = []
    rules: list[Rule] = []
    for raw in data.get("rules", []):
        rule_id = raw["id"]
        regex = _compile(raw["regex"]) if raw.get("regex") else None
        path = _compile(raw["path"]) if raw.get("path") else None
        # A rule needs a regex, a path, or both; one that has a pattern we cannot
        # compile is skipped rather than loosened.
        broken = (raw.get("regex") and regex is None) or (raw.get("path") and path is None)
        if broken or (regex is None and path is None):
            skipped.append(rule_id)
            continue
        lists = list(raw.get("allowlists", []))
        if "allowlist" in raw:
            lists.append(raw["allowlist"])
        rules.append(
            Rule(
                id=rule_id,
                description=raw.get("description", ""),
                regex=regex,
                secret_group=int(raw.get("secretGroup", 0)),
                entropy=float(raw["entropy"]) if "entropy" in raw else None,
                keywords=tuple(word.lower() for word in raw.get("keywords", [])),
                path=path,
                allowlists=tuple(_allowlist(item, rule_id, dropped) for item in lists),
            )
        )
    global_lists = list(data.get("allowlists", []))
    if "allowlist" in data:
        global_lists.append(data["allowlist"])
    merged = Allowlist()
    for item in global_lists:
        part = _allowlist(item, "*", dropped)
        merged = Allowlist(
            description=merged.description or part.description,
            regexes=merged.regexes + part.regexes,
            stopwords=merged.stopwords + part.stopwords,
            paths=merged.paths + part.paths,
        )
    return RuleSet(tuple(rules), merged, tuple(skipped), tuple(dropped))


@cache
def _bundled() -> RuleSet:
    text = resources.files("whyline.security").joinpath("rules/gitleaks.toml").read_text("utf-8")
    return _parse(tomllib.loads(text))


def load_rules(path: Path | None = None) -> RuleSet:
    """The bundled rules, or the gitleaks-format file at `path` (used by tests)."""
    if path is None:
        return _bundled()
    return _parse(tomllib.loads(path.read_text("utf-8")))
