"""Tests for the index-navigation helper used by the completion docs popover."""
from __future__ import annotations

from gedit_lsp.features.completion_docs import (
    NavStep,
    advance_index,
)


def test_advance_index_step_down() -> None:
    assert advance_index(0, NavStep.STEP, 1, list_len=5, page_size=3) == 1
    assert advance_index(2, NavStep.STEP, 2, list_len=5, page_size=3) == 4


def test_advance_index_step_up() -> None:
    assert advance_index(2, NavStep.STEP, -1, list_len=5, page_size=3) == 1
    assert advance_index(0, NavStep.STEP, -1, list_len=5, page_size=3) == 0  # clamp


def test_advance_index_clamps_at_top_and_bottom() -> None:
    assert advance_index(4, NavStep.STEP, 5, list_len=5, page_size=3) == 4  # clamp
    assert advance_index(0, NavStep.STEP, -10, list_len=5, page_size=3) == 0


def test_advance_index_page_uses_page_size() -> None:
    assert advance_index(0, NavStep.PAGE, 1, list_len=20, page_size=5) == 5
    assert advance_index(15, NavStep.PAGE, -2, list_len=20, page_size=5) == 5


def test_advance_index_empty_list_returns_minus_one() -> None:
    assert advance_index(0, NavStep.STEP, 1, list_len=0, page_size=3) == -1


def test_advance_index_ends_jumps_to_extremes() -> None:
    assert advance_index(2, NavStep.ENDS, 1, list_len=5, page_size=3) == 4
    assert advance_index(2, NavStep.ENDS, -1, list_len=5, page_size=3) == 0
