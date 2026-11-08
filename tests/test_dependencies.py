import importlib


def test_relay_documents_module_exposes_the_draft_api():
    documents = importlib.import_module("whyline_relay.documents")
    for name in ("draft", "revise_text", "discard", "DocKind"):
        assert hasattr(documents, name), name
