"""HoverController — Ctrl+K shows a popover with the server's hover content.

Markdown is rendered as plain text — we don't pull in a markdown renderer
for v1. Code-block fences are kept as-is in the body.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource

from gedit_lsp.utf16 import text_iter_to_utf16

if TYPE_CHECKING:
    from gedit_lsp.server import LanguageServer


def render_hover_contents(contents: Any) -> str:
    """Render LSP `Hover.contents` to plain text.

    Accepts:
        - str
        - {"kind": "markdown" | "plaintext", "value": str}    (MarkupContent)
        - {"language": str, "value": str}                     (MarkedString — old)
        - list of MarkedString | str                          (MarkedString[])
        - None
    """
    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return cast(str, contents.get("value", ""))
    if isinstance(contents, list):
        return "\n\n".join(render_hover_contents(c) for c in contents).strip()
    return ""


class HoverController:
    def __init__(
        self,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: LanguageServer,
        uri: str,
        spinner_threshold_ms: int,
    ) -> None:
        self._view = view
        self._buffer = buffer
        self._server = server
        self._uri = uri
        self._spinner_threshold_ms = spinner_threshold_ms
        self._popover: Gtk.Popover | None = None

    def trigger(self) -> None:
        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        line, char = text_iter_to_utf16(cursor)

        def on_response(msg: dict[str, Any]) -> None:
            if msg.get("error") or msg.get("result") is None:
                return
            text = render_hover_contents(msg["result"].get("contents"))
            if not text.strip():
                return
            self._show_popover(cursor, text)

        self._server._send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": self._uri},
                "position": {"line": line, "character": char},
            },
            on_response,
        )

    def _show_popover(self, anchor_iter: Gtk.TextIter, text: str) -> None:
        if self._popover is not None:
            self._popover.popdown()
        rect = self._view.get_iter_location(anchor_iter)
        bx, by = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y + rect.height
        )
        rect.x = bx
        rect.y = by
        rect.width = 1
        rect.height = 1

        self._popover = Gtk.Popover.new(self._view)  # type: ignore[call-arg]
        self._popover.set_pointing_to(rect)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(120)
        scrolled.set_min_content_width(400)
        inner_buf = GtkSource.Buffer()
        inner_buf.set_text(text)
        inner_view = GtkSource.View.new_with_buffer(inner_buf)
        inner_view.set_editable(False)
        inner_view.set_cursor_visible(False)
        inner_view.set_wrap_mode(Gtk.WrapMode.WORD)
        inner_view.set_monospace(True)
        scrolled.add(inner_view)  # type: ignore[attr-defined]
        self._popover.add(scrolled)  # type: ignore[attr-defined]
        self._popover.show_all()  # type: ignore[attr-defined]
        self._popover.popup()
