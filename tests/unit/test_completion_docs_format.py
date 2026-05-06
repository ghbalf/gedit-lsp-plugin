"""Tests for the proposal-text formatter used by the completion docs popover."""
from __future__ import annotations

from gedit_lsp.features.completion import LspProposal
from gedit_lsp.features.completion_docs import format_proposal_text


def _make(label: str, *, detail: str | None = None, doc: str = "") -> LspProposal:
    return LspProposal(
        label=label, insert_text=label, detail=detail, kind=None,
        documentation=doc, sort_text=label, filter_text=label, raw_item={},
    )


def test_format_with_detail_and_doc() -> None:
    p = _make("foo", detail="(method) foo() -> int", doc="Foo the bar.")
    assert format_proposal_text(p) == "(method) foo() -> int\n\nFoo the bar."


def test_format_doc_only() -> None:
    p = _make("foo", doc="Just docs.")
    assert format_proposal_text(p) == "Just docs."


def test_format_detail_only() -> None:
    p = _make("foo", detail="(class)")
    assert format_proposal_text(p) == "(class)"


def test_format_empty_returns_blank_placeholder() -> None:
    p = _make("foo")
    # A single space rather than "" so the popover doesn't collapse to
    # zero height (matches the v0.2.0 attempt's approach).
    assert format_proposal_text(p) == " "
