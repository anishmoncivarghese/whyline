"""`whyline jobs`: personal job-search profile, companies, and shortlist CLI."""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from whyline.jobs import companies, paths, profile, review

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

_LIST_KEYS = frozenset({"roles", "locations", "languages", "deal_breakers"})


def tilde_path(path: Path) -> str:
    """Render paths under the home directory with a leading `~`."""
    try:
        resolved = Path(path).expanduser().resolve()
        home = Path.home().expanduser().resolve()
    except OSError:
        resolved = Path(path)
        home = Path.home()
    shown = resolved.as_posix()
    home_s = home.as_posix().rstrip("/")
    if shown == home_s:
        return "~"
    if home_s and shown.startswith(home_s + "/"):
        return "~" + shown[len(home_s):]
    return shown


def format_list_preference(items: list[str]) -> str:
    """Format a string list for display/editing while keeping commas/spaces round-trippable."""
    if not items:
        return ""
    if any("," in item or "\n" in item or item != item.strip() or not item for item in items):
        return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in items) + "]"
    return ", ".join(items)


def parse_preference_value(key: str, raw: str) -> Any:
    """Parse a string input into the typed value expected by `profile.save_preferences`."""
    if key not in profile.KNOWN_PREFERENCE_KEYS:
        allowed = ", ".join(profile.KNOWN_PREFERENCE_KEYS)
        raise profile.ProfileError(
            f"Unknown preference key '{key}'. Choose one of: {allowed}."
        )
    if key in _LIST_KEYS:
        stripped = raw.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = tomllib.loads(f"v = {stripped}")["v"]
            except tomllib.TOMLDecodeError as error:
                raise profile.ProfileError(
                    f"Invalid list syntax for {key}: {error}"
                ) from error
            return parsed
        return [item.strip() for item in re.split(r"[,\n]", raw) if item.strip()]
    if key == "salary_min":
        stripped = raw.strip()
        if not stripped or re.fullmatch(r"[+-]?\d+", stripped) is None:
            raise profile.ProfileError("salary_min must be a whole number.")
        return int(stripped, 10)
    if key in ("remote", "seniority", "currency"):
        return raw.strip()
    return raw


def _format_size(size_bytes: int) -> str:
    noun = "byte" if size_bytes == 1 else "bytes"
    return f"{size_bytes} {noun}"


def _format_timestamp(moment: datetime.datetime | None) -> str:
    if moment is None:
        return ""
    utc = moment.astimezone(datetime.timezone.utc)
    return utc.strftime("%Y-%m-%d %H:%M UTC")


def format_cv_status(statuses: Mapping[str, profile.FileStatus]) -> str:
    """One-line CV status shared by the CLI and the Jobs profile screen."""
    entry = statuses.get(profile.CV_FILE)
    if entry is None or not entry.exists:
        return "CV: not imported yet"
    parts = [tilde_path(entry.path), _format_size(entry.size_bytes)]
    stamp = _format_timestamp(entry.modified_at)
    if stamp:
        parts.append(f"updated {stamp}")
    return f"CV: present ({' · '.join(parts)})"


def _format_file_entry(name: str, entry: profile.FileStatus | None) -> str:
    if entry is None or not entry.exists:
        return "not imported" if name == profile.CV_FILE else "missing"
    parts = [_format_size(entry.size_bytes)]
    stamp = _format_timestamp(entry.modified_at)
    if stamp:
        parts.append(f"updated {stamp}")
    return f"present ({', '.join(parts)})"


