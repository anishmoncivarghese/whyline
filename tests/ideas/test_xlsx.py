import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import pytest

from whyline.ideas import paths, store, xlsx

_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
# Excel's 1900 system: serial 61 is 1900-03-01, and 2026-10-19 is 46314.
_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)

_IDEA_HEADERS = [
    "id",
    "created",
    "source",
    "title",
    "status",
    "latest usefulness",
    "MVP complexity",
    "full complexity",
    "verdict",
    "confidence",
    "report path",
    "brainstorm path",
    "repo",
    "plan path",
]
_SCORE_HEADERS = [
    "idea id",
    "version",
    "created",
    "agent",
    "usefulness",
    "MVP complexity",
    "full complexity",
    "verdict",
    "confidence",
    "report path",
]
_SOURCE_HEADERS = ["idea id", "version", "title", "url"]
_HISTORY_HEADERS = ["id", "idea id", "at", "from", "to", "actor", "note"]
_SCORE_COLUMNS = [
    "latest usefulness",
    "MVP complexity",
    "full complexity",
    "verdict",
    "confidence",
    "report path",
]


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _serial(value: str) -> float:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment.astimezone(timezone.utc) - _EPOCH).total_seconds() / 86400


def _seed(conn):
    scored = store.add(conn, '=HYPERLINK("x")\nmore', source="+manual")
    store.set_paths(
        conn,
        scored.id,
        brainstorm_path="\tbrain.md",
        plan_path="@plan.md",
    )
    conn.execute("UPDATE ideas SET repo = ? WHERE id = ?", ("-repo", scored.id))
    store.add_analysis(
        conn,
        scored.id,
        agent="claude",
        report_path="1.md",
        usefulness=7,
        complexity_mvp=3,
        complexity_full=5,
        verdict="YES",
        confidence="high",
        sources_json=json.dumps(
            [
                {"title": "Example", "url": "https://example.com"},
                {"title": "Other", "url": "https://other.test"},
            ]
        ),
    )
    store.add_analysis(
        conn,
        scored.id,
        agent="codex",
        report_path="2.md",
        usefulness=4,
        complexity_mvp=2,
        complexity_full=9,
        verdict="NOT YET",
        confidence="low",
        sources_json=json.dumps(
            [{"title": "Later", "url": "\rhttps://later.test"}]
        ),
    )
    plain = store.add(conn, "Unscored idea", source="cli")
    store.set_paths(
        conn, plain.id, brainstorm_path="brain.md", plan_path="plan.md"
    )
    conn.execute(
        "UPDATE ideas SET repo = ? WHERE id = ?", ("/tmp/repo", plain.id)
    )
    store.transition(
        conn,
        plain.id,
        "dropped",
        expected_revision=plain.revision,
        actor="ada",
        note="\t=drop",
    )
    return scored, plain


def _workbook(path: Path):
    with zipfile.ZipFile(path) as package:
        workbook = ElementTree.fromstring(package.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(package.read("xl/_rels/workbook.xml.rels"))
        styles = package.read("xl/styles.xml")
        targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall(f"{{{_PKG_REL}}}Relationship")
        }
        sheets = []
        for sheet in workbook.findall(f"{{{_SS}}}sheets/{{{_SS}}}sheet"):
            target = targets[sheet.attrib[f"{{{_OFFICE_REL}}}id"]]
            part = target if target.startswith("xl/") else "xl/" + target
            xml = package.read(part)
            sheets.append((sheet.attrib["name"], xml))
    return sheets, styles


def _rows(xml: bytes):
    root = ElementTree.fromstring(xml)
    rows = []
    for row in root.findall(f"{{{_SS}}}sheetData/{{{_SS}}}row"):
        cells = {}
        for cell in row.findall(f"{{{_SS}}}c"):
            ref = cell.attrib["r"]
            letter = "".join(ch for ch in ref if ch.isalpha())
            kind = cell.attrib.get("t")
            if kind == "inlineStr":
                value = "".join(
                    node.text or "" for node in cell.iter(f"{{{_SS}}}t")
                )
            else:
                node = cell.find(f"{{{_SS}}}v")
                value = None if node is None or node.text is None else node.text
            cells[letter] = value
        rows.append(cells)
    return rows


def _table(xml: bytes):
    rows = _rows(xml)
    headers = rows[0]
    body = []
    for row in rows[1:]:
        body.append({name: row.get(letter) for letter, name in headers.items()})
    return [headers[letter] for letter in headers], body


def _cell(xml: bytes, ref: str):
    root = ElementTree.fromstring(xml)
    for cell in root.iter(f"{{{_SS}}}c"):
        if cell.attrib.get("r") == ref:
            return cell
    return None


