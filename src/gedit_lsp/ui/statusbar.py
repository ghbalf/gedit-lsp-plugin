"""Statusbar indicator showing LSP state for the active buffer."""
from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]


class StatusbarIndicator:
    def __init__(self, window: Gedit.Window) -> None:
        self._window = window
        self._label = Gtk.Label(label="")
        self._label.set_margin_start(8)
        self._label.set_margin_end(8)
        statusbar = window.get_statusbar()
        statusbar.pack_end(self._label, False, False, 0)
        self._label.show()

    def set_state(self, text: str) -> None:
        self._label.set_text(text)

    def hide(self) -> None:
        self._label.hide()

    def show(self) -> None:
        self._label.show()

    def destroy(self) -> None:
        self._label.destroy()  # type: ignore[attr-defined]
