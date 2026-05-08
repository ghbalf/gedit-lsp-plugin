"""DefinitionController + CursorHistory.

The controller sends `textDocument/definition`, classifies the response
as 0/1/N locations, and dispatches:
    none   → status-bar message
    single → `navigate_to_uri` (in-buffer move or open-or-focus tab)
    many   → small Gtk.Popover listing each location

The history stack is per-window. Goto pushes the *current* cursor location
before jumping; Alt+Left pops and restores it.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from gedit_lsp.navigation import navigate_to_uri
from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter

if TYPE_CHECKING:
    # Gedit typelib is only present inside a running gedit process.
    # Use TYPE_CHECKING so unit tests can import this module.
    from gi.repository import Gedit  # type: ignore[attr-defined]

    from gedit_lsp.server import LanguageServer


def classify_locations(result: Any) -> tuple[str, list[dict[str, Any]]]:
    if result is None:
        return ("none", [])
    if isinstance(result, dict):
        return ("single", [result])
    if isinstance(result, list):
        if not result:
            return ("none", [])
        if len(result) == 1:
            return ("single", result)
        return ("many", result)
    return ("none", [])


class CursorHistory:
    def __init__(self, max_entries: int) -> None:
        self._stack: deque[tuple[str, int, int]] = deque(maxlen=max_entries)

    def push(self, entry: tuple[str, int, int]) -> None:
        self._stack.append(entry)

    def pop(self) -> tuple[str, int, int] | None:
        if not self._stack:
            return None
        return self._stack.pop()


class DefinitionController:
    def __init__(self, window: Gedit.Window, history: CursorHistory) -> None:
        self._window = window
        self._history = history

    def trigger(self, server: LanguageServer, uri: str) -> None:
        view = self._window.get_active_view()
        buf = view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line, char = text_iter_to_utf16(cursor)

        # Capture current position for the history stack
        current_uri = buf.get_file().get_location().get_uri()
        self._history.push(
            (current_uri, cursor.get_line(), cursor.get_line_offset())
        )

        def on_response(msg: dict[str, Any]) -> None:
            kind, locs = classify_locations(msg.get("result"))
            if kind == "none":
                self._window.get_statusbar().push(0, "LSP: no definition found")
                # Pop the history entry we pushed — we didn't actually navigate
                self._history.pop()
                return
            if kind == "single":
                self._navigate_to(locs[0])
                return
            self._show_locations_popover(locs)

        server._send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": char},
            },
            on_response,
        )

    def go_back(self) -> None:
        entry = self._history.pop()
        if entry is None:
            return
        uri, line, col = entry
        self._navigate_to_uri_line_col(uri, line, col)

    def _navigate_to(self, location: dict[str, Any]) -> None:
        uri = location["uri"]
        line = location["range"]["start"]["line"]
        char_utf16 = location["range"]["start"]["character"]
        self._navigate_to_uri_line_utf16(uri, line, char_utf16)

    def _navigate_to_uri_line_utf16(
        self, uri: str, line: int, char_utf16: int
    ) -> None:
        navigate_to_uri(
            self._window, uri, line, char_utf16,
            to_iter=lambda buf: utf16_to_text_iter(buf, line, char_utf16),
        )

    def _navigate_to_uri_line_col(self, uri: str, line: int, col: int) -> None:
        navigate_to_uri(
            self._window, uri, line, col,
            to_iter=lambda buf: buf.get_iter_at_line_offset(line, col),
        )

    def _show_locations_popover(self, locs: list[dict[str, Any]]) -> None:
        # Minimal implementation for v0.1.0-alpha: show a simple chooser.
        active_view = self._window.get_active_view()
        if active_view is None:
            return
        popover = Gtk.Popover.new(active_view)  # type: ignore[call-arg]
        listbox = Gtk.ListBox()
        for loc in locs:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(
                label=f"{loc['uri']}:{loc['range']['start']['line'] + 1}"
            )
            label.set_xalign(0)
            row.add(label)  # type: ignore[attr-defined]
            listbox.add(row)  # type: ignore[attr-defined]

        def _on_row_activated(_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
            self._navigate_to(locs[row.get_index()])
            popover.popdown()

        listbox.connect("row-activated", _on_row_activated)
        popover.add(listbox)  # type: ignore[attr-defined]
        popover.show_all()  # type: ignore[attr-defined]
        popover.popup()
