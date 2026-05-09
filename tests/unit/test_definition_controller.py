"""Unit tests for the CursorHistory helper used by DefinitionController.

The 0/1/N classifier (`classify_locations`) was relocated to
`gedit_lsp.navigation` in the v0.4.0 cycle so references and definition
share it; its tests now live in `test_navigation.py`. This file keeps
only the history-stack tests, which remain definition-specific.
"""
from __future__ import annotations

from gedit_lsp.features.definition import CursorHistory


def test_cursor_history_push_pop() -> None:
    h = CursorHistory(max_entries=3)
    h.push(("file:///a", 1, 1))
    h.push(("file:///b", 2, 2))
    assert h.pop() == ("file:///b", 2, 2)
    assert h.pop() == ("file:///a", 1, 1)
    assert h.pop() is None


def test_cursor_history_drops_oldest_when_full() -> None:
    h = CursorHistory(max_entries=2)
    h.push(("file:///a", 1, 1))
    h.push(("file:///b", 2, 2))
    h.push(("file:///c", 3, 3))
    assert h.pop() == ("file:///c", 3, 3)
    assert h.pop() == ("file:///b", 2, 2)
    assert h.pop() is None  # 'a' was dropped
