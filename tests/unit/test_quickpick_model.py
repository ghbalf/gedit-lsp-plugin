"""Unit tests for QuickPickModel — pure selection state, GTK-free."""
from __future__ import annotations

from typing import Any

from gedit_lsp.ui.workspace_symbol_quickpick import QuickPickModel


def _syms(n: int) -> list[dict[str, Any]]:
    return [{"name": f"s{i}", "location": {"uri": f"file:///{i}"}} for i in range(n)]


def test_set_results_selects_first() -> None:
    m = QuickPickModel()
    m.set_results(_syms(3))
    assert m.selected()["name"] == "s0"
    assert m.results == _syms(3)
    assert m.selected_index == 0


def test_set_results_empty_selects_none() -> None:
    m = QuickPickModel()
    m.set_results([])
    assert m.selected() is None
    assert m.selected_index is None


def test_move_down_up_wraps() -> None:
    m = QuickPickModel()
    m.set_results(_syms(3))
    m.move_down()
    assert m.selected()["name"] == "s1"
    m.move_down()
    m.move_down()
    assert m.selected()["name"] == "s0"        # wrapped forward
    m.move_up()
    assert m.selected()["name"] == "s2"        # wrapped backward


def test_page_moves_clamp() -> None:
    m = QuickPickModel()
    m.set_results(_syms(5))
    m.page_down(10)
    assert m.selected()["name"] == "s4"        # clamped to last
    m.page_up(10)
    assert m.selected()["name"] == "s0"        # clamped to first


def test_reset_reclamps_selection() -> None:
    m = QuickPickModel()
    m.set_results(_syms(5))
    m.page_down(10)                            # selected -> index 4
    m.set_results(_syms(2))                    # shorter list
    assert m.selected()["name"] == "s0"        # re-selected to first


def test_moves_noop_when_empty() -> None:
    m = QuickPickModel()
    m.set_results([])
    m.move_down()
    m.move_up()
    m.page_down(3)
    m.page_up(3)
    assert m.selected() is None


def test_moves_single_element_stay() -> None:
    m = QuickPickModel()
    m.set_results(_syms(1))
    m.move_down()
    m.move_up()
    assert m.selected_index == 0
