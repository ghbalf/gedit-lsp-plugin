"""Right-click "LSP" submenu in the gedit text view popup.

Hooks `Gtk.TextView::populate-popup`. The submenu is inserted only when
the underlying `Gedit.Document` has a bridge attached — otherwise the
popup looks identical to plain gedit and we don't pretend to offer LSP
functionality the buffer can't deliver.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

if TYPE_CHECKING:
    from gedit_lsp.plugin import GeditLspPlugin

logger = logging.getLogger("gedit_lsp.popup")

MENU_ITEMS: list[tuple[str, str]] = [
    ("Show Hover",        "lsp-hover"),
    ("Go to Definition",  "lsp-goto-definition"),
    ("Go Back",           "lsp-go-back"),
    ("Format",            "lsp-format"),
    ("Show Server Logs…", "lsp-show-server-logs"),
]


def attach(view: Gtk.TextView, plugin: GeditLspPlugin) -> int:
    """Connect a populate-popup handler. Returns the handler id."""
    return view.connect("populate-popup", _on_populate_popup, plugin)


def _on_populate_popup(
    view: Gtk.TextView, popup: Gtk.Widget, plugin: GeditLspPlugin
) -> None:
    if not isinstance(popup, Gtk.Menu):  # type: ignore[attr-defined]
        return
    doc = view.get_buffer()
    if doc not in plugin._bridges:
        return
    submenu = _build_submenu(plugin)
    if submenu is None:
        return
    sep = Gtk.SeparatorMenuItem()  # type: ignore[attr-defined]
    sep.show()
    popup.append(sep)
    parent = Gtk.MenuItem.new_with_label("LSP")  # type: ignore[attr-defined]
    parent.set_submenu(submenu)
    parent.show()
    popup.append(parent)


def _build_submenu(plugin: GeditLspPlugin) -> Any:
    win = plugin.window
    app = win.get_application()
    submenu = Gtk.Menu()  # type: ignore[attr-defined]
    for label, action_name in MENU_ITEMS:
        item = Gtk.MenuItem.new_with_label(_label_with_accel(app, label, action_name))  # type: ignore[attr-defined]
        item.connect("activate", _on_item_activate, win, action_name)
        submenu.append(item)
    submenu.show_all()
    return submenu


def _label_with_accel(app: Gtk.Application | None, label: str, action_name: str) -> str:
    if app is None:
        return label
    accels = app.get_accels_for_action(f"win.{action_name}")
    if not accels:
        return label
    parsed = Gtk.accelerator_parse(accels[0])
    keyval, mods = parsed[-2], parsed[-1]
    if keyval == 0:
        return label
    return f"{label}  ({Gtk.accelerator_get_label(keyval, mods)})"


def _on_item_activate(
    _item: Any, win: Gtk.Window, action_name: str
) -> None:
    action = win.lookup_action(action_name)  # type: ignore[attr-defined]
    if action is not None:
        logger.info("popup: activating action win.%s", action_name)
        action.activate(None)
