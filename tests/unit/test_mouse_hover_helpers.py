"""Unit tests for mouse_hover pure helpers."""
from __future__ import annotations

import gi

gi.require_version("GtkSource", "300")
from gi.repository import GtkSource

from gedit_lsp.features.mouse_hover import _iters_from_lsp_range, _word_bounds_at


def _buffer_with(text: str) -> GtkSource.Buffer:
    buf = GtkSource.Buffer()
    buf.set_text(text)
    return buf


def test_iters_from_lsp_range_single_line() -> None:
    buf = _buffer_with("hello world\n")
    rng = {
        "start": {"line": 0, "character": 6},
        "end":   {"line": 0, "character": 11},
    }
    start, end = _iters_from_lsp_range(buf, rng)
    assert start.get_line() == 0 and start.get_line_offset() == 6
    assert end.get_line() == 0 and end.get_line_offset() == 11
    assert buf.get_text(start, end, False) == "world"


def test_iters_from_lsp_range_multi_byte_utf8() -> None:
    # "α" is one codepoint, one UTF-16 unit, two UTF-8 bytes.
    buf = _buffer_with("αβγ\n")
    rng = {
        "start": {"line": 0, "character": 1},
        "end":   {"line": 0, "character": 2},
    }
    start, end = _iters_from_lsp_range(buf, rng)
    assert buf.get_text(start, end, False) == "β"


def test_word_bounds_at_mid_word() -> None:
    buf = _buffer_with("hello world\n")
    cursor = buf.get_iter_at_line_offset(0, 8)  # inside "world"
    start, end = _word_bounds_at(cursor)
    assert buf.get_text(start, end, False) == "world"


def test_word_bounds_at_on_whitespace_returns_single_char_range() -> None:
    buf = _buffer_with("hello world\n")
    cursor = buf.get_iter_at_line_offset(0, 5)  # the space
    start, end = _word_bounds_at(cursor)
    # Falls back: one-character range starting at the iter.
    assert end.get_offset() - start.get_offset() == 1


def test_word_bounds_at_start_of_buffer() -> None:
    buf = _buffer_with("hello\n")
    cursor = buf.get_iter_at_line_offset(0, 0)
    start, end = _word_bounds_at(cursor)
    assert buf.get_text(start, end, False) == "hello"
