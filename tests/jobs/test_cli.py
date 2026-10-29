"""CLI tests for `whyline jobs profile`."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from whyline import cli
from whyline.jobs import paths, profile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    return home_dir


def _invoke(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _build_docx(target: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml.encode("utf-8"))
    return target


def test_profile_show_before_any_setup_is_side_effect_free(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _invoke(["jobs", "profile", "show"], capsys)
    assert code == 0
    assert err == ""
    assert not paths.configured_home().exists()
    assert "~/.whyline/jobs" in out
    assert "cv.md" in out and "not imported" in out
    assert "preferences.toml" in out and "missing" in out
    assert "remote" in out and "any" in out
    assert "salary_min" in out and "0" in out


def test_profile_import_cv_file_and_stdin_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    md_file = tmp_path / "cv.md"
    md_file.write_text("# Ada Lovelace\nAnalytical Engine\n", encoding="utf-8")

    code, out, err = _invoke(["jobs", "profile", "import-cv", str(md_file)], capsys)
    assert code == 0, err
    assert "~/.whyline/jobs/cv.md" in out
    assert profile.cv_path().read_text(encoding="utf-8") == "# Ada Lovelace\nAnalytical Engine\n"

    docx_file = _build_docx(tmp_path / "cv.docx", ["Grace Hopper", "A-0 Compiler"])
    code, out, err = _invoke(["jobs", "profile", "import-cv", str(docx_file)], capsys)
    assert code == 0, err
    assert profile.cv_path().read_text(encoding="utf-8") == "Grace Hopper\nA-0 Compiler"

    # Import from stdin (`-`) via StringIO (no .buffer)
    monkeypatch.setattr(sys, "stdin", io.StringIO("\ufeffBarbara Liskov\r\nCLU & Thor\r\n"))
    code, out, err = _invoke(["jobs", "profile", "import-cv", "-"], capsys)
    assert code == 0, err
    assert profile.cv_path().read_text(encoding="utf-8") == "Barbara Liskov\nCLU & Thor\n"

    # Import from stdin (`-`) via TextIOWrapper with binary .buffer (UTF-8 multi-byte)
    raw_bytes = "Margaret Hamilton — Apollo Guidance\n".encode("utf-8")
    wrapper = io.TextIOWrapper(io.BytesIO(raw_bytes), encoding="ascii")
    monkeypatch.setattr(sys, "stdin", wrapper)
    code, out, err = _invoke(["jobs", "profile", "import-cv", "-"], capsys)
    assert code == 0, err
    assert profile.cv_path().read_text(encoding="utf-8") == "Margaret Hamilton — Apollo Guidance\n"

    code, show_out, err = _invoke(["jobs", "profile", "show"], capsys)
    assert code == 0, err
    assert "cv.md" in show_out and "present" in show_out

    code, json_out, err = _invoke(["jobs", "profile", "show", "--json"], capsys)
    assert code == 0, err
    parsed = json.loads(json_out)
    assert parsed["files"]["cv.md"]["exists"] is True
    assert parsed["files"]["cv.md"]["path"] == "~/.whyline/jobs/cv.md"


def test_profile_set_and_show_round_trip_keeps_unknown_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Seed an unknown key in preferences.toml to verify CLI updates preserve it.
    prefs_path = paths.home() / "preferences.toml"
    prefs_path.write_text("min_score = 18\n", encoding="utf-8")

    updates = [
        ("roles", "Backend Engineer, Staff Engineer"),
        ("seniority", "Staff"),
        ("locations", '["San Francisco, CA", "London"]'),
        ("remote", "hybrid"),
        ("salary_min", "145000"),
        ("currency", "GBP"),
        ("languages", "English, German"),
        ("deal_breakers", "crypto, unpaid"),
        ("notes", "Developer tools and distributed systems"),
    ]
    for key, val in updates:
        code, out, err = _invoke(["jobs", "profile", "set", key, val], capsys)
        assert code == 0, f"{key}: {err}"
        assert f"Saved {key}" in out

    loaded = profile.load_preferences()
    assert loaded["roles"] == ["Backend Engineer", "Staff Engineer"]
    assert loaded["seniority"] == "Staff"
    assert loaded["locations"] == ["San Francisco, CA", "London"]
    assert loaded["remote"] == "hybrid"
    assert loaded["salary_min"] == 145000
    assert loaded["currency"] == "GBP"
    assert loaded["languages"] == ["English", "German"]
    assert loaded["deal_breakers"] == ["crypto", "unpaid"]
    assert loaded["notes"] == "Developer tools and distributed systems"
    assert loaded["min_score"] == 18

    code, show_out, err = _invoke(["jobs", "profile", "show"], capsys)
    assert code == 0, err
    for expected in (
        "Backend Engineer, Staff Engineer",
        "Staff",
        "San Francisco, CA, London",
        "hybrid",
        "145000",
        "GBP",
        "English, German",
        "crypto, unpaid",
        "Developer tools and distributed systems",
        "min_score",
        "18",
    ):
        assert expected in show_out

    # Clearing a list key with an empty string sets []
    code, _, err = _invoke(["jobs", "profile", "set", "deal_breakers", ""], capsys)
    assert code == 0, err
    assert profile.load_preferences()["deal_breakers"] == []


@pytest.mark.parametrize(
    ("argv", "expected_err"),
    [
        (["jobs", "profile", "set", "unknown_key", "val"], "Unknown preference key"),
        (["jobs", "profile", "set", "remote", "anywhere"], "remote must be one of"),
        (["jobs", "profile", "set", "salary_min", "abc"], "whole number"),
        (["jobs", "profile", "set", "salary_min", "-5"], "zero or a positive whole number"),
        (["jobs", "profile", "set", "roles", "[1, 2]"], "roles must be a list of strings"),
        (["jobs", "profile", "set", "roles", "[unclosed"], "Invalid list syntax"),
    ],
)
def test_profile_set_rejects_invalid_keys_and_values(
    argv: list[str],
    expected_err: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile.save_preferences({"remote": "remote", "salary_min": 100000})
    code, out, err = _invoke(argv, capsys)
    assert code == 1
    assert out == ""
    assert expected_err in err
    assert "Traceback" not in err
    # Prior valid preferences remain untouched
    saved = profile.load_preferences()
    assert saved["remote"] == "remote"
    assert saved["salary_min"] == 100000


def test_profile_import_cv_rejects_bad_file_and_oversized_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile.import_cv_text("Keep me")

    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    code, _, err = _invoke(["jobs", "profile", "import-cv", str(pdf)], capsys)
    assert code == 1
    assert ".md, .txt, or .docx" in err

    oversized = io.TextIOWrapper(
        io.BytesIO(b"x" * (profile.MAX_CV_BYTES * 2 + 10)),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "stdin", oversized)
    code, _, err = _invoke(["jobs", "profile", "import-cv", "-"], capsys)
    assert code == 1
    assert "200 KB" in err
    assert profile.cv_path().read_text(encoding="utf-8") == "Keep me"
