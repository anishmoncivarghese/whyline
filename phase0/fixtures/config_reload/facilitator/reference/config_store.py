from __future__ import annotations

import re
import threading


KEY_PATTERN = re.compile(r"^[A-Z_]+$")


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

    def reload(self, text: str) -> None:
        replacement: dict[str, str] = {}
        for line in text.splitlines():
            if not line:
                continue
            key, separator, value = line.partition("=")
            if not separator or not KEY_PATTERN.fullmatch(key):
                raise ValueError(f"Malformed configuration line: {line!r}")
            if key in replacement:
                raise ValueError(f"Duplicate configuration key: {key}")
            replacement[key] = value
        with self._lock:
            self._values = replacement

