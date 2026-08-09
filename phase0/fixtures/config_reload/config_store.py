from __future__ import annotations

import threading


class ConfigStore:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._lock = threading.Lock()
        self._values = dict(initial or {})

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._values)

