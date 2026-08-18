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


def test_instruction_references_only_commands_that_exist():
    """Superseded 2026-08-18. This previously asserted the instruction must NOT
    mention `whyline brief`, because brief was gated on the M0 result and did not
    exist yet. M0 passed, brief shipped in 0.1.0, and the assertion then actively
    prevented the read instruction from being added — so it outlived its reason
    and blocked the fix. It now checks the real invariant: every command named
    here is one the CLI actually provides."""
    import re

    from whyline import cli

    named = set(re.findall(r"whyline ([a-z]+)", agentsmd.INSTRUCTION))
    assert named, "the instruction should name at least one command"
    assert named <= set(cli.COMMANDS), f"unknown commands referenced: {named - set(cli.COMMANDS)}"


def test_the_instruction_tells_agents_to_read_not_only_to_write():
    """0.1.0 shipped with only the write half, so nothing ever asked an agent to
    consult the history — half the product had no instruction behind it."""
    assert "whyline brief" in agentsmd.INSTRUCTION
    assert "whyline note" in agentsmd.INSTRUCTION


def test_both_directives_carry_all_four_parts_that_make_an_instruction_fire():
    """Trigger, exact command, pre-authorisation, verification. The observations
    doc records a declarative instruction being ignored for six hours while an
    imperative one fired twice unprompted."""
    text = agentsmd.INSTRUCTION
    # Assert on content, not line wrapping: the prose is hard-wrapped, so a
    # phrase can straddle a newline. Collapsing whitespace first means rewrapping
    # the instruction cannot break these assertions, while changing what it says
    # still does.
    flat = " ".join(text.split())
    # trigger
    assert "At the start of a session" in flat
    assert "After completing any non-trivial change" in flat
    # exact commands, each indented on its own line in the real text
    assert "    whyline brief" in text
    assert '    whyline note "<one-line decision>"' in text
    # pre-authorisation, once per directive
    assert flat.count("Do not ask permission") == 2
    # verification for the read half
    assert "say so in your first message" in flat


def test_the_declarative_sentence_that_was_ignored_is_gone():
    """It was read as a prohibition and inverted a permission into a restriction."""
    assert "rather than appending it to AGENTS.md" not in agentsmd.INSTRUCTION


def test_install_upgrades_an_outdated_block(tmp_path):
    """0.1.0 returned already-present for any existing block, so an improved
    instruction could never reach a repository that had already run init."""
    path = tmp_path / "AGENTS.md"
    stale = f"""# Project

Human-written conventions above.

{agentsmd.BEGIN}
## Recording decisions

Old wording that predates the read instruction.
{agentsmd.END}

More human-written notes below.
"""
    path.write_text(stale, encoding="utf-8")
    assert agentsmd.install(path) == "upgraded"
    updated = path.read_text(encoding="utf-8")
    assert "whyline brief" in updated
    assert "Old wording that predates" not in updated
    # everything the human wrote is preserved
    assert "Human-written conventions above." in updated
    assert "More human-written notes below." in updated
    assert updated.count(agentsmd.BEGIN) == 1


def test_install_is_still_idempotent_when_current(tmp_path):
    path = tmp_path / "AGENTS.md"
    assert agentsmd.install(path) == "installed"
    assert agentsmd.install(path) == "already-present"
    assert agentsmd.install(path) == "already-present"
    assert path.read_text(encoding="utf-8").count(agentsmd.BEGIN) == 1
