"""Review CV and preferences to draft and accept profile.md and rubric.md."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from whyline import account
from whyline.agents import capabilities, definitions as d, records, runner, templates
from whyline.jobs import paths, profile

TEMPLATE_NAME = "job-profile"
AGENT_NAME = "job-profile"
PROFILE_DRAFT_FILE = "profile.draft.md"
RUBRIC_DRAFT_FILE = "rubric.draft.md"
RUNNABLE_CLIS: tuple[str, ...] = tuple(c for c in d.CLIS if capabilities.can_run(c))

_OPEN_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\r\n]*)$")
_REPORTED_OUTCOMES = ("succeeded", "succeeded_with_denials")
_ORIG_ENABLED_AGENTS = account.enabled_agents
_ORIG_AGENT_STATUS = account.agent_status


class ReviewError(profile.ProfileError):
    """Raised when review output, provider selection, or draft acceptance fails."""


@dataclass(frozen=True)
class DraftBlocks:
    profile: str
    rubric: str

    def __iter__(self):
        yield self.profile
        yield self.rubric


@dataclass(frozen=True)
class ReviewResult:
    ok: bool
    outcome: str
    reason: str = ""
    cli: str = ""
    run_id: str = ""
    profile: str = ""
    rubric: str = ""
    profile_draft_path: Path | None = None
    rubric_draft_path: Path | None = None


def profile_draft_path() -> Path:
    return paths.configured_home() / PROFILE_DRAFT_FILE


def rubric_draft_path() -> Path:
    return paths.configured_home() / RUBRIC_DRAFT_FILE


def _ensure_utf8(value: str, label: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ReviewError(f"{label} contains invalid Unicode text.") from error


def _write_private_file(folder: Path, filename: str, text: str) -> Path:
    _ensure_utf8(text, filename)
    target = folder / filename
    if target.is_symlink():
        raise ReviewError(f"Refusing to overwrite symlink: {target}")
    fd, raw_tmp = tempfile.mkstemp(dir=folder, prefix=f".{filename}.", suffix=".tmp")
    tmp_path = Path(raw_tmp)
    try:
        if os.name != "nt":
            os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if target.is_symlink():
            raise ReviewError(f"Refusing to overwrite symlink: {target}")
        os.replace(tmp_path, target)
        if os.name != "nt":
            os.chmod(target, 0o600)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def _normalize_draft_text(text: str, label: str) -> str:
    if not isinstance(text, str):
        raise ReviewError(f"{label} must be text.")
    _ensure_utf8(text, label)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ReviewError(f"{label} cannot be empty.")
    return normalized + "\n"


def parse_blocks(text: str) -> DraftBlocks:
    """Extract the fenced `profile` and `rubric` blocks from an agent's final answer."""
    if not isinstance(text, str):
        raise ReviewError("Agent answer must be text.")
    _ensure_utf8(text, "Agent answer")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    found: dict[str, str] = {}
    in_fence = False
    fence_char = ""
    fence_len = 0
    fence_tag = ""
    body_lines: list[str] = []

    for line in normalized.split("\n"):
        if not in_fence:
            match = _OPEN_FENCE_RE.match(line)
            if match is None:
                continue
            marker = match.group(1)
            info = match.group(2).strip()
            # Backtick info strings in CommonMark cannot contain backticks.
            if marker[0] == "`" and "`" in info:
                continue
            in_fence = True
            fence_char = marker[0]
            fence_len = len(marker)
            fence_tag = info.lower()
            body_lines = []
        else:
            stripped_leading = line.lstrip(" ")
            leading_spaces = len(line) - len(stripped_leading)
            if leading_spaces <= 3 and stripped_leading:
                run_len = len(stripped_leading) - len(stripped_leading.lstrip(fence_char))
                rest = stripped_leading[run_len:]
                if run_len >= fence_len and rest.strip(" \t") == "":
                    if fence_tag in ("profile", "rubric"):
                        if fence_tag in found:
                            raise ReviewError(
                                f"Multiple fenced '{fence_tag}' blocks in agent answer."
                            )
                        found[fence_tag] = "\n".join(body_lines)
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                    fence_tag = ""
                    body_lines = []
                    continue
            body_lines.append(line)

    if in_fence and fence_tag in ("profile", "rubric"):
        raise ReviewError(f"Unclosed fenced '{fence_tag}' block in agent answer.")

    if "profile" not in found:
        raise ReviewError("Missing fenced 'profile' block in agent answer.")
    if "rubric" not in found:
        raise ReviewError("Missing fenced 'rubric' block in agent answer.")

    profile_body = _normalize_draft_text(found["profile"], "Fenced 'profile' block")
    rubric_body = _normalize_draft_text(found["rubric"], "Fenced 'rubric' block")
    return DraftBlocks(profile=profile_body, rubric=rubric_body)


parse_answer = parse_blocks


