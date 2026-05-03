"""Crash-loop notification — Gtk.InfoBar on Gedit.Tab.set_info_bar()."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]


class CrashNotifier:
    def __init__(self, window: Gedit.Window) -> None:
        self._window = window
        self._active: dict[Gedit.Tab, Gtk.InfoBar] = {}

    def show_for_tab(
        self,
        tab: Gedit.Tab,
        message: str,
        on_restart: Callable[[], None],
        on_open_log: Callable[[], None],
        on_disable: Callable[[], None],
    ) -> None:
        if tab in self._active:
            return
        bar = Gtk.InfoBar()
        bar.set_message_type(Gtk.MessageType.WARNING)
        content = bar.get_content_area()  # type: ignore[attr-defined]
        content.add(Gtk.Label(label=message))
        bar.add_button("Restart", 1)
        bar.add_button("Open log", 2)
        bar.add_button("Disable for session", 3)

        def _on_response(_b: Gtk.InfoBar, response_id: int) -> None:
            self._dispatch(tab, response_id, on_restart, on_open_log, on_disable)

        bar.connect("response", _on_response)
        bar.show_all()  # type: ignore[attr-defined]
        tab.set_info_bar(bar)
        self._active[tab] = bar

    def _dispatch(
        self,
        tab: Gedit.Tab,
        response_id: int,
        on_restart: Callable[[], None],
        on_open_log: Callable[[], None],
        on_disable: Callable[[], None],
    ) -> None:
        bar = self._active.pop(tab, None)
        if bar is not None:
            tab.set_info_bar(None)
        if response_id == 1:
            on_restart()
        elif response_id == 2:
            on_open_log()
        elif response_id == 3:
            on_disable()
