"""workspace/symbol quick-pick: pure QuickPickModel + Gtk.Popover widget.

QuickPickModel is GTK-free and fully unit-tested. WorkspaceSymbolQuickPick
(added in Task 4) is the Gtk.Popover and is smoke-only — widget
construction in headless unit tests SIGTRAPs CI (the mouse-hover lesson).
"""
from __future__ import annotations

from typing import Any


class QuickPickModel:
    """Selection state over a flat symbol list.

    `set_results` re-selects index 0 (or None when empty). Movement
    wraps for line moves and clamps for page moves. No hint/placeholder
    rows ever enter the model — the widget renders hints separately.
    """

    def __init__(self) -> None:
        self._symbols: list[dict[str, Any]] = []
        self._selected: int | None = None

    def set_results(self, symbols: list[dict[str, Any]]) -> None:
        self._symbols = list(symbols)
        self._selected = 0 if self._symbols else None

    @property
    def results(self) -> list[dict[str, Any]]:
        return list(self._symbols)

    def selected(self) -> dict[str, Any] | None:
        if self._selected is None:
            return None
        return self._symbols[self._selected]

    @property
    def selected_index(self) -> int | None:
        return self._selected

    def move_down(self) -> None:
        if self._selected is None:
            return
        self._selected = (self._selected + 1) % len(self._symbols)

    def move_up(self) -> None:
        if self._selected is None:
            return
        self._selected = (self._selected - 1) % len(self._symbols)

    def page_down(self, n: int) -> None:
        if self._selected is None:
            return
        self._selected = min(self._selected + n, len(self._symbols) - 1)

    def page_up(self, n: int) -> None:
        if self._selected is None:
            return
        self._selected = max(self._selected - n, 0)
