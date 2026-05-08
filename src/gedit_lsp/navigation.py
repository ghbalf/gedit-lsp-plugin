"""Window-scoped navigation: jump to (uri, line, column) safely.

The native gedit method `Gedit.Window.create_tab_from_location` referenced
in older versions of this codebase does **not** exist in the gedit-46
typelib (no symbol in `libgedit-46.so`, no entry in `Gedit-3.0.gir`).
Calls hit a missing method and silently failed, so cross-file navigation
in this codebase has been quietly broken — only the same-active-document
fast path masked it. This helper replaces that pattern.

The right gedit API is `Gedit.commands_load_location(window, gfile,
encoding, line_pos, column_pos)` (a top-level command function, not a
window method); it handles "file already open" by re-using the existing
tab. We layer two synchronous fast paths on top so we don't pay an
async file-load round trip when the buffer is already in-memory.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk


def navigate_to_uri(
    window: Any,
    uri: str,
    line: int,
    column: int,
    *,
    to_iter: Callable[[Any], Gtk.TextIter] | None = None,
    load_location: Callable[..., None] | None = None,
    file_for_uri: Callable[[str], Any] = Gio.File.new_for_uri,
) -> None:
    """Navigate to (uri, line, column) in `window`, opening the file if needed.

    Branches in priority order:

    1. **Active document match** — place the cursor in-buffer and scroll.
       No tab churn.
    2. **Other open tab match** — `set_active_tab` then place the cursor.
       Synchronous, no file-load round trip.
    3. **Not open** — `Gedit.commands_load_location(window, gfile, None,
       line + 1, column)` opens the file and lands the cursor on
       completion. Note `line + 1`: gedit's commands API is 1-indexed for
       lines, while LSP and our own `line` argument are 0-indexed.
       `column` is 0-indexed in both.

    `to_iter(buf)` produces the `Gtk.TextIter` for branches 1 and 2; it
    lets callers pick the right offset semantics:

    - LSP UTF-16 char: `lambda buf: utf16_to_text_iter(buf, line, char_utf16)`
    - char-offset:     `lambda buf: buf.get_iter_at_line_offset(line, col)`
    - line-only:       default, `lambda buf: buf.get_iter_at_line(line)`

    `load_location` and `file_for_uri` are injection seams so unit tests
    can run without the gedit runtime — defaults call the real APIs and
    lazy-import `Gedit` only when branch 3 fires.
    """
    if to_iter is None:
        # Default: line-only positioning (caller's `column` is ignored
        # except as the column we pass to load_location below).
        captured_line = line

        def _default_to_iter(buf: Any) -> Gtk.TextIter:
            return cast(Gtk.TextIter, buf.get_iter_at_line(captured_line))

        to_iter = _default_to_iter

    gfile = file_for_uri(uri)

    active_view = window.get_active_view()
    active_doc = active_view.get_buffer() if active_view is not None else None
    if (
        active_doc is not None
        and active_doc.get_file().get_location().get_uri() == uri
    ):
        it = to_iter(active_doc)
        active_doc.place_cursor(it)
        active_view.scroll_to_iter(it, 0.1, False, 0.0, 0.5)
        return

    tab = window.get_tab_from_location(gfile)
    if tab is not None:
        window.set_active_tab(tab)
        view = tab.get_view()
        buf = view.get_buffer()
        it = to_iter(buf)
        buf.place_cursor(it)
        view.scroll_to_iter(it, 0.1, False, 0.0, 0.5)
        return

    # Branch 3: not yet open. Lazy import keeps unit tests off the
    # `Gedit` typelib, which only exists at runtime inside gedit.
    if load_location is None:
        gi.require_version("Gedit", "3.0")
        from gi.repository import Gedit  # type: ignore[attr-defined]
        load_location = Gedit.commands_load_location
    load_location(window, gfile, None, line + 1, column)
