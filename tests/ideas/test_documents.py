import subprocess
import zipfile
from pathlib import Path

import pytest

from whyline.ideas import documents, paths, store

PDF_BYTES = b"%PDF-1.4\n%whyline-fake\n%%EOF\n"
TABLE = "| Item | Score |\n| --- | --- |\n| Inbox | 7 |\n"


@pytest.fixture
def ideas_home(tmp_path, monkeypatch):
    home = tmp_path / "ideas"
    monkeypatch.setenv("WHYLINE_IDEAS_HOME", str(home))
    return home


@pytest.fixture
def conn(ideas_home):
    return store.connect()


def _markdown(folder: Path, name: str = "note.md", text: str = "# Hello\n\nA note.\n") -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def _runner(stdout=PDF_BYTES, code=0, exc=None):
    calls = []

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if exc is not None:
            raise exc
        page = Path(argv[-1])
        page.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(argv, code, stdout=stdout)

    return calls, run


def test_word_is_a_zip_with_document_xml(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    result = documents.export(md, formats="word")
    assert result.docx == paths.documents_dir() / "note.docx"
    assert result.pdf is None
    assert result.notes == []
    with zipfile.ZipFile(result.docx) as package:
        assert "word/document.xml" in package.namelist()


def test_fake_cupsfilter_writes_the_pdf(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    calls, run = _runner()
    result = documents.export(md, formats="both", run=run)
    assert result.docx == paths.documents_dir() / "note.docx"
    assert result.pdf == paths.documents_dir() / "note.pdf"
    assert result.pdf.read_bytes() == PDF_BYTES
    assert result.notes == []
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[0] == "/usr/sbin/cupsfilter"
    assert argv[-1].endswith(".html")
    assert kwargs["timeout"] == 60
    assert kwargs["shell"] is False
    html = Path(argv[-1])
    # The temp HTML is removed after cupsfilter returns. The runner already
    # read it; a second export is not required to prove the page existed.
    assert not html.exists()


def test_fake_cupsfilter_receives_the_html(ideas_home, tmp_path):
    md = _markdown(tmp_path, text="Keep the table.\n\n" + TABLE)
    seen = []

    def run(argv, **kwargs):
        seen.append(Path(argv[-1]).read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(argv, 0, stdout=PDF_BYTES)

    documents.export(md, formats="pdf", run=run)
    assert len(seen) == 1
    assert "<table>" in seen[0] and "Inbox" in seen[0]


def test_missing_cupsfilter_gives_word_only(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    calls, run = _runner(exc=FileNotFoundError(2, "No such file", "/usr/sbin/cupsfilter"))
    result = documents.export(md, formats="both", run=run)
    assert result.docx == paths.documents_dir() / "note.docx"
    assert result.pdf is None
    assert not (paths.documents_dir() / "note.pdf").exists()
    assert result.notes == ["PDF not available on this machine; sent Word only"]
    assert calls


def test_word_format_never_calls_the_pdf_runner(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    calls, run = _runner()
    result = documents.export(md, formats="word", run=run)
    assert calls == []
    assert result.docx is not None
    assert result.pdf is None
    assert result.notes == []


def test_markdown_table_survives_into_word(ideas_home, tmp_path):
    md = _markdown(tmp_path, name="scored.md", text="# Score\n\n" + TABLE)
    result = documents.export(md, formats="word")
    xml = zipfile.ZipFile(result.docx).read("word/document.xml").decode("utf-8")
    assert "<w:tbl>" in xml
    assert "Inbox" in xml and "Score" in xml and "7" in xml


def test_empty_cupsfilter_output_gives_word_only(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    _calls, run = _runner(stdout=b"")
    result = documents.export(md, formats="both", run=run)
    assert result.docx is not None
    assert result.pdf is None
    assert not (paths.documents_dir() / "note.pdf").exists()
    assert result.notes == ["PDF not available on this machine; sent Word only"]


def test_cupsfilter_failure_gives_word_only(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    _calls, run = _runner(code=1, stdout=b"not a pdf")
    result = documents.export(md, formats="both", run=run)
    assert result.pdf is None
    assert result.docx is not None
    assert result.notes == ["PDF not available on this machine; sent Word only"]


def test_cupsfilter_timeout_gives_word_only(ideas_home, tmp_path):
    md = _markdown(tmp_path)

    def run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 60))

    result = documents.export(md, formats="both", run=run)
    assert result.pdf is None
    assert result.docx is not None
    assert result.notes == ["PDF not available on this machine; sent Word only"]


def test_both_fail_says_to_send_the_markdown(ideas_home, tmp_path):
    missing = tmp_path / "gone.md"
    calls, run = _runner()
    result = documents.export(missing, formats="both", run=run)
    assert result.docx is None
    assert result.pdf is None
    assert calls == []
    assert result.notes == [
        "Word and PDF could not be written; sent the Markdown file."
    ]
    assert list(paths.documents_dir().glob("gone.*")) == []


def test_formats_follow_the_kv_key(conn, tmp_path):
    md = _markdown(tmp_path)
    conn.execute("INSERT INTO kv (key, value) VALUES ('doc_formats', 'pdf')")
    calls, run = _runner()
    result = documents.export(md, run=run)
    assert result.docx is None
    assert result.pdf == paths.documents_dir() / "note.pdf"
    assert result.pdf.read_bytes() == PDF_BYTES
    assert not (paths.documents_dir() / "note.docx").exists()
    assert calls


def test_explicit_formats_override_kv(conn, tmp_path):
    md = _markdown(tmp_path)
    conn.execute("INSERT INTO kv (key, value) VALUES ('doc_formats', 'pdf')")
    calls, run = _runner()
    result = documents.export(md, formats="word", run=run)
    assert calls == []
    assert result.docx is not None
    assert result.pdf is None


def test_missing_kv_means_both(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    calls, run = _runner()
    result = documents.export(md, run=run)
    assert result.docx is not None
    assert result.pdf is not None
    assert calls


def test_unknown_kv_means_both(conn, tmp_path):
    md = _markdown(tmp_path)
    conn.execute("INSERT INTO kv (key, value) VALUES ('doc_formats', 'docx')")
    calls, run = _runner()
    result = documents.export(md, run=run)
    assert result.docx is not None
    assert result.pdf is not None
    assert calls


def test_formats_must_be_word_pdf_or_both(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    with pytest.raises(ValueError, match="formats"):
        documents.export(md, formats="docx")
