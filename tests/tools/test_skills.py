import pytest

from whyline import cli
from whyline.tools import skills, users


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.setattr(users, "_providers", {})
    return h


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    return r


def _skill(base, name, description="Does a thing", fm_name=None, extra=None):
    folder = base / name
    folder.mkdir(parents=True)
    lines = ["---", f"name: {fm_name or name}"]
    if description:
        lines.append(f"description: {description}")
    lines += ["---", "", "Body."]
    (folder / "SKILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for rel, text in (extra or {}).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    return folder


def test_discovery_from_all_four_places_in_order(home, repo):
    _skill(home / ".whyline" / "skills", "a")
    _skill(repo / ".whyline" / "skills", "b")
    _skill(home / ".claude" / "skills", "c")
    _skill(repo / ".claude" / "skills", "d")
    assert [s.ref for s in skills.find(repo)] == [
        "whyline:a", "whyline-repo:b", "claude:c", "claude-project:d"]
    assert [s.ref for s in skills.find(None)] == ["whyline:a", "claude:c"]
    assert skills.get("claude-project:d", repo).description == "Does a thing"


def test_front_matter_parsing():
    text = "---\nname: x\ndescription: \"Quoted: yes\"\nother\n---\nbody"
    assert skills.parse_front_matter(text) == {"name": "x", "description": "Quoted: yes"}
    assert skills.parse_front_matter("no front matter") == {}
    assert skills.parse_front_matter("---\nname: x\n") == {}


def test_broken_skills_say_why(home, repo):
    base = home / ".claude" / "skills"
    _skill(base, "nodesc", description="")
    _skill(base, "wrong", fm_name="other")
    (base / "nofile").mkdir()
    found = {s.name: s for s in skills.find(repo)}
    assert "description" in found["nodesc"].problem
    assert "does not match" in found["wrong"].problem
    assert found["nofile"].problem == "no SKILL.md"
    assert all(s.broken for s in found.values())


def test_create_and_copy(home, repo):
    made = skills.create("notes", "Take notes", "Write.")
    assert made.ref == "whyline:notes" and not made.broken
    assert (home / ".whyline" / "skills" / "notes" / "SKILL.md").is_file()
    in_repo = skills.create("local", "Repo only", "x", repo_root=repo)
    assert in_repo.origin == "whyline-repo"
    _skill(home / ".claude" / "skills", "big", extra={"refs/a.txt": "hello"})
    copied = skills.copy_to_whyline("claude:big", repo)
    assert copied.ref == "whyline:big" and "refs/a.txt" in copied.files
    with pytest.raises(ValueError):
        skills.copy_to_whyline("claude:big", repo)  # already there
    with pytest.raises(ValueError):
        skills.create("Bad Name", "d", "b")
    with pytest.raises(ValueError):
        skills.create("huge", "d", "x" * skills.SKILL_LIMIT)


def test_edit_and_remove(home, repo):
    skills.create("notes", "Take notes", "Write.")
    changed = skills.edit("whyline:notes", repo, description="New words")
    assert changed.description == "New words"
    text = (changed.path / "SKILL.md").read_text(encoding="utf-8")
    assert text.rstrip().endswith("Write.")
    skills.edit("whyline:notes", repo, body="Fresh.")
    assert skills.body_of((changed.path / "SKILL.md").read_text(encoding="utf-8")) == "Fresh."
    skills.remove("whyline:notes", repo)
    assert not changed.path.exists()


def test_claude_skills_refused(home, repo):
    _skill(home / ".claude" / "skills", "c")
    for call in (lambda: skills.edit("claude:c", repo, description="x"),
                 lambda: skills.remove("claude:c", repo)):
        with pytest.raises(ValueError, match="Claude skills are read where they are. Copy to whyline to change it."):
            call()
    assert (home / ".claude" / "skills" / "c").exists()


def test_remove_refused_while_used(home, repo):
    skills.create("notes", "Take notes", "Write.")
    users.register("agent", lambda: [users.Use("skill", "whyline:notes", "agent digest")])
    with pytest.raises(ValueError, match="agent digest"):
        skills.remove("whyline:notes", repo)
    users.unregister("agent")
    skills.remove("whyline:notes", repo)


def test_cli(home, repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    _skill(home / ".claude" / "skills", "c")
    assert cli.main(["tools", "skills", "new", "mine", "--description", "Mine", "--body", "Hi"]) == 0
    assert cli.main(["tools", "skills", "copy", "claude:c"]) == 0
    capsys.readouterr()
    assert cli.main(["tools", "skills", "list"]) == 0
    out = capsys.readouterr().out
    assert "whyline:mine" in out and "whyline:c" in out and "claude:c" in out
    assert cli.main(["tools", "skills", "show", "whyline:mine"]) == 0
    assert cli.main(["tools", "skills", "edit", "claude:c", "--description", "x"]) == 1
    assert "Copy to whyline" in capsys.readouterr().err
    assert cli.main(["tools", "skills", "remove", "whyline:mine"]) == 0
    assert cli.main(["tools", "skills", "show", "whyline:mine"]) == 1
