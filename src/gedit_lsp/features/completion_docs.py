"""Completion docs popover — pure helpers + GTK-bound controller.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GTK class (`CompletionDocsController`) is added in a later task.
"""
from __future__ import annotations

import enum


class NavStep(enum.Enum):
    """Subset of Gtk.ScrollStep we care about for completion navigation."""
    STEP = "step"   # one row at a time (Up/Down)
    PAGE = "page"   # one page at a time (PageUp/PageDown)
    ENDS = "ends"   # jump to top/bottom (Home/End equivalent)


def advance_index(
    current: int,
    step: NavStep,
    num: int,
    *,
    list_len: int,
    page_size: int,
) -> int:
    """Compute the new highlight index after a navigation event.

    `num` is signed: negative = up/back, positive = down/forward.
    Returns -1 when the list is empty. Otherwise clamps to [0, list_len-1].
    """
    if list_len <= 0:
        return -1
    if step is NavStep.ENDS:
        return list_len - 1 if num > 0 else 0
    delta = num * (page_size if step is NavStep.PAGE else 1)
    new_index = current + delta
    if new_index < 0:
        return 0
    if new_index >= list_len:
        return list_len - 1
    return new_index
