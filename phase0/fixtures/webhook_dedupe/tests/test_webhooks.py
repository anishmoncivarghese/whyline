import threading
import unittest

from webhooks import WebhookProcessor


class WebhookProcessorTests(unittest.TestCase):
    def test_duplicate_is_not_processed_twice(self) -> None:
        calls = []
        processor = WebhookProcessor(calls.append)
        self.assertTrue(processor.process("evt-1", {"n": 1}))
        self.assertFalse(processor.process("evt-1", {"n": 2}))
        self.assertEqual(calls, [{"n": 1}])

    def test_failed_event_can_be_retried(self) -> None:
        attempts = 0

        def handler(payload: dict) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")

        processor = WebhookProcessor(handler)
        with self.assertRaises(RuntimeError):
            processor.process("evt-2", {})
        self.assertTrue(processor.process("evt-2", {}))
        self.assertEqual(attempts, 2)

    def test_concurrent_duplicate_runs_once(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        calls = []
        results = []

        def handler(payload: dict) -> None:
            calls.append(payload)
            entered.set()
            release.wait(timeout=2)

        processor = WebhookProcessor(handler)
        first = threading.Thread(target=lambda: results.append(processor.process("evt-3", {"n": 1})))
        second = threading.Thread(target=lambda: results.append(processor.process("evt-3", {"n": 2})))
        first.start()
        self.assertTrue(entered.wait(timeout=1))
        second.start()
        second.join(timeout=1)
        release.set()
        first.join(timeout=1)
        self.assertEqual(len(calls), 1)
        self.assertCountEqual(results, [True, False])


if __name__ == "__main__":
    unittest.main()

