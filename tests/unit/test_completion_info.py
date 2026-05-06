"""Tests for the completion Details-pane formatter."""
from __future__ import annotations

from gedit_lsp.features.completion import LspProposal, format_info_text


def _proposal(detail: str | None = None, doc: str = "") -> LspProposal:
    return LspProposal(
        label="x",
        insert_text="x",
        detail=detail,
        kind=None,
        documentation=doc,
        sort_text="x",
        filter_text="x",
        raw_item={},
    )


def test_format_info_text_detail_and_doc() -> None:
    p = _proposal(detail="def foo() -> int", doc="Returns an integer.")
    assert format_info_text(p) == "def foo() -> int\n\nReturns an integer."


def test_format_info_text_detail_only() -> None:
    assert format_info_text(_proposal(detail="def foo()")) == "def foo()"


def test_format_info_text_doc_only() -> None:
    assert format_info_text(_proposal(doc="The thing.")) == "The thing."


def test_format_info_text_neither_returns_empty() -> None:
    """Empty result lets the pane render blank — a clearer "no docs"
    signal than synthesised placeholder text."""
    assert format_info_text(_proposal()) == ""
