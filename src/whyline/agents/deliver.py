"""After a run: send its result where the agent's delivery settings say
(deliveries spec 2, 7, 8). Never raises; never changes the run's outcome."""
from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

from whyline.agents import convert, deliveries, mail_send, paths, quiet, records

COMMAND_TIMEOUT = 120
_SUCCEEDED = ("succeeded", "succeeded_with_denials")
_NO_RUN = ("nothing_new", "cancelled")
_NOT_STARTED = ("skipped", "missed")
MAX_HELD = 20
HOURLY = timedelta(hours=1)
NOTHING_NOTE = "nothing to report"
_NO_WORD = "(Word conversion isn't available on this computer, so the Markdown file is attached.)"


def _telegram():
    from whyline.agents import telegram
    return telegram


def subject_line(defn, delivery, record, *, failed: bool = False, word: str = "failed") -> str:
    base = delivery.subject.strip() or defn.label
    day = record.started[:10]
    return f"{base} {word} — {day}" if failed else f"{base} — {day}"


def _not_started_body(defn, record) -> str:
    if record.reason:
        return f"{defn.label} {record.outcome}: {record.reason}"
    if record.outcome == "missed":
        try:
            at = datetime.fromisoformat(record.started).strftime("%H:%M")
            run = f"the {at} run"
        except (TypeError, ValueError):
            run = "a run"
        return (f"{defn.label} missed {run}: the Mac was asleep or the scheduler was off.")
    return f"{defn.label} skipped a run: no reason given"


def _signature() -> str:
    name = platform.node().split(".")[0] or "this computer"
    return f"Sent by whyline from {name}."


def _is_brief(defn) -> bool:
    from whyline.ideas import brief
    return defn.name == brief.AGENT_NAME


def _attachment(defn, record, delivery) -> tuple[Path | None, str]:
    folder = records.run_folder(record.run_id)
    report = folder / "final.md"
    try:
        text = report.read_text(encoding="utf-8")
    except OSError:
        return None, ""
    if _is_brief(defn):
        from whyline.ideas import brief
        text = brief.split_actions(text)[0]
        report = folder / "delivered.md"
        report.write_text(text, encoding="utf-8")
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


def send(delivery, subject, body, attachment=None, *, mail=None, tg=None) -> list[dict]:
    """Send to the delivery's email addresses and Telegram chat; one result each."""
    mail = mail or mail_send.send
    tg = tg or _telegram()
    results = []
    if delivery.email:
        results.append(_email(delivery, subject, body, attachment, mail))
    if delivery.telegram_chat:
        results.append(_send_telegram(delivery, subject, body, attachment, tg))
    for result in results:
        if not result["ok"]:
            logging.getLogger(__name__).warning("%s delivery failed: %s", result["to"], result["detail"])
    return results


def _held_file() -> Path:
    return paths.settings_file("held.json")


