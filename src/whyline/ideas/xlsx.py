"""The idea ledger as an Excel workbook.

The SQLite ledger is the record. This rebuilds the workbook from it with
SpreadsheetML, using the standard library the way ``whyline.agents.docx``
writes Word files. No dependency is added.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

from whyline.ideas import paths

# Excel's 1900 date system: serial 61 is 1900-03-01. The epoch is
# 1899-12-30 so that dates after the fake 1900-02-29 land on the serial
# Excel displays. Ledger timestamps are UTC; the cell shows that clock.
_EXCEL_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)
_DATE_FORMAT = "yyyy-mm-dd hh:mm:ss"

# A leading apostrophe is stored in the cell. Excel then shows the
# characters and does not treat them as a formula. quotePrefix would hide
# the mark and is not what the export promises.
_FORMULA = ("=", "+", "-", "@", "\t", "\r")
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

# (header, kind, width). Width is in Excel character units. kind is
# "number", "date", or "text". Ideas score columns are the latest
# analysis; spec_path and original_text are not in the plan's column list.
_IDEAS = (
    ("id", "number", 8),
    ("created", "date", 22),
    ("source", "text", 16),
    ("title", "text", 42),
    ("status", "text", 24),
    ("latest usefulness", "number", 20),
    ("MVP complexity", "number", 18),
    ("full complexity", "number", 18),
    ("verdict", "text", 14),
    ("confidence", "text", 14),
    ("report path", "text", 42),
    ("brainstorm path", "text", 42),
    ("repo", "text", 28),
    ("plan path", "text", 42),
)
_SCORES = (
    ("idea id", "number", 10),
    ("version", "number", 10),
    ("created", "date", 22),
    ("agent", "text", 16),
    ("usefulness", "number", 14),
    ("MVP complexity", "number", 18),
    ("full complexity", "number", 18),
    ("verdict", "text", 14),
    ("confidence", "text", 14),
    ("report path", "text", 42),
)
_SOURCES = (
    ("idea id", "number", 10),
    ("version", "number", 10),
    ("title", "text", 42),
    ("url", "text", 48),
)
_HISTORY = (
    ("id", "number", 8),
    ("idea id", "number", 10),
    ("at", "date", 22),
    ("from", "text", 24),
    ("to", "text", 24),
    ("actor", "text", 16),
    ("note", "text", 42),
)


def export(conn: sqlite3.Connection, target=None) -> Path:
    """Rebuild the workbook from ``conn`` and return the path written.

    ``target`` defaults to ``paths.workbook()``. The file is written under
    a temporary name in that folder, opened again, and checked against the
    ledger before it replaces ``target``. When that replace fails because
    the workbook is open, ``ideas-YYYYmmdd-HHMMSS.xlsx`` is written beside
    it and that path is returned. The previous file is left where it was.
    """
    destination = paths.workbook() if target is None else Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tables = _read(conn)
    temporary = _temporary(destination.parent)
    try:
        _write(temporary, tables)
        _verify(temporary, {name: 1 + len(rows) for name, _columns, rows in tables})
        os.chmod(temporary, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    try:
        os.replace(temporary, destination)
    except OSError:
        fallback = _fallback(destination.parent)
        try:
            os.replace(temporary, fallback)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        return fallback
    return destination


def _temporary(folder: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=".ideas-", suffix=".xlsx", dir=folder)
    os.close(fd)
    return Path(name)


def _fallback(folder: Path) -> Path:
    # Local clock: this name is for the person who has the workbook open.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return folder / f"ideas-{stamp}.xlsx"


def _begin_read(conn: sqlite3.Connection) -> bool:
    """One snapshot for all four sheets. False when the caller already began."""
    try:
        conn.execute("BEGIN")
    except sqlite3.OperationalError as exc:
        if "transaction" in str(exc).lower():
            return False
        raise
    return True


def _read(conn: sqlite3.Connection):
    started = _begin_read(conn)
    try:
        ideas = _all(conn, "SELECT * FROM ideas ORDER BY id")
        analyses = _all(
            conn, "SELECT * FROM analyses ORDER BY idea_id, version, id"
        )
        events = _all(conn, "SELECT * FROM events ORDER BY id")
    finally:
        if started:
            conn.execute("ROLLBACK")
    latest: dict[int, dict] = {}
    for row in analyses:
        latest[row["idea_id"]] = row
    sources: list[tuple] = []
    for row in analyses:
        sources.extend(_sources(row))
    return (
        ("Ideas", _IDEAS, [_idea_row(row, latest.get(row["id"])) for row in ideas]),
        ("Scores", _SCORES, [_score_row(row) for row in analyses]),
        ("Sources", _SOURCES, [_source_row(item) for item in sources]),
        ("History", _HISTORY, [_event_row(row) for row in events]),
    )


def _all(conn: sqlite3.Connection, sql: str) -> list[dict]:
    return [dict(row) for row in conn.execute(sql)]


def _sources(row: dict) -> list[tuple]:
    raw = row["sources_json"] if row["sources_json"] else "[]"
    where = f"idea {row['idea_id']} version {row['version']}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{where} has invalid sources_json") from exc
    if not isinstance(payload, list):
        raise ValueError(f"{where} sources_json is not a list")
    found = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"{where} has a source that is not an object")
        found.append(
            (
                row["idea_id"],
                row["version"],
                "" if item.get("title") is None else str(item.get("title")),
                "" if item.get("url") is None else str(item.get("url")),
            )
        )
    return found


def _score(latest: dict | None, field: str):
    if latest is None:
        return None
    return latest[field]


def _idea_row(idea: dict, latest: dict | None) -> list:
    return [
        idea["id"],
        idea["created_at"],
        idea["source"],
        idea["title"],
        idea["status"],
        _score(latest, "usefulness"),
        _score(latest, "complexity_mvp"),
        _score(latest, "complexity_full"),
        _score(latest, "verdict"),
        _score(latest, "confidence"),
        _score(latest, "report_path"),
        idea["brainstorm_path"],
        idea["repo"],
        idea["plan_path"],
    ]


def _score_row(row: dict) -> list:
    return [
        row["idea_id"],
        row["version"],
        row["created_at"],
        row["agent"],
        row["usefulness"],
        row["complexity_mvp"],
        row["complexity_full"],
        row["verdict"],
        row["confidence"],
        row["report_path"],
    ]


def _source_row(item: tuple) -> list:
    idea_id, version, title, url = item
    return [idea_id, version, title, url]


def _event_row(row: dict) -> list:
    return [
        row["id"],
        row["idea_id"],
        row["at"],
        row["from_status"],
        row["to_status"],
        row["actor"],
        row["note"],
    ]


def _write(path: Path, tables) -> None:
    names = [name for name, _columns, _rows in tables]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", _content_types(len(tables)))
        package.writestr("_rels/.rels", _package_rels())
        package.writestr("xl/workbook.xml", _workbook(names))
        package.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(tables)))
        package.writestr("xl/styles.xml", _styles())
        for index, (name, columns, rows) in enumerate(tables, start=1):
            package.writestr(
                f"xl/worksheets/sheet{index}.xml", _sheet(name, columns, rows)
            )


def _content_types(sheets: int) -> str:
    overrides = [
        "<Override PartName=\"/xl/workbook.xml\" "
        "ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>",
        "<Override PartName=\"/xl/styles.xml\" "
        "ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>",
    ]
    for index in range(1, sheets + 1):
        overrides.append(
            f"<Override PartName=\"/xl/worksheets/sheet{index}.xml\" "
            "ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        )
    return (
        f"{_XML}<Types xmlns={quoteattr(_CONTENT_TYPES)}>"
        "<Default Extension=\"rels\" "
        "ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        + "".join(overrides)
        + "</Types>"
    )


def _package_rels() -> str:
    return (
        f"{_XML}<Relationships xmlns={quoteattr(_PKG_REL)}>"
        "<Relationship Id=\"rId1\" "
        f"Type={quoteattr(_OFFICE_REL + '/officeDocument')} "
        "Target=\"xl/workbook.xml\"/></Relationships>"
    )


def _workbook(names: list[str]) -> str:
    sheets = "".join(
        f"<sheet name={quoteattr(name)} sheetId=\"{index}\" r:id=\"rId{index}\"/>"
        for index, name in enumerate(names, start=1)
    )
    return (
        f"{_XML}<workbook xmlns={quoteattr(_SS)} xmlns:r={quoteattr(_OFFICE_REL)}>"
        "<workbookPr/><bookViews><workbookView activeTab=\"0\"/></bookViews>"
        f"<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_rels(sheets: int) -> str:
    items = [
        "<Relationship "
        f"Id=\"rId{index}\" Type={quoteattr(_OFFICE_REL + '/worksheet')} "
        f"Target=\"worksheets/sheet{index}.xml\"/>"
        for index in range(1, sheets + 1)
    ]
    items.append(
        f"<Relationship Id=\"rId{sheets + 1}\" "
        f"Type={quoteattr(_OFFICE_REL + '/styles')} Target=\"styles.xml\"/>"
    )
    return (
        f"{_XML}<Relationships xmlns={quoteattr(_PKG_REL)}>"
        + "".join(items)
        + "</Relationships>"
    )


def _styles() -> str:
    return (
        f"{_XML}<styleSheet xmlns={quoteattr(_SS)}>"
        "<numFmts count=\"1\">"
        f"<numFmt numFmtId=\"164\" formatCode={quoteattr(_DATE_FORMAT)}/>"
        "</numFmts>"
        "<fonts count=\"2\">"
        "<font><sz val=\"11\"/><name val=\"Calibri\"/></font>"
        "<font><b/><sz val=\"11\"/><name val=\"Calibri\"/></font>"
        "</fonts>"
        "<fills count=\"2\">"
        "<fill><patternFill patternType=\"none\"/></fill>"
        "<fill><patternFill patternType=\"gray125\"/></fill>"
        "</fills>"
        "<borders count=\"1\"><border>"
        "<left/><right/><top/><bottom/><diagonal/>"
        "</border></borders>"
        "<cellStyleXfs count=\"1\">"
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/>"
        "</cellStyleXfs>"
        "<cellXfs count=\"3\">"
        "<xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/>"
        "<xf numFmtId=\"0\" fontId=\"1\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyFont=\"1\"/>"
        "<xf numFmtId=\"164\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyNumberFormat=\"1\"/>"
        "</cellXfs></styleSheet>"
    )


def _sheet(name: str, columns: tuple, rows: list) -> str:
    last = _column_name(len(columns))
    dimension = f"A1:{last}{len(rows) + 1}"
    cols = []
    for index, (header, _kind, width) in enumerate(columns, start=1):
        shown = max(float(width), len(header) + 2)
        cols.append(
            f"<col min=\"{index}\" max=\"{index}\" width=\"{shown:.1f}\" customWidth=\"1\"/>"
        )
    body = [_row_xml(1, [header for header, _kind, _width in columns], columns, header=True)]
    for offset, row in enumerate(rows, start=2):
        if len(row) != len(columns):
            raise RuntimeError(
                f"{name} row has {len(row)} cells, expected {len(columns)}"
            )
        body.append(_row_xml(offset, row, columns, header=False))
    return (
        f"{_XML}<worksheet xmlns={quoteattr(_SS)}>"
        f"<dimension ref={quoteattr(dimension)}/>"
        "<sheetViews><sheetView workbookViewId=\"0\">"
        "<pane ySplit=\"1\" topLeftCell=\"A2\" activePane=\"bottomLeft\" state=\"frozen\"/>"
        "</sheetView></sheetViews>"
        f"<cols>{''.join(cols)}</cols>"
        f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


def _row_xml(number: int, values, columns: tuple, *, header: bool) -> str:
    cells = []
    for index, value in enumerate(values, start=1):
        kind = "text" if header else columns[index - 1][1]
        cells.append(_cell_xml(f"{_column_name(index)}{number}", kind, value, header=header))
    return f"<row r=\"{number}\">{''.join(cells)}</row>"


def _cell_xml(ref: str, kind: str, value, *, header: bool) -> str:
    if header:
        return (
            f"<c r={quoteattr(ref)} t=\"inlineStr\" s=\"1\">"
            f"<is><t xml:space=\"preserve\">{_xml_text(str(value))}</t></is></c>"
        )
    if value is None or value == "":
        return f"<c r={quoteattr(ref)}/>"
    if kind == "number":
        return f"<c r={quoteattr(ref)}><v>{int(value)}</v></c>"
    if kind == "date":
        serial = _format_serial(_serial(str(value)))
        return f"<c r={quoteattr(ref)} s=\"2\"><v>{serial}</v></c>"
    return (
        f"<c r={quoteattr(ref)} t=\"inlineStr\">"
        f"<is><t xml:space=\"preserve\">{_xml_text(_as_text(str(value)))}</t></is></c>"
    )


def _as_text(value: str) -> str:
    cleaned = _ILLEGAL_XML.sub("", value)
    if cleaned.startswith(_FORMULA):
        return "'" + cleaned
    return cleaned


def _xml_text(value: str) -> str:
    # A raw CR is normalised to LF before an XML parser returns the text.
    # The character reference is expanded afterwards, so the CR stays a CR.
    return escape(value).replace("\r", "&#13;")


def _serial(value: str) -> float:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    return (moment - _EXCEL_EPOCH).total_seconds() / 86400


def _format_serial(value: float) -> str:
    return format(value, ".12f").rstrip("0").rstrip(".")


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _verify(path: Path, expected: dict[str, int]) -> None:
    with zipfile.ZipFile(path) as package:
        found = _sheet_counts(package)
    if list(found) != list(expected) or found != expected:
        raise RuntimeError(
            f"workbook row counts {found} do not match the ledger {expected}"
        )


def _sheet_counts(package: zipfile.ZipFile) -> dict[str, int]:
    workbook = ElementTree.fromstring(package.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(package.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall(f"{{{_PKG_REL}}}Relationship")
    }
    counts = {}
    for sheet in workbook.findall(f"{{{_SS}}}sheets/{{{_SS}}}sheet"):
        name = sheet.attrib["name"]
        rid = sheet.attrib[f"{{{_OFFICE_REL}}}id"]
        target = targets[rid]
        if target.startswith("/"):
            part = target.lstrip("/")
        elif target.startswith("xl/"):
            part = target
        else:
            part = "xl/" + target
        root = ElementTree.fromstring(package.read(part))
        counts[name] = len(root.findall(f"{{{_SS}}}sheetData/{{{_SS}}}row"))
    return counts
