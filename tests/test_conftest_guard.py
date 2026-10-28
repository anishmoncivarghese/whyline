import time

import pytest

from whyline.agents import telegram


def test_tests_cannot_call_the_telegram_api():
    started = time.monotonic()
    with pytest.raises(telegram.TelegramError):
        telegram._http("sendMessage", "123:abc", {"chat_id": 1, "text": "x"}, None)
    assert time.monotonic() - started < 1
