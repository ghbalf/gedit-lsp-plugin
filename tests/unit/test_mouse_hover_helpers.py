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


def test_word_bounds_at_on_interior_whitespace_returns_single_char_range() -> None:
    # Two spaces between "a" and "b"; cursor at offset 2 is on the SECOND space,
    # which has inside_word() == False, ends_word() == False (no word just ended
    # there), starts_word() == False. True interior whitespace — falls back.
    buf = _buffer_with("a  b\n")
    cursor = buf.get_iter_at_line_offset(0, 2)
    start, end = _word_bounds_at(cursor)
    assert end.get_offset() - start.get_offset() == 1


def test_word_bounds_at_start_of_buffer() -> None:
    buf = _buffer_with("hello\n")
    cursor = buf.get_iter_at_line_offset(0, 0)
    start, end = _word_bounds_at(cursor)
    assert buf.get_text(start, end, False) == "hello"


def test_word_bounds_at_trailing_edge_of_word_expands_to_word() -> None:
    # Offset 5 of "hello world" is between 'o' and ' ': ends_word()==True for "hello".
    # With the original (and correct) guard, the cursor at a word-boundary
    # iter should expand to the word that just ended.
    buf = _buffer_with("hello world\n")
    cursor = buf.get_iter_at_line_offset(0, 5)
    start, end = _word_bounds_at(cursor)
    assert buf.get_text(start, end, False) == "hello"


def test_word_bounds_at_trailing_edge_before_newline_expands_to_word() -> None:
    # Offset 11 of "hello world\n" is between 'd' and '\n': ends_word()==True.
    # Should anchor to "world", not to the newline.
    buf = _buffer_with("hello world\n")
    cursor = buf.get_iter_at_line_offset(0, 11)
    start, end = _word_bounds_at(cursor)
    assert buf.get_text(start, end, False) == "world"
