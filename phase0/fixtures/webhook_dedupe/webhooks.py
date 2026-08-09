from __future__ import annotations

from collections.abc import Callable


class WebhookProcessor:
    def __init__(self, handler: Callable[[dict], None]) -> None:
        self._handler = handler

    def process(self, event_id: str, payload: dict) -> bool:
        self._handler(payload)
        return True

