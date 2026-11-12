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
    assert out == "# v1.3.0\n\n- feat: a\n- fix: b\n"


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