def _format_pref_display(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value if value else "(none)"
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return value


def add_parser(subparsers: "argparse._SubParsersAction") -> None:
    parser = subparsers.add_parser(
        "jobs",
        help="Personal job search: profile, companies, shortlist",
    )
    jobs_sub = parser.add_subparsers(dest="jobs_command", required=True)

    prof = jobs_sub.add_parser(
        "profile",
        help="Show or update your CV and job preferences",
    )
    prof_sub = prof.add_subparsers(dest="jobs_profile_command", required=True)

    show = prof_sub.add_parser("show", help="Show CV status and preferences")
    show.add_argument("--json", action="store_true", help="Machine-readable output")

    imp = prof_sub.add_parser(
        "import-cv",
        help="Import a CV (.md, .txt, .docx, or - for stdin)",
    )
    imp.add_argument("file", help="Path to CV file, or - to read UTF-8 text from stdin")

    set_p = prof_sub.add_parser("set", help="Set a preference value")
    set_p.add_argument("key", help="Preference key")
    set_p.add_argument("value", help="Preference value")

    rev = jobs_sub.add_parser(
        "review",
        help="Review your CV and draft profile.draft.md and rubric.draft.md",
    )
    rev.add_argument(
        "--cli",
        default=None,
        help="AI provider CLI to run (default: first enabled)",
    )
    rev_sub = rev.add_subparsers(dest="jobs_review_command", required=False)
    rev_sub.add_parser(
        "accept",
        help="Accept profile.draft.md and rubric.draft.md into profile.md and rubric.md",
    )

    comp = jobs_sub.add_parser(
        "companies",
        help="Manage tracked companies and AI company suggestions",
    )
    comp_sub = comp.add_subparsers(dest="jobs_companies_command", required=True)

    comp_list = comp_sub.add_parser("list", help="List companies in companies.toml")
    comp_list.add_argument(
        "--status",
        choices=companies.STATUSES,
        default=None,
        help="Filter by company status",
    )
    comp_list.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output",
    )

    comp_sug = comp_sub.add_parser(
        "suggest",
        help="Suggest matching companies from your profile and preferences",
    )
    comp_sug.add_argument(
        "--cli",
        default=None,
        help="AI provider CLI to run (default: first enabled)",
    )

    comp_add = comp_sub.add_parser("add", help="Add a company to track")
    comp_add.add_argument("name", help="Company name")
    comp_add.add_argument(
        "careers_url_pos",
        nargs="?",
        default=None,
        metavar="careers_url",
        help="Optional https:// careers page URL",
    )
    comp_add.add_argument(
        "--careers-url",
        "--url",
        dest="careers_url_opt",
        default=None,
        help="Optional https:// careers page URL",
    )

    comp_acc = comp_sub.add_parser("accept", help="Accept a suggested company")
    comp_acc.add_argument("name", help="Company name")

    comp_rem = comp_sub.add_parser(
        "remove",
        help="Remove a company so it is not tracked or re-suggested",
    )
    comp_rem.add_argument("name", help="Company name")


