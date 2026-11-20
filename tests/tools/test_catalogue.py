import pytest

from whyline.tools import catalogue

BASE = 'name = "x"\ntitle = "X"\nabout = "a"\nargs = []\n'


def one(extra: str) -> str:
    return "[[connector]]\n" + BASE + extra


def test_refuses_no_source():
    with pytest.raises(catalogue.CatalogueError, match="source"):
        catalogue.parse(one('command = "npx"\n'))


@pytest.mark.parametrize("cmd", ["/usr/bin/npx", "npx -y foo", "./run.sh", "sh;rm"])
def test_refuses_non_bare_command(cmd):
    with pytest.raises(catalogue.CatalogueError, match="command"):
        catalogue.parse(one(f'command = "{cmd}"\nsource = "https://e.com"\n'))


def test_refuses_credential_value():
    text = one(
        'command = "npx"\nsource = "https://e.com"\n'
        '[[connector.credentials]]\nvar = "ghp_abc123secret"\nlabel = "t"\nwhere = "u"\n'
    )
    with pytest.raises(catalogue.CatalogueError, match="credential"):
        catalogue.parse(text)


def test_packaged_file_loads():
    entries = catalogue.load()
    assert entries
    for e in entries:
        assert e.source.startswith("https://")
        assert e.checked == ""
        assert e.status == catalogue.NOT_CHECKED
        for c in e.credentials:
            assert c.var.isupper() and c.where.startswith("https://")


def test_no_pays_risk():
    assert all(t.risk != "pays" for e in catalogue.load() for t in e.tools)


def test_search_matches_all_words():
    assert [e.name for e in catalogue.search("github")] == ["github"]
    assert [e.name for e in catalogue.search("GITHUB issue")] == ["github"]
    assert catalogue.search("github sqlite") == []
    assert [e.name for e in catalogue.search("read_query")] == ["sqlite"]
