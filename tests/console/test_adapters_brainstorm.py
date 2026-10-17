from pathlib import Path

from whyline.console import adapters


def _fake_relay(monkeypatch, unavailable=()):
    from whyline_relay import brainstorm, config

    calls = []
    monkeypatch.setattr(config, "load", lambda root: "settings")
    monkeypatch.setattr(
        brainstorm, "check_availability",
        lambda settings, models: [m for m in models if m[0] in unavailable],
    )

    def pass_zero(root, models, topic, *, settings, print_fn=None, **kw):
        calls.append(("zero", [k for k, _ in models]))
        for key, _ in models:  # each model's research note, as a real turn writes
            target = brainstorm.temp_path(root, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("research\n")
        return {}

    def review(root, models, topic, number, *, settings, print_fn=None, actual_agents=None, **kw):
        calls.append(("review", number))
        return {}

    def final(root, agent, models, topic, *, settings, **kw):
        calls.append(("final", agent))
        return {"agent": agent, "response": "the synthesis"}

    monkeypatch.setattr(brainstorm, "run_pass_zero", pass_zero)
    monkeypatch.setattr(brainstorm, "merge_pass_zero", lambda *a, **k: calls.append(("merge",)))
    monkeypatch.setattr(brainstorm, "run_review_pass", review)
    monkeypatch.setattr(brainstorm, "run_final_synthesis", final)
    return calls


def test_run_brainstorm_runs_every_stage_in_order(tmp_path, monkeypatch):
    calls = _fake_relay(monkeypatch)
    progress = []
    event = adapters.run_brainstorm(
        tmp_path, topic="Retry policy", agents=["claude", "antigravity"], passes=2,
        final_agent="antigravity", progress=progress.append,
    )
    # whyline's own agent names go to relay -- "antigravity", never "agy"
    assert calls == [
        ("zero", ["claude", "antigravity"]), ("merge",),
        ("review", 1), ("review", 2), ("final", "antigravity"),
    ]
    assert event.kind == "output"
    assert "the synthesis" in event.text
    # the path is shown in the platform's own form (backslashes on Windows)
    assert f"Saved to {Path('docs/brainstorm/retry-policy.md')}" in event.text
    assert any("Review pass 2 of 2" in line for line in progress)


def test_run_brainstorm_skips_models_relay_cannot_use(tmp_path, monkeypatch):
    calls = _fake_relay(monkeypatch, unavailable=("claude",))
    progress = []
    adapters.run_brainstorm(
        tmp_path, topic="t", agents=["claude", "codex"], passes=0,
        final_agent="claude", progress=progress.append,
    )
    assert calls[0] == ("zero", ["codex"])
    assert calls[-1] == ("final", "codex")  # final fell back to a usable model
    assert any("Skipping" in line and "Claude" in line for line in progress)


def test_run_brainstorm_with_no_usable_models_is_an_error(tmp_path, monkeypatch):
    calls = _fake_relay(monkeypatch, unavailable=("grok",))
    event = adapters.run_brainstorm(
        tmp_path, topic="t", agents=["grok"], passes=1, final_agent="grok"
    )
    assert event.kind == "error"
    assert calls == []


def test_run_brainstorm_does_not_print_relays_progress_twice(tmp_path, monkeypatch):
    """relay prints each model's progress line itself (through print_fn);
    also passing progress_fn and formatting its events printed every line
    twice."""
    from whyline_relay import brainstorm

    _fake_relay(monkeypatch)
    seen = {}

    def pass_zero(root, models, topic, *, settings, print_fn=None, progress_fn=None, **kw):
        seen["progress_fn"] = progress_fn
        for key, _ in models:
            target = brainstorm.temp_path(root, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("research\n")
        return {}

    monkeypatch.setattr(brainstorm, "run_pass_zero", pass_zero)
    adapters.run_brainstorm(tmp_path, topic="t", agents=["claude"], passes=0, final_agent="claude")
    assert seen["progress_fn"] is None


def test_run_brainstorm_stops_when_no_model_finished_its_research(tmp_path, monkeypatch):
    from whyline_relay import brainstorm

    calls = _fake_relay(monkeypatch)

    def pass_zero(root, models, topic, *, settings, print_fn=None, **kw):
        calls.append(("zero", [k for k, _ in models]))
        return {}  # every model timed out: nothing written

    monkeypatch.setattr(brainstorm, "run_pass_zero", pass_zero)
    event = adapters.run_brainstorm(
        tmp_path, topic="t", agents=["codex"], passes=1, final_agent="codex"
    )
    assert event.kind == "error"
    assert "No model finished its research" in event.text
    assert calls == [("zero", ["codex"])]  # no merge, review or synthesis after that


def test_skipped_models_say_how_to_set_them_up(tmp_path, monkeypatch):
    _fake_relay(monkeypatch, unavailable=("grok",))
    progress = []
    adapters.run_brainstorm(
        tmp_path, topic="t", agents=["claude", "grok"], passes=0,
        final_agent="claude", progress=progress.append,
    )
    line = next(line for line in progress if line.startswith("Skipping"))
    assert "Grok" in line and "whyline relay doctor" in line


def test_collect_brainstorm_none_sets_timeout_unlimited_without_reading_chat_select():
    from types import SimpleNamespace

    from whyline.console.repl import BRAINSTORM_AGENTS
    from whyline.console.tui import collect_brainstorm

    values = {
        "#bs-topic": "retry policy",
        "#bs-passes": "1",
        "#bs-final": "claude",
        "#bs-timeout": "none",
    }
    for agent in BRAINSTORM_AGENTS:
        values[f"#bs-{agent}"] = agent == "claude"

    def query_one(selector, cls=None):
        assert selector != "#cb-timeout"
        if selector == "#bs-attachments":
            return SimpleNamespace(pending=SimpleNamespace(paths=lambda: []))
        return SimpleNamespace(value=values[selector])

    choice = collect_brainstorm(query_one)
    assert choice["timeout_unlimited"] is True
    assert "timeout_minutes" not in choice

    values["#bs-timeout"] = 30
    finite = collect_brainstorm(query_one)
    assert finite["timeout_minutes"] == 30
    assert finite["timeout_unlimited"] is False


def test_run_brainstorm_unlimited_passes_no_limit(tmp_path, monkeypatch):
    from whyline_relay import brainstorm, chat

    calls = _fake_relay(monkeypatch)
    seen = []

    def pass_zero(root, models, topic, *, settings, print_fn=None, **kw):
        seen.append(("zero", kw.get("timeout_seconds")))
        for key, _ in models:
            target = brainstorm.temp_path(root, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("research\n")
        return {}

    def review(root, models, topic, number, *, settings, print_fn=None, actual_agents=None, **kw):
        seen.append(("review", kw.get("timeout_seconds")))
        return {}

    def final(root, agent, models, topic, *, settings, **kw):
        seen.append(("final", kw.get("timeout_seconds")))
        return {"agent": agent, "response": "the synthesis"}

    monkeypatch.setattr(brainstorm, "run_pass_zero", pass_zero)
    monkeypatch.setattr(brainstorm, "run_review_pass", review)
    monkeypatch.setattr(brainstorm, "run_final_synthesis", final)
    adapters.run_brainstorm(
        tmp_path, topic="t", agents=["claude"], passes=1, final_agent="claude",
        timeout_unlimited=True,
    )
    assert [seconds for _name, seconds in seen] == [chat.NO_LIMIT, chat.NO_LIMIT, chat.NO_LIMIT]
    assert calls[0][0] == "merge"


def test_run_brainstorm_stop_between_phases_does_not_start_the_next_model(tmp_path, monkeypatch):
    import threading

    from whyline_relay import brainstorm

    calls = _fake_relay(monkeypatch)
    cancel = threading.Event()

    def pass_zero(root, models, topic, *, settings, print_fn=None, **kw):
        calls.append(("zero", [k for k, _ in models], kw.get("cancel_event")))
        for key, _ in models:
            target = brainstorm.temp_path(root, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("research\n")
        cancel.set()
        return {}

    monkeypatch.setattr(brainstorm, "run_pass_zero", pass_zero)
    event = adapters.run_brainstorm(
        tmp_path, topic="t", agents=["claude"], passes=1, final_agent="claude",
        cancel_event=cancel,
    )
    assert event.kind == "error"
    assert event.text == "Stopped. Review did not start."
    assert calls == [("zero", ["claude"], cancel)]


def test_run_brainstorm_stop_after_review_does_not_start_synthesis(tmp_path, monkeypatch):
    import threading

    from whyline_relay import brainstorm

    calls = _fake_relay(monkeypatch)
    cancel = threading.Event()

    def review(root, models, topic, number, *, settings, print_fn=None, actual_agents=None, **kw):
        calls.append(("review", number))
        cancel.set()
        return {}

    monkeypatch.setattr(brainstorm, "run_review_pass", review)
    event = adapters.run_brainstorm(
        tmp_path, topic="t", agents=["claude"], passes=1, final_agent="claude",
        cancel_event=cancel,
    )
    assert event.kind == "error"
    assert event.text == "Stopped. Final synthesis did not start."
    assert ("final", "claude") not in calls
    assert ("review", 1) in calls
