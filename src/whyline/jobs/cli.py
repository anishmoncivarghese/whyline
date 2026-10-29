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

from whyline.jobs import paths, profile

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


_COMMANDS = {
    "profile": _cmd_profile,
}


def run(args: argparse.Namespace) -> int:
    command = getattr(args, "jobs_command", None)
    handler = _COMMANDS.get(command or "")
    if handler is None:
        print("usage: whyline jobs profile", file=sys.stderr)
        return EXIT_USAGE
    return handler(args)
