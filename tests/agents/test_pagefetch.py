import os
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from whyline.agents import pagefetch

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


class Resp:
    def __init__(self, status=200, body="", ctype="text/html", headers=None):
        self.status = status
        self._body = body.encode() if isinstance(body, str) else body
        self.headers = {"Content-Type": ctype, **(headers or {})}

    def read(self, n=-1):
        data, self._body = self._body[:n], self._body[n:]
        return data

    def close(self):
        pass


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(url) if callable(item) else item


def public(host):
    return ["93.184.216.34"]


def go(url, opener, tmp_path, resolve=public, now=NOW):
    return pagefetch.fetch(url, now=now, opener=opener, resolve=resolve, cache_dir=tmp_path)


def redirect(to, status=302):
    return Resp(status, headers={"Location": to})


def test_ok_page_and_headers(tmp_path):
    opener = Opener(Resp(body="<html><title>T</title><body><p>Hello world</p></body></html>"))
    page = go("https://example.com/a", opener, tmp_path)
    assert page.state == "ok" and "Hello world" in page.text and "<p>" not in page.text
    headers = opener.calls[0][1]
    assert headers["User-Agent"].startswith("whyline-watch/")
    assert headers["Accept"] == "text/html, application/json, text/plain"
    assert not any(k.lower() == "cookie" for k in headers)


@pytest.mark.parametrize("target,resolver", [
    ("http://127.0.0.1/x", public),
    ("http://169.254.169.254/latest", public),
    ("http://internal.example/x", lambda host: ["10.0.0.5"] if host == "internal.example" else public(host)),
])
def test_private_address_is_refused_after_redirect(tmp_path, target, resolver):
    opener = Opener(redirect(target))
    page = go("https://example.com/", opener, tmp_path, resolve=resolver)
    assert page.state == "failed" and page.reason == "that address is on a private network"
    assert len(opener.calls) == 1


def test_private_address_refused_up_front_and_mixed_answers(tmp_path):
    opener = Opener()
    assert go("http://localhost/", opener, tmp_path, resolve=lambda h: ["127.0.0.1"]).state == "failed"
    page = go("http://mixed.example/", opener, tmp_path, resolve=lambda h: ["93.184.216.34", "::1"])
    assert page.reason == "that address is on a private network"
    assert opener.calls == []


def test_other_schemes_refused(tmp_path):
    assert go("file:///etc/passwd", Opener(), tmp_path).state == "failed"
    assert go("ftp://example.com/", Opener(), tmp_path).state == "failed"


@pytest.mark.parametrize("status,reason", [
    (401, "the site asked for a login"),
    (407, "the site asked for a login"),
    (403, "the site is blocking automated checks"),
    (429, "the site asked to slow down"),
    (503, "the site asked to slow down"),
])
def test_blocked_statuses(tmp_path, status, reason):
    page = go("https://example.com/", Opener(Resp(status, "no")), tmp_path)
    assert page.state == "blocked" and page.reason == reason


@pytest.mark.parametrize("phrase", [
    "captcha", "Are You A Robot", "unusual traffic", "Verify you are human", "ENABLE JAVASCRIPT",
])
def test_blocked_phrases(tmp_path, phrase):
    page = go("https://example.com/", Opener(Resp(body=f"<p>Please {phrase} now</p>")), tmp_path)
    assert page.state == "blocked" and page.reason == "the site is blocking automated checks"


def test_sign_in_phrase_is_a_login(tmp_path):
    page = go("https://example.com/", Opener(Resp(body="<p>Sign in to continue</p>")), tmp_path)
    assert page.state == "blocked" and page.reason == "the site asked for a login"


def test_long_page_with_phrase_is_not_blocked(tmp_path):
    body = "<p>" + "word " * 1000 + " captcha</p>"
    assert go("https://example.com/", Opener(Resp(body=body)), tmp_path).state == "ok"


def test_retry_after_seconds(tmp_path):
    page = go("https://example.com/", Opener(Resp(429, headers={"Retry-After": "120"})), tmp_path)
    assert page.retry_at == NOW + timedelta(seconds=120)


