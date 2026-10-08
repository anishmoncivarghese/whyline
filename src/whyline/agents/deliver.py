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
