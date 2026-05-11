"""Bottom panel listing all diagnostics across all open buffers in the window."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from gedit_lsp.navigation import navigate_to_uri

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]


logger = logging.getLogger("gedit_lsp.diagnostics_panel")

_SEVERITY_LABEL = {1: "Error", 2: "Warning", 3: "Info", 4: "Hint"}


def _uri_basename(uri: str) -> str:
    """Display name for the File column. Percent-decoded, last path segment."""
    return unquote(uri.rsplit("/", 1)[-1]) if uri else ""


class DiagnosticsPanel:
    def __init__(self, window: Gedit.Window) -> None:
        self._window = window
        # cols: severity, file, line, message, source, uri (hidden)
        self._store = Gtk.ListStore(str, str, int, str, str, str)  # type: ignore[call-arg]
        self._view = Gtk.TreeView(model=self._store)
        for i, title in enumerate(["Severity", "File", "Line", "Message", "Source"]):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)  # type: ignore[call-arg,arg-type]
            self._view.append_column(col)
        self._view.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self._view)  # type: ignore[attr-defined]
        scrolled.show_all()  # type: ignore[attr-defined]
        panel = window.get_bottom_panel()
        panel.add_titled(scrolled, "lsp-diagnostics", "LSP Diagnostics")

    def clear_for_uri(self, uri: str) -> None:
        """Drop all rows whose hidden uri column matches `uri`."""
        self.update_for_uri(uri, [])

    def update_for_uri(self, uri: str, diagnostics: list[dict[str, Any]]) -> None:
        rows_to_remove: list[Gtk.TreePath] = []
        it = self._store.get_iter_first()
        while it:
            if self._store.get_value(it, 5) == uri:
                rows_to_remove.append(self._store.get_path(it))
            it = self._store.iter_next(it)  # type: ignore[no-untyped-call]
        for path in reversed(rows_to_remove):
            self._store.remove(self._store.get_iter(path))  # type: ignore[no-untyped-call]
        basename = _uri_basename(uri)
        for d in diagnostics:
            sev = _SEVERITY_LABEL.get(d.get("severity", 1), "Error")
            line = d["range"]["start"]["line"] + 1
            self._store.append(  # type: ignore[no-untyped-call]
                [sev, basename, line, d.get("message", ""), d.get("source", ""), uri]
            )

    def _on_row_activated(
        self,
        _view: Gtk.TreeView,
        path: Gtk.TreePath,
        _column: Gtk.TreeViewColumn,
    ) -> None:
        it = self._store.get_iter(path)  # type: ignore[no-untyped-call]
        line = self._store.get_value(it, 2) - 1
        uri = self._store.get_value(it, 5)
        logger.info("diagnostics-panel: navigate to uri=%s line=%d", uri, line)
        navigate_to_uri(self._window, uri, line, 0)