def _letter(xml: bytes, header: str) -> str:
    headers = _rows(xml)[0]
    for letter, name in headers.items():
        if name == header:
            return letter
    raise AssertionError(header)


def test_excel_serial_epoch():
    assert _serial("1900-03-01T00:00:00Z") == 61
    assert _serial("2026-10-19T00:00:00Z") == 46314


def test_four_sheets_and_row_counts(conn):
    scored, plain = _seed(conn)
    path = xlsx.export(conn)
    assert path == paths.workbook()
    sheets, styles = _workbook(path)
    assert [name for name, _xml in sheets] == ["Ideas", "Scores", "Sources", "History"]

    counts = {
        "Ideas": conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0],
        "Scores": conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
        "History": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
    }
    sources = 0
    for (raw,) in conn.execute("SELECT sources_json FROM analyses"):
        sources += len(json.loads(raw))
    counts["Sources"] = sources

    by_name = dict(sheets)
    assert _table(by_name["Ideas"])[0] == _IDEA_HEADERS
    assert _table(by_name["Scores"])[0] == _SCORE_HEADERS
    assert _table(by_name["Sources"])[0] == _SOURCE_HEADERS
    assert _table(by_name["History"])[0] == _HISTORY_HEADERS
    for name, xml in sheets:
        assert len(_rows(xml)) == counts[name] + 1
        _assert_header(xml, styles)

    _headers, ideas = _table(by_name["Ideas"])
    idea = next(row for row in ideas if row["id"] == str(scored.id))
    assert idea["latest usefulness"] == "4"
    assert idea["MVP complexity"] == "2"
    assert idea["full complexity"] == "9"
    assert idea["verdict"] == "NOT YET"
    assert idea["confidence"] == "low"
    assert idea["report path"] == "2.md"
    created = store.get(conn, scored.id).created_at
    assert float(idea["created"]) == pytest.approx(_serial(created), abs=1e-7)
    assert "T" not in idea["created"]
    created_cell = _cell(by_name["Ideas"], f"{_letter(by_name['Ideas'], 'created')}2")
    assert created_cell.attrib["s"] == "2"
    assert "t" not in created_cell.attrib

    _headers, score_rows = _table(by_name["Scores"])
    assert [row["version"] for row in score_rows] == ["1", "2"]
    assert score_rows[0]["usefulness"] == "7"
    assert score_rows[1]["agent"] == "codex"

    _headers, source_rows = _table(by_name["Sources"])
    assert [(row["version"], row["title"], row["url"]) for row in source_rows] == [
        ("1", "Example", "https://example.com"),
        ("1", "Other", "https://other.test"),
        ("2", "Later", "'\rhttps://later.test"),
    ]

    _headers, history = _table(by_name["History"])
    assert history[0]["idea id"] == str(plain.id)
    assert history[0]["from"] == "captured"
    assert history[0]["to"] == "dropped"
    assert history[0]["actor"] == "ada"
    assert float(history[0]["at"]) == pytest.approx(
        _serial(
            conn.execute("SELECT at FROM events").fetchone()[0]
        ),
        abs=1e-7,
    )

    store.add(conn, "after the export", source="cli")


def _assert_header(xml: bytes, styles: bytes) -> None:
    root = ElementTree.fromstring(xml)
    pane = root.find(f"{{{_SS}}}sheetViews/{{{_SS}}}sheetView/{{{_SS}}}pane")
    assert pane.attrib["ySplit"] == "1"
    assert pane.attrib["state"] == "frozen"
    assert pane.attrib["topLeftCell"] == "A2"
    header = root.find(f"{{{_SS}}}sheetData/{{{_SS}}}row")
    for cell in header.findall(f"{{{_SS}}}c"):
        assert cell.attrib["s"] == "1"
        assert cell.attrib["t"] == "inlineStr"
    widths = [
        float(col.attrib["width"])
        for col in root.findall(f"{{{_SS}}}cols/{{{_SS}}}col")
    ]
    assert len(widths) == len(header.findall(f"{{{_SS}}}c"))
    assert all(width >= 8 for width in widths)
    style = ElementTree.fromstring(styles)
    fonts = style.findall(f"{{{_SS}}}fonts/{{{_SS}}}font")
    xfs = style.findall(f"{{{_SS}}}cellXfs/{{{_SS}}}xf")
    assert fonts[int(xfs[1].attrib["fontId"])].find(f"{{{_SS}}}b") is not None
    assert xfs[2].attrib["numFmtId"] == "164"
    formats = style.findall(f"{{{_SS}}}numFmts/{{{_SS}}}numFmt")
    assert formats[0].attrib["formatCode"] == "yyyy-mm-dd hh:mm:ss"


