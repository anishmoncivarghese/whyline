import unittest

from cache import MemoryCache


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class MemoryCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.cache = MemoryCache(clock=self.clock)

    def test_existing_behavior_without_ttl(self) -> None:
        self.cache.set("count", 0)
        self.assertEqual(self.cache.get("count"), 0)

    def test_value_exists_before_expiry(self) -> None:
        self.cache.set("token", "abc", ttl_seconds=10)
        self.clock.now = 109.9
        self.assertEqual(self.cache.get("token"), "abc")

    def test_value_is_removed_at_expiry(self) -> None:
        self.cache.set("token", "abc", ttl_seconds=10)
        self.clock.now = 110.0
        self.assertIsNone(self.cache.get("token"))
        self.assertNotIn("token", self.cache._values)

    def test_zero_ttl_expires_immediately(self) -> None:
        self.cache.set("token", "abc", ttl_seconds=0)
        self.assertIsNone(self.cache.get("token"))

    def test_negative_ttl_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.cache.set("token", "abc", ttl_seconds=-1)


if __name__ == "__main__":
    unittest.main()

