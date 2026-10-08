# Agent deliveries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this project the plan is run by whyline-relay, one relay task per plan task (`plans/agent-deliveries.plan.md`). Task 9 is a release, done by a person.

**Goal:** After every agent run, whyline itself sends the result to the agent's chosen destinations — email through the Mail app, a Telegram chat, and an optional command — with a Word attachment and a short summary, or a short alert when the run failed.

**Architecture:** Delivery settings live per Mac in `~/.whyline/agents/deliveries.toml` (`deliveries.py`). After `after.finish` updates state, `deliver.after_run` builds the attachment (`convert.py`), sends through `mail_send.py` and `telegram.py`, runs the command, and records each result on the run (`RunRecord.deliveries`). The CLI (`whyline agents deliver|telegram|resend`) and the console (a "Deliver to" form section, a Telegram setup screen, delivery status and Resend in Runs) sit on top.

**Tech Stack:** Python 3.11+ (stdlib `urllib`, `tomllib`, `subprocess`), the `markdown` package (new dependency), macOS `textutil`, `osascript` and `security`, Textual 0.89.1, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-08-agent-deliveries-design.md`

## Global Constraints

- Repository: `~/agentdock` (whyline). No whyline-relay changes.
- One new dependency: `markdown>=3.5,<4` in `pyproject.toml` `dependencies`. Nothing else new.
- Delivery settings are per Mac in `~/.whyline/agents/deliveries.toml`, created `0o600`, keyed by agent id. Never written into an agent's own TOML file.
- The Telegram bot token is stored in the macOS Keychain (service `whyline-telegram`, account `bot-token`) via `security`; off macOS in `~/.whyline/agents/telegram-token` (`0o600`). It is never written to a log, run record, history or error text; errors replace it with `•••`.
- Known Telegram chats: `~/.whyline/agents/telegram-chats.toml` (`0o600`).
- Telegram messages are plain text: never send `parse_mode`. Captions are cut to 1,024 characters.
- Attachment formats: `docx` (default) and `md`. No PDF.
- Subject: `"<subject> — <YYYY-MM-DD>"`; alerts `"<subject> failed — <YYYY-MM-DD>"`; `<subject>` is the agent's `subject` setting or its label; the date is the run's start date. `subject` is one line of at most 120 characters.
- Delivery never changes a run's outcome and never raises out of `deliver.after_run`.
- `skipped` and `missed` outcomes send nothing.
- The advanced command runs only from `deliveries.toml`, with a 2-minute timeout, stdin closed, output saved as `command.log` in the run folder.
- Tests never use the network, Mail, the Keychain, `textutil`, `osascript` or a real Telegram bot (stub them), never touch the real home folder (`HOME` → `tmp_path`), contain no `/Users/` paths, check POSIX permission bits only when `os.name != "nt"`, write paths into hand-made TOML with `json.dumps`, and press console buttons by widget with condition-based waits. They pass on macOS, Linux and Windows.
- Console screens fit 80×24; the bottom bar fits 80 columns.
- After each task: `whyline note "<decision>" --because "<why>" --file <path> --actor <agent> --role implementer --task DL-<n>`.
- Never push, tag, bump the version or publish inside a task.

## Review Focus

- **An email address with a quote or apostrophe** (`o'brien@example.com`) must reach Mail as one recipient, never break the AppleScript. Pinned in Task 4.
- **A report whose first line is a table** (no text before it) must still give a non-empty summary. Pinned in Task 2.
- **The bot token in an error** (a Telegram error description that echoes the request URL) must be redacted. Pinned in Task 3.
- **Mail fails but Telegram works** for the same run: Telegram still sends, both results are recorded, the run's outcome is unchanged. Pinned in Task 5.
- **An agent renamed through Edit** must not leave its old delivery table behind or lose its settings. Pinned in Task 8.

---

### Task 1: Delivery settings store and run-record field

**Files:**
- Create: `src/whyline/agents/deliveries.py`
- Modify: `src/whyline/agents/records.py` (add `deliveries` to `RunRecord`; add `run_folder`, `load`, `save_metadata`)
- Modify: `src/whyline/agents/service.py` (`delete` also removes the delivery table)
- Test: `tests/agents/test_deliveries.py`

**Interfaces:**
- Produces:
  - `Delivery` (frozen dataclass): `email: tuple[str, ...] = ()`, `subject: str = ""`, `telegram_chat: int = 0`, `telegram_label: str = ""`, `attach: str = "docx"`, `on_failure: str = "alert"`, `command: str = ""`, property `empty -> bool` (no email, no chat, no command).
  - `DeliveryError(ValueError)`.
  - `path() -> Path`, `parse_emails(text: str) -> tuple[str, ...]`, `validate(delivery, known_chats: set[int] | None = None) -> None`, `load_all() -> dict[str, Delivery]`, `get(agent_id: str) -> Delivery | None`, `save(agent_id: str, delivery: Delivery, known_chats: set[int] | None = None) -> None`, `remove(agent_id: str) -> None`, `render(all_: dict[str, Delivery]) -> str`.
  - `records.RunRecord.deliveries: list` (default empty), `records.run_folder(run_id) -> Path`, `records.load(run_id) -> RunRecord | None`, `records.save_metadata(record) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_deliveries.py
import json
import os

import pytest

from whyline.agents import deliveries as dl, records, service
from whyline.agents import definitions as d


def test_round_trip_and_private_file(home):
    want = dl.Delivery(email=("a@example.com", "o'brien@example.com"), subject="Daily jobs",
                       telegram_chat=-1001, telegram_label="Family jobs (group)",
                       attach="docx", on_failure="silent", command="echo hi")
    dl.save("personal:jobs", want)
    assert dl.get("personal:jobs") == want
    assert dl.get("personal:other") is None
    if os.name != "nt":
        assert (dl.path().stat().st_mode & 0o777) == 0o600


def test_repo_agent_ids_with_paths_are_valid_keys(home, tmp_path):
    agent_id = f"repo:{tmp_path.resolve()}:digest"
    dl.save(agent_id, dl.Delivery(email=("a@example.com",)))
    assert dl.get(agent_id).email == ("a@example.com",)


def test_an_empty_delivery_removes_the_table(home):
    dl.save("personal:jobs", dl.Delivery(email=("a@example.com",)))
    dl.save("personal:jobs", dl.Delivery())
    assert dl.get("personal:jobs") is None


@pytest.mark.parametrize("delivery, message", [
    (dl.Delivery(email=("not-an-address",)), "not an email address"),
    (dl.Delivery(email=("a@b@example.com",)), "not an email address"),
    (dl.Delivery(email=("a @example.com",)), "not an email address"),
    (dl.Delivery(email=("a@example.com",), subject="x" * 121), "120 characters"),
    (dl.Delivery(email=("a@example.com",), subject="two\nlines"), "one line"),
    (dl.Delivery(email=("a@example.com",), attach="pdf"), "docx or md"),
    (dl.Delivery(email=("a@example.com",), on_failure="loud"), "alert or silent"),
    (dl.Delivery(command="a\nb"), "one line"),
])
def test_validation(home, delivery, message):
    with pytest.raises(dl.DeliveryError, match=message):
        dl.save("personal:jobs", delivery)


def test_an_unknown_telegram_chat_is_refused_on_save(home):
    with pytest.raises(dl.DeliveryError, match="Telegram setup"):
        dl.save("personal:jobs", dl.Delivery(telegram_chat=5), known_chats={7})
    dl.save("personal:jobs", dl.Delivery(telegram_chat=7), known_chats={7})


def test_parse_emails():
    assert dl.parse_emails(" a@example.com, ,b@example.com ") == ("a@example.com", "b@example.com")


def test_unreadable_file_raises_a_delivery_error(home):
    dl.path().write_text("not = [valid", encoding="utf-8")
    with pytest.raises(dl.DeliveryError, match="deliveries.toml"):
        dl.load_all()


def test_deleting_an_agent_removes_its_deliveries(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "p.toml").write_text(
        f'name="p"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n')
    defn = d.load(folder / "p.toml", kind="personal")
    dl.save(defn.agent_id, dl.Delivery(email=("a@example.com",)))
    service.delete("p", None)
    assert dl.get(defn.agent_id) is None


def test_run_record_keeps_deliveries(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "p.toml").write_text(
        f'name="p"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n')
    defn = d.load(folder / "p.toml", kind="personal")
    from datetime import datetime
    record, run_dir = records.new_run(defn, source="manual", now=datetime(2026, 10, 9, 7, 0))
    assert records.run_folder(record.run_id) == run_dir
    record.deliveries = [{"to": "email", "ok": True, "detail": ""}]
    records.save_metadata(record)
    assert records.load(record.run_id).deliveries == record.deliveries
```

- [ ] **Step 2: Run and verify they fail**

Run: `uv run pytest tests/agents/test_deliveries.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'whyline.agents.deliveries'`.

- [ ] **Step 3: Implement `deliveries.py`**

```python
"""Where each agent's results are delivered on this Mac (deliveries spec 1).

Per Mac, never in an agent's own file: a repo agent's file is committed, so
recipients would leak into git, and a command there would let `git pull`
run someone else's command."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from whyline.agents import paths

ATTACH = ("docx", "md")
ON_FAILURE = ("alert", "silent")


class DeliveryError(ValueError):
    pass


@dataclass(frozen=True)
class Delivery:
    email: tuple[str, ...] = ()
    subject: str = ""
    telegram_chat: int = 0
    telegram_label: str = ""
    attach: str = "docx"
    on_failure: str = "alert"
    command: str = ""

    @property
    def empty(self) -> bool:
        return not (self.email or self.telegram_chat or self.command)


def path() -> Path:
    return paths.home() / "deliveries.toml"


def parse_emails(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _is_address(text: str) -> bool:
    local, _, domain = text.partition("@")
    return (
        text.count("@") == 1 and bool(local) and "." in domain
        and not any(ch in text for ch in " ,;\t\r\n")
    )


def validate(delivery: Delivery, known_chats: set[int] | None = None) -> None:
    for address in delivery.email:
        if not _is_address(address):
            raise DeliveryError(f"not an email address: {address!r}")
    if "\n" in delivery.subject or "\r" in delivery.subject:
        raise DeliveryError("the subject must be one line")
    if len(delivery.subject) > 120:
        raise DeliveryError("the subject must be at most 120 characters")
    if delivery.attach not in ATTACH:
        raise DeliveryError("attach must be docx or md")
    if delivery.on_failure not in ON_FAILURE:
        raise DeliveryError("on_failure must be alert or silent")
    if "\n" in delivery.command or "\r" in delivery.command:
        raise DeliveryError("the command must be one line")
    if delivery.telegram_chat and known_chats is not None and delivery.telegram_chat not in known_chats:
        raise DeliveryError("that Telegram chat isn't known on this Mac; run Telegram setup first")


def _from_table(raw: dict) -> Delivery:
    return Delivery(
        email=tuple(str(item) for item in raw.get("email", [])),
        subject=str(raw.get("subject", "")),
        telegram_chat=int(raw.get("telegram_chat", 0) or 0),
        telegram_label=str(raw.get("telegram_label", "")),
        attach=str(raw.get("attach", "docx")),
        on_failure=str(raw.get("on_failure", "alert")),
        command=str(raw.get("command", "")),
    )


def load_all() -> dict[str, Delivery]:
    try:
        raw = tomllib.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DeliveryError(f"can't read {path().as_posix()} (deliveries.toml): {error}") from error
    return {key: _from_table(value) for key, value in raw.items() if isinstance(value, dict)}


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a valid TOML basic string


def render(all_: dict[str, Delivery]) -> str:
    out = [
        "# whyline: where each agent's results go on this Mac.",
        "# Change it in the console's agent form or with `whyline agents deliver`.",
        "",
    ]
    for agent_id in sorted(all_):
        item = all_[agent_id]
        out += [
            f"[{_q(agent_id)}]",
            "email = [" + ", ".join(_q(address) for address in item.email) + "]",
            f"subject = {_q(item.subject)}",
            f"telegram_chat = {int(item.telegram_chat)}",
            f"telegram_label = {_q(item.telegram_label)}",
            f"attach = {_q(item.attach)}",
            f"on_failure = {_q(item.on_failure)}",
            f"command = {_q(item.command)}",
            "",
        ]
    return "\n".join(out)


def _write(all_: dict[str, Delivery]) -> None:
    target = path()
    temporary = target.with_name(target.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(render(all_))
    os.replace(temporary, target)
    if os.name != "nt":
        os.chmod(target, 0o600)


def get(agent_id: str) -> Delivery | None:
    return load_all().get(agent_id)


def save(agent_id: str, delivery: Delivery, known_chats: set[int] | None = None) -> None:
    validate(delivery, known_chats)
    all_ = load_all()
    if delivery.empty:
        all_.pop(agent_id, None)
    else:
        all_[agent_id] = delivery
    _write(all_)


def remove(agent_id: str) -> None:
    all_ = load_all()
    if all_.pop(agent_id, None) is not None:
        _write(all_)
```

