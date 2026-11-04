import pytest

from whyline.relaychat import history, settings


def test_settings_defaults_and_round_trip(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    base = tmp_path / "base"
    assert settings.load(repo, base) == settings.ChatSettings(None, 180, 40000)
    saved = settings.save(repo, base, agent="claude", timeout_seconds=60)
    assert saved == settings.load(repo, base)
    assert saved.agent == "claude" and saved.timeout_seconds == 60
    assert saved.snapshot_chars == 40000
    settings.save(repo, base, agent=None)
    assert settings.load(repo, base).agent is None
    assert settings.load(repo, base).timeout_seconds == 60


def test_settings_refuse_bad_input(tmp_path):
    base = tmp_path / "base"
    for bad in ({"colour": 1}, {"timeout_seconds": -1}, {"timeout_seconds": "9"},
                {"snapshot_chars": 0}, {"snapshot_chars": True}, {"agent": ""}, {"agent": 3}):
        with pytest.raises(ValueError):
            settings.save(tmp_path, base, **bad)
    assert not settings.settings_path(base).exists()


def test_settings_timeout_zero_means_no_limit(tmp_path):
    base = tmp_path / "base"
    assert settings.save(tmp_path, base, timeout_seconds=0).timeout_seconds == 0
    assert settings.load(tmp_path, base).timeout_seconds == 0


def test_settings_two_repos_do_not_mix(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    base = tmp_path / "base"
    settings.save(a, base, agent="grok")
    settings.save(b, base, agent='we"ird\\name')
    assert settings.load(a, base).agent == "grok"
    assert settings.load(b, base).agent == 'we"ird\\name'


def test_history_round_trip_and_last(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    base = tmp_path / "base"
    assert history.load(repo, None, base=base) == []
    for i in range(3):
        history.append(repo, None, "user", f"q{i}", agent="claude", base=base)
    assert history.path(repo, None, base).name == "adhoc.jsonl"
    rows = history.load(repo, "adhoc", base=base)
    assert [r["text"] for r in rows] == ["q0", "q1", "q2"]
    assert rows[0]["agent"] == "claude" and rows[0]["role"] == "user"
    assert [r["text"] for r in history.load(repo, None, last=2, base=base)] == ["q1", "q2"]


def test_history_two_repos_and_runs_do_not_mix(tmp_path):
    a, b = tmp_path / "x" / "app", tmp_path / "y" / "app"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    base = tmp_path / "base"
    history.append(a, "run1", "user", "from a", base=base)
    history.append(b, "run1", "user", "from b", base=base)
    history.append(a, "run2", "user", "other run", base=base)
    assert history.path(a, "run1", base) != history.path(b, "run1", base)
    assert [r["text"] for r in history.load(a, "run1", base=base)] == ["from a"]
    assert [r["text"] for r in history.load(b, "run1", base=base)] == ["from b"]


def test_history_refuses_unsafe_run_id(tmp_path):
    with pytest.raises(ValueError):
        history.path(tmp_path, "../x", tmp_path)


def test_clear_keeps_old_file(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    base = tmp_path / "base"
    assert history.clear(repo, "run1", base) is None
    history.append(repo, "run1", "user", "hello", base=base)
    kept = history.clear(repo, "run1", base)
    assert kept is not None and kept.exists()
    assert kept.name.startswith("run1.") and kept.name.endswith(".jsonl")
    assert kept.name != "run1.jsonl"
    assert history.load(repo, "run1", base=base) == []
    assert "hello" in kept.read_text(encoding="utf-8")
