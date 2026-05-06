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


def test_format_empty_returns_empty_string() -> None:
    p = _make("foo")
    assert format_proposal_text(p) == ""


def test_format_preserves_embedded_newlines() -> None:
    """Pre-embedded \\n in detail or documentation is left as-is — the
    helper joins with `\\n\\n` separators between fields, not within them."""
    p = _make("foo", detail="line1\nline2", doc="paragraph one\n\nparagraph two")
    assert format_proposal_text(p) == "line1\nline2\n\nparagraph one\n\nparagraph two"


def test_format_does_not_truncate_long_documentation() -> None:
    """The pure formatter never truncates — UI-side scrolling is the
    controller's responsibility."""
    long_doc = "x" * 10_000
    p = _make("foo", doc=long_doc)
    out = format_proposal_text(p)
    assert long_doc in out
    assert len(out) >= 10_000
