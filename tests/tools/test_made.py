import json

import pytest

from whyline.tools import made
from whyline.tools.made import MadeTool, MadeToolError, ToolInput

SECRET = "s3cr3t-token/+value"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    return h


def tool(**kw):
    base = dict(
        name="weather",
        about="Weather",
        method="GET",
        url="https://api.example.com/v1/{city}",
        inputs=[ToolInput("city", "string", "City")],
    )
    base.update(kw)
    return MadeTool(**base)


def accepted_tool(**kw):
    t = tool(**kw)
    return made.replace(t, accepted_hash=made.tool_hash(t))


class Net:
    """A fake resolve and request that records what was sent."""

    def __init__(self, status=200, body=b"{}", headers=None, ips=("93.184.216.34",)):
        self.status, self.body, self.headers, self.ips = status, body, headers or {}, ips
        self.sent = []

    def resolve(self, host):
        return list(self.ips)

    def request(self, method, url, headers, body, *, timeout, max_bytes, address):
        self.sent.append(
            dict(
                method=method,
                url=url,
                headers=headers,
                body=body,
                timeout=timeout,
                max_bytes=max_bytes,
                address=address,
            )
        )
        reply = self.status, self.headers, self.body
        if callable(self.body):
            reply = self.body(len(self.sent))
        return reply


def run(t, args=None, net=None, cred=None):
    net = net or Net()
    out = made.call(
        t,
        {"city": "Paris"} if args is None else args,
        get_credential=lambda name: cred,
        resolve=net.resolve,
        request=net.request,
    )
    return out, net


# --- storage ---------------------------------------------------------------


def test_save_load_remove_round_trip(home):
    t = tool(
        headers={"X-A": "1"},
        query={"units": "{city}"},
        body='{"q": "{city}"}',
        credential="k",
        credential_in="header:Authorization",
        pick="a.b",
        risk="writes",
        method="POST",
    )
    made.save(t)
    assert (home / ".whyline" / "tools" / "weather.toml").exists()
    assert made.load_all() == [t]
    assert made.remove("weather") is True
    assert made.remove("weather") is False
    assert made.load_all() == []


def test_bad_names_never_touch_the_disk(home):
    with pytest.raises(MadeToolError):
        made.save(tool(name="../evil"))


def test_edited_tool_needs_accepting(home):
    made.save(tool())
    assert not made.accepted(made.load("weather"))
    made.accept("weather")
    stored = made.load("weather")
    assert made.accepted(stored)
    stored.url = "https://api.example.org/v1/{city}"
    assert not made.accepted(stored)
    made.save(stored)
    assert not made.accepted(made.load("weather"))
    with pytest.raises(MadeToolError, match="accept"):
        run(made.load("weather"))
    made.accept("weather")
    out, _ = run(made.load("weather"))
    assert out == "{}"


# --- validate --------------------------------------------------------------


def test_valid_tool_passes():
    made.validate(tool())
    made.validate(tool(method="POST", risk="writes", body='{"a": "{city}"}'))


@pytest.mark.parametrize(
    "kw, text",
    [
        (dict(url="http://api.example.com/{city}"), "https"),
        (dict(url="https://127.0.0.1/{city}"), "IP"),
        (dict(url="https://[::1]/{city}"), "IP"),
        (dict(url="https://localhost/{city}"), "localhost"),
        (dict(url="https://{city}.example.com/"), "fixed host"),
        (dict(url="https://api.example.com/{credential}"), "path"),
        (dict(url="https://api.example.com/{other}"), "not declared"),
        (dict(query={"q": "{other}"}), "not declared"),
        (dict(headers={"X": "{other}"}), "not declared"),
        (dict(method="POST", body='{"a": "{other}"}', risk="writes"), "not declared"),
        (dict(headers={"Host": "evil.com"}), "Host"),
        (dict(headers={"content-length": "1"}), "content-length"),
        (dict(method="POST", risk="reads"), "writes"),
        (dict(method="DELETE", risk="reads"), "writes"),
        (dict(risk="bogus"), "risk"),
        (dict(method="TRACE"), "method"),
        (dict(credential="k", credential_in="path:x"), "credential_in"),
        (dict(credential="k"), "credential_in"),
    ],
)
def test_validate_refusals(kw, text):
    with pytest.raises(MadeToolError, match=text):
        made.validate(tool(**kw))


def test_reads_only_for_get():
    made.validate(tool(method="GET", risk="reads"))
    made.validate(tool(method="GET", risk="writes"))


# --- call: filling ---------------------------------------------------------


def test_url_and_query_are_url_encoded():
    t = accepted_tool(
        url="https://api.example.com/v1/{city}",
        query={"q": "{city}", "n": "{n}"},
        inputs=[ToolInput("city"), ToolInput("n", "number", required=False)],
    )
    _, net = run(t, {"city": "São Paulo/x?y=1&z", "n": "3"})
    url = net.sent[0]["url"]
    assert url.startswith("https://api.example.com/v1/S%C3%A3o%20Paulo%2Fx%3Fy%3D1%26z?")
    assert "q=S%C3%A3o%20Paulo%2Fx%3Fy%3D1%26z" in url
    assert "n=3" in url
    assert net.sent[0]["timeout"] == 15
    assert net.sent[0]["max_bytes"] == 200_000
    assert net.sent[0]["address"] == "93.184.216.34"


