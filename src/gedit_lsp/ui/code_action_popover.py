"""CodeActionPopover — picker widget + its pure model.

The model class is GTK-free and fully unit-tested. The widget class
(added later) wraps the model and adds anchoring, ListBox rendering,
and key handling.
"""
from __future__ import annotations

from gedit_lsp.code_action import NormalizedAction, group_by_kind


class CodeActionPopoverModel:
    """Pure-Python state for the codeAction picker.

    Tracks the action list, current selection index, and provides
    group_by_kind output for rendering. Disabled actions are visible
    in the list but unselectable — movement skips them.
    """

    def __init__(self, actions: list[NormalizedAction]) -> None:
        self._actions: list[NormalizedAction] = actions
        self._selected: int | None = self._first_enabled_index()

    def _first_enabled_index(self) -> int | None:
        for i, a in enumerate(self._actions):
            if a["disabled_reason"] is None:
                return i
        return None

    @property
    def selected_index(self) -> int | None:
        return self._selected

    def selected_action(self) -> NormalizedAction | None:
        if self._selected is None:
            return None
        return self._actions[self._selected]

    def move_down(self) -> None:
        if not self._actions or self._selected is None:
            return
        n = len(self._actions)
        i = self._selected
        for _ in range(n):
            i = (i + 1) % n
            if self._actions[i]["disabled_reason"] is None:
                self._selected = i
                return

    def move_up(self) -> None:
        if not self._actions or self._selected is None:
            return
        n = len(self._actions)
        i = self._selected
        for _ in range(n):
            i = (i - 1) % n
            if self._actions[i]["disabled_reason"] is None:
                self._selected = i
                return

    def grouped_rows(self) -> list[tuple[str, list[NormalizedAction]]]:
        """Return actions grouped by kind, in display order."""
        return group_by_kind(self._actions)
