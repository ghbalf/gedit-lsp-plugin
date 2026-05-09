"""Unit tests for DefinitionController helpers — handles 0/1/N location responses."""
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
