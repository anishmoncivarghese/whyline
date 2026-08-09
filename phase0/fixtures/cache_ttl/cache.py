from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any


class MemoryCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._values: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value

    def get(self, key: str) -> Any | None:
        return self._values.get(key)

