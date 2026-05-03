"""OutlineController + tree-building.

Hierarchical responses (DocumentSymbol[]) are converted directly. Flat
responses (SymbolInformation[]) are nested by `containerName` matching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Tepl", "6")
from gi.repository import Gtk
from gi.repository import Tepl  # type: ignore[attr-defined]

from gedit_lsp.utf16 import utf16_to_text_iter

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]


@dataclass
class SymbolNode:
    name: str
    kind: int
    range_start_line: int
    range_start_char: int
    selection_start_line: int
    selection_start_char: int
    children: list[SymbolNode] = field(default_factory=list)


def detect_response_format(items: list[dict[str, Any]]) -> str:
    """Return 'hierarchical' (DocumentSymbol[]) or 'flat' (SymbolInformation[])."""
    if not items:
        return "hierarchical"
    first = items[0]
    if "location" in first and "selectionRange" not in first:
        return "flat"
    return "hierarchical"


def build_tree(items: list[dict[str, Any]], fmt: str) -> list[SymbolNode]:
    if fmt == "hierarchical":
        return [_build_hier(it) for it in items]
    return _build_flat(items)


def _build_hier(it: dict[str, Any]) -> SymbolNode:
    r = it["range"]["start"]
    s = it.get("selectionRange", it["range"])["start"]
    return SymbolNode(
        name=it["name"],
        kind=it.get("kind", 0),
        range_start_line=r["line"],
        range_start_char=r["character"],
        selection_start_line=s["line"],
        selection_start_char=s["character"],
        children=[_build_hier(c) for c in it.get("children", [])],
    )


def _build_flat(items: list[dict[str, Any]]) -> list[SymbolNode]:
    by_name: dict[str, SymbolNode] = {}
    roots: list[SymbolNode] = []
    for it in items:
        r = it["location"]["range"]["start"]
        node = SymbolNode(
            name=it["name"],
            kind=it.get("kind", 0),
            range_start_line=r["line"],
            range_start_char=r["character"],
            selection_start_line=r["line"],
            selection_start_char=r["character"],
        )
        by_name[it["name"]] = node
        container = it.get("containerName")
        if container and container in by_name:
            by_name[container].children.append(node)
        else:
            roots.append(node)
    return roots


class OutlineController:
    """Side-panel TreeView populated from documentSymbol responses."""

    def __init__(
        self,
        window: Gedit.Window,
        refresh_debounce_ms: int,
        initial_delay_ms: int,
    ) -> None:
        self._window = window
        self._refresh_debounce_ms = refresh_debounce_ms
        self._initial_delay_ms = initial_delay_ms
        self._store = Gtk.TreeStore(str, int, int)  # type: ignore[call-arg]  # name, line, col
        self._tree = Gtk.TreeView(model=self._store)
        col = Gtk.TreeViewColumn("Symbol")  # type: ignore[arg-type]
        renderer = Gtk.CellRendererText()
        col.pack_start(renderer, True)
        col.add_attribute(renderer, "text", 0)
        self._tree.append_column(col)
        self._tree.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self._tree)  # type: ignore[attr-defined]
        scrolled.show_all()  # type: ignore[attr-defined]
        # Side panel is a TeplPanel (libgedit-tepl interface). Invoke the
        # interface method explicitly: bare `panel.add(...)` resolves to
        # the inherited Gtk.Container.add() instead and only takes one
        # argument.
        panel = window.get_side_panel()
        self._panel_item = Tepl.Panel.add(
            panel, scrolled, "lsp-outline", "LSP Outline", None
        )
        self._scrolled = scrolled

    def populate(self, items: list[dict[str, Any]]) -> None:
        fmt = detect_response_format(items)
        tree = build_tree(items, fmt)
        self._store.clear()
        for node in tree:
            self._insert(None, node)
        self._tree.expand_all()

    def _insert(self, parent_iter: Gtk.TreeIter | None, node: SymbolNode) -> None:
        it = self._store.append(  # type: ignore[no-untyped-call]
            parent_iter, [node.name, node.selection_start_line, node.selection_start_char]
        )
        for child in node.children:
            self._insert(it, child)

    def _on_row_activated(
        self, _view: Gtk.TreeView, path: Gtk.TreePath, _column: Gtk.TreeViewColumn
    ) -> None:
        it = self._store.get_iter(path)  # type: ignore[no-untyped-call]
        line, col = self._store.get(it, 1, 2)  # type: ignore[no-untyped-call]
        active_view = self._window.get_active_view()
        if active_view is None:
            return
        buf = active_view.get_buffer()
        target = utf16_to_text_iter(buf, line, col)
        buf.place_cursor(target)
        active_view.scroll_to_iter(target, 0.1, False, 0.0, 0.5)
