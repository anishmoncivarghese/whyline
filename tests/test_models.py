import json
import subprocess
from types import SimpleNamespace

import pytest

from whyline import models


@pytest.fixture(autouse=True)
def _clean():
    models.clear_antigravity_models_cache()
    yield
    models.clear_antigravity_models_cache()


def _ok(stdout):
    return lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _boom(*a, **k):
    raise AssertionError("no process may start")


def test_merge_order_and_no_duplicates():
    models.add("antigravity", "mine-1")
    models.add("antigravity", "gemini-x")
    models.add("claude", "opus")
    run = _ok("gemini-x\tGemini X\nother\tOther\n")
    got = models.options("antigravity", run=run)
    assert got == [("Gemini X", "gemini-x"), ("Other", "other"), ("mine-1", "mine-1")]
    claude = models.options("claude")
    ids = [i for _, i in claude]
    assert ids[:3] == ["opus", "sonnet", "haiku"]
    assert len(ids) == len(set(ids))


def test_cached_starts_no_process(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    assert models.cached("antigravity") == []
    assert ("codex-not", "codex-not") not in models.cached("codex")
    assert [i for _, i in models.cached("grok")] == ["grok-4.6", "grok-4"]


def test_failed_lister_keeps_old_cache():
    models.options("antigravity", run=_ok("a\tA\n"))
    before = models.cached("antigravity")
    assert before == [("A", "a")]

    def fail(*a, **k):
        return SimpleNamespace(returncode=1, stdout="", stderr="x")

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("agy", 10)

    assert models.options("antigravity", refresh=True, run=fail) == before
    assert models.options("antigravity", refresh=True, run=timeout) == before
    assert models.cached("antigravity") == before


def test_stale_mark_after_24_hours():
    models.options("antigravity", run=_ok("a\tA\n"), now=lambda: 1000.0)
    assert not models.stale("antigravity", now=lambda: 1000.0 + 3600)
    later = lambda: 1000.0 + 25 * 3600
    assert models.stale("antigravity", now=later)
    assert models.cached("antigravity") == [("A", "a")]


def test_add_and_remove_refuse_bad_ids():
    for bad in ("", "x" * 81, "has space", "semi;colon"):
        with pytest.raises(ValueError):
            models.add("claude", bad)
        with pytest.raises(ValueError):
            models.remove("claude", bad)
    models.add("claude", "my.model:1/x-[y]")
    assert ("my.model:1/x-[y]",) * 2 in models.cached("claude")
    models.add("claude", "my.model:1/x-[y]")
    models.remove("claude", "my.model:1/x-[y]")
    assert ("my.model:1/x-[y]",) * 2 not in models.cached("claude")


def test_file_shape(tmp_path):
    models.add("claude", "extra")
    data = json.loads((models._path()).read_text(encoding="utf-8"))
    assert data["claude"]["added"] == ["extra"]
