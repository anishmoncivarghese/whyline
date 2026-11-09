from __future__ import annotations

from pathlib import Path

from whyline.agents import convert
from whyline.ideas import documents
from whyline.sdlc import docset, export


def make_set(root: Path, size="feature", prd_mode="new"):
    made = docset.create(root, "Login", size, "auto", prd_mode=prd_mode, roles={})
    (root / "plans").mkdir(exist_ok=True)
    for doc in made.documents:
        if doc["kind"] == "plan":
            continue
        path = root / doc["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {doc['kind']} body\n")
    (root / "plans/login.plan.md").write_text("# Plan body\n")
    (root / "plans/login.tests.md").write_text("# Tests body\n")
    docset.save(root, made)
    docset.refresh(root, made)
    docset.log_review(root, made, made.documents[0]["kind"], actor="a", action="approved")
    return made


def fake_word(monkeypatch):
    def to_docx(md, out):
        out.write_bytes(b"docx")
        return out

    monkeypatch.setattr(convert, "to_docx", to_docx)


def fake_pdf(monkeypatch, route="appkit"):
    def render(html, out, *, run=None, work=None):
        if route:
            Path(out).write_bytes(b"%PDF-1")
        return documents.PdfResult(route)

    monkeypatch.setattr(documents, "render_html", render)


def capture_md(monkeypatch):
    seen = {}

    def to_docx(md, out):
        seen["md"] = md.read_text()
        out.write_bytes(b"docx")
        return out

    monkeypatch.setattr(convert, "to_docx", to_docx)
    return seen


def test_order_and_header_stripped(tmp_path, monkeypatch):
    make_set(tmp_path)
    seen = capture_md(monkeypatch)
    fake_pdf(monkeypatch)
    result = export.export_pack(tmp_path, "login", tmp_path / "out")
    md = seen["md"]
    assert docset.HEADER_START not in md
    order = [md.index(s) for s in (
        "# Login", "# prd body", "# spec body", "# Plan body", "# Tests body",
        "# build-record body", "# Review log",
    )]
    assert order == sorted(order)
    assert len(set(order)) == len(order)
    assert {p.name for p in result.files} == {"login-docs.docx", "login-docs.pdf"}


def test_pdf_fallback_note(tmp_path, monkeypatch):
    make_set(tmp_path)
    fake_word(monkeypatch)
    fake_pdf(monkeypatch, route=None)
    result = export.export_pack(tmp_path, "login", tmp_path / "out")
    assert [p.name for p in result.files] == ["login-docs.docx"]
    assert any("PDF not available" in n for n in result.notes)


def test_missing_document_skipped_with_note(tmp_path, monkeypatch):
    made = make_set(tmp_path)
    (tmp_path / made.document("spec")["path"]).unlink()
    seen = capture_md(monkeypatch)
    fake_pdf(monkeypatch)
    result = export.export_pack(tmp_path, "login", tmp_path / "out")
    assert "# spec body" not in seen["md"]
    assert any("Spec is missing" in n for n in result.notes)


def test_prd_update_uses_history_version(tmp_path, monkeypatch):
    made = make_set(tmp_path, prd_mode="update")
    hist = tmp_path / "docs/product/history"
    hist.mkdir(parents=True)
    (hist / "prd-v1.2.md").write_text(
        "<!-- product-prd v1.2 -->\n# PRD\n\n## Goals\n\nold\n\n## Users\n\nsame\n"
    )
    prd = made.document("prd")
    prd["based_on_prd"] = "1.2"
    (tmp_path / prd["path"]).write_text("# PRD\n\n## Goals\n\nnew\n\n## Users\n\nsame\n")
    docset.save(tmp_path, made)
    seen = capture_md(monkeypatch)
    fake_pdf(monkeypatch)
    export.export_pack(tmp_path, "login", tmp_path / "out")
    md = seen["md"]
    assert "# Product PRD v1.2" in md
    assert "old" in md and "### Goals" in md and "new" in md
    assert "### Users" not in md


def test_default_out_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert export.default_out_dir() == tmp_path / "Downloads"


def test_fresh_eyes_appendix_follows_review_log(tmp_path, monkeypatch):
    from whyline.sdlc import goldfish, workspace

    monkeypatch.setattr(workspace, "docs_root", lambda root: root)
    made = make_set(tmp_path)
    folder = docset._folder(tmp_path, made.slug) / goldfish.REVIEWS_DIR
    folder.mkdir(parents=True)
    (folder / "spec-v1.md").write_text(
        "Blockers: 0 · Major: 0 · Nits: 0 · Not run: none · Reviewer: codex\n", encoding="utf-8"
    )
    seen = capture_md(monkeypatch)
    fake_pdf(monkeypatch)
    export.export_pack(tmp_path, "login", tmp_path / "out")
    md = seen["md"]
    assert md.index("# Review log") < md.index("# Fresh-eyes reviews") < md.index("## Spec")
    assert "Reviewer: codex" in md
    assert md.rstrip().endswith("Reviewer: codex")
