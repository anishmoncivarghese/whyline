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
