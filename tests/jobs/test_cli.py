"""CLI tests for `whyline jobs profile`."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from whyline import cli
from whyline.jobs import companies, paths, profile, review

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


def test_jobs_review_and_accept_cli_round_trip_and_failure_reporting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Accept before any drafts exist fails with exit code 1.
    code, out, err = _invoke(["jobs", "review", "accept"], capsys)
    assert code == 1
    assert out == ""
    assert "No review drafts" in err

    # Failed review run reports outcome and reason to stderr and writes nothing.
    monkeypatch.setattr(
        review,
        "run",
        lambda cli=None, progress=None: review.ReviewResult(
            ok=False,
            outcome="missing_block",
            reason="Missing fenced 'rubric' block in agent answer.",
        ),
    )
    code, out, err = _invoke(["jobs", "review"], capsys)
    assert code == 1
    assert "missing_block" in err and "rubric" in err
    assert not review.profile_draft_path().exists()
    assert not review.rubric_draft_path().exists()

    # Successful review writes drafts, shows tilde paths, and forwards --cli.
    seen_cli: list[str | None] = []

    def fake_ok_run(cli: str | None = None, progress=None) -> review.ReviewResult:
        seen_cli.append(cli)
        if progress is not None:
            progress("codex is working")
        p_draft, r_draft = review.save_drafts("# Draft Profile\n", "# Draft Rubric\n")
        return review.ReviewResult(
            ok=True,
            outcome="succeeded",
            cli=cli or "codex",
            profile="# Draft Profile\n",
            rubric="# Draft Rubric\n",
            profile_draft_path=p_draft,
            rubric_draft_path=r_draft,
        )

    monkeypatch.setattr(review, "run", fake_ok_run)
    code, out, err = _invoke(["jobs", "review", "--cli", "codex"], capsys)
    assert code == 0, err
    assert seen_cli == ["codex"]
    assert "codex is working" in out
    assert "~/.whyline/jobs/profile.draft.md" in out
    assert "~/.whyline/jobs/rubric.draft.md" in out

    # Accept moves drafts into profile.md and rubric.md.
    code, out, err = _invoke(["jobs", "review", "accept"], capsys)
    assert code == 0, err
    assert "~/.whyline/jobs/profile.md" in out
    assert "~/.whyline/jobs/rubric.md" in out
    assert profile.profile_path().read_text(encoding="utf-8") == "# Draft Profile\n"
    assert profile.rubric_path().read_text(encoding="utf-8") == "# Draft Rubric\n"
    assert not review.profile_draft_path().exists()
    assert not review.rubric_draft_path().exists()


def test_jobs_companies_cli_list_add_suggest_accept_remove_and_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # List before any writes is side-effect-free.
    code, out, err = _invoke(["jobs", "companies", "list"], capsys)
    assert code == 0, err
    assert err == ""
    assert not paths.configured_home().exists()
    assert "No companies" in out
    assert "~/.whyline/jobs/companies.toml" in out

    # Add companies with positional and --careers-url flags; reject non-https URL.
    code, out, err = _invoke(
        ["jobs", "companies", "add", "Stripe", "https://stripe.com/jobs"],
        capsys,
    )
    assert code == 0, err
    assert "Stripe" in out and "https://stripe.com/jobs" in out and "accepted" in out

    code, out, err = _invoke(
        ["jobs", "companies", "add", "Linear", "--careers-url", "https://linear.app/careers"],
        capsys,
    )
    assert code == 0, err
    assert "Linear" in out

    code, out, err = _invoke(
        ["jobs", "companies", "add", "BadHttp", "http://bad.example/jobs"],
        capsys,
    )
    assert code == 1
    assert out == ""
    assert "https://" in err
    assert "Traceback" not in err

    # Failed / malformed suggest reports error to stderr and exits 1.
    monkeypatch.setattr(
        companies,
        "suggest",
        lambda cli=None, progress=None: companies.SuggestResult(
            ok=False,
            outcome="malformed_answer",
            reason="Missing fenced 'companies' block in agent answer.",
        ),
    )
    code, out, err = _invoke(["jobs", "companies", "suggest"], capsys)
    assert code == 1
    assert "malformed_answer" in err

    # Successful suggest forwards --cli, prints progress and added suggestions.
    seen_cli: list[str | None] = []

    def fake_suggest(cli: str | None = None, progress=None) -> companies.SuggestResult:
        seen_cli.append(cli)
        if progress is not None:
            progress("claude is working")
        added_item = companies.Company(
            name="Tailscale",
            status="suggested",
            reason="Mesh networking & distributed systems",
            ats="unknown",
            slug="",
            careers_url="https://tailscale.com/careers",
            added_by="ai",
            checked_at="",
        )
        store = companies._load_store()
        store[companies._company_key(added_item.name)] = added_item
        companies._write_private_companies(store)
        return companies.SuggestResult(
            ok=True,
            outcome="succeeded",
            cli=cli or "claude",
            added=(added_item,),
        )

    monkeypatch.setattr(companies, "suggest", fake_suggest)
    code, out, err = _invoke(["jobs", "companies", "suggest", "--cli", "claude"], capsys)
    assert code == 0, err
    assert seen_cli == ["claude"]
    assert "claude is working" in out
    assert "Tailscale" in out and "Mesh networking" in out

    # List human-readable and --json and --status filter.
    code, list_out, err = _invoke(["jobs", "companies", "list"], capsys)
    assert code == 0, err
    assert "Stripe" in list_out and "accepted" in list_out
    assert "Tailscale" in list_out and "suggested" in list_out

    code, sug_only, err = _invoke(["jobs", "companies", "list", "--status", "suggested"], capsys)
    assert code == 0, err
    assert "Tailscale" in sug_only
    assert "Stripe" not in sug_only

    code, json_out, err = _invoke(["jobs", "companies", "list", "--json"], capsys)
    assert code == 0, err
    parsed = json.loads(json_out)
    assert [row["name"] for row in parsed] == ["Stripe", "Linear", "Tailscale"]

    # Accept and remove round-trip, plus unknown company errors.
    code, out, err = _invoke(["jobs", "companies", "accept", "tailscale"], capsys)
    assert code == 0, err
    assert "Accepted Tailscale" in out

    code, out, err = _invoke(["jobs", "companies", "remove", "Linear"], capsys)
    assert code == 0, err
    assert "Removed Linear" in out

    by_name = {c.name: c.status for c in companies.list()}
    assert by_name == {"Stripe": "accepted", "Linear": "removed", "Tailscale": "accepted"}

    code, out, err = _invoke(["jobs", "companies", "accept", "NoSuchCo"], capsys)
    assert code == 1
    assert "not found" in err.lower()
    code, out, err = _invoke(["jobs", "companies", "remove", "NoSuchCo"], capsys)
    assert code == 1
    assert "not found" in err.lower()
