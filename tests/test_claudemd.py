from whyline import claudemd


def test_install_creates_a_minimal_agents_import(tmp_path):
    path = tmp_path / "CLAUDE.md"
    assert claudemd.install(path) == "installed"
    content = path.read_text()
    assert content.splitlines()[0] == "@AGENTS.md"
    assert "canonical source" in content


def test_install_preserves_existing_claude_instructions(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("# Existing Claude rules\n\nKeep this.\n")
    assert claudemd.install(path) == "installed"
    content = path.read_text()
    assert content.startswith("# Existing Claude rules")
    assert "Keep this." in content
    assert "@AGENTS.md" in content


def test_install_is_idempotent(tmp_path):
    path = tmp_path / "CLAUDE.md"
    claudemd.install(path)
    assert claudemd.install(path) == "already-present"
    assert path.read_text().count("@AGENTS.md") == 1


def test_existing_exact_import_gets_the_canonical_source_guard(tmp_path):
    path = tmp_path / "CLAUDE.md"
    original = "@AGENTS.md\n\n# Claude-specific rule\nKeep this too.\n"
    path.write_text(original)
    assert claudemd.install(path) == "installed"
    content = path.read_text()
    assert content.startswith(original)
    assert content.count("@AGENTS.md") == 1
    assert "canonical source" in content
