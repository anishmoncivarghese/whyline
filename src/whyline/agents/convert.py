"""A report as an attachment (deliveries spec 4) and its summary (spec 5).

Markdown → HTML with the `markdown` package, then HTML → Word with macOS
`textutil`. Without textutil (Linux, Windows) the caller attaches the
Markdown instead."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import markdown

_STYLE = (
    "body{font-family:sans-serif;font-size:10pt}"
    "table{border-collapse:collapse}"
    "td,th{border:1px solid #999;padding:3px;vertical-align:top}"
    "th{background:#eee}"
)


def to_html(text: str) -> str:
    body = markdown.markdown(text, extensions=["tables"])
    return (
        "<html><head><meta charset='utf-8'><style>" + _STYLE
        + "</style></head><body>" + body + "</body></html>"
    )


def to_docx(report_md: Path, out: Path, *, run=subprocess.run, which=shutil.which) -> Path | None:
    if which("textutil") is None:
        return None
    page = out.with_suffix(".html")
    page.write_text(to_html(report_md.read_text(encoding="utf-8")), encoding="utf-8")
    try:
        result = run(
            ["textutil", "-convert", "docx", str(page), "-output", str(out)],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        page.unlink(missing_ok=True)
    if result.returncode != 0 or not out.is_file():
        return None
    return out


def summary(text: str, limit: int = 1000) -> str:
    """The report from the top down to its first table or fenced block."""
    head = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("|", "```", "~~~")):
            break
        head.append(line)
    chosen = "\n".join(head).strip() or text.strip()
    if len(chosen) > limit:
        cut = chosen[:limit]
        newline = cut.rfind("\n")
        chosen = cut[:newline] if newline > 0 else cut
    return chosen.rstrip() + "\n\nFull report attached."
