"""Tests for the LSP UTF-16 ↔ Gtk.TextIter converter.

These functions are the single highest-risk module in the plugin. A one-off
bug here turns into "go-to-definition jumps to the wrong line on files with
emoji or CJK" much later.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from hypothesis import given, settings, strategies as st
import pytest

from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter


def _buffer(text: str) -> Gtk.TextBuffer:
    buf = Gtk.TextBuffer()
    buf.set_text(text)
    return buf


@pytest.mark.parametrize(
    "text, line, char_utf16, expected_offset",
    [
        # Plain ASCII
        ("hello world", 0, 0, 0),
        ("hello world", 0, 5, 5),
        ("hello world", 0, 11, 11),
        # BMP characters (each = 1 UTF-16 code unit, but >1 byte in UTF-8)
        ("héllo", 0, 1, 1),
        ("héllo", 0, 2, 2),
        # Surrogate pair characters (1 codepoint = 2 UTF-16 code units)
        ("a🐍b", 0, 0, 0),
        ("a🐍b", 0, 1, 1),  # before snake
        ("a🐍b", 0, 3, 2),  # after snake (snake = 2 UTF-16 units)
        ("a🐍b", 0, 4, 3),  # after b
        # Multi-line
        ("line0\nline1\nline2", 1, 3, 3),
        ("line0\nline1\nline2", 2, 5, 5),
    ],
)
def test_utf16_to_text_iter_known_positions(
    text: str, line: int, char_utf16: int, expected_offset: int
) -> None:
    buf = _buffer(text)
    it = utf16_to_text_iter(buf, line, char_utf16)
    assert it.get_line() == line
    assert it.get_line_offset() == expected_offset


@pytest.mark.parametrize(
    "text, line, line_offset, expected_utf16",
    [
        ("hello", 0, 5, 5),
        ("héllo", 0, 5, 5),
        ("a🐍b", 0, 0, 0),
        ("a🐍b", 0, 1, 1),
        ("a🐍b", 0, 2, 3),  # after snake
        ("a🐍b", 0, 3, 4),
        ("line0\nline1", 1, 5, 5),
    ],
)
def test_text_iter_to_utf16_known_positions(
    text: str, line: int, line_offset: int, expected_utf16: int
) -> None:
    buf = _buffer(text)
    it = buf.get_iter_at_line_offset(line, line_offset)
    got_line, got_char = text_iter_to_utf16(it)
    assert got_line == line
    assert got_char == expected_utf16


def test_empty_buffer_position_zero() -> None:
    buf = _buffer("")
    it = utf16_to_text_iter(buf, 0, 0)
    assert it.get_line() == 0
    assert it.get_line_offset() == 0


def test_end_of_line_position() -> None:
    buf = _buffer("hello\nworld")
    it = utf16_to_text_iter(buf, 0, 5)
    assert it.get_line() == 0
    assert it.get_line_offset() == 5


@given(
    text=st.text(
        alphabet=st.characters(
            blacklist_categories=("Cs",),  # exclude lone surrogates
            blacklist_characters="\n\r",
        ),
        min_size=0,
        max_size=200,
    ),
    pos=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=500, deadline=None)
def test_round_trip_iter_to_utf16_and_back(text: str, pos: int) -> None:
    """For any single-line text and any valid offset, round-tripping is identity."""
    buf = _buffer(text)
    pos = min(pos, len(text))
    original_iter = buf.get_iter_at_line_offset(0, pos)
    line, char_utf16 = text_iter_to_utf16(original_iter)
    round_tripped = utf16_to_text_iter(buf, line, char_utf16)
    assert round_tripped.get_line() == original_iter.get_line()
    assert round_tripped.get_line_offset() == original_iter.get_line_offset()


def test_surrogate_pair_alone_on_line() -> None:
    """A line containing only a surrogate-pair char must convert correctly at both ends."""
    buf = _buffer("🐍")
    start = utf16_to_text_iter(buf, 0, 0)
    end = utf16_to_text_iter(buf, 0, 2)  # snake = 2 UTF-16 units
    assert start.get_line_offset() == 0
    assert end.get_line_offset() == 1  # 1 codepoint