def _read_stdin_cv() -> str:
    max_raw_bytes = profile.MAX_CV_BYTES * 2 + 3
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        try:
            raw = buffer.read(max_raw_bytes + 1)
        except OSError as error:
            raise profile.ProfileError(f"Could not read CV from stdin: {error}") from error
        if len(raw) > max_raw_bytes:
            raise profile.ProfileError("CV is over the 200 KB text limit.")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise profile.ProfileError("CV from stdin must be UTF-8 text.") from error
    else:
        try:
            text = sys.stdin.read(max_raw_bytes + 1)
        except (OSError, UnicodeDecodeError) as error:
            raise profile.ProfileError("CV from stdin must be UTF-8 text.") from error
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def _cmd_profile_show(args: argparse.Namespace) -> int:
    try:
        statuses = profile.status()
        prefs = profile.load_preferences()
    except profile.ProfileError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR

    if getattr(args, "json", False):
        payload = {
            "files": {
                name: {
                    "path": tilde_path(st.path),
                    "exists": st.exists,
                    "size_bytes": st.size_bytes,
                    "modified_at": st.modified_at.isoformat() if st.modified_at else None,
                }
                for name, st in statuses.items()
            },
            "preferences": _json_safe(prefs),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return EXIT_OK

    print(f"Files ({tilde_path(paths.configured_home())})")
    for name in profile.MANAGED_FILES:
        print(f"  {name:<18} {_format_file_entry(name, statuses.get(name))}")
    print("\nPreferences")
    ordered_keys = list(profile.KNOWN_PREFERENCE_KEYS) + [
        k for k in prefs if k not in profile.KNOWN_PREFERENCE_KEYS
    ]
    for key in ordered_keys:
        print(f"  {key:<18} {_format_pref_display(prefs[key])}")
    return EXIT_OK


def _cmd_profile_import_cv(args: argparse.Namespace) -> int:
    try:
        if args.file == "-":
            target = profile.import_cv_text(_read_stdin_cv())
        else:
            target = profile.import_cv(args.file)
    except profile.ProfileError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    shown = tilde_path(target) if isinstance(target, Path) else "~/.whyline/jobs/cv.md"
    print(f"Imported CV to {shown}.")
    return EXIT_OK


def _cmd_profile_set(args: argparse.Namespace) -> int:
    try:
        parsed = parse_preference_value(args.key, args.value)
        saved = profile.save_preferences({args.key: parsed})
    except profile.ProfileError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    shown_val = _format_pref_display(saved[args.key] if isinstance(saved, Mapping) and args.key in saved else parsed)
    print(f"Saved {args.key} = {shown_val} ({tilde_path(profile.preferences_path())}).")
    return EXIT_OK


_PROFILE_COMMANDS = {
    "show": _cmd_profile_show,
    "import-cv": _cmd_profile_import_cv,
    "set": _cmd_profile_set,
}


def _cmd_profile(args: argparse.Namespace) -> int:
    sub = getattr(args, "jobs_profile_command", None)
    handler = _PROFILE_COMMANDS.get(sub or "")
    if handler is None:
        print("usage: whyline jobs profile show|import-cv|set", file=sys.stderr)
        return EXIT_USAGE
    return handler(args)


def _cmd_review_run(args: argparse.Namespace) -> int:
    try:
        result = review.run(
            cli=getattr(args, "cli", None),
            progress=lambda line: print(f"· {line}"),
        )
    except (review.ReviewError, profile.ProfileError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR

    if not result.ok:
        detail = f"{result.outcome}: {result.reason}" if result.reason else result.outcome
        print(detail, file=sys.stderr)
        return EXIT_ERROR

    p_shown = (
        tilde_path(result.profile_draft_path)
        if isinstance(result.profile_draft_path, Path)
        else "~/.whyline/jobs/profile.draft.md"
    )
    r_shown = (
        tilde_path(result.rubric_draft_path)
        if isinstance(result.rubric_draft_path, Path)
        else "~/.whyline/jobs/rubric.draft.md"
    )
    print(f"Wrote {p_shown} and {r_shown} ({result.outcome}).")
    print("Review or edit the drafts, then run `whyline jobs review accept`.")
    return EXIT_OK


def _cmd_review_accept(args: argparse.Namespace) -> int:
    if getattr(args, "cli", None) is not None:
        print("`whyline jobs review accept` does not take --cli.", file=sys.stderr)
        return EXIT_USAGE
    try:
        prof_path, rub_path = review.accept()
    except (review.ReviewError, profile.ProfileError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    p_shown = (
        tilde_path(prof_path)
        if isinstance(prof_path, Path)
        else "~/.whyline/jobs/profile.md"
    )
    r_shown = (
        tilde_path(rub_path)
        if isinstance(rub_path, Path)
        else "~/.whyline/jobs/rubric.md"
    )
    print(f"Accepted {p_shown} and {r_shown}.")
    return EXIT_OK


def _cmd_review(args: argparse.Namespace) -> int:
    sub = getattr(args, "jobs_review_command", None)
    if sub in (None, ""):
        return _cmd_review_run(args)
    if sub == "accept":
        return _cmd_review_accept(args)
    print("usage: whyline jobs review [accept]", file=sys.stderr)
    return EXIT_USAGE


def _cmd_companies_list(args: argparse.Namespace) -> int:
    status_filter = getattr(args, "status", None)
    try:
        rows = companies.list(status=status_filter)
    except (companies.CompanyError, profile.ProfileError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR

    if getattr(args, "json", False):
        print(json.dumps([row.to_dict() for row in rows], indent=2, ensure_ascii=False))
        return EXIT_OK

    shown_path = tilde_path(companies.companies_path())
    if not rows:
        if status_filter:
            print(f"No companies with status '{status_filter}' ({shown_path}).")
        else:
            print(f"No companies ({shown_path}).")
        return EXIT_OK

    print(f"Companies ({shown_path})")
    name_w = max(4, *(len(row.name) for row in rows))
    for row in rows:
        details: list[str] = []
        if row.reason:
            details.append(row.reason)
        if row.careers_url:
            details.append(row.careers_url)
        tail = f"  {' — '.join(details)}" if details else ""
        print(
            f"  {row.name:<{name_w}}  {row.status:<9}  {row.ats:<15}  {row.added_by:<4}{tail}"
        )
    return EXIT_OK


def _cmd_companies_suggest(args: argparse.Namespace) -> int:
    try:
        result = companies.suggest(
            cli=getattr(args, "cli", None),
            progress=lambda line: print(f"· {line}"),
        )
    except (companies.CompanyError, profile.ProfileError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR

    if not result.ok:
        detail = f"{result.outcome}: {result.reason}" if result.reason else result.outcome
        print(detail, file=sys.stderr)
        return EXIT_ERROR

    shown_path = tilde_path(companies.companies_path())
    if not result.added:
        print(f"Added 0 new companies ({result.outcome}).")
        return EXIT_OK

    noun = "company" if len(result.added) == 1 else "companies"
    print(f"Added {len(result.added)} suggested {noun} to {shown_path} ({result.outcome}):")
    for item in result.added:
        suffix = f" — {item.reason}" if item.reason else ""
        print(f"  - {item.name}{suffix}")
    return EXIT_OK


def _cmd_companies_add(args: argparse.Namespace) -> int:
    pos_url = getattr(args, "careers_url_pos", None)
    opt_url = getattr(args, "careers_url_opt", None)
    if pos_url is not None and opt_url is not None and pos_url != opt_url:
        print("Provide careers_url once (positional or --careers-url).", file=sys.stderr)
        return EXIT_USAGE
    careers_url = opt_url if opt_url is not None else pos_url
    try:
        entry = companies.add(args.name, careers_url=careers_url)
    except (companies.CompanyError, profile.ProfileError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR

    shown_path = tilde_path(companies.companies_path())
    url_part = f" ({entry.careers_url})" if entry.careers_url else ""
    print(f"Added {entry.name}{url_part} [{entry.status}] to {shown_path}.")
    return EXIT_OK


def _cmd_companies_accept(args: argparse.Namespace) -> int:
    try:
        entry = companies.accept(args.name)
    except (companies.CompanyError, profile.ProfileError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print(f"Accepted {entry.name} ({tilde_path(companies.companies_path())}).")
    return EXIT_OK


def _cmd_companies_remove(args: argparse.Namespace) -> int:
    try:
        entry = companies.remove(args.name)
    except (companies.CompanyError, profile.ProfileError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print(f"Removed {entry.name} ({tilde_path(companies.companies_path())}).")
    return EXIT_OK


_COMPANIES_COMMANDS = {
    "list": _cmd_companies_list,
    "suggest": _cmd_companies_suggest,
    "add": _cmd_companies_add,
    "accept": _cmd_companies_accept,
    "remove": _cmd_companies_remove,
}


def _cmd_companies(args: argparse.Namespace) -> int:
    sub = getattr(args, "jobs_companies_command", None)
    handler = _COMPANIES_COMMANDS.get(sub or "")
    if handler is None:
        print(
            "usage: whyline jobs companies list|suggest|add|accept|remove",
            file=sys.stderr,
        )
        return EXIT_USAGE
    return handler(args)


_COMMANDS = {
    "profile": _cmd_profile,
    "review": _cmd_review,
    "companies": _cmd_companies,
}


def run(args: argparse.Namespace) -> int:
    command = getattr(args, "jobs_command", None)
    handler = _COMMANDS.get(command or "")
    if handler is None:
        print("usage: whyline jobs profile|review|companies", file=sys.stderr)
        return EXIT_USAGE
    return handler(args)
