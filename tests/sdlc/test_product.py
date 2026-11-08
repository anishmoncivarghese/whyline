from __future__ import annotations

import json

import pytest

from whyline.sdlc import docset, product

ROLES = {"implementer": "claude"}
V1 = "# Product\n\n## Goals\n\nShip it.\n\n## Users\n\nEveryone.\n"
V2 = "# Product\n\n## Goals\n\nShip it fast.\n\n## Users\n\nEveryone.\n"


def _publish(root, text, **kw):
    return product.publish(root, text, set_name="Login", slug="login", approver="anish", **kw)


@pytest.mark.parametrize(
    "version, major, expected",
    [(None, False, "1.0"), (None, True, "1.0"), ("1.0", False, "1.1"), ("1.9", False, "1.10"),
     ("1.2", True, "2.0")],
)
def test_next_version(version, major, expected):
    assert product.next_version(version, major=major) == expected


def test_current_is_none_without_a_prd(tmp_path):
    assert product.current(tmp_path) is None


def test_publish_writes_all_four_files(tmp_path):
    assert _publish(tmp_path, V1) == "1.0"
    folder = tmp_path / "docs/product"
    text = (folder / "prd.md").read_text()
    assert text.splitlines()[0] == "<!-- product-prd v1.0 -->"
    assert text.endswith(V1)
    assert (folder / "history/prd-v1.0.md").read_text() == text
    meta = json.loads((folder / "product.json").read_text())
    assert meta["schema"] == 1 and meta["version"] == "1.0"
    assert meta["approved_by"] == "anish" and meta["update_claim"] is None
    cur = product.current(tmp_path)
    assert (cur.version, cur.text, cur.sha256) == ("1.0", text, meta["sha256"])
    assert cur.path == folder / "prd.md"
    assert "· Login · changed: all (new PRD) · approved by anish" in (folder / "changelog.md").read_text()


def test_second_publish_logs_only_changed_sections(tmp_path):
    _publish(tmp_path, V1)
    assert _publish(tmp_path, V2) == "1.1"
    lines = (tmp_path / "docs/product/changelog.md").read_text().splitlines()
    assert lines[-1].startswith("v1.1 · ")
    assert lines[-1].endswith(" · Login · changed: Goals · approved by anish")
    assert _publish(tmp_path, V2, major=True) == "2.0"
    assert (tmp_path / "docs/product/history/prd-v1.0.md").is_file()


def test_changed_sections_ignores_untouched():
    assert product.changed_sections(V1, V2) == ["Goals"]
    assert product.changed_sections(V1, V1) == []
    added = V1 + "\n## Risks\n\nMany.\n"
    assert product.changed_sections(V1, added) == ["Risks"]
    assert product.changed_sections(added, V1) == ["Risks"]
    assert product.changed_sections(V1, "# Retitled\n" + V1.split("\n", 1)[1]) == []


def test_changed_sections_ignores_headings_in_code():
    old = "## A\n\n```\n## Fake\n```\n"
    assert product.changed_sections(old, old.replace("Fake", "Other")) == ["A"]


def _set(tmp_path, name="Login", prd_mode="new"):
    return docset.create(tmp_path, name, "feature", "human", prd_mode=prd_mode, roles=ROLES)


def test_claim_refusal_and_release(tmp_path):
    _set(tmp_path, "One")
    _set(tmp_path, "Two")
    assert product.claim_holder(tmp_path) is None
    assert product.claim_update(tmp_path, "one") is True
    assert product.claim_update(tmp_path, "one") is True
    assert product.claim_update(tmp_path, "two") is False
    assert product.claim_holder(tmp_path) == "one"
    product.release_update(tmp_path, "two")
    assert product.claim_holder(tmp_path) == "one"
    product.release_update(tmp_path, "one")
    assert product.claim_update(tmp_path, "two") is True


def test_stale_claims_are_taken_over(tmp_path):
    made = _set(tmp_path, "One")
    _set(tmp_path, "Two")
    assert product.claim_update(tmp_path, "one")
    docset.add_version(tmp_path, made, "prd", V1, author="claude", note="n")
    docset.approve(tmp_path, made, "prd", approver="anish")
    assert product.claim_holder(tmp_path) is None
    assert product.claim_update(tmp_path, "two") is True
    assert product.claim_update(tmp_path, "ghost") is False
    (tmp_path / "docs/sdlc/two/docset.json").unlink()
    assert product.claim_holder(tmp_path) is None
    assert product.claim_update(tmp_path, "ghost") is True


def test_moved(tmp_path):
    made = _set(tmp_path, prd_mode="update")
    assert product.moved(tmp_path, made) is False
    _publish(tmp_path, V1)
    assert product.moved(tmp_path, made) is True
    made.document("prd")["based_on"] = "1.0"
    assert product.moved(tmp_path, made) is False
    _publish(tmp_path, V2)
    assert product.moved(tmp_path, made) is True
    assert product.moved(tmp_path, _set(tmp_path, "Small", prd_mode="none")) is False


def _approved(tmp_path):
    made = _set(tmp_path)
    docset.add_version(tmp_path, made, "prd", V1, author="claude", note="n")
    docset.approve(tmp_path, made, "prd", approver="anish")
    _publish(tmp_path, V1)
    docset.add_version(tmp_path, made, "spec", "spec text", author="claude", note="n")
    docset.approve(tmp_path, made, "spec", approver="anish")
    return made


def test_unbuilt_set_goes_out_of_date_when_the_prd_moves(tmp_path):
    made = _approved(tmp_path)
    assert made.document("spec")["based_on_prd"] == "1.0"
    assert docset.refresh_out_of_date(tmp_path, made) == []
    _publish(tmp_path, V2)
    assert docset.refresh_out_of_date(tmp_path, made) == [
        ("spec", "PRD changed (v1.0 → v1.1) after this was approved")
    ]


def test_built_set_is_never_marked(tmp_path):
    made = _approved(tmp_path)
    made.build_base = "abc123"
    docset.save(tmp_path, made)
    assert docset.load(tmp_path, "login").build_base == "abc123"
    _publish(tmp_path, V2)
    assert docset.refresh_out_of_date(tmp_path, made) == []
    assert made.document("spec")["status"] == "approved"


def test_header_and_index_label(tmp_path):
    made = _set(tmp_path)
    docset.add_version(tmp_path, made, "prd", V1, author="claude", note="n")
    docset.add_version(tmp_path, made, "prd", V2, author="claude", note="n")
    path = tmp_path / made.document("prd")["path"]
    assert "**Version:** Product PRD v1.0 (draft 2)" in path.read_text()
    assert "| Product PRD v1.0 (draft 2) |" in (tmp_path / "docs/sdlc/login/index.md").read_text()
    docset.approve(tmp_path, made, "prd", approver="anish")
    _publish(tmp_path, V2)
    docset.refresh(tmp_path, made)
    text = path.read_text()
    assert "**Version:** Product PRD v1.0\n" in text
    assert "draft" not in text
    assert "| Product PRD v1.0 |" in (tmp_path / "docs/sdlc/login/index.md").read_text()
