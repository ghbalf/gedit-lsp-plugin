"""Unit tests for DefinitionController helpers — handles 0/1/N location responses."""
from __future__ import annotations

from gedit_lsp.features.definition import (
    CursorHistory,
    classify_locations,
)


def test_classify_no_locations() -> None:
    assert classify_locations(None) == ("none", [])
    assert classify_locations([]) == ("none", [])


def test_classify_single_location() -> None:
    loc = {
        "uri": "file:///x.py",
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 3},
        },
    }
    kind, locs = classify_locations(loc)
    assert kind == "single"
    assert locs == [loc]


def test_classify_array_with_one() -> None:
    loc = {
        "uri": "file:///x.py",
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 3},
        },
    }
    kind, _locs = classify_locations([loc])
    assert kind == "single"


def test_classify_array_with_many() -> None:
    locs = [
        {
            "uri": "file:///x.py",
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 3},
            },
        },
        {
            "uri": "file:///y.py",
            "range": {
                "start": {"line": 5, "character": 0},
                "end": {"line": 5, "character": 3},
            },
        },
    ]
    kind, got = classify_locations(locs)
    assert kind == "many"
    assert got == locs


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
