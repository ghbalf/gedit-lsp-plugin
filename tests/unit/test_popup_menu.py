"""Unit tests for the right-click LSP popup-menu builder."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # type: ignore[attr-defined]

from gedit_lsp.ui import popup_menu


def test_label_without_app_returns_plain_label() -> None:
    assert popup_menu._label_with_accel(None, "Show Hover", "lsp-hover") == "Show Hover"


def test_label_with_unbound_action_returns_plain_label() -> None:
    app = Gtk.Application.new("test.lsp.unbound", 0)
    # Action exists in registration map but no accel set — expect plain label.
    assert popup_menu._label_with_accel(app, "Go Back", "lsp-go-back") == "Go Back"


def test_label_with_bound_action_includes_accel_hint() -> None:
    app = Gtk.Application.new("test.lsp.bound", 0)
    app.set_accels_for_action("win.lsp-hover", ["<Primary>k"])
    label = popup_menu._label_with_accel(app, "Show Hover", "lsp-hover")
    assert label.startswith("Show Hover")
    assert label != "Show Hover"  # accel suffix appended
    assert "(" in label and ")" in label
