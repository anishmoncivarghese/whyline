from datetime import datetime

from whyline.agents import definitions as d, after, records, state

NOW = datetime(2026, 10, 5, 7, 5)


def _setup(repo):
    path = repo / ".whyline/agents/a.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('name="a"\ninstructions="x"\nrunner="claude"\nbackup=["codex"]')
    defn = d.load(path, kind="repo", repo_root=repo)
    conn = state.connect()
    state.accept(conn, defn)
    return conn, defn


def _rec(outcome, reason="", cli="claude", backup=None):
    return records.RunRecord("r", "id", "a", "schedule", NOW.isoformat(), cli=cli,
                             outcome=outcome, reason=reason, used_backup=backup)


def test_success_resets_the_streak_and_notifies_with_the_backup(repo, home, monkeypatch):
    sent = []
    conn, defn = _setup(repo)
    state.update(conn, defn.agent_id, consecutive_failures=2)
    monkeypatch.setattr(records, "read_final", lambda run_id: "All quiet today.\nMore.")
    after.finish(conn, defn, _rec("succeeded", cli="codex",
                                  backup={"cli": "codex", "because": "claude: usage_limit until 15:00"}),
                 now=NOW, send=lambda title, body: sent.append((title, body)))
    act = state.get(conn, defn.agent_id)
    assert act.consecutive_failures == 0 and act.last_run_at == NOW.isoformat()
    assert sent == [("whyline · a", "succeeded via codex (backup; claude: usage_limit until 15:00) — All quiet today.")]


def test_login_needed_everywhere_pauses_with_the_command(repo, home):
    sent = []
    conn, defn = _setup(repo)
    after.finish(conn, defn, _rec("login_needed", "claude: login_needed"), now=NOW,
                 send=lambda t, b: sent.append(b))
    act = state.get(conn, defn.agent_id)
    assert act.status == "paused" and "claude auth login" in act.paused_reason
    assert any("claude auth login" in b for b in sent)


def test_usage_limit_backs_off_until_the_earliest_reset(repo, home):
    conn, defn = _setup(repo)
    after.finish(conn, defn, _rec("all_unavailable", "claude: usage_limit until 15:00; codex: usage_limit until 13:00"),
                 now=NOW, send=lambda t, b: None)
    assert state.get(conn, defn.agent_id).backoff_until == "2026-10-05T13:00:00"


def test_three_failures_need_attention_and_notify_once_more(repo, home):
    sent = []
    conn, defn = _setup(repo)
    for _ in range(3):
        after.finish(conn, defn, _rec("failed", "boom"), now=NOW, send=lambda t, b: sent.append(b))
    assert state.get(conn, defn.agent_id).status == "needs_attention"
    assert sum("needs attention" in b for b in sent) == 1


def test_a_notification_failure_changes_nothing(repo, home):
    conn, defn = _setup(repo)

    def broken(title, body):
        raise OSError("no notifier")

    after.finish(conn, defn, _rec("succeeded"), now=NOW, send=broken)
    assert state.get(conn, defn.agent_id).consecutive_failures == 0
