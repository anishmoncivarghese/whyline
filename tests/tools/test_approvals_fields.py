"""Fields on pays and sends approvals (RSK-2)."""
import json

import pytest

from whyline.agents import paths
from whyline.tools import approvals


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


def _folder():
    folder = paths.runs_dir() / "r1"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class Clock:
    def __init__(self, on_sleep):
        self.now, self.sleeps, self.on_sleep = 0.0, 0, on_sleep

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps += 1
        self.on_sleep(self.sleeps)


def test_fields_are_stored_and_shown_first():
    folder = _folder()
    fields = {"amount": "12", "currency": "USD", "payee": "Acme", "today": "0",
              "limits": {"per_call": "20"}}
    clock = Clock(lambda n: approvals.answer("r1", 1, True))
    approvals.request(folder, "shop__buy", {"q": 1}, fields=fields, clock=clock, sleep=clock.sleep)
    assert json.loads((folder / "approvals" / "1.json").read_text())["fields"] == fields
    approvals._create(folder / "approvals", {"tool": "t", "arguments": "{}", "asked_at": "x",
                                             "status": "waiting", "fields": {"to": "a@b", "text": "hi"}})
    (item,) = approvals.pending("r1")
    assert item.fields == {"to": "a@b", "text": "hi"}
    assert item.arguments.startswith("to=a@b  text=hi  |  ")


def test_the_same_call_asks_every_time():
    folder = _folder()
    for n in (1, 2):
        clock = Clock(lambda s, n=n: approvals.answer("r1", n, True))
        got = approvals.request(folder, "shop__buy", {"q": 1}, fields={"amount": "1"},
                                clock=clock, sleep=clock.sleep)
        assert (got.status, got.n) == ("approved", n)
