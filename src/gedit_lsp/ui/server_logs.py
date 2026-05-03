"""Show buffered server stderr in a read-only dialog.

The dialog is a one-shot snapshot: open it, see what's been captured so
far, close it. To see lines published after the dialog opened, close
and re-open. Keeping the polish minimal — most users only need this
for "why didn't pylsp start" forensics, where a snapshot is enough.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango

if TYPE_CHECKING:
    from gedit_lsp.server import LanguageServer


def show(parent: Gtk.Window, server: LanguageServer) -> None:
    title = f"LSP server logs — {server.language_id}"
    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=False)
    dialog.set_default_size(800, 500)
    dialog.add_button("Close", Gtk.ResponseType.CLOSE)

    box = dialog.get_content_area()
    header = Gtk.Label()
    header.set_xalign(0.0)
    header.set_margin_start(8)
    header.set_margin_end(8)
    header.set_margin_top(8)
    header.set_margin_bottom(4)
    header.set_selectable(True)
    header.set_markup(_header_markup(server))
    box.pack_start(header, expand=False, fill=False, padding=0)  # type: ignore[attr-defined]

    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_hexpand(True)
    scrolled.set_vexpand(True)

    view = Gtk.TextView()
    view.set_editable(False)
    view.set_cursor_visible(False)
    view.set_monospace(True)
    view.override_font(Pango.FontDescription.from_string("monospace 10"))  # type: ignore[attr-defined]

    buf = view.get_buffer()
    lines = server.recent_stderr()
    text = "\n".join(lines) if lines else "(no stderr captured yet)"
    buf.set_text(text)
    end = buf.get_end_iter()
    buf.place_cursor(end)
    view.scroll_to_iter(end, 0.0, False, 0.0, 0.0)

    scrolled.add(view)  # type: ignore[attr-defined]
    box.pack_start(scrolled, expand=True, fill=True, padding=0)  # type: ignore[attr-defined]

    dialog.connect("response", lambda d, _r: d.destroy())
    dialog.show_all()  # type: ignore[attr-defined]


def _header_markup(server: LanguageServer) -> str:
    cmd = " ".join(server.command)
    return (
        f"<b>Language:</b> {_escape(server.language_id)}    "
        f"<b>State:</b> {_escape(server.state.value)}\n"
        f"<b>Root:</b> <tt>{_escape(server.root_path)}</tt>\n"
        f"<b>Command:</b> <tt>{_escape(cmd)}</tt>"
    )


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
