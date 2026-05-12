"""Tests for the pure model class behind CodeActionPopover."""
from __future__ import annotations

from gedit_lsp.code_action import NormalizedAction
from gedit_lsp.ui.code_action_popover import CodeActionPopoverModel


def _action(title: str, kind: str = "quickfix", disabled: bool = False) -> NormalizedAction:
    return NormalizedAction(
        title=title,
        kind=kind,
        edit={"changes": {}},
        command=None,
        data=None,
        is_preferred=False,
        disabled_reason="reason" if disabled else None,
    )


def test_model_initial_selection_is_first_enabled() -> None:
    a = _action("first", disabled=True)
    b = _action("second")
    c = _action("third")
    m = CodeActionPopoverModel([a, b, c])
    # Disabled rows are unselectable — first selectable is index 1
    assert m.selected_index == 1
    assert m.selected_action()["title"] == "second"


def test_model_all_disabled_no_selection() -> None:
    a = _action("a", disabled=True)
    b = _action("b", disabled=True)
    m = CodeActionPopoverModel([a, b])
    assert m.selected_index is None
    assert m.selected_action() is None


def test_model_move_down_skips_disabled() -> None:
    a = _action("a")
    b = _action("b", disabled=True)
    c = _action("c")
    m = CodeActionPopoverModel([a, b, c])
    assert m.selected_index == 0
    m.move_down()
    assert m.selected_index == 2  # skipped b


def test_model_move_down_wraps_to_first_enabled() -> None:
    a = _action("a")
    b = _action("b")
    m = CodeActionPopoverModel([a, b])
    assert m.selected_index == 0
    m.move_down()
    assert m.selected_index == 1
    m.move_down()
    assert m.selected_index == 0  # wrap


def test_model_move_up_skips_disabled_and_wraps() -> None:
    a = _action("a")
    b = _action("b", disabled=True)
    c = _action("c")
    m = CodeActionPopoverModel([a, b, c])
    # Start at 0, move_up wraps to 2 (skip b)
    m.move_up()
    assert m.selected_index == 2


def test_model_empty_actions_no_selection() -> None:
    m = CodeActionPopoverModel([])
    assert m.selected_index is None
    assert m.selected_action() is None
    # Movement on empty list is a no-op
    m.move_down()
    m.move_up()
    assert m.selected_index is None


def test_model_grouped_rows_preserves_order() -> None:
    # The model accepts a flat list but groups for display via
    # group_by_kind. Verify the grouped output for rendering.
    a = _action("ext", kind="refactor.extract")
    b = _action("fix", kind="quickfix")
    m = CodeActionPopoverModel([a, b])
    groups = m.grouped_rows()
    # quickfix → refactor ordering
    assert [g for g, _ in groups] == ["quickfix", "refactor"]
