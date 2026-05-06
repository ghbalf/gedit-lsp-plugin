"""Completion docs popover — pure helpers + GTK-bound controller.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GTK class (`CompletionDocsController`) wires the helpers to GtkSource's
completion popup signals.
"""
from __future__ import annotations

import enum


class NavStep(enum.Enum):
    """Subset of Gtk.ScrollStep we care about for completion navigation.

    Values are debug labels, not GTK constants — mapping to/from
    Gtk.ScrollStep belongs in the controller adapter, not here, so the
    pure layer stays GTK-free.
    """
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

    `num` is signed: negative = up/back, positive = down/forward; `num=0`
    is a no-op. Returns -1 when the list is empty. Otherwise clamps to
    [0, list_len-1]. A caller-supplied `current` outside that range is
    treated as a programmer bug and silently clamped (no exception).
    A non-positive `page_size` is coerced to 1 so PAGE never inverts
    direction.
    """
    if list_len <= 0:
        return -1
    if step is NavStep.ENDS:
        return list_len - 1 if num > 0 else 0
    delta = num * (max(1, page_size) if step is NavStep.PAGE else 1)
    new_index = current + delta
    if new_index < 0:
        return 0
    if new_index >= list_len:
        return list_len - 1
    return new_index


from gedit_lsp.features.completion import LspProposal  # noqa: E402  (after enum)


def format_proposal_text(proposal: LspProposal) -> str:
    """Format detail + documentation for the docs popover.

    Detail (e.g. function signature) on the first line, documentation
    below. Markdown is stringified upstream — no rich rendering for v1.
    Returns " " (single space) when both fields are empty so the popover
    doesn't collapse to a zero-height row.
    """
    parts: list[str] = []
    if proposal.detail:
        parts.append(proposal.detail)
    if proposal.documentation:
        parts.append(proposal.documentation)
    return "\n\n".join(parts) or " "
