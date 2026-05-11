"""Tests for the pure codeAction helpers."""
from __future__ import annotations

from gedit_lsp.code_action import (
    extract_diag_context,
    group_by_kind,
    needs_resolve,
    normalize_action,
)


def test_normalize_command_shape() -> None:
    # Legacy LSP `Command` shape: title + command name + arguments
    raw = {
        "title": "Apply suggestion",
        "command": "ruff.applySuggestion",
        "arguments": [{"uri": "file:///a.py"}],
    }
    result = normalize_action(raw)
    assert result is not None
    assert result["title"] == "Apply suggestion"
    assert result["kind"] == ""
    assert result["edit"] is None
    assert result["command"] == {
        "title": "Apply suggestion",
        "command": "ruff.applySuggestion",
        "arguments": [{"uri": "file:///a.py"}],
    }
    assert result["data"] is None
    assert result["is_preferred"] is False
    assert result["disabled_reason"] is None


def test_normalize_code_action_full() -> None:
    raw = {
        "title": "Extract method",
        "kind": "refactor.extract",
        "edit": {"documentChanges": []},
        "isPreferred": True,
    }
    result = normalize_action(raw)
    assert result is not None
    assert result["title"] == "Extract method"
    assert result["kind"] == "refactor.extract"
    assert result["edit"] == {"documentChanges": []}
    assert result["command"] is None
    assert result["is_preferred"] is True
    assert result["disabled_reason"] is None


def test_normalize_code_action_with_command_dict() -> None:
    raw = {
        "title": "Organize imports",
        "kind": "source.organizeImports",
        "command": {
            "title": "Organize imports",
            "command": "pylsp.organizeImports",
            "arguments": [],
        },
    }
    result = normalize_action(raw)
    assert result is not None
    assert result["edit"] is None
    assert result["command"] == {
        "title": "Organize imports",
        "command": "pylsp.organizeImports",
        "arguments": [],
    }


def test_normalize_code_action_disabled() -> None:
    raw = {
        "title": "Inline variable",
        "kind": "refactor.inline",
        "data": {"id": "x"},
        "disabled": {"reason": "Selection contains side effects"},
    }
    result = normalize_action(raw)
    assert result is not None
    assert result["disabled_reason"] == "Selection contains side effects"


def test_normalize_missing_title_returns_none() -> None:
    assert normalize_action({"command": "do.thing"}) is None
    assert normalize_action({"title": None}) is None


def test_normalize_no_edit_no_command_no_data_returns_none() -> None:
    # Action with only a title and kind — nothing to execute.
    raw = {"title": "Nope", "kind": "refactor"}
    assert normalize_action(raw) is None


def test_normalize_resolve_needed_action_keeps_data() -> None:
    # Server sends a stub with just title/kind/data — resolve will
    # populate the rest. We keep the data field so resolve can use it.
    raw = {"title": "Stub", "kind": "quickfix", "data": {"id": "fix-1"}}
    result = normalize_action(raw)
    assert result is not None
    assert result["data"] == {"id": "fix-1"}


def test_normalize_non_dict_returns_none() -> None:
    assert normalize_action("not a dict") is None
    assert normalize_action(None) is None
    assert normalize_action(42) is None


def _action(title: str, kind: str) -> dict:
    """Return a minimal NormalizedAction-shape dict for grouping tests."""
    return {
        "title": title,
        "kind": kind,
        "edit": {},
        "command": None,
        "data": None,
        "is_preferred": False,
        "disabled_reason": None,
    }


def test_group_by_kind_orders_quickfix_refactor_source() -> None:
    actions = [
        _action("organize", "source.organizeImports"),
        _action("extract", "refactor.extract"),
        _action("fix", "quickfix"),
    ]
    result = group_by_kind(actions)
    # Expected order: quickfix → refactor.* → source.* → unknown
    assert [g for g, _ in result] == ["quickfix", "refactor", "source"]


