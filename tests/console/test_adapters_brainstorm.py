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
