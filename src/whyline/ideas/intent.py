"""Route one inbox message without calling a model.

Buttons, commands, and a message made only of ``key: value`` settings are
decided here. A message that is plainly a new idea is captured. An
instruction such as "use grok to implement and give it an hour" stays
``free`` for the assistant.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

# Fuzzy order is part of the match. difflib breaks a tie by the later name,
# so this sequence stays stable.
COMMANDS = (
    "new",
    "list",
    "status",
    "run",
    "ask",
    "excel",
    "brainstorm",
    "plan",
    "stop",
    "drop",
    "help",
)
AGENTS = ("claude", "codex", "antigravity", "grok")
SETTING_KEYS = (
    "models",
    "passes",
    "final",
    "backup",
    "timeout",
    "repo",
    "implementer",
    "tester",
    "reviewer",
    "release",
    "drafter",
    "plan_reviewer",
)

_COMMAND_CUTOFF = 0.8
_AGENT_CUTOFF = 0.75
_COMMAND_SET = frozenset(COMMANDS)
_NO_ARG = frozenset({"new", "list", "excel", "help"})
_AGENT_SET = frozenset(AGENTS)
_SETTING_KEY_SET = frozenset(SETTING_KEYS)
_AGENT_LIST_KEYS = frozenset({"models", "backup"})
_ONE_AGENT_KEYS = frozenset({
    "final",
    "implementer",
    "tester",
    "reviewer",
    "drafter",
    "plan_reviewer",
})
# Checked before the fuzzy pass. "agy" is not within 0.75 of "antigravity".
_ALIASES = {
    "agy": "antigravity",
    "claud": "claude",
    "cluade": "claude",
    "codx": "codex",
    "grock": "grok",
}
_TIMEOUTS = frozenset({"15", "30", "45", "60", "none"})
# Verbs that, beside an agent name, address the inbox rather than describe
# an idea. "make" and "with" are omitted: "Make a grok plugin" is an idea.
_STRONG_OPS = frozenset({
    "use",
    "implement",
    "set",
    "change",
    "switch",
    "assign",
    "pick",
    "choose",
    "run",
})
# Rare outside a settings edit. "reviewer" and "passes" are ordinary words.
_CONTROL_WORDS = frozenset({"timeout", "implementer", "drafter", "plan_reviewer"})

_ID = re.compile(r"^[0-9]+$")
_REQ_CODE = re.compile(r"^[A-Za-z0-9]+$")
_REQ_ACTIONS = frozenset({"ok", "no"})
_SETTING_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*)$")
_SPLIT = re.compile(r"[\s,]+")
_WORD = re.compile(r"[A-Za-z]+")
_TIME = re.compile(
    r"\b(?:an?\s+hour|half\s+an\s+hour|\d+\s*(?:m|min|mins|minutes|h|hr|hrs|hours))\b",
    re.IGNORECASE,
)
_GIVE_IT = re.compile(r"\bgive\s+it\b", re.IGNORECASE)
_ALNUM = re.compile(r"[A-Za-z0-9]")


@dataclass(frozen=True)
class AgentWord:
    """One agent token from a settings value.

    ``name`` is the canonical agent, or None when nothing matched. ``raw``
    is the word as written, so an unknown such as ``banana`` stays visible.
    """

    raw: str
    name: str | None


@dataclass(frozen=True)
class Field:
    """One settings line.

    ``value`` is the normalised form. None means the value is not one this
    router accepts; ``raw`` still holds what was written.
    """

    raw: str
    value: str | int | AgentWord | tuple[AgentWord, ...] | None


_EMPTY_FIELDS: Mapping[str, Field] = MappingProxyType({})


@dataclass(frozen=True)
class Intent:
    """One routed message.

    ``fields`` is the settings map in the order the keys were written.
    ``args`` is the argument after a command, empty when none was given.
    """

    kind: str
    text: str = ""
    name: str = ""
    idea_id: int | None = None
    revision: int | None = None
    args: tuple[str, ...] = ()
    # A factory, not the proxy itself: Python 3.11 rejects any unhashable
    # dataclass default, and a mappingproxy is unhashable.
    fields: Mapping[str, Field] = field(default_factory=lambda: _EMPTY_FIELDS)
    request_id: int | None = None
    code: str = ""


def capture(text: str) -> Intent:
    return Intent(kind="capture", text=text)


def action(name: str, idea_id: int, revision: int) -> Intent:
    return Intent(kind="action", name=name, idea_id=idea_id, revision=revision)


def command(name: str, args: tuple[str, ...] = ()) -> Intent:
    return Intent(kind="command", name=name, args=tuple(args))


def settings(fields: Mapping[str, Field]) -> Intent:
    return Intent(kind="settings", fields=MappingProxyType(dict(fields)))


def answer(text: str) -> Intent:
    return Intent(kind="answer", text=text)


def free(text: str) -> Intent:
    return Intent(kind="free", text=text)


def request(name: str, request_id: int, code: str) -> Intent:
    return Intent(kind="request", name=name, request_id=request_id, code=code)


def normalise_agent(word: str) -> str | None:
    """Return the canonical agent for ``word``, or None.

    Aliases are exact. Anything else must be within cutoff 0.75 of
    ``claude``, ``codex``, ``antigravity``, or ``grok``.
    """
    token = _token(word)
    if not token:
        return None
    if token in _ALIASES:
        return _ALIASES[token]
    if token in _AGENT_SET:
        return token
    match = difflib.get_close_matches(token, AGENTS, n=1, cutoff=_AGENT_CUTOFF)
    return match[0] if match else None


def route(
    text: str | None,
    callback_data: str | None,
    *,
    open_question: object,
) -> Intent:
    """Route one message.

    A non-empty callback is parsed exactly as ``action:idea_id:revision``,
    or as ``req:ok|no:request_id:code`` for a request card, and wins over
    the text. Then a command, then a settings message, then a reply to an
    open question. What remains is ``capture`` when it is plainly an idea,
    and ``free`` when it is an instruction.
    """
    if callback_data:
        parsed = _callback(callback_data)
        return parsed if parsed is not None else free(callback_data)
    body = "" if text is None else str(text).strip()
    if not body:
        return free("")
    parsed = _command(body)
    if parsed is not None:
        return parsed
    parsed = _settings(body)
    if parsed is not None:
        return parsed
    if open_question and _ALNUM.search(body):
        return answer(body)
    if _is_instruction(body):
        return free(body)
    return capture(body)


def _token(word: str) -> str:
    return word.strip().lower().strip(".,;:!?\"'`()[]{}")


def _callback(data: str) -> Intent | None:
    parts = data.split(":")
    if len(parts) == 4 and parts[0] == "req":
        _, name, request_s, code = parts
        if name not in _REQ_ACTIONS:
            return None
        if _ID.fullmatch(request_s) is None:
            return None
        if _REQ_CODE.fullmatch(code) is None:
            return None
        return request(name, int(request_s), code.lower())
    if len(parts) != 3:
        return None
    name, idea_s, rev_s = parts
    if not name or any(ch.isspace() for ch in name):
        return None
    if _ID.fullmatch(idea_s) is None or _ID.fullmatch(rev_s) is None:
        return None
    return action(name, int(idea_s), int(rev_s))


def _command(body: str) -> Intent | None:
    parts = body.split()
    if not parts:
        return None
    name = _command_name(parts[0])
    if name is None:
        return None
    args = parts[1:]
    # Run is deliberately strict, but all of its trailing text still reaches
    # the command handler so it can give the deterministic refusal instead of
    # sending an ad-hoc prompt through the assistant.
    if name in {"run", "ask"}:
        return command(name, tuple(args))
    # Every other command is one line. A newline means prose or settings.
    if "\n" in body or "\r" in body:
        return None
    if name in _NO_ARG:
        if args:
            return None
        return command(name, ())
    # Brainstorm, plan, and stop take an optional id. `/drop <id>` requires
    # one. A bare "drop", or any other extra word, is prose.
    if name == "drop":
        if len(args) == 1 and _ID.fullmatch(args[0]) is not None:
            return command(name, (args[0],))
        return None
    # Status also addresses saved agents and the relay. Its existing empty and
    # numeric forms still mean the latest idea and an explicit idea id.
    if name == "status":
        if len(args) <= 1:
            return command(name, tuple(args))
        return None
    if len(args) > 1 or (len(args) == 1 and _ID.fullmatch(args[0]) is None):
        return None
    return command(name, tuple(args))


def _command_name(token: str) -> str | None:
    word = token[1:] if token.startswith("/") else token
    word = word.lower()
    if not word:
        return None
    if word in _COMMAND_SET:
        return word
    match = difflib.get_close_matches(word, COMMANDS, n=1, cutoff=_COMMAND_CUTOFF)
    return match[0] if match else None


def _settings(body: str) -> Intent | None:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return None
    rows: list[tuple[str, str]] = []
    known = 0
    for line in lines:
        match = _SETTING_LINE.match(line)
        if match is None:
            return None
        key = match.group(1).lower()
        raw = match.group(2).strip()
        if key in _SETTING_KEY_SET:
            known += 1
        rows.append((key, raw))
    if known == 0:
        # "Idea: a bot that files receipts" is prose that happens to use a colon.
        return None
    if known != len(rows):
        # A real settings key beside an unknown one is a broken edit, not a new idea.
        return free(body)
    fields: dict[str, Field] = {}
    for key, raw in rows:
        fields[key] = _field(key, raw)
    return settings(fields)


def _field(key: str, raw: str) -> Field:
    if key in _AGENT_LIST_KEYS:
        return Field(raw=raw, value=_agent_list(raw))
    if key in _ONE_AGENT_KEYS or key == "release":
        return Field(raw=raw, value=_one_agent(raw, human=key == "release"))
    if key == "timeout":
        return Field(raw=raw, value=_timeout(raw))
    if key == "passes":
        return Field(raw=raw, value=_passes(raw))
    return Field(raw=raw, value=raw)


def _agent_list(raw: str) -> tuple[AgentWord, ...]:
    text = raw.strip()
    if not text or text.lower() == "none":
        return ()
    words = [word for word in _SPLIT.split(text) if word]
    return tuple(AgentWord(word, normalise_agent(word)) for word in words)


def _one_agent(raw: str, *, human: bool) -> AgentWord | None:
    words = [word for word in _SPLIT.split(raw.strip()) if word]
    if len(words) != 1:
        return None
    word = words[0]
    if human and word.lower() == "human":
        return AgentWord(word, "human")
    return AgentWord(word, normalise_agent(word))


def _timeout(raw: str) -> str | None:
    token = "".join(raw.split()).lower()
    if token.endswith("m") and token[:-1] in _TIMEOUTS:
        token = token[:-1]
    if token in _TIMEOUTS:
        return token
    return None


def _passes(raw: str) -> int | None:
    if raw.isascii() and raw.isdigit():
        return int(raw)
    return None


def _is_instruction(text: str) -> bool:
    """True when the text tells the inbox what to do.

    Agent words here are exact names and aliases only. The 0.75 fuzzy
    pass is for a settings token, where the user meant an agent.
    Scanning prose with it would read the word "code" as Codex.
    """
    words = [word.lower() for word in _WORD.findall(text)]
    if not words:
        return True
    mentions_agent = any(_exact_agent(word) for word in words)
    strong = bool(_STRONG_OPS.intersection(words))
    if mentions_agent and strong:
        return True
    if _GIVE_IT.search(text) and _TIME.search(text):
        return True
    if _CONTROL_WORDS.intersection(words) and (mentions_agent or strong or _TIME.search(text)):
        return True
    if len(words) == 1 and mentions_agent:
        return True
    return False


def _exact_agent(word: str) -> bool:
    token = _token(word)
    return token in _AGENT_SET or token in _ALIASES
