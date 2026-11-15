from dataclasses import dataclass, replace
from pathlib import Path

from whyline.release import notes
from whyline.release.config import ReleaseConfig


@dataclass
class Res:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def make_run(tag: str | None, log: str = "feat: a\nfix: b\n"):
    calls: list[list[str]] = []

    def run(args, **kw):
        calls.append(list(args))
        if args[:2] == ["git", "describe"]:
            return Res(0, tag + "\n") if tag else Res(128, "", "no tags")
        if args[:2] == ["git", "log"]:
            return Res(0, log)
        return Res(1)

    run.calls = calls
    return run


def test_commits_since_tag(tmp_path):
    run = make_run("v1.2.0")
    assert notes.commits_since_last_tag(tmp_path, run=run) == ["feat: a", "fix: b"]
    assert ["git", "log", "--format=%s", "v1.2.0..HEAD"] in run.calls


def test_commits_without_tag_uses_last_50(tmp_path):
    run = make_run(None)
    assert notes.commits_since_last_tag(tmp_path, run=run) == ["feat: a", "fix: b"]
    assert ["git", "log", "--format=%s", "-50"] in run.calls


def test_prompt_includes_commits_and_style_example(tmp_path):
    (tmp_path / "docs/releases").mkdir(parents=True)
    (tmp_path / "docs/releases/v1.2.0.md").write_text("# v1.2.0\n\nOLD STYLE\n")
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return "<notes>\n# v1.3.0\n\n- Shiny\n</notes>"

    out = notes.draft(tmp_path, ReleaseConfig(), "1.3.0", ask_agent=ask, run=make_run("v1.2.0"))
    assert out == "# v1.3.0\n\n- Shiny\n"
    assert "v1.3.0" in seen[0]
    assert "- feat: a" in seen[0]
    assert "OLD STYLE" in seen[0]
    assert "Do not invent" in seen[0]


def test_prompt_without_previous_notes_has_no_example(tmp_path):
    seen = []
    notes.draft(tmp_path, ReleaseConfig(), "1.3.0",
                ask_agent=lambda p: seen.append(p) or "<notes>\nx\n</notes>", run=make_run("v1.2.0"))
    assert "previous release notes" not in seen[0]


def test_fallback_when_agent_fails(tmp_path):
    def boom(prompt):
        raise RuntimeError("all agents failed")

    out = notes.draft(tmp_path, ReleaseConfig(), "1.3.0", ask_agent=boom, run=make_run("v1.2.0"))
    assert out == notes.fallback("1.3.0", ["feat: a", "fix: b"])


def test_fallback_when_agent_returns_nothing(tmp_path):
    out = notes.draft(tmp_path, ReleaseConfig(), "1.3.0", ask_agent=lambda p: "  ",
                      run=make_run(None))
    assert out == notes.fallback("1.3.0", ["feat: a", "fix: b"])


def test_prompt_ends_with_the_marker_instruction():
    prompt = notes.build_prompt("1.3.0", ["feat: a"], "")
    assert prompt.rstrip().endswith(
        "Put the notes between a line <notes> and a line </notes>. Write nothing else.")


def test_notes_keep_only_the_marked_part(tmp_path):
    raw = ("Sure! Here you go:\n<notes>\nold\n</notes>\n"
           "<notes>\n\n# v1.3.0\n- Shiny\n\n</notes>\nHope it helps")
    assert notes.extract(raw) == "# v1.3.0\n- Shiny"
    out = notes.draft(tmp_path, ReleaseConfig(), "1.3.0", ask_agent=lambda p: raw,
                      run=make_run("v1.2.0"))
    assert out == "# v1.3.0\n- Shiny\n"


def test_missing_or_empty_pair_falls_back_and_says_so(tmp_path):
    assert notes.extract("no markers") is None
    assert notes.extract("<notes>\n  \n</notes>") is None
    for raw in ("# v1.3.0\n- chatter", "<notes>\n \n</notes>"):
        said = []
        out = notes.draft(tmp_path, ReleaseConfig(), "1.3.0", ask_agent=lambda p, r=raw: r,
                          run=make_run("v1.2.0"), say=said.append)
        assert out == notes.fallback("1.3.0", ["feat: a", "fix: b"])
        assert said == ["The agent's notes were not usable; using the commit list"]


def test_write_to_notes_path(tmp_path):
    path = notes.write(tmp_path, ReleaseConfig(), "1.3.0", "# v1.3.0")
    assert path == tmp_path / "docs/releases/v1.3.0.md"
    assert path.read_text() == "# v1.3.0\n"


