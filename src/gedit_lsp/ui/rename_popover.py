"""Gtk.Popover with a single Gtk.Entry for the rename feature's
new-name input.

Anchored at the active view's cursor position via set_pointing_to(rect)
where the rect comes from view.get_iter_location(cursor_iter) and is
converted to widget coordinates with view.buffer_to_window_coords.
Same positioning pattern as features/signature_help's popover.

This widget is excluded from automated tests per the unit-tests-avoid-
GTK-widgets project invariant — Gtk.Popover SIGTRAPs in headless CI.
It is exercised by manual smoke testing only (see the rename PR's
test plan).

Cancellation discipline: any close path that didn't go through commit
is treated as a cancel. To avoid double-firing the cancel callback
after a successful commit, the Enter handler clears the callbacks
to None *before* calling popdown(); the `closed` handler then sees
None and no-ops.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

logger = logging.getLogger("gedit_lsp.rename_popover")


class RenamePopover:
    def __init__(self, view: Gtk.TextView) -> None:
        self._view = view
        self._popover: Gtk.Popover | None = None
        self._entry: Gtk.Entry | None = None
        self._on_commit: Callable[[str], None] | None = None
        self._on_cancel: Callable[[], None] | None = None

    def show(
        self,
        *,
        placeholder: str,
        on_commit: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._on_commit = on_commit
        self._on_cancel = on_cancel

        popover = Gtk.Popover.new(self._view)  # type: ignore[call-arg]
        entry = Gtk.Entry()
        entry.set_text(placeholder)
        entry.select_region(0, -1)
        entry.set_width_chars(max(20, len(placeholder) + 4))
        entry.connect("activate", self._on_activate)
        entry.connect("key-press-event", self._on_key_press)
        popover.add(entry)  # type: ignore[attr-defined]
        popover.connect("closed", self._on_closed)

        # Anchor at cursor.
        buf = self._view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        rect = self._view.get_iter_location(cursor)
        wx, wy = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y,
        )
        rect.x = wx
        rect.y = wy
        popover.set_pointing_to(rect)
        popover.show_all()  # type: ignore[attr-defined]
        popover.popup()
        entry.grab_focus()

        self._popover = popover
        self._entry = entry

    def dismiss(self) -> None:
        if self._popover is not None:
            self._popover.popdown()

    def _on_activate(self, entry: Gtk.Entry) -> None:
        text = entry.get_text()
        on_commit = self._on_commit
        # Clear callbacks BEFORE popdown so _on_closed's auto-cancel no-ops.
        self._on_commit = None
        self._on_cancel = None
        self.dismiss()
        if on_commit is not None:
            on_commit(text)

    def _on_key_press(self, _entry: Gtk.Entry, event: Any) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            on_cancel = self._on_cancel
            # Clear before popdown — same reason as commit path.
            self._on_commit = None
            self._on_cancel = None
            self.dismiss()
            if on_cancel is not None:
                on_cancel()
            return True
        return False

    def _on_closed(self, _popover: Gtk.Popover) -> None:
        # Treat any close that didn't go through commit/escape (i.e.
        # focus-out, click-elsewhere, programmatic dismiss) as a cancel.
        on_cancel = self._on_cancel
        self._on_commit = None
        self._on_cancel = None
        self._popover = None
        self._entry = None
        if on_cancel is not None:
            on_cancel()
