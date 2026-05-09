"""Unit tests for ReferencesPanel + its pure preview/uri helpers.

Constructor is bypassed via __new__ because real construction needs a
Gedit.Window and the corresponding bottom panel, which are unavailable
in unit tests. The row-manipulation methods only touch `self._store`,
so we exercise them on a freshly-built ListStore. The pure helpers
(`_basename_for_uri`, `fetch_preview_line`) are tested directly at
module level, no panel needed.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # type: ignore[attr-defined]

from gedit_lsp.ui.references_panel import (
    ReferencesPanel,
    _basename_for_uri,
    fetch_preview_line,
)


def _panel_with_rows(rows: list[list[Any]]) -> ReferencesPanel:
    panel = ReferencesPanel.__new__(ReferencesPanel)
    panel._window = MagicMock()
    panel._store = Gtk.ListStore(str, int, str, str, int)  # type: ignore[call-arg]
    for r in rows:
        panel._store.append(r)
    return panel


# --- _basename_for_uri ------------------------------------------------


def test_basename_for_uri_extracts_final_path_segment() -> None:
    assert _basename_for_uri("file:///home/u/a.py") == "a.py"
    assert _basename_for_uri("file:///x/y/z/__init__.py") == "__init__.py"


def test_basename_for_uri_falls_back_to_full_uri_on_no_separator() -> None:
    # Defensive: malformed URIs without a `/` still produce a non-empty label.
    assert _basename_for_uri("untitled") == "untitled"


# --- fetch_preview_line: open-buffer fast path -----------------------


class _FakeBuffer:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def get_iter_at_line(self, line: int) -> str:
        return f"@{line}"

    def get_line_count(self) -> int:
        return len(self._lines)

    def get_text(self, start: str, _end: str, _include_hidden: bool) -> str:
        # `start` is `@N`, return that line's text.
        n = int(str(start).lstrip("@"))
        if 0 <= n < len(self._lines):
            return self._lines[n]
        return ""

    def get_end_iter(self) -> str:
        return f"@{len(self._lines)}"

    def get_file(self) -> Any:
        class _F:
            def get_location(_self) -> Any:
                class _L:
                    def get_uri(__self) -> str:
                        return "file:///open.py"
                return _L()
        return _F()


class _FakeWindow:
    def __init__(self, docs: list[Any]) -> None:
        self._docs = docs

    def get_documents(self) -> list[Any]:
        return self._docs


def test_preview_from_open_buffer_uses_buffer_text() -> None:
    buf = _FakeBuffer(["line zero", "line one  ", "    line two with leading ws"])
    window = _FakeWindow([buf])
    assert fetch_preview_line("file:///open.py", 0, window) == "line zero"
    assert fetch_preview_line("file:///open.py", 1, window) == "line one  "
    # lstrip applies — verify
    assert fetch_preview_line("file:///open.py", 2, window) == "line two with leading ws"


def test_preview_from_open_buffer_returns_empty_on_out_of_range() -> None:
    buf = _FakeBuffer(["only line"])
    window = _FakeWindow([buf])
    assert fetch_preview_line("file:///open.py", 99, window) == ""


# --- fetch_preview_line: disk fallback -------------------------------


def test_preview_from_disk_when_no_open_buffer(tmp_path: Any) -> None:
    f = tmp_path / "a.py"
    f.write_text("zero\n  one\ntwo\n", encoding="utf-8")
    window = _FakeWindow([])  # no open buffers
    uri = f"file://{f}"
    assert fetch_preview_line(uri, 0, window) == "zero"
    assert fetch_preview_line(uri, 1, window) == "one"  # lstrip
    assert fetch_preview_line(uri, 2, window) == "two"


def test_preview_from_disk_returns_empty_on_out_of_range(tmp_path: Any) -> None:
    f = tmp_path / "a.py"
    f.write_text("zero\n", encoding="utf-8")
    window = _FakeWindow([])
    assert fetch_preview_line(f"file://{f}", 99, window) == ""


def test_preview_from_disk_returns_empty_on_unreadable_file(tmp_path: Any) -> None:
    window = _FakeWindow([])
    # File doesn't exist — Path.read_text raises FileNotFoundError.
    assert fetch_preview_line(
        f"file://{tmp_path}/never-created.py", 0, window
    ) == ""


def test_preview_truncates_long_lines() -> None:
    long = "x" * 200
    buf = _FakeBuffer([long])
    window = _FakeWindow([buf])
    out = fetch_preview_line("file:///open.py", 0, window)
    assert len(out) <= 121  # 120 chars + ellipsis
    assert out.endswith("…")


# --- panel: store mutation --------------------------------------------


def test_set_results_empty_clears_store() -> None:
    panel = _panel_with_rows([
        ["a.py", 1, "preview", "file:///a.py", 0],
    ])
    panel.set_results([])
    assert list(panel._store) == []


def test_set_results_populates_in_order() -> None:
    panel = _panel_with_rows([])
    panel._window = _FakeWindow([])  # disk-fallback path; will return ""
    panel.set_results([
        {"uri": "file:///a.py",
         "range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 3}}},
        {"uri": "file:///b.py",
         "range": {"start": {"line": 9, "character": 4},
                   "end":   {"line": 9, "character": 7}}},
    ])
    rows = list(panel._store)
    assert len(rows) == 2
    assert rows[0][0] == "a.py"
    assert rows[0][1] == 1   # 1-based display
    assert rows[0][3] == "file:///a.py"
    assert rows[0][4] == 0
    assert rows[1][0] == "b.py"
    assert rows[1][1] == 10
    assert rows[1][3] == "file:///b.py"
    assert rows[1][4] == 4


def test_set_results_clears_prior_results() -> None:
    panel = _panel_with_rows([
        ["old.py", 1, "stale", "file:///old.py", 0],
    ])
    panel._window = _FakeWindow([])
    panel.set_results([
        {"uri": "file:///new.py",
         "range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 0}}},
    ])
    rows = list(panel._store)
    assert len(rows) == 1
    assert rows[0][3] == "file:///new.py"


def test_clear_empties_store() -> None:
    panel = _panel_with_rows([
        ["a.py", 1, "preview", "file:///a.py", 0],
        ["b.py", 2, "preview", "file:///b.py", 0],
    ])
    panel.clear()
    assert list(panel._store) == []
