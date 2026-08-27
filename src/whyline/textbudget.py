"""Fence sanitising and token budgeting. Standard library only, by contract.

Every packet whyline hands to an agent is wrapped in a nonce fence, and the
content inside it is untrusted: it comes from `decisions.md`, which is committed
and therefore travels with a clone, and from a handoff written by some other
agent. This module owns the one definition of what a fence token looks like.

Owning it in one place is the point. C6, 2026-08-17, was a Critical: a note
containing the closing tag ended the fence early, so everything after it reached
the next agent's prompt *unlabelled*, and a reviewer demonstrated a fabricated
"SYSTEM:" directive escaping that way. The pattern was then copied into two
modules, which is how a security fix quietly becomes two security fixes that can
drift apart.

Kept dependency-free deliberately. `render` needs `clipped` for one line of
output, and it used to reach into `sync` for it — which dragged `brief`,
`handoff`, `ownership`, `state` and eight more modules into every `explain`,
`timeline` and `status` invocation, against a documented 200 ms cold-start
budget and against `render`'s own claim to have no import cost.
"""

from __future__ import annotations

import re
from math import ceil

# Any literal fence token appearing in content, in any casing or with stray
# whitespace, is neutralised before it can be emitted. `>?` is deliberate: a
# truncated tag must not survive to be completed by whatever follows it.
FENCE_TOKEN = re.compile(r"<\s*/?\s*whyline-(?:context|sync)[^>]*>?", re.IGNORECASE)

REDACTED = "[redacted-fence-token]"


def safe(value: object) -> str:
    """Strip anything that could close, reopen or forge the fence."""
    return FENCE_TOKEN.sub(REDACTED, str(value))


def clipped(value: object, limit: int = 120) -> str:
    """Sanitise, then bound the length.

    Sanitising first matters: clipping first could split a fence token into a
    fragment that no longer matches the pattern but still reassembles against
    adjacent text.
    """
    clean = safe(value)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def approximate_tokens(text: str) -> int:
    """Conservative, dependency-free token estimate used for hard budgets.

    Bytes over three, not a tokeniser. Every caller that reports a budget must
    describe it as approximate, because this will disagree with any real model's
    count.
    """
    return ceil(len(text.encode("utf-8")) / 3)
