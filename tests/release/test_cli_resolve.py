"""`whyline release resolve`: each form calls the functions the console will call."""

import pytest

from whyline.console import fixmode
from whyline.release import cli as release_cli
from whyline.release import conflicts as release_conflicts
from whyline.release import plan as release_plan
from whyline.release import ready as release_ready
from whyline.release import resolve as release_resolve
from whyline.release import state as release_state


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n')
    monkeypatch.setattr(release_cli, "_root", lambda: tmp_path)
    return tmp_path


def tty(monkeypatch, value):
    monkeypatch.setattr(release_cli, "_interactive", lambda: value)


def answers(monkeypatch, *texts):
    given = list(texts)
    monkeypatch.setattr("builtins.input", lambda prompt="": given.pop(0))
    return given


COMMIT = release_resolve.Option("commit", "Commit them", "run", needs="message", recommended=True)
STASH = release_resolve.Option("stash", "Stash them", "run")
CLEAN = release_resolve.Resolution("clean", "Uncommitted changes: a.py", ("a.py (changed)",),
                                   (COMMIT, STASH))
SETTLE = release_resolve.Option("conflicts", "Settle the conflicts", "conflicts",
                                recommended=True)
SYNCED = release_resolve.Resolution("synced", "Behind main", ("1 commit behind",), (SETTLE,))


class Resolver:
    """Everything resolve touches, faked; `calls` is what changed anything."""

    def __init__(self, monkeypatch, resolutions=(CLEAN,)):
        self.calls = []
        self.checks = 0
        self.fixed = False  # True: the item passes on every check after the first
        items = [release_ready.ReadyItem(r.key, False, r.title) for r in resolutions]
        by_key = {r.key: r for r in resolutions}

        def check(root, cfg, version):
            self.checks += 1
            return [release_ready.ReadyItem("git", True, "git is installed"),
                    *([] if self.fixed and self.checks > 1 else items)]

        monkeypatch.setattr(release_ready, "check", check)
        monkeypatch.setattr(release_ready, "default_fetch", lambda root, branch: None)
        monkeypatch.setattr(release_resolve, "explain",
                            lambda root, cfg, v, item, **k: by_key[item.key])
        monkeypatch.setattr(release_resolve, "preview",
                            lambda *a, **k: release_resolve.Preview(
                                ("Commit 1 file",), (("git", "commit"),)))
        monkeypatch.setattr(release_resolve, "apply", self.apply)

    def apply(self, root, cfg, version, option, **kw):
        self.calls.append(("apply", option.id, kw.get("message"), kw.get("key")))
        return release_resolve.Outcome(True, "Committed 1 file", 1, "snap1")


def test_lists_title_facts_and_numbered_options(root, monkeypatch, capsys):
    Resolver(monkeypatch)
    assert release_cli.main(["resolve"]) == 0
    out = capsys.readouterr().out
    assert "✗ Uncommitted changes: a.py" in out and "a.py (changed)" in out
    assert "1. Commit them [commit] (recommended)" in out
    assert "2. Stash them [stash]\n" in out


def test_nothing_failed_says_so(root, monkeypatch, capsys):
    monkeypatch.setattr(release_ready, "check",
                        lambda *a, **k: [release_ready.ReadyItem("git", True, "ok")])
    assert release_cli.main(["resolve"]) == 0
    assert "Nothing to resolve" in capsys.readouterr().out


def test_reads_a_stopped_release_instead_of_running_ready(root, monkeypatch, capsys):
    release_state.save(root, release_state.State(
        version="1.2.4", step_ids=["a"], reason="conflicts", kind="merge-conflict",
        data={"files": ["x.md"]}))
    seen = []
    monkeypatch.setattr(release_ready, "check", lambda *a, **k: seen.append("ready") or [])
    monkeypatch.setattr(release_resolve, "explain_stop", lambda *a, **k: SYNCED)
    assert release_cli.main(["resolve"]) == 0
    assert seen == [] and "Behind main" in capsys.readouterr().out


