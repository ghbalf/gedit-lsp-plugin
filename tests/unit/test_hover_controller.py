"""Unit tests for HoverController — verifies request format and response rendering."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gdk, Gtk, GtkSource

from gedit_lsp.features.hover import build_hover_popover, render_hover_contents


def test_render_string_contents() -> None:
    text = render_hover_contents("hello")
    assert text == "hello"


def test_render_markup_contents_extracts_value() -> None:
    text = render_hover_contents({"kind": "markdown", "value": "# Title\n\nbody"})
    assert "Title" in text and "body" in text


def test_render_markedstring_array() -> None:
    text = render_hover_contents([{"language": "python", "value": "def f(): ..."}, "docstring"])
    assert "def f()" in text and "docstring" in text


def test_render_none_returns_empty() -> None:
    assert render_hover_contents(None) == ""


def test_build_hover_popover_returns_popover_pointing_at_iter() -> None:
    view = MagicMock(spec=Gtk.TextView)
    # iter_location returns a Gdk.Rectangle — use a real one so GTK's
    # set_pointing_to() accepts it.
    rect = Gdk.Rectangle()
    rect.x = 10
    rect.y = 20
    rect.width = 0
    rect.height = 14
    view.get_iter_location.return_value = rect
    view.buffer_to_window_coords.return_value = (10, 34)

    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    anchor = buf.get_iter_at_line_offset(0, 6)  # 'w' in "world"

    # Gtk.Popover.new() requires a real GObject parent; CI is headless so
    # the mock view cannot be passed.  Use patch.object on Gtk.Popover.new
    # to return a parent-less popover so the rest of the construction
    # (scrolled, inner_view, show_all) runs against the real GTK stack.
    real_popover = Gtk.Popover.new(None)
    with patch.object(Gtk.Popover, "new", return_value=real_popover):
        popover = build_hover_popover(view, anchor, "type: str")

    assert isinstance(popover, Gtk.Popover)
    view.get_iter_location.assert_called_once_with(anchor)
