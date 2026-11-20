import pytest

from whyline import cli
from whyline.tools import skill_install, skill_sources


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(skill_install, "_commit", lambda source, run: "abc123def456")
    return tmp_path


def _fetched(home, body="Do it.\n", extra=None):
    source = skill_sources.add("mine", "https://example.com/o/r", "skills")
    folder = home / ".whyline" / "skill-sources" / "mine" / "skills" / "pdf"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: pdf\ndescription: reads pdf files\n---\n{body}")
    for rel, text in (extra or {}).items():
        (folder / rel).write_text(text)
    skill_sources._stamp(source).write_text("2026-11-20T00:00:00Z")
    return folder


def _run(*argv):
    return cli.main(["tools", "skills", *argv])


def _answer(monkeypatch, text):
    monkeypatch.setattr("builtins.input", lambda prompt="": text)


def test_sources_add_list_remove(home, capsys):
    assert _run("sources", "add", "mine", "https://example.com/o/r", "--path", "skills") == 0
    assert _run("sources") == 0
    assert "mine  https://example.com/o/r  skills  not fetched" in capsys.readouterr().out
    assert _run("sources", "add", "mine", "https://example.com/o/r") == 1
    assert _run("sources", "remove", "mine") == 0
    assert _run("sources", "remove", "mine") == 1


def test_sources_refresh_fetches_named_or_all(home, monkeypatch, capsys):
    _fetched(home)
    seen = []
    monkeypatch.setattr(skill_sources, "fetch", lambda source: seen.append(source.name) or "f" * 40)
    assert _run("sources", "refresh", "mine") == 0
    assert _run("sources", "refresh", "nope") == 1
    assert seen == ["mine"]
    assert "mine: ffffffffffff  1 skills" in capsys.readouterr().out

    def broken(source):
        raise RuntimeError("git clone failed: no")

    monkeypatch.setattr(skill_sources, "fetch", broken)
    assert _run("sources", "refresh") == 1


def test_browse_and_show_remote(home, capsys):
    _fetched(home, extra={"run.sh": "echo hi\n"})
    assert _run("browse", "pdf") == 0
    assert "mine:pdf" in capsys.readouterr().out
    assert _run("browse", "zzz") == 0
    assert "No skills found." in capsys.readouterr().out
    assert _run("show-remote", "mine:pdf") == 0
    out = capsys.readouterr().out
    assert "Warning: contains scripts: run.sh" in out and "Do it." in out
    assert _run("show-remote", "mine:nope") == 1
    assert _run("show-remote", "pdf") == 1


def test_install_writes_nothing_on_n_and_installs_on_y(home, monkeypatch, capsys):
    _fetched(home, extra={"run.sh": "echo hi\n"})
    _answer(monkeypatch, "n")
    assert _run("install", "mine:pdf") == 0
    out = capsys.readouterr().out
    assert "Warning: contains scripts" in out and "Nothing installed." in out
    assert not (home / ".whyline" / "skills" / "pdf").exists()
    _answer(monkeypatch, "y")
    assert _run("install", "mine:pdf", "--as", "reader") == 0
    assert (home / ".whyline" / "skills" / "reader" / "SKILL.md").is_file()
    assert _run("install", "mine:pdf", "--as", "reader", "--yes") == 1


def test_update_shows_diff_and_writes_nothing_on_n(home, monkeypatch, capsys):
    folder = _fetched(home)
    assert _run("install", "mine:pdf", "--yes") == 0
    capsys.readouterr()
    assert _run("update", "pdf") == 0
    assert "up to date" in capsys.readouterr().out
    (folder / "SKILL.md").write_text("---\nname: pdf\ndescription: reads pdf files\n---\nNew text.\n")
    installed = home / ".whyline" / "skills" / "pdf" / "SKILL.md"
    before = installed.read_text()
    _answer(monkeypatch, "")
    assert _run("update", "pdf") == 0
    out = capsys.readouterr().out
    assert "+New text." in out and "Nothing changed." in out
    assert installed.read_text() == before
    assert _run("update", "pdf", "--yes") == 0
    assert "New text." in installed.read_text()
    assert _run("update", "ghost") == 1
