"""Unit tests for DiagnosticsPanel row manipulation.

Constructor is bypassed via __new__ because real construction needs a
Gedit.Window and the corresponding bottom panel, which are unavailable
in unit tests. The row-manipulation methods only touch `self._store`,
so we can exercise them on a freshly-built ListStore.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # type: ignore[attr-defined]

from gedit_lsp.ui.diagnostics_panel import DiagnosticsPanel, _uri_basename


def _panel_with_rows(rows: list[list]) -> DiagnosticsPanel:
    panel = DiagnosticsPanel.__new__(DiagnosticsPanel)
    # cols: severity, file, line, message, source, uri
    panel._store = Gtk.ListStore(str, str, int, str, str, str)  # type: ignore[call-arg]
    for r in rows:
        panel._store.append(r)
    return panel


def _row_uris(panel: DiagnosticsPanel) -> list[str]:
    return [row[5] for row in panel._store]


def test_clear_for_uri_drops_only_matching_rows() -> None:
    panel = _panel_with_rows([
        ["Error",   "a.py", 1, "py error",   "pyflakes", "file:///a.py"],
        ["Warning", "b.c",  2, "c warn",     "clang",    "file:///b.c"],
        ["Error",   "a.py", 3, "py error 2", "pyflakes", "file:///a.py"],
        ["Info",    "b.c",  4, "c info",     "clang",    "file:///b.c"],
    ])
    panel.clear_for_uri("file:///a.py")
    assert _row_uris(panel) == ["file:///b.c", "file:///b.c"]


def test_clear_for_uri_no_matches_is_noop() -> None:
    panel = _panel_with_rows([
        ["Error", "a.py", 1, "msg", "src", "file:///a.py"],
    ])
    panel.clear_for_uri("file:///never-listed.rs")
    assert _row_uris(panel) == ["file:///a.py"]


def test_clear_for_uri_empty_panel_is_noop() -> None:
    panel = _panel_with_rows([])
    panel.clear_for_uri("file:///anything.c")
    assert _row_uris(panel) == []


def test_update_for_uri_replaces_existing_rows_for_that_uri() -> None:
    panel = _panel_with_rows([
        ["Error", "a.py", 1, "old1", "src", "file:///a.py"],
        ["Error", "a.py", 2, "old2", "src", "file:///a.py"],
        ["Error", "b.c",  3, "keep", "src", "file:///b.c"],
    ])
    panel.update_for_uri(
        "file:///a.py",
        [
            {
                "severity": 2,
                "range": {"start": {"line": 9, "character": 0},
                          "end":   {"line": 9, "character": 1}},
                "message": "new1",
                "source":  "src",
            }
        ],
    )
    rows = list(panel._store)
    assert len(rows) == 2
    assert {r[5] for r in rows} == {"file:///a.py", "file:///b.c"}
    a_row = next(r for r in rows if r[5] == "file:///a.py")
    assert a_row[0] == "Warning"
    assert a_row[1] == "a.py"   # File column shows the basename
    assert a_row[2] == 10        # 1-based line
    assert a_row[3] == "new1"


def test_update_for_uri_populates_file_column_with_basename() -> None:
    """Mutation invariant: change `_uri_basename` to return the full uri and
    this test pins the regression."""
    panel = _panel_with_rows([])
    panel.update_for_uri(
        "file:///home/alf/projects/foo/bar/baz.py",
        [
            {
                "severity": 1,
                "range": {"start": {"line": 0, "character": 0},
                          "end":   {"line": 0, "character": 1}},
                "message": "boom",
                "source":  "src",
            }
        ],
    )
    row = list(panel._store)[0]
    assert row[1] == "baz.py"


def test_uri_basename_decodes_percent_encoding() -> None:
    assert _uri_basename("file:///a/b%20c.py") == "b c.py"
    assert _uri_basename("file:///plain.py") == "plain.py"
    assert _uri_basename("") == ""
