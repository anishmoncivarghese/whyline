import dataclasses
import pytest

from whyline.security import settings as st
from whyline.security.findings import Finding, make_fingerprint, mask
from whyline.security.settings import SecuritySettings, SettingsError, decide


def finding(kind="secret", severity="unknown", fp="abc", **kw):
    return Finding(kind=kind, rule="r", title="t", severity=severity, fingerprint=fp, **kw)


def test_mask_short_and_long():
    assert mask("") == "****"
    assert mask("12345678") == "****"
    assert mask("sk-abcdefghijkl") == "sk****kl"
    assert "abcdefgh" not in mask("sk-abcdefghijkl")


def test_fingerprint_is_stable_and_ignores_line():
    a = make_fingerprint("secret", "aws", "a.py", "AKIA123")
    assert a == make_fingerprint("secret", "aws", "a.py", "AKIA123")
    assert a != make_fingerprint("secret", "aws", "b.py", "AKIA123")
    assert a != make_fingerprint("secret", "aws", "a.py", "AKIA124")
    assert "AKIA123" not in a


def test_finding_rejects_unknown_values():
    with pytest.raises(ValueError):
        Finding(kind="nope", rule="r", title="t")
    with pytest.raises(ValueError):
        Finding(kind="secret", rule="r", title="t", severity="bad")
    with pytest.raises(ValueError):
        Finding(kind="secret", rule="r", title="t", source="bad")


def test_parse_defaults_and_errors():
    assert st.parse({}) == SecuritySettings()
    assert st.parse({"secrets": "off", "pre_commit": True}).pre_commit is True
    for bad in ({"secrets": "x"}, {"audit": "block"}, {"pre_commit": "yes"}, {"history_scanned": 5}):
        with pytest.raises(SettingsError):
            st.parse(bad)
    with pytest.raises(SettingsError):
        st.parse([])


def test_allow_needs_a_reason(tmp_path):
    f = finding()
    for reason in ("", "   "):
        with pytest.raises(SettingsError):
            st.allow(tmp_path, f, reason)
    assert not st.is_allowed(tmp_path, f)


def test_allow_round_trip_and_replace(tmp_path):
    f = finding(path="a.py")
    st.allow(tmp_path, f, 'test "fixture"')
    st.allow(tmp_path, f, "second reason")
    assert st.is_allowed(tmp_path, f)
    assert not st.is_allowed(tmp_path, finding(fp="other"))
    entries = st._read_allow(tmp_path)
    assert len(entries) == 1
    assert entries[0]["reason"] == "second reason"
    assert entries[0]["path"] == "a.py"
    assert entries[0]["added"]


def test_ignore_once_lasts_until_cleared(tmp_path):
    state = tmp_path / ".git" / "whyline-release"
    f = finding()
    assert not st.is_ignored_once(state, f)
    st.ignore_once(state, f)
    assert st.is_ignored_once(state, f)
    assert not st.is_allowed(tmp_path, f)
    st.clear_ignored(state)
    assert not st.is_ignored_once(state, f)


def test_decide_block_high_lets_medium_through_as_warning():
    s = SecuritySettings()
    high = finding("dependency", "high", fp="1")
    crit = finding("dependency", "critical", fp="2")
    med = finding("dependency", "medium", fp="3")
    d = decide([high, crit, med], s)
    assert d.blocking == (high, crit)
    assert d.warnings == (med,)


def test_decide_per_setting():
    dep = finding("dependency", "low")
    sec = finding("secret", fp="s")
    con = finding("contents", fp="c")
    aud = finding("audit", fp="a")
    every = [dep, sec, con, aud]
    assert decide(every, SecuritySettings(dependencies="block")).blocking == (dep, sec, con)
    assert decide(every, SecuritySettings(dependencies="warn", secrets="warn")).warnings == (dep, sec)
    off = SecuritySettings(dependencies="off", secrets="off", contents="off")
    assert decide(every, off) == st.Decision()
    assert decide([aud], SecuritySettings(audit="warn")).warnings == (aud,)
    assert decide([aud], SecuritySettings(audit="block-confirmed")).blocking == (aud,)


def test_decide_exempt_findings_are_allowed():
    sec = finding()
    d = decide([sec], SecuritySettings(), is_exempt=lambda f: True)
    assert d.allowed == (sec,)
    assert not d.blocking and not d.warnings


def test_skip_paths_default_and_round_trip(tmp_path):
    from whyline.release import config as release_config

    assert SecuritySettings().skip_paths == ("tests/**/fixtures/**",)
    assert st.parse({"skip_paths": ["a/**", " b "]}).skip_paths == ("a/**", "b")
    with pytest.raises(SettingsError):
        st.parse({"skip_paths": "tests"})
    cfg = release_config.ReleaseConfig(security=SecuritySettings(skip_paths=("x/**", "y")))
    release_config.save(tmp_path, cfg)
    assert release_config.load(tmp_path).security.skip_paths == ("x/**", "y")


def test_allow_marks_the_file_pending(tmp_path):
    from pathlib import Path

    from whyline.release import config as release_config

    st.allow(tmp_path, finding(path="a.py"), "why")
    assert Path(".whyline/security-allow.toml") in release_config.pending(tmp_path)


def test_old_versioned_entry_matches_only_that_path_and_value(tmp_path):
    shown = "pkg-0.3.69.tar.gz:pkg-0.3.69/tests/x.py"
    st.allow(tmp_path, finding(fp="old", path=shown), "why")
    same = dataclasses.replace(finding(fp="new", path=shown), legacy_fingerprint="old")
    assert st.is_allowed(tmp_path, same)
    # A changed secret at the identical version and path stays blocking.
    changed = dataclasses.replace(finding(fp="new2", path=shown), legacy_fingerprint="other")
    assert not st.is_allowed(tmp_path, changed)
    assert not st.is_allowed(tmp_path, finding(fp="new3", path=shown))
    later = dataclasses.replace(finding(fp="new", path=shown.replace("69", "70")), legacy_fingerprint="old")
    assert not st.is_allowed(tmp_path, later)
