from whyline import agentsmd


def test_install_creates_the_file_with_markers(tmp_path):
    path = tmp_path / "AGENTS.md"
    assert agentsmd.install(path) == "installed"
    content = path.read_text()
    assert agentsmd.BEGIN in content
    assert agentsmd.END in content
    assert "whyline note" in content


def test_install_appends_and_preserves_existing_content(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text("# Project\n\nExisting conventions.\n")
    agentsmd.install(path)
    content = path.read_text()
    assert "Existing conventions." in content
    assert agentsmd.BEGIN in content


def test_install_is_idempotent(tmp_path):
    path = tmp_path / "AGENTS.md"
    agentsmd.install(path)
    assert agentsmd.install(path) == "already-present"
    assert path.read_text().count(agentsmd.BEGIN) == 1


def test_instruction_does_not_reference_gated_brief_command():
    assert "whyline brief" not in agentsmd.INSTRUCTION
