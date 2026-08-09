from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any


class MemoryCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._values: dict[str, Any] = {}
        self._expiries: dict[str, float] = {}

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        if ttl_seconds is not None and ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        self._values[key] = value
        if ttl_seconds is None:
            self._expiries.pop(key, None)
        else:
            self._expiries[key] = self._clock() + ttl_seconds

    def get(self, key: str) -> Any | None:
        expires_at = self._expiries.get(key)
        if expires_at is not None and self._clock() >= expires_at:
            self._values.pop(key, None)
            self._expiries.pop(key, None)
            return None
        return self._values.get(key)

