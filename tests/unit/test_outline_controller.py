"""Unit tests for outline tree-building.

These pin down the conversion from LSP `DocumentSymbol[]` (or the legacy
`SymbolInformation[]`) to a flat tree-row structure suitable for
Gtk.TreeStore.
"""
from __future__ import annotations

from gedit_lsp.features.outline import (
    build_tree,
    detect_response_format,
)


def test_detect_hierarchical() -> None:
    assert detect_response_format([{"name": "x", "kind": 12, "range": {}, "selectionRange": {}}]) == "hierarchical"


def test_detect_flat_via_location_field() -> None:
    assert detect_response_format([{"name": "x", "kind": 12, "location": {"uri": "...", "range": {}}}]) == "flat"


def test_detect_empty() -> None:
    assert detect_response_format([]) == "hierarchical"  # default


def test_build_tree_hierarchical() -> None:
    items = [
        {
            "name": "Greeter", "kind": 5,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 5, "character": 0}},
            "selectionRange": {"start": {"line": 0, "character": 6}, "end": {"line": 0, "character": 13}},
            "children": [
                {
                    "name": "hello", "kind": 6,
                    "range": {"start": {"line": 1, "character": 4}, "end": {"line": 2, "character": 16}},
                    "selectionRange": {"start": {"line": 1, "character": 8}, "end": {"line": 1, "character": 13}},
                },
                {
                    "name": "goodbye", "kind": 6,
                    "range": {"start": {"line": 4, "character": 4}, "end": {"line": 5, "character": 16}},
                    "selectionRange": {"start": {"line": 4, "character": 8}, "end": {"line": 4, "character": 15}},
                },
            ],
        }
    ]
    tree = build_tree(items, "hierarchical")
    assert len(tree) == 1
    assert tree[0].name == "Greeter"
    assert [c.name for c in tree[0].children] == ["hello", "goodbye"]


def test_build_tree_flat() -> None:
    items = [
        {"name": "Greeter", "kind": 5, "location": {"uri": "x", "range": {"start": {"line": 0, "character": 0}, "end": {"line": 5, "character": 0}}}, "containerName": None},
        {"name": "hello", "kind": 6, "location": {"uri": "x", "range": {"start": {"line": 1, "character": 8}, "end": {"line": 1, "character": 13}}}, "containerName": "Greeter"},
        {"name": "goodbye", "kind": 6, "location": {"uri": "x", "range": {"start": {"line": 4, "character": 8}, "end": {"line": 4, "character": 15}}}, "containerName": "Greeter"},
    ]
    tree = build_tree(items, "flat")
    assert len(tree) == 1
    assert tree[0].name == "Greeter"
    assert {c.name for c in tree[0].children} == {"hello", "goodbye"}
