import re
import zipfile
import xml.etree.ElementTree as ET

from whyline.agents import docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

WIDE = (
    "# Live result\n\n**Current search date:** 8 October 2026\n\n"
    "## Currently open vacancies\n\n"
    "| " + " | ".join(f"Col {i}" for i in range(17)) + " |\n"
    "|" + "---|" * 17 + "\n"
    "| 1 | ⭐⭐⭐⭐ | **Medical Officer** & A < B | " + " | ".join(f"v{i}" for i in range(3, 17))
    + " |\n| 2 | ⭐⭐⭐ | [Official PDF](https://example.gov.in/a.pdf) | "
    + " | ".join(f"w{i}" for i in range(3, 17)) + " |\n\n"
    "Top actions:\n\n1. Apply for X.\n2. Apply for Y.\n\nDocuments:\n\n- one\n- two\n"
)


def _parts(path):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        doc = z.read("word/document.xml").decode("utf-8")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    return names, doc, rels


def test_a_wide_markdown_table_becomes_a_real_word_table(tmp_path):
    out = docx.write(WIDE, tmp_path / "r.docx")
    names, doc, rels = _parts(out)
    assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml",
            "word/_rels/document.xml.rels"} <= names
    root = ET.fromstring(doc)  # well-formed
    tables = root.findall(f".//{W}tbl")
    assert len(tables) == 1
    rows = tables[0].findall(f"{W}tr")
    assert len(rows) == 3 and rows[0].find(f"{W}trPr/{W}tblHeader") is not None
    assert len(tables[0].findall(f"{W}tblGrid/{W}gridCol")) == 17
    assert all(len(row.findall(f"{W}tc")) == 17 for row in rows)
    for cell in tables[0].iter(f"{W}tc"):
        assert cell.find(f"{W}p") is not None  # Word needs a paragraph in every cell
    text = "".join(t.text or "" for t in root.iter(f"{W}t"))
    assert "Medical Officer & A < B" in text and "⭐⭐⭐⭐" in text
    assert 'w:orient="landscape"' in doc


def test_links_headings_and_lists(tmp_path):
    out = docx.write(WIDE, tmp_path / "r.docx")
    _, doc, rels = _parts(out)
    assert 'Target="https://example.gov.in/a.pdf"' in rels and 'TargetMode="External"' in rels
    rid = re.search(r'Id="(rId\d+)"[^>]*Target="https://example.gov.in/a.pdf"', rels).group(1)
    assert f'<w:hyperlink r:id="{rid}"' in doc
    root = ET.fromstring(doc)
    paragraphs = ["".join(t.text or "" for t in p.iter(f"{W}t")) for p in root.iter(f"{W}p")]
    assert "Live result" in paragraphs and "Currently open vacancies" in paragraphs
    assert "1. Apply for X." in paragraphs and "• one" in paragraphs


def test_a_report_without_wide_tables_stays_portrait(tmp_path):
    out = docx.write("# Hi\n\n| A | B |\n|---|---|\n| 1 | 2 |\n", tmp_path / "r.docx")
    _, doc, _ = _parts(out)
    assert 'w:orient="landscape"' not in doc and doc.count("<w:tbl>") == 1


def test_plain_text_and_empty_reports(tmp_path):
    out = docx.write("just text, no markdown", tmp_path / "a.docx")
    _, doc, _ = _parts(out)
    assert "just text, no markdown" in doc
    out = docx.write("", tmp_path / "b.docx")
    ET.fromstring(_parts(out)[1])


def test_a_space_between_two_bold_pieces_is_kept(tmp_path):
    out = docx.write("**Open vacancies:** **6 posts**", tmp_path / "r.docx")
    root = ET.fromstring(_parts(out)[1])
    assert "Open vacancies: 6 posts" in "".join(t.text or "" for t in root.iter(f"{W}t"))


def test_column_widths_follow_how_much_text_each_column_holds(tmp_path):
    long = "a long explanation of how to apply " * 4
    text = ("| # | How to apply | Days |\n|---|---|---|\n"
            f"| 1 | {long} | 3 |\n| 2 | {long} | 4 |\n")
    out = docx.write(text, tmp_path / "r.docx")
    root = ET.fromstring(_parts(out)[1])
    widths = [int(col.get(f"{W}w")) for col in root.iter(f"{W}gridCol")]
    assert widths[1] > 3 * widths[0] and widths[1] > 3 * widths[2]
    assert all(width >= 300 for width in widths)  # at least its longest word


def test_short_header_words_fit_their_column(tmp_path):
    # Found on the real 17-column report: "Rank", "Priority" and "Vacancies"
    # broke mid-word because column floors ignored the font size.
    headers = ["Rank", "Priority", "Vacancy / Post", "Organisation", "Category", "Location",
               "Permanent / Contract", "Eligibility for Her", "Ex-Servicemen Benefit",
               "Age Limit & Relaxation", "Salary / Pay Level", "Vacancies", "Last Date",
               "Days Remaining", "How to Apply", "Official Notification / Application Link",
               "Why It Is Important"]
    row = ["1", "⭐⭐⭐⭐"] + ["some longer explanatory text " * 3] * 15
    text = "| " + " | ".join(headers) + " |\n|" + "---|" * 17 + "\n| " + " | ".join(row) + " |\n"
    out = docx.write(text, tmp_path / "r.docx")
    root = ET.fromstring(_parts(out)[1])
    widths = [int(col.get(f"{W}w")) for col in root.iter(f"{W}gridCol")]
    font_pt = 7.5  # tables of 12+ columns use 7.5 pt
    for header, width in zip(headers, widths):
        longest = max(len(word) for word in header.split())
        assert width >= longest * font_pt * 0.6 * 20 * 1.1, header  # bold header, plus padding
    assert sum(widths) <= 23811 - 2 * 720 + 17  # fits the landscape A3 text width