def test_body_is_json_encoded_with_types():
    t = accepted_tool(
        method="POST",
        risk="writes",
        url="https://api.example.com/x",
        body='{"name": "{name}", "n": "{n}", "ok": "{ok}", "msg": "hi {name}"}',
        inputs=[
            ToolInput("name"),
            ToolInput("n", "number"),
            ToolInput("ok", "boolean"),
        ],
    )
    _, net = run(t, {"name": 'a"b\n', "n": 2.5, "ok": True})
    sent = net.sent[0]
    assert json.loads(sent["body"]) == {"name": 'a"b\n', "n": 2.5, "ok": True, "msg": 'hi a"b\n'}
    assert sent["headers"]["Content-Type"] == "application/json"
    assert sent["method"] == "POST"


def test_input_checks():
    t = accepted_tool(inputs=[ToolInput("city"), ToolInput("n", "number", required=False)])
    with pytest.raises(MadeToolError, match="required"):
        run(t, {})
    with pytest.raises(MadeToolError, match="Unknown"):
        run(t, {"city": "a", "zzz": 1})
    with pytest.raises(MadeToolError, match="number"):
        run(t, {"city": "a", "n": "abc"})


def test_credential_goes_in_header_or_query():
    t = accepted_tool(credential="k", credential_in="header:Authorization")
    _, net = run(t, cred=SECRET)
    assert net.sent[0]["headers"]["Authorization"] == SECRET
    t = accepted_tool(credential="k", credential_in="query:key")
    _, net = run(t, cred=SECRET)
    assert "key=s3cr3t-token%2F%2Bvalue" in net.sent[0]["url"]
    with pytest.raises(MadeToolError, match="not stored"):
        run(t, cred=None)


# --- call: safety ----------------------------------------------------------


@pytest.mark.parametrize(
    "url, ips",
    [
        ("https://192.168.1.1/{city}", ("93.184.216.34",)),
        ("https://localhost/{city}", ("127.0.0.1",)),
        ("https://internal.example.com/{city}", ("10.0.0.1",)),
        ("https://loop.example.com/{city}", ("127.0.0.1",)),
        ("https://meta.example.com/{city}", ("169.254.169.254",)),
        ("https://v6.example.com/{city}", ("::1",)),
        ("https://mapped.example.com/{city}", ("::ffff:10.0.0.1",)),
        ("https://mixed.example.com/{city}", ("93.184.216.34", "10.0.0.1")),
    ],
)
def test_made_tool_refuses_private_addresses(url, ips):
    net = Net(ips=ips)
    t = made.replace(tool(url=url), accepted_hash="")
    t = made.replace(t, accepted_hash=made.tool_hash(t))
    with pytest.raises(MadeToolError):
        run(t, net=net)
    assert net.sent == []


def test_made_tool_refuses_private_addresses_redirect_to_another_host():
    net = Net(status=302, headers={"location": "https://evil.example.net/x"})
    t = accepted_tool(credential="k", credential_in="header:Authorization")
    with pytest.raises(MadeToolError, match="another host") as info:
        run(t, net=net, cred=SECRET)
    assert len(net.sent) == 1
    assert SECRET not in str(info.value)


def test_redirect_on_same_host_is_followed():
    def body(n):
        if n == 1:
            return 301, {"location": "/moved"}, b""
        return 200, {}, b"done"

    net = Net(body=body)
    out, _ = run(accepted_tool(), net=net)
    assert out == "done"
    assert net.sent[1]["url"] == "https://api.example.com/moved"


def test_redirect_to_private_address_is_refused():
    def body(n):
        return 302, {"location": "https://api.example.com/loop"}, b""

    net = Net(body=body)
    with pytest.raises(MadeToolError, match="redirects"):
        run(accepted_tool(), net=net)


# --- call: answer ----------------------------------------------------------


def test_size_cap():
    net = Net(body=b"x" * 300_000)
    out, _ = run(accepted_tool(), net=net)
    assert len(out) == 200_000


def test_pick():
    net = Net(body=json.dumps({"a": {"b": [{"c": "hi"}, 2]}}).encode())
    assert run(accepted_tool(pick="a.b.0.c"), net=net)[0] == "hi"
    assert json.loads(run(accepted_tool(pick="a.b"), net=net)[0]) == [{"c": "hi"}, 2]
    assert json.loads(run(accepted_tool(pick=""), net=net)[0])["a"]["b"][1] == 2
    with pytest.raises(MadeToolError, match="Nothing at"):
        run(accepted_tool(pick="a.zzz"), net=net)
    with pytest.raises(MadeToolError, match="not JSON"):
        run(accepted_tool(pick="a"), net=Net(body=b"plain"))


def test_non_2xx_returns_code_and_first_500_chars():
    net = Net(status=404, body=b"n" * 900)
    out, _ = run(accepted_tool(), net=net)
    assert out == "HTTP 404 " + "n" * 500


def test_credential_never_in_output():
    t = accepted_tool(credential="k", credential_in="header:Authorization", pick="echo")
    body = json.dumps({"echo": f"you sent {SECRET}"}).encode()
    out, _ = run(t, net=Net(body=body), cred=SECRET)
    assert SECRET not in out and "[credential]" in out

    out, _ = run(t, net=Net(status=401, body=body), cred=SECRET)
    assert SECRET not in out

    t = accepted_tool(credential="k", credential_in="query:key")
    body = f"bad url ...?key=s3cr3t-token%2F%2Bvalue".encode()
    out, _ = run(t, net=Net(status=400, body=body), cred=SECRET)
    assert "s3cr3t" not in out

    class Boom(Net):
        def request(self, *a, **k):
            raise OSError(f"connect failed with {SECRET}")

    with pytest.raises(MadeToolError) as info:
        run(t, net=Boom(), cred=SECRET)
    assert SECRET not in str(info.value) and "s3cr3t" not in str(info.value)
