"""Watch agents: a number to compare, what was already told, and a note the
agent keeps for itself. whyline compares the value, never the agent."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

STOPS = ("first", "never")
MAX_VALUES = 200
MAX_NOTE = 500
MAX_ITEMS = 10
DAILY_CAP_RANGE = (1, 200)
_VALUE_RULE = re.compile(r"^(below|above) (\d+(?:\.\d+)?)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class Watch:
    stop: str = "never"  # first | never
    value: str = ""  # "below <number>" or "above <number>"
    urgent: bool = False
    daily_cap: int = 24

    def limit(self) -> tuple[str, float] | None:
        found = _VALUE_RULE.match(self.value)
        return None if found is None else (found[1], float(found[2]))


@dataclass
class Memory:
    values: list[tuple[str, float]] = field(default_factory=list)  # (time, value)
    told: float | None = None
    last_message: str = ""
    note: str = ""


@dataclass(frozen=True)
class Hit:
    value: float
    line: str


def check_value_rule(value: str) -> None:
    if value and not _VALUE_RULE.match(value):
        raise ValueError("watch value must look like 'below 4000' or 'above 4000'")


def _last_line(answer: str, prefix: str) -> str | None:
    found = None
    for line in answer.splitlines():
        if line.strip().startswith(prefix):
            found = line.strip()[len(prefix):]
    return found


def read_value(answer: str) -> float | None:
    rest = _last_line(answer, "VALUE:")
    if rest is None:
        return None
    number = re.search(r"\d+(?:\.\d+)?", rest.replace(",", "").replace(" ", ""))
    return None if number is None else float(number.group())


def _fmt(number: float) -> str:
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,.2f}"


def decide(watch: Watch, value: float, memory: Memory) -> Hit | None:
    """A hit when the value is past the limit and not already told. Updates
    memory.told (cleared back over the limit, set on a hit); the caller saves."""
    limit = watch.limit()
    if limit is None:
        return None
    direction, bound = limit
    below = direction == "below"
    past = value < bound if below else value > bound
    if not past:
        memory.told = None
        return None
    if memory.told is not None and not (value < memory.told if below else value > memory.told):
        return None
    earlier = memory.values[-1][1] if memory.values else None
    line = _fmt(value)
    if earlier is not None and earlier != value:
        line += f", {'down' if value < earlier else 'up'} from {_fmt(earlier)}"
    memory.told = value
    return Hit(value, f"{line}. Your limit is {_fmt(bound)}.")


def record(memory: Memory, value: float, now: datetime) -> None:
    memory.values.append((now.isoformat(timespec="seconds"), value))
    del memory.values[:-MAX_VALUES]


def _clean(text: str) -> str:
    return " ".join(_CONTROL.sub(" ", text).split())


def note(answer: str) -> str:
    rest = _last_line(answer, "REMEMBER:")
    return "" if rest is None else _clean(rest)[:MAX_NOTE]


def strip(answer: str) -> str:
    kept = [line for line in answer.splitlines()
            if not line.strip().startswith(("VALUE:", "REMEMBER:"))]
    return "\n".join(kept).strip()


def last_md(memory: Memory) -> str:
    parts = ["## Last message", memory.last_message or "(none yet)", "", "## Last values"]
    recent = memory.values[-10:]
    parts += [f"- {when[:10]}: {_fmt(v)}" for when, v in recent] or ["(none yet)"]
    parts += ["", "## Note", memory.note or "(none)"]
    return "\n".join(parts) + "\n"


def own_message(defn, found) -> str:
    args = defn.gate_args
    rule = args.get("rule", "changed")
    text = args.get("text", "")
    if rule == "appears":
        said = f'The text "{text}" is now on the page.'
    elif rule == "gone":
        said = f'The text "{text}" is no longer on the page.'
    else:
        said = "The page changed."
    lines = [defn.name, said]
    lines += [" ".join(i.line.split()) for i in found.items[:MAX_ITEMS]]
    lines += args.get("url", "").split()
    return "\n".join(lines)