- [ ] **Step 4: Extend `records.py`**

Add the field to `RunRecord` after `definition_hash`:

```python
    deliveries: list = field(default_factory=list)
```

Add after `finish`:

```python
def run_folder(run_id: str) -> Path:
    return paths.runs_dir() / run_id


def load(run_id: str) -> RunRecord | None:
    return _load(run_folder(run_id))


def save_metadata(record: RunRecord) -> None:
    """Rewrite a finished run's metadata, e.g. after its deliveries."""
    _write_private(
        run_folder(record.run_id) / "metadata.json",
        json.dumps(asdict(record), indent=2, default=str),
    )
```

(`_load` already builds `RunRecord(**data)`; older metadata without `deliveries` gets the default.)

- [ ] **Step 5: `service.delete` removes the table**

```python
def delete(name: str, repo_root: Path | None) -> None:
    defn = find(name, repo_root)
    defn.path.unlink(missing_ok=True)
    state.remove(state.connect(), defn.agent_id)
    from whyline.agents import deliveries

    try:
        deliveries.remove(defn.agent_id)
    except deliveries.DeliveryError:
        pass  # an unreadable file is reported where it is edited, not here
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/agents -q && uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline/agents/deliveries.py src/whyline/agents/records.py src/whyline/agents/service.py tests/agents/test_deliveries.py
git commit -m "feat: per-Mac delivery settings and run delivery results (DL-1)"
```

---

### Task 2: Word attachment and summary

**Files:**
- Create: `src/whyline/agents/convert.py`
- Modify: `pyproject.toml` (add `"markdown>=3.5,<4"` to `dependencies`), then `uv lock`
- Test: `tests/agents/test_convert.py`

**Interfaces:**
- Produces: `to_html(text: str) -> str`; `to_docx(report_md: Path, out: Path, *, run=subprocess.run, which=shutil.which) -> Path | None`; `summary(text: str, limit: int = 1000) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_convert.py
from pathlib import Path

from whyline.agents import convert

WIDE = "# Scan\n\nCurrent search date: 9 Oct\nOpen: 6\n\n| " + " | ".join(
    f"C{i}" for i in range(17)) + " |\n|" + "---|" * 17 + "\n| " + " | ".join(
    str(i) for i in range(17)) + " |\n"


def test_to_html_keeps_a_wide_table():
    html = convert.to_html(WIDE)
    assert "<table>" in html and html.count("<th>") == 17
    assert "border-collapse" in html and "<meta charset='utf-8'>" in html


def test_to_docx_calls_textutil(tmp_path):
    report = tmp_path / "final.md"
    report.write_text(WIDE, encoding="utf-8")
    out = tmp_path / "jobs-2026-10-09.docx"
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"PK")
        class R: returncode = 0
        return R()

    assert convert.to_docx(report, out, run=run, which=lambda name: "/usr/bin/textutil") == out
    assert calls[0][:3] == ["textutil", "-convert", "docx"] and calls[0][-2:] == ["-output", str(out)]
    assert not out.with_suffix(".html").exists()  # the temporary page is removed


def test_to_docx_without_textutil_or_on_failure(tmp_path):
    report = tmp_path / "final.md"
    report.write_text("hi", encoding="utf-8")
    out = tmp_path / "x.docx"
    assert convert.to_docx(report, out, which=lambda name: None) is None

    def failing(argv, **kwargs):
        class R: returncode = 1
        return R()

    assert convert.to_docx(report, out, run=failing, which=lambda name: "/usr/bin/textutil") is None


def test_summary_stops_at_the_first_table():
    text = convert.summary(WIDE)
    assert "Open: 6" in text and "C0" not in text
    assert text.endswith("Full report attached.")


def test_summary_of_a_report_that_starts_with_a_table():
    table_only = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    assert "| A | B |" in convert.summary(table_only)


def test_summary_is_trimmed_at_a_line_end():
    long = "\n".join("line %03d %s" % (n, "x" * 40) for n in range(100))
    text = convert.summary(long, limit=1000)
    body = text.rsplit("\n\nFull report attached.", 1)[0]
    assert len(body) <= 1000 and body.endswith("x" * 40)
```

- [ ] **Step 2: Run and verify they fail**

Run: `uv run pytest tests/agents/test_convert.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'whyline.agents.convert'` (or `markdown`).

- [ ] **Step 3: Add the dependency**

In `pyproject.toml`, `dependencies` becomes:

```toml
dependencies = [
    "whyline-relay>=0.2.32,<0.3",
    "prompt_toolkit>=3.0,<4.0",
    "textual>=0.60,<1.0",
    "markdown>=3.5,<4",
]
```

Run: `uv lock && uv sync`

- [ ] **Step 4: Implement `convert.py`**

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/agents/test_convert.py -q && uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/whyline/agents/convert.py tests/agents/test_convert.py
git commit -m "feat: Word attachments and report summaries for deliveries (DL-2)"
```

---

### Task 3: Telegram

**Files:**
- Create: `src/whyline/agents/telegram.py`
- Test: `tests/agents/test_telegram.py`

**Interfaces:**
- Produces:
  - `TelegramError(RuntimeError)`; `API = "https://api.telegram.org"`; `CAPTION_LIMIT = 1024`.
  - `token_get(*, run=subprocess.run, mac: bool | None = None) -> str | None`; `token_set(token: str, *, run=subprocess.run, mac: bool | None = None) -> None`.
  - `check_token(token: str, *, http=None, sleep=time.sleep) -> str` (returns `"@<username>"`).
  - `find_chats(token: str, *, http=None, sleep=time.sleep) -> dict[int, str]`.
  - `known_chats() -> dict[int, str]`; `remember_chats(chats: dict[int, str]) -> dict[int, str]` (merged, saved).
  - `send_document(token, chat_id: int, path: Path, caption: str, *, label: str = "", http=None, sleep=time.sleep) -> None`.
  - `send_message(token, chat_id: int, text: str, *, label: str = "", http=None, sleep=time.sleep) -> None`.
  - `redact(text: str, token: str | None) -> str`.
  - `http` is a callable `(method: str, token: str, fields: dict, files: dict | None) -> dict` returning Telegram's JSON (`{"ok": ..., "result": ..., "error_code": ..., "description": ...}`), raising `OSError` on network failure.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_telegram.py
import os
import urllib.error

import pytest

from whyline.agents import telegram as tg

TOKEN = "123:secret"


def fake(responses):
    calls = []

    def http(method, token, fields, files):
        calls.append((method, fields, files))
        item = responses[min(len(calls), len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    return http, calls


def test_check_token_ok_and_rejected():
    http, _ = fake([{"ok": True, "result": {"username": "JobsBot"}}])
    assert tg.check_token(TOKEN, http=http) == "@JobsBot"
    http, _ = fake([{"ok": False, "error_code": 401, "description": "Unauthorized"}])
    with pytest.raises(tg.TelegramError, match="token was rejected"):
        tg.check_token(TOKEN, http=http)


def test_find_chats_private_and_group():
    http, _ = fake([{"ok": True, "result": [
        {"message": {"chat": {"id": 11, "type": "private", "first_name": "Anish", "last_name": "V"}}},
        {"my_chat_member": {"chat": {"id": -100, "type": "supergroup", "title": "Family jobs"}}},
        {"message": {"chat": {"id": 11, "type": "private", "first_name": "Anish", "last_name": "V"}}},
    ]}])
    assert tg.find_chats(TOKEN, http=http) == {11: "Anish V (private)", -100: "Family jobs (group)"}


def test_known_chats_are_remembered_privately(home):
    tg.remember_chats({11: "Anish V (private)"})
    assert tg.remember_chats({-100: "Family jobs (group)"}) == {11: "Anish V (private)", -100: "Family jobs (group)"}
    assert tg.known_chats() == {11: "Anish V (private)", -100: "Family jobs (group)"}
    if os.name != "nt":
        path = home / ".whyline/agents/telegram-chats.toml"
        assert (path.stat().st_mode & 0o777) == 0o600


def test_send_document_is_plain_text_and_caption_limited(tmp_path):
    report = tmp_path / "jobs.docx"
    report.write_bytes(b"PK")
    http, calls = fake([{"ok": True, "result": {}}])
    tg.send_document(TOKEN, -100, report, "x" * 3000, http=http)
    method, fields, files = calls[0]
    assert method == "sendDocument" and files == {"document": report}
    assert len(fields["caption"]) == tg.CAPTION_LIMIT and "parse_mode" not in fields


def test_a_chat_the_bot_cannot_reach():
    http, _ = fake([{"ok": False, "error_code": 403, "description": "Forbidden: bot was kicked"}])
    with pytest.raises(tg.TelegramError, match="can't reach Family jobs"):
        tg.send_message(TOKEN, -100, "hi", label="Family jobs (group)", http=http)


def test_one_retry_on_a_network_error_then_no_connection():
    slept = []
    http, calls = fake([urllib.error.URLError("down"), {"ok": True, "result": {}}])
    tg.send_message(TOKEN, 1, "hi", http=http, sleep=slept.append)
    assert len(calls) == 2 and slept == [30]
    http, _ = fake([OSError("down"), OSError("down")])
    with pytest.raises(tg.TelegramError, match="no connection"):
        tg.send_message(TOKEN, 1, "hi", http=http, sleep=lambda s: None)


def test_the_token_is_redacted_from_errors():
    http, _ = fake([{"ok": False, "error_code": 400,
                     "description": f"Bad Request: url /bot{TOKEN}/sendMessage"}])
    with pytest.raises(tg.TelegramError) as raised:
        tg.send_message(TOKEN, 1, "hi", http=http)
    assert TOKEN not in str(raised.value) and "•••" in str(raised.value)


def test_keychain_token_on_mac():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        class R:
            returncode = 0
            stdout = "123:secret\n"
        return R()

    tg.token_set(TOKEN, run=run, mac=True)
    assert calls[0][:2] == ["security", "add-generic-password"] and "whyline-telegram" in calls[0]
    assert tg.token_get(run=run, mac=True) == TOKEN


def test_token_file_off_mac(home):
    assert tg.token_get(mac=False) is None
    tg.token_set(TOKEN, mac=False)
    assert tg.token_get(mac=False) == TOKEN
    if os.name != "nt":
        assert ((home / ".whyline/agents/telegram-token").stat().st_mode & 0o777) == 0o600
```

