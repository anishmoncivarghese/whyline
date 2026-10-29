from pathlib import Path

import pytest

from whyline.agents import definitions as d, service, state, templates


def _write_template(
    root: Path,
    name: str,
    *,
    toml_text: str | None = 'title = "Sample"\nabout = "One line."\nrunner = "claude"\n',
    instructions: str | None = "Summarise the files.\n",
    files: dict[str, str] | None = None,
) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    if toml_text is not None:
        (folder / "agent.toml").write_text(toml_text, encoding="utf-8")
    if instructions is not None:
        (folder / "instructions.md").write_text(instructions, encoding="utf-8")
    if files:
        for rel, body in files.items():
            target = folder / "files" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
    return folder


def test_list_templates_includes_example_digest_and_normalises_descriptions(tmp_path):
    shipped = templates.list_templates()
    by_name = {item.name: item for item in shipped}
    assert "example-digest" in by_name
    digest = by_name["example-digest"]
    name, title, about = digest
    assert name == "example-digest"
    assert title == "Example digest"
    assert about and "\n" not in about
    assert digest.description == about

    _write_template(
        tmp_path,
        "beta",
        toml_text='title = "Beta"\nabout = "First line\\n  second line"\nrunner = "claude"\n',
    )
    _write_template(
        tmp_path,
        "alpha",
        toml_text='title = "Alpha"\nabout = "Short"\nrunner = "codex"\n',
    )
    custom = templates.list_templates(templates_dir=tmp_path)
    assert [(t.name, t.title, t.about) for t in custom] == [
        ("alpha", "Alpha", "Short"),
        ("beta", "Beta", "First line second line"),
    ]


def test_definitions_parse_ignores_template_title_and_about(home):
    parsed = d.parse(
        'name = "x"\ntitle = "Title"\nabout = "About"\n'
        'instructions = "Do nothing."\nrunner = "claude"\nworkdir = "~/x"\n',
        kind="personal",
        path=home / ".whyline/agents/x.toml",
    )
    assert parsed.name == "x"
    assert parsed.runner == "claude"


def test_create_into_tmp_copies_files_calls_save_new_and_is_not_accepted(
    tmp_path, home, monkeypatch
):
    calls: list[d.AgentDef] = []
    real_save_new = service.save_new

    def spy_save_new(defn: d.AgentDef) -> Path:
        calls.append(defn)
        return real_save_new(defn)

    monkeypatch.setattr(service, "save_new", spy_save_new)

    workdir = tmp_path / "digest-work"
    defn = templates.create("example-digest", "my-digest", workdir)

    assert len(calls) == 1 and calls[0] == defn
    assert defn.name == "my-digest"
    assert defn.kind == "personal"
    assert defn.workdir == str(workdir)
    assert defn.root == workdir
    assert defn.trigger == d.Trigger(kind="manual", min_gap_minutes=10)
    assert defn.sources == ("notes.md",)
    assert "Read the source files" in defn.instructions
    assert (workdir / "notes.md").is_file()
    assert defn.path == home / ".whyline/agents/my-digest.toml"
    assert d.load(defn.path, kind="personal") == defn

    conn = state.connect()
    try:
        assert state.get(conn, defn.agent_id) is None
        assert state.status_of(conn, defn) == "not accepted"
        assert state.check_hash(conn, defn) == "not accepted"
    finally:
        conn.close()
    [row] = service.rows(None)
    assert row.status == "not accepted"


def test_create_works_when_template_has_no_files_folder(tmp_path, home):
    tpl_root = tmp_path / "templates"
    _write_template(tpl_root, "bare")
    workdir = tmp_path / "bare-work"
    defn = templates.create("bare", "bare-agent", workdir, templates_dir=tpl_root)
    assert workdir.is_dir()
    assert list(workdir.iterdir()) == []
    assert defn.name == "bare-agent"


def test_create_keeps_existing_files_in_workdir(tmp_path, home):
    tpl_root = tmp_path / "templates"
    _write_template(
        tpl_root,
        "seeded",
        files={
            "notes.md": "template notes\n",
            "nested/keep.txt": "template keep\n",
            "nested/added.txt": "template added\n",
        },
    )
    workdir = tmp_path / "work"
    (workdir / "nested").mkdir(parents=True)
    (workdir / "notes.md").write_text("user notes\n", encoding="utf-8")
    (workdir / "nested/keep.txt").write_text("", encoding="utf-8")

    templates.create("seeded", "seeded", workdir, templates_dir=tpl_root)

    assert (workdir / "notes.md").read_text(encoding="utf-8") == "user notes\n"
    assert (workdir / "nested/keep.txt").read_text(encoding="utf-8") == ""
    assert (workdir / "nested/added.txt").read_text(encoding="utf-8") == "template added\n"


