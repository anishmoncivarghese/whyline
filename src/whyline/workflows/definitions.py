"""Workflow definitions: one TOML file per workflow, in a repository
(.whyline/workflows/) or personal (~/.whyline/workflows/). A definition never
runs on its own; acceptance lives in the state file, never here (spec 4.4).

`Workflow.raw` is the parsed table in normal form (version and description
always present, empty optional parts dropped), so it is stable across a
render/parse round trip and the hashes ignore how a file was formatted."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from whyline.paths import global_whyline_dir
from whyline.workflows import paths
from whyline.workflows.steps import STEP_TYPES, FieldSpec

NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
IDENT = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
TRIGGER_KINDS = ("manual", "daily", "weekdays", "every", "folder")
INPUT_TYPES = ("string", "number", "boolean")
MAX_STEPS = 30
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_TOP_KEYS = {"name", "description", "version", "trigger", "input", "step", "layout"}
_TRIGGER_FIELDS = {"daily": ("at",), "weekdays": ("at",), "every": ("every_hours",),
                   "folder": ("folder",), "manual": ()}


class DefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class TriggerSpec:
    kind: str = "manual"
    at: str = ""
    every_hours: int = 0
    folder: str = ""


@dataclass(frozen=True)
class InputSpec:
    name: str
    type: str = "string"
    default: object = None


@dataclass(frozen=True)
class Step:
    id: str
    type: str
    fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Workflow:
    name: str
    kind: str  # "personal" | "repo"
    path: Path
    root: Path
    description: str = ""
    trigger: TriggerSpec = field(default_factory=TriggerSpec)
    inputs: tuple[InputSpec, ...] = ()
    steps: tuple[Step, ...] = ()
    layout: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)

    @property
    def workflow_id(self) -> str:
        if self.kind == "repo":
            return f"repo:{self.root.resolve()}:{self.name}"
        return f"personal:{self.name}"

    @property
    def label(self) -> str:
        return f"{self.name} ({self.kind})"


@dataclass(frozen=True)
class Broken:
    path: Path
    kind: str
    error: str


# ---- validation -----------------------------------------------------------

def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_plain(value: object) -> bool:
    if isinstance(value, (str, bool, int, float)):
        return True
    if isinstance(value, list):
        return all(_is_plain(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_plain(v) for k, v in value.items())
    return False


def _kind_ok(value: object, kind: str) -> bool:
    if kind in ("str", "step_ref"):
        return isinstance(value, str)
    if kind == "int":
        return _is_int(value)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "list[str]":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return isinstance(value, dict) and _is_plain(value)


def _has_template(value: object) -> bool:
    if isinstance(value, str):
        return "{{" in value
    if isinstance(value, list):
        return any(_has_template(v) for v in value)
    if isinstance(value, dict):
        return any(_has_template(v) for v in value.values())
    return False


def _trigger(raw: object, errors: list[str]) -> TriggerSpec:
    if not isinstance(raw, dict):
        errors.append('trigger: must be a table')
        return TriggerSpec()
    kind = raw.get("kind", "manual")
    if kind not in TRIGGER_KINDS:
        errors.append(f'trigger: field "kind" must be one of {", ".join(TRIGGER_KINDS)}')
        return TriggerSpec()
    allowed = _TRIGGER_FIELDS[kind]
    for key in raw:
        if key != "kind" and key not in allowed:
            errors.append(f'trigger: field "{key}" is not used by a {kind} trigger')
    at, hours, folder = raw.get("at", ""), raw.get("every_hours", 0), raw.get("folder", "")
    if kind in ("daily", "weekdays") and not (isinstance(at, str) and _TIME.match(at)):
        errors.append('trigger: field "at" must be a 24-hour time like 08:00')
    if kind == "every" and not (_is_int(hours) and 1 <= hours <= 24 and 24 % hours == 0):
        errors.append('trigger: field "every_hours" must be 1 to 24 and divide 24 evenly')
    if kind == "folder":
        if not isinstance(folder, str) or not folder:
            errors.append('trigger: field "folder" needs a folder')
        else:
            path = Path(folder).expanduser()
            home = Path.home().resolve()
            if not path.is_absolute() or not path.resolve().is_relative_to(home):
                errors.append('trigger: field "folder" must be inside your home folder')
    return TriggerSpec(
        kind=kind,
        at=at if kind in ("daily", "weekdays") and isinstance(at, str) else "",
        every_hours=hours if kind == "every" and _is_int(hours) else 0,
        folder=folder if kind == "folder" and isinstance(folder, str) else "",
    )


def _inputs(raw: object, errors: list[str]) -> tuple[InputSpec, ...]:
    if not isinstance(raw, list) or not all(isinstance(i, dict) for i in raw):
        errors.append('input: must be a list of [[input]] tables')
        return ()
    found: list[InputSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, 1):
        name = item.get("name")
        label = f'input "{name}"' if isinstance(name, str) else f"input #{index}"
        for key in item:
            if key not in ("name", "type", "default"):
                errors.append(f'{label}: unknown field "{key}"')
        if not isinstance(name, str) or not IDENT.match(name):
            errors.append(f'{label}: field "name" must match {IDENT.pattern}')
            continue
        if name in seen:
            errors.append(f'{label}: field "name" is used twice')
        seen.add(name)
        kind = item.get("type", "string")
        if kind not in INPUT_TYPES:
            errors.append(f'{label}: field "type" must be one of {", ".join(INPUT_TYPES)}')
            continue
        default = item.get("default")
        ok = (default is None or (kind == "string" and isinstance(default, str))
              or (kind == "number" and isinstance(default, (int, float))
                  and not isinstance(default, bool))
              or (kind == "boolean" and isinstance(default, bool)))
        if not ok:
            errors.append(f'{label}: field "default" must be a {kind}')
            default = None
        found.append(InputSpec(name, kind, default))
    return tuple(found)


def _check_field(label: str, spec: FieldSpec, value: object, errors: list[str]) -> None:
    where = f'{label} field "{spec.name}"'
    if not _kind_ok(value, spec.kind):
        errors.append(f"{where}: must be a {spec.kind.replace('step_ref', 'step id')}")
        return
    if not spec.templated and _has_template(value):
        errors.append(f"{where}: must not contain a template ({{{{ }}}})")
        return
    if spec.choices:
        items = value if isinstance(value, list) else [value]
        bad = [i for i in items if i not in spec.choices]
        if bad:
            errors.append(f'{where}: must be one of {", ".join(spec.choices)}')


def _in_range(label: str, name: str, value: object, low: int, high: int,
              errors: list[str]) -> None:
    if _is_int(value) and not low <= value <= high:
        errors.append(f'{label} field "{name}": must be between {low} and {high}')


def _step_rules(label: str, kind: str, f: dict, errors: list[str]) -> None:
    """Rules that span fields. Field kinds were already checked."""
    if kind == "condition":
        if f.get("op") not in ("exists", "empty", None) and "right" not in f:
            errors.append(f'{label} field "right": required unless op is exists or empty')
    elif kind == "wait":
        if ("minutes" in f) == ("until" in f):
            errors.append(f'{label} field "minutes": give exactly one of minutes or until')
        _in_range(label, "minutes", f.get("minutes"), 1, 10080, errors)
        if isinstance(f.get("until"), str) and not _TIME.match(f["until"]):
            errors.append(f'{label} field "until": must be a 24-hour time like 08:00')
    elif kind == "approval":
        _in_range(label, "expires_hours", f.get("expires_hours"), 1, 168, errors)
    elif kind == "agent":
        _in_range(label, "timeout_minutes", f.get("timeout_minutes"), 1, 240, errors)
        backup = f.get("backup")
        if isinstance(backup, list) and (len(set(backup)) != len(backup)
                                         or f.get("runner") in backup):
            errors.append(f'{label} field "backup": list other CLIs, each once')
    elif kind == "deliver":
        if f.get("to") == "email" and "email" not in f:
            errors.append(f'{label} field "email": required when to is email')
        if "chat" in f and f.get("to") != "telegram":
            errors.append(f'{label} field "chat": only used when to is telegram')
        if "email" in f and f.get("to") != "email":
            errors.append(f'{label} field "email": only used when to is email')


def _targets(kind: str, f: dict, label: str, errors: list[str]) -> list[tuple[str, str]]:
    """(field description, target id) for every routing target of one step."""
    found: list[tuple[str, str]] = []
    for name in ("then", "else", "default"):
        if isinstance(f.get(name), str) and (kind == "condition" or name == "default"):
            found.append((name, f[name]))
    cases = f.get("cases")
    if kind == "switch" and isinstance(cases, dict):
        for case, body in cases.items():
            if not isinstance(body, dict) or set(body) != {"equals", "goto"} or not all(
                    isinstance(v, str) for v in body.values()):
                errors.append(f'{label} field "cases": case "{case}" needs text '
                              '"equals" and "goto"')
            else:
                found.append((f"cases.{case}.goto", body["goto"]))
    return found


def _steps(raw: object, errors: list[str]) -> tuple[Step, ...]:
    if not isinstance(raw, list) or not all(isinstance(s, dict) for s in raw):
        errors.append("step: must be a list of [[step]] tables")
        return ()
    if len(raw) > MAX_STEPS:
        errors.append(f"step: at most {MAX_STEPS} steps, found {len(raw)}")
    index_of: dict[str, int] = {}
    for index, item in enumerate(raw):
        sid = item.get("id")
        if isinstance(sid, str) and IDENT.match(sid):
            index_of.setdefault(sid, index)
    steps: list[Step] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        sid = item.get("id")
        label = f'step "{sid}"' if isinstance(sid, str) else f"step #{index + 1}"
        if not isinstance(sid, str) or not IDENT.match(sid):
            errors.append(f'{label} field "id": must match {IDENT.pattern}')
        elif sid in seen:
            errors.append(f'{label} field "id": used twice')
        if isinstance(sid, str):
            seen.add(sid)
        kind = item.get("type")
        spec = STEP_TYPES.get(kind) if isinstance(kind, str) else None
        if spec is None:
            errors.append(f'{label} field "type": must be one of {", ".join(STEP_TYPES)}')
            continue
        fields = {k: v for k, v in item.items() if k not in ("id", "type")}
        for key in fields:
            if spec.field(key) is None:
                errors.append(f'{label} field "{key}": unknown for a {kind} step')
        for fspec in spec.fields:
            if fspec.name not in fields:
                if fspec.required:
                    errors.append(f'{label} field "{fspec.name}": required')
            else:
                _check_field(label, fspec, fields[fspec.name], errors)
        _step_rules(label, kind, fields, errors)
        for where, target in _targets(kind, fields, label, errors):
            if "{{" in target:
                if where.startswith("cases."):  # field-level checks only see the table
                    errors.append(
                        f'{label} field "{where}": must not contain a template ({{{{ }}}})')
            elif target not in index_of:
                errors.append(f'{label} field "{where}": no step "{target}"')
            elif index_of[target] <= index:
                errors.append(f'{label} field "{where}": "{target}" must come later in the file')
        if isinstance(sid, str):
            steps.append(Step(sid, kind, fields))
    return tuple(steps)


def _layout(raw: object, errors: list[str]) -> dict:
    if not isinstance(raw, dict):
        errors.append("layout: must be a table")
        return {}
    for key, value in raw.items():
        if not (isinstance(value, list) and value and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
            errors.append(f'layout field "{key}": must be a list of numbers')
    return dict(raw)


def _to_raw(name: str, description: str, version: int, trigger: TriggerSpec,
            inputs: tuple[InputSpec, ...], steps: tuple[Step, ...], layout: Mapping) -> dict:
    t: dict = {"kind": trigger.kind}
    for key in ("at", "every_hours", "folder"):
        if getattr(trigger, key):
            t[key] = getattr(trigger, key)
    raw: dict = {"name": name, "description": description, "version": version, "trigger": t}
    if inputs:
        raw["input"] = [
            {"name": i.name, "type": i.type, **({} if i.default is None else {"default": i.default})}
            for i in inputs
        ]
    raw["step"] = [{"id": s.id, "type": s.type, **s.fields} for s in steps]
    if layout:
        raw["layout"] = dict(layout)
    return raw


def parse(text: str, *, kind: str, path: Path, repo_root: Path | None = None) -> Workflow:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise DefinitionError(f"not valid TOML: {error}") from error
    errors: list[str] = []
    for key in raw:
        if key not in _TOP_KEYS:
            errors.append(f'field "{key}": unknown')
    name = raw.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        errors.append('field "name": must be lower-case letters, digits and -, '
                      "starting with a letter, at most 40")
        name = ""
    description = raw.get("description", "")
    if not isinstance(description, str):
        errors.append('field "description": must be text')
        description = ""
    version = raw.get("version", 1)
    if version != 1 or not _is_int(version):
        errors.append('field "version": must be 1')
        version = 1
    if kind == "repo":
        if repo_root is None:
            errors.append("a repo workflow needs its repository")
        root = repo_root or Path.home()
    else:
        root = Path.home()
    trigger = _trigger(raw.get("trigger", {}), errors)
    inputs = _inputs(raw.get("input", []), errors)
    steps = _steps(raw.get("step", []), errors)
    layout = _layout(raw.get("layout", {}), errors)
    if errors:
        raise DefinitionError("\n".join(errors))
    return Workflow(
        name=name, kind=kind, path=path, root=root, description=description,
        trigger=trigger, inputs=inputs, steps=steps, layout=layout,
        raw=_to_raw(name, description, version, trigger, inputs, steps, layout),
    )


def load(path: Path, *, kind: str, repo_root: Path | None = None) -> Workflow:
    return parse(path.read_text(encoding="utf-8"), kind=kind, path=path, repo_root=repo_root)


# ---- rendering ------------------------------------------------------------

def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else _q(key)


def _val(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _q(value)
    if isinstance(value, list):
        return "[" + ", ".join(_val(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_val(v)}" for k, v in value.items()) + " }" \
            if value else "{}"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


def render(workflow: Workflow) -> str:
    version = workflow.raw.get("version", 1)
    lines = [f"name = {_q(workflow.name)}", f"description = {_q(workflow.description)}",
             f"version = {version}", "", "[trigger]", f"kind = {_q(workflow.trigger.kind)}"]
    t = workflow.trigger
    if t.at:
        lines.append(f"at = {_q(t.at)}")
    if t.every_hours:
        lines.append(f"every_hours = {t.every_hours}")
    if t.folder:
        lines.append(f"folder = {_q(t.folder)}")
    for item in workflow.inputs:
        lines += ["", "[[input]]", f"name = {_q(item.name)}", f"type = {_q(item.type)}"]
        if item.default is not None:
            lines.append(f"default = {_val(item.default)}")
    for step in workflow.steps:
        lines += ["", "[[step]]", f"id = {_q(step.id)}", f"type = {_q(step.type)}"]
        lines += [f"{_key(k)} = {_val(v)}" for k, v in step.fields.items()]
    if workflow.layout:
        lines += ["", "[layout]"]
        lines += [f"{_key(k)} = {_val(v)}" for k, v in workflow.layout.items()]
    return "\n".join(lines) + "\n"


def save(workflow: Workflow) -> Path:
    workflow.path.parent.mkdir(parents=True, exist_ok=True)
    workflow.path.write_text(render(workflow), encoding="utf-8")
    return workflow.path


# ---- hashes (spec 4.4) ----------------------------------------------------

def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def semantic_hash(raw: Mapping[str, object]) -> str:
    return _digest({k: v for k, v in raw.items() if k != "layout"})


def layout_hash(raw: Mapping[str, object]) -> str:
    return _digest(raw.get("layout", {}))


# ---- discovery ------------------------------------------------------------

def _scan(folder: Path, kind: str, repo_root: Path | None) -> list[Workflow | Broken]:
    if not folder.is_dir():
        return []
    valid: list[Workflow] = []
    broken: list[Broken] = []
    for path in folder.glob("*.toml"):
        if kind == "personal" and path.name == "settings.toml":
            continue  # the workflow settings file lives beside the workflows
        try:
            valid.append(load(path, kind=kind, repo_root=repo_root))
        except (DefinitionError, OSError, UnicodeDecodeError) as error:
            broken.append(Broken(path, kind, str(error)))
    broken.sort(key=lambda item: item.path.name)
    valid.sort(key=lambda w: (w.name, w.path.name))
    return broken + valid


def discover(repo_root: Path | None) -> list[Workflow | Broken]:
    found = _scan(paths.repo_dir(repo_root), "repo", repo_root) if repo_root else []
    return found + _scan(global_whyline_dir() / "workflows", "personal", None)