def test_write_without_notes_path(tmp_path):
    cfg = replace(ReleaseConfig(), notes="")
    assert notes.write(tmp_path, cfg, "1.3.0", "text") is None
    assert not (tmp_path / "docs").exists()


# Real opening lines from the 0.3.70, 0.3.71 and 0.3.72 drafts, before the
# agent's narration was dropped by hand.
KNOWN_CHATTER = (
    "I'll check the project handoff and the existing release-note style, then write v0.3.70 notes only from those commit subjects.",
    "The 0.3.69 notes and version bump are already in the tree. I'll read those plus the notes template so 0.3.70 matches the same voice.",
    "I'll start with the project handoff, then read the existing notes and the RFB commits so the 0.3.71 write-up stays faithful to those subjects.",
    "No active handoff. I'll read the previous notes and the RFB commit subjects so the 0.3.71 write-up stays in the same voice and only covers what those commits actually say.",
    "I'll start with the project handoff, then read the full commit messages so the 0.3.72 notes stay inside what those subjects actually shipped.",
    "No active handoff. I'll pull the full RFB-8 and related commit messages so the notes stay inside what those subjects actually shipped.",
)

TALK_PHRASES = (
    "Here are the notes.",
    "Here is the summary.",
    "Here's what changed.",
    "Below are the highlights.",
    "Below is the list.",
    "I have drafted the notes.",
    "I've grouped the commits.",
    "I created these notes.",
    "I wrote a short summary.",
    "As requested, the notes follow.",
    "Let me know if this looks right.",
    "Please review the notes.",
    "Please let me know of gaps.",
    "Hope this helps with the release.",
    "Feel free to edit.",
    "Happy to tighten the wording.",
    "Does this cover the release?",
)


def test_known_chatter_is_flagged():
    text = "\n".join(KNOWN_CHATTER)
    problems = notes.lint(text, version="0.3.70")
    assert len(problems) == len(KNOWN_CHATTER)
    assert {p.line for p in problems} == set(range(1, len(KNOWN_CHATTER) + 1))
    assert all(p.removable for p in problems)


def test_ordinary_lines_pass():
    text = "\n".join((
        "Review rounds now show who approved each change.",
        "Fixed I/O errors when the disk is full.",
        "Published `my-package` to PyPI.",
        'Improved the "I have a plan already" form',
    ))
    assert notes.lint(text, version="1.2.0") == []


def test_talks_to_the_reader():
    for line in TALK_PHRASES:
        problems = notes.lint(line, version="1.2.0")
        assert len(problems) == 1, line
        assert problems[0].reason == "talks to the reader", line
        assert problems[0].removable
    problems = notes.lint("- Here are the notes I drafted.", version="1.2.0")
    assert problems[0].reason == "talks to the reader"


def test_first_person():
    for line in (
        "The installer saved my settings.",
        "The tool told me when a check failed.",
        "The notes I drafted stay in the file.",
        "I'm grouping the commits by kind.",
        "I'll list every user-facing change.",
    ):
        problems = notes.lint(line, version="1.2.0")
        assert len(problems) == 1, line
        assert problems[0].reason == "first person", line
        assert problems[0].removable


def test_process_noise():
    for line in (
        "chore: tick RCR-6 in the plan",
        "- chore: release v1.2.0",
        "1. chore: record decisions",
        "chore: move finished plans to plans/done",
        "- setup: assign implementer/tester/reviewer roles",
        "merge: origin/main into the release branch",
        "plan: console restart notice (CRS-1..4)",
    ):
        problems = notes.lint(line, version="1.2.0")
        assert len(problems) == 1, line
        assert problems[0].reason == "process noise", line
        assert problems[0].removable
    assert notes.lint("- feat: add a notes check", version="1.2.0") == []
    assert notes.lint("chore: something else", version="1.2.0") == []


def test_repeats_the_title():
    text = "# v1.2.0\n\n- Users can pause a run\n\n# v1.2.0\n"
    problems = notes.lint(text, version="1.2.0")
    assert [(p.line, p.reason, p.removable) for p in problems] == [
        (5, "repeats the title", True),
    ]


def test_code_fence_around_everything():
    text = "```markdown\n# v1.2.0\n\n- Users can pause a run\n```\n"
    problems = notes.lint(text, version="1.2.0")
    assert [(p.line, p.reason, p.removable) for p in problems] == [
        (1, "code fence around everything", True),
        (5, "code fence around everything", True),
    ]


