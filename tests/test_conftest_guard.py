import time
from pathlib import Path

import pytest

from whyline.agents import telegram
from whyline.tools import mcp_config


def test_tests_cannot_call_the_telegram_api():
    started = time.monotonic()
    with pytest.raises(telegram.TelegramError):
        telegram._http("sendMessage", "123:abc", {"chat_id": 1, "text": "x"}, None)
    assert time.monotonic() - started < 1


# Collection imports this module before any test fixture runs.
SESSION_HOME = Path.home()


def test_tests_never_see_the_real_home():
    home = Path.home()
    assert home != SESSION_HOME
    assert SESSION_HOME not in home.parents
    assert "autohome" in home.name


def test_saving_a_connector_in_a_plain_test_lands_in_tmp():
    mcp_config.save_server(mcp_config.Server(
        "files", "cmd", env={}, tools_hash="h1",
        tools=(mcp_config.Tool("read"),)))
    assert (Path.home() / ".whyline" / "mcp.toml").exists()
    assert "files" in mcp_config.load()
