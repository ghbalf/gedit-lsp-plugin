"""Completion docs popover — pure helpers + GTK-bound controller.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GTK class (`CompletionDocsController`) wires the helpers to GtkSource's
completion popup signals.
"""
from __future__ import annotations

import contextlib
import enum
import logging
from typing import TYPE_CHECKING

from gedit_lsp.features.completion import LspProposal


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


def format_proposal_text(proposal: LspProposal) -> str:
    """Format detail + documentation for the docs popover.

    Detail (e.g. function signature) on the first line, documentation
    below. Returns empty string when both fields are empty; the caller
    decides how to handle that.
    """
    parts: list[str] = []
    if proposal.detail:
        parts.append(proposal.detail)
    if proposal.documentation:
        parts.append(proposal.documentation)
    return "\n\n".join(parts)


import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource  # noqa: E402

if TYPE_CHECKING:
    from gedit_lsp.features.completion import LspCompletionProvider

logger = logging.getLogger("gedit_lsp.completion_docs")


class CompletionDocsController:
    """Per-view controller showing a docs popover for the highlighted proposal.

    Lifecycle: constructed when `_attach_document` runs (after the existing
    `CompletionController`); `dispose()` called from `plugin.py` on
    tab-removed or `do_deactivate`. Returns its disposer so the plugin
    can store it alongside the existing listener-disposer set.
    """

    def __init__(
        self,
        *,
        view: Gtk.TextView,
        provider: LspCompletionProvider,
    ) -> None:
        self._view = view
        self._provider = provider
        self._proposals: list[LspProposal] = []
        self._index = 0
        self._popover: Gtk.Popover | None = None
        self._label: Gtk.Label | None = None
        self._handler_ids: list[int] = []
        self._anchor_set: bool = False
        self._completion = view.get_completion()  # type: ignore[attr-defined]
        # Hook the completion popup signals.
        if self._completion is not None:
            for sig, cb in (
                ("show",          self._on_show),
                ("hide",          self._on_hide),
                ("move-cursor",   self._on_move_cursor),
                ("move-page",     self._on_move_page),
            ):
                hid = self._completion.connect(sig, cb)
                self._handler_ids.append(hid)
        # Subscribe to populate events on our provider.
        self._provider.set_populate_callback(self._on_populated)
        logger.info(
            "constructed: completion=%s handler_ids=%s",
            self._completion is not None, self._handler_ids,
        )

    def dispose(self) -> None:
        if self._completion is not None:
            for hid in self._handler_ids:
                with contextlib.suppress(Exception):
                    self._completion.disconnect(hid)
        self._handler_ids.clear()
        self._provider.set_populate_callback(None)
        if self._popover is not None:
            with contextlib.suppress(Exception):
                self._popover.popdown()
        self._popover = None
        self._label = None

    # --- callbacks ---

    def _on_populated(self, proposals: list[LspProposal]) -> None:
        logger.info("populated: %d proposals", len(proposals))
        self._proposals = proposals
        self._index = 0
        self._refresh()

    def _on_show(self, _completion: GtkSource.Completion) -> None:
        logger.info("popup show: %d cached proposals", len(self._proposals))
        # The popup just opened. If our provider's proposals are stale
        # (e.g. another provider populated last), don't show — wait for
        # the next _on_populated.
        if self._proposals:
            self._refresh(show=True)

    def _on_hide(self, _completion: GtkSource.Completion) -> None:
        logger.info("popup hide")
        if self._popover is not None:
            with contextlib.suppress(Exception):
                self._popover.popdown()
        # Clear stale state so the next _on_show doesn't render last
        # session's proposals before _on_populated repopulates, and so
        # the next show session re-anchors at the new cursor position.
        self._proposals = []
        self._index = 0
        self._anchor_set = False

    def _on_move_cursor(
        self,
        _completion: GtkSource.Completion,
        scroll_step: Gtk.ScrollStep,
        num: int,
    ) -> None:
        step = _scroll_step_to_navstep(scroll_step)
        if step is None:
            return  # unsupported step — ignore
        page_size = self._page_size()
        self._index = advance_index(
            self._index, step, num,
            list_len=len(self._proposals), page_size=page_size,
        )
        self._refresh()

    def _on_move_page(
        self,
        _completion: GtkSource.Completion,
        scroll_step: Gtk.ScrollStep,
        num: int,
    ) -> None:
        # libgedit also fires move-page for PageUp/PageDown; treat as PAGE
        # regardless of the scroll_step value.
        page_size = self._page_size()
        self._index = advance_index(
            self._index, NavStep.PAGE, num,
            list_len=len(self._proposals), page_size=page_size,
        )
        self._refresh()

    # --- helpers ---

    def _page_size(self) -> int:
        # The completion popup's proposal-page-size property (default 5
        # in libgedit) tells us how many rows fit in a "page".
        if self._completion is None:
            return 5
        try:
            return int(self._completion.get_property("proposal-page-size"))
        except (TypeError, ValueError):
            return 5

    def _refresh(self, *, show: bool = False) -> None:
        if not self._proposals or self._index < 0:
            return
        proposal = self._proposals[self._index]
        body = format_proposal_text(proposal)
        # Always render: label as a header (so the user sees we got a
        # proposal even when pylsp's initial response is sparse), and a
        # placeholder body when detail+documentation are both empty.
        # `completionItem/resolve` enrichment (which pylsp would use to
        # fill these fields) is a follow-up.
        text = proposal.label + "\n\n" + (body or "(no documentation)")
        logger.info(
            "refresh: index=%d label=%r body_chars=%d show=%s",
            self._index, proposal.label, len(body), show,
        )
        label = self._ensure_label()
        label.set_text(text)
        if show or (self._popover is not None and self._popover.get_visible()):
            self._show_popover()

    def _ensure_label(self) -> Gtk.Label:
        if self._label is None:
            label = Gtk.Label.new("")
            label.set_xalign(0)
            label.set_line_wrap(True)  # type: ignore[attr-defined]
            label.set_selectable(True)
            label.set_max_width_chars(60)
            self._label = label
        return self._label

    def _ensure_popover(self) -> Gtk.Popover:
        if self._popover is None:
            popover = Gtk.Popover.new(self._view)  # type: ignore[call-arg]
            popover.set_modal(False)  # type: ignore[attr-defined]  # don't steal focus from completion popup
            popover.set_position(Gtk.PositionType.RIGHT)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_min_content_height(120)
            scrolled.set_min_content_width(360)
            scrolled.set_max_content_height(360)
            scrolled.add(self._ensure_label())  # type: ignore[attr-defined]
            popover.add(scrolled)  # type: ignore[attr-defined]
            # show_all() realizes/maps children — without it, popup()
            # shows an empty/invisible window on libgedit-gtksourceview.
            # Matches the working hover popover pattern in features/hover.py.
            popover.show_all()  # type: ignore[attr-defined]
            self._popover = popover
        return self._popover

    def _show_popover(self) -> None:
        # NOTE: The completion popup is also anchored at the cursor and extends
        # right/down. PositionType.RIGHT places our popover to the right of the
        # cursor's column, which on small windows may overlap the popup. Manual
        # smoke (Task 9) verifies this; if it fails we revisit anchor strategy
        # (e.g. anchor to the view's right edge instead).
        popover = self._ensure_popover()
        if not self._anchor_set:
            # Anchor once per show session at the cursor's current rect.
            # Subsequent refreshes (highlight changes, populate updates) should
            # not jitter the popover — the cursor may have advanced as the user
            # typed, but the popup itself is still anchored to the original
            # trigger position.
            buf = self._view.get_buffer()
            cursor_iter = buf.get_iter_at_mark(buf.get_insert())
            rect = self._view.get_iter_location(cursor_iter)
            bx, by = self._view.buffer_to_window_coords(
                Gtk.TextWindowType.WIDGET, rect.x, rect.y + rect.height,
            )
            rect.x = bx
            rect.y = by
            rect.width = 1
            rect.height = 1
            popover.set_pointing_to(rect)
            self._anchor_set = True
        popover.popup()  # non-modal show


def _scroll_step_to_navstep(s: Gtk.ScrollStep) -> NavStep | None:
    # Gtk.ScrollStep values that GtkSourceCompletion actually emits:
    # STEPS (single row), PAGES (page), ENDS (top/bottom).
    if s == Gtk.ScrollStep.STEPS:
        return NavStep.STEP
    if s == Gtk.ScrollStep.PAGES:
        return NavStep.PAGE
    if s == Gtk.ScrollStep.ENDS:
        return NavStep.ENDS
    return None
