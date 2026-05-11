"""LightbulbGutter — diagnostic-driven gutter indicator.

One per GtkSourceView. Subscribes to one server's diagnostics
listener, maintains the set of "lit" line numbers for its URI, and
renders a lightbulb icon in the gutter on those lines. Click on the
icon fires the `on_activate(line)` callback (typically the
CodeActionController's trigger entry point).

Disposal contract: call `dispose()` from the plugin's `tab-removed`
handler. Idempotent — see memory project_latent_diag_listener_cleanup.
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gdk, GdkPixbuf, Gtk, GtkSource

logger = logging.getLogger("gedit_lsp.lightbulb")

# Priority offset for the gutter renderer. Positive places the bulb
# to the right of the line-number column (closer to the text). Final
# value verified empirically with ./install.sh — adjust if it lands
# in the wrong column.
_GUTTER_PRIORITY = 20

_ICON_NAME = "dialog-information-symbolic"
_ICON_SIZE_PX = 12


class _LightbulbRenderer(GtkSource.GutterRendererPixbuf):
    """GtkSourceGutterRendererPixbuf subclass painting an icon on lit lines.

    Kept private and minimal — the renderer asks `_owner` for the current
    lit set via a callable, so the renderer doesn't hold state of its own.
    """

    def __init__(self, lit_lines_getter: Callable[[], set[int]]) -> None:
        super().__init__()
        self._lit_lines_getter = lit_lines_getter
        # Pre-render the pixbuf once
        icon_theme = Gtk.IconTheme.get_default()  # type: ignore[attr-defined]
        try:
            pixbuf = icon_theme.load_icon(
                _ICON_NAME, _ICON_SIZE_PX,
                Gtk.IconLookupFlags.USE_BUILTIN,  # type: ignore[attr-defined]
            )
        except Exception:  # noqa: BLE001 — theme misconfigured
            pixbuf = None
        self._pixbuf: GdkPixbuf.Pixbuf | None = pixbuf
        self.set_size(_ICON_SIZE_PX)  # type: ignore[attr-defined]

    def do_draw(
        self,
        cr: Any,
        background_area: Any,
        cell_area: Any,
        start: Gtk.TextIter,
        end: Gtk.TextIter,
        state: Any,
    ) -> None:
        line = start.get_line()
        if line not in self._lit_lines_getter():
            return
        if self._pixbuf is None:
            return
        # Render centered in cell
        x = cell_area.x + (cell_area.width - _ICON_SIZE_PX) // 2
        y = cell_area.y + (cell_area.height - _ICON_SIZE_PX) // 2
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, x, y)
        cr.paint()


class LightbulbGutter:
    """One per GtkSourceView. Maintains lit-line state and renderer
    attachment for one URI's diagnostics."""

    def __init__(
        self,
        *,
        view: Any,
        server: Any,
        uri: str,
        on_activate: Callable[[int], None],
    ) -> None:
        self._view = view
        self._uri = uri
        self._on_activate = on_activate
        self._lit_lines: set[int] = set()
        self._disposed = False

        self._renderer = _LightbulbRenderer(lambda: self._lit_lines)
        self._gutter = view.get_gutter(Gtk.TextWindowType.LEFT)
        self._gutter.insert(self._renderer, _GUTTER_PRIORITY)

        # Click handler on the renderer
        self._click_handler_id = self._renderer.connect(
            "activate", self._on_renderer_activated,
        )

        self._listener_disposer = server.add_diagnostics_listener(
            self._on_diagnostics,
        )

    def lit_lines(self) -> set[int]:
        """Return a copy of the current lit-line set (for tests)."""
        return set(self._lit_lines)

    def dispose(self) -> None:
        """Detach listener, remove renderer. Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        try:
            self._listener_disposer()
        except Exception:  # noqa: BLE001 — disposer should be safe; log if not
            logger.info("lightbulb: listener disposer raised")
        try:
            self._gutter.remove(self._renderer)
        except Exception:  # noqa: BLE001 — view may already be torn down
            logger.info("lightbulb: gutter renderer remove raised")

    def _on_diagnostics(self, params: dict[str, Any]) -> None:
        if params.get("uri") != self._uri:
            return
        new_lines: set[int] = set()
        for d in params.get("diagnostics", []):
            rng = d.get("range")
            if not isinstance(rng, dict):
                continue
            start = rng.get("start")
            if isinstance(start, dict) and isinstance(start.get("line"), int):
                new_lines.add(start["line"])
        self._lit_lines = new_lines
        with contextlib.suppress(Exception):
            self._view.queue_draw()

    def _on_renderer_activated(
        self, _renderer: Any, it: Gtk.TextIter, _area: Any, _event: Any,
    ) -> None:
        line = it.get_line()
        self._on_activate(line)

    # --- test seam ---
    def _fire_activate_for_test(self, *, line: int) -> None:
        self._on_activate(line)
