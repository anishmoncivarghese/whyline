"""Company watch list and AI company suggestions in ~/.whyline/jobs/companies.toml."""

from __future__ import annotations

import builtins
import datetime
import json
import os
import re
import tempfile
import tomllib
import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from whyline.agents import capabilities, definitions as d, records, runner, templates
from whyline.jobs import paths, profile, review

COMPANIES_FILE = "companies.toml"
TEMPLATE_NAME = "job-companies"
AGENT_NAME = "job-companies"

MAX_SUGGESTIONS = 40
MAX_NAME_LENGTH = 80
MAX_REASON_CHARS = 300  # reason must be strictly under 300 characters (0..299)
MAX_URL_LENGTH = 2048

STATUSES = ("suggested", "accepted", "removed")
ATS_KINDS = (
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
    "recruitee",
    "careers_page",
    "unknown",
)
ADDED_BY_KINDS = ("ai", "user")
COMPANY_KEYS = (
    "name",
    "status",
    "reason",
    "ats",
    "slug",
    "careers_url",
    "added_by",
    "checked_at",
)

RUNNABLE_CLIS: tuple[str, ...] = review.RUNNABLE_CLIS
_OPEN_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\r\n]*)$")
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_REPORTED_OUTCOMES = ("succeeded", "succeeded_with_denials")


class CompanyError(profile.ProfileError):
    """Raised when a company entry, URL, or companies.toml file is invalid."""


@dataclass(frozen=True)
class Company:
    name: str
    status: str = "suggested"
    reason: str = ""
    ats: str = "unknown"
    slug: str = ""
    careers_url: str = ""
    added_by: str = "user"
    checked_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "ats": self.ats,
            "slug": self.slug,
            "careers_url": self.careers_url,
            "added_by": self.added_by,
            "checked_at": self.checked_at,
        }

    def __getitem__(self, key: str) -> str:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in COMPANY_KEYS

    def keys(self) -> tuple[str, ...]:
        return COMPANY_KEYS


@dataclass(frozen=True)
class SuggestResult:
    ok: bool
    outcome: str
    reason: str = ""
    cli: str = ""
    run_id: str = ""
    added: tuple[Company, ...] = ()

    @property
    def companies(self) -> tuple[Company, ...]:
        return self.added

    def __iter__(self) -> Iterator[Company]:
        return iter(self.added)

    def __len__(self) -> int:
        return len(self.added)

    def __getitem__(self, index: int) -> Company:
        return self.added[index]


def companies_path() -> Path:
    """Return ~/.whyline/jobs/companies.toml without creating directories."""
    return paths.configured_home() / COMPANIES_FILE


def enabled_providers() -> builtins.list[str]:
    """Return runnable providers permitted by Settings."""
    return review.enabled_providers()


