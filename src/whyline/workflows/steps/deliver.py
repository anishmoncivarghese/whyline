"""The deliver step: send text to Telegram, email or a report file (spec section 4)."""
from __future__ import annotations

import os

from whyline.agents import deliver as agent_deliver
from whyline.agents import deliveries
from whyline.workflows.steps.basic import _render, _text


def _result(*args, **kwargs):
    from whyline.workflows.engine import StepResult
    return StepResult(*args, **kwargs)


def _allowed_chats() -> list[int]:
    from whyline.ideas import store, telegram_in
    return telegram_in.allowed_chats(store.connect())


def _chat(wanted: str) -> int | str:
    """The chat id to send to, or the failure text."""
    allowed = _allowed_chats()
    if not wanted:
        if len(allowed) == 1:
            return allowed[0]
        return "no default Telegram chat: allow exactly one inbox chat or set chat"
    try:
        chat = int(wanted)
    except ValueError:
        return f"chat {wanted} is not an allowed inbox chat"
    if chat not in allowed:
        return f"chat {wanted} is not an allowed inbox chat"
    return chat


def _write_report(ctx, text: str) -> str:
    from whyline.workflows import paths
    folder = paths.reports_dir(str(ctx.definition.get("name", "workflow")))
    folder.mkdir(parents=True, exist_ok=True)
    stamp = ctx.now.astimezone().strftime("%Y-%m-%d-%H%M")
    target = folder / f"{stamp}-{ctx.run['id']}.md"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(target, 0o600)
    return str(target)


def run_deliver(ctx, step, *, mail=None, tg=None):
    f = step.fields
    where = f["to"]
    text = _text(_render(f["text"], ctx))
    subject = _text(_render(f.get("subject") or "", ctx)).strip() \
        or str(ctx.definition.get("name", "workflow"))
    if where == "file":
        return _result("succeeded", {"to": "file", "path": _write_report(ctx, text)})
    if where == "telegram":
        chat = _chat(str(_render(f.get("chat") or "", ctx)))
        if isinstance(chat, str):
            return _result("failed", reason=chat)
        delivery = deliveries.Delivery(telegram_chat=chat)
    else:
        addresses = deliveries.parse_emails(str(_render(f.get("email") or "", ctx)))
        if not addresses:
            return _result("failed", reason="no email address to send to")
        try:
            deliveries.validate(deliveries.Delivery(email=addresses))
        except deliveries.DeliveryError as error:
            return _result("failed", reason=str(error))
        delivery = deliveries.Delivery(email=addresses)
    results = agent_deliver.send(delivery, subject, text, mail=mail, tg=tg)
    bad = [item for item in results if not item["ok"]]
    if bad:
        return _result("failed", reason=bad[0]["detail"] or f"{bad[0]['to']} send failed")
    return _result("succeeded", {"to": where, "sent": len(results)})


HANDLERS = {"deliver": run_deliver}
