"""The Set up conversation for planning an idea into a repository.

Repositories an idea may be planned into are allowlisted in kv key `repos`
(name -> absolute path).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from whyline import account
from whyline import paths as wl_paths
from whyline.console import relay_ops
from whyline.console.plan_job import AutoRunRequest
from whyline.ideas import brainstorm, store

REPOS_KEY = "repos"

TEMPLATE = """\
repo: name
implementer: codex
tester: claude
reviewer: claude
release: human
backup: codex
timeout: 30
drafter: codex
plan_reviewer: claude
models: claude, codex, grok
passes: 1
final: claude"""


class SetupError(ValueError):
    """Raised when repository or setup configuration is invalid."""


class SettingsError(ValueError):
    """Raised when a setting is refused."""


def check_repo_path(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        raise SetupError(f"{p}: not a directory")
    if not (p / ".git").exists():
        raise SetupError(f"{p}: not a git repository")
    if not wl_paths.is_initialised(p):
        raise SetupError(f"{p}: whyline is not initialised here")
    return p


def list_repos(conn: sqlite3.Connection) -> dict[str, str]:
    raw = _kv(conn, REPOS_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def add_repo(conn: sqlite3.Connection, name: str, path: str | Path) -> str:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise SetupError("repository name is required")
    if any(ch.isspace() or ch == ":" for ch in cleaned_name):
        raise SetupError("repository name cannot contain whitespace or colons")
    resolved_path = check_repo_path(path)
    repos = list_repos(conn)
    repos[cleaned_name] = str(resolved_path)
    _kv_set(conn, REPOS_KEY, json.dumps(repos, sort_keys=True))
    return str(resolved_path)


def remove_repo(conn: sqlite3.Connection, name: str) -> bool:
    cleaned_name = name.strip()
    repos = list_repos(conn)
    if cleaned_name not in repos:
        return False
    del repos[cleaned_name]
    _kv_set(conn, REPOS_KEY, json.dumps(repos, sort_keys=True))
    return True


@dataclass(frozen=True)
class Request:
    repo: str
    implementer: str
    tester: str
    reviewer: str
    release: str
    backup: tuple[str, ...]
    timeout: int | str
    drafter: str
    plan_reviewer: str
    models: tuple[str, ...]
    passes: int
    final: str

    def as_fields(self) -> dict:
        return {
            "repo": self.repo,
            "implementer": self.implementer,
            "tester": self.tester,
            "reviewer": self.reviewer,
            "release": self.release,
            "backup": list(self.backup),
            "timeout": self.timeout,
            "drafter": self.drafter,
            "plan_reviewer": self.plan_reviewer,
            "models": list(self.models),
            "passes": self.passes,
            "final": self.final,
        }


def request_from_fields(fields: Mapping) -> Request:
    raw_backup = fields.get("backup") or ()
    if isinstance(raw_backup, str):
        backup_tuple = tuple(w for w in re.split(r"[\s,]+", raw_backup) if w and w != "none")
    elif isinstance(raw_backup, (list, tuple)):
        backup_tuple = tuple(str(x) for x in raw_backup if x and x != "none")
    else:
        backup_tuple = ()

    raw_models = fields.get("models") or ()
    if isinstance(raw_models, str):
        models_tuple = tuple(w for w in re.split(r"[\s,]+", raw_models) if w and w != "none")
    elif isinstance(raw_models, (list, tuple)):
        models_tuple = tuple(str(x) for x in raw_models if x and x != "none")
    else:
        models_tuple = ()

    raw_timeout = fields.get("timeout", 30)
    if str(raw_timeout).strip().lower() in ("none", "0"):
        timeout: int | str = "none"
    else:
        try:
            iv = int(raw_timeout)
            timeout = "none" if iv == 0 else iv
        except ValueError:
            timeout = raw_timeout

    try:
        passes = int(fields.get("passes", 1))
    except (ValueError, TypeError):
        passes = 1

    return Request(
        repo=str(fields.get("repo") or ""),
        implementer=str(fields.get("implementer") or ""),
        tester=str(fields.get("tester") or ""),
        reviewer=str(fields.get("reviewer") or ""),
        release=str(fields.get("release") or "human"),
        backup=backup_tuple,
        timeout=timeout,
        drafter=str(fields.get("drafter") or ""),
        plan_reviewer=str(fields.get("plan_reviewer") or ""),
        models=models_tuple,
        passes=passes,
        final=str(fields.get("final") or ""),
    )


def format_setup(request: Request) -> str:
    lines = [
        f"repo: {request.repo}",
        f"implementer: {request.implementer}",
        f"tester: {request.tester}",
        f"reviewer: {request.reviewer}",
        f"release: {request.release}",
        f"backup: {', '.join(request.backup) if request.backup else 'none'}",
        f"timeout: {request.timeout}",
        f"drafter: {request.drafter}",
        f"plan_reviewer: {request.plan_reviewer}",
        f"models: {', '.join(request.models) if request.models else 'none'}",
        f"passes: {request.passes}",
        f"final: {request.final or 'none'}",
    ]
    return "\n".join(lines)


def defaults(
    conn: sqlite3.Connection,
    idea_id: int,
    repo_name: str,
    root: Path | None = None,
) -> tuple[Request, tuple[str, ...]]:
    if root is None:
        repos = list_repos(conn)
        path_str = repos.get(repo_name)
        if not path_str:
            raise SetupError(f"unknown repository: {repo_name}")
        root = Path(path_str)

    roles = relay_ops.current_roles(root)
    backup = list(roles.get("backup") or [])
    timeout_raw = relay_ops.relay_timeout(root)
    timeout = "none" if timeout_raw == 0 else timeout_raw
    release = "human"
    planner = relay_ops.planner_agents(root)
    drafter = planner[0]
    plan_reviewer = planner[1]

    status = account.agent_status(root)
    usable = relay_ops.usable_agents(root, status)
    ag_state = relay_ops.antigravity_state(root)
    ag_trusted = (ag_state == "trusted")

    valid_agents = [a for a in usable if a != "antigravity" or ag_trusted]
    if not valid_agents:
        # Never fall back to a hard-coded agent: every agent on the card must
        # be installed and logged in (and Antigravity trusted) for this repo.
        if "antigravity" in usable:
            raise SetupError(
                f"No usable agent for {repo_name}: Antigravity is the only "
                "logged-in agent and it is not trusted for this repo. Log in "
                "another agent or trust Antigravity, then try again."
            )
        raise SetupError(
            f"No usable agent for {repo_name}: no agent is installed and "
            "logged in. Log one in, then try again."
        )
    fallback_agent = valid_agents[0]

    notes: list[str] = []

    for role in ("implementer", "tester", "reviewer"):
        agent = roles.get(role)
        if agent == "antigravity" and not ag_trusted:
            other_agents = [roles.get(r) for r in ("implementer", "tester", "reviewer") if r != role and roles.get(r) in valid_agents]
            candidates = [a for a in valid_agents if a not in other_agents]
            next_agent = candidates[0] if candidates else fallback_agent
            notes.append(f"Antigravity is not trusted for this repo; offered {next_agent} for {role}")
            roles[role] = next_agent
        elif agent not in usable:
            other_agents = [roles.get(r) for r in ("implementer", "tester", "reviewer") if r != role and roles.get(r) in valid_agents]
            candidates = [a for a in valid_agents if a not in other_agents]
            next_agent = candidates[0] if candidates else fallback_agent
            notes.append(f"{agent}: not installed or logged in; offered {next_agent} for {role}")
            roles[role] = next_agent

    clean_backup = []
    for a in backup:
        if a == "antigravity" and not ag_trusted:
            notes.append("Antigravity is not trusted for this repo; removed from backup")
        elif a not in usable:
            notes.append(f"{a}: not installed or logged in; removed from backup")
        else:
            clean_backup.append(a)
    backup = clean_backup

    if drafter == "antigravity" and not ag_trusted:
        next_agent = fallback_agent
        notes.append(f"Antigravity is not trusted for this repo; offered {next_agent} for drafter")
        drafter = next_agent
    elif drafter not in usable:
        next_agent = fallback_agent
        notes.append(f"{drafter}: not installed or logged in; offered {next_agent} for drafter")
        drafter = next_agent

    if plan_reviewer == "antigravity" and not ag_trusted:
        candidates = [a for a in valid_agents if a != drafter]
        next_agent = candidates[0] if candidates else fallback_agent
        notes.append(f"Antigravity is not trusted for this repo; offered {next_agent} for plan_reviewer")
        plan_reviewer = next_agent
    elif plan_reviewer not in usable:
        candidates = [a for a in valid_agents if a != drafter]
        next_agent = candidates[0] if candidates else fallback_agent
        notes.append(f"{plan_reviewer}: not installed or logged in; offered {next_agent} for plan_reviewer")
        plan_reviewer = next_agent

    # Carry over brainstorm values
    bs_fields = _stored_fields(conn, idea_id)
    models_carried: tuple[str, ...] = ()
    passes = 1
    final_carried = ""
    if bs_fields and bs_fields.get("models"):
        models_carried = tuple(bs_fields["models"])
        passes = int(bs_fields.get("passes", 1))
        final_carried = str(bs_fields.get("final") or (models_carried[0] if models_carried else ""))
    else:
        bs_req, _bs_notes = brainstorm.defaults(conn)
        models_carried = tuple(bs_req.models)
        passes = bs_req.passes
        final_carried = bs_req.final

    clean_models: list[str] = []
    for m in models_carried:
        if m == "antigravity" and not ag_trusted:
            candidates = [a for a in valid_agents if a not in clean_models and a not in models_carried]
            if candidates:
                next_agent = candidates[0]
                clean_models.append(next_agent)
                notes.append(f"Antigravity is not trusted for this repo; offered {next_agent} for models")
            elif clean_models:
                notes.append("Antigravity is not trusted for this repo; removed from models")
            else:
                next_agent = fallback_agent
                clean_models.append(next_agent)
                notes.append(f"Antigravity is not trusted for this repo; offered {next_agent} for models")
        elif m not in usable:
            candidates = [a for a in valid_agents if a not in clean_models and a not in models_carried]
            if candidates:
                next_agent = candidates[0]
                clean_models.append(next_agent)
                notes.append(f"{m}: not installed or logged in; offered {next_agent} for models")
            elif clean_models:
                notes.append(f"{m}: not installed or logged in; removed from models")
            else:
                next_agent = fallback_agent
                clean_models.append(next_agent)
                notes.append(f"{m}: not installed or logged in; offered {next_agent} for models")
        else:
            if m not in clean_models:
                clean_models.append(m)

    if not clean_models:
        clean_models = [fallback_agent]

    if final_carried == "antigravity" and not ag_trusted:
        candidates = [a for a in clean_models if a in valid_agents]
        next_agent = candidates[0] if candidates else fallback_agent
        notes.append(f"Antigravity is not trusted for this repo; offered {next_agent} for final")
        final = next_agent
    elif final_carried not in usable:
        candidates = [a for a in clean_models if a in valid_agents]
        next_agent = candidates[0] if candidates else fallback_agent
        notes.append(f"{final_carried}: not installed or logged in; offered {next_agent} for final")
        final = next_agent
    else:
        final = final_carried if final_carried in valid_agents else (clean_models[0] if clean_models else fallback_agent)

    req = Request(
        repo=repo_name,
        implementer=roles.get("implementer") or fallback_agent,
        tester=roles.get("tester") or fallback_agent,
        reviewer=roles.get("reviewer") or fallback_agent,
        release=release,
        backup=tuple(backup),
        timeout=timeout,
        drafter=drafter,
        plan_reviewer=plan_reviewer,
        models=tuple(clean_models),
        passes=passes,
        final=final,
    )
    return req, tuple(notes)


def apply(
    base: Request,
    fields: Mapping,
    *,
    root: Path,
) -> tuple[Request, tuple[str, ...]]:
    status = account.agent_status(root)
    usable = relay_ops.usable_agents(root, status)
    ag_state = relay_ops.antigravity_state(root)
    ag_trusted = (ag_state == "trusted")

    notes: list[str] = []

    # Check release
    if "release" in fields:
        rel = str(fields["release"]).strip().lower()
        if rel != "human":
            raise SettingsError("release other than 'human' is refused")

    for key in ("implementer", "tester", "reviewer", "drafter", "plan_reviewer"):
        if key in fields and not str(fields[key]).strip():
            raise SettingsError(f"{key}: agent name is required")

    if "timeout" in fields:
        raw_t = fields["timeout"]
        if str(raw_t).strip().lower() in ("none", "0"):
            pass
        else:
            try:
                iv = int(raw_t)
                if iv not in (15, 30, 45, 60):
                    raise SettingsError(f"timeout: must be 15, 30, 45, 60, or none (got {raw_t})")
            except ValueError:
                raise SettingsError(f"timeout: must be 15, 30, 45, 60, or none (got {raw_t})")

    if "passes" in fields:
        try:
            pv = int(fields["passes"])
            if pv not in (1, 2, 3):
                raise SettingsError(f"passes: must be 1, 2, or 3 (got {pv})")
        except (ValueError, TypeError):
            raise SettingsError(f"passes: invalid number {fields['passes']}")

    merged = dict(base.as_fields())
    for k, v in fields.items():
        if k == "backup":
            if isinstance(v, str):
                merged[k] = [w for w in re.split(r"[\s,]+", v) if w and w != "none"]
            elif isinstance(v, (list, tuple)):
                merged[k] = [str(x) for x in v if x and x != "none"]
        elif k == "models":
            if isinstance(v, str):
                merged[k] = [w for w in re.split(r"[\s,]+", v) if w and w != "none"]
            elif isinstance(v, (list, tuple)):
                merged[k] = [str(x) for x in v if x and x != "none"]
        elif k == "timeout":
            if str(v).strip().lower() in ("none", "0"):
                merged[k] = "none"
            else:
                merged[k] = int(v)
        elif k == "passes":
            merged[k] = int(v)
        else:
            merged[k] = v

    req = request_from_fields(merged)
    # Validate every agent the merged request names against `root`, not just
    # the edited fields: a repo-only edit must not carry agents accepted for
    # the previous repository.
    named = [
        req.implementer,
        req.tester,
        req.reviewer,
        req.drafter,
        req.plan_reviewer,
        req.final,
        *req.backup,
        *req.models,
    ]
    for agent in named:
        agent = agent.strip()
        if not agent:
            continue
        if agent not in usable:
            raise SettingsError(f"{agent}: not logged in")
        if agent == "antigravity" and not ag_trusted:
            raise SettingsError("Antigravity is not trusted for this repo")
    return req, tuple(notes)


def request(conn: sqlite3.Connection, idea_id: int) -> AutoRunRequest:
    idea = store.get(conn, idea_id)
    if idea is None:
        raise LookupError(f"no idea {idea_id}")
    raw = _kv(conn, f"telegram_settings:{idea_id}")
    if not raw:
        raw = _kv(conn, "telegram_settings")
    fields = json.loads(raw) if raw else {}
    req = request_from_fields(fields)
    timeout_int = 0 if req.timeout == "none" or req.timeout == 0 or str(req.timeout).lower() == "none" else int(req.timeout)
    attachments = (Path(idea.brainstorm_path),) if idea.brainstorm_path else ()
    return AutoRunRequest(
        name=idea.title,
        topic=idea.original_text,
        replace=False,
        continue_paths=False,
        agents=tuple(req.models),
        passes=int(req.passes),
        final_agent=req.final,
        timeout_minutes=timeout_int,
        attachments=attachments,
        drafter=req.drafter,
        reviewer=req.plan_reviewer,
        implementer=req.implementer,
        tester=req.tester,
        reviewer_role=req.reviewer,
        release=req.release or "human",
        chain=tuple(req.backup),
    )


def _kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def _kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    with store._txn(conn):
        conn.execute(
            """
            INSERT INTO kv (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _stored_fields(conn: sqlite3.Connection, idea_id: int) -> dict:
    raw = _kv(conn, f"telegram_settings:{idea_id}")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    raw = _kv(conn, "telegram_card")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("fields"), dict):
                return parsed["fields"]
        except json.JSONDecodeError:
            pass
    return {}
