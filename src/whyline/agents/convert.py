"""A report as an attachment (deliveries spec 4) and its summary (spec 5).

HTML comes from the `markdown` package. Word files come from
whyline.agents.docx, which keeps tables (macOS `textutil` drops them)."""
from __future__ import annotations

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


def to_docx(report_md: Path, out: Path) -> Path | None:
    """The report as Word, with real tables (whyline.agents.docx). None when
    the report can't be read or written; the caller attaches Markdown."""
    from whyline.agents import docx

    try:
        return docx.write(report_md.read_text(encoding="utf-8"), out)
    except Exception:
        out.unlink(missing_ok=True)
        return None


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