def enabled_providers() -> list[str]:
    """Return runnable providers permitted by Settings (never offering disabled ones)."""
    if account.agent_status is not _ORIG_AGENT_STATUS:
        try:
            rows = account.agent_status(paths.configured_home())
        except Exception:
            rows = None
        if isinstance(rows, dict):
            return [
                c
                for c in RUNNABLE_CLIS
                if isinstance(rows.get(c), dict)
                and rows[c].get("enabled", True)
                and rows[c].get("available", True)
            ]

    enabled = account.enabled_agents()
    if enabled:
        return [c for c in RUNNABLE_CLIS if c in enabled]
    if isinstance(account.load_global(), dict):
        return []
    if account.enabled_agents is not _ORIG_ENABLED_AGENTS:
        return []
    return list(RUNNABLE_CLIS)


def save_drafts(profile_text: str, rubric_text: str) -> tuple[Path, Path]:
    """Validate and atomically write profile.draft.md and rubric.draft.md (mode 0600)."""
    norm_profile = _normalize_draft_text(profile_text, "Profile draft")
    norm_rubric = _normalize_draft_text(rubric_text, "Rubric draft")
    try:
        folder = paths.home()
    except OSError as error:
        raise ReviewError(f"Could not prepare jobs folder: {error}") from error

    p_target = folder / PROFILE_DRAFT_FILE
    r_target = folder / RUBRIC_DRAFT_FILE
    if p_target.is_symlink() or r_target.is_symlink():
        raise ReviewError("Refusing to overwrite symlinked draft file.")

    had_prev_profile = p_target.is_file()
    prev_profile = p_target.read_text(encoding="utf-8") if had_prev_profile else None
    written_profile = _write_private_file(folder, PROFILE_DRAFT_FILE, norm_profile)
    try:
        written_rubric = _write_private_file(folder, RUBRIC_DRAFT_FILE, norm_rubric)
    except Exception:
        if prev_profile is not None:
            _write_private_file(folder, PROFILE_DRAFT_FILE, prev_profile)
        else:
            written_profile.unlink(missing_ok=True)
        raise
    return written_profile, written_rubric


def read_drafts() -> DraftBlocks | None:
    """Return pending drafts from ~/.whyline/jobs/ if both exist, else None."""
    p_path = profile_draft_path()
    r_path = rubric_draft_path()
    if (
        p_path.is_symlink()
        or r_path.is_symlink()
        or not p_path.is_file()
        or not r_path.is_file()
    ):
        return None
    try:
        p_text = p_path.read_text(encoding="utf-8")
        r_text = r_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not p_text.strip() or not r_text.strip():
        return None
    return DraftBlocks(profile=p_text, rubric=r_text)


def _find_or_create_agent() -> d.AgentDef:
    configured = paths.configured_home()
    try:
        default_jobs = Path.home() / ".whyline" / "jobs"
    except OSError:
        default_jobs = configured
    workdir = "~/.whyline/jobs" if configured == default_jobs else str(configured)

    for item in d.discover(None):
        if isinstance(item, d.AgentDef) and item.kind == "personal" and item.name == AGENT_NAME:
            return item
        if isinstance(item, d.Broken) and item.kind == "personal" and item.path.stem == AGENT_NAME:
            raise ReviewError(f"Agent definition {item.path.name} is invalid: {item.error}")

    try:
        jobs_dir = paths.home()
    except OSError as error:
        raise ReviewError(f"Could not prepare jobs folder: {error}") from error

    created = templates.create(TEMPLATE_NAME, AGENT_NAME, workdir)
    if os.name != "nt" and jobs_dir.is_dir() and not jobs_dir.is_symlink():
        jobs_dir.chmod(0o700)
    return created


def _read_run_answer(record: Any) -> str:
    run_id = getattr(record, "run_id", "")
    if run_id:
        try:
            return records.read_final(run_id)
        except OSError:
            pass
    for attr in ("final_text", "answer", "output"):
        val = getattr(record, attr, None)
        if isinstance(val, str) and val:
            return val
    return ""


