"""MouseHoverController — pointer-dwell triggering for textDocument/hover.

Long-lived per-Gedit.Document object. Watches motion-notify-event,
debounces dwell with a configurable timer, tracks an in-flight request
token to drop stale responses, and renders results through the shared
`build_hover_popover` helper.
"""
from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gdk, GLib, Gtk, GtkSource

from gedit_lsp.features.hover import build_hover_popover, render_hover_contents
from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter

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
    if start.inside_word() or start.ends_word():
        if not start.starts_word():
            start.backward_word_start()
        if not end.ends_word():
            end.forward_word_end()
        return start, end
    # Fallback: one-character range.
    if not end.is_end():
        end.forward_char()
    return start, end


def should_attach_mouse_hover(*, tunable_enabled: bool) -> bool:
    """Return True iff a MouseHoverController should be attached.

    Only the `enabledFeatures` membership matters here. We deliberately do
    NOT inspect `server.capability("hoverProvider")` at attach time: LSP
    capabilities arrive asynchronously after initialize, so any document
    attached during the race window would see `None` and the feature would
    silently disable itself. Mirrors how completion/signatureHelp/formatting
    wire — request-time fallthrough handles servers that don't actually
    answer hover.
    """
    return bool(tunable_enabled)


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
            with contextlib.suppress(Exception):
                GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _cancel_grace_timer(self) -> None:
        if self._grace_timer_id is not None:
            with contextlib.suppress(Exception):
                GLib.source_remove(self._grace_timer_id)
            self._grace_timer_id = None

    def _dismiss_popover(self) -> None:
        if self._popover is not None:
            with contextlib.suppress(Exception):
                self._popover.popdown()
            self._popover = None

    # --- signal handlers ---

    def _on_motion(self, view: Any, event: Any) -> bool:
        # Drag-suppress: any mouse button held → not dwell.
        any_button_mask = (
            Gdk.ModifierType.BUTTON1_MASK
            | Gdk.ModifierType.BUTTON2_MASK
            | Gdk.ModifierType.BUTTON3_MASK
        )
        if event.state & any_button_mask:
            self._cancel_timer()         # cancel any pending dwell before bailing
            return False

        self._cancel_timer()
        self._request_token += 1
        captured_token = self._request_token

        # Motion events carry event.window set to the sub-window the pointer
        # is over (TEXT for the text area, LEFT for the line-number gutter,
        # etc.). The first arg to window_to_buffer_coords tells GTK which
        # sub-window the input coords are FROM — passing a hardcoded WIDGET
        # double-subtracts the gutter offset and shifts the resolved iter
        # left by the gutter width.
        window_type = view.get_window_type(event.window)
        bx, by = view.window_to_buffer_coords(
            window_type, int(event.x), int(event.y)
        )
        over_text, buffer_iter = view.get_iter_at_location(bx, by)

        # The grace timer is a DEADLINE, not a debounce: it must fire 150ms
        # after the user first left the anchor, even if they keep wiggling
        # the pointer over whitespace. Each branch below arms it iff one
        # isn't already armed; cancellation is reserved for "user came
        # back to the anchor" and successful re-popover paths.

        if not over_text:
            if (
                self._popover is not None
                and not self._pointer_in_popover
                and self._grace_timer_id is None
            ):
                self._grace_timer_id = GLib.timeout_add(
                    self._GRACE_MS, self._on_grace_expired,
                )
            return False

        # If popover is up and pointer is still inside the anchored range,
        # leave it alone — stable hover, no re-fire. Also cancel any grace
        # that was armed by a brief detour through whitespace: the user is
        # back on the hover target.
        if self._popover is not None and self._anchor_range is not None:
            start, end = self._anchor_range
            if start.get_offset() <= buffer_iter.get_offset() < end.get_offset():
                self._cancel_grace_timer()
                return False
            # Pointer moved off the anchored token. "Whitespace" here
            # includes intertoken spaces and punctuation (over_text=True
            # but not on the hovered word) — for those the dwell-then-null
            # path would silently keep the stale popover up forever. Arm a
            # grace dismiss; if the new dwell resolves to fresh hover
            # content it will build a replacement popover (which cancels
            # the grace timer in _on_response).
            if (
                not self._pointer_in_popover
                and self._grace_timer_id is None
            ):
                self._grace_timer_id = GLib.timeout_add(
                    self._GRACE_MS, self._on_grace_expired,
                )

        self._timer_id = GLib.timeout_add(
            self._dwell_ms, self._on_dwell, captured_token, bx, by,
        )
        return False

    def _on_dwell(
        self, captured_token: int, bx: int, by: int,
    ) -> bool:
        # If our token moved on (motion canceled us, dispose ran), drop silently.
        if captured_token != self._request_token:
            return False
        self._timer_id = None

        # Re-translate (bx, by) → live buffer iter. Buffer may have mutated
        # since motion scheduled us, so we always read against the current state.
        over_text, buffer_iter = self._view.get_iter_at_location(bx, by)
        if not over_text:
            return False

        line, char = text_iter_to_utf16(buffer_iter)
        logger.info(
            "mouse-hover dwell: uri=%s pos=%d:%d token=%d",
            self._uri, line, char, captured_token,
        )

        self._server._send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": self._uri},
                "position": {"line": line, "character": char},
            },
            lambda msg: self._on_response(captured_token, buffer_iter, msg),
        )
        return False

    def _on_response(
        self,
        captured_token: int,
        anchor_iter: Gtk.TextIter,
        msg: dict[str, Any],
    ) -> None:
        if captured_token != self._request_token:
            logger.debug("mouse-hover response: stale token %d", captured_token)
            return
        if msg.get("error"):
            logger.info("mouse-hover response: error=%r", msg.get("error"))
            return
        result = msg.get("result")
        if result is None:
            return

        text = render_hover_contents(result.get("contents"))
        if not text.strip():
            return

        server_range = result.get("range")
        if server_range:
            start_iter, end_iter = _iters_from_lsp_range(
                self._buffer, server_range,
            )
        else:
            start_iter, end_iter = _word_bounds_at(anchor_iter)

        # Pop any previous popover before replacing. Also cancel any grace
        # timer armed by motion through the prior anchor's whitespace —
        # the new popover supersedes that pending deadline.
        self._dismiss_popover()
        self._cancel_grace_timer()
        self._anchor_range = (start_iter, end_iter)
        self._popover = build_hover_popover(self._view, start_iter, text)
        # Disable modal mode: the default `Gtk.Popover.new(parent)` installs
        # a pointer grab on popup that swallows the view's motion-notify-
        # event, breaking every motion-driven dismiss path in this
        # controller. We have our own button/key/focus/leave handlers, so
        # we don't need GTK's modal-grab "click outside" auto-dismiss.
        self._popover.set_modal(False)  # type: ignore[attr-defined]
        self._attach_popover_pointer_tracking(self._popover)
        self._popover.popup()

    _GRACE_MS = 150

    def _on_view_leave(self, _view: Any, _event: Any) -> bool:
        if self._popover is None:
            return False
        if self._pointer_in_popover:
            return False
        self._cancel_grace_timer()
        self._grace_timer_id = GLib.timeout_add(
            self._GRACE_MS, self._on_grace_expired,
        )
        return False

    def _on_grace_expired(self) -> bool:
        self._grace_timer_id = None
        if not self._pointer_in_popover:
            self._dismiss_state()
        return False  # one-shot

    def _on_focus_out(self, _view: Any, _event: Any) -> bool:
        self._dismiss_state()
        return False

    def _on_key_press(self, _view: Any, _event: Any) -> bool:
        self._dismiss_state()
        return False

    def _on_button_press(self, _view: Any, _event: Any) -> bool:
        self._dismiss_state()
        return False

    def _dismiss_state(self) -> None:
        """Cancel pending work and dismiss the popover."""
        self._cancel_timer()
        self._cancel_grace_timer()
        self._request_token += 1
        self._dismiss_popover()
        self._anchor_range = None
        self._pointer_in_popover = False

    def _attach_popover_pointer_tracking(self, popover: Gtk.Popover) -> None:
        def on_enter(_w: Any, _e: Any) -> bool:
            self._pointer_in_popover = True
            self._cancel_grace_timer()
            return False

        def on_leave(_w: Any, event: Any) -> bool:
            # GTK fires leave-notify on a widget when the pointer crosses
            # into one of its children (detail=INFERIOR). That's still
            # "inside the popover" from the user's perspective — ignore it,
            # otherwise the popover dismisses the moment the pointer reaches
            # the inner ScrolledWindow / SourceView content.
            if event.detail == Gdk.NotifyType.INFERIOR:
                return False
            self._pointer_in_popover = False
            # Real leave: schedule a grace dismiss; on_enter cancels it if
            # the pointer comes back in within the window.
            self._cancel_grace_timer()
            self._grace_timer_id = GLib.timeout_add(
                self._GRACE_MS, self._on_grace_expired,
            )
            return False

        # Gtk.Popover's GdkWindow does not subscribe to enter/leave events by
        # default; without this the signal handlers below silently never fire
        # and the popover would dismiss as soon as the pointer enters it.
        with contextlib.suppress(TypeError, RuntimeError):
            popover.add_events(  # type: ignore[attr-defined]
                Gdk.EventMask.ENTER_NOTIFY_MASK  # type: ignore[attr-defined]
                | Gdk.EventMask.LEAVE_NOTIFY_MASK,  # type: ignore[attr-defined]
            )
        with contextlib.suppress(TypeError, RuntimeError):
            popover.connect("enter-notify-event", on_enter)
        with contextlib.suppress(TypeError, RuntimeError):
            popover.connect("leave-notify-event", on_leave)
        with contextlib.suppress(TypeError, RuntimeError):
            popover.connect(
                "closed",
                lambda _p: setattr(self, "_popover", None),
            )
