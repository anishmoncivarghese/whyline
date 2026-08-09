# Task: per-entry cache TTL

Add time-to-live support to `MemoryCache`.

Requirements:

- `set(key, value, ttl_seconds=None)` accepts an optional TTL.
- `get(key)` returns `None` and removes an entry after it expires.
- Entries without a TTL retain current behavior.
- Reject negative TTL values with `ValueError`.
- Preserve the existing public API and make all tests pass.

Verification: `python3 -m unittest discover -s tests -v`
