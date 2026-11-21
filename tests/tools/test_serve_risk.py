"""`tools serve` and the pays and sends levels (RSK-2)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import io

import pytest

from whyline.tools import serve
from whyline.tools.mcp_config import Server

FAKE = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")
@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


PAY = {"amount_arg": "amount", "currency_arg": "currency", "payee_arg": "to"}
LIMIT = {"currency": "USD", "per_call": 20, "per_day": 30}


def _tool(name, permission, **extra):
    return {"server": "fake", "tool": name, "permission": permission, "description": "d",
            "input_schema": {"type": "object"}, **extra}


def _buy(permission="ask", **extra):
    return _tool("echo", permission, risk="pays", hints={"pay": PAY}, limits=LIMIT, **extra)


def _pay(amount=10, currency="USD", ident=2):
    return _call({"amount": amount, "currency": currency, "to": "Acme"}, ident)


def _call(arguments, ident=2):
    return {"jsonrpc": "2.0", "id": ident, "method": "tools/call",
            "params": {"name": "fake__echo", "arguments": arguments}}


def _run(folder, tools, messages, answer="approved", **options):
    asked = []

    def ask(run_folder, tool, args, fields=None):
        asked.append(fields)
        return answer

    path = folder / "tools.json"
    path.write_text(json.dumps({"run": "r1", "agent": "a", "tools": tools}), encoding="utf-8")
    stdout = io.StringIO()
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    servers = {"fake": Server(name="fake", command=sys.executable, args=(FAKE,))}
    serve.serve(stdin, stdout, environ={serve.ENV_VAR: str(path)}, servers=servers, ask=ask, **options)
    return [json.loads(line)["result"] for line in stdout.getvalue().splitlines()], asked


def _refused(tmp_path, tool, call, message):
    results, asked = _run(tmp_path, [tool], [call])
    assert results[0]["isError"] and message in results[0]["content"][0]["text"]
    assert asked == []


def test_pays_limits_are_enforced(tmp_path):
    _refused(tmp_path, {**_buy(), "limits": None}, _pay(), "Set a limit for fake.echo first")
    _refused(tmp_path, {**_buy(), "limits": {"currency": "USD"}}, _pay(), "Set a limit for fake.echo first")
    _refused(tmp_path, {**_buy(), "hints": {}}, _pay(), "does not say which arguments")
    _refused(tmp_path, _buy(), _pay("lots"), "not a number")
    _refused(tmp_path, _buy(), _pay(-3), "not a number")
    _refused(tmp_path, _buy(), _pay(5, "EUR"), "limited to USD, not EUR")
    _refused(tmp_path, _buy(), _pay(25), "over the 20 USD limit per call")


def test_pays_per_day_across_calls_and_a_new_day(tmp_path):
    now = [datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)]

    def go(amount):
        results, asked = _run(tmp_path, [_buy()], [_pay(amount)], now=lambda: now[0])
        return results[0], asked

    first, asked = go(20)
    assert not first["isError"] and asked[0]["today"] == "0"
    over, asked = go(11)
    assert over["isError"] and "over the 30 USD limit per day" in over["content"][0]["text"]
    assert asked == []  # refused without asking
    second, asked = go(10)
    assert not second["isError"] and asked[0]["today"] == "20"
    now[0] += timedelta(days=1)
    _, asked = go(20)
    assert asked[0]["today"] == "0"


def test_pays_approval_fields_and_no_remembered_answer(tmp_path):
    _, asked = _run(tmp_path, [_buy()], [_pay(5), _pay(5, ident=3)])
    assert len(asked) == 2  # each call asks
    assert asked[0] == {"amount": "5", "currency": "USD", "payee": "Acme", "today": "0",
                        "limits": {"per_call": "20", "per_day": "30"}}


def test_stored_allowed_for_pays_is_treated_as_ask(tmp_path):
    results, asked = _run(tmp_path, [_buy("allowed")], [_pay()], answer="denied")
    assert asked and results[0]["content"][0]["text"] == serve.DENIED_TEXT


def test_pays_timeout_is_not_run(tmp_path):
    results, _ = _run(tmp_path, [_buy()], [_pay()], answer="timed out")
    assert results[0]["content"][0]["text"] == serve.TIMED_OUT_TEXT


def test_sends_approval_carries_recipient_and_full_text(tmp_path):
    send = _tool("echo", "ask", risk="sends", hints={"send": {"to_arg": "to", "text_arg": "text"}})
    long = "x" * 5000
    call = {"to": "a@b.c", "text": long}
    _, asked = _run(tmp_path, [send], [_call(call), _call(call, ident=3)])
    assert asked == [call] * 2
