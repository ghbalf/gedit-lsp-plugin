"""Unit tests for the workspace_edit module.

Covers two helpers:
  * apply_workspace_edit — walks WorkspaceEdit (preferring documentChanges
    over the older `changes` map), per-file delegates to apply_text_edits.
  * derive_placeholder — regex-based identifier extraction at a cursor
    position; the prepareRename fallback for servers that don't (or won't)
    return a placeholder.

No real GTK widgets; buffers are GtkSource.Buffer model objects (safe in
headless CI per the project-memory invariant) or MagicMocks.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import GtkSource  # type: ignore[attr-defined]

from gedit_lsp.workspace_edit import (
    apply_workspace_edit,
    derive_placeholder,
)


# --- derive_placeholder ----------------------------------------------


def _buf(text: str) -> GtkSource.Buffer:
    buf = GtkSource.Buffer()
    buf.set_text(text, -1)
    return buf


def test_derive_placeholder_returns_identifier_at_cursor() -> None:
    buf = _buf("foo = bar(baz)\n")
    # cursor inside "bar"
    assert derive_placeholder(buf, 0, 7) == "bar"
    # cursor on the leading 'f' of "foo"
    assert derive_placeholder(buf, 0, 0) == "foo"
    # cursor on the closing paren — between identifiers
    assert derive_placeholder(buf, 0, 13) == ""


def test_derive_placeholder_supports_underscored_identifiers() -> None:
    buf = _buf("    _private_var = 1\n")
    assert derive_placeholder(buf, 0, 8) == "_private_var"


def test_derive_placeholder_returns_empty_on_whitespace_or_punctuation() -> None:
    buf = _buf("a = b\n")
    # cursor on the space between 'a' and '='
    assert derive_placeholder(buf, 0, 1) == ""
    # cursor on the '='
    assert derive_placeholder(buf, 0, 2) == ""


def test_derive_placeholder_returns_empty_on_out_of_range_line() -> None:
    buf = _buf("only line\n")
    assert derive_placeholder(buf, 99, 0) == ""
    assert derive_placeholder(buf, -1, 0) == ""


def test_derive_placeholder_works_on_last_line_without_newline() -> None:
    buf = _buf("first\nsecond")  # no trailing newline
    assert derive_placeholder(buf, 1, 0) == "second"


def test_derive_placeholder_cursor_one_past_end_of_identifier() -> None:
    # `bar` spans [6, 9); cursor at 9 is on the `(` after the token,
    # not on the token. m.end() exclusive matches Python re conventions
    # and the user's mental model: "cursor on '(' shouldn't rename `bar`".
    buf = _buf("foo = bar(baz)\n")
    assert derive_placeholder(buf, 0, 9) == ""


# --- apply_workspace_edit: documentChanges precedence -------------


def test_documentChanges_preferred_over_changes() -> None:
    # If both shapes are present, documentChanges wins.
    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///a.py", "version": 7},
                "edits": [{"range": {
                    "start": {"line": 0, "character": 0},
                    "end":   {"line": 0, "character": 3},
                }, "newText": "NEW"}],
            },
        ],
        "changes": {
            "file:///b.py": [{"range": {
                "start": {"line": 0, "character": 0},
                "end":   {"line": 0, "character": 3},
            }, "newText": "OTHER"}],
        },
    }
    seen: list[str] = []

    def buffer_for_uri(uri: str) -> Any:
        seen.append(uri)
        b = MagicMock()
        return b

    applied, failed = apply_workspace_edit(edit, buffer_for_uri=buffer_for_uri)
    assert applied == ["file:///a.py"]
    assert failed == []
    assert seen == ["file:///a.py"]  # changes map ignored


def test_changes_fallback_when_no_documentChanges() -> None:
    edit = {
        "changes": {
            "file:///a.py": [{"range": {
                "start": {"line": 0, "character": 0},
                "end":   {"line": 0, "character": 3},
            }, "newText": "X"}],
            "file:///b.py": [{"range": {
                "start": {"line": 1, "character": 0},
                "end":   {"line": 1, "character": 3},
            }, "newText": "Y"}],
        }
    }
    seen: list[str] = []

    def buffer_for_uri(uri: str) -> Any:
        seen.append(uri)
        return MagicMock()

    applied, failed = apply_workspace_edit(edit, buffer_for_uri=buffer_for_uri)
    assert sorted(applied) == ["file:///a.py", "file:///b.py"]
    assert failed == []
    assert sorted(seen) == ["file:///a.py", "file:///b.py"]


# --- apply_workspace_edit: per-file failure isolation -------------


def test_uri_not_found_in_lookup_goes_to_failed() -> None:
    edit = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"},
             "edits": [{"range": {
                 "start": {"line": 0, "character": 0},
                 "end":   {"line": 0, "character": 1},
             }, "newText": "X"}]},
            {"textDocument": {"uri": "file:///missing.py"},
             "edits": [{"range": {
                 "start": {"line": 0, "character": 0},
                 "end":   {"line": 0, "character": 1},
             }, "newText": "Y"}]},
        ],
    }

    def buffer_for_uri(uri: str) -> Any:
        return MagicMock() if uri == "file:///a.py" else None

    applied, failed = apply_workspace_edit(edit, buffer_for_uri=buffer_for_uri)
    assert applied == ["file:///a.py"]
    assert failed == ["file:///missing.py"]


def test_apply_text_edits_exception_routes_uri_to_failed(monkeypatch: Any) -> None:
    def fake_apply(buffer: Any, edits: Any) -> None:
        raise RuntimeError("simulated server-range corruption")

    monkeypatch.setattr(
        "gedit_lsp.workspace_edit.apply_text_edits", fake_apply,
    )

    edit = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"},
             "edits": [{"range": {
                 "start": {"line": 0, "character": 0},
                 "end":   {"line": 0, "character": 1},
             }, "newText": "X"}]},
        ],
    }
    applied, failed = apply_workspace_edit(
        edit, buffer_for_uri=lambda _u: MagicMock(),
    )
    assert applied == []
    assert failed == ["file:///a.py"]


# --- apply_workspace_edit: empty / malformed edge cases ----------


def test_empty_workspace_edit_returns_empty_lists() -> None:
    applied, failed = apply_workspace_edit(
        {}, buffer_for_uri=lambda _u: MagicMock(),
    )
    assert applied == []
    assert failed == []


def test_non_dict_edit_returns_empty_lists() -> None:
    applied, failed = apply_workspace_edit(
        None, buffer_for_uri=lambda _u: MagicMock(),  # type: ignore[arg-type]
    )
    assert applied == []
    assert failed == []


def test_documentChanges_with_malformed_entries_skipped() -> None:
    edit = {
        "documentChanges": [
            "not a dict",  # type: ignore[list-item]
            {"missing": "textDocument"},
            {"textDocument": "not a dict"},
            {"textDocument": {"uri": 42}, "edits": []},  # uri not str
            {"textDocument": {"uri": "file:///a.py"}, "edits": "not a list"},
            {"textDocument": {"uri": "file:///b.py"},
             "edits": [{"range": {
                 "start": {"line": 0, "character": 0},
                 "end":   {"line": 0, "character": 1},
             }, "newText": "X"}]},
        ],
    }
    applied, failed = apply_workspace_edit(
        edit, buffer_for_uri=lambda _u: MagicMock(),
    )
    assert applied == ["file:///b.py"]
    assert failed == []


# --- apply_workspace_edit: per-file edit isolation ---------------


def test_per_file_edits_handed_through_unchanged(monkeypatch: Any) -> None:
    captured: list[tuple[str, list[Any]]] = []

    def fake_apply(buffer: Any, edits: list[Any]) -> None:
        # buffer is uniquely tagged per uri so we can verify isolation.
        captured.append((buffer.tag, edits))

    monkeypatch.setattr(
        "gedit_lsp.workspace_edit.apply_text_edits", fake_apply,
    )

    a_edits = [{"range": {"start": {"line": 0, "character": 0},
                          "end":   {"line": 0, "character": 1}}, "newText": "A"}]
    b_edits = [{"range": {"start": {"line": 1, "character": 0},
                          "end":   {"line": 1, "character": 1}}, "newText": "B"}]
    edit = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": a_edits},
            {"textDocument": {"uri": "file:///b.py"}, "edits": b_edits},
        ],
    }

    def buffer_for_uri(uri: str) -> Any:
        m = MagicMock()
        m.tag = uri
        return m

    apply_workspace_edit(edit, buffer_for_uri=buffer_for_uri)
    assert ("file:///a.py", a_edits) in captured
    assert ("file:///b.py", b_edits) in captured
    # No cross-contamination
    a_call = next(c for c in captured if c[0] == "file:///a.py")
    assert a_call[1] is a_edits
