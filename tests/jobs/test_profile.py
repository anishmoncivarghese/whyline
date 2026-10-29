from __future__ import annotations

import datetime
import os
import zipfile
from pathlib import Path

import pytest

from whyline.jobs import paths, profile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    return home_dir


def _build_minimal_docx(target: Path, document_xml: str) -> Path:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml.encode("utf-8"))
    return target


def test_import_cv_supports_md_txt_docx_and_text(tmp_path: Path, isolated_home: Path) -> None:
    md_src = tmp_path / "resume.md"
    md_src.write_text("# Ada Lovelace\n\nAnalytical Engine Architect\n", encoding="utf-8")
    out_md = profile.import_cv(md_src)
    assert out_md == isolated_home / ".whyline" / "jobs" / "cv.md"
    assert out_md.read_text(encoding="utf-8") == "# Ada Lovelace\n\nAnalytical Engine Architect\n"

    txt_src = tmp_path / "resume.TXT"
    txt_src.write_bytes(b"\xef\xbb\xbfGrace Hopper\r\nCompiler Pioneer\r\n")
    out_txt = profile.import_cv(txt_src)
    assert out_txt.read_text(encoding="utf-8") == "Grace Hopper\nCompiler Pioneer\n"

    docx_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{W_NS}">'
        "<w:body>"
        "<w:p><w:r><w:t>Barbara Liskov</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Distributed </w:t></w:r><w:r><w:t>Systems</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>MIT</w:t><w:tab/><w:t>Boston</w:t><w:br/><w:t>USA</w:t></w:r></w:p>"
        "<w:p><w:del><w:r><w:delText>Removed</w:delText></w:r></w:del>"
        "<w:ins><w:r><w:t>CLU &amp; Argus</w:t></w:r></w:ins></w:p>"
        "</w:body>"
        "</w:document>"
    )
    docx_src = _build_minimal_docx(tmp_path / "cv.docx", docx_xml)
    out_docx = profile.import_cv(docx_src)
    assert out_docx.read_text(encoding="utf-8").splitlines() == [
        "Barbara Liskov",
        "Distributed Systems",
        "MIT\tBoston USA",
        "CLU & Argus",
    ]

    out_direct = profile.import_cv_text("Margaret Hamilton\nFlight Software Lead")
    assert out_direct.read_text(encoding="utf-8") == "Margaret Hamilton\nFlight Software Lead"


def test_import_cv_rejects_bad_formats_and_corrupt_docx_keeping_existing_cv(
    tmp_path: Path,
) -> None:
    profile.import_cv_text("Existing CV")
    cv_file = paths.home() / "cv.md"

    pdf_src = tmp_path / "cv.pdf"
    pdf_src.write_bytes(b"%PDF-1.4")
    with pytest.raises(profile.ProfileError, match=r"\.md, \.txt, or \.docx"):
        profile.import_cv(pdf_src)

    with pytest.raises(profile.ProfileError, match="not found"):
        profile.import_cv(tmp_path / "missing.md")

    bad_zip = tmp_path / "broken.docx"
    bad_zip.write_bytes(b"not a zip file")
    with pytest.raises(profile.ProfileError, match="invalid Word document"):
        profile.import_cv(bad_zip)

    missing_doc = tmp_path / "empty_zip.docx"
    with zipfile.ZipFile(missing_doc, "w") as archive:
        archive.writestr("other.xml", "<x/>")
    with pytest.raises(profile.ProfileError, match=r"word/document\.xml is missing"):
        profile.import_cv(missing_doc)

    bad_xml = _build_minimal_docx(tmp_path / "bad_xml.docx", "<w:document><unclosed>")
    with pytest.raises(profile.ProfileError, match="not valid XML"):
        profile.import_cv(bad_xml)

    entity_xml = _build_minimal_docx(
        tmp_path / "entity.docx",
        '<!DOCTYPE doc [<!ENTITY x "boom">]><doc><p><t>&x;</t></p></doc>',
    )
    with pytest.raises(profile.ProfileError, match="entities are not allowed"):
        profile.import_cv(entity_xml)

    assert cv_file.read_text(encoding="utf-8") == "Existing CV"


