"""Trace requirements through the plan and test plan: which are built and tested."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from whyline.sdlc import docset as docset_mod
from whyline.sdlc.docset import DocSet, Status

_HEADING = re.compile(r"^#{1,6}\s+(?P<title>.*?)\s*#*\s*$")
_REQUIREMENT = re.compile(r"^\s*(?:[-*]\s+)?\W{0,4}(R\d+)\b(?P<rest>.*)$")
_R_NUMBER = re.compile(r"\bR\d+\b")
_TITLE_TAG = re.compile(r"\[(R\d+(?:\s*,\s*R\d+)*)\]")
_REMOVED = re.compile(r"removed in v", re.IGNORECASE)


@dataclass
class Coverage:
    total: int = 0
    unbuilt: list[str] = field(default_factory=list)
    untested: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    uncovered_tasks: list[str] = field(default_factory=list)

    def line(self) -> str:
        gaps = set(self.unbuilt) | set(self.untested)
        parts = [f"Covers {self.total - len(gaps)} of {self.total} requirements"]
        parts += [f"{number} has no task" for number in self.unbuilt]
        parts += [f"{number} has no test" for number in self.untested]
        parts += [f"{task} covers {number}, not in scope" for task, number in self._pairs()]
        parts += [f"{task} has no covers line" for task in self.uncovered_tasks]
        return " · ".join(parts)

    def _pairs(self) -> list[tuple[str, str]]:
        pairs = []
        for item in self.out_of_scope:
            task, _, number = item.partition(":")
            pairs.append((task, number))
        return pairs


def requirements(text: str) -> list[str]:
    """R-numbers listed under a Requirements or Requirements covered heading."""
    found: list[str] = []
    inside = False
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            title = heading.group("title").strip().lower()
            inside = title in ("requirements", "requirements covered")
            continue
        if not inside:
            continue
        match = _REQUIREMENT.match(line)
        if match and not _REMOVED.search(match.group("rest")):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found


def _numbers(value: str) -> list[str]:
    value = value.strip()
    if value.lower().startswith("none"):
        return []
    return list(dict.fromkeys(_R_NUMBER.findall(value)))


def plan_covers(plan_text: str) -> dict[str, list[str]]:
    """Each task's covers line, by task id; a task with no covers line is absent."""
    from whyline_relay import plan

    result: dict[str, list[str]] = {}
    for task in plan.parse(plan_text):
        for line in task.text.splitlines()[1:]:
            stripped = line.strip()
            if stripped.startswith("covers:"):
                result[task.task_id] = _numbers(stripped.removeprefix("covers:"))
                break
    return result


def test_covers(tests_text: str) -> dict[str, list[str]]:
    """R-numbers in each test case's title, `[R3]` or `[R3, R4]`, by case id."""
    from whyline_relay import testplan

    result: dict[str, list[str]] = {}
    for scenario in testplan.parse(tests_text):
        numbers: list[str] = []
        for tag in _TITLE_TAG.findall(scenario.title):
            numbers += _R_NUMBER.findall(tag)
        result[scenario.id] = list(dict.fromkeys(numbers))
    return result


def _approved_text(docs: Path, docset: DocSet, kind: str) -> str | None:
    doc = docset.document(kind)
    if doc is None or doc["status"] != Status.APPROVED.value:
        return None
    return docset_mod._current_text(docs, docset, doc)


def scope(docs: Path, docset: DocSet) -> list[str]:
    """The requirements in scope: the approved spec's or design's, else the PRD's."""
    for kind in ("spec", "design"):
        text = _approved_text(docs, docset, kind)
        if text is not None:
            return requirements(text)
    prd = docset.document("prd")
    if prd is not None:
        return requirements(docset_mod._current_text(docs, docset, prd))
    return []


def _tests_text(docs: Path, docset: DocSet) -> str:
    doc = docset.document("plan")
    if doc is None:
        return ""
    target = docset_mod.plan_file(docs, docset.slug, tests=True)
    if target is not None:
        return target.read_text(encoding="utf-8")
    history = docset_mod._history_path(docs, docset.slug, "plan", int(doc["version"]))
    history = history.with_name(f"plan-v{doc['version']}.tests.md")
    return history.read_text(encoding="utf-8") if history.is_file() else ""


def coverage(docs: Path, docset: DocSet) -> Coverage:
    docs = Path(docs)
    wanted = scope(docs, docset)
    plan_doc = docset.document("plan")
    plan_text = docset_mod._current_text(docs, docset, plan_doc) if plan_doc else ""
    from whyline_relay import plan

    task_ids = [task.task_id for task in plan.parse(plan_text)] if plan_text else []
    by_task = plan_covers(plan_text) if plan_text else {}
    by_test = test_covers(_tests_text(docs, docset))
    built = {number for numbers in by_task.values() for number in numbers}
    tested = {number for numbers in by_test.values() for number in numbers}
    result = Coverage(total=len(wanted))
    result.unbuilt = [number for number in wanted if number not in built]
    result.untested = [number for number in wanted if number not in tested]
    result.out_of_scope = [
        f"{task}:{number}"
        for task, numbers in by_task.items()
        for number in numbers
        if number not in wanted
    ]
    result.uncovered_tasks = [task for task in task_ids if task not in by_task]
    return result
