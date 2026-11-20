import pytest

from whyline.tools import catalogue, made, mcp_config, risk, users
from whyline.tools.mcp_config import Server, Tool


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(users, "_providers", {})
    return tmp_path


def _catalogue(monkeypatch, tools):
    entry = catalogue.Entry(
        name="shop", title="Shop", about="", command="npx", args=(), credentials=(),
        tools=tuple(tools), source="https://e.com", checked="")
    monkeypatch.setattr(catalogue, "load", lambda: [entry])


def test_levels_rise():
    assert risk.LEVELS == ("reads", "writes", "sends", "pays")


def test_default_is_writes(home):
    assert risk.of("nothing", "x") == "writes"


def test_read_only_hint_gives_reads(home):
    mcp_config.save_server(Server(
        name="files", command="x", tools=(Tool("look", read_only=True), Tool("change", read_only=False), Tool("odd"))))
    assert risk.of("files", "look") == "reads"
    assert risk.of("files", "change") == "writes"
    assert risk.of("files", "odd") == "writes"


def test_catalogue_beats_read_only_hint(home, monkeypatch):
    _catalogue(monkeypatch, [catalogue.Tool("buy", "pay"), catalogue.Tool("look", "read")])
    mcp_config.save_server(Server(name="shop", command="x", tools=(Tool("buy", read_only=True),)))
    assert risk.of("shop", "buy") == "pays"
    assert risk.of("shop", "look") == "reads"


def test_user_setting_beats_catalogue(home, monkeypatch):
    _catalogue(monkeypatch, [catalogue.Tool("look", "read")])
    risk.set_level("shop", "look", "sends")
    assert risk.of("shop", "look") == "sends"


def test_made_tool_has_its_own_risk(home):
    made.save(made.MadeTool(name="buy", url="https://e.com", method="POST", risk="spends"))
    made.save(made.MadeTool(name="look", url="https://e.com"))
    assert risk.of("made", "buy") == "pays"
    assert risk.of("made", "look") == "reads"


def test_raise_allowed_lower_refused(home, monkeypatch):
    _catalogue(monkeypatch, [catalogue.Tool("edit", "write")])
    risk.set_level("shop", "edit", "pays")
    with pytest.raises(ValueError, match="never lowered"):
        risk.set_level("shop", "edit", "reads")
    assert risk.of("shop", "edit") == "pays"
    risk.set_level("shop", "edit", "writes")  # back to its own level is the floor, not a lowering
    assert risk.of("shop", "edit") == "writes"
    with pytest.raises(ValueError):
        risk.set_level("shop", "edit", "bogus")


def test_settings_file_is_private(home):
    import os
    import stat

    risk.set_level("a", "t", "pays")
    assert stat.S_IMODE(os.stat(home / ".whyline" / "tool-risk.toml").st_mode) == 0o600


def test_hints_from_catalogue(home, monkeypatch):
    _catalogue(monkeypatch, [catalogue.Tool(
        "buy", "pay", pay={"amount_arg": "total", "payee_arg": "to"}, send={"to_arg": "email"})])
    assert risk.hints("shop", "buy") == {
        "pay": {"amount_arg": "total", "payee_arg": "to"}, "send": {"to_arg": "email"}}
    assert risk.hints("shop", "other") == {}


def test_hints_from_made_tool_and_hash_stable_without_them(home):
    plain = made.MadeTool(name="p", url="https://e.com")
    before = made.tool_hash(plain)
    assert made.tool_hash(made.MadeTool(name="p", url="https://e.com", pay={})) == before
    made.save(made.MadeTool(name="buy", url="https://e.com", method="POST", risk="spends",
                            pay={"amount_arg": "amount", "currency_arg": "cur"}))
    assert risk.hints("made", "buy") == {"pay": {"amount_arg": "amount", "currency_arg": "cur"}}


def test_catalogue_parses_hints_and_refuses_unknown():
    text = ('[[connector]]\nname = "x"\ntitle = "X"\nabout = "a"\nargs = []\ncommand = "npx"\n'
            'source = "https://e.com"\n[[connector.tools]]\nname = "buy"\nrisk = "pay"\n'
            '[connector.tools.pay]\namount_arg = "amt"\n')
    assert catalogue.parse(text)[0].tools[0].pay == {"amount_arg": "amt"}
    with pytest.raises(catalogue.CatalogueError, match="hints"):
        catalogue.parse(text.replace("amount_arg", "secret_arg"))


def test_level_change_changes_tools_hash(home, monkeypatch):
    _catalogue(monkeypatch, [catalogue.Tool("look", "read")])
    mcp_config.save_server(Server(name="shop", command="x", tools_hash="abc"))
    assert mcp_config.load()["shop"].tools_hash == "abc"
    risk.set_level("shop", "look", "sends")
    changed = mcp_config.load()["shop"].tools_hash
    assert changed != "abc"
    risk.set_level("shop", "look", "pays")
    assert mcp_config.load()["shop"].tools_hash not in ("abc", changed)
    # saving a server read back from load() keeps the stored hash
    mcp_config.save_server(mcp_config.load()["shop"])
    assert mcp_config._load_saved()["shop"].tools_hash == "abc"