def test_group_by_kind_preserves_within_group_order() -> None:
    actions = [
        _action("fix-a", "quickfix"),
        _action("fix-b", "quickfix"),
        _action("fix-c", "quickfix"),
    ]
    result = group_by_kind(actions)
    assert len(result) == 1
    titles = [a["title"] for a in result[0][1]]
    assert titles == ["fix-a", "fix-b", "fix-c"]


def test_group_by_kind_unknown_bucketed_last() -> None:
    actions = [
        _action("???", "vendor.custom"),
        _action("fix", "quickfix"),
        _action("", ""),
    ]
    result = group_by_kind(actions)
    group_names = [g for g, _ in result]
    assert group_names[0] == "quickfix"
    assert "unknown" in group_names
    assert group_names[-1] == "unknown"


def test_needs_resolve_with_edit_returns_false() -> None:
    a = _action("a", "quickfix")
    a["edit"] = {"changes": {}}
    assert needs_resolve(a) is False  # type: ignore[arg-type]


def test_needs_resolve_with_command_returns_false() -> None:
    a = _action("a", "quickfix")
    a["edit"] = None
    a["command"] = {"command": "x", "title": "x", "arguments": []}
    assert needs_resolve(a) is False  # type: ignore[arg-type]


def test_needs_resolve_with_neither_returns_true() -> None:
    a = _action("a", "quickfix")
    a["edit"] = None
    a["command"] = None
    a["data"] = {"id": 1}
    assert needs_resolve(a) is True  # type: ignore[arg-type]


def test_extract_diag_context_cursor_inside_range() -> None:
    diagnostics = [
        {
            "range": {
                "start": {"line": 5, "character": 4},
                "end":   {"line": 5, "character": 10},
            },
            "message": "unused import",
        },
    ]
    # Cursor at (5, 7) — inside the range
    assert extract_diag_context(diagnostics, 5, 7) == diagnostics


def test_extract_diag_context_cursor_on_start_boundary() -> None:
    diagnostics = [
        {"range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 4}}},
    ]
    # Cursor exactly on start — included (per LSP overlap semantics)
    assert extract_diag_context(diagnostics, 0, 0) == diagnostics


def test_extract_diag_context_range_fully_before_cursor() -> None:
    diagnostics = [
        {"range": {"start": {"line": 2, "character": 0},
                   "end":   {"line": 2, "character": 5}}},
    ]
    # Cursor at (2, 10) — after the range end
    assert extract_diag_context(diagnostics, 2, 10) == []


def test_extract_diag_context_range_fully_after_cursor() -> None:
    diagnostics = [
        {"range": {"start": {"line": 5, "character": 0},
                   "end":   {"line": 5, "character": 4}}},
    ]
    # Cursor at (4, 99) — before the range start
    assert extract_diag_context(diagnostics, 4, 99) == []


def test_extract_diag_context_multiline_range() -> None:
    diagnostics = [
        {"range": {"start": {"line": 5, "character": 10},
                   "end":   {"line": 7, "character": 2}}},
    ]
    # Cursor on line 6 — inside multi-line range
    assert extract_diag_context(diagnostics, 6, 0) == diagnostics


def test_extract_diag_context_filters_mixed() -> None:
    diagnostics = [
        {"range": {"start": {"line": 1, "character": 0},
                   "end":   {"line": 1, "character": 4}}, "id": "before"},
        {"range": {"start": {"line": 5, "character": 0},
                   "end":   {"line": 5, "character": 10}}, "id": "match"},
        {"range": {"start": {"line": 9, "character": 0},
                   "end":   {"line": 9, "character": 4}}, "id": "after"},
    ]
    # Cursor at (5, 5)
    result = extract_diag_context(diagnostics, 5, 5)
    assert len(result) == 1
    assert result[0]["id"] == "match"


def test_extract_diag_context_empty_input() -> None:
    assert extract_diag_context([], 0, 0) == []
