# tests/agents/test_convert.py
from pathlib import Path

from whyline.agents import convert

WIDE = "# Scan\n\nCurrent search date: 9 Oct\nOpen: 6\n\n| " + " | ".join(
    f"C{i}" for i in range(17)) + " |\n|" + "---|" * 17 + "\n| " + " | ".join(
    str(i) for i in range(17)) + " |\n"


def test_to_html_keeps_a_wide_table():
    html = convert.to_html(WIDE)
    assert "<table>" in html and html.count("<th>") == 17
    assert "border-collapse" in html and "<meta charset='utf-8'>" in html


def test_to_docx_keeps_the_table(tmp_path):
    # Found in the live check: textutil's .docx had no tables at all.
    import zipfile

    report = tmp_path / "final.md"
    report.write_text(WIDE, encoding="utf-8")
    out = tmp_path / "jobs-2026-10-09.docx"
    assert convert.to_docx(report, out) == out
    document = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    assert document.count("<w:tbl>") == 1 and document.count("<w:gridCol") == 17


def test_to_docx_returns_none_when_the_report_is_missing(tmp_path):
    out = tmp_path / "x.docx"
    assert convert.to_docx(tmp_path / "missing.md", out) is None
    assert not out.exists()


def test_summary_stops_at_the_first_table():
    text = convert.summary(WIDE)
    assert "Open: 6" in text and "C0" not in text
    assert text.endswith("Full report attached.")


def test_summary_of_a_report_that_starts_with_a_table():
    table_only = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    assert "| A | B |" in convert.summary(table_only)


def test_summary_is_trimmed_at_a_line_end():
    long = "\n".join("line %03d %s" % (n, "x" * 40) for n in range(100))
    text = convert.summary(long, limit=1000)
    body = text.rsplit("\n\nFull report attached.", 1)[0]
    assert len(body) <= 1000 and body.endswith("x" * 40)