def test_cv_size_limit_accepts_200kb_and_refuses_larger_with_plain_message(
    tmp_path: Path,
) -> None:
    exact_200kb = "a" * (200 * 1024)
    cv_file = profile.import_cv_text(exact_200kb)
    assert len(cv_file.read_bytes()) == 200 * 1024

    over_ascii = "b" * (200 * 1024 + 1)
    with pytest.raises(profile.ProfileError) as exc_info:
        profile.import_cv_text(over_ascii)
    message = str(exc_info.value)
    assert "200 KB" in message
    assert "Traceback" not in message
    assert cv_file.read_text(encoding="utf-8") == exact_200kb

    # Multi-byte UTF-8 characters count by encoded UTF-8 byte size, not codepoints.
    over_utf8 = "é" * (100 * 1024 + 1)
    with pytest.raises(profile.ProfileError, match="200 KB"):
        profile.import_cv_text(over_utf8)

    large_md = tmp_path / "huge.md"
    large_md.write_text(over_ascii, encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="200 KB"):
        profile.import_cv(large_md)

    # A multi-byte UTF-8 file larger than 2x the limit still reports the 200 KB limit,
    # never a mid-codepoint UTF-8 decode error.
    large_multibyte_txt = tmp_path / "huge_euro.txt"
    large_multibyte_txt.write_text("€" * 200_000, encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="200 KB"):
        profile.import_cv(large_multibyte_txt)

    large_docx = _build_minimal_docx(
        tmp_path / "huge.docx",
        f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>{over_ascii}</w:t></w:r></w:p></w:body></w:document>',
    )
    with pytest.raises(profile.ProfileError, match="200 KB"):
        profile.import_cv(large_docx)

    assert cv_file.read_text(encoding="utf-8") == exact_200kb


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode bits only")
def test_permissions_are_0700_for_home_and_0600_for_managed_files(
    isolated_home: Path, tmp_path: Path
) -> None:
    loose_dir = isolated_home / ".whyline" / "jobs"
    loose_dir.mkdir(parents=True)
    loose_dir.chmod(0o755)

    jobs_dir = paths.home()
    assert jobs_dir == loose_dir
    assert (jobs_dir.stat().st_mode & 0o777) == 0o700

    # Pre-seed loose files to ensure atomic replacement resets permissions to 0600.
    for filename in profile.MANAGED_FILES:
        seeded = jobs_dir / filename
        seeded.write_text("", encoding="utf-8")
        seeded.chmod(0o644)

    profile.import_cv_text("# Candidate CV\n")
    profile.save_preferences({"roles": ["Backend Engineer"], "remote": "remote"})
    profile.save_profile("Strengths: distributed systems.\n")
    profile.save_rubric("Role fit: 0-5.\n")

    for filename in profile.MANAGED_FILES:
        managed = jobs_dir / filename
        assert managed.is_file()
        assert (managed.stat().st_mode & 0o777) == 0o600

    # Symlinked target files inside ~/.whyline/jobs are refused without clobbering outside files.
    outside = tmp_path / "outside.md"
    outside.write_text("do not touch", encoding="utf-8")
    cv_target = jobs_dir / "cv.md"
    cv_target.unlink()
    cv_target.symlink_to(outside)
    with pytest.raises(profile.ProfileError, match="symlink"):
        profile.import_cv_text("new cv")
    assert outside.read_text(encoding="utf-8") == "do not touch"


@pytest.mark.parametrize(
    "bad_prefs",
    [
        {"roles": "Backend Engineer"},
        {"roles": [123]},
        {"seniority": ["senior"]},
        {"seniority": 5},
        {"locations": "London"},
        {"locations": [True]},
        {"remote": "anywhere"},
        {"remote": True},
        {"remote": ["remote"]},
        {"salary_min": "120000"},
        {"salary_min": True},
        {"salary_min": False},
        {"salary_min": 120000.5},
        {"salary_min": -1},
        {"currency": 840},
        {"currency": ["USD"]},
        {"languages": "English"},
        {"languages": [1]},
        {"deal_breakers": {"crypto": True}},
        {"notes": ["line"]},
        {"notes": 42},
        {"custom_null": None},
    ],
)
def test_invalid_preference_type_or_value_is_refused(bad_prefs: dict) -> None:
    profile.save_preferences({"roles": ["Platform Engineer"], "salary_min": 100000})

    with pytest.raises(profile.ProfileError):
        profile.save_preferences(bad_prefs)

    # Previous valid preferences stay intact after a refused save.
    saved = profile.load_preferences()
    assert saved["roles"] == ["Platform Engineer"]
    assert saved["salary_min"] == 100000


def test_load_preferences_refuses_invalid_types_on_disk() -> None:
    jobs_dir = paths.home()
    prefs_file = jobs_dir / "preferences.toml"

    prefs_file.write_text('salary_min = "lots"\n', encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="salary_min"):
        profile.load_preferences()

    prefs_file.write_text('remote = "moon"\n', encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="remote"):
        profile.load_preferences()

    prefs_file.write_text("not = [valid toml", encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="not valid TOML"):
        profile.load_preferences()


