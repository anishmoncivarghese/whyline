"""Refresh the bundled gitleaks rules from a release tag.

Developer-only: run by hand, never by whyline.

    uv run python scripts/update_secret_rules.py --ref v8.30.1

Writes `gitleaks.toml`, `LICENSE-gitleaks` and `VERSION` under
`src/whyline/security/rules/`. Everything is fetched and checked before any file
is touched, so a failed run leaves the bundled rules as they were.
"""

from __future__ import annotations

import argparse
import json
import tomllib
import urllib.request
from datetime import date
from pathlib import Path

REPO = "gitleaks/gitleaks"
RULES_DIR = Path(__file__).resolve().parent.parent / "src" / "whyline" / "security" / "rules"


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed https hosts
        return response.read().decode("utf-8")


def _release_date(ref: str) -> str:
    """The release's publish date, or today's if the tag has no release."""
    try:
        published = json.loads(_get(f"https://api.github.com/repos/{REPO}/releases/tags/{ref}"))
        return str(published["published_at"])[:10]
    except Exception:  # noqa: BLE001 - the date is informational only
        return date.today().isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", required=True, help="gitleaks release tag, e.g. v8.30.1")
    ref = parser.parse_args().ref

    raw = f"https://raw.githubusercontent.com/{REPO}/{ref}"
    config = _get(f"{raw}/config/gitleaks.toml")
    licence = _get(f"{raw}/LICENSE")
    if not tomllib.loads(config).get("rules"):
        raise SystemExit(f"{ref}: config/gitleaks.toml has no rules; nothing written")

    RULES_DIR.mkdir(parents=True, exist_ok=True)
    (RULES_DIR / "gitleaks.toml").write_text(config, encoding="utf-8")
    (RULES_DIR / "LICENSE-gitleaks").write_text(licence, encoding="utf-8")
    (RULES_DIR / "VERSION").write_text(f"{ref} {_release_date(ref)}\n", encoding="utf-8")
    print(f"bundled gitleaks {ref}")


if __name__ == "__main__":
    main()
