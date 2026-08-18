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


def test_install_upgrades_an_outdated_guidance_block(tmp_path):
    """Same frozen-block problem as agentsmd: an older wording would otherwise
    never be replaced."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(
        "# My project\n\n@AGENTS.md\n\n"
        f"{claudemd.BEGIN}\nOld guidance wording.\n{claudemd.END}\n\nMy own notes.\n",
        encoding="utf-8",
    )
    assert claudemd.install(path) == "upgraded"
    updated = path.read_text(encoding="utf-8")
    assert "Old guidance wording." not in updated
    assert "canonical source" in updated
    assert "My own notes." in updated
    assert updated.count(claudemd.BEGIN) == 1


def test_install_adds_a_missing_import_without_losing_guidance(tmp_path):
    """Guidance without the @AGENTS.md import means Claude never reads the
    canonical instructions at all — the shim is inert."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(
        f"# Mine\n\n{claudemd.BEGIN}\nOld guidance.\n{claudemd.END}\n", encoding="utf-8"
    )
    assert claudemd.install(path) == "upgraded"
    updated = path.read_text(encoding="utf-8")
    assert any(line.strip() == claudemd.IMPORT for line in updated.splitlines())
    assert "# Mine" in updated


def test_install_is_still_idempotent_when_current(tmp_path):
    path = tmp_path / "CLAUDE.md"
    assert claudemd.install(path) == "installed"
    assert claudemd.install(path) == "already-present"