def _load_held() -> dict:
    try:
        data = json.loads(_held_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    held, last = data.get("held"), data.get("last")
    return {"held": held if isinstance(held, dict) else {},
            "last": last if isinstance(last, dict) else {}}


def _save_held(data: dict) -> None:
    target = _held_file()
    temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        logging.getLogger(__name__).warning("could not save held deliveries")
        with contextlib.suppress(OSError):
            temporary.unlink()


_THREAD_LOCK = threading.RLock()


@contextlib.contextmanager
def _held_lock():
    """One writer at a time across threads and agent processes, held over the
    whole read, decide, send and write of the held list."""
    with _THREAD_LOCK:
        handle = None
        try:
            handle = open(_held_file().with_name("held.lock"), "a+b")
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            logging.getLogger(__name__).warning("could not lock held deliveries")
        try:
            yield
        finally:
            if handle is not None:
                handle.close()  # closing releases the lock


def _within_hour(data: dict, chat: int, now: datetime) -> bool:
    try:
        last = datetime.fromisoformat(str(data["last"][str(chat)]))
    except (KeyError, TypeError, ValueError):
        return False
    return timedelta(0) <= now - last < HOURLY


def _hold(data: dict, defn, delivery, subject, body, answer, attachment=None, *, email: bool,
          chat: bool, now: datetime) -> None:
    items = data["held"].setdefault(defn.agent_id, [])
    items.append({
        "name": defn.name, "label": defn.label, "subject": subject, "body": body,
        "answer": answer, "email": list(delivery.email) if email else [],
        "chat": delivery.telegram_chat if chat else 0,
        "chat_label": delivery.telegram_label, "at": now.isoformat(),
        "attachment": str(attachment) if attachment and email else "",
    })
    data["held"][defn.agent_id] = items[-MAX_HELD:]


def _route(defn, delivery, subject, body, attachment, answer, *, mail, tg, now) -> list[dict]:
    """Send now, or for a check-in agent hold by active hours and the hourly
    Telegram limit."""
    if not defn.gate:
        return send(delivery, subject, body, attachment, mail=mail, tg=tg)
    with _held_lock():
        return _route_gated(defn, delivery, subject, body, attachment, answer, mail=mail,
                            tg=tg, now=now)


def _route_gated(defn, delivery, subject, body, attachment, answer, *, mail, tg, now) -> list[dict]:
    data = _load_held()
    mail_fn = mail or mail_send.send
    tg = tg or _telegram()
    results = []
    if not quiet.active(defn.active_hours, now):
        _hold(data, defn, delivery, subject, body, answer, attachment, email=bool(delivery.email),
              chat=bool(delivery.telegram_chat), now=now)
        _save_held(data)
        at = quiet.next_start(defn.active_hours, now).strftime("%a %H:%M")
        return [_result("held", True, f"held until {at}")]
    if delivery.email:
        results.append(_email(delivery, subject, body, attachment, mail_fn))
    if delivery.telegram_chat:
        if _within_hour(data, delivery.telegram_chat, now):
            _hold(data, defn, delivery, subject, body, answer, email=False, chat=True, now=now)
            _save_held(data)
            results.append(_result("held", True, "held: one check-in message an hour"))
        else:
            sent = _send_telegram(delivery, subject, body, attachment, tg)
            results.append(sent)
            if sent["ok"]:
                data["last"][str(delivery.telegram_chat)] = now.isoformat()
                _save_held(data)
    for result in results:
        if not result["ok"]:
            logging.getLogger(__name__).warning("%s delivery failed: %s", result["to"], result["detail"])
    return results


def _first_lines(text: str, count: int = 5) -> str:
    return "\n".join(text.strip().splitlines()[:count])


def flush_held(now: datetime, known: dict, *, mail=None, tg=None) -> list[dict]:
    """Send held deliveries whose agent is inside active hours. Held items for
    one chat go as one message once the hour since its last check-in has
    passed. `known` maps agent_id to its definition. Never raises."""
    try:
        with _held_lock():
            return _flush_held(now, known, mail, tg)
    except Exception:
        logging.getLogger(__name__).exception("held deliveries failed")
        return []


def _flush_held(now, known, mail, tg) -> list[dict]:
    data = _load_held()
    if not data["held"]:
        return []
    mail_fn = mail or mail_send.send
    tg = tg or _telegram()
    results, chats = [], {}
    for agent_id, items in list(data["held"].items()):
        defn = known.get(agent_id)
        if defn is None or not quiet.active(defn.active_hours, now):
            continue
        keep = []
        for item in items:
            if item.get("notice"):
                sent = _flush_notice(defn, item, mail_fn, tg)
                results.extend(sent)
                if any(not result["ok"] for result in sent):
                    keep.append(item)
                continue
            if item.get("email"):
                delivery = deliveries.Delivery(email=tuple(item["email"]))
                saved = Path(item["attachment"]) if item.get("attachment") else None
                if saved is not None and not saved.is_file():
                    saved = None
                result = _email(delivery, item["subject"], item["body"], saved, mail_fn)
                results.append(result)
                if not result["ok"]:
                    keep.append({**item, "chat": item.get("chat", 0)})
                    continue
            if item.get("chat"):
                chats.setdefault(item["chat"], []).append((agent_id, item))
        data["held"][agent_id] = keep
    for chat, entries in chats.items():
        if _within_hour(data, chat, now):
            for agent_id, item in entries:
                data["held"][agent_id].append({**item, "email": []})
            continue
        body = "\n\n".join(f"{item['label']}\n{_first_lines(item['answer'])}"
                            for _, item in entries)
        delivery = deliveries.Delivery(telegram_chat=chat,
                                       telegram_label=entries[0][1].get("chat_label", ""))
        result = _send_telegram(delivery, "While you were away:", body, None, tg)
        results.append(result)
        if result["ok"]:
            data["last"][str(chat)] = now.isoformat()
        else:
            for agent_id, item in entries:
                data["held"][agent_id].append({**item, "email": []})
    data["held"] = {k: v[-MAX_HELD:] for k, v in data["held"].items() if v}
    _save_held(data)
    return results


def _notice_env(defn, text: str) -> dict:
    return {
        "WHYLINE_AGENT": defn.name, "WHYLINE_AGENT_LABEL": defn.label,
        "WHYLINE_OUTCOME": "notice", "WHYLINE_REASON": "", "WHYLINE_RUN_ID": "",
        "WHYLINE_REPORT": "", "WHYLINE_ATTACHMENT": "", "WHYLINE_SUMMARY": text,
    }


def _flush_notice(defn, item: dict, mail_fn, tg) -> list[dict]:
    """Send one held notice by itself: with its own subject, outside the hourly
    limit, and through every delivery it was held for."""
    results = []
    subject, text = item["subject"], item["body"]
    if item.get("email"):
        delivery = deliveries.Delivery(email=tuple(item["email"]))
        results.append(_email(delivery, subject, text, None, mail_fn))
    if item.get("chat"):
        delivery = deliveries.Delivery(telegram_chat=item["chat"],
                                       telegram_label=item.get("chat_label", ""))
        results.append(_send_telegram(delivery, subject, text, None, tg))
    if item.get("command"):
        delivery = deliveries.Delivery(command=item["command"])
        results.append(_command(delivery, _notice_env(defn, text), defn.root, None, subprocess.run))
    return results


def notice(defn, text: str, *, now: datetime, urgent: bool = False, held_ok: bool = True,
           delivery=None, mail=None, tg=None, run=subprocess.run) -> list[dict]:
    """Send plain text through the agent's delivery. It is outside the hourly
    check-in limit. Outside active hours it is held for the next active hour
    unless `urgent` (or `held_ok` is False, when holding is not acceptable).
    Never raises."""
    try:
        if delivery is None:
            delivery = deliveries.get(defn.agent_id)
        text = (text or "").strip()
        if delivery is None or delivery.empty or not text:
            return []
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        subject = f"{defn.name}: {first}"[:200]
        hold = held_ok and not urgent and not quiet.active(defn.active_hours, now)
        results = []
        if hold:
            with _held_lock():
                data = _load_held()
                _hold(data, defn, delivery, subject, text, text, email=bool(delivery.email),
                      chat=bool(delivery.telegram_chat), now=now)
                data["held"][defn.agent_id][-1].update(
                    {"notice": True, "command": delivery.command})
                _save_held(data)
            at = quiet.next_start(defn.active_hours, now).strftime("%a %H:%M")
            results.append(_result("held", True, f"held until {at}"))
        else:
            if delivery.email:
                results.append(_email(delivery, subject, text, None, mail or mail_send.send))
            if delivery.telegram_chat:
                results.append(_send_telegram(delivery, subject, text, None, tg or _telegram()))
            if delivery.command:
                results.append(_command(delivery, _notice_env(defn, text), defn.root, None, run))
        for result in results:
            if not result["ok"]:
                logging.getLogger(__name__).warning("%s delivery failed: %s", result["to"],
                                                    result["detail"])
        return results
    except Exception:
        logging.getLogger(__name__).exception("notice failed")
        return []


def after_run(defn, record, *, delivery=None, mail=None, tg=None, run=subprocess.run,
              now: datetime | None = None) -> list[dict]:
    now = now or datetime.now().replace(microsecond=0)
    if getattr(defn, "watch", None) is not None and (
            record.outcome in _SUCCEEDED or record.outcome in _NO_RUN):
        # A watch run sends its own message (the runner calls notice), so a hit
        # is sent once. A failed run still alerts below.
        return []
    if delivery is None:
        try:
            delivery = deliveries.get(defn.agent_id)
        except deliveries.DeliveryError:
            return []
    if delivery is None or delivery.empty or record.outcome in _NO_RUN:
        return []
    succeeded = record.outcome in _SUCCEEDED
    not_started = record.outcome in _NOT_STARTED
    attachment, report_path, text = None, "", ""
    if succeeded:
        try:
            text = records.read_final(record.run_id)
        except OSError:
            text = ""
        if defn.gate and defn.silent and quiet.is_nothing(text):
            record.deliveries = []
            record.reason = NOTHING_NOTE
            try:
                records.save_metadata(record)
            except OSError:
                pass
            return []
        attachment, note = _attachment(defn, record, delivery)
        if _is_brief(defn):
            from whyline.ideas import brief
            text = brief.split_actions(text)[0]
        report_path = str(records.run_folder(record.run_id) / "final.md")
        body = convert.summary(text) + (f"\n{note}" if note else "")
        subject = subject_line(defn, delivery, record)
    elif not_started:
        body = _not_started_body(defn, record)
        subject = subject_line(defn, delivery, record, failed=True, word=record.outcome)
    else:
        body = f"{defn.label} {record.outcome}: {record.reason or 'no reason given'}"
        subject = subject_line(defn, delivery, record, failed=True)
    results = []
    if succeeded or delivery.on_failure == "alert":
        results += _route(defn, delivery, subject, body, attachment,
                          text if succeeded else body, mail=mail, tg=tg, now=now)
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
    if succeeded and _is_brief(defn):
        try:
            from whyline.ideas import brief
            made = brief.after_delivery(record, chat_id=delivery.telegram_chat or None)
        except Exception as error:  # cards are a bonus; never change the run
            made = _result("brief-actions", False, str(error))
        if made:
            results.append(made)
    record.deliveries = results
    try:
        records.save_metadata(record)
    except OSError:
        pass
    return results


def missed(defn, due_at, next_run=None, *, delivery=None, mail=None, tg=None,
           now: datetime | None = None) -> list[dict]:
    """Alert that the scheduler recorded a missed occurrence. Never raises."""
    try:
        if delivery is None:
            delivery = deliveries.get(defn.agent_id)
        if delivery is None or delivery.empty or delivery.on_failure != "alert":
            return []
        try:
            run = f"the {datetime.fromisoformat(str(due_at)).strftime('%H:%M')} run"
        except (TypeError, ValueError):
            run = "a run"
        body = f"{defn.label} missed {run}: the Mac was asleep or the scheduler was off."
        if next_run is not None:
            body += f" The next run is {next_run.strftime('%a %d %b %H:%M')}."
        base = delivery.subject.strip() or defn.label
        return _route(defn, delivery, f"{base} missed", body, None, body, mail=mail, tg=tg,
                      now=now or datetime.now().replace(microsecond=0))
    except Exception:
        logging.getLogger(__name__).exception("missed-run alert failed")
        return []


def start_failed(defn, error, *, delivery=None, mail=None, tg=None,
                 now: datetime | None = None) -> list[dict]:
    """Alert that a due agent could not start. Never raises."""
    try:
        if delivery is None:
            delivery = deliveries.get(defn.agent_id)
        if delivery is None or delivery.empty or delivery.on_failure != "alert":
            return []
        text = " ".join(str(error).split()) or type(error).__name__
        body = (f"{defn.label} could not start: {text}. "
                "Run whyline doctor or open the console's Check.")
        base = delivery.subject.strip() or defn.label
        return _route(defn, delivery, f"{base} could not start", body, None, body, mail=mail,
                      tg=tg, now=now or datetime.now().replace(microsecond=0))
    except Exception:
        logging.getLogger(__name__).exception("start-failure alert failed")
        return []


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
