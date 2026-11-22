import io
from email.message import Message

import pytest

from whyline import cli
from whyline.tools import knowledge, users


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.setattr(users, "_providers", {})
    return h


class _Response(io.BytesIO):
    def __init__(self, body: bytes, ctype: str = "text/html; charset=utf-8"):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = ctype


def _opener(pages):
    def open_(url, timeout):
        page = pages[url]
        if isinstance(page, Exception):
            raise page
        return page if isinstance(page, _Response) else _Response(page.encode())
    return open_


def test_pack_round_trip(home):
    pack = knowledge.Pack("docs", 'API "docs"', ("~/notes", "https://example.com/a", "pack:other"))
    knowledge.save_pack(pack)
    assert knowledge.get_pack("docs") == pack
    assert [p.name for p in knowledge.list_packs()] == ["docs"]
    knowledge.remove_pack("docs")
    assert knowledge.list_packs() == []
    with pytest.raises(KeyError):
        knowledge.get_pack("docs")


def test_remove_refused_while_used(home):
    knowledge.save_pack(knowledge.Pack("docs"))
    users.register("t", lambda: [users.Use("pack", "docs", "agent a")])
    with pytest.raises(ValueError, match="agent a"):
        knowledge.remove_pack("docs")
    assert knowledge.get_pack("docs")


def test_pack_expansion_relative_and_urls(home, tmp_path):
    knowledge.save_pack(knowledge.Pack("inner", items=("inner.md", "https://x.org/p")))
    base = tmp_path / "repo"
    items = knowledge.resolve(["pack:inner", "docs/a.md", "~/n.md", "https://x.org/p", "/abs/f"], base)
    assert items == [
        knowledge.Item(str(base / "inner.md")),
        knowledge.Item("https://x.org/p", True),
        knowledge.Item(str(base / "docs/a.md")),
        knowledge.Item(str(home / "n.md")),
        knowledge.Item(str(base / "/abs/f")),  # Windows adds base's drive
    ]
    with pytest.raises(ValueError):
        knowledge.resolve(["pack:missing"], base)


def test_pack_cycle_refused(home, tmp_path):
    knowledge.save_pack(knowledge.Pack("a", items=("pack:b",)))
    knowledge.save_pack(knowledge.Pack("b", items=("pack:a",)))
    with pytest.raises(ValueError):
        knowledge.resolve(["pack:a"], tmp_path)


def test_page_fetched_and_stripped(tmp_path):
    html = "<html><head><title>Hi</title><style>p{}</style></head><body><script>x()</script><p>One &amp; two</p><p>Three</p></body></html>"
    url = "https://example.com/page"
    [got] = knowledge.fetch_pages([url], tmp_path / "out", opener=_opener({url: html}))
    assert got.ok
    text = got.path.read_text(encoding="utf-8")
    assert "One & two" in text and "Three" in text
    assert "x()" not in text and "p{}" not in text


def test_plain_text_kept_as_is(tmp_path):
    url = "https://example.com/a.txt"
    page = _Response(b"<b>raw</b>\n", "text/plain")
    [got] = knowledge.fetch_pages([url], tmp_path, opener=_opener({url: page}))
    assert got.path.read_text(encoding="utf-8") == "<b>raw</b>\n"


def test_size_limit(tmp_path):
    url = "https://example.com/big"
    big = _Response(b"a" * (knowledge.PAGE_LIMIT + 1), "text/plain")
    [got] = knowledge.fetch_pages([url], tmp_path, opener=_opener({url: big}))
    assert not got.ok and "larger" in got.error
    assert not list(tmp_path.iterdir())


def test_non_http_refused_and_opener_not_called(tmp_path):
    def boom(url, timeout):
        raise AssertionError("opened")
    got = knowledge.fetch_pages(["file:///etc/passwd", "ftp://x/y"], tmp_path, opener=boom)
    assert [g.ok for g in got] == [False, False]
    assert "http" in got[0].error


def test_failed_page_noted_and_rest_go_on(tmp_path):
    bad, good = "https://example.com/bad", "https://example.com/good"
    got = knowledge.fetch_pages([bad, good], tmp_path, opener=_opener({bad: OSError("HTTP 404"), good: "<p>ok</p>"}))
    assert not got[0].ok and "404" in got[0].error
    assert got[1].ok and got[1].path.read_text(encoding="utf-8") == "ok"


def test_cli(home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["tools", "knowledge", "add", "docs", "--description", "D",
                     "--item", "a.md", "--item", "https://x.org/p"]) == 0
    assert cli.main(["tools", "knowledge", "list"]) == 0
    assert "docs" in capsys.readouterr().out
    assert cli.main(["tools", "knowledge", "show", "docs"]) == 0
    assert "https://x.org/p" in capsys.readouterr().out
    assert cli.main(["tools", "knowledge", "add", "bad", "--item", "ftp://x/y"]) == 1
    assert cli.main(["tools", "knowledge", "remove", "docs"]) == 0
    assert cli.main(["tools", "knowledge", "show", "docs"]) == 1