def test_hyperlink_title_is_stored_as_text(conn):
    scored, _plain = _seed(conn)
    path = xlsx.export(conn)
    sheets, _styles = _workbook(path)
    by_name = dict(sheets)
    ideas_xml = by_name["Ideas"]
    assert b"<f" not in ideas_xml
    _headers, ideas = _table(ideas_xml)
    idea = next(row for row in ideas if row["id"] == str(scored.id))
    assert idea["title"] == "'=HYPERLINK(\"x\")"
    assert idea["source"] == "'+manual"
    assert idea["repo"] == "'-repo"
    assert idea["brainstorm path"] == "'\tbrain.md"
    assert idea["plan path"] == "'@plan.md"
    _headers, history = _table(by_name["History"])
    assert history[0]["note"] == "'\t=drop"
    title_letter = _letter(ideas_xml, "title")
    cell = _cell(ideas_xml, f"{title_letter}2")
    assert cell.attrib["t"] == "inlineStr"
    assert cell.find(f"{{{_SS}}}f") is None


def test_replace_failure_keeps_the_old_workbook(monkeypatch, conn, ideas_home):
    target = ideas_home / "ideas.xlsx"
    target.write_bytes(b"previous-workbook")
    real = os.replace
    seen = []

    def boom(src, dst):
        seen.append((Path(src), Path(dst)))
        if Path(dst) == target:
            raise PermissionError("locked")
        real(src, dst)

    monkeypatch.setattr(xlsx.os, "replace", boom)
    found = xlsx.export(conn, target)
    assert target.read_bytes() == b"previous-workbook"
    assert found != target
    assert found.parent == target.parent
    assert len(found.name) == len("ideas-YYYYmmdd-HHMMSS.xlsx")
    assert found.name.startswith("ideas-") and found.suffix == ".xlsx"
    stamp = found.stem.removeprefix("ideas-")
    datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    assert seen[0][0].parent == target.parent
    assert seen[0][1] == target
    sheets, _styles = _workbook(found)
    assert [name for name, _xml in sheets] == ["Ideas", "Scores", "Sources", "History"]
    for _name, xml in sheets:
        assert len(_rows(xml)) == 1
    assert list(ideas_home.glob(".ideas-*")) == []


def test_a_workbook_that_does_not_parse_is_not_published(monkeypatch, conn, ideas_home):
    target = ideas_home / "ideas.xlsx"
    target.write_bytes(b"keep")

    def boom(*_args, **_kwargs):
        raise ElementTree.ParseError("bad sheet")

    monkeypatch.setattr(xlsx.ElementTree, "fromstring", boom)
    with pytest.raises(ElementTree.ParseError):
        xlsx.export(conn, target)
    assert target.read_bytes() == b"keep"
    assert list(ideas_home.glob(".ideas-*")) == []


def test_empty_ledger_writes_headers_only(conn, ideas_home):
    path = xlsx.export(conn)
    assert path == ideas_home / "ideas.xlsx"
    sheets, _styles = _workbook(path)
    assert [name for name, _xml in sheets] == ["Ideas", "Scores", "Sources", "History"]
    expected = {
        "Ideas": _IDEA_HEADERS,
        "Scores": _SCORE_HEADERS,
        "Sources": _SOURCE_HEADERS,
        "History": _HISTORY_HEADERS,
    }
    for name, xml in sheets:
        headers, body = _table(xml)
        assert headers == expected[name]
        assert body == []
        assert len(_rows(xml)) == 1
    assert list(ideas_home.glob("ideas-*.xlsx")) == []


def test_unscored_idea_has_empty_score_cells(conn):
    _scored, plain = _seed(conn)
    path = xlsx.export(conn)
    sheets, _styles = _workbook(path)
    ideas_xml = dict(sheets)["Ideas"]
    _headers, ideas = _table(ideas_xml)
    row = next(item for item in ideas if item["title"] == "Unscored idea")
    assert row["id"] == str(plain.id)
    assert row["source"] == "cli"
    assert row["status"] == "dropped"
    assert row["brainstorm path"] == "brain.md"
    assert row["repo"] == "/tmp/repo"
    assert row["plan path"] == "plan.md"
    assert row["created"] not in (None, "")
    for name in _SCORE_COLUMNS:
        assert row[name] is None
        cell = _cell(ideas_xml, f"{_letter(ideas_xml, name)}3")
        assert cell is not None
        assert list(cell) == []
        assert "t" not in cell.attrib