def _ensure_utf8(value: str, label: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CompanyError(f"{label} contains invalid Unicode text.") from error


def _company_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def validate_name(name: Any) -> str:
    """Validate that a company name is 1–80 printable characters."""
    if not isinstance(name, str):
        raise CompanyError("Company name must be a string.")
    _ensure_utf8(name, "Company name")
    if not name.isprintable():
        raise CompanyError("Company name must contain only printable characters.")
    cleaned = name.strip()
    if len(name) > MAX_NAME_LENGTH or not (1 <= len(cleaned) <= MAX_NAME_LENGTH):
        raise CompanyError(
            f"Company name must be 1 to {MAX_NAME_LENGTH} printable characters."
        )
    return cleaned


def validate_reason(reason: Any) -> str:
    """Validate that a company reason is printable text strictly under 300 characters."""
    if not isinstance(reason, str):
        raise CompanyError("Company reason must be a string.")
    _ensure_utf8(reason, "Company reason")
    if len(reason) >= MAX_REASON_CHARS:
        raise CompanyError(f"Company reason must be under {MAX_REASON_CHARS} characters.")
    collapsed = re.sub(r"[\r\n\t]+", " ", reason).strip()
    if not collapsed.isprintable():
        raise CompanyError("Company reason must contain only printable characters.")
    if len(collapsed) >= MAX_REASON_CHARS:
        raise CompanyError(f"Company reason must be under {MAX_REASON_CHARS} characters.")
    return collapsed


def validate_careers_url(url: Any) -> str:
    """Validate an https:// careers URL (or return '' when None)."""
    if url is None:
        return ""
    if not isinstance(url, str):
        raise CompanyError("careers_url must be an https:// URL string.")
    _ensure_utf8(url, "careers_url")
    cleaned = url.strip()
    if not cleaned:
        raise CompanyError("careers_url must be an https:// URL.")
    if len(cleaned) > MAX_URL_LENGTH:
        raise CompanyError(f"careers_url must be at most {MAX_URL_LENGTH} characters.")
    if not cleaned.isprintable() or any(ch.isspace() for ch in cleaned):
        raise CompanyError("careers_url must not contain whitespace or control characters.")
    try:
        parts = urllib.parse.urlsplit(cleaned)
        _ = parts.port
    except ValueError as error:
        raise CompanyError(f"Invalid careers_url: {error}") from error
    if parts.scheme.lower() != "https":
        raise CompanyError("careers_url must use https://.")
    if parts.username is not None or parts.password is not None:
        raise CompanyError("careers_url must not include credentials.")
    host = parts.hostname or ""
    if not host or host.startswith(".") or ".." in host:
        raise CompanyError("careers_url must include a valid host.")
    return urllib.parse.urlunsplit(
        ("https", parts.netloc, parts.path, parts.query, parts.fragment)
    )


def _validate_optional_field(value: Any, label: str, *, max_len: int = 512) -> str:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        value = value.isoformat()
    if not isinstance(value, str):
        raise CompanyError(f"{label} must be a string.")
    _ensure_utf8(value, label)
    if not value.isprintable() or len(value) > max_len:
        raise CompanyError(f"{label} must be printable text (at most {max_len} chars).")
    return value


def _validate_company_table(raw: Mapping[str, Any]) -> Company:
    if not isinstance(raw, Mapping):
        raise CompanyError("Each company in companies.toml must be a table.")
    if "name" not in raw:
        raise CompanyError("Company table in companies.toml is missing 'name'.")
    name = validate_name(raw["name"])

    status = raw.get("status", "suggested")
    if not isinstance(status, str) or status not in STATUSES:
        allowed = ", ".join(STATUSES)
        raise CompanyError(f"Company status must be one of: {allowed}.")

    reason = validate_reason(raw.get("reason", ""))

    ats = raw.get("ats", "unknown")
    if not isinstance(ats, str) or ats not in ATS_KINDS:
        allowed = ", ".join(ATS_KINDS)
        raise CompanyError(f"Company ats must be one of: {allowed}.")

    slug = _validate_optional_field(raw.get("slug", ""), "slug", max_len=200)

    raw_url = raw.get("careers_url", "")
    if not isinstance(raw_url, str):
        raise CompanyError("careers_url in companies.toml must be a string.")
    careers_url = validate_careers_url(raw_url) if raw_url != "" else ""

    added_by = raw.get("added_by", "user")
    if not isinstance(added_by, str) or added_by not in ADDED_BY_KINDS:
        allowed = ", ".join(ADDED_BY_KINDS)
        raise CompanyError(f"Company added_by must be one of: {allowed}.")

    checked_at = _validate_optional_field(raw.get("checked_at", ""), "checked_at", max_len=64)

    return Company(
        name=name,
        status=status,
        reason=reason,
        ats=ats,
        slug=slug,
        careers_url=careers_url,
        added_by=added_by,
        checked_at=checked_at,
    )


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_key(key: str) -> str:
    if key and _BARE_KEY_RE.match(key):
        return key
    return _toml_string(key)


def _render_companies(entries: Mapping[str, Company]) -> str:
    blocks: builtins.list[str] = []
    for key, item in entries.items():
        validated = _validate_company_table(item.to_dict())
        lines = [
            f"[{_toml_key(key)}]",
            f"name = {_toml_string(validated.name)}",
            f"status = {_toml_string(validated.status)}",
            f"reason = {_toml_string(validated.reason)}",
            f"ats = {_toml_string(validated.ats)}",
            f"slug = {_toml_string(validated.slug)}",
            f"careers_url = {_toml_string(validated.careers_url)}",
            f"added_by = {_toml_string(validated.added_by)}",
            f"checked_at = {_toml_string(validated.checked_at)}",
        ]
        blocks.append("\n".join(lines))
    rendered = ("\n\n".join(blocks) + "\n") if blocks else ""
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise CompanyError(f"Failed to serialise companies as TOML: {error}") from error
    return rendered


def _write_private_companies(entries: Mapping[str, Company]) -> Path:
    rendered = _render_companies(entries)
    _ensure_utf8(rendered, COMPANIES_FILE)
    try:
        folder = paths.home()
    except OSError as error:
        raise CompanyError(f"Could not prepare jobs folder: {error}") from error
    target = folder / COMPANIES_FILE
    if target.is_symlink():
        raise CompanyError(f"Refusing to overwrite symlink: {target}")
    fd, raw_tmp = tempfile.mkstemp(dir=folder, prefix=f".{COMPANIES_FILE}.", suffix=".tmp")
    tmp_path = Path(raw_tmp)
    try:
        if os.name != "nt":
            os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
        if target.is_symlink():
            raise CompanyError(f"Refusing to overwrite symlink: {target}")
        os.replace(tmp_path, target)
        if os.name != "nt":
            os.chmod(target, 0o600)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def _load_store() -> dict[str, Company]:
    target = companies_path()
    if not target.exists():
        return {}
    if target.is_symlink() or not target.is_file():
        raise CompanyError("companies.toml is not a regular file.")
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CompanyError(f"Could not read companies.toml: {error}") from error
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise CompanyError(f"companies.toml is not valid TOML: {error}") from error

    tables: builtins.list[Any]
    if builtins.list(parsed.keys()) == ["companies"] and isinstance(
        parsed["companies"], builtins.list
    ):
        tables = parsed["companies"]
    else:
        tables = builtins.list(parsed.values())

    store: dict[str, Company] = {}
    for raw_table in tables:
        company = _validate_company_table(raw_table)
        key = _company_key(company.name)
        if key in store:
            raise CompanyError(f"Duplicate company in companies.toml: {company.name}")
        store[key] = company
    return store


def parse_companies_block(text: str) -> builtins.list[Any]:
    """Extract and parse the fenced `companies` JSON list (capped at 40 entries)."""
    if not isinstance(text, str):
        raise CompanyError("Agent answer must be text.")
    _ensure_utf8(text, "Agent answer")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    found_body: str | None = None
    in_fence = False
    fence_char = ""
    fence_len = 0
    fence_tag = ""
    body_lines: builtins.list[str] = []

    for line in normalized.split("\n"):
        if not in_fence:
            match = _OPEN_FENCE_RE.match(line)
            if match is None:
                continue
            marker = match.group(1)
            info = match.group(2).strip()
            if marker[0] == "`" and "`" in info:
                continue
            tokens = info.split()
            in_fence = True
            fence_char = marker[0]
            fence_len = len(marker)
            fence_tag = tokens[0].lower() if tokens else ""
            body_lines = []
        else:
            stripped_leading = line.lstrip(" ")
            leading_spaces = len(line) - len(stripped_leading)
            if leading_spaces <= 3 and stripped_leading:
                run_len = len(stripped_leading) - len(stripped_leading.lstrip(fence_char))
                rest = stripped_leading[run_len:]
                if run_len >= fence_len and rest.strip(" \t") == "":
                    if fence_tag == "companies":
                        if found_body is not None:
                            raise CompanyError(
                                "Multiple fenced 'companies' blocks in agent answer."
                            )
                        found_body = "\n".join(body_lines)
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                    fence_tag = ""
                    body_lines = []
                    continue
            body_lines.append(line)

    if in_fence and fence_tag == "companies":
        raise CompanyError("Unclosed fenced 'companies' block in agent answer.")
    if found_body is None:
        raise CompanyError("Missing fenced 'companies' block in agent answer.")

    try:
        parsed = json.loads(found_body)
    except json.JSONDecodeError as error:
        raise CompanyError(
            f"Fenced 'companies' block is not valid JSON: {error.msg}."
        ) from error

    if not isinstance(parsed, builtins.list):
        raise CompanyError("Fenced 'companies' block must be a JSON list.")

    return parsed[:MAX_SUGGESTIONS]


def validate_suggestion_entry(raw: Any) -> Company:
    """Validate a single `{name, reason, careers_hint}` dict from the AI response."""
    if not isinstance(raw, Mapping):
        raise CompanyError("Company suggestion entry must be a JSON object.")
    if "name" not in raw:
        raise CompanyError("Company suggestion entry is missing 'name'.")
    if "reason" not in raw:
        raise CompanyError("Company suggestion entry is missing 'reason'.")

    name = validate_name(raw["name"])
    reason = validate_reason(raw["reason"])

    careers_hint = raw.get("careers_hint", "")
    if careers_hint is None or careers_hint == "":
        careers_url = ""
    elif isinstance(careers_hint, str):
        _ensure_utf8(careers_hint, "careers_hint")
        try:
            careers_url = validate_careers_url(careers_hint)
        except CompanyError:
            careers_url = ""
    else:
        raise CompanyError("careers_hint must be a string.")

    return Company(
        name=name,
        status="suggested",
        reason=reason,
        ats="unknown",
        slug="",
        careers_url=careers_url,
        added_by="ai",
        checked_at="",
    )


def parse_suggestions(text: str) -> builtins.list[Company]:
    """Parse a fenced `companies` answer and return unique valid suggested companies."""
    raw_items = parse_companies_block(text)
    seen: set[str] = set()
    valid: builtins.list[Company] = []
    for raw_item in raw_items:
        try:
            entry = validate_suggestion_entry(raw_item)
        except CompanyError:
            continue
        key = _company_key(entry.name)
        if key in seen:
            continue
        seen.add(key)
        valid.append(entry)
    return valid


def _find_or_create_agent() -> d.AgentDef:
    configured = paths.configured_home()
    try:
        default_jobs = Path.home() / ".whyline" / "jobs"
    except OSError:
        default_jobs = configured
    workdir = "~/.whyline/jobs" if configured == default_jobs else str(configured)

    for item in d.discover(None):
        if (
            isinstance(item, d.AgentDef)
            and item.kind == "personal"
            and item.name == AGENT_NAME
        ):
            return item
        if (
            isinstance(item, d.Broken)
            and item.kind == "personal"
            and item.path.stem == AGENT_NAME
        ):
            raise CompanyError(f"Agent definition {item.path.name} is invalid: {item.error}")

    try:
        jobs_dir = paths.home()
    except OSError as error:
        raise CompanyError(f"Could not prepare jobs folder: {error}") from error

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


def suggest(
    cli: str | None = None,
    *,
    progress: Callable[[str], None] | None = None,
    run_fn: Any = None,
) -> SuggestResult:
    """Run the `job-companies` agent via execute_once and store valid new suggestions."""
    enabled = enabled_providers()
    chosen: str | None = None
    if cli is not None:
        if not isinstance(cli, str) or not cli.strip():
            raise CompanyError("Provider CLI name must be a non-empty string.")
        chosen = cli.strip()
        if chosen not in d.CLIS or not capabilities.can_run(chosen):
            allowed = ", ".join(RUNNABLE_CLIS)
            raise CompanyError(f"Unsupported provider '{chosen}'. Choose one of: {allowed}.")
        if chosen not in enabled:
            return SuggestResult(
                ok=False,
                outcome="all_unavailable",
                reason=f"{chosen}: Enable {chosen} in Settings or choose another provider.",
            )
    elif not enabled:
        return SuggestResult(
            ok=False,
            outcome="all_unavailable",
            reason="No enabled AI provider can run agents. Enable Claude, Codex, or Grok in Settings.",
        )

    try:
        store = _load_store()
        defn = _find_or_create_agent()
        jobs_dir = paths.home()
    except (CompanyError, d.DefinitionError, OSError) as error:
        return SuggestResult(ok=False, outcome="failed", reason=str(error))

    if chosen is not None:
        run_defn = replace(defn, root=jobs_dir, runner=chosen, backup=())
    else:
        preferred = [c for c in (defn.runner, *defn.backup) if c in enabled]
        order = preferred if preferred else builtins.list(enabled)
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
        return SuggestResult(
            ok=False,
            outcome=outcome,
            reason=reason,
            cli=used_cli,
            run_id=run_id,
        )

    answer = _read_run_answer(record)
    try:
        candidates = parse_suggestions(answer)
    except CompanyError as error:
        return SuggestResult(
            ok=False,
            outcome="malformed_answer",
            reason=str(error),
            cli=used_cli,
            run_id=run_id,
        )

    newly_added: builtins.list[Company] = []
    for candidate in candidates:
        key = _company_key(candidate.name)
        if key in store:
            # Never overwrite a user entry, a removed company, or an already-listed entry.
            continue
        store[key] = candidate
        newly_added.append(candidate)

    if newly_added:
        try:
            _write_private_companies(store)
        except CompanyError as error:
            return SuggestResult(
                ok=False,
                outcome="failed",
                reason=str(error),
                cli=used_cli,
                run_id=run_id,
            )

    return SuggestResult(
        ok=True,
        outcome=outcome,
        reason=reason,
        cli=used_cli,
        run_id=run_id,
        added=tuple(newly_added),
    )


def add(name: str, careers_url: str | None = None) -> Company:
    """Add or update a user company entry as `accepted` (user entry wins over AI)."""
    clean_name = validate_name(name)
    validated_url = validate_careers_url(careers_url) if careers_url is not None else None

    store = _load_store()
    key = _company_key(clean_name)
    existing = store.get(key)

    if existing is None:
        entry = Company(
            name=clean_name,
            status="accepted",
            reason="",
            ats="unknown",
            slug="",
            careers_url=validated_url or "",
            added_by="user",
            checked_at="",
        )
    else:
        if existing.added_by == "user":
            final_url = validated_url if validated_url is not None else existing.careers_url
            reason_val = existing.reason
        else:
            final_url = validated_url or ""
            reason_val = ""
        same_url = final_url == existing.careers_url
        entry = Company(
            name=clean_name,
            status="accepted",
            reason=reason_val,
            ats=existing.ats if same_url else "unknown",
            slug=existing.slug if same_url else "",
            careers_url=final_url,
            added_by="user",
            checked_at=existing.checked_at if same_url else "",
        )

    store[key] = entry
    _write_private_companies(store)
    return entry


def accept(name: str) -> Company:
    """Mark an existing company in companies.toml as `accepted`."""
    clean_name = validate_name(name)
    store = _load_store()
    key = _company_key(clean_name)
    existing = store.get(key)
    if existing is None:
        raise CompanyError(f"Company not found: {clean_name}")
    updated = replace(existing, status="accepted")
    store[key] = updated
    _write_private_companies(store)
    return updated


def remove(name: str) -> Company:
    """Mark an existing company in companies.toml as `removed` so it is not re-suggested."""
    clean_name = validate_name(name)
    store = _load_store()
    key = _company_key(clean_name)
    existing = store.get(key)
    if existing is None:
        raise CompanyError(f"Company not found: {clean_name}")
    updated = replace(existing, status="removed")
    store[key] = updated
    _write_private_companies(store)
    return updated


def list(status: str | None = None) -> builtins.list[Company]:
    """Return all companies in companies.toml (optionally filtered by status)."""
    if status is not None:
        if not isinstance(status, str) or status not in STATUSES:
            allowed = ", ".join(STATUSES)
            raise CompanyError(f"Company status filter must be one of: {allowed}.")
    store = _load_store()
    items = builtins.list(store.values())
    if status is not None:
        return [item for item in items if item.status == status]
    return items
