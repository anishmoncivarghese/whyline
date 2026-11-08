from __future__ import annotations

import zipfile

import pytest

from whyline.sdlc import docset as ds
from whyline.sdlc import importer
from whyline.sdlc.docset import DocSetError

ROLES = {"implementer": "claude"}


@pytest.fixture
def made(tmp_path):
    return tmp_path, ds.create(tmp_path, "Thing", "large", "human", roles=ROLES)


def test_markdown_and_text(tmp_path):
    (tmp_path / "a.md").write_bytes(b"# Hi\r\nthere")
    (tmp_path / "b.TXT").write_text("plain", encoding="utf-8")
    assert importer.read_source(tmp_path / "a.md") == "# Hi\nthere"
    assert importer.read_source(tmp_path / "b.TXT") == "plain"


def test_docx(tmp_path):
    body = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Hello docx</w:t></w:r></w:p></w:body></w:document>"
    )
    path = tmp_path / "a.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", body)
    assert "Hello docx" in importer.read_source(path)


def test_pdf(tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(importer, "read_pdf_text", lambda p: "pdf text")
    assert importer.read_source(path) == "pdf text"


def test_readers_are_public():
    from whyline.jobs import profile

    assert profile.read_pdf_text is profile._read_pdf_text
    assert profile.read_docx_text is profile._read_docx_text


def test_refuses_other_type(tmp_path):
    (tmp_path / "a.exe").write_text("x")
    with pytest.raises(DocSetError, match="Cannot import"):
        importer.read_source(tmp_path / "a.exe")


def test_refuses_missing(tmp_path):
    with pytest.raises(DocSetError, match="not found"):
        importer.read_source(tmp_path / "a.md")


def test_refuses_empty(tmp_path):
    (tmp_path / "a.md").write_text("  \n", encoding="utf-8")
    with pytest.raises(DocSetError, match="no text"):
        importer.read_source(tmp_path / "a.md")


def test_refuses_over_2mb(tmp_path):
    (tmp_path / "a.txt").write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(DocSetError, match="2 MB"):
        importer.read_source(tmp_path / "a.txt")


def test_refuses_bad_docx(tmp_path):
    (tmp_path / "a.docx").write_text("not a zip")
    with pytest.raises(DocSetError, match="docx"):
        importer.read_source(tmp_path / "a.docx")


def test_import_as_adds_version_and_logs(made):
    root, docset = made
    src = root / "spec-notes.md"
    src.write_text("Notes", encoding="utf-8")
    assert importer.import_as(root, docset, "design", src, actor="anish") == 1
    doc = docset.document("design")
    assert doc["note"] == "imported from spec-notes.md"
    assert doc["written_by"] == "anish"
    assert ds.strip_header((root / doc["path"]).read_text(encoding="utf-8")).strip() == "Notes"
    log = (root / "docs/sdlc" / docset.slug / "review-log.md").read_text(encoding="utf-8")
    assert "design v1 · imported · anish" in log


def test_import_brainstorm_keeps_original(made):
    root, docset = made
    folder = root / "docs" / "brainstorm"
    folder.mkdir(parents=True)
    src = folder / "idea.md"
    src.write_text("Idea", encoding="utf-8")
    importer.import_brainstorm(root, docset, src)
    assert src.read_text(encoding="utf-8") == "Idea"
    doc = docset.document("brainstorm")
    assert ds.strip_header((root / doc["path"]).read_text(encoding="utf-8")).strip() == "Idea"
    assert doc["note"] == "imported from idea.md"