def test_unknown_key_and_option_exit_two_with_the_choices(root, monkeypatch, capsys):
    Resolver(monkeypatch)
    assert release_cli.main(["resolve", "nope"]) == 2
    assert "clean" in capsys.readouterr().err
    assert release_cli.main(["resolve", "clean", "--do", "nope"]) == 2
    err = capsys.readouterr().err
    assert "commit" in err and "stash" in err
    assert release_cli.main(["resolve", "--do", "commit"]) == 2


def test_do_shows_the_preview_and_does_nothing_on_n(root, monkeypatch, capsys):
    fake = Resolver(monkeypatch)
    tty(monkeypatch, True)
    asked = answers(monkeypatch, "n")
    assert release_cli.main(["resolve", "clean", "--do", "commit", "--message", "wip"]) == 1
    out = capsys.readouterr().out
    assert "Commit 1 file" in out and "$ git commit" in out and "Nothing was done" in out
    assert fake.calls == [] and asked == []


def test_do_needs_a_terminal_or_yes(root, monkeypatch, capsys):
    fake = Resolver(monkeypatch)
    tty(monkeypatch, False)
    assert release_cli.main(["resolve", "clean", "--do", "stash"]) == 1
    assert "No terminal" in capsys.readouterr().err and fake.calls == []


def test_do_runs_prints_the_outcome_and_rechecks_that_item(root, monkeypatch, capsys):
    fake = Resolver(monkeypatch)
    fake.fixed = True
    tty(monkeypatch, True)
    answers(monkeypatch, "y")
    assert release_cli.main(["resolve", "clean", "--do", "1", "--message", "wip"]) == 0
    out = capsys.readouterr().out
    assert fake.calls == [("apply", "commit", "wip", "clean")]
    assert "Committed 1 file" in out
    assert "is no longer in the Ready check" in out and fake.checks == 2


def test_do_recheck_prints_the_line_when_still_failing(root, monkeypatch, capsys):
    fake = Resolver(monkeypatch)
    assert release_cli.main(["resolve", "clean", "--do", "stash", "--yes"]) == 0
    assert "✗ Uncommitted changes: a.py" in capsys.readouterr().out.splitlines()[-1]


def test_do_failure_exits_one_and_still_rechecks(root, monkeypatch, capsys):
    fake = Resolver(monkeypatch)
    monkeypatch.setattr(release_resolve, "apply",
                        lambda *a, **k: release_resolve.Outcome(False, "git commit failed"))
    assert release_cli.main(["resolve", "clean", "--do", "stash", "--yes"]) == 1
    assert "git commit failed" in capsys.readouterr().out and fake.checks == 2


def test_commit_without_a_message_exits_two(root, monkeypatch, capsys):
    fake = Resolver(monkeypatch)
    assert release_cli.main(["resolve", "clean", "--do", "commit", "--yes"]) == 2
    assert "--message" in capsys.readouterr().err and fake.calls == []


CONFLICTS = [
    release_conflicts.Conflict("plans/a.plan.md", 2, "lines", release_conflicts.TICKS),
    release_conflicts.Conflict("src/b.py", 1, "lines", "both changed the same line"),
    release_conflicts.Conflict("img.png", 1, "binary"),
]


def test_conflicts_prints_each_file_with_places_and_reading(root, monkeypatch, capsys):
    Resolver(monkeypatch, (SYNCED,))
    monkeypatch.setattr(release_conflicts, "read", lambda *a, **k: CONFLICTS)
    assert release_cli.main(["resolve", "synced", "--conflicts"]) == 0
    out = capsys.readouterr().out
    assert "plans/a.plan.md: 2 places (lines)" in out and "only ticked and unticked" in out
    assert "src/b.py: 1 place (lines)" in out and "choices: ours, theirs, agent" in out


def test_conflicts_without_that_option_exits_two(root, monkeypatch, capsys):
    Resolver(monkeypatch)
    assert release_cli.main(["resolve", "clean", "--conflicts"]) == 2


