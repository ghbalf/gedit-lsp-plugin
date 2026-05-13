"""mouse_hover — pure helpers for textDocument/hover via pointer dwell.

This module currently contains only the two conversion helpers used to
translate LSP positions and GTK TextIter positions into anchoring ranges.
The `MouseHoverController` class (dwell timer, in-flight request tracking,
popover rendering) will be added in subsequent tasks.
"""
from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource

from gedit_lsp.utf16 import utf16_to_text_iter

if TYPE_CHECKING:
    from gedit_lsp.server import LanguageServer

logger = logging.getLogger("gedit_lsp.mouse_hover")


def _iters_from_lsp_range(
    buffer: GtkSource.Buffer, lsp_range: dict[str, Any]
) -> tuple[Gtk.TextIter, Gtk.TextIter]:
    """Convert an LSP `Range` (UTF-16) to a `(start, end)` iter pair."""
    s = lsp_range["start"]
    e = lsp_range["end"]
    start = utf16_to_text_iter(buffer, s["line"], s["character"])
    end = utf16_to_text_iter(buffer, e["line"], e["character"])
    return start, end


def _word_bounds_at(
    cursor: Gtk.TextIter,
) -> tuple[Gtk.TextIter, Gtk.TextIter]:
    """Return the word range surrounding `cursor`.

    If `cursor` is not on a word character, returns a one-character
    range starting at `cursor` (so the popover still anchors somewhere
    reasonable).
    """
    start = cursor.copy()
    end = cursor.copy()
    if start.inside_word():
        if not start.starts_word():
            start.backward_word_start()
        if not end.ends_word():
            end.forward_word_end()
        return start, end
    # Fallback: one-character range.
    if not end.is_end():
        end.forward_char()
    return start, end


class MouseHoverController:
    def __init__(
        self,
        *,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: LanguageServer,
        uri: str,
        dwell_ms: int,
        spinner_threshold_ms: int,
    ) -> None:
        self._view = view
        self._buffer = buffer
        self._server = server
        self._uri = uri
        self._dwell_ms = dwell_ms
        self._spinner_threshold_ms = spinner_threshold_ms

        self._timer_id: int | None = None
        self._grace_timer_id: int | None = None
        self._request_token: int = 0
        self._popover: Gtk.Popover | None = None
        self._anchor_range: tuple[Gtk.TextIter, Gtk.TextIter] | None = None
        self._pointer_in_popover: bool = False
        self._disposed: bool = False
        self._view_handler_ids: list[int] = []

        self._view_handler_ids.append(
            view.connect("motion-notify-event", self._on_motion),
        )
        self._view_handler_ids.append(
            view.connect("leave-notify-event", self._on_view_leave),
        )
        self._view_handler_ids.append(
            view.connect("focus-out-event", self._on_focus_out),
        )
        self._view_handler_ids.append(
            view.connect("key-press-event", self._on_key_press),
        )
        self._view_handler_ids.append(
            view.connect("button-press-event", self._on_button_press),
        )
        logger.info("mouse-hover controller wired uri=%s dwell_ms=%d", uri, dwell_ms)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._cancel_timer()
        self._cancel_grace_timer()
        self._request_token += 1
        for hid in self._view_handler_ids:
            with contextlib.suppress(TypeError, RuntimeError):
                self._view.disconnect(hid)
        self._view_handler_ids.clear()
        self._dismiss_popover()
        self._anchor_range = None
        self._pointer_in_popover = False

    # --- helpers ---

    def _cancel_timer(self) -> None:
        if self._timer_id is not None:
            from gi.repository import GLib
            with contextlib.suppress(Exception):
                GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _cancel_grace_timer(self) -> None:
        if self._grace_timer_id is not None:
            from gi.repository import GLib
            with contextlib.suppress(Exception):
                GLib.source_remove(self._grace_timer_id)
            self._grace_timer_id = None

    def _dismiss_popover(self) -> None:
        if self._popover is not None:
            with contextlib.suppress(Exception):
                self._popover.popdown()
            self._popover = None

    # --- signal handlers (stubs; behavior added in later tasks) ---

    def _on_motion(self, _view: Any, _event: Any) -> bool:
        return False

    def _on_view_leave(self, _view: Any, _event: Any) -> bool:
        return False

    def _on_focus_out(self, _view: Any, _event: Any) -> bool:
        return False

    def _on_key_press(self, _view: Any, _event: Any) -> bool:
        return False

    def _on_button_press(self, _view: Any, _event: Any) -> bool:
        return False
