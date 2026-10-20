import subprocess
import sys
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
        command = Path(str(argv[0])).name
        if (
            command == "osascript"
            and code == 0
            and isinstance(stdout, (bytes, bytearray))
            and bytes(stdout).startswith(b"%PDF")
        ):
            Path(argv[-1]).write_bytes(stdout)
        elif command != "osascript":
            # cupsfilter and textutil are handed a real file. AppKit's
            # output path does not exist until the script writes it.
            Path(argv[-1]).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=b"")

    return calls, run


def test_word_is_a_zip_with_document_xml(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    result = documents.export(md, formats="word")
    assert result.docx == paths.documents_dir() / "note.docx"
    assert result.pdf is None
    assert result.notes == []
    with zipfile.ZipFile(result.docx) as package:
        assert "word/document.xml" in package.namelist()


def test_fake_osascript_writes_the_pdf(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    calls, run = _runner()
    result = documents.export(md, formats="both", run=run)
    assert result.docx == paths.documents_dir() / "note.docx"
    assert result.pdf == paths.documents_dir() / "note.pdf"
    assert result.pdf.read_bytes() == PDF_BYTES
    assert result.notes == []
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:3] == ["/usr/bin/osascript", "-l", "JavaScript"]
    assert argv[3].endswith("html_to_pdf.js")
    assert argv[4].endswith(".html")
    assert argv[5].endswith(".pdf")
    assert kwargs["timeout"] == 60
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL
    # The temp HTML is removed after osascript returns.
    assert not Path(argv[4]).exists()


def test_fake_osascript_receives_the_html(ideas_home, tmp_path):
    md = _markdown(tmp_path, text="Keep the table.\n\n" + TABLE)
    seen = []

    def run(argv, **kwargs):
        seen.append(Path(argv[-2]).read_text(encoding="utf-8"))
        Path(argv[-1]).write_bytes(PDF_BYTES)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    documents.export(md, formats="pdf", run=run)
    assert len(seen) == 1
    assert "<table>" in seen[0] and "Inbox" in seen[0]
    assert "ul { list-style-type: disc; }" in seen[0]
    assert "li { padding-left: 0.4em; }" in seen[0]


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


def _finished(argv, *, code=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=stderr)


def test_osascript_failure_uses_plain_text_and_says_so(ideas_home, tmp_path):
    md = _markdown(tmp_path)
    calls = []

    def run(argv, **kwargs):
        calls.append(Path(argv[0]).name)
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 60
        command = Path(argv[0]).name
        if command == "osascript":
            return _finished(argv, code=1, stderr=b"osascript failed")
        if command == "textutil":
            Path(argv[argv.index("-output") + 1]).write_text("A note.\n", encoding="utf-8")
            return _finished(argv)
        if command == "cupsfilter":
            assert argv[argv.index("-i") + 1] == "text/plain"
            return _finished(argv, stdout=PDF_BYTES)
        raise AssertionError(command)

    result = documents.export(md, formats="both", run=run)
    assert calls == ["osascript", "textutil", "cupsfilter"]
    assert result.docx is not None
    assert result.pdf is not None
    assert result.pdf.read_bytes() == PDF_BYTES
    assert result.notes == ["PDF is plain text on this Mac"]


def test_both_pdf_routes_failing_sends_word_only(ideas_home, tmp_path):
    md = _markdown(tmp_path)

    def run(argv, **kwargs):
        return _finished(argv, code=1, stderr=b"no converter")

    result = documents.export(md, formats="both", run=run)
    assert result.docx is not None
    assert result.pdf is None
    assert not (paths.documents_dir() / "note.pdf").exists()
    assert result.notes == ["PDF not available on this machine; sent Word only"]


def test_zero_byte_pdf_counts_as_failure(ideas_home, tmp_path):
    md = _markdown(tmp_path)

    def run(argv, **kwargs):
        command = Path(argv[0]).name
        if command == "osascript":
            Path(argv[-1]).write_bytes(b"")
            return _finished(argv)
        if command == "textutil":
            Path(argv[argv.index("-output") + 1]).write_text("A note.\n", encoding="utf-8")
            return _finished(argv)
        if command == "cupsfilter":
            return _finished(argv, stdout=b"")
        raise AssertionError(command)

    result = documents.export(md, formats="both", run=run)
    assert result.docx is not None
    assert result.pdf is None
    assert not (paths.documents_dir() / "note.pdf").exists()
    assert result.notes == ["PDF not available on this machine; sent Word only"]


def test_output_that_is_not_a_pdf_counts_as_failure(ideas_home, tmp_path):
    md = _markdown(tmp_path)

    def run(argv, **kwargs):
        command = Path(argv[0]).name
        if command == "osascript":
            Path(argv[-1]).write_bytes(b"not a pdf")
            return _finished(argv)
        if command == "cupsfilter":
            return _finished(argv, stdout=b"not a pdf either")
        if command == "textutil":
            Path(argv[argv.index("-output") + 1]).write_text("A note.\n", encoding="utf-8")
            return _finished(argv)
        raise AssertionError(command)

    result = documents.export(md, formats="pdf", run=run)
    assert result.pdf is None
    assert result.notes == ["PDF not available on this machine; sent the Markdown file."]


def test_probe_names_the_route_and_stays_in_a_temporary_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen = {}

    def run(argv, **kwargs):
        command = Path(argv[0]).name
        if command != "osascript":
            raise AssertionError(command)
        html = Path(argv[-2]).read_text(encoding="utf-8")
        pdf = Path(argv[-1]).resolve()
        seen["html"] = html
        seen["pdf"] = pdf
        assert pdf.parent != tmp_path.resolve()
        pdf.write_bytes(PDF_BYTES)
        return _finished(argv)

    result = documents.probe_pdf(run=run)
    assert result.route == "appkit"
    assert result.reason == ""
    assert "<h1>" in seen["html"]
    assert seen["html"].count("<li>") == 2
    assert seen["html"].count("<tr>") == 2
    assert "list-style-type: disc" in seen["html"]
    assert not seen["pdf"].exists()
    assert list(tmp_path.iterdir()) == []


def test_probe_fails_cleanly_when_no_route_works():
    def run(argv, **kwargs):
        return _finished(argv, code=1, stderr=b"no filter")

    result = documents.probe_pdf(run=run)
    assert result.route is None
    assert result.reason == "AppKit: no filter; plain text: no filter"


def test_html_to_pdf_script_ships_with_the_package():
    script = documents.script_path()
    text = script.read_text(encoding="utf-8")
    assert script.name == "html_to_pdf.js"
    assert "NSPrintSaveJob" in text
    assert "NSPrintJobSavingURL" in text
    assert "540" in text
    assert "setShowsPrintPanel(false)" in text
    assert "setShowsProgressPanel(false)" in text


def _pdf_text(path: Path) -> str:
    script = path.parent / "pdf-text.js"
    script.write_text(
        'ObjC.import("Quartz");\n'
        "function run(argv) {\n"
        "  var doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));\n"
        "  if (!doc || doc.isNil()) return '';\n"
        "  var text = doc.string;\n"
        "  if (!text || text.isNil()) return '';\n"
        "  return ObjC.unwrap(text);\n"
        "}\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", str(script), str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="AppKit PDF rendering needs macOS")
def test_appkit_renders_one_bullet_per_list_item(ideas_home, tmp_path):
    md = _markdown(tmp_path, name="report.md", text="# Report\n\n- Alpha\n- Beta\n")
    result = documents.export(md, formats="pdf")
    assert result.pdf is not None
    assert result.notes == []
    assert result.pdf.read_bytes().startswith(b"%PDF")
    text = _pdf_text(result.pdf)
    for item in ("Alpha", "Beta"):
        lines = [line for line in text.splitlines() if item in line]
        assert lines == [f"\u2022 {item}"]
        assert lines[0].count("\u2022") == 1


@pytest.mark.skipif(sys.platform != "darwin", reason="AppKit PDF rendering needs macOS")
def test_real_plain_text_route_writes_a_pdf_and_says_so(ideas_home, tmp_path):
    md = _markdown(tmp_path, text="# Report\n\nJust words.\n")

    def run(argv, **kwargs):
        if Path(argv[0]).name == "osascript":
            return _finished(argv, code=1, stderr=b"osascript failed")
        return subprocess.run(argv, **kwargs)

    result = documents.export(md, formats="pdf", run=run)
    assert result.pdf is not None
    assert result.pdf.read_bytes().startswith(b"%PDF")
    assert result.notes == ["PDF is plain text on this Mac"]
