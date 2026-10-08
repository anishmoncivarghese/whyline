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


def test_to_docx_calls_textutil(tmp_path):
    report = tmp_path / "final.md"
    report.write_text(WIDE, encoding="utf-8")
    out = tmp_path / "jobs-2026-10-09.docx"
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"PK")
        class R: returncode = 0
        return R()

    assert convert.to_docx(report, out, run=run, which=lambda name: "/usr/bin/textutil") == out
    assert calls[0][:3] == ["textutil", "-convert", "docx"] and calls[0][-2:] == ["-output", str(out)]
    assert not out.with_suffix(".html").exists()  # the temporary page is removed


def test_to_docx_without_textutil_or_on_failure(tmp_path):
    report = tmp_path / "final.md"
    report.write_text("hi", encoding="utf-8")
    out = tmp_path / "x.docx"
    assert convert.to_docx(report, out, which=lambda name: None) is None

    def failing(argv, **kwargs):
        class R: returncode = 1
        return R()

    assert convert.to_docx(report, out, run=failing, which=lambda name: "/usr/bin/textutil") is None


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
