"""LSP UTF-16 position ↔ Gtk.TextIter conversion.

LSP `Position` is `(line, character)` where `character` is a UTF-16 code-unit
offset within the line. `Gtk.TextIter` works in codepoints (Python `str`
indexing), so a converter is needed at every protocol boundary.

This module is pure: no GTK widgets, no signals, no side effects. It is
exercised by property-based tests and is the highest-risk module in the
plugin — every controller goes through these two functions, never anything
else.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


def _line_end_iter(start_of_line: Gtk.TextIter) -> Gtk.TextIter:
    """Return an iter at the end of the line that `start_of_line` belongs to."""
    end = start_of_line.copy()
    if not end.ends_line():
        end.forward_to_line_end()
    return end


def utf16_to_text_iter(
    buffer: Gtk.TextBuffer, line: int, char_utf16: int
) -> Gtk.TextIter:
    """Convert an LSP `(line, character)` to a `Gtk.TextIter`.

    `character` is interpreted as a UTF-16 code-unit offset.
    """
    line_iter: Gtk.TextIter = buffer.get_iter_at_line(line)  # type: ignore[assignment]
    line_text: str = buffer.get_text(line_iter, _line_end_iter(line_iter), False)

    units = 0
    cp_offset = 0
    for ch in line_text:
        if units >= char_utf16:
            break
        units += 1 if ord(ch) < 0x10000 else 2
        cp_offset += 1

    return buffer.get_iter_at_line_offset(line, cp_offset)  # type: ignore[return-value]


def text_iter_to_utf16(it: Gtk.TextIter) -> tuple[int, int]:
    """Convert a `Gtk.TextIter` to LSP `(line, character_utf16)`."""
    line = it.get_line()
    line_start: Gtk.TextIter = it.get_buffer().get_iter_at_line(line)  # type: ignore[assignment]
    line_text: str = it.get_buffer().get_text(line_start, it, False)
    units = sum(1 if ord(ch) < 0x10000 else 2 for ch in line_text)
    return line, units