def test_secret_shown_as_rule_name():
    key = "AKIA" + "QYLPMN5HHQKB3XZT"
    text = f"- token {key} was shipped"
    problems = notes.lint(text, version="1.2.0")
    assert len(problems) == 1
    problem = problems[0]
    assert problem.reason == "secret"
    assert problem.removable is True
    assert "aws-access-token" in problem.text
    assert key not in problem.text
    assert key not in problem.text.lower()
    cleaned = notes.clean(text, problems)
    assert key not in cleaned
    assert "token" not in cleaned


def test_home_path():
    for line in (
        "Logs were written to /Users/anish/whyline.",
        "The unit file lives in /home/anish/.config.",
        r"The installer used C:\Users\anish\AppData.",
    ):
        problems = notes.lint(line, version="1.2.0")
        assert len(problems) == 1, line
        assert problems[0].reason == "home path", line
        assert problems[0].removable
    assert notes.lint("Installed to /usr/local/bin.", version="1.2.0") == []


def test_email_address():
    text = "- Contact jane@example.com for the beta."
    problems = notes.lint(text, version="1.2.0")
    assert len(problems) == 1
    assert problems[0].reason == "email address"
    assert problems[0].removable
    allowed = frozenset({"jane@example.com"})
    assert notes.lint(text, version="1.2.0", allowed_emails=allowed) == []


def test_empty_heading_removed():
    text = (
        "# v1.2.0\n"
        "\n"
        "## Other\n"
        "\n"
        "- chore: tick RCR-6 in the plan\n"
        "\n"
        "## New\n"
        "\n"
        "- Users can pause a run\n"
    )
    problems = notes.lint(text, version="1.2.0")
    assert any(p.reason == "process noise" for p in problems)
    out = notes.clean(text, problems)
    assert "## Other" not in out
    assert "chore: tick" not in out
    assert "## New" in out
    assert "Users can pause a run" in out
    assert "\n\n\n" not in out


def test_problem_text_is_cut_to_120():
    line = "Here are " + ("x" * 200)
    problems = notes.lint(line, version="1.2.0")
    assert len(problems) == 1
    assert len(problems[0].text) == 120


def test_usable():
    assert notes.usable("# v1.2.0\n\n- Users can pause a run\n")
    assert notes.usable("# v1.2.0\n\nUsers can pause a run.\n")
    assert not notes.usable("# v1.2.0\n\n## New\n")
    assert not notes.usable("")
    assert not notes.usable("```\n```\n")
    assert notes.usable(notes.clean(
        "# v1.2.0\n\n- Users can pause a run\n- chore: tick RCR-6\n",
        notes.lint(
            "# v1.2.0\n\n- Users can pause a run\n- chore: tick RCR-6\n",
            version="1.2.0",
        ),
    ))


def test_only_process_commits():
    commits = (
        "chore: tick RCR-6 in the plan",
        "chore: release v1.2.0",
        "chore: record decisions",
        "chore: move finished plans to plans/done",
        "setup: assign implementer/tester/reviewer roles",
        "merge: origin/main into the release branch",
        "plan: console restart notice (CRS-1..4)",
    )
    assert notes.fallback("1.2.0", list(commits)) == "# v1.2.0\n\nMaintenance release.\n"
    assert notes.fallback("1.2.0", []) == "# v1.2.0\n\nMaintenance release.\n"


def test_feat_group():
    assert notes.fallback("1.2.0", ["feat: add a notes check"]) == (
        "# v1.2.0\n\n## New\n\n- Add a notes check\n"
    )


def test_fix_group():
    assert notes.fallback("1.2.0", ["fix: handle empty tags"]) == (
        "# v1.2.0\n\n## Fixed\n\n- Handle empty tags\n"
    )


def test_docs_group():
    assert notes.fallback("1.2.0", ["docs: drop the agent's narration"]) == (
        "# v1.2.0\n\n## Docs\n\n- Drop the agent's narration\n"
    )


def test_other_group():
    assert notes.fallback("1.2.0", ["chore: something else"]) == (
        "# v1.2.0\n\n## Other\n\n- Something else\n"
    )


def test_prefix_and_task_id_stripped():
    out = notes.fallback("1.2.0", ["feat: add a notes check (RCR-6)"])
    assert out == "# v1.2.0\n\n## New\n\n- Add a notes check\n"
    assert "feat:" not in out
    assert "(RCR-6)" not in out


