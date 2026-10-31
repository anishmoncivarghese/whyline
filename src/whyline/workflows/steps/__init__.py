"""The step registry: which step types exist and what fields each takes
(spec section 4.2). Validation reads this; the engine adds behaviour per type."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from whyline.agents.definitions import CLIS

KINDS = ("str", "int", "bool", "list[str]", "table", "step_ref")
CONDITION_OPS = ("eq", "ne", "contains", "gt", "lt", "exists", "empty")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str
    required: bool = False
    templated: bool = True
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown field kind {self.kind}")


@dataclass(frozen=True)
class StepType:
    name: str
    fields: tuple[FieldSpec, ...] = ()
    ports: tuple[str, ...] = ("next",)
    writes: bool = False

    def field(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)


def _target(name: str) -> FieldSpec:
    return FieldSpec(name, "step_ref", templated=False)


def _literal(name: str, kind: str = "str", required: bool = False,
             choices: tuple[str, ...] = ()) -> FieldSpec:
    return FieldSpec(name, kind, required, templated=False, choices=choices)


_TYPES = (
    StepType("set", (FieldSpec("values", "table", True),)),
    StepType("condition", (
        FieldSpec("left", "str", True),
        _literal("op", required=True, choices=CONDITION_OPS),
        FieldSpec("right", "str"),
        _target("then"), _target("else"),
    ), ports=("true", "false")),
    StepType("switch", (
        FieldSpec("value", "str", True),
        FieldSpec("cases", "table"),
        _target("default"),
    ), ports=("default",)),
    StepType("wait", (FieldSpec("minutes", "int"), _literal("until"))),
    StepType("stop"),
    StepType("approval", (
        FieldSpec("message", "str", True),
        FieldSpec("expires_hours", "int"),
    )),
    StepType("agent", (
        _literal("runner", required=True, choices=CLIS),
        _literal("backup", "list[str]", choices=CLIS),
        _literal("model"),
        _literal("instructions", required=True),
        FieldSpec("inputs", "list[str]"),
        _literal("output", choices=("text", "json")),
        FieldSpec("schema", "table"),
        FieldSpec("timeout_minutes", "int"),
    )),
    StepType("deliver", (
        _literal("to", required=True, choices=("telegram", "email", "file")),
        _literal("chat"),
        _literal("email"),
        FieldSpec("subject", "str"),
        FieldSpec("text", "str", True),
    ), writes=True),
)

STEP_TYPES: Mapping[str, StepType] = MappingProxyType({t.name: t for t in _TYPES})