- [ ] **Step 2: Run and verify they fail**

Run: `uv run pytest tests/agents/test_telegram.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'whyline.agents.telegram'`.

- [ ] **Step 3: Implement `telegram.py`**

```python
"""Telegram delivery through the Bot API (deliveries spec 3). Standard
library only. One bot per Mac; its token lives in the macOS Keychain (a
0600 file elsewhere) and never appears in a log, record or error."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from whyline.agents import paths

API = "https://api.telegram.org"
CAPTION_LIMIT = 1024
_SERVICE, _ACCOUNT = "whyline-telegram", "bot-token"


class TelegramError(RuntimeError):
    pass


class _ChatError(TelegramError):
    pass


def redact(text: str, token: str | None) -> str:
    return text.replace(token, "•••") if token else text


def _is_mac(mac: bool | None) -> bool:
    return platform.system() == "Darwin" if mac is None else mac


def _token_file() -> Path:
    return paths.home() / "telegram-token"


def _write_private(target: Path, text: str) -> None:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    if os.name != "nt":
        os.chmod(target, 0o600)


def token_get(*, run=subprocess.run, mac: bool | None = None) -> str | None:
    if _is_mac(mac):
        result = run(
            ["security", "find-generic-password", "-s", _SERVICE, "-a", _ACCOUNT, "-w"],
            capture_output=True, text=True,
        )
        token = (result.stdout or "").strip() if result.returncode == 0 else ""
        return token or None
    try:
        return _token_file().read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def token_set(token: str, *, run=subprocess.run, mac: bool | None = None) -> None:
    if _is_mac(mac):
        result = run(
            ["security", "add-generic-password", "-U", "-s", _SERVICE, "-a", _ACCOUNT, "-w", token],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise TelegramError("couldn't save the bot token in the Keychain")
        return
    _write_private(_token_file(), token + "\n")


def _http(method: str, token: str, fields: dict, files: dict | None) -> dict:
    url = f"{API}/bot{token}/{method}"
    if files:
        boundary = uuid.uuid4().hex
        body = bytearray()
        for key, value in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\""
                     f"\r\n\r\n{value}\r\n").encode("utf-8")
        for key, file_path in files.items():
            name = Path(file_path).name
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; "
                     f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                     ).encode("utf-8")
            body += Path(file_path).read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode("utf-8")
        data, content_type = bytes(body), f"multipart/form-data; boundary={boundary}"
    else:
        data, content_type = json.dumps(fields).encode("utf-8"), "application/json"
    request = urllib.request.Request(url, data=data, headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except ValueError:
            payload = {"description": str(error)}
        payload["ok"] = False
        payload.setdefault("error_code", error.code)
        return payload


def _call(method: str, token: str, fields: dict, files: dict | None = None, *, http=None,
          sleep=time.sleep):
    http = http or _http
    result = None
    for attempt in (1, 2):
        try:
            result = http(method, token, fields, files)
        except OSError:  # urllib.error.URLError is an OSError
            result = None
        if result is not None and (result.get("ok") or int(result.get("error_code", 0)) < 500):
            break
        if attempt == 1:
            sleep(30)
    if result is None or (not result.get("ok") and int(result.get("error_code", 0)) >= 500):
        raise TelegramError("no connection to Telegram")
    if result.get("ok"):
        return result.get("result")
    code = int(result.get("error_code", 0))
    description = redact(str(result.get("description", "Telegram refused the request")), token)
    if code == 401:
        raise TelegramError("the bot token was rejected; run Telegram setup again")
    if code == 403 or (code == 400 and "chat" in description.lower()):
        raise _ChatError(description)
    raise TelegramError(description)


def check_token(token: str, *, http=None, sleep=time.sleep) -> str:
    me = _call("getMe", token, {}, http=http, sleep=sleep) or {}
    return "@" + str(me.get("username", "bot"))


def find_chats(token: str, *, http=None, sleep=time.sleep) -> dict[int, str]:
    found: dict[int, str] = {}
    for update in _call("getUpdates", token, {}, http=http, sleep=sleep) or []:
        for key in ("message", "my_chat_member", "channel_post", "edited_message"):
            chat = (update.get(key) or {}).get("chat")
            if not chat:
                continue
            if chat.get("type") == "private":
                name = " ".join(part for part in (chat.get("first_name"), chat.get("last_name")) if part)
                found[int(chat["id"])] = f"{name or 'Private chat'} (private)"
            else:
                found[int(chat["id"])] = f"{chat.get('title') or 'Group'} (group)"
            break
    return found


def _chats_file() -> Path:
    return paths.home() / "telegram-chats.toml"


def known_chats() -> dict[int, str]:
    try:
        raw = tomllib.loads(_chats_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}
    return {int(key): str(value) for key, value in raw.get("chats", {}).items()}


def remember_chats(chats: dict[int, str]) -> dict[int, str]:
    merged = {**known_chats(), **chats}
    lines = ["[chats]"] + [f"{json.dumps(str(cid))} = {json.dumps(label, ensure_ascii=False)}"
                           for cid, label in sorted(merged.items())]
    _write_private(_chats_file(), "\n".join(lines) + "\n")
    return merged


def send_document(token: str, chat_id: int, path: Path, caption: str, *, label: str = "",
                  http=None, sleep=time.sleep) -> None:
    fields = {"chat_id": str(chat_id), "caption": caption[:CAPTION_LIMIT]}
    try:
        _call("sendDocument", token, fields, {"document": path}, http=http, sleep=sleep)
    except _ChatError:
        raise TelegramError(f"the bot can't reach {label or chat_id}") from None


def send_message(token: str, chat_id: int, text: str, *, label: str = "",
                 http=None, sleep=time.sleep) -> None:
    try:
        _call("sendMessage", token, {"chat_id": chat_id, "text": text[:4096]}, http=http, sleep=sleep)
    except _ChatError:
        raise TelegramError(f"the bot can't reach {label or chat_id}") from None
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/agents/test_telegram.py -q && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/whyline/agents/telegram.py tests/agents/test_telegram.py
git commit -m "feat: Telegram delivery through the Bot API (DL-3)"
```

---

### Task 4: Email through Mail

**Files:**
- Create: `src/whyline/agents/mail_send.py`
- Test: `tests/agents/test_mail_send.py`

**Interfaces:**
- Produces: `MailError(RuntimeError)`; `SCRIPT: str`; `send(to: list[str], subject: str, body: str, attachments: list[Path], *, run=subprocess.run, system=platform.system) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_mail_send.py
from pathlib import Path

import pytest

from whyline.agents import mail_send


def runner(code=0, stderr=""):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        class R:
            returncode = code
        R.stderr = stderr
        return R()

    return run, calls


def test_arguments_are_passed_separately_never_spliced(tmp_path):
    run, calls = runner()
    doc = tmp_path / "jobs.docx"
    mail_send.send(["a@example.com", "o'brien@example.com"], 'Daily "jobs" — 2026-10-09',
                   "body", [doc], run=run, system=lambda: "Darwin")
    argv, kwargs = calls[0]
    assert argv[:2] == ["osascript", "-"]
    assert argv[2:] == ['Daily "jobs" — 2026-10-09', "body", "2",
                        "a@example.com", "o'brien@example.com", str(doc)]
    assert kwargs["input"] == mail_send.SCRIPT and "o'brien" not in mail_send.SCRIPT


def test_automation_permission_message():
    run, _ = runner(1, "execution error: Not authorized to send Apple events to Mail. (-1743)")
    with pytest.raises(mail_send.MailError, match="Privacy & Security → Automation"):
        mail_send.send(["a@example.com"], "s", "b", [], run=run, system=lambda: "Darwin")


def test_no_account_message():
    run, _ = runner(1, "execution error: whyline: no Mail account (9001)")
    with pytest.raises(mail_send.MailError, match="no account set up"):
        mail_send.send(["a@example.com"], "s", "b", [], run=run, system=lambda: "Darwin")


def test_other_errors_use_the_first_line():
    run, _ = runner(1, "something odd\nmore")
    with pytest.raises(mail_send.MailError, match="^something odd$"):
        mail_send.send(["a@example.com"], "s", "b", [], run=run, system=lambda: "Darwin")


def test_not_on_macos():
    with pytest.raises(mail_send.MailError, match="needs the Mail app on macOS"):
        mail_send.send(["a@example.com"], "s", "b", [], system=lambda: "Linux")
```

- [ ] **Step 2: Run and verify they fail**

Run: `uv run pytest tests/agents/test_mail_send.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `mail_send.py`**

```python
"""Email through the Mail app (deliveries spec 6). Recipients, subject, body
and attachment paths go to osascript as arguments, never into the script
text, so no address or subject can change what the script does."""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

SCRIPT = """on run argv
	set subj to item 1 of argv
	set body to item 2 of argv
	set n to (item 3 of argv) as integer
	tell application "Mail"
		if (count of accounts) is 0 then error "whyline: no Mail account" number 9001
		set m to make new outgoing message with properties {subject:subj, content:body & return & return, visible:false}
		tell m
			repeat with i from 4 to (3 + n)
				make new to recipient at end of to recipients with properties {address:(item i of argv)}
			end repeat
			repeat with i from (4 + n) to (count of argv)
				make new attachment with properties {file name:(POSIX file (item i of argv))} at after the last paragraph of content
			end repeat
		end tell
		delay 3
		send m
	end tell
end run
"""


class MailError(RuntimeError):
    pass


def _explain(stderr: str) -> str:
    if "-1743" in stderr:
        return ("allow whyline to control Mail in System Settings → "
                "Privacy & Security → Automation")
    if "9001" in stderr:
        return "Mail has no account set up"
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[0] if lines else "Mail couldn't send the message"