def test_feat_scope_goes_to_new():
    assert notes.fallback("1.2.0", ["feat(notes): add a grouped fallback"]) == (
        "# v1.2.0\n\n## New\n\n- Add a grouped fallback\n"
    )


def test_fallback_passes_lint_for_every_kind():
    commits = [
        "feat: add a notes check (RCR-6)",
        "feat(notes): group the fallback",
        "fix: handle empty tags",
        "docs: drop the agent's narration",
        "chore: something else",
        "chore: tick RCR-6 in the plan",
        "chore: release v1.2.0",
        "chore: record decisions",
        "chore: move finished plans to plans/done",
        "setup: assign implementer/tester/reviewer roles",
        "merge: origin/main into the release branch",
        "plan: console restart notice (CRS-1..4)",
    ]
    out = notes.fallback("1.2.0", commits)
    assert notes.lint(out, version="1.2.0") == []
    assert out == (
        "# v1.2.0\n"
        "\n"
        "## New\n"
        "\n"
        "- Add a notes check\n"
        "- Group the fallback\n"
        "\n"
        "## Fixed\n"
        "\n"
        "- Handle empty tags\n"
        "\n"
        "## Docs\n"
        "\n"
        "- Drop the agent's narration\n"
        "\n"
        "## Other\n"
        "\n"
        "- Something else\n"
    )


DRAFT = "# v1.2.0\n\n- Users can pause a running relay\n"
COMMITS = ["feat: users can pause a running relay"]
INVENTED = "- Teleports the user to the moon instantly"
REWORDED = "- Pause a running relay from the console"


def test_build_review_prompt_puts_data_in_labelled_blocks():
    problems = [notes.Problem(3, "Here are the notes.", "talks to the reader", True)]
    draft = "# v1.2.0\n\nHere are the notes.\n- Users can pause a running relay\n"
    prompt = notes.build_review_prompt("1.2.0", COMMITS, draft, problems)
    assert "<commits>\nfeat: users can pause a running relay\n</commits>" in prompt
    assert "<draft>\n" + draft + "</draft>" in prompt or (
        "<draft>\n" + draft.rstrip("\n") + "\n</draft>" in prompt
    )
    assert "line 3: talks to the reader" in prompt
    assert "talk to the reader" in prompt.lower() or "talks to the reader" in prompt.lower()
    assert "first person" in prompt.lower()
    assert "process noise" in prompt.lower()
    assert "tighten" in prompt.lower()
    assert "keep every real change" in prompt.lower()
    assert "add nothing" in prompt.lower()
    assert prompt.rstrip().endswith(
        "Put the notes between a line <notes> and a line </notes>. Write nothing else.")


def test_reviewer_cannot_add():
    def ask(prompt):
        return (
            "<notes>\n"
            "# v1.2.0\n"
            "\n"
            "- Users can pause a running relay\n"
            f"{INVENTED}\n"
            "</notes>"
        )

    result = notes.review("1.2.0", COMMITS, DRAFT, [], ask_agent=ask)
    assert "Teleports" not in result.text
    assert "Users can pause a running relay" in result.text
    assert any("Teleports" in item for item in result.added)


def test_reworded_bullet_is_kept():
    def ask(prompt):
        return f"<notes>\n# v1.2.0\n\n{REWORDED}\n</notes>"

    result = notes.review("1.2.0", COMMITS, DRAFT, [], ask_agent=ask)
    assert "Pause a running relay from the console" in result.text
    assert result.added == ()


def test_removed_line_stays_removed():
    draft = "# v1.2.0\n\nHere are the notes.\n- Users can pause a running relay\n"
    problems = notes.lint(draft, version="1.2.0")

    def ask(prompt):
        assert "line 3: talks to the reader" in prompt
        return "<notes>\n# v1.2.0\n\n- Users can pause a running relay\n</notes>"

    result = notes.review("1.2.0", COMMITS, draft, problems, ask_agent=ask)
    assert "Here are the notes" not in result.text
    assert "Users can pause a running relay" in result.text


def test_unmarked_answer_returns_the_draft():
    result = notes.review(
        "1.2.0", COMMITS, DRAFT, [], ask_agent=lambda p: "looks good to me")
    assert result.text == DRAFT
    assert result.added == ()


def test_failed_turn_returns_the_draft():
    def ask(prompt):
        raise RuntimeError("agent down")

    result = notes.review("1.2.0", COMMITS, DRAFT, [], ask_agent=ask)
    assert result.text == DRAFT
    assert result.added == ()