def run(
    cli: str | None = None,
    *,
    progress: Callable[[str], None] | None = None,
    run_fn: Any = None,
) -> ReviewResult:
    """Create/reuse job-profile in ~/.whyline/jobs/, run it, parse blocks, write drafts."""
    enabled = enabled_providers()
    chosen: str | None = None
    if cli is not None:
        if not isinstance(cli, str) or not cli.strip():
            raise ReviewError("Provider CLI name must be a non-empty string.")
        chosen = cli.strip()
        if chosen not in d.CLIS or not capabilities.can_run(chosen):
            allowed = ", ".join(RUNNABLE_CLIS)
            raise ReviewError(f"Unsupported provider '{chosen}'. Choose one of: {allowed}.")
        if chosen not in enabled:
            return ReviewResult(
                ok=False,
                outcome="all_unavailable",
                reason=f"{chosen}: Enable {chosen} in Settings or choose another provider.",
            )
    elif not enabled:
        return ReviewResult(
            ok=False,
            outcome="all_unavailable",
            reason="No enabled AI provider can run agents. Enable Claude, Codex, or Grok in Settings.",
        )

    try:
        defn = _find_or_create_agent()
        jobs_dir = paths.home()
    except (ReviewError, d.DefinitionError, OSError) as error:
        return ReviewResult(ok=False, outcome="failed", reason=str(error))

    if chosen is not None:
        run_defn = replace(defn, root=jobs_dir, runner=chosen, backup=())
    else:
        preferred = [c for c in (defn.runner, *defn.backup) if c in enabled]
        order = preferred if preferred else list(enabled)
        run_defn = replace(defn, root=jobs_dir, runner=order[0], backup=tuple(order[1:]))

    exec_kwargs: dict[str, Any] = {"source": "manual"}
    if progress is not None:
        exec_kwargs["progress"] = progress
    if run_fn is not None:
        exec_kwargs["run_fn"] = run_fn
    record = runner.execute_once(run_defn, **exec_kwargs)

    outcome = getattr(record, "outcome", "") or "failed"
    reason = getattr(record, "reason", "") or ""
    used_cli = getattr(record, "cli", "") or ""
    run_id = getattr(record, "run_id", "") or ""

    if outcome not in _REPORTED_OUTCOMES:
        return ReviewResult(
            ok=False,
            outcome=outcome,
            reason=reason,
            cli=used_cli,
            run_id=run_id,
        )

    answer = _read_run_answer(record)
    try:
        parsed = parse_blocks(answer)
    except ReviewError as error:
        return ReviewResult(
            ok=False,
            outcome="missing_block",
            reason=str(error),
            cli=used_cli,
            run_id=run_id,
        )

    try:
        p_draft, r_draft = save_drafts(parsed.profile, parsed.rubric)
    except ReviewError as error:
        return ReviewResult(
            ok=False,
            outcome="failed",
            reason=str(error),
            cli=used_cli,
            run_id=run_id,
        )

    return ReviewResult(
        ok=True,
        outcome=outcome,
        reason=reason,
        cli=used_cli,
        run_id=run_id,
        profile=parsed.profile,
        rubric=parsed.rubric,
        profile_draft_path=p_draft,
        rubric_draft_path=r_draft,
    )


def accept(
    profile_text: str | None = None,
    rubric_text: str | None = None,
) -> tuple[Path, Path]:
    """Move profile.draft.md and rubric.draft.md into profile.md and rubric.md (0600)."""
    if (profile_text is None) != (rubric_text is None):
        raise ReviewError(
            "Provide both profile_text and rubric_text, or neither to accept saved drafts."
        )

    if profile_text is not None and rubric_text is not None:
        save_drafts(profile_text, rubric_text)

    configured = paths.configured_home()
    p_draft = configured / PROFILE_DRAFT_FILE
    r_draft = configured / RUBRIC_DRAFT_FILE
    if p_draft.is_symlink() or r_draft.is_symlink():
        raise ReviewError("Refusing to accept symlinked draft file.")
    if not p_draft.is_file() or not r_draft.is_file():
        raise ReviewError(
            "No review drafts to accept. Run `whyline jobs review` first."
        )

    try:
        raw_profile = p_draft.read_text(encoding="utf-8")
        raw_rubric = r_draft.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ReviewError(f"Could not read review drafts: {error}") from error

    norm_profile = _normalize_draft_text(raw_profile, "Profile draft")
    norm_rubric = _normalize_draft_text(raw_rubric, "Rubric draft")

    try:
        folder = paths.home()
    except OSError as error:
        raise ReviewError(f"Could not prepare jobs folder: {error}") from error

    p_target = folder / profile.PROFILE_FILE
    r_target = folder / profile.RUBRIC_FILE
    if p_target.is_symlink() or r_target.is_symlink():
        raise ReviewError("Refusing to overwrite symlinked profile or rubric file.")

    # Ensure normalized LF content and private 0600 mode on both drafts before moving.
    if raw_profile != norm_profile:
        _write_private_file(folder, PROFILE_DRAFT_FILE, norm_profile)
    elif os.name != "nt":
        os.chmod(p_draft, 0o600)

    if raw_rubric != norm_rubric:
        _write_private_file(folder, RUBRIC_DRAFT_FILE, norm_rubric)
    elif os.name != "nt":
        os.chmod(r_draft, 0o600)

    os.replace(p_draft, p_target)
    os.replace(r_draft, r_target)
    if os.name != "nt":
        os.chmod(p_target, 0o600)
        os.chmod(r_target, 0o600)
    return p_target, r_target


def discard() -> None:
    """Remove pending profile.draft.md and rubric.draft.md without touching accepted files."""
    folder = paths.configured_home()
    if folder.is_symlink() or not folder.exists():
        return
    for name in (PROFILE_DRAFT_FILE, RUBRIC_DRAFT_FILE):
        target = folder / name
        if target.is_symlink():
            raise ReviewError(f"Refusing to remove symlink: {target}")
        if target.is_file():
            target.unlink(missing_ok=True)