def test_merge_passes_the_keeps_and_the_tick_default(root, monkeypatch, capsys):
    Resolver(monkeypatch, (SYNCED,))
    monkeypatch.setattr(release_conflicts, "read", lambda *a, **k: CONFLICTS[:2])
    previews = []
    monkeypatch.setattr(release_conflicts, "preview",
                        lambda r, b, choices, **k: previews.append(dict(choices))
                        or {p: "line\n" for p in choices})
    merged = []
    monkeypatch.setattr(release_conflicts, "merge",
                        lambda r, cfg, v, choices, **k: merged.append(dict(choices))
                        or release_resolve.Outcome(True, "Merged main", 1, "snapM"))
    recorded = []
    monkeypatch.setattr(release_resolve, "_record", lambda *a, **k: recorded.append(a[2:5]))
    assert release_cli.main(["resolve", "synced", "--do", "merge", "--keep", "src/b.py=theirs",
                             "--yes"]) == 0
    want = {"plans/a.plan.md": "ticks", "src/b.py": "theirs"}
    assert merged == [want] and previews == [want]
    assert recorded == [("merge", "synced", "")]
    assert "Merged main" in capsys.readouterr().out


def test_merge_runs_nothing_on_n(root, monkeypatch, capsys):
    Resolver(monkeypatch, (SYNCED,))
    monkeypatch.setattr(release_conflicts, "read", lambda *a, **k: CONFLICTS[:2])
    monkeypatch.setattr(release_conflicts, "preview", lambda r, b, c, **k: {p: "x" for p in c})
    merged = []
    monkeypatch.setattr(release_conflicts, "merge", lambda *a, **k: merged.append(1))
    tty(monkeypatch, True)
    answers(monkeypatch, "n")
    assert release_cli.main(["resolve", "synced", "--do", "merge",
                             "--keep", "src/b.py=ours"]) == 1
    assert merged == []


def test_keep_rejects_unknown_files_and_choices(root, monkeypatch, capsys):
    Resolver(monkeypatch, (SYNCED,))
    monkeypatch.setattr(release_conflicts, "read", lambda *a, **k: CONFLICTS)
    assert release_cli.main(["resolve", "synced", "--do", "merge", "--keep", "zzz=ours"]) == 2
    assert "src/b.py" in capsys.readouterr().err
    assert release_cli.main(["resolve", "synced", "--do", "merge",
                             "--keep", "src/b.py=ticks"]) == 2
    assert release_cli.main(["resolve", "synced", "--do", "merge",
                             "--keep", "src/b.py=mine"]) == 2
    # --keep belongs to merge only
    Resolver(monkeypatch)
    assert release_cli.main(["resolve", "clean", "--do", "stash", "--keep", "a=ours"]) == 2


def say_setup(monkeypatch, status="proposal"):
    fake = Resolver(monkeypatch)
    log = []
    monkeypatch.setattr(release_plan, "default_ask_agent", lambda root: (lambda prompt: ""))
    monkeypatch.setattr(release_resolve, "propose", lambda *a, **k: release_resolve.Proposal(
        "a.py is not committed", ("Commit a.py",), ("git push (whyline won't do that)",)))
    monkeypatch.setattr(release_resolve, "record_fix", lambda *a, **k: log.append(a[3]))
    monkeypatch.setattr(fixmode, "fix_level", lambda root: fixmode.LEVEL_APPROVAL)
    monkeypatch.setattr(fixmode, "open_session", lambda *a, **k: fixmode.Session("p"))
    monkeypatch.setattr(release_cli, "_fix_chain", lambda root: ["claude"])
    snap = fixmode.Snapshot("s1", "h", "b", "c", [], "now")
    fixes = []

    def run_fix(root, session, **kw):
        fixes.append(session.turns[-1].text)
        return fixmode.FixResult(status, "claude", snap,
                                 changes=[fixmode.Change("a.py", "modified")],
                                 counts={"a.py": (3, 1)})

    monkeypatch.setattr(fixmode, "run_fix", run_fix)
    return fake, fixes, log, snap


def test_say_asks_before_the_fix_turn(root, monkeypatch, capsys):
    fake, fixes, log, snap = say_setup(monkeypatch)
    tty(monkeypatch, True)
    answers(monkeypatch, "n")
    assert release_cli.main(["resolve", "clean", "--say", "commit it"]) == 1
    out = capsys.readouterr().out
    assert "Cause: a.py is not committed" in out and "1. Commit a.py" in out
    assert "whyline won't do that" in out and fixes == []