def send(to: list[str], subject: str, body: str, attachments: list[Path], *,
         run=subprocess.run, system=platform.system) -> None:
    if system() != "Darwin":
        raise MailError("email needs the Mail app on macOS")
    argv = ["osascript", "-", subject, body, str(len(to)), *to, *[str(p) for p in attachments]]
    try:
        result = run(argv, input=SCRIPT, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MailError(f"Mail couldn't be reached: {error}") from error
    if result.returncode != 0:
        raise MailError(_explain(result.stderr or ""))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/agents/test_mail_send.py -q && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/whyline/agents/mail_send.py tests/agents/test_mail_send.py
git commit -m "feat: email deliveries through the Mail app (DL-4)"
```

---

### Task 5: Delivering after a run, the command, test sends and resend

**Files:**
- Create: `src/whyline/agents/deliver.py`
- Modify: `src/whyline/agents/after.py` (call `deliver.after_run` before notifying; list failed deliveries)
- Modify: `src/whyline/agents/service.py` (add `resend`)
- Test: `tests/agents/test_deliver.py`

**Interfaces:**
- Consumes: `deliveries.Delivery`, `deliveries.get`, `deliveries.DeliveryError` (Task 1); `records.run_folder`, `records.load`, `records.save_metadata`, `records.read_final` (Task 1); `convert.to_docx`, `convert.summary` (Task 2); `telegram.token_get`, `telegram.send_document`, `telegram.send_message` (Task 3); `mail_send.send`, `mail_send.MailError` (Task 4).
- Produces:
  - `deliver.after_run(defn, record, *, delivery=None, mail=None, tg=None, run=subprocess.run) -> list[dict]`.
  - `deliver.send_test(label: str, delivery, *, mail=None, tg=None, run=subprocess.run, cwd: Path | None = None) -> list[dict]`.
  - `deliver.subject_line(defn, delivery, record, *, failed: bool = False) -> str`.
  - `deliver.status_text(record) -> str` (e.g. `"delivered: email ✓ telegram ✗ the bot can't reach X"`; `"alert: …"` for failed runs; `""` when nothing was delivered).
  - `deliver.describe(delivery) -> str` (a Review sentence; `""` for an empty delivery).
  - `service.resend(name: str, repo_root: Path | None, run_id: str | None = None) -> list[dict]`.
  - Result dicts: `{"to": "email" | "telegram" | "command", "ok": bool, "detail": str}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_deliver.py
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline.agents import after, deliver, deliveries as dl, records, service, state
from whyline.agents import definitions as d

REPORT = "Current search date: 9 Oct\nOpen: 6\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"


@pytest.fixture
def agent(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "jobs.toml").write_text(
        f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n')
    defn = d.load(folder / "jobs.toml", kind="personal")
    state.accept(state.connect(), defn)
    return defn


def _run(defn, outcome="succeeded", reason="", text=REPORT):
    record, folder = records.new_run(defn, source="manual", now=datetime(2026, 10, 9, 7, 0))
    record.outcome, record.reason, record.cli = outcome, reason, "codex"
    return records.finish(record, folder, final_text=text, defn=defn)


class FakeTelegram:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def token_get(self):
        return "123:secret"

    def send_document(self, token, chat, path, caption, label=""):
        if self.fail:
            raise RuntimeError(self.fail)
        self.sent.append(("doc", chat, Path(path).name, caption))

    def send_message(self, token, chat, text, label=""):
        if self.fail:
            raise RuntimeError(self.fail)
        self.sent.append(("msg", chat, text))


def _no_docx(monkeypatch):
    monkeypatch.setattr("whyline.agents.convert.to_docx", lambda md, out: None)


DELIVERY = dl.Delivery(email=("a@example.com",), subject="Daily jobs", telegram_chat=-100,
                       telegram_label="Family (group)")


def test_success_sends_the_attachment_and_summary_to_both(agent, monkeypatch):
    def to_docx(md, out):
        out.write_bytes(b"PK")
        return out
    monkeypatch.setattr("whyline.agents.convert.to_docx", to_docx)
    mails, tg = [], FakeTelegram()
    record = _run(agent)
    results = deliver.after_run(agent, record, delivery=DELIVERY,
                                mail=lambda *a, **k: mails.append(a), tg=tg)
    assert [r["to"] for r in results] == ["email", "telegram"] and all(r["ok"] for r in results)
    to, subject, body, attachments = mails[0]
    assert to == ["a@example.com"] and subject == "Daily jobs — 2026-10-09"
    assert "Open: 6" in body and "| A |" not in body and "Sent by whyline from" in body
    assert [p.name for p in attachments] == ["jobs-2026-10-09.docx"]
    kind, chat, name, caption = tg.sent[0]
    assert (kind, chat, name) == ("doc", -100, "jobs-2026-10-09.docx")
    assert caption.startswith("Daily jobs — 2026-10-09\n\n")
    assert records.load(record.run_id).deliveries == results
    assert records.load(record.run_id).outcome == "succeeded"


def test_markdown_fallback_note_without_word(agent, monkeypatch):
    _no_docx(monkeypatch)
    mails = []
    deliver.after_run(agent, _run(agent), delivery=dl.Delivery(email=("a@example.com",)),
                      mail=lambda *a, **k: mails.append(a), tg=FakeTelegram())
    assert mails[0][3][0].name == "jobs-2026-10-09.md"
    assert "Markdown file is attached" in mails[0][2]


def test_a_failed_run_sends_a_short_alert(agent, monkeypatch):
    _no_docx(monkeypatch)
    mails, tg = [], FakeTelegram()
    record = _run(agent, outcome="timed_out", reason="codex ran past 45 minutes", text="")
    deliver.after_run(agent, record, delivery=DELIVERY, mail=lambda *a, **k: mails.append(a), tg=tg)
    assert mails[0][1] == "Daily jobs failed — 2026-10-09" and mails[0][3] == []
    assert "jobs (personal) timed_out: codex ran past 45 minutes" in mails[0][2]
    assert tg.sent[0][0] == "msg"
    assert deliver.status_text(records.load(record.run_id)).startswith("alert: ")


def test_silent_and_no_run_outcomes_send_nothing(agent, monkeypatch):
    _no_docx(monkeypatch)
    mails = []
    silent = dl.Delivery(email=("a@example.com",), on_failure="silent")
    assert deliver.after_run(agent, _run(agent, "failed", "boom", ""), delivery=silent,
                             mail=lambda *a, **k: mails.append(a), tg=FakeTelegram()) == []
    for outcome in ("skipped", "missed"):
        assert deliver.after_run(agent, _run(agent, outcome, "", ""), delivery=DELIVERY,
                                 mail=lambda *a, **k: mails.append(a), tg=FakeTelegram()) == []
    assert mails == []


def test_mail_failing_still_sends_telegram(agent, monkeypatch):
    _no_docx(monkeypatch)
    from whyline.agents.mail_send import MailError

    def broken(*args, **kwargs):
        raise MailError("Mail has no account set up")

    tg = FakeTelegram()
    results = deliver.after_run(agent, _run(agent), delivery=DELIVERY, mail=broken, tg=tg)
    assert results[0] == {"to": "email", "ok": False, "detail": "Mail has no account set up"}
    assert results[1]["ok"] and tg.sent
    assert "email ✗ Mail has no account set up" in deliver.status_text(SimpleNamespace(
        outcome="succeeded", deliveries=results))


def test_telegram_not_set_up(agent, monkeypatch):
    _no_docx(monkeypatch)
    tg = FakeTelegram()
    tg.token_get = lambda: None
    results = deliver.after_run(agent, _run(agent), delivery=dl.Delivery(telegram_chat=-100),
                                mail=lambda *a, **k: None, tg=tg)
    assert results == [{"to": "telegram", "ok": False,
                        "detail": "Telegram isn't set up on this Mac; run Telegram setup"}]


def test_the_command_gets_its_environment_and_log(agent, monkeypatch):
    _no_docx(monkeypatch)
    seen = {}

    def run(argv, **kwargs):
        seen.update(kwargs["env"])
        seen["argv"] = argv
        return SimpleNamespace(returncode=3, stdout="first\nlast line\n")

    record = _run(agent)
    results = deliver.after_run(agent, record, delivery=dl.Delivery(command="notify.sh"),
                                mail=None, tg=FakeTelegram(), run=run)
    assert seen["argv"][-1] == "notify.sh"
    assert seen["WHYLINE_AGENT"] == "jobs" and seen["WHYLINE_OUTCOME"] == "succeeded"
    assert seen["WHYLINE_REPORT"].endswith("final.md") and seen["WHYLINE_ATTACHMENT"].endswith(".md")
    assert "Open: 6" in seen["WHYLINE_SUMMARY"] and seen["WHYLINE_RUN_ID"] == record.run_id
    assert results == [{"to": "command", "ok": False, "detail": "command failed (exit 3): last line"}]
    assert "last line" in (records.run_folder(record.run_id) / "command.log").read_text()


def test_a_command_timeout(agent, monkeypatch):
    import subprocess
    _no_docx(monkeypatch)

    def run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 120)

    results = deliver.after_run(agent, _run(agent), delivery=dl.Delivery(command="sleep 999"),
                                tg=FakeTelegram(), run=run)
    assert results[0]["detail"] == "command failed (timed out after 2 minutes)"


def test_after_finish_delivers_and_never_raises(agent, monkeypatch):
    sent = []
    monkeypatch.setattr(deliver, "after_run", lambda defn, record: sent.append(record.run_id) or [])
    record = _run(agent)
    after.finish(state.connect(), agent, record, notify=False)
    assert sent == [record.run_id]

    def explode(defn, record):
        raise RuntimeError("boom")

    monkeypatch.setattr(deliver, "after_run", explode)
    after.finish(state.connect(), agent, _run(agent), notify=False)  # no exception


def test_resend_uses_the_latest_run(agent, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver, "after_run", lambda defn, record: calls.append(record.run_id) or [])
    record = _run(agent)
    service.resend("jobs", None)
    service.resend("jobs", None, record.run_id)
    assert calls == [record.run_id, record.run_id]


def test_send_test(home, monkeypatch, tmp_path):
    mails, tg = [], FakeTelegram()
    results = deliver.send_test("jobs (personal)", DELIVERY, mail=lambda *a, **k: mails.append(a),
                                tg=tg, cwd=tmp_path)
    assert [r["to"] for r in results] == ["email", "telegram"]
    assert mails[0][1] == "Test from whyline: jobs (personal)"


def test_describe():
    assert deliver.describe(dl.Delivery()) == ""
    text = deliver.describe(DELIVERY)
    assert "a@example.com" in text and "Telegram 'Family (group)'" in text
    assert "Word file attached" in text and "short alert" in text
```

- [ ] **Step 2: Run and verify they fail**

Run: `uv run pytest tests/agents/test_deliver.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'whyline.agents.deliver'`.

- [ ] **Step 3: Implement `deliver.py`**

```python
"""After a run: send its result where the agent's delivery settings say
(deliveries spec 2, 7, 8). Never raises; never changes the run's outcome."""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from whyline.agents import convert, deliveries, mail_send, paths, records

COMMAND_TIMEOUT = 120
_SUCCEEDED = ("succeeded", "succeeded_with_denials")
_NO_RUN = ("skipped", "missed")
_NO_WORD = "(Word conversion isn't available on this computer, so the Markdown file is attached.)"


def _telegram():
    from whyline.agents import telegram
    return telegram


def subject_line(defn, delivery, record, *, failed: bool = False) -> str:
    base = delivery.subject.strip() or defn.label
    day = record.started[:10]
    return f"{base} failed — {day}" if failed else f"{base} — {day}"


def _signature() -> str:
    name = platform.node().split(".")[0] or "this computer"
    return f"Sent by whyline from {name}."


def _attachment(defn, record, delivery) -> tuple[Path | None, str]:
    folder = records.run_folder(record.run_id)
    report = folder / "final.md"
    try:
        text = report.read_text(encoding="utf-8")
    except OSError:
        return None, ""
    if not text.strip():
        return None, ""
    stem = f"{defn.name}-{record.started[:10]}"
    note = ""
    if delivery.attach == "docx":
        word = folder / f"{stem}.docx"
        if word.is_file():
            return word, ""
        made = convert.to_docx(report, word)
        if made is not None:
            return made, ""
        note = _NO_WORD
    plain = folder / f"{stem}.md"
    if not plain.is_file():
        plain.write_text(text, encoding="utf-8")
    return plain, note


def _result(to: str, ok: bool, detail: str = "") -> dict:
    return {"to": to, "ok": ok, "detail": detail}


def _email(delivery, subject, body, attachment, mail) -> dict:
    try:
        mail(list(delivery.email), subject, body + "\n\n" + _signature(),
             [attachment] if attachment else [])
    except Exception as error:  # MailError and anything unexpected
        return _result("email", False, str(error))
    return _result("email", True)


def _send_telegram(delivery, subject, body, attachment, tg) -> dict:
    token = None
    try:
        token = tg.token_get()
        if not token:
            return _result("telegram", False, "Telegram isn't set up on this Mac; run Telegram setup")
        text = subject + "\n\n" + body
        if attachment:
            tg.send_document(token, delivery.telegram_chat, attachment, text,
                             label=delivery.telegram_label)
        else:
            tg.send_message(token, delivery.telegram_chat, text, label=delivery.telegram_label)
    except Exception as error:
        detail = str(error).replace(token, "•••") if token else str(error)
        return _result("telegram", False, detail)
    return _result("telegram", True)


def _command(delivery, env_values: dict, cwd: Path, log: Path | None, run) -> dict:
    argv = ["cmd", "/c", delivery.command] if os.name == "nt" else ["/bin/sh", "-c", delivery.command]
    env = {**os.environ, **env_values}
    try:
        done = run(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                   timeout=COMMAND_TIMEOUT)
    except subprocess.TimeoutExpired:
        return _result("command", False, "command failed (timed out after 2 minutes)")
    except OSError as error:
        return _result("command", False, f"command failed: {error}")
    output = done.stdout or ""
    if log is not None:
        log.write_text(output, encoding="utf-8")
    if done.returncode == 0:
        return _result("command", True)
    lines = [line for line in output.splitlines() if line.strip()]
    last = lines[-1].strip() if lines else ""
    return _result("command", False, f"command failed (exit {done.returncode}): {last}".rstrip(": "))


def after_run(defn, record, *, delivery=None, mail=None, tg=None, run=subprocess.run) -> list[dict]:
    if delivery is None:
        try:
            delivery = deliveries.get(defn.agent_id)
        except deliveries.DeliveryError:
            return []
    if delivery is None or delivery.empty or record.outcome in _NO_RUN:
        return []
    mail = mail or mail_send.send
    tg = tg or _telegram()
    succeeded = record.outcome in _SUCCEEDED
    attachment, report_path = None, ""
    if succeeded:
        attachment, note = _attachment(defn, record, delivery)
        try:
            text = records.read_final(record.run_id)
        except OSError:
            text = ""
        report_path = str(records.run_folder(record.run_id) / "final.md")
        body = convert.summary(text) + (f"\n{note}" if note else "")
        subject = subject_line(defn, delivery, record)
    else:
        body = f"{defn.label} {record.outcome}: {record.reason or 'no reason given'}"
        subject = subject_line(defn, delivery, record, failed=True)
    results = []
    if succeeded or delivery.on_failure == "alert":
        if delivery.email:
            results.append(_email(delivery, subject, body, attachment, mail))
        if delivery.telegram_chat:
            results.append(_send_telegram(delivery, subject, body, attachment, tg))
    if delivery.command:
        env_values = {
            "WHYLINE_AGENT": defn.name,
            "WHYLINE_AGENT_LABEL": defn.label,
            "WHYLINE_OUTCOME": record.outcome,
            "WHYLINE_REASON": record.reason or "",
            "WHYLINE_RUN_ID": record.run_id,
            "WHYLINE_REPORT": report_path,
            "WHYLINE_ATTACHMENT": str(attachment) if attachment else "",
            "WHYLINE_SUMMARY": body,
        }
        results.append(_command(delivery, env_values, defn.root,
                                records.run_folder(record.run_id) / "command.log", run))
    record.deliveries = results
    try:
        records.save_metadata(record)
    except OSError:
        pass
    return results


def send_test(label: str, delivery, *, mail=None, tg=None, run=subprocess.run,
              cwd: Path | None = None) -> list[dict]:
    mail = mail or mail_send.send
    tg = tg or _telegram()
    sample = paths.home() / "whyline-test.md"
    sample.write_text(f"# Test from whyline\n\nThis is how {label}'s results will arrive.\n",
                      encoding="utf-8")
    subject = f"Test from whyline: {label}"
    body = "If this arrived, delivery works."
    results = []
    if delivery.email:
        results.append(_email(delivery, subject, body, sample, mail))
    if delivery.telegram_chat:
        results.append(_send_telegram(delivery, subject, body, sample, tg))
    if delivery.command:
        env_values = {"WHYLINE_AGENT_LABEL": label, "WHYLINE_OUTCOME": "test",
                      "WHYLINE_REPORT": str(sample), "WHYLINE_ATTACHMENT": str(sample),
                      "WHYLINE_SUMMARY": body}
        results.append(_command(delivery, env_values, cwd or paths.home(), None, run))
    return results


def status_text(record) -> str:
    results = getattr(record, "deliveries", None) or []
    if not results:
        return ""
    parts = []
    for item in results:
        mark = "✓" if item.get("ok") else "✗"
        part = f"{item.get('to')} {mark}"
        if not item.get("ok") and item.get("detail"):
            part += f" {item['detail']}"
        parts.append(part)
    prefix = "delivered" if record.outcome in _SUCCEEDED else "alert"
    return f"{prefix}: " + "  ".join(parts)


def describe(delivery) -> str:
    if delivery is None or delivery.empty:
        return ""
    places = []
    if delivery.email:
        places.append("email to " + ", ".join(delivery.email))
    if delivery.telegram_chat:
        places.append(f"Telegram '{delivery.telegram_label or delivery.telegram_chat}'")
    text = ""
    if places:
        kind = "a Word file" if delivery.attach == "docx" else "a Markdown file"
        text = "It also sends the result by " + " and ".join(places) + f", with {kind} attached."
        if delivery.on_failure == "alert":
            text += " If a run fails, a short alert goes to the same places."
    if delivery.command:
        text += f" After each run it runs: {delivery.command}"
    return text.strip()
```

Note for `describe`'s test: "Word file attached" matches "with a Word file attached".

- [ ] **Step 4: Hook into `after.finish`**

In `src/whyline/agents/after.py`, immediately before `if notify:`, add:

```python
    try:
        from whyline.agents import deliver

        delivered = deliver.after_run(defn, record)
    except Exception:  # delivery must never break the run's bookkeeping
        delivered = []
    for item in delivered:
        if not item.get("ok"):
            messages.append(f"{item.get('to')} delivery failed — {item.get('detail')}")
```

- [ ] **Step 5: Add `service.resend`**

```python
def resend(name: str, repo_root: Path | None, run_id: str | None = None) -> list[dict]:
    from whyline.agents import deliver

    defn = find(name, repo_root)
    if run_id:
        record = records.load(run_id)
    else:
        latest = records.list_runs(defn.agent_id, limit=1)
        record = latest[0] if latest else None
    if record is None or record.agent_id != defn.agent_id:
        raise AgentNotFound(f"no run of {defn.label} to resend")
    return deliver.after_run(defn, record)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/agents -q && uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline/agents/deliver.py src/whyline/agents/after.py src/whyline/agents/service.py tests/agents/test_deliver.py
git commit -m "feat: deliver each run's result by email, Telegram and command (DL-5)"
```

---

### Task 6: The CLI

**Files:**
- Modify: `src/whyline/cli.py` (parsers for `deliver`, `resend`, `telegram setup|chats`; handlers; delivery status in `history`)
- Test: `tests/agents/test_cli_deliver.py`

**Interfaces:**
- Consumes: Tasks 1, 3 and 5 (`deliveries`, `telegram`, `deliver.send_test`, `deliver.status_text`, `service.resend`).
- Produces: `whyline agents deliver <name> [--email ...] [--subject ...] [--telegram ...] [--attach docx|md] [--on-failure alert|silent] [--command ...] [--clear] [--test]`; `whyline agents resend <name> [--run RUN_ID]`; `whyline agents telegram setup`; `whyline agents telegram chats`. Handlers `_cmd_agents_deliver(args, root) -> int`, `_cmd_agents_resend(args, root) -> int`, `_cmd_agents_telegram(args, *, input_fn=input, getpass_fn=getpass.getpass) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_cli_deliver.py
import json

import pytest

from whyline import cli
from whyline.agents import deliver, deliveries as dl, telegram


@pytest.fixture
def agent(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "jobs.toml").write_text(
        f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n')
    from whyline.agents import definitions as d, state
    defn = d.load(folder / "jobs.toml", kind="personal")
    state.accept(state.connect(), defn)
    return defn


def main(*argv):
    return cli.main(["agents", *argv])


def test_deliver_sets_and_shows(agent, capsys, monkeypatch):
    monkeypatch.setattr(telegram, "known_chats", lambda: {-100: "Family (group)"})
    assert main("deliver", "jobs", "--email", "a@example.com,b@example.com",
                "--subject", "Daily jobs", "--telegram", "Family (group)",
                "--attach", "md", "--on-failure", "silent") == 0
    got = dl.get(agent.agent_id)
    assert got.email == ("a@example.com", "b@example.com") and got.telegram_chat == -100
    assert got.subject == "Daily jobs" and got.attach == "md" and got.on_failure == "silent"
    capsys.readouterr()
    assert main("deliver", "jobs") == 0
    out = capsys.readouterr().out
    assert "a@example.com, b@example.com" in out and "Family (group)" in out


def test_deliver_rejects_a_bad_address_and_unknown_chat(agent, capsys, monkeypatch):
    monkeypatch.setattr(telegram, "known_chats", lambda: {})
    assert main("deliver", "jobs", "--email", "nope") != 0
    assert "not an email address" in capsys.readouterr().err
    assert main("deliver", "jobs", "--telegram", "Nobody") != 0
    assert "Telegram setup" in capsys.readouterr().err


def test_deliver_clear_and_test(agent, capsys, monkeypatch):
    dl.save(agent.agent_id, dl.Delivery(email=("a@example.com",)))
    monkeypatch.setattr(deliver, "send_test",
                        lambda label, delivery, **k: [{"to": "email", "ok": True, "detail": ""}])
    assert main("deliver", "jobs", "--test") == 0
    assert "email ✓" in capsys.readouterr().out
    assert main("deliver", "jobs", "--clear") == 0
    assert dl.get(agent.agent_id) is None


def test_resend(agent, capsys, monkeypatch):
    from whyline.agents import service
    monkeypatch.setattr(service, "resend",
                        lambda name, root, run_id=None: [{"to": "telegram", "ok": False, "detail": "x"}])
    assert main("resend", "jobs") == 1
    assert "telegram ✗ x" in capsys.readouterr().out


def test_telegram_setup_and_chats(home, capsys, monkeypatch):
    saved = {}
    monkeypatch.setattr(telegram, "check_token", lambda token: "@JobsBot")
    monkeypatch.setattr(telegram, "token_set", lambda token: saved.setdefault("token", token))
    monkeypatch.setattr(telegram, "find_chats", lambda token: {11: "Anish V (private)"})
    answers = iter([""])
    rc = cli._cmd_agents_telegram(
        cli.build_parser().parse_args(["agents", "telegram", "setup"]),
        input_fn=lambda prompt="": next(answers), getpass_fn=lambda prompt="": "123:secret")
    assert rc == 0 and saved["token"] == "123:secret"
    out = capsys.readouterr().out
    assert "Connected to @JobsBot" in out and "Anish V (private)" in out and "123:secret" not in out
    assert main("telegram", "chats") == 0
    assert "Anish V (private)" in capsys.readouterr().out
```

- [ ] **Step 2: Run and verify they fail**

Run: `uv run pytest tests/agents/test_cli_deliver.py -q`
Expected: FAIL (`invalid choice: 'deliver'`).

- [ ] **Step 3: Add the parsers**

In the `agents` parser block of `src/whyline/cli.py` (after `mail-script`), add:

```python
    deliver = sub.add_parser("deliver", help="Where an agent's results are sent on this Mac")
    deliver.add_argument("name")
    deliver.add_argument("--email", help="comma-separated addresses; empty string clears")
    deliver.add_argument("--subject")
    deliver.add_argument("--telegram", help="a known chat's label or id; 'none' clears")
    deliver.add_argument("--attach", choices=("docx", "md"))
    deliver.add_argument("--on-failure", dest="on_failure", choices=("alert", "silent"))
    deliver.add_argument("--command")
    deliver.add_argument("--clear", action="store_true", help="remove all deliveries")
    deliver.add_argument("--test", action="store_true", help="send a test now")
    resend = sub.add_parser("resend", help="Send a run's result again")
    resend.add_argument("name")
    resend.add_argument("--run", dest="run_id")
    telegram_parser = sub.add_parser("telegram", help="Set up Telegram delivery on this Mac")
    telegram_sub = telegram_parser.add_subparsers(dest="telegram_command", required=True)
    telegram_sub.add_parser("setup", help="Connect a bot (one-time) and find your chats")
    telegram_sub.add_parser("chats", help="Chats whyline can send to")
```

- [ ] **Step 4: Add the handlers**

Add `import getpass` and `from dataclasses import replace` to the imports at the top of `cli.py` (neither is imported today). Then add near the other `_cmd_agents_*` helpers:

```python
def _delivery_lines(results: list[dict]) -> str:
    return "  ".join(
        f"{r['to']} {'✓' if r['ok'] else '✗'}" + ("" if r["ok"] or not r["detail"] else f" {r['detail']}")
        for r in results
    )


def _cmd_agents_deliver(args, root) -> int:
    from whyline.agents import deliver, deliveries as dl, service, telegram

    defn = service.find(args.name, root)
    current = dl.get(defn.agent_id) or dl.Delivery()
    if args.clear:
        dl.remove(defn.agent_id)
        print(f"{defn.label}: no deliveries.")
        return EXIT_OK
    changes = {}
    if args.email is not None:
        changes["email"] = dl.parse_emails(args.email)
    if args.subject is not None:
        changes["subject"] = args.subject
    if args.attach:
        changes["attach"] = args.attach
    if args.on_failure:
        changes["on_failure"] = args.on_failure
    if args.command is not None:
        changes["command"] = args.command
    known = telegram.known_chats()
    if args.telegram is not None:
        wanted = args.telegram.strip()
        if wanted.lower() in ("", "none"):
            changes.update(telegram_chat=0, telegram_label="")
        else:
            match = [(cid, label) for cid, label in known.items()
                     if wanted in (label, str(cid))]
            if not match:
                print(f"error: no known Telegram chat '{wanted}'; run `whyline agents telegram setup` "
                      "(Telegram setup) first", file=sys.stderr)
                return EXIT_ERROR
            changes.update(telegram_chat=match[0][0], telegram_label=match[0][1])
    if changes:
        updated = replace(current, **changes)
        try:
            dl.save(defn.agent_id, updated, known_chats=set(known))
        except dl.DeliveryError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR
        current = updated
    if args.test:
        results = deliver.send_test(defn.label, current, cwd=defn.root)
        print(_delivery_lines(results) or "Nothing to test: no deliveries set.")
        return EXIT_OK if all(r["ok"] for r in results) else EXIT_ERROR
    if current.empty:
        print(f"{defn.label}: no deliveries.")
        return EXIT_OK
    print(f"{defn.label}")
    print(f"  Email to       {', '.join(current.email) or '—'}")
    print(f"  Subject        {current.subject or defn.label}")
    print(f"  Telegram       {current.telegram_label or '—'}")
    print(f"  Attach as      {current.attach}")
    print(f"  If a run fails {current.on_failure}")
    print(f"  Command        {current.command or '—'}")
    return EXIT_OK


def _cmd_agents_resend(args, root) -> int:
    from whyline.agents import service

    results = service.resend(args.name, root, args.run_id)
    print(_delivery_lines(results) or "Nothing was sent: no deliveries set.")
    return EXIT_OK if all(r["ok"] for r in results) else EXIT_ERROR


def _cmd_agents_telegram(args, *, input_fn=input, getpass_fn=getpass.getpass) -> int:
    from whyline.agents import telegram

    if args.telegram_command == "chats":
        chats = telegram.known_chats()
        if not chats:
            print("No Telegram chats yet. Run: whyline agents telegram setup")
        for cid, label in chats.items():
            print(f"{label}  ({cid})")
        return EXIT_OK
    print("1. In Telegram, open @BotFather (https://t.me/BotFather), send /newbot,")
    print("   choose a name, and copy the token it gives you.")
    token = getpass_fn("2. Paste the bot token (hidden): ").strip()
    try:
        bot = telegram.check_token(token)
        telegram.token_set(token)
    except telegram.TelegramError as error:
        print(f"error: {telegram.redact(str(error), token)}", file=sys.stderr)
        return EXIT_ERROR
    print(f"   Connected to {bot}. The token is saved on this Mac.")
    while True:
        input_fn(f"3. Send any message to {bot}, or add it to a group, then press Enter. ")
        try:
            chats = telegram.remember_chats(telegram.find_chats(token))
        except telegram.TelegramError as error:
            print(f"error: {telegram.redact(str(error), token)}", file=sys.stderr)
            return EXIT_ERROR
        if chats:
            print("   Chats found:")
            for cid, label in chats.items():
                print(f"   - {label}")
            print("4. Done. Choose a chat for an agent with:")
            print('   whyline agents deliver <name> --telegram "<chat>"')
            return EXIT_OK
        print("   No messages yet. Send one to the bot and try again.")
```

In `cmd_agents`, before `root = _repo_root_or_none()`:

```python
    if args.agents_command == "telegram":
        return _cmd_agents_telegram(args)
```

and inside the `try:` with the other commands:

```python
        if args.agents_command == "deliver":
            return _cmd_agents_deliver(args, root)
        if args.agents_command == "resend":
            return _cmd_agents_resend(args, root)
```

Change the `history` line to add the delivery status:

```python
        if args.agents_command == "history":
            from whyline.agents import deliver

            for r in service.history(args.name, root, args.n):
                status = deliver.status_text(r)
                line = f"{r.started[:16].replace('T', ' ')}  {r.source:<9} {r.cli:<12} {r.outcome}"
                print(f"{line}  {status}" if status else line)
            return EXIT_OK
```


- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/agents/test_cli_deliver.py -q && uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline/cli.py tests/agents/test_cli_deliver.py
git commit -m "feat: whyline agents deliver, resend and telegram setup (DL-6)"
```

---

### Task 7: Console — Telegram setup screen, delivery status and Resend in Runs

**Files:**
- Modify: `src/whyline/console/agents_screens.py` (add `TelegramSetupScreen`; `RunsScreen` gains a Delivered column, an `on_resend` callback and a **Resend** button)
- Modify: `src/whyline/console/tui.py` (`_open_runs` passes `on_resend`; add `_agent_resend`)
- Test: `tests/console/test_agent_deliveries_console.py`

**Interfaces:**
- Consumes: `telegram.token_get`, `telegram.check_token`, `telegram.token_set`, `telegram.find_chats`, `telegram.remember_chats`, `telegram.known_chats`, `telegram.send_message` (Task 3); `deliver.status_text` (Task 5); `service.resend` (Task 5).
- Produces: `TelegramSetupScreen()` (dismisses with `dict[int, str]`, the known chats); `RunsScreen(label, runs, on_resend=None)`; `WhylineConsoleApp._agent_resend(name: str, run_id: str) -> None`. Widget ids: `#tg-open`, `#tg-token`, `#tg-check`, `#tg-bot`, `#tg-chats`, `#tg-chat`, `#tg-test`, `#tg-done`; `#rs-resend`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/console/test_agent_deliveries_console.py
from types import SimpleNamespace

import pytest

from whyline.agents import service, telegram
from whyline.console import tui
from whyline.console.agents_screens import RunsScreen, TelegramSetupScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


async def _until(pilot, condition, what):
    for _ in range(400):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


@pytest.fixture
def fake_telegram(monkeypatch):
    state = {"token": None, "chats": {}, "sent": []}
    monkeypatch.setattr(telegram, "token_get", lambda: state["token"])
    monkeypatch.setattr(telegram, "check_token", lambda token: "@JobsBot")
    monkeypatch.setattr(telegram, "token_set", lambda token: state.update(token=token))
    monkeypatch.setattr(telegram, "find_chats", lambda token: {11: "Anish V (private)"})
    monkeypatch.setattr(telegram, "remember_chats", lambda chats: state["chats"].update(chats) or state["chats"])
    monkeypatch.setattr(telegram, "known_chats", lambda: dict(state["chats"]))
    monkeypatch.setattr(telegram, "send_message",
                        lambda token, chat, text, label="": state["sent"].append((chat, text)))
    return state


async def test_telegram_setup_checks_finds_chats_and_tests(tmp_path, fake_telegram):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        result = []
        app.push_screen(TelegramSetupScreen(), result.append)
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup shown")
        screen = app.screen
        screen.query_one("#tg-token", tui.Input).value = "123:secret"
        screen.query_one("#tg-check", tui.Button).press()
        await _until(pilot, lambda: "Connected to @JobsBot" in str(screen.query_one("#tg-bot").renderable),
                     "connected")
        assert fake_telegram["token"] == "123:secret"
        await _until(pilot, lambda: "Anish V (private)" in str(screen.query_one("#tg-chats").renderable),
                     "chat found")
        screen.query_one("#tg-test", tui.Button).press()
        await _until(pilot, lambda: fake_telegram["sent"], "test sent")
        assert fake_telegram["sent"][0][0] == 11
        for button in ("#tg-check", "#tg-test", "#tg-done"):
            region = screen.query_one(button).region
            assert region.right <= 80 and region.bottom <= 24
        screen.query_one("#tg-done", tui.Button).press()
        await _until(pilot, lambda: result, "dismissed")
        assert result[0] == {11: "Anish V (private)"}


async def test_a_rejected_token_shows_the_error(tmp_path, fake_telegram, monkeypatch):
    def reject(token):
        raise telegram.TelegramError("the bot token was rejected; run Telegram setup again")

    monkeypatch.setattr(telegram, "check_token", reject)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(TelegramSetupScreen())
        await _until(pilot, lambda: isinstance(app.screen, TelegramSetupScreen), "setup shown")
        app.screen.query_one("#tg-token", tui.Input).value = "bad"
        app.screen.query_one("#tg-check", tui.Button).press()
        await _until(pilot, lambda: "rejected" in str(app.screen.query_one("#tg-bot").renderable),
                     "error shown")
        assert fake_telegram["token"] is None


async def test_runs_show_delivery_status_and_resend(tmp_path, monkeypatch):
    run = SimpleNamespace(run_id="r1", started="2026-10-09T07:00:00", source="schedule", cli="codex",
                          used_backup=None, outcome="succeeded",
                          deliveries=[{"to": "email", "ok": True, "detail": ""},
                                      {"to": "telegram", "ok": False, "detail": "no connection to Telegram"}])
    resent = []
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(RunsScreen("jobs (personal)", [run], on_resend=resent.append))
        await _until(pilot, lambda: isinstance(app.screen, RunsScreen), "runs shown")
        table = app.screen.query_one("#rs-runs")
        assert "telegram ✗" in str(table.get_row_at(0)[-1])
        app.screen.query_one("#rs-resend", tui.Button).press()
        await _until(pilot, lambda: resent == ["r1"], "resend called")
```

- [ ] **Step 2: Run and verify they fail**

Run: `uv run pytest tests/console/test_agent_deliveries_console.py -q`
Expected: FAIL with `ImportError: cannot import name 'TelegramSetupScreen'`.

- [ ] **Step 3: Implement `TelegramSetupScreen`**

Add to `src/whyline/console/agents_screens.py` (with `import webbrowser` at the top and `Input`, `Select`, `Static`, `Label`, `Button`, `Vertical`, `Horizontal` already imported there):

```python
class TelegramSetupScreen(ModalScreen):
    """One-time Telegram set-up (deliveries spec 9). Dismisses with the
    chats known afterwards. Network calls run in worker threads."""

    DEFAULT_CSS = _CSS.format(name="TelegramSetupScreen") + """
    TelegramSetupScreen Static { height: auto; }
    TelegramSetupScreen Input { width: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._token: str | None = None
        self._poller = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Set up Telegram (once per Mac)"),
            Static("1. In Telegram, open @BotFather, send /newbot, choose a name, copy the token.",
                   markup=False),
            Horizontal(Button("Open BotFather", id="tg-open")),
            Horizontal(Input(placeholder="2. Paste the bot token", password=True, id="tg-token"),
                       Button("Check", id="tg-check")),
            Static("", id="tg-bot", markup=False),
            Static("3. Send any message to your bot, or add it to a group.", markup=False),
            Static("", id="tg-chats", markup=False),
            Horizontal(Select([], prompt="Chat to test", id="tg-chat"),
                       Button("Send test message", id="tg-test"),
                       Button("Done", id="tg-done", variant="primary")),
        )

    def on_mount(self) -> None:
        from whyline.agents import telegram

        self._token = telegram.token_get()
        if self._token:
            self.query_one("#tg-bot", Static).update(
                "A bot is already set up on this Mac. Paste a new token only to replace it.")
            self._start_polling()
        self._show_chats(telegram.known_chats())

    def _show_chats(self, chats: dict[int, str]) -> None:
        self.query_one("#tg-chats", Static).update(
            "Found: " + ", ".join(chats.values()) if chats else "Waiting for a message…")
        select = self.query_one("#tg-chat", Select)
        current = select.value
        select.set_options([(label, cid) for cid, label in chats.items()])
        if chats:
            select.value = current if current in chats else next(iter(chats))

    def _start_polling(self) -> None:
        if self._poller is None:
            self._poll()
            self._poller = self.set_interval(3, self._poll)

    def _poll(self) -> None:
        token = self._token
        if not token:
            return

        def work() -> None:
            from whyline.agents import telegram

            try:
                chats = telegram.remember_chats(telegram.find_chats(token))
            except Exception:
                return
            self.app.call_from_thread(self._show_chats, chats)

        self.app.run_worker(work, thread=True, exclusive=True, group="tg-poll")

    def _check(self) -> None:
        token = self.query_one("#tg-token", Input).value.strip()
        if not token:
            return
        self.query_one("#tg-bot", Static).update("Checking…")

        def work() -> None:
            from whyline.agents import telegram

            try:
                bot = telegram.check_token(token)
                telegram.token_set(token)
            except Exception as error:
                text = telegram.redact(str(error), token)
                self.app.call_from_thread(self.query_one("#tg-bot", Static).update, text)
                return

            def done() -> None:
                self._token = token
                self.query_one("#tg-bot", Static).update(f"Connected to {bot}. Saved on this Mac.")
                self._start_polling()

            self.app.call_from_thread(done)

        self.app.run_worker(work, thread=True)

    def _test(self) -> None:
        chat = self.query_one("#tg-chat", Select).value
        token = self._token
        if not token or not isinstance(chat, int):
            return

        def work() -> None:
            from whyline.agents import telegram

            try:
                telegram.send_message(token, chat, "Test from whyline: Telegram is set up.")
                text = "Test message sent."
            except Exception as error:
                text = telegram.redact(str(error), token)
            self.app.call_from_thread(self.query_one("#tg-bot", Static).update, text)

        self.app.run_worker(work, thread=True)

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        event.stop()
        button_id = event.button.id
        if button_id == "tg-open":
            webbrowser.open("https://t.me/BotFather")
        elif button_id == "tg-check":
            self._check()
        elif button_id == "tg-test":
            self._test()
        elif button_id == "tg-done":
            from whyline.agents import telegram

            if self._poller is not None:
                self._poller.stop()
            self.dismiss(telegram.known_chats())
```

- [ ] **Step 4: Runs view: status column and Resend**

Change `RunsScreen` in `agents_screens.py`:

```python
    def __init__(self, label: str, runs, on_resend=None) -> None:
        super().__init__()
        self._label, self._runs, self._on_resend = label, runs, on_resend

    def compose(self) -> ComposeResult:
        from whyline.agents import deliver

        table = DataTable(id="rs-runs", cursor_type="row")
        table.add_columns("When", "Trigger", "CLI", "Outcome", "Delivered")
        for run in self._runs:
            cli = run.cli + (" (backup)" if run.used_backup else "")
            table.add_row(run.started[:16].replace("T", " "), run.source, cli, run.outcome,
                          deliver.status_text(run), key=run.run_id)
        buttons = [Button("Show log", id="rs-log")]
        if self._on_resend is not None:
            buttons.append(Button("Resend", id="rs-resend"))
        buttons.append(Button("Close", id="rs-close"))
        yield Vertical(
            Label(f"Runs of {self._label}" if self._runs else f"{self._label} has not run yet."),
            table,
            VerticalScroll(Static("", id="rs-text", markup=False)),
            Horizontal(*buttons),
        )
```

and in its `on_button_pressed`, before the `rs-log` branch:

```python
        if event.button.id == "rs-resend":
            run_id = self._selected()
            if run_id and self._on_resend is not None:
                self._on_resend(run_id)
                self._show("Resending…")
            return
```

- [ ] **Step 5: Wire Resend in `tui.py`**

In `_open_runs`, replace the push with:

```python
        self.push_screen(RunsScreen(
            row.defn.label, runs, on_resend=lambda run_id: self._agent_resend(name, run_id)))
```

Add:

```python
    def _agent_resend(self, name: str, run_id: str) -> None:
        from whyline.agents import service

        root = self.session.root

        def work() -> None:
            try:
                results = service.resend(name, root, run_id)
                text = "  ".join(
                    f"{r['to']} {'✓' if r['ok'] else '✗'}" + ("" if r["ok"] else f" {r['detail']}")
                    for r in results) or "Nothing was sent: no deliveries set."
                event = SessionEvent(kind="output", text=f"{name}: resent — {text}")
            except Exception as error:
                event = SessionEvent(kind="error", text=str(error))
            self.call_from_thread(self.render_event, event)

        self.run_worker(work, thread=True)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/console -q && uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/whyline/console/agents_screens.py src/whyline/console/tui.py tests/console/test_agent_deliveries_console.py
git commit -m "feat: Telegram setup screen and delivery status with Resend in Runs (DL-7)"
```

---

### Task 8: Console — "Deliver to" in the agent form, Review sentence and Send test

**Files:**
- Modify: `src/whyline/console/agents_screens.py` (`NewAgentScreen` fields, `AgentForm` result, Send test)
- Modify: `src/whyline/console/tui.py` (`_new_agent_done` saves the delivery; Review text; renamed agents)
- Test: `tests/console/test_new_agent_deliveries.py`

**Interfaces:**
- Consumes: `deliveries.Delivery`, `deliveries.get`, `deliveries.save`, `deliveries.remove`, `deliveries.parse_emails`, `deliveries.validate`, `deliveries.DeliveryError` (Task 1); `telegram.known_chats` (Task 3); `deliver.describe`, `deliver.send_test` (Task 5); `TelegramSetupScreen` (Task 7).
- Produces: `@dataclass AgentForm(defn: AgentDef, delivery: Delivery)`. `NewAgentScreen(root, status, existing=None, delivery: Delivery | None = None)` now dismisses with an `AgentForm` or `None` (it used to dismiss with an `AgentDef`); `delivery`, when given, prefills the Deliver to fields (used when Review's **Back** reopens the form). Widget ids: `#na-email`, `#na-subject`, `#na-telegram`, `#na-telegram-setup`, `#na-attach`, `#na-on-failure`, `#na-command`, `#na-send-test`, `#na-test-result`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/console/test_new_agent_deliveries.py
import json

import pytest

from whyline.agents import deliver, deliveries as dl, definitions as d, telegram
from whyline.console import tui
from whyline.console.agents_screens import AgentForm, NewAgentScreen

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


async def _until(pilot, condition, what):
    for _ in range(400):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never happened: {what}")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    monkeypatch.setattr(telegram, "known_chats", lambda: {-100: "Family (group)"})
    return folder


def _fill_basic(screen, work):
    screen.query_one("#na-kind", tui.Select).value = "personal"
    screen.query_one("#na-name", tui.Input).value = "jobs"
    screen.query_one("#na-instructions").text = "Scan."
    screen.query_one("#na-workdir", tui.Input).value = str(work)


async def _open_form(app, pilot, existing=None):
    result = []
    app.push_screen(NewAgentScreen(app.session.root, {}, existing=existing), result.append)
    await _until(pilot, lambda: isinstance(app.screen, NewAgentScreen), "form shown")
    return result


async def test_the_form_returns_the_delivery(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        result = await _open_form(app, pilot)
        screen = app.screen
        _fill_basic(screen, work)
        screen.query_one("#na-email", tui.Input).value = "a@example.com, b@example.com"
        screen.query_one("#na-subject", tui.Input).value = "Daily jobs"
        screen.query_one("#na-telegram", tui.Select).value = -100
        screen.query_one("#na-attach", tui.Select).value = "docx"
        screen.query_one("#na-on-failure", tui.Select).value = "alert"
        screen.query_one("#na-next", tui.Button).press()
        await _until(pilot, lambda: result, "submitted")
        form = result[0]
        assert isinstance(form, AgentForm) and form.defn.name == "jobs"
        assert form.delivery == dl.Delivery(email=("a@example.com", "b@example.com"),
                                            subject="Daily jobs", telegram_chat=-100,
                                            telegram_label="Family (group)")


async def test_a_bad_address_is_shown_in_the_form(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        result = await _open_form(app, pilot)
        _fill_basic(app.screen, work)
        app.screen.query_one("#na-email", tui.Input).value = "nope"
        app.screen.query_one("#na-next", tui.Button).press()
        await _until(pilot, lambda: "not an email address" in str(app.screen.query_one("#na-error").renderable),
                     "error shown")
        assert result == []


async def test_saving_writes_deliveries_and_review_mentions_them(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        text = f'name="jobs"\ninstructions="Scan."\nrunner="codex"\nworkdir={json.dumps(str(work))}\n'
        path = app.session.root / "jobs.toml"
        defn = d.parse(text, kind="personal", path=path)
        delivery = dl.Delivery(email=("a@example.com",))
        reviews = []
        from whyline.console import agents_screens

        real_review = agents_screens.ReviewScreen

        def capture(defn_, text_, scheduler_on):
            reviews.append(text_)
            return real_review(defn_, text_, scheduler_on)

        monkeypatch.setattr(agents_screens, "ReviewScreen", capture)
        app._new_agent_done(AgentForm(defn, delivery))
        await _until(pilot, lambda: reviews, "review shown")
        assert "email to a@example.com" in reviews[0]
        app.screen.query_one("#rv-save", tui.Button).press()
        await _until(pilot, lambda: dl.get(defn.agent_id) is not None, "delivery saved")


async def test_a_renamed_agent_moves_its_deliveries(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    old = d.parse(f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n',
                  kind="personal", path=tmp_path / "jobs.toml")
    dl.save(old.agent_id, dl.Delivery(email=("a@example.com",)))
    new = d.parse(f'name="jobs2"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n',
                  kind="personal", path=tmp_path / "jobs2.toml")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        app._editing_agent_id = old.agent_id
        app._new_agent_done(AgentForm(new, dl.Delivery(email=("a@example.com",))))
        await _until(pilot, lambda: app.screen.query("#rv-save"), "review shown")
        app.screen.query_one("#rv-save", tui.Button).press()
        await _until(pilot, lambda: dl.get(new.agent_id) is not None, "moved")
        assert dl.get(old.agent_id) is None


async def test_review_back_reopens_the_form_with_the_delivery(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    defn = d.parse(f'name="jobs"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n',
                   kind="personal", path=tmp_path / "jobs.toml")
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        app._new_agent_done(AgentForm(defn, dl.Delivery(email=("a@example.com",), subject="Daily")))
        await _until(pilot, lambda: app.screen.query("#rv-back"), "review shown")
        app.screen.query_one("#rv-back", tui.Button).press()
        await _until(pilot, lambda: isinstance(app.screen, NewAgentScreen), "form reopened")
        assert app.screen.query_one("#na-email", tui.Input).value == "a@example.com"
        assert app.screen.query_one("#na-subject", tui.Input).value == "Daily"


async def test_send_test_shows_each_result(tmp_path, monkeypatch):
    monkeypatch.setattr(deliver, "send_test", lambda label, delivery, **k: [
        {"to": "email", "ok": True, "detail": ""},
        {"to": "telegram", "ok": False, "detail": "the bot can't reach Family (group)"}])
    work = tmp_path / "work"
    work.mkdir()
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open_form(app, pilot)
        _fill_basic(app.screen, work)
        app.screen.query_one("#na-email", tui.Input).value = "a@example.com"
        app.screen.query_one("#na-send-test", tui.Button).press()
        await _until(pilot, lambda: "telegram ✗" in str(app.screen.query_one("#na-test-result").renderable),
                     "results shown")
        assert "email ✓" in str(app.screen.query_one("#na-test-result").renderable)
```

- [ ] **Step 2: Run and verify they fail**

Run: `uv run pytest tests/console/test_new_agent_deliveries.py -q`
Expected: FAIL with `ImportError: cannot import name 'AgentForm'`.

- [ ] **Step 3: `AgentForm` and the form fields**

In `agents_screens.py`, add near the top (after imports):

```python
from dataclasses import dataclass

from whyline.agents import deliveries as dl


@dataclass(frozen=True)
class AgentForm:
    defn: d.AgentDef
    delivery: dl.Delivery
```

`NewAgentScreen.__init__` gains `delivery: dl.Delivery | None = None` and stores it as `self._delivery_in = delivery`. In `NewAgentScreen.compose`, before the `Static("", id="na-error", ...)`, add (with `existing_delivery` read at the start of `compose`):

```python
        try:
            existing_delivery = self._delivery_in or (
                dl.get(existing.agent_id) if existing else None) or dl.Delivery()
        except dl.DeliveryError:
            existing_delivery = dl.Delivery()
        from whyline.agents import telegram

        chats = telegram.known_chats()
        chat_options = [("None", 0)] + [(label, cid) for cid, label in chats.items()]
        chat_value = existing_delivery.telegram_chat if existing_delivery.telegram_chat in chats else 0
```

and the rows:

```python
            Label("Deliver to"),
            HorizontalGroup(
                Label("Email to", classes="field-label"),
                Input(", ".join(existing_delivery.email), id="na-email",
                      placeholder="optional; comma-separated"),
            ),
            HorizontalGroup(
                Label("Subject", classes="field-label"),
                Input(existing_delivery.subject, id="na-subject", placeholder="the agent's name"),
            ),
            HorizontalGroup(
                Label("Telegram", classes="field-label"),
                Select(chat_options, value=chat_value, allow_blank=False, id="na-telegram"),
                Button("Set up Telegram…", id="na-telegram-setup"),
            ),
            HorizontalGroup(
                Label("Attach as", classes="field-label"),
                Select([("Word (.docx)", "docx"), ("Markdown (.md)", "md")],
                       value=existing_delivery.attach, allow_blank=False, id="na-attach"),
            ),
            HorizontalGroup(
                Label("If a run fails", classes="field-label"),
                Select([("Send a short alert", "alert"), ("Stay silent", "silent")],
                       value=existing_delivery.on_failure, allow_blank=False, id="na-on-failure"),
            ),
            HorizontalGroup(
                Label("After each run", classes="field-label"),
                Input(existing_delivery.command, id="na-command",
                      placeholder="advanced: a command; runs on this Mac only"),
            ),
            HorizontalGroup(
                Button("Send test", id="na-send-test"),
                Static("", id="na-test-result", markup=False),
            ),
```

- [ ] **Step 4: Build the delivery, submit, Send test and Telegram setup**

Add to `NewAgentScreen`:

```python
    def _delivery(self) -> dl.Delivery:
        from whyline.agents import telegram

        chat = self.query_one("#na-telegram", Select).value
        chat = chat if isinstance(chat, int) else 0
        return dl.Delivery(
            email=dl.parse_emails(self.query_one("#na-email", Input).value),
            subject=self.query_one("#na-subject", Input).value.strip(),
            telegram_chat=chat,
            telegram_label=telegram.known_chats().get(chat, "") if chat else "",
            attach=self._choice("#na-attach") or "docx",
            on_failure=self._choice("#na-on-failure") or "alert",
            command=self.query_one("#na-command", Input).value.strip(),
        )

    def _send_test(self) -> None:
        from whyline.agents import deliver

        try:
            delivery = self._delivery()
            dl.validate(delivery)
        except dl.DeliveryError as error:
            self.query_one("#na-test-result", Static).update(str(error))
            return
        label = (self.query_one("#na-name", Input).value.strip() or "this agent")
        self.query_one("#na-test-result", Static).update("Sending…")

        def work() -> None:
            try:
                results = deliver.send_test(label, delivery)
                text = "  ".join(f"{r['to']} {'✓' if r['ok'] else '✗'}"
                                 + ("" if r["ok"] else f" {r['detail']}") for r in results)
                text = text or "Nothing to test: choose an email, Telegram chat or command."
            except Exception as error:
                text = str(error)
            self.app.call_from_thread(self.query_one("#na-test-result", Static).update, text)

        self.app.run_worker(work, thread=True)

    def _telegram_setup(self) -> None:
        from whyline.console.agents_screens import TelegramSetupScreen

        def done(chats) -> None:
            if not isinstance(chats, dict):
                return
            select = self.query_one("#na-telegram", Select)
            current = select.value
            select.set_options([("None", 0)] + [(label, cid) for cid, label in chats.items()])
            select.value = current if current in chats else (next(iter(chats)) if chats else 0)

        self.app.push_screen(TelegramSetupScreen(), done)
```

In `on_button_pressed`, add:

```python
        elif button_id == "na-send-test":
            self._send_test()
        elif button_id == "na-telegram-setup":
            self._telegram_setup()
```

In `_submit`, after the name check, replace `self.dismiss(defn)` with:

```python
        try:
            delivery = self._delivery()
            from whyline.agents import telegram

            dl.validate(delivery, set(telegram.known_chats()))
        except dl.DeliveryError as error:
            self._show_error(str(error))
            return
        self.dismiss(AgentForm(defn, delivery))
```

- [ ] **Step 5: Save the delivery in `tui.py`**

`_open_new_agent` records which agent is being edited:

```python
    def _open_new_agent(self, existing=None, delivery=None, *, editing_id=None) -> None:
        from whyline import account
        from whyline.console.agents_screens import NewAgentScreen

        if editing_id is None:
            editing_id = existing.agent_id if existing is not None else None
        self._editing_agent_id = editing_id
        self.push_screen(
            NewAgentScreen(self.session.root, account.agent_status(self.session.root),
                           existing=existing, delivery=delivery),
            self._new_agent_done,
        )
```

Initialise `self._editing_agent_id: str | None = None` in `WhylineConsoleApp.__init__`.

`_new_agent_done` takes the `AgentForm`:

```python
    def _new_agent_done(self, form) -> None:
        if form is None:
            return
        from whyline.agents import deliver, deliveries, service, telegram
        from whyline.console import agents_screens

        defn, delivery = form.defn, form.delivery
        old_id = getattr(self, "_editing_agent_id", None)

        def decided(choice) -> None:
            if choice != "save":
                # Back: reopen the form with everything that was typed,
                # still editing the agent that was opened.
                self._open_new_agent(existing=defn, delivery=delivery, editing_id=old_id)
                return
            try:
                service.save_new(defn)
                deliveries.save(defn.agent_id, delivery, known_chats=set(telegram.known_chats()))
                if old_id and old_id != defn.agent_id:
                    deliveries.remove(old_id)
            except Exception as error:
                self.render_event(SessionEvent(kind="error", text=str(error)))
                return
            shown = defn.path.as_posix().replace(str(Path.home()), "~")
            self.render_event(SessionEvent(
                kind="output",
                text=f"Saved {defn.label} ({shown}) and accepted it on this Mac.",
            ))
            self._editing_agent_id = None
            self._refresh_agents_status()

        text = service.describe(defn)
        extra = deliver.describe(delivery)
        if extra:
            text = text.rstrip() + " " + extra
        self.push_screen(
            agents_screens.ReviewScreen(defn, text, self._scheduler_on()),
            decided,
        )
```

Keep whatever the existing `_new_agent_done` did after saving beyond these lines (for example refreshing the list or status); copy those calls into `decided`. Existing tests that dismissed `NewAgentScreen` with an `AgentDef`, or called `_new_agent_done(defn)`, must be updated to use `AgentForm(defn, Delivery())`, keeping what they check.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/console -q && uv run pytest -q`
Expected: PASS. The form is taller now; it already scrolls (`overflow-y: auto`), so 80×24 still reaches every field.

- [ ] **Step 7: Commit**

```bash
git add src/whyline/console/agents_screens.py src/whyline/console/tui.py tests/console
git commit -m "feat: Deliver to section, Review sentence and Send test in the agent form (DL-8)"
```

---

### Task 9: Release whyline 0.3.38 (human)

Before tagging, on macOS: set up a real Telegram bot (`whyline agents telegram setup` or the console); set `govt-job-search` to deliver to an email address and the Telegram chat, Word attachment; **Run now** and confirm the summary and the `.docx` arrive by email and on Telegram, and `whyline agents history govt-job-search` shows `delivered: email ✓ telegram ✓`; set the agent's timeout to 1 minute, run again, confirm the short alert arrives in both and history shows `alert: …`; restore the timeout.

Then: bump to `0.3.38` in `pyproject.toml` and `src/whyline/__init__.py`, `uv lock`, write `docs/releases/v0.3.38.md`, run the suite with and without agent CLIs on `PATH`, build and check the sdist (no `/Users/` paths, no `.whyline/`, `docs/`, `plans/`), push `main`, tag `v0.3.38`, watch the release workflow on all OSes, confirm PyPI, and install it.
