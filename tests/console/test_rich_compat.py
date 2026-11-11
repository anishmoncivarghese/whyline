"""Textual 2.x reads rich's style metadata with marshal; rich 14.2 and later write it
with pickle. Moving the mouse over any link in the console then crashed with
"bad marshal data (unknown type code)". Rich is pinned below 14.2 for that."""

from rich.style import Style as RichStyle
from textual.style import Style


def test_link_style_metadata_reads_back():
    rich_style = RichStyle(link="https://example.com", meta={"@click": "go"})
    style = Style.from_rich_style(rich_style)
    assert style.meta["@click"] == "go"
