import pytest

from whyline import cli
from whyline import credentials as cr
from whyline import credentials_cli
from whyline.tools import users

SECRET = "s3cr3t-VALUE"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    store: dict[str, str] = {}
    prompts: list[str] = []
    answers = [SECRET]

    def fake_put(name, value, run, which, system):
        store[name] = value

    def fake_getpass(prompt=""):
        prompts.append(prompt)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(cr, "_put", fake_put)
    monkeypatch.setattr(cr, "_backend", lambda which=None, system=None: "mac")
    monkeypatch.setattr(credentials_cli.getpass, "getpass", fake_getpass)
    monkeypatch.setattr(users, "_providers", {})
    return store, answers, prompts


def test_add_reads_value_from_getpass_and_lists_without_it(env, capsys):
    store, _, prompts = env
    assert cli.main(["cred", "add", "notion-key"]) == 0
    assert store == {"notion-key": SECRET} and prompts
    assert cr.get("notion-key").kind == "env"
    capsys.readouterr()
    assert cli.main(["cred", "list"]) == 0
    out = capsys.readouterr().out
    assert "notion-key" in out and SECRET not in out


def test_add_http_kind_keeps_origin_and_header(env):
    assert cli.main(["cred", "add", "gh", "--kind", "header", "--origin",
                     "https://api.github.com", "--header", "X-Token"]) == 0
    cred = cr.get("gh")
    assert cred.origins == ("https://api.github.com",) and cred.header_name == "X-Token"


def test_add_rejects_origin_on_env(env):
    assert cli.main(["cred", "add", "tok", "--origin", "https://x.com"]) == 2
    assert cr.get("tok") is None


def test_rotate_replaces_value(env):
    store, answers, _ = env
    cli.main(["cred", "add", "tok"])
    answers.append("new-value")
    assert cli.main(["cred", "rotate", "tok"]) == 0
    assert store["tok"] == "new-value"


def test_rotate_unknown_fails(env):
    assert cli.main(["cred", "rotate", "nope"]) == 1


def test_remove_deletes_unused(env, monkeypatch):
    cli.main(["cred", "add", "tok"])
    removed = []
    monkeypatch.setattr(cr, "remove", lambda name: (removed.append(name), cr._store(
        {k: v for k, v in cr._load().items() if k != name}))[0])
    assert cli.main(["cred", "remove", "tok"]) == 0
    assert removed == ["tok"] and cr.get("tok") is None


def test_remove_refused_while_used(env, capsys):
    cli.main(["cred", "add", "notion-key"])
    users.register("agent", lambda: [users.Use("credential", "notion-key", "agent research-digest")])
    capsys.readouterr()
    assert cli.main(["cred", "remove", "notion-key"]) == 1
    assert "agent research-digest" in capsys.readouterr().err
    assert cr.get("notion-key") is not None


def test_add_help_has_no_value_argument(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["cred", "add", "--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "--value" not in out and "--secret" not in out and "--kind" in out
    assert "name" in out


def test_users_of_filters_and_dedupes():
    users._providers.clear()
    users.register("a", lambda: [users.Use("credential", "k", "agent b"),
                                 users.Use("credential", "other", "agent z")])
    users.register("b", lambda: [users.Use("credential", "k", "agent b"),
                                 users.Use("credential", "k", "agent a")])
    assert users.of("credential", "k") == ["agent a", "agent b"]
    assert users.of("server", "k") == []
    users._providers.clear()