def test_say_prints_changes_and_keeps_by_default(root, monkeypatch, capsys):
    fake, fixes, log, snap = say_setup(monkeypatch)
    tty(monkeypatch, True)
    undone = []
    monkeypatch.setattr(fixmode, "undo", lambda r, s, **k: undone.append(s) or [])
    answers(monkeypatch, "y", "")
    assert release_cli.main(["resolve", "clean", "--say", "commit it"]) == 0
    out = capsys.readouterr().out
    assert "modified a.py (+3 -1)" in out and undone == []
    assert len(fixes) == 1 and "commit it" in fixes[0] and log == ["proposal"]
    assert fake.checks == 2


def test_say_undoes_the_fix_when_not_kept(root, monkeypatch, capsys):
    fake, fixes, log, snap = say_setup(monkeypatch)
    tty(monkeypatch, True)
    undone = []
    monkeypatch.setattr(fixmode, "undo", lambda r, s, **k: undone.append(s) or ["a.py"])
    answers(monkeypatch, "y", "n")
    assert release_cli.main(["resolve", "clean", "--say", "commit it"]) == 0
    assert undone == [snap] and "Undone: 1 path" in capsys.readouterr().out


def test_say_violation_exits_one(root, monkeypatch, capsys):
    fake, fixes, log, snap = say_setup(monkeypatch, status="violation")
    assert release_cli.main(["resolve", "clean", "--say", "go", "--yes"]) == 1
    assert "broke a rule" in capsys.readouterr().out and log == ["violation"]


def test_say_respects_the_suggest_level(root, monkeypatch, capsys):
    fake, fixes, log, snap = say_setup(monkeypatch)
    monkeypatch.setattr(fixmode, "fix_level", lambda root: fixmode.LEVEL_SUGGEST)
    assert release_cli.main(["resolve", "clean", "--say", "go", "--yes"]) == 1
    assert fixes == [] and "Suggest" in capsys.readouterr().err


def entry(option, snap, result="kept", ok=True):
    return release_resolve.Entry("2026-11-26T10:00:00+00:00", "clean", option, "msg", 1, result,
                                 snap, "abc", ok)


def test_undo_takes_the_newest_option_that_can_be_undone(root, monkeypatch, capsys):
    newest_first = [entry("commit", "s3", "undone"), entry("commit", "s3"),
                    entry("propose", ""), entry("stash", "s2", ok=False), entry("pull", "s1")]
    monkeypatch.setattr(release_resolve, "history", lambda *a, **k: newest_first)
    undone = []
    monkeypatch.setattr(release_resolve, "undo",
                        lambda r, snap, **k: undone.append(snap) or "Undone: 2 files put back")
    assert release_cli.main(["resolve", "--undo"]) == 0
    assert undone == ["s1"] and "Undone: 2 files" in capsys.readouterr().out


def test_undo_exit_codes(root, monkeypatch, capsys):
    monkeypatch.setattr(release_resolve, "history", lambda *a, **k: [])
    assert release_cli.main(["resolve", "--undo"]) == 1
    assert "nothing to undo" in capsys.readouterr().err
    monkeypatch.setattr(release_resolve, "history", lambda *a, **k: [entry("commit", "s1")])
    monkeypatch.setattr(release_resolve, "undo",
                        lambda *a, **k: "Something was committed after this")
    assert release_cli.main(["resolve", "--undo"]) == 1


def test_history_prints_the_log(root, monkeypatch, capsys):
    monkeypatch.setattr(release_resolve, "history", lambda *a, **k: [entry("commit", "s1")])
    assert release_cli.main(["resolve", "--history"]) == 0
    assert "clean commit kept: msg" in capsys.readouterr().out
    monkeypatch.setattr(release_resolve, "history", lambda *a, **k: [])
    assert release_cli.main(["resolve", "--history"]) == 0
    assert "Nothing has been resolved" in capsys.readouterr().out