def test_retry_after_date_and_cap(tmp_path):
    when = NOW + timedelta(hours=2)
    page = go("https://example.com/", Opener(Resp(503, headers={"Retry-After": format_datetime(when)})), tmp_path)
    assert page.retry_at == when
    far = go("https://example.com/b", Opener(Resp(503, headers={"Retry-After": "999999999"})), tmp_path)
    assert far.retry_at == NOW + timedelta(hours=24)


def test_retry_after_with_naive_now(tmp_path):
    naive = NOW.replace(tzinfo=None)
    when = NOW + timedelta(hours=2)
    page = go("https://example.com/", Opener(Resp(503, headers={"Retry-After": format_datetime(when)})), tmp_path, now=naive)
    assert page.state == "blocked" and page.retry_at == naive + timedelta(hours=2)


@pytest.mark.parametrize("value", ["9" * 30, "-5", "99999999999999999999999999", "not a date"])
def test_retry_after_hostile_values_stay_blocked(tmp_path, value):
    page = go("https://example.com/", Opener(Resp(429, headers={"Retry-After": value})), tmp_path)
    assert page.state == "blocked"
    assert page.retry_at is None or NOW <= page.retry_at <= NOW + timedelta(hours=24)


def test_cache_makes_no_second_request(tmp_path):
    opener = Opener(Resp(body="<p>one</p>"))
    first = go("https://example.com/", opener, tmp_path)
    second = go("https://example.com/", opener, tmp_path, now=NOW + timedelta(minutes=4))
    assert second == first and len(opener.calls) == 1
    opener2 = Opener(Resp(body="<p>two</p>"))
    third = go("https://example.com/", opener2, tmp_path, now=NOW + timedelta(minutes=6))
    assert "two" in third.text and len(opener2.calls) == 1


def test_cache_holds_until_retry_at(tmp_path):
    opener = Opener(Resp(429, headers={"Retry-After": "3600"}))
    go("https://example.com/", opener, tmp_path)
    again = go("https://example.com/", opener, tmp_path, now=NOW + timedelta(minutes=30))
    assert again.state == "blocked" and len(opener.calls) == 1


def test_cache_file_is_private(tmp_path):
    go("https://example.com/", Opener(Resp(body="<p>x</p>")), tmp_path)
    final = next(tmp_path.glob("*.json"))
    final.unlink()
    stale = final.with_suffix(".tmp")
    stale.write_text("old")
    stale.chmod(0o644)
    go("https://example.com/", Opener(Resp(body="<p>x</p>")), tmp_path, now=NOW + timedelta(hours=1))
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    if os.name != "nt":  # Windows files have no group/other mode bits
        assert files[0].stat().st_mode & 0o077 == 0


def test_redirects_followed_up_to_five(tmp_path):
    ok = Opener(*[redirect("/n")] * 5, Resp(body="<p>done</p>"))
    assert go("https://example.com/", ok, tmp_path).state == "ok"
    too_many = Opener(*[redirect("/n")] * 6, Resp(body="<p>done</p>"))
    page = go("https://example.org/", too_many, tmp_path)
    assert page.state == "failed" and "too many" in page.reason


def test_non_text_page(tmp_path):
    page = go("https://example.com/a.png", Opener(Resp(body=b"\x89PNG", ctype="image/png")), tmp_path)
    assert page.state == "failed" and page.reason == "that page is not text"


def test_json_page_is_text(tmp_path):
    page = go("https://example.com/a.json", Opener(Resp(body='{"a": 1}', ctype="application/json")), tmp_path)
    assert page.state == "ok" and '"a"' in page.text


def test_not_found_is_failed(tmp_path):
    page = go("https://example.com/", Opener(Resp(404, "gone")), tmp_path)
    assert page.state == "failed" and "404" in page.reason


def test_no_exception_escapes(tmp_path):
    page = go("https://example.com/", Opener(OSError("boom")), tmp_path)
    assert page.state == "failed" and page.reason == "boom"

    def broken(host):
        raise RuntimeError("dns")

    assert go("https://nowhere.example/", Opener(), tmp_path, resolve=broken).state == "failed"
    assert pagefetch.fetch(None, now=NOW, cache_dir=tmp_path).state == "failed"
    assert pagefetch.fetch("https://example.com/", now=NOW, opener=Opener(Resp(body="x")),
                           resolve=public, cache_dir=tmp_path / "f" / "g").state in ("ok", "blocked", "failed")