def test_create_skips_target_symlinks_without_writing_outside_workdir(tmp_path, home):
    tpl_root = tmp_path / "templates"
    _write_template(
        tpl_root,
        "symlink-check",
        files={
            "safe.txt": "safe content\n",
            "linked_dir/seed.txt": "escaped dir file\n",
            "linked_dir/sub/deep.txt": "escaped nested file\n",
            "nested/sub_link/seed.txt": "escaped sub link\n",
            "nested/sibling.txt": "nested safe\n",
            "broken_dir/seed.txt": "escaped broken dir\n",
            "dangling_file.txt": "escaped dangling file\n",
            "live_file.txt": "overwritten live file\n",
        },
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "live.txt").write_text("keep outside\n", encoding="utf-8")

    workdir = tmp_path / "work"
    (workdir / "nested").mkdir(parents=True)
    (workdir / "linked_dir").symlink_to(outside)
    (workdir / "nested/sub_link").symlink_to(outside)
    (workdir / "broken_dir").symlink_to(outside / "missing_dir")
    (workdir / "dangling_file.txt").symlink_to(outside / "dangling_target.txt")
    (workdir / "live_file.txt").symlink_to(outside / "live.txt")

    templates.create("symlink-check", "symlink-check", workdir, templates_dir=tpl_root)

    # Nothing new was created outside the workdir, and existing outside files are intact.
    assert sorted(p.name for p in outside.iterdir()) == ["live.txt"]
    assert (outside / "live.txt").read_text(encoding="utf-8") == "keep outside\n"
    assert not (outside / "seed.txt").exists()
    assert not (outside / "sub").exists()
    assert not (outside / "missing_dir").exists()
    assert not (outside / "dangling_target.txt").exists()

    # Existing symlink entries in workdir are preserved, and safe files are copied.
    assert (workdir / "linked_dir").is_symlink()
    assert (workdir / "nested/sub_link").is_symlink()
    assert (workdir / "broken_dir").is_symlink()
    assert (workdir / "dangling_file.txt").is_symlink()
    assert (workdir / "live_file.txt").is_symlink()
    assert (workdir / "safe.txt").read_text(encoding="utf-8") == "safe content\n"
    assert (workdir / "nested/sibling.txt").read_text(encoding="utf-8") == "nested safe\n"

    # A symlinked workdir root itself also writes nothing into its target.
    linked_workdir = tmp_path / "linked-workdir"
    linked_workdir.symlink_to(outside)
    templates.create("symlink-check", "symlink-root", linked_workdir, templates_dir=tpl_root)
    assert linked_workdir.is_symlink()
    assert sorted(p.name for p in outside.iterdir()) == ["live.txt"]


@pytest.mark.parametrize(
    "setup_kwargs, template_name, agent_name",
    [
        ({}, "missing-template", "ok"),
        ({}, "../escape", "ok"),
        ({"toml_text": None}, "no-toml", "ok"),
        ({"instructions": None}, "no-instructions", "ok"),
        ({"instructions": "   \n"}, "blank-instructions", "ok"),
        ({"toml_text": "not = [valid"}, "bad-toml", "ok"),
        ({"toml_text": 'runner = "gpt"\n'}, "bad-runner", "ok"),
        ({"toml_text": 'runner = "claude"\nworkdir = "~/x"\n'}, "has-workdir", "ok"),
        ({"toml_text": 'title = 123\nrunner = "claude"\n'}, "bad-title", "ok"),
        ({"toml_text": 'about = false\nrunner = "claude"\n'}, "bad-about", "ok"),
        ({"toml_text": 'runner = "claude"\ntrigger = "daily"\n'}, "bad-trigger", "ok"),
        ({"toml_text": 'name = "Bad Name"\nrunner = "claude"\n'}, "bad-tpl-name", "ok"),
        ({}, "valid-tpl", "Bad Agent Name"),
    ],
)
def test_invalid_template_or_name_raises_definition_error(
    tmp_path, home, setup_kwargs, template_name, agent_name
):
    tpl_root = tmp_path / "templates"
    tpl_root.mkdir()
    if template_name not in ("missing-template", "../escape"):
        _write_template(tpl_root, template_name, **setup_kwargs)
    workdir = tmp_path / "out"

    with pytest.raises(d.DefinitionError):
        templates.create(template_name, agent_name, workdir, templates_dir=tpl_root)

    assert not workdir.exists()
    assert not (home / ".whyline/agents").exists()


def test_name_clash_is_refused_without_touching_existing_agent(tmp_path, home):
    first_dir = tmp_path / "first"
    first = templates.create("example-digest", "digest", first_dir)
    service.accept("digest", None)

    second_dir = tmp_path / "second"
    with pytest.raises(d.DefinitionError, match="already exists"):
        templates.create("example-digest", "digest", second_dir)

    assert not second_dir.exists()
    assert d.load(first.path, kind="personal") == first
    conn = state.connect()
    try:
        assert state.status_of(conn, first) == "active"
    finally:
        conn.close()

    # Clash against a personal agent stored under a different filename.
    (home / ".whyline/agents/custom-file.toml").write_text(
        'name = "other-name"\ninstructions = "x"\nrunner = "claude"\nworkdir = "~"\n',
        encoding="utf-8",
    )
    with pytest.raises(d.DefinitionError, match="already exists"):
        templates.create("example-digest", "other-name", tmp_path / "third")
