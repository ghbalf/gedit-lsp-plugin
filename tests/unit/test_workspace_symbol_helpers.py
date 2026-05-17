"""Unit tests for workspace/symbol pure helpers.

seed_query uses a real Gtk.TextBuffer — a model object, allowed in
headless unit tests (only View/Window/Popover SIGTRAP without DISPLAY).
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from gedit_lsp.features.workspace_symbol import (
    parse_symbol_results,
    seed_query,
    symbol_kind_label,
)


def _buf(text: str, offset: int) -> Gtk.TextBuffer:
    b = Gtk.TextBuffer()
    b.set_text(text)
    b.place_cursor(b.get_iter_at_offset(offset))
    return b


# --- parse_symbol_results --------------------------------------------


def test_parse_symbolinformation() -> None:
    result = [
        {"name": "compute_total", "kind": 12,
         "location": {"uri": "file:///lib.py",
                      "range": {"start": {"line": 10, "character": 4},
                                "end": {"line": 10, "character": 17}}}},
    ]
    out = parse_symbol_results(result)
    assert len(out) == 1
    assert out[0]["name"] == "compute_total"
    assert out[0]["location"]["range"]["start"]["line"] == 10


def test_parse_workspacesymbol_with_range() -> None:
    result = [{"name": "C", "kind": 5,
               "location": {"uri": "file:///a.py",
                            "range": {"start": {"line": 1, "character": 0},
                                      "end": {"line": 1, "character": 1}}}}]
    assert parse_symbol_results(result)[0]["name"] == "C"


def test_parse_workspacesymbol_without_range_kept() -> None:
    result = [{"name": "C", "kind": 5,
               "location": {"uri": "file:///a.py"},
               "data": {"server": "token"}}]
    out = parse_symbol_results(result)
    assert len(out) == 1
    assert "range" not in out[0]["location"]
    assert out[0]["data"] == {"server": "token"}  # preserved for resolve


def test_parse_null_and_empty() -> None:
    assert parse_symbol_results(None) == []
    assert parse_symbol_results([]) == []


def test_parse_non_list_and_malformed() -> None:
    assert parse_symbol_results({"name": "x"}) == []
    assert parse_symbol_results("garbage") == []
    # items missing name / location / location.uri are dropped
    assert parse_symbol_results([
        {"kind": 5, "location": {"uri": "file:///a"}},       # no name
        {"name": "ok", "location": {}},                       # no uri
        {"name": "ok2"},                                      # no location
        {"name": "bad", "location": {"uri": None}},           # uri not a str
        {"name": "good", "location": {"uri": "file:///g"}},   # kept
    ]) == [{"name": "good", "location": {"uri": "file:///g"}}]


# --- symbol_kind_label -----------------------------------------------


def test_symbol_kind_label_known() -> None:
    assert symbol_kind_label(5) == "class"
    assert symbol_kind_label(6) == "method"
    assert symbol_kind_label(12) == "function"
    assert symbol_kind_label(13) == "variable"
    assert symbol_kind_label(14) == "constant"


def test_symbol_kind_label_unknown() -> None:
    assert symbol_kind_label(0) == "symbol"
    assert symbol_kind_label(99) == "symbol"
    assert symbol_kind_label(-1) == "symbol"


# --- seed_query ------------------------------------------------------


def test_seed_query_identifier() -> None:
    # cursor inside "compute_total"
    assert seed_query(_buf("x = compute_total(items)", 8)) == "compute_total"


def test_seed_query_boundaries() -> None:
    text = "foo_bar = 1"
    assert seed_query(_buf(text, 0)) == "foo_bar"   # at start
    assert seed_query(_buf(text, 7)) == "foo_bar"   # just past last ident char


def test_seed_query_whitespace() -> None:
    assert seed_query(_buf("a  +  b", 3)) == ""      # cursor on spaces/'+'


def test_seed_query_selection_precedence() -> None:
    b = Gtk.TextBuffer()
    b.set_text("alpha beta gamma")
    b.select_range(b.get_iter_at_offset(6), b.get_iter_at_offset(10))  # "beta"
    assert seed_query(b) == "beta"


def test_seed_query_empty_line() -> None:
    assert seed_query(_buf("", 0)) == ""
