import sys
from types import SimpleNamespace

import pytest

from whyline.release import targets
from whyline.release.config import CustomTarget as Entry
from whyline.release.config import ReleaseConfig, Targets
from whyline.release.github import StepError
from whyline.release.targets import custom


def cfg(*entries):
    return ReleaseConfig(targets=Targets(custom=tuple(entries)))


def make(tmp_path, *entries, **kw):
    target = custom.CustomTarget(**kw)
    return target, cfg(*entries), tmp_path


def steps(target, config, root):
    return target.steps(root, config, "1.2.3", run=None, fetch=None)


def test_registered_and_enabled_only_with_entries():
    assert targets.REGISTRY["custom"].key == "custom"
    assert targets.enabled(cfg()) == []
    assert [t.key for t in targets.enabled(cfg(Entry("a", "true")))] == ["custom"]


def test_ready_fails_on_a_missing_command(tmp_path):
    target, config, root = make(tmp_path, Entry("ship", "no-such-tool-xyz --go"))
    (item,) = target.ready_items(root, config, "1.2.3", run=None, fetch=None)
    assert not item.ok and "no-such-tool-xyz" in item.text


def test_ready_accepts_path_commands_and_commands_on_path(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "push.sh").write_text("#!/bin/sh\n")
    target, config, root = make(
        tmp_path, Entry("a", "./scripts/push.sh now"), Entry("b", "./scripts/missing.sh"),
        Entry("c", "tool --x"), which=lambda name: "/bin/tool" if name == "tool" else None)
    items = target.ready_items(root, config, "1.2.3", run=None, fetch=None)
    assert [i.ok for i in items] == [True, False, True]


def test_ready_rejects_an_unparseable_command(tmp_path):
    target, config, root = make(tmp_path, Entry("a", "echo 'unclosed"))
    (item,) = target.ready_items(root, config, "1.2.3", run=None, fetch=None)
    assert not item.ok


def test_step_is_irreversible_and_named_after_the_entry(tmp_path):
    target, config, root = make(tmp_path, Entry("ship", "true"))
    (step,) = steps(target, config, root)
    assert step.id == "custom:ship" and step.irreversible


def test_env_vars_reach_the_command_and_lines_stream(tmp_path):
    seen = []
    target, config, root = make(
        tmp_path, Entry("ship", 'echo "$WHYLINE_RELEASE_VERSION $WHYLINE_RELEASE_TAG" > out.txt; pwd'),
        on_line=seen.append)
    (step,) = steps(target, config, root)
    step.run(None)
    assert (tmp_path / "out.txt").read_text().strip() == "1.2.3 v1.2.3"
    assert seen == [str(tmp_path.resolve())] or seen == [str(tmp_path)]


def test_failure_shows_the_last_20_lines(tmp_path):
    command = f'{sys.executable} -c "[print(i) for i in range(30)]"; exit 3'
    target, config, root = make(tmp_path, Entry("ship", command))
    (step,) = steps(target, config, root)
    with pytest.raises(StepError) as error:
        step.run(None)
    text = str(error.value)
    assert "exited with 3" in text and "29" in text and "10" in text
    assert "\n9\n" not in text


def test_verify_is_the_done_check_and_absent_means_not_done(tmp_path):
    target, config, root = make(
        tmp_path, Entry("a", "true", "test -f marker"), Entry("b", "true"))
    a, b = steps(target, config, root)
    assert a.done_check() is False
    (tmp_path / "marker").write_text("x")
    assert a.done_check() is True
    assert b.done_check() is False


def test_verify_check_sees_the_version(tmp_path):
    target, config, root = make(
        tmp_path, Entry("a", "true", 'test "$WHYLINE_RELEASE_TAG" = v1.2.3'))
    assert target.verify(root, config, "1.2.3", run=None, fetch=None)[0] is True


def test_verify_reports_failures_and_missing_commands(tmp_path):
    target, config, root = make(
        tmp_path, Entry("a", "true", "false"), Entry("b", "true"))
    good, detail = target.verify(root, config, "1.2.3", run=None, fetch=None)
    assert not good and "a: verify command failed" in detail
    assert "b: no verify command" in detail


def test_entries_without_verify_count_as_verified(tmp_path):
    target, config, root = make(tmp_path, Entry("b", "true"))
    good, detail = target.verify(root, config, "1.2.3", run=None, fetch=None)
    assert good and "no verify command" in detail


def test_setup_status_lists_entries(tmp_path):
    target, config, root = make(tmp_path, Entry("a", "do it", "check it"))
    assert target.setup_status(root, config, run=None) == ["a: do it (verify: check it)"]