def named_agent(name, answer=None, error=None):
    def ask(prompt):
        if error is not None:
            raise error
        return answer

    ask.agent = name
    return ask


def test_checked_uses_two_agents_and_reports_every_removed_line(tmp_path):
    before = (
        "# v1.3.0\n\nHere are the notes.\n"
        "- Users can pause a running relay\n"
    )
    writer = named_agent("claude", f"<notes>\n{before}</notes>")
    reviewer = named_agent(
        "grok",
        "<notes>\n# v1.3.0\n\nPlease review the notes.\n"
        "- Pause a running relay from the console\n</notes>",
    )
    said = []

    result = notes.checked(
        tmp_path,
        ReleaseConfig(),
        "1.3.0",
        ask_agent=writer,
        ask_reviewer=reviewer,
        run=make_run("v1.2.0", "feat: users can pause a running relay\n"),
        say=said.append,
    )

    assert result.before == before
    assert result.text == "# v1.3.0\n\n- Pause a running relay from the console\n"
    assert result.writer == "claude" and result.reviewer == "grok"
    assert result.removed == (
        "Here are the notes.",
        "- Users can pause a running relay",
        "Please review the notes.",
    )
    assert result.used_fallback is False
    assert result.summary == "Written by claude, checked by grok. 3 lines removed."
    assert said == [result.summary]


def test_checked_review_off_uses_fixed_rules_only(tmp_path):
    reviewer = named_agent("grok", error=AssertionError("review should be off"))
    result = notes.checked(
        tmp_path,
        replace(ReleaseConfig(), notes_review=False),
        "1.3.0",
        ask_agent=named_agent(
            "claude",
            "<notes>\n# v1.3.0\n\nHere are the notes.\n- Users can pause a run\n</notes>",
        ),
        ask_reviewer=reviewer,
        run=make_run(None),
    )
    assert "Here are" not in result.text
    assert result.reviewer == ""
    assert result.removed == ("Here are the notes.",)
    assert result.summary == "Written by claude, checked by fixed rules only."


def test_checked_with_one_agent_reports_writer_as_checker(tmp_path):
    result = notes.checked(
        tmp_path,
        ReleaseConfig(),
        "1.3.0",
        ask_agent=named_agent(
            "claude",
            "<notes>\n# v1.3.0\n\nHere are the notes.\n- Users can pause a run\n</notes>",
        ),
        run=make_run(None),
    )
    assert result.reviewer == "claude"
    assert result.summary == (
        "Written and checked by claude (only one agent is enabled). 1 lines removed."
    )


def test_checked_falls_back_when_cleaning_leaves_nothing_usable(tmp_path):
    said = []
    result = notes.checked(
        tmp_path,
        ReleaseConfig(),
        "1.3.0",
        ask_agent=named_agent("claude", "<notes>\n# v1.3.0\n\nHere are the notes.\n</notes>"),
        run=make_run(None),
        say=said.append,
    )
    assert result.text == notes.fallback("1.3.0", ["feat: a", "fix: b"])
    assert result.used_fallback is True
    assert result.before == "# v1.3.0\n\nHere are the notes.\n"
    assert result.summary == "The agent's notes couldn't be used; this is the commit list."
    assert said == [result.summary]


def test_notes_never_block_a_release(tmp_path, monkeypatch):
    fallback = notes.fallback("1.3.0", ["feat: a", "fix: b"])

    writer_failure = notes.checked(
        tmp_path,
        ReleaseConfig(),
        "1.3.0",
        ask_agent=named_agent("claude", error=RuntimeError("writer down")),
        run=make_run(None),
    )
    reviewer_failure = notes.checked(
        tmp_path,
        ReleaseConfig(),
        "1.3.0",
        ask_agent=named_agent("claude", f"<notes>\n{DRAFT}</notes>"),
        ask_reviewer=named_agent("grok", error=RuntimeError("reviewer down")),
        run=make_run(None),
    )

    monkeypatch.setattr(
        notes,
        "load_rules",
        lambda: (_ for _ in ()).throw(RuntimeError("bad rule")),
    )
    lint_failure = notes.checked(
        tmp_path,
        ReleaseConfig(),
        "1.3.0",
        ask_agent=named_agent("claude", f"<notes>\n{DRAFT}</notes>"),
        run=make_run(None),
    )

    for result in (writer_failure, reviewer_failure, lint_failure):
        assert result.text == fallback
        assert result.used_fallback is True
        assert result.summary == "The agent's notes couldn't be used; this is the commit list."

