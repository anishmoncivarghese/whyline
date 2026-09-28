import builtins
import importlib
import pytest
from whyline.console import editor


def test_build_session_raises_a_clear_error_without_prompt_toolkit(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(editor, "AVAILABLE", False)
    with pytest.raises(editor.EditorUnavailable, match=r"whyline\[console\]"):
        editor.build_session(tmp_path)


def test_module_imports_cleanly_even_if_prompt_toolkit_is_missing(monkeypatch):
    # Simulates a real environment without the [console] extra installed --
    # editor.py itself must still import without raising.
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "prompt_toolkit" or name.startswith("prompt_toolkit."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    reloaded = importlib.reload(editor)
    assert reloaded.AVAILABLE is False
    monkeypatch.undo()
    importlib.reload(editor)  # restore real state for later tests in this process


@pytest.mark.skipif(
    not editor.AVAILABLE, reason="prompt_toolkit not installed -- skip the real smoke test"
)
def test_build_session_returns_a_real_prompt_session_when_installed(tmp_path):
    session = editor.build_session(tmp_path)
    assert session is not None
    assert (tmp_path / ".whyline" / "console-history").parent.exists()
