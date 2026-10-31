"""Workflow templates: ``{{ path | filter }}`` and nothing else (spec 4.3).

The grammar is parsed by hand, never evaluated: dotted paths of identifiers
and integer list indexes, then filters with at most one double-quoted string
argument. Scanning is iterative, so a very large template cannot hit the
recursion limit.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["TemplateError", "references", "render", "value"]


class TemplateError(ValueError):
    """A template is malformed, or a path it uses is not available."""


_MISSING = object()
_NO_ARG = object()
_IDENT_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_IDENT_CHARS = _IDENT_START | frozenset("0123456789_")
_DIGITS = frozenset("0123456789")
# filter name -> whether it takes its one string argument
_FILTERS = {
    "json": False,
    "lower": False,
    "upper": False,
    "trim": False,
    "length": False,
    "first": False,
    "join": True,
    "default": True,
}


@dataclass(frozen=True)
class _Expr:
    pos: int
    path: tuple[str, ...]
    filters: tuple[tuple[str, object], ...]

    @property
    def dotted(self) -> str:
        return ".".join(self.path)


def _fail(message: str, pos: int) -> TemplateError:
    return TemplateError(f"{message} at position {pos}")


def _parse_path(text: str, base: int) -> tuple[str, ...]:
    parts: list[str] = []
    for segment in text.split("."):
        if segment and segment[0] in _DIGITS:
            if not set(segment) <= _DIGITS:
                raise _fail(f"invalid list index {segment!r}", base)
        elif not segment or segment[0] not in _IDENT_START or not set(segment) <= _IDENT_CHARS:
            raise _fail(f"invalid path {text.strip()!r}", base)
        elif segment.startswith("_") or segment.endswith("__"):
            raise _fail(f"invalid path {text.strip()!r}", base)
        parts.append(segment)
    return tuple(parts)


def _split_pipes(body: str) -> list[tuple[int, str]]:
    """Split on ``|`` outside double quotes, keeping each piece's offset."""
    pieces: list[tuple[int, str]] = []
    start = 0
    quoted = False
    escaped = False
    for i, ch in enumerate(body):
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "|":
            pieces.append((start, body[start:i]))
            start = i + 1
    if quoted:
        raise _fail("unterminated string", len(body))
    pieces.append((start, body[start:]))
    return pieces


def _parse_filter(text: str, pos: int) -> tuple[str, object]:
    text = text.strip()
    name, paren, rest = text.partition("(")
    name = name.strip()
    if name not in _FILTERS:
        raise _fail(f"unknown filter {name!r}", pos)
    if not paren:
        if _FILTERS[name]:
            raise _fail(f"filter {name} needs one string argument", pos)
        return name, _NO_ARG
    if not _FILTERS[name]:
        raise _fail(f"filter {name} takes no argument", pos)
    rest = rest.strip()
    if not rest.endswith(")"):
        raise _fail(f"filter {name} is missing its closing parenthesis", pos)
    arg = rest[:-1].strip()
    if len(arg) < 2 or arg[0] != '"' or arg[-1] != '"':
        raise _fail(f"filter {name} needs one string argument in double quotes", pos)
    out: list[str] = []
    inner = arg[1:-1]
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\":
            if i + 1 >= len(inner) or inner[i + 1] not in '"\\':
                raise _fail("only \\\" and \\\\ may be escaped", pos)
            out.append(inner[i + 1])
            i += 2
            continue
        if ch == '"':
            raise _fail("unescaped quote in string", pos)
        out.append(ch)
        i += 1
    return name, "".join(out)


def _parse_expr(body: str, pos: int) -> _Expr:
    pieces = _split_pipes(body)
    head_off, head = pieces[0]
    lead = len(head) - len(head.lstrip())
    path = _parse_path(head.strip(), pos + head_off + lead)
    filters = tuple(_parse_filter(text, pos + off) for off, text in pieces[1:])
    return _Expr(pos, path, filters)


def _parse(template: str) -> list[str | _Expr]:
    if "{%" in template:
        raise _fail("{% %} is not supported", template.index("{%"))
    parts: list[str | _Expr] = []
    i = 0
    n = len(template)
    while i < n:
        start = template.find("{{", i)
        if start < 0:
            parts.append(template[i:])
            break
        if start > i:
            parts.append(template[i:start])
        body_start = start + 2
        j = body_start
        quoted = False
        escaped = False
        while j < n:
            ch = template[j]
            if quoted:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    quoted = False
            elif ch == '"':
                quoted = True
            elif ch == "}" and template.startswith("}}", j):
                break
            j += 1
        else:
            raise _fail("unclosed {{", start)
        parts.append(_parse_expr(template[body_start:j], body_start))
        i = j + 2
    return parts


def _lookup(context: Mapping, path: tuple[str, ...]) -> object:
    current: object = context
    for segment in path:
        if isinstance(current, Mapping):
            if segment not in current:
                return _MISSING
            current = current[segment]
        elif isinstance(current, (list, tuple)) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _text(item: object) -> str:
    return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


def _apply(expr: _Expr, current: object, name: str, arg: object) -> object:
    where = f"{expr.dotted} | {name}"
    if name == "default":
        return arg if current is _MISSING else current
    if current is _MISSING:
        raise TemplateError(f"{expr.dotted} is not available")
    if name == "json":
        return json.dumps(current, ensure_ascii=False)
    if name in ("lower", "upper", "trim"):
        if not isinstance(current, str):
            raise _fail(f"{where} needs text", expr.pos)
        return {"lower": str.lower, "upper": str.upper, "trim": str.strip}[name](current)
    if name == "length":
        if not isinstance(current, (str, list, tuple, Mapping)):
            raise _fail(f"{where} needs text, a list or an object", expr.pos)
        return len(current)
    if name == "first":
        if not isinstance(current, (str, list, tuple)):
            raise _fail(f"{where} needs text or a list", expr.pos)
        if not current:
            raise TemplateError(f"{expr.dotted} is empty")
        return current[0]
    if name == "join":
        if not isinstance(current, (list, tuple)):
            raise _fail(f"{where} needs a list", expr.pos)
        return str(arg).join(_text(item) for item in current)
    raise _fail(f"unknown filter {name!r}", expr.pos)  # pragma: no cover


def _evaluate(expr: _Expr, context: Mapping) -> object:
    current = _lookup(context, expr.path)
    if current is _MISSING and not any(name == "default" for name, _ in expr.filters):
        raise TemplateError(f"{expr.dotted} is not available")
    for name, arg in expr.filters:
        current = _apply(expr, current, name, arg)
    return current


def render(template: str, context: Mapping) -> str:
    """Render every ``{{ }}`` in ``template`` to text."""
    out: list[str] = []
    for part in _parse(template):
        out.append(part if isinstance(part, str) else _text(_evaluate(part, context)))
    return "".join(out)


def value(template: str, context: Mapping) -> object:
    """Like ``render``, but a template that is exactly one ``{{ }}`` keeps its type."""
    parts = _parse(template)
    if len(parts) == 1 and isinstance(parts[0], _Expr):
        return _evaluate(parts[0], context)
    return render(template, context)


def references(template: str) -> list[str]:
    """The dotted paths a template uses, in order, without repeats."""
    seen: dict[str, None] = {}
    for part in _parse(template):
        if isinstance(part, _Expr):
            seen.setdefault(part.dotted)
    return list(seen)
