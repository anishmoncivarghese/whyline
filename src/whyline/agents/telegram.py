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
    return paths.settings_file("telegram-token")


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
            ["security", "add-generic-password", "-U", "-s", _SERVICE, "-a", _ACCOUNT,
             "-w", token],
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
            body += (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\""
                f"\r\n\r\n{value}\r\n"
            ).encode("utf-8")
        for key, file_path in files.items():
            name = Path(file_path).name
            body += (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; "
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
                name = " ".join(
                    part for part in (chat.get("first_name"), chat.get("last_name")) if part
                )
                found[int(chat["id"])] = f"{name or 'Private chat'} (private)"
            else:
                found[int(chat["id"])] = f"{chat.get('title') or 'Group'} (group)"
            break
    return found


def _chats_file() -> Path:
    return paths.settings_file("telegram-chats.toml")


def known_chats() -> dict[int, str]:
    try:
        raw = tomllib.loads(_chats_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}
    return {int(key): str(value) for key, value in raw.get("chats", {}).items()}


def remember_chats(chats: dict[int, str]) -> dict[int, str]:
    merged = {**known_chats(), **chats}
    lines = ["[chats]"] + [
        f"{json.dumps(str(cid))} = {json.dumps(label, ensure_ascii=False)}"
        for cid, label in sorted(merged.items())
    ]
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
        _call("sendMessage", token, {"chat_id": chat_id, "text": text[:4096]},
              http=http, sleep=sleep)
    except _ChatError:
        raise TelegramError(f"the bot can't reach {label or chat_id}") from None
