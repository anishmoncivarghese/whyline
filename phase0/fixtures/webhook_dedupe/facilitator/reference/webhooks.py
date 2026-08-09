from __future__ import annotations

from collections.abc import Callable
import threading


class WebhookProcessor:
    def __init__(self, handler: Callable[[dict], None]) -> None:
        self._handler = handler
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def process(self, event_id: str, payload: dict) -> bool:
        with self._lock:
            if event_id in self._seen:
                return False
            self._seen.add(event_id)
        try:
            self._handler(payload)
        except BaseException:
            with self._lock:
                self._seen.remove(event_id)
            raise
        return True

