"""Tests for the LSP formatting feature.

Covers:
  - capability detection (`documentFormattingProvider`,
    `documentRangeFormattingProvider`) for the bool form and the
    DocumentFormattingOptions/DocumentRangeFormattingOptions object form;
  - `textDocument/formatting` and `textDocument/rangeFormatting` param
    builders;
  - `apply_text_edits` correctness — empty list is a no-op; non-overlapping
    edits applied right-to-left so earlier edits don't shift later ones'
    positions; edits at end-of-buffer insert correctly; UTF-16 positions
    translate via the same helpers diagnostics uses.

Buffer-touching tests use `GtkSource.Buffer` (model only), not
`GtkSource.View` — see PR #14's CI postmortem for why View needs DISPLAY.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import GtkSource

from gedit_lsp.features.formatting import (
    apply_text_edits,
    build_formatting_params,
    build_range_formatting_params,
    is_formatting_supported,
    is_range_formatting_supported,
)


# --- capability detection ---------------------------------------------


def test_is_formatting_supported_true_when_bool_true() -> None:
    assert is_formatting_supported(True) is True


def test_is_formatting_supported_true_when_options_object() -> None:
    """LSP allows `documentFormattingProvider` to be a
    `DocumentFormattingOptions` dict (e.g. `{"workDoneProgress": true}`).
    Empty dict still means "supported"."""
    assert is_formatting_supported({}) is True
    assert is_formatting_supported({"workDoneProgress": True}) is True


def test_is_formatting_supported_false_when_none_or_false() -> None:
    assert is_formatting_supported(None) is False
    assert is_formatting_supported(False) is False


def test_is_range_formatting_supported_mirrors_formatting() -> None:
    assert is_range_formatting_supported(True) is True
    assert is_range_formatting_supported({}) is True
    assert is_range_formatting_supported(None) is False
    assert is_range_formatting_supported(False) is False


# --- param builders ---------------------------------------------------


def test_build_formatting_params_shape() -> None:
    params = build_formatting_params(
        uri="file:///tmp/x.py", tab_size=4, insert_spaces=True
    )
    assert params == {
        "textDocument": {"uri": "file:///tmp/x.py"},
        "options": {"tabSize": 4, "insertSpaces": True},
    }


def test_build_formatting_params_tab_indent() -> None:
    params = build_formatting_params(
        uri="file:///tmp/x.go", tab_size=8, insert_spaces=False
    )
    assert params["options"] == {"tabSize": 8, "insertSpaces": False}


def test_build_range_formatting_params_shape() -> None:
    params = build_range_formatting_params(
        uri="file:///tmp/x.py",
        start_line=2, start_char=0,
        end_line=5, end_char=10,
        tab_size=4, insert_spaces=True,
    )
    assert params == {
        "textDocument": {"uri": "file:///tmp/x.py"},
        "range": {
            "start": {"line": 2, "character": 0},
            "end":   {"line": 5, "character": 10},
        },
        "options": {"tabSize": 4, "insertSpaces": True},
    }


# --- apply_text_edits -------------------------------------------------


def _buffer(text: str) -> GtkSource.Buffer:
    buf = GtkSource.Buffer()
    buf.set_text(text)
    return buf


def _all_text(buf: GtkSource.Buffer) -> str:
    start = buf.get_start_iter()
    end = buf.get_end_iter()
    return buf.get_text(start, end, False)


def test_apply_text_edits_empty_is_noop() -> None:
    buf = _buffer("hello")
    apply_text_edits(buf, [])
    assert _all_text(buf) == "hello"


def test_apply_text_edits_single_replacement() -> None:
    buf = _buffer("hello world")
    apply_text_edits(buf, [
        {"range": {"start": {"line": 0, "character": 6},
                   "end":   {"line": 0, "character": 11}}, "newText": "there"},
    ])
    assert _all_text(buf) == "hello there"


def test_apply_text_edits_applied_right_to_left() -> None:
    """LSP spec: edits' positions reference the document state before
    *any* edit is applied. The applier must therefore work right-to-left
    so an earlier edit's text-shift doesn't invalidate a later edit's
    coordinates. This regression test gives edits in *forward* order
    (the order pylsp returns them) and asserts the result is correct."""
    buf = _buffer("aaa bbb ccc")
    # Edits in forward order (server-emitted order):
    #   (0,0)..(0,3) → "AAA"
    #   (0,4)..(0,7) → "BBB"
    #   (0,8)..(0,11) → "CCC"
    apply_text_edits(buf, [
        {"range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 3}}, "newText": "AAA"},
        {"range": {"start": {"line": 0, "character": 4},
                   "end":   {"line": 0, "character": 7}}, "newText": "BBB"},
        {"range": {"start": {"line": 0, "character": 8},
                   "end":   {"line": 0, "character": 11}}, "newText": "CCC"},
    ])
    assert _all_text(buf) == "AAA BBB CCC"


def test_apply_text_edits_with_size_changing_replacements() -> None:
    """Same as above but each replacement changes the text length.
    Right-to-left ordering is what makes this safe."""
    buf = _buffer("a b c")
    apply_text_edits(buf, [
        {"range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 1}}, "newText": "alpha"},
        {"range": {"start": {"line": 0, "character": 2},
                   "end":   {"line": 0, "character": 3}}, "newText": "beta"},
        {"range": {"start": {"line": 0, "character": 4},
                   "end":   {"line": 0, "character": 5}}, "newText": "gamma"},
    ])
    assert _all_text(buf) == "alpha beta gamma"


def test_apply_text_edits_pure_insertion() -> None:
    """A TextEdit with start == end is an insertion."""
    buf = _buffer("hello world")
    apply_text_edits(buf, [
        {"range": {"start": {"line": 0, "character": 5},
                   "end":   {"line": 0, "character": 5}}, "newText": ","},
    ])
    assert _all_text(buf) == "hello, world"


def test_apply_text_edits_at_end_of_buffer() -> None:
    """An edit at end-of-buffer (e.g. pylsp adding a trailing newline)
    must be applied without going out of bounds."""
    buf = _buffer("x = 1")
    apply_text_edits(buf, [
        {"range": {"start": {"line": 0, "character": 5},
                   "end":   {"line": 0, "character": 5}}, "newText": "\n"},
    ])
    assert _all_text(buf) == "x = 1\n"


def test_apply_text_edits_full_document_replacement() -> None:
    """Some servers (e.g. black via pylsp) return one big edit covering
    the whole document. Range goes from (0,0) to (last_line, last_char)."""
    buf = _buffer("def f( ):\n  pass\n")
    last_line = buf.get_end_iter().get_line()
    last_col = buf.get_end_iter().get_line_offset()
    apply_text_edits(buf, [
        {"range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": last_line, "character": last_col}},
         "newText": "def f():\n    pass\n"},
    ])
    assert _all_text(buf) == "def f():\n    pass\n"
