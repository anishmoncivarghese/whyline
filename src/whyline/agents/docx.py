"""A report as a Word (.docx) file with real tables (deliveries spec 4).

macOS `textutil` drops HTML tables when it writes .docx, so whyline writes
the file itself: Markdown → HTML with the `markdown` package, then that HTML
→ WordprocessingML with the standard library. Headings, paragraphs, bold,
italic, links, lists and tables are kept; a wide table puts the document on
a landscape A3 page with a smaller font."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import markdown

WIDE_TABLE = 7  # columns from which the page turns landscape

_HEADING_SIZE = {1: 32, 2: 28, 3: 24, 4: 22, 5: 20, 6: 20}  # half-points


@dataclass
class Run:
    text: str = ""
    bold: bool = False
    italic: bool = False
    mono: bool = False
    href: str = ""
    br: bool = False


@dataclass
class Para:
    level: int = 0  # 1-6 for headings
    prefix: str = ""
    indent: int = 0
    runs: list[Run] = field(default_factory=list)


@dataclass
class Row:
    header: bool
    cells: list[list[Para]] = field(default_factory=list)


@dataclass
class Table:
    rows: list[Row] = field(default_factory=list)


class _Reader(HTMLParser):
    """Turns the `markdown` package's HTML into paragraphs and tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Para | Table] = []
        self.para: Para | None = None
        self.bold = self.italic = self.mono = 0
        self.links: list[str] = []
        self.lists: list[list] = []  # [kind, counter]
        self.table: Table | None = None
        self.cell: list[Para] | None = None
        self.header_row = False

    # -- where text goes -------------------------------------------------
    def _new_para(self, **kwargs) -> Para:
        para = Para(**kwargs)
        if self.cell is not None:
            self.cell.append(para)
        else:
            self.blocks.append(para)
        self.para = para
        return para

    def _current(self) -> Para:
        return self.para if self.para is not None else self._new_para()

    def _run(self, **kwargs) -> None:
        self._current().runs.append(Run(
            bold=self.bold > 0, italic=self.italic > 0, mono=self.mono > 0,
            href=self.links[-1] if self.links else "", **kwargs,
        ))

    # -- parser callbacks ------------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._new_para(level=int(tag[1]))
        elif tag == "p":
            # A loose list item wraps its text in <p>: keep the item's line.
            if not (self.para is not None and self.para.prefix and not self.para.runs):
                self._new_para()
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            self.para = None
        elif tag == "li":
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            prefix = f"{kind[1]}. " if kind[0] == "ol" else "• "
            self._new_para(prefix=prefix, indent=len(self.lists))
        elif tag in ("strong", "b"):
            self.bold += 1
        elif tag in ("em", "i"):
            self.italic += 1
        elif tag in ("code", "pre"):
            self.mono += 1
            if tag == "pre":
                self._new_para()
        elif tag == "a":
            self.links.append(attrs.get("href") or "")
        elif tag == "br":
            self._run(br=True)
        elif tag == "table":
            self.table = Table()
            self.blocks.append(self.table)
            self.para = None
        elif tag == "thead":
            self.header_row = True
        elif tag == "tbody":
            self.header_row = False
        elif tag == "tr" and self.table is not None:
            self.table.rows.append(Row(header=self.header_row))
        elif tag in ("th", "td") and self.table is not None and self.table.rows:
            self.cell = []
            self.table.rows[-1].cells.append(self.cell)
            if tag == "th":
                self.table.rows[-1].header = True
            self._new_para()
        elif tag == "hr":
            self._new_para()
            self.para = None

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
            self.para = None
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self.para = None
        elif tag in ("strong", "b"):
            self.bold = max(0, self.bold - 1)
        elif tag in ("em", "i"):
            self.italic = max(0, self.italic - 1)
        elif tag in ("code", "pre"):
            self.mono = max(0, self.mono - 1)
            if tag == "pre":
                self.para = None
        elif tag == "a":
            if self.links:
                self.links.pop()
        elif tag in ("th", "td"):
            self.cell = None
            self.para = None
        elif tag == "table":
            self.table = None
            self.para = None

    def handle_data(self, data):
        if self.mono:
            text = data
        elif not data.strip():
            # Whitespace between blocks is dropped; between two inline
            # pieces ("**A:** **B**") it is the one space that separates them.
            if self.para is None or not self.para.runs or "\n" in data:
                return
            text = " "
        else:
            text = " ".join(data.split())
            if data[:1].isspace():
                text = " " + text
            if data[-1:].isspace():
                text = text + " "
        if text:
            self._run(text=text)


def _read(text: str) -> list[Para | Table]:
    reader = _Reader()
    reader.feed(markdown.markdown(text, extensions=["tables"]))
    reader.close()
    return reader.blocks


# -- WordprocessingML ------------------------------------------------------

_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


class _Links:
    def __init__(self) -> None:
        self.targets: list[str] = []

    def rid(self, url: str) -> str:
        if url not in self.targets:
            self.targets.append(url)
        return f"rId{self.targets.index(url) + 10}"


def _run_xml(run: Run, size: int | None = None) -> str:
    props = []
    if run.bold:
        props.append("<w:b/>")
    if run.italic:
        props.append("<w:i/>")
    if run.mono:
        props.append('<w:rFonts w:ascii="Menlo" w:hAnsi="Menlo" w:cs="Menlo"/>')
    if run.href:
        props.append('<w:color w:val="0563C1"/><w:u w:val="single"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    if run.br:
        return f"<w:r>{rpr}<w:br/></w:r>"
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(run.text)}</w:t></w:r>'


