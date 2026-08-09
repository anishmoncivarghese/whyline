Add TTLs to the in-memory cache. There is already a clock passed to the constructor, so use that instead of sleeping in tests. Keep non-expiring values working and be careful that cached values like `0` are valid.

