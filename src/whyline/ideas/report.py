"""The quick-score contract: parse an idea-report and render it for a reader.

No model calls. IDEA-3 pastes ``RUBRIC`` into the prompt; bump
``RUBRIC_VERSION`` when that wording changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# One complexity scale covers both scores. The MVP and the full product differ
# by scope, not by what a point means. Higher complexity is harder, not better.
RUBRIC_VERSION = 1

RUBRIC = """\
Usefulness: how worth building this is for the people named. 1 is the lowest and 9 is the highest.
1. No real problem, or nothing left to add to what already exists.
2. A mild inconvenience with an easy workaround.
3. A narrow annoyance. Few people would switch.
4. A real but small problem. Worth it only if the build is cheap.
5. A solid problem for a known group. The value is plausible.
6. A clear pain for people you can reach. They would try a good version.
7. A strong, repeated pain. A focused version would change their work.
8. An urgent pain with a credible way to reach those users.
9. A compelling problem, reachable users, and a sharp reason to build it now.

Complexity: how hard the build is. 1 is the lowest and 9 is the highest. Higher is harder, not better. Score the MVP and the full product on this same scale.
1. A script or a config change that could ship in a day.
2. A small feature in a codebase you already know.
3. A few known pieces, with little new risk.
4. One unfamiliar integration, or a modest new surface.
5. Several parts that must work together, and some unknowns.
6. A real product slice: persistence, an interface, and one external system.
7. Multiple systems, an operational burden, or hard edge cases.
8. New ground: security, compliance, or reliability you have not shipped.
9. A long program with several unsolved problems.
"""

VERDICTS = ("YES", "NO", "NOT YET")
CONFIDENCE_LEVELS = ("low", "medium", "high")
_NO_SOURCES = "no sources were checked"
_TAG = "idea-report"
_TITLE_MAX = 80


class ReportError(ValueError):
    """The idea-report block is missing or a field is invalid.

    ``field`` is the first bad field in contract order, or ``idea-report``
    when the fenced block itself is missing or not a JSON object.
    """

    def __init__(self, field: str, detail: str) -> None:
        self.field = field
        super().__init__(f"{field}: {detail}")


@dataclass(frozen=True)
class Existing:
    name: str
    url: str
    how_it_differs: str


@dataclass(frozen=True)
class Source:
    url: str
    title: str


@dataclass(frozen=True)
class Report:
    title: str
    problem: str
    users: str
    usefulness: int
    complexity_mvp: int
    complexity_full: int
    verdict: str
    confidence: str
    existing: tuple[Existing, ...]
    sources: tuple[Source, ...]
    deploy: str
    risks: tuple[str, ...]
    next_step: str


def parse(text: str) -> Report:
    """Return the last closed ``idea-report`` block, validated."""
    payload = _load_last_block(text)
    if not isinstance(payload, dict):
        raise ReportError(_TAG, "must be a JSON object")

    title = _string(payload, "title", max_len=_TITLE_MAX)
    problem = _string(payload, "problem")
    users = _string(payload, "users")
    usefulness = _score(payload, "usefulness")
    complexity_mvp = _score(payload, "complexity_mvp")
    complexity_full = _score(payload, "complexity_full")
    verdict = _choice(payload, "verdict", VERDICTS)
    confidence = _choice(payload, "confidence", CONFIDENCE_LEVELS)
    existing = _existing(payload)
    sources = _sources(payload)
    # Both lists are present and well typed. An empty existing list is legal
    # only once sources shows the agent actually looked.
    if not existing and not sources:
        raise ReportError("existing", "may be empty only when sources is not")

    deploy = _string(payload, "deploy")
    risks = _string_list(payload, "risks")
    next_step = _string(payload, "next_step")
    if not sources:
        confidence = "low"
        if _NO_SOURCES not in risks:
            risks = (*risks, _NO_SOURCES)

    return Report(
        title=title,
        problem=problem,
        users=users,
        usefulness=usefulness,
        complexity_mvp=complexity_mvp,
        complexity_full=complexity_full,
        verdict=verdict,
        confidence=confidence,
        existing=existing,
        sources=sources,
        deploy=deploy,
        risks=risks,
        next_step=next_step,
    )


def render_markdown(report: Report, original_text: str) -> str:
    """The report a person reads. The original idea is quoted first."""
    lines = [
        _blockquote(original_text),
        "",
        f"# {report.title}",
        "",
        f"**Verdict:** {report.verdict}",
        f"**Confidence:** {report.confidence}",
        "",
        f"- Usefulness: {report.usefulness}/9",
        f"- MVP complexity: {report.complexity_mvp}/9",
        f"- Full complexity: {report.complexity_full}/9",
        "",
        "## Problem",
        "",
        report.problem,
        "",
        "## Users",
        "",
        report.users,
        "",
        "## What already exists",
        "",
        _existing_lines(report.existing),
        "",
        "## Deploy",
        "",
        report.deploy,
        "",
        "## Risks",
        "",
        _bullets(report.risks),
        "",
        "## Next step",
        "",
        report.next_step,
        "",
        "## Sources checked",
        "",
        _source_lines(report.sources),
    ]
    return "\n".join(lines) + "\n"


def _load_last_block(text: str):
    if not isinstance(text, str):
        raise ReportError(_TAG, "expected text")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    index = 0
    total = len(lines)
    while index < total:
        if _fence_token(lines[index]) != _TAG:
            index += 1
            continue
        index += 1
        body: list[str] = []
        while index < total and not _is_closing_fence(lines[index]):
            body.append(lines[index])
            index += 1
        if index >= total:
            # An unclosed fence is not a block. An earlier closed one still counts.
            break
        blocks.append("\n".join(body))
        index += 1
    if not blocks:
        raise ReportError(_TAG, "no fenced idea-report block")
    try:
        return json.loads(blocks[-1])
    except json.JSONDecodeError as exc:
        raise ReportError(_TAG, "not valid JSON") from exc


def _fence_token(line: str) -> str | None:
    # Agents indent fences inside lists, so leading whitespace is ignored.
    stripped = line.lstrip(" \t")
    if not stripped.startswith("```"):
        return None
    info = stripped[3:].strip()
    if not info:
        return None
    return info.split()[0]


def _is_closing_fence(line: str) -> bool:
    return line.strip() == "```"


def _require(payload: dict, field: str):
    if field not in payload or payload[field] is None:
        raise ReportError(field, "missing")
    return payload[field]


def _string(payload: dict, field: str, *, max_len: int | None = None) -> str:
    value = _require(payload, field)
    if not isinstance(value, str):
        raise ReportError(field, "must be a string")
    text = value.strip()
    if not text:
        raise ReportError(field, "must not be empty")
    if max_len is not None and len(text) > max_len:
        raise ReportError(field, f"must be at most {max_len} characters")
    return text


def _score(payload: dict, field: str) -> int:
    value = _require(payload, field)
    # bool is a subclass of int, and JSON true would otherwise score as 1.
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 9:
        raise ReportError(field, "must be an integer from 1 to 9")
    return value


def _choice(payload: dict, field: str, allowed: tuple[str, ...]) -> str:
    value = _require(payload, field)
    if isinstance(value, str):
        value = value.strip()
    if not isinstance(value, str) or value not in allowed:
        raise ReportError(field, "must be one of " + ", ".join(allowed))
    return value


def _existing(payload: dict) -> tuple[Existing, ...]:
    rows = _object_list(payload, "existing", ("name", "url", "how_it_differs"))
    return tuple(
        Existing(
            name=row["name"],
            url=row["url"],
            how_it_differs=row["how_it_differs"],
        )
        for row in rows
    )


def _sources(payload: dict) -> tuple[Source, ...]:
    rows = _object_list(payload, "sources", ("url", "title"))
    return tuple(Source(url=row["url"], title=row["title"]) for row in rows)


def _object_list(
    payload: dict, field: str, keys: tuple[str, ...]
) -> list[dict[str, str]]:
    value = _require(payload, field)
    if not isinstance(value, list):
        raise ReportError(field, "must be a list")
    rows: list[dict[str, str]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ReportError(field, f"item {index} must be an object")
        row: dict[str, str] = {}
        for key in keys:
            if key not in item or item[key] is None:
                raise ReportError(field, f"item {index} missing {key}")
            cell = item[key]
            if not isinstance(cell, str) or not cell.strip():
                raise ReportError(
                    field, f"item {index} {key} must be a non-empty string"
                )
            row[key] = cell.strip()
        rows.append(row)
    return rows


def _string_list(payload: dict, field: str) -> tuple[str, ...]:
    value = _require(payload, field)
    if not isinstance(value, list):
        raise ReportError(field, "must be a list")
    rows: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ReportError(field, f"item {index} must be a non-empty string")
        rows.append(item.strip())
    return tuple(rows)


def _blockquote(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return ">"
    return "\n".join(">" if line == "" else f"> {line}" for line in lines)


def _existing_lines(items: tuple[Existing, ...]) -> str:
    if not items:
        return "- None found in the sources checked."
    return "\n".join(
        f"- **{item.name}** ({item.url}): {item.how_it_differs}" for item in items
    )


def _source_lines(items: tuple[Source, ...]) -> str:
    if not items:
        return "- None."
    return "\n".join(f"- [{item.title}]({item.url})" for item in items)


def _bullets(items: tuple[str, ...]) -> str:
    if not items:
        return "- None."
    return "\n".join(f"- {item}" for item in items)
