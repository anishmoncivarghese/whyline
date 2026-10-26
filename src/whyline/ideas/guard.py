"""Content guard for untrusted input such as forwarded email (ASST-14).

Strips HTML tags, comments, zero-width and bidi control characters, and
CSS-hidden blocks. Collapses whitespace, caps at 20,000 characters, and flags
lines that address an AI or give orders.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

MAX_LENGTH = 20_000

_ZERO_WIDTH_CHARS = frozenset({
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\ufeff",  # zero-width no-break space / BOM
    "\u2060",  # word joiner
    "\u180e",  # mongolian vowel separator
    "\u00ad",  # soft hyphen
})

_AI_ADDRESS_RE = re.compile(
    r"(?:"
    r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\b"
    r"|\bdisregard\s+(?:all\s+|any\s+)?(?:previous|prior|above)\b"
    r"|\bforget\s+(?:all\s+|any\s+)?(?:previous|prior|above)\b"
    r"|\byou\s+are\s+now\b"
    r"|\byou\s+are\s+an?\b"
    r"|\bact\s+as\s+(?:an?|a)\b"
    r"|\bpretend\s+(?:you\s+are|to\s+be)\b"
    r"|\bsystem\s+prompt\b"
    r"|\bas\s+an?\s+ai\b"
    r"|\bas\s+a\s+language\s+model\b"
    r"|\b(?:system|assistant|developer)\s*:"
    r"|\b(?:override|new)\s+instructions?\b"
    r")",
    re.IGNORECASE,
)

_ORDER_RE = re.compile(
    r"(?:"
    r"^[>\-*•#]*\s*(?:\d+[\.)]\s*)?(?:please\s+|kindly\s+|now\s+)?(?:run|execute|send|forward|delete|remove|stop|cancel|drop|destroy|wipe)\b"
    r"|\b(?:must|need to|want you to|order you to|command you to)\s+(?:run|execute|send|forward|delete|remove|stop|cancel|drop|destroy)\b"
    r")",
    re.IGNORECASE,
)


class _HiddenStripper(HTMLParser):
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    BLOCK_TAGS = {
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr",
        "blockquote", "section", "article", "header", "footer",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        style = (attrs_dict.get("style") or "").lower()
        is_hidden = (
            tag in {"style", "script", "head", "title"}
            or "hidden" in attrs_dict
            or bool(re.search(r"display\s*:\s*none", style))
            or bool(re.search(r"visibility\s*:\s*hidden", style))
        )
        if self.hidden_depth > 0:
            if tag not in self.VOID_TAGS:
                self.hidden_depth += 1
        elif is_hidden:
            if tag not in self.VOID_TAGS:
                self.hidden_depth = 1
        else:
            if tag == "br":
                self.output.append("\n")
            elif tag in self.BLOCK_TAGS:
                self.output.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden_depth > 0:
            self.hidden_depth -= 1
        elif tag in self.BLOCK_TAGS:
            self.output.append("\n")

    def handle_data(self, data: str) -> None:
        if self.hidden_depth == 0:
            self.output.append(data)

    def handle_comment(self, data: str) -> None:
        pass


def _strip_zero_width_and_bidi(text: str) -> str:
    cleaned = []
    for ch in text:
        if ch in _ZERO_WIDTH_CHARS:
            continue
        if "\u200e" <= ch <= "\u200f" or "\u202a" <= ch <= "\u202e" or "\u2066" <= ch <= "\u2069":
            continue
        if unicodedata.category(ch) == "Cf":
            continue
        cleaned.append(ch)
    return "".join(cleaned)


def _strip_html(text: str) -> str:
    # First, quick check if text contains HTML elements or entities
    if "<" not in text and "&" not in text:
        return text
    stripper = _HiddenStripper()
    try:
        stripper.feed(text)
        stripper.close()
        return "".join(stripper.output)
    except Exception:
        # Fallback to regex
        clean = re.sub(r"<!--[\s\S]*?-->", "", text)
        clean = re.sub(r"<(style|script|head)[\s\S]*?</\1>", "", clean, flags=re.IGNORECASE)
        clean = re.sub(
            r"<[a-zA-Z0-9]+[^>]*?(?:style\s*=\s*['\"][^'\"]*?\b(?:display\s*:\s*none|visibility\s*:\s*hidden)\b|hidden)[^>]*?>[\s\S]*?</[a-zA-Z0-9]+>",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"<[^>]+>", " ", clean)
        return clean


def _is_flagged_line(line: str) -> bool:
    clean_line = line.strip()
    if not clean_line:
        return False
    return bool(_AI_ADDRESS_RE.search(clean_line) or _ORDER_RE.search(clean_line))


def clean(text: str) -> tuple[str, list[str]]:
    """Clean untrusted text and return (clean_text, flagged_lines).

    - Strips HTML tags, comments, zero-width and bidi control characters,
      and CSS-hidden blocks.
    - Collapses whitespace.
    - Caps the result at 20,000 characters.
    - Flags (keeps but marks with ``[flagged]``) lines that address an AI
      or give orders.
    """
    if not text:
        return "", []

    # 1. Strip HTML tags, comments, and CSS-hidden blocks
    text = _strip_html(text)

    # 2. Strip zero-width and bidi control characters
    text = _strip_zero_width_and_bidi(text)

    # 3. Collapse whitespace within lines and between lines
    lines: list[str] = []
    for raw_line in text.splitlines():
        collapsed = re.sub(r"[ \t]+", " ", raw_line).strip()
        if collapsed:
            lines.append(collapsed)
        elif lines and lines[-1] != "":
            lines.append("")
    collapsed_text = "\n".join(lines).strip()

    # Cap at MAX_LENGTH before processing lines if excessively long
    if len(collapsed_text) > MAX_LENGTH:
        collapsed_text = collapsed_text[:MAX_LENGTH]

    # 4. Flag lines that address an AI or give orders
    flags: list[str] = []
    output_lines: list[str] = []
    for line in collapsed_text.splitlines():
        if _is_flagged_line(line):
            flags.append(line)
            if line.startswith("[flagged]"):
                output_lines.append(line)
            else:
                output_lines.append(f"[flagged] {line}")
        else:
            output_lines.append(line)

    clean_text = "\n".join(output_lines)
    if len(clean_text) > MAX_LENGTH:
        clean_text = clean_text[:MAX_LENGTH]

    return clean_text, flags
