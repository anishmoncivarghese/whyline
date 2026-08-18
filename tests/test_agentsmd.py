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


def test_the_read_directive_carries_four_parts_and_the_write_directive_three():
    """Trigger, exact command, pre-authorisation, verification. The observations
    doc records a declarative instruction being ignored for six hours while an
    imperative one fired twice unprompted.

    Renamed 0.1.3. The old name claimed *both* directives carried all four, which
    this test never actually asserted — it only ever checked verification for the
    read half, because the write half has never had one. That asymmetry is
    deliberate, not an oversight: the write half fires reliably without it (M0
    measured 150%/130%), so adding one would change a working instruction on
    theory. The name now matches what is verified."""
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


def test_the_write_trigger_covers_review_not_only_authorship():
    """Added 0.1.3. CodeGraph Tasks 10, 12 and 13 each had the implementer record
    and the reviewer not. "After completing any non-trivial change" names someone
    who completed a change, so a reviewer following it exactly concludes it is not
    addressed to them — their reasoning went to a gitignored ledger instead."""
    flat = " ".join(agentsmd.INSTRUCTION.split())
    assert "or after reviewing someone else's" in flat
    assert "Reviewing counts as deciding" in flat


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
    assert agentsmd.install(path).startswith("upgraded")
    updated = path.read_text(encoding="utf-8")
    assert "whyline brief" in updated
    assert "Old wording that predates" not in updated
    # everything the human wrote is preserved
    assert "Human-written conventions above." in updated
    assert "More human-written notes below." in updated
    assert updated.count(agentsmd.BEGIN) == 1


def test_upgrading_copies_the_replaced_block_beside_the_file(tmp_path):
    """Added 0.1.3 after review. Text inside the markers is replaced wholesale —
    that is the contract — but 0.1.3 is the first release to change the block's
    content since init shipped, so it is the first to exercise this path in real
    repositories. Anything a human put inside the markers would vanish silently,
    which contradicts the project's "degrade with a warning, never fail silently"
    invariant. We cannot tell old whyline wording from a human addition without
    keeping every prior version forever, so the replaced text is copied out
    instead of being judged."""
    path = tmp_path / "AGENTS.md"
    stale = (
        f"{agentsmd.BEGIN}\n## Recording decisions\n\n"
        "IMPORTANT: our team also requires a Jira ticket ID in every note.\n"
        f"{agentsmd.END}\n"
    )
    path.write_text(stale, encoding="utf-8")

    outcome = agentsmd.install(path)

    backup = tmp_path / ".whyline" / "AGENTS.md.bak"
    assert backup.exists(), "the replaced block must be recoverable"
    assert "Jira ticket ID" in backup.read_text(encoding="utf-8")
    assert ".whyline/AGENTS.md.bak" in outcome, "tell the caller where it went"
    # The live file really was upgraded, not left alone to protect the text.
    assert "Jira ticket ID" not in path.read_text(encoding="utf-8")
    assert "or after reviewing someone else's" in path.read_text(encoding="utf-8")


def test_the_backup_goes_where_whylines_own_gitignore_covers_it(tmp_path):
    """It must not land beside AGENTS.md. whyline manages `.whyline/.gitignore`
    and never touches the repository's own, so a sibling file would show up
    untracked in every repo that upgrades — and `init` would have to edit a file
    the human owns to silence it. `*.bak` in GITIGNORE_LINES covers this path."""
    from whyline import cli

    path = tmp_path / "AGENTS.md"
    path.write_text(f"{agentsmd.BEGIN}\nstale\n{agentsmd.END}\n", encoding="utf-8")
    agentsmd.install(path)

    assert not list(tmp_path.glob("*.bak")), "must not litter the repository root"
    assert "*.bak" in cli.GITIGNORE_LINES


def test_a_fresh_install_leaves_no_backup(tmp_path):
    """Only an upgrade replaces text, so only an upgrade copies anything out."""
    path = tmp_path / "AGENTS.md"
    assert agentsmd.install(path) == "installed"
    assert not (tmp_path / ".whyline" / "AGENTS.md.bak").exists()


def test_install_is_still_idempotent_when_current(tmp_path):
    path = tmp_path / "AGENTS.md"
    assert agentsmd.install(path) == "installed"
    assert agentsmd.install(path) == "already-present"
    assert agentsmd.install(path) == "already-present"
    assert path.read_text(encoding="utf-8").count(agentsmd.BEGIN) == 1
