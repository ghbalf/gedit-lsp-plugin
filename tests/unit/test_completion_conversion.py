"""Tests for LSP CompletionItem → display-ready Python dataclass."""
from __future__ import annotations

from gedit_lsp.features.completion import (
    LspProposal,
    extract_completion_items,
    lsp_item_to_proposal,
)


def test_lsp_item_minimal_label_only() -> None:
    p = lsp_item_to_proposal({"label": "foo"})
    assert isinstance(p, LspProposal)
    assert p.label == "foo"
    assert p.insert_text == "foo"           # falls back to label
    assert p.detail is None
    assert p.kind is None
    assert p.documentation == ""
    assert p.sort_text == "foo"             # falls back to label
    assert p.filter_text == "foo"           # falls back to label
    assert p.raw_item == {"label": "foo"}   # preserved for resolve


def test_lsp_item_full_fields() -> None:
    item = {
        "label": "spam",
        "insertText": "spam(${0})",
        "detail": "(method) Spam.spam() -> int",
        "kind": 2,
        "documentation": {"kind": "markdown", "value": "Spam the eggs."},
        "sortText": "0_spam",
        "filterText": "spam",
    }
    p = lsp_item_to_proposal(item)
    assert p.insert_text == "spam(${0})"
    assert p.detail == "(method) Spam.spam() -> int"
    assert p.kind == 2
    assert p.documentation == "Spam the eggs."
    assert p.sort_text == "0_spam"
    assert p.filter_text == "spam"


def test_lsp_item_documentation_string_form() -> None:
    p = lsp_item_to_proposal({"label": "x", "documentation": "plain string"})
    assert p.documentation == "plain string"


def test_extract_completion_items_handles_array() -> None:
    items = extract_completion_items([{"label": "a"}, {"label": "b"}])
    assert [p.label for p in items] == ["a", "b"]


def test_extract_completion_items_handles_completion_list() -> None:
    response = {"isIncomplete": False, "items": [{"label": "x"}]}
    items = extract_completion_items(response)
    assert [p.label for p in items] == ["x"]


def test_extract_completion_items_handles_null() -> None:
    assert extract_completion_items(None) == []


def test_extract_completion_items_handles_empty_object() -> None:
    assert extract_completion_items({}) == []
    assert extract_completion_items({"items": []}) == []


def test_extract_completion_list_preserves_isincomplete() -> None:
    """Caller needs to know if the list was incomplete — we expose it via
    a sibling helper since extract_ returns proposals only."""
    from gedit_lsp.features.completion import response_is_incomplete
    assert response_is_incomplete(None) is False
    assert response_is_incomplete([]) is False
    assert response_is_incomplete({"isIncomplete": True, "items": []}) is True
    assert response_is_incomplete({"isIncomplete": False, "items": []}) is False