def test_preferences_defaults_all_remote_modes_and_saving_keeps_unknown_keys() -> None:
    # Reading defaults before any write does not create ~/.whyline/jobs on disk.
    defaults = profile.load_preferences()
    assert not paths.configured_home().exists()
    assert defaults == {
        "roles": [],
        "seniority": "",
        "locations": [],
        "remote": "any",
        "salary_min": 0,
        "currency": "",
        "languages": [],
        "deal_breakers": [],
        "notes": "",
    }
    defaults["roles"].append("mutated")
    assert profile.load_preferences()["roles"] == []

    for mode in ("any", "remote", "hybrid", "onsite"):
        saved_mode = profile.save_preferences({"remote": mode})
        assert saved_mode["remote"] == mode
        assert profile.load_preferences()["remote"] == mode

    # Hand-written unknown keys (scalars, dates, arrays, nested tables) in preferences.toml
    # survive subsequent save_preferences calls that only pass known keys, and unknown keys
    # passed directly to save_preferences are also kept.
    prefs_file = paths.home() / "preferences.toml"
    prefs_file.write_text(
        'roles = ["Backend Engineer"]\n'
        "min_score = 18\n"
        'tags = ["b2b", "devtools"]\n'
        "reviewed_on = 2026-10-29\n"
        "\n"
        "[extra]\n"
        'visa = "not required"\n'
        "\n"
        '[extra."sub.group"]\n'
        "weight = 2.5\n",
        encoding="utf-8",
    )

    loaded = profile.load_preferences()
    assert loaded["min_score"] == 18
    assert loaded["tags"] == ["b2b", "devtools"]
    assert loaded["reviewed_on"] == datetime.date(2026, 10, 29)
    assert loaded["extra"] == {"visa": "not required", "sub.group": {"weight": 2.5}}

    # Updating known keys (plus adding another unknown key) preserves existing unknown keys.
    profile.save_preferences(
        {
            "roles": ["Staff Engineer", "Principal Engineer"],
            "seniority": "staff",
            "locations": ["London", " Berlin "],
            "remote": "hybrid",
            "salary_min": 140000,
            "currency": "GBP",
            "languages": ["English"],
            "deal_breakers": ["unpaid"],
            "notes": "Focus on developer tools.",
            "include_contract": False,
        }
    )

    after = profile.load_preferences()
    assert after["roles"] == ["Staff Engineer", "Principal Engineer"]
    assert after["seniority"] == "staff"
    assert after["locations"] == ["London", " Berlin "]
    assert after["remote"] == "hybrid"
    assert after["salary_min"] == 140000
    assert after["currency"] == "GBP"
    assert after["languages"] == ["English"]
    assert after["deal_breakers"] == ["unpaid"]
    assert after["notes"] == "Focus on developer tools."
    assert after["min_score"] == 18
    assert after["tags"] == ["b2b", "devtools"]
    assert after["reviewed_on"] == datetime.date(2026, 10, 29)
    assert after["extra"] == {"visa": "not required", "sub.group": {"weight": 2.5}}
    assert after["include_contract"] is False


def test_status_reports_existing_files_and_last_changed_without_side_effects() -> None:
    initial = profile.status()
    assert not paths.configured_home().exists()
    assert list(initial.keys()) == [
        "cv.md",
        "preferences.toml",
        "profile.md",
        "rubric.md",
    ]
    assert all(not entry.exists and entry.modified_at is None for entry in initial.values())

    cv_file = profile.import_cv_text("# CV\n")
    profile.save_preferences({"remote": "remote"})
    prefs_file = profile.preferences_path()
    os.utime(cv_file, (1_700_000_100, 1_700_000_100))
    os.utime(prefs_file, (1_700_000_200, 1_700_000_200))

    mid = profile.status()
    assert mid["cv.md"].exists is True
    assert mid["cv.md"].modified_at == datetime.datetime.fromtimestamp(
        1_700_000_100, tz=datetime.timezone.utc
    )
    assert mid["cv.md"].size_bytes == len(b"# CV\n")
    assert mid["preferences.toml"].exists is True
    assert mid["preferences.toml"].modified_at == datetime.datetime.fromtimestamp(
        1_700_000_200, tz=datetime.timezone.utc
    )
    assert mid["profile.md"].exists is False
    assert mid["rubric.md"].exists is False

    prof_file = profile.save_profile("Profile summary\n")
    rub_file = profile.save_rubric("Rubric dimensions\n")
    os.utime(prof_file, (1_700_000_300, 1_700_000_300))
    os.utime(rub_file, (1_700_000_400, 1_700_000_400))

    final = profile.status()
    assert all(entry.exists for entry in final.values())
    assert final["profile.md"].modified_at == datetime.datetime.fromtimestamp(
        1_700_000_300, tz=datetime.timezone.utc
    )
    assert final["rubric.md"].modified_at == datetime.datetime.fromtimestamp(
        1_700_000_400, tz=datetime.timezone.utc
    )