def _para_xml(para: Para, links: _Links, *, bold: bool = False) -> str:
    ppr = []
    size = None
    if para.level:
        ppr.append('<w:spacing w:before="240" w:after="120"/><w:keepNext/>')
        size = _HEADING_SIZE[para.level]
    if para.indent:
        ppr.append(f'<w:ind w:left="{360 * para.indent}" w:hanging="360"/>')
    out = [f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>" if ppr else "<w:p>"]
    runs = list(para.runs)
    if para.prefix:
        runs.insert(0, Run(text=para.prefix))
    index = 0
    while index < len(runs):
        run = runs[index]
        if run.bold is False and (para.level or bold):
            run = Run(**{**run.__dict__, "bold": True})
        if run.href:
            href = run.href
            group = []
            while index < len(runs) and runs[index].href == href:
                group.append(runs[index])
                index += 1
            inner = "".join(_run_xml(Run(**{**g.__dict__, "bold": g.bold or bool(para.level) or bold}), size)
                            for g in group)
            out.append(f'<w:hyperlink r:id="{links.rid(href)}" w:history="1">{inner}</w:hyperlink>')
            continue
        out.append(_run_xml(run, size))
        index += 1
    out.append("</w:p>")
    return "".join(out)


_BORDERS = "".join(
    f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
    for side in ("top", "left", "bottom", "right", "insideH", "insideV")
)


def _cell_text(cell: list[Para]) -> str:
    return " ".join("".join(run.text for run in para.runs) for para in cell)


def _widths(table: Table, columns: int, text_width: int, font: int) -> list[int]:
    """Column widths in twips. Each column is at least as wide as its longest
    word in this font (so words never break mid-way); the rest of the page is
    shared by how much text each column holds."""
    # An average character, in twips, allowing for viewers that swap in a
    # wider font than the one asked for (Quick Look uses a serif font).
    char = font / 2 * 20 * 0.75
    floors, weights = [], []
    for index in range(columns):
        texts = [_cell_text(row.cells[index]) for row in table.rows if index < len(row.cells)]
        longest_word = max((len(word) for text in texts for word in text.split()), default=1)
        floors.append(int(min(longest_word, 24) * char * 1.25) + 130)  # bold headers, cell margins
        average = sum(len(text) for text in texts) / max(len(texts), 1)
        weights.append(min(average, 160) + 1)
    spare = text_width - sum(floors)
    if spare <= 0:
        scale = text_width / sum(floors)
        return [int(floor * scale) for floor in floors]
    total = sum(weights)
    return [floor + int(spare * weight / total) for floor, weight in zip(floors, weights)]


def _table_xml(table: Table, links: _Links, text_width: int, font: int) -> str:
    columns = max((len(row.cells) for row in table.rows), default=1) or 1
    widths = _widths(table, columns, text_width, font)
    out = [
        "<w:tbl><w:tblPr>"
        '<w:tblW w:w="5000" w:type="pct"/>'
        f"<w:tblBorders>{_BORDERS}</w:tblBorders>"
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:left w:w="60" w:type="dxa"/><w:right w:w="60" w:type="dxa"/></w:tblCellMar>'
        "</w:tblPr><w:tblGrid>"
        + "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
        + "</w:tblGrid>"
    ]
    for row in table.rows:
        out.append("<w:tr>")
        if row.header:
            out.append("<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>")
        cells = row.cells + [[] for _ in range(columns - len(row.cells))]
        for cell, width in zip(cells, widths):
            shade = '<w:shd w:val="clear" w:color="auto" w:fill="EEEEEE"/>' if row.header else ""
            out.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>')
            paragraphs = cell or [Para()]
            out.extend(_para_xml(para, links, bold=row.header) for para in paragraphs)
            out.append("</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl><w:p/>")  # Word wants a paragraph after a table
    return "".join(out)


def _styles(font_half_points: int) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:styles {_NS}><w:docDefaults><w:rPrDefault><w:rPr>"
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>'
        f'<w:sz w:val="{font_half_points}"/><w:szCs w:val="{font_half_points}"/>'
        '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="80"/></w:pPr>'
        "</w:pPrDefault></w:docDefaults>"
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        "</w:styles>"
    )


def write(text: str, out: Path) -> Path:
    blocks = _read(text)
    wide = any(isinstance(b, Table) and b.rows and max(len(r.cells) for r in b.rows) >= WIDE_TABLE
               for b in blocks)
    widest = max((len(r.cells) for b in blocks if isinstance(b, Table) for r in b.rows), default=0)
    if wide:  # A3 landscape, 12.7 mm margins; 7.5 pt for very wide tables
        page_w, page_h, margin, font = 23811, 16838, 720, 15 if widest >= 12 else 16
        size = f'<w:pgSz w:w="{page_w}" w:h="{page_h}" w:orient="landscape"/>'
    else:  # A4 portrait, 20 mm margins
        page_w, page_h, margin, font = 11906, 16838, 1134, 21
        size = f'<w:pgSz w:w="{page_w}" w:h="{page_h}"/>'
    links = _Links()
    body = []
    for block in blocks:
        if isinstance(block, Table):
            body.append(_table_xml(block, links, page_w - 2 * margin, font))
        else:
            body.append(_para_xml(block, links))
    section = (f'<w:sectPr>{size}<w:pgMar w:top="{margin}" w:right="{margin}" '
               f'w:bottom="{margin}" w:left="{margin}" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f"<w:document {_NS}><w:body>{''.join(body) or '<w:p/>'}{section}</w:body></w:document>")
    rels = "".join(
        f'<Relationship Id="{links.rid(url)}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        f'Target={quoteattr(url)} TargetMode="External"/>'
        for url in links.targets
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        f'Target="styles.xml"/>{rels}</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    out = Path(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", package_rels)
        package.writestr("word/document.xml", document)
        package.writestr("word/styles.xml", _styles(font))
        package.writestr("word/_rels/document.xml.rels", document_rels)
    return out
