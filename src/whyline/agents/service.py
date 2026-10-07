"""The one API the console and `whyline agents` share."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whyline.agents import definitions as d, records, runner, state


class AgentNotFound(LookupError):
    pass


class Ambiguous(LookupError):
    pass


@dataclass
class Row:
    defn: object  # AgentDef | Broken
    status: str
    last_outcome: str
    last_run: str
    next_due: str
    when: str


def when_text(t: d.Trigger) -> str:
    return {
        "manual": "on demand",
        "daily": f"daily at {t.at}",
        "weekdays": f"weekdays at {t.at}",
        "every": f"every {t.every_hours} hours",
        "folder": f"when files appear in {t.folder}",
    }[t.kind]


def find(name: str, repo_root: Path | None) -> d.AgentDef:
    kind = None
    if ":" in name:
        kind, name = name.split(":", 1)
    matches = [a for a in d.discover(repo_root)
               if isinstance(a, d.AgentDef) and a.name == name and (kind is None or a.kind == kind)]
    if not matches:
        raise AgentNotFound(f"No agent named {name}")
    if len(matches) > 1:
        raise Ambiguous(f"Both a repo and a personal agent are named {name}: "
                        f"use repo:{name} or personal:{name}")
    return matches[0]


def rows(repo_root: Path | None) -> list[Row]:
    conn = state.connect()
    out = []
    for item in d.discover(repo_root):
        if isinstance(item, d.Broken):
            out.append(Row(item, "needs_review", "", "", "", item.error))
            continue
        status = state.check_hash(conn, item)
        act = state.get(conn, item.agent_id)
        last = records.list_runs(item.agent_id, limit=1)
        out.append(Row(item, status, last[0].outcome if last else "",
                       last[0].started[:16].replace("T", " ") if last else "",
                       (act.next_due_at[:16].replace("T", " ") if act and act.next_due_at else ""),
                       when_text(item.trigger)))
    return out


def save_new(defn: d.AgentDef) -> Path:
    path = d.save(defn)
    state.accept(state.connect(), defn)
    return path


def accept(name: str, repo_root: Path | None) -> None:
    state.accept(state.connect(), find(name, repo_root))


def pause(name: str, repo_root: Path | None) -> None:
    state.set_status(state.connect(), find(name, repo_root).agent_id, "paused", "paused by you")


def resume(name: str, repo_root: Path | None) -> None:
    defn = find(name, repo_root)
    conn = state.connect()
    if state.check_hash(conn, defn) == "needs_review":
        raise ValueError(f"{defn.label} changed since you accepted it: accept it first")
    state.update(conn, defn.agent_id, status="active", paused_reason="", consecutive_failures=0)


def delete(name: str, repo_root: Path | None) -> None:
    defn = find(name, repo_root)
    defn.path.unlink(missing_ok=True)
    state.remove(state.connect(), defn.agent_id)


def run_now(name: str, repo_root: Path | None, *, progress=None, run_fn=None) -> records.RunRecord:
    return runner.execute_once(find(name, repo_root), source="manual", progress=progress, run_fn=run_fn)


def history(name: str, repo_root: Path | None, n: int = 20) -> list[records.RunRecord]:
    return records.list_runs(find(name, repo_root).agent_id, limit=n)


def describe(defn: d.AgentDef) -> str:
    t = defn.trigger
    when = {
        "manual": "When you run it",
        "daily": f"Every day at {t.at} on this Mac",
        "weekdays": f"Every weekday at {t.at} on this Mac",
        "every": f"Every {t.every_hours} hours on this Mac",
        "folder": f"When files appear in {t.folder} on this Mac",
    }[t.kind]
    reads = " and ".join(defn.sources) if defn.sources else "your instructions only"
    text = f"{when}, {defn.runner} reads {reads} (read-only) and answers your instructions."
    if defn.backup:
        text += (f" If {defn.runner} is out of usage or logged out, "
                 f"{' then '.join(defn.backup)} runs it instead.")
    text += " It can't change files. Results go to history, a notification"
    text += f", and {defn.report_folder}/<date>.md." if defn.report_folder else "."
    return text
