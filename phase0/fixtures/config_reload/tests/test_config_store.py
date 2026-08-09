import threading
import unittest

from config_store import ConfigStore


class ConfigStoreTests(unittest.TestCase):
    def test_reload_replaces_configuration(self) -> None:
        store = ConfigStore({"OLD": "value"})
        store.reload("API_URL=https://example.test\nTIMEOUT=30\n")
        self.assertEqual(store.snapshot(), {"API_URL": "https://example.test", "TIMEOUT": "30"})

    def test_invalid_reload_preserves_previous_configuration(self) -> None:
        store = ConfigStore({"SAFE": "yes"})
        with self.assertRaises(ValueError):
            store.reload("GOOD=1\nbad=2\n")
        self.assertEqual(store.snapshot(), {"SAFE": "yes"})

    def test_duplicate_key_is_rejected(self) -> None:
        store = ConfigStore()
        with self.assertRaises(ValueError):
            store.reload("MODE=one\nMODE=two")

    def test_value_may_contain_equals(self) -> None:
        store = ConfigStore()
        store.reload("TOKEN=a=b=c")
        self.assertEqual(store.get("TOKEN"), "a=b=c")

    def test_reader_observes_only_complete_snapshots(self) -> None:
        store = ConfigStore({"A": "old", "B": "old"})
        observed = []
        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                observed.append(store.snapshot())

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            store.reload("A=new\nB=new")
        finally:
            stop.set()
            thread.join(timeout=1)
        allowed = ({"A": "old", "B": "old"}, {"A": "new", "B": "new"})
        self.assertTrue(observed)
        self.assertTrue(all(value in allowed for value in observed))


if __name__ == "__main__":
    unittest.main()
