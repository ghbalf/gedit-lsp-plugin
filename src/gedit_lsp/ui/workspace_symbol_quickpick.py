"""workspace/symbol quick-pick: pure QuickPickModel + Gtk.Popover widget.

QuickPickModel is GTK-free and fully unit-tested. WorkspaceSymbolQuickPick
(added in Task 4) is the Gtk.Popover and is smoke-only — widget
construction in headless unit tests SIGTRAPs CI (the mouse-hover lesson).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

from gedit_lsp.features.workspace_symbol import symbol_kind_label


class QuickPickModel:
    """Selection state over a flat symbol list.

    `set_results` re-selects index 0 (or None when empty). Movement
    wraps for line moves and clamps for page moves. No hint/placeholder
    rows ever enter the model — the widget renders hints separately.
    """

    def __init__(self) -> None:
        self._symbols: list[dict[str, Any]] = []
        self._selected: int | None = None

    def set_results(self, symbols: list[dict[str, Any]]) -> None:
        self._symbols = list(symbols)
        self._selected = 0 if self._symbols else None

    def select_index(self, index: int) -> None:
        """Select `index` directly if in range; no-op otherwise."""
        if 0 <= index < len(self._symbols):
            self._selected = index

    @property
    def results(self) -> list[dict[str, Any]]:
        return list(self._symbols)

    def selected(self) -> dict[str, Any] | None:
        if self._selected is None:
            return None
        return self._symbols[self._selected]

    @property
    def selected_index(self) -> int | None:
        return self._selected

    def move_down(self) -> None:
        if self._selected is None:
            return
        self._selected = (self._selected + 1) % len(self._symbols)

    def move_up(self) -> None:
        if self._selected is None:
            return
        self._selected = (self._selected - 1) % len(self._symbols)

    def page_down(self, n: int) -> None:
        if self._selected is None:
            return
        self._selected = min(self._selected + n, len(self._symbols) - 1)

    def page_up(self, n: int) -> None:
        if self._selected is None:
            return
        self._selected = max(self._selected - n, 0)


def _row_label(symbol: dict[str, Any]) -> str:
    """Single-line display string for a symbol row.

    Plain text only — never markup. A symbol literally named
    `<b>x</b>` must render verbatim, not as bold.
    """
    name = symbol.get("name", "")
    kind = symbol_kind_label(symbol.get("kind", 0))
    container = symbol.get("containerName") or ""
    loc = symbol.get("location") or {}
    uri = loc.get("uri", "")
    base = uri.rsplit("/", 1)[1] if "/" in uri else uri
    rng = loc.get("range") or {}
    line = rng.get("start", {}).get("line")
    where = base if line is None else f"{base}:{line + 1}"
    tail = " · ".join(p for p in (kind, container, where) if p)
    return f"{name}    {tail}" if tail else name


class WorkspaceSymbolQuickPick:
    """Cursor-anchored Gtk.Popover: a Gtk.Entry over a results TreeView.

    Smoke-only. Wraps a QuickPickModel for selection state. Focus stays
    in the entry; arrow/page/Enter/Escape are intercepted on the entry
    and routed to the model. Uses the callback-clear-before-popdown
    discipline so the `closed` signal's auto-cancel no-ops after an
    activation.
    """

    def __init__(self, window: Any) -> None:
        self._window = window
        self._popover: Gtk.Popover | None = None
        self._entry: Gtk.Entry | None = None
        self._tree: Gtk.TreeView | None = None
        self._store: Gtk.ListStore | None = None
        self._model = QuickPickModel()
        self._on_query: Callable[[str], None] | None = None
        self._on_activate: Callable[[dict[str, Any]], None] | None = None
        self._on_cancel: Callable[[], None] | None = None

    def show(
        self,
        *,
        seed: str,
        on_query: Callable[[str], None],
        on_activate: Callable[[dict[str, Any]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        if self._popover is not None:  # defensive: tear down a stale one
            self._on_query = self._on_activate = self._on_cancel = None
            self._popover.popdown()

        self._on_query = on_query
        self._on_activate = on_activate
        self._on_cancel = on_cancel
        self._model = QuickPickModel()

        view = self._window.get_active_view()
        popover = Gtk.Popover.new(view)  # type: ignore[call-arg]
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.set_modal(True)  # type: ignore[attr-defined]

        buf = view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        rect = view.get_iter_location(cursor)
        rect.x, rect.y = view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y,
        )
        popover.set_pointing_to(rect)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_size_request(520, 320)

        entry = Gtk.Entry()
        entry.set_text(seed)
        entry.select_region(0, -1)
        entry.set_placeholder_text("Search project symbols…")
        entry.connect("changed", self._on_entry_changed)
        entry.connect("key-press-event", self._on_entry_key)
        box.pack_start(entry, False, False, 0)  # type: ignore[attr-defined]

        store = Gtk.ListStore(str)  # type: ignore[call-arg]
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(False)
        tree.append_column(
            Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0)  # type: ignore[call-arg,arg-type]
        )
        tree.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(tree)  # type: ignore[attr-defined]
        box.pack_start(scrolled, True, True, 0)  # type: ignore[attr-defined]

        popover.add(box)  # type: ignore[attr-defined]
        popover.connect("closed", self._on_closed)
        popover.show_all()  # type: ignore[attr-defined]
        popover.popup()
        entry.grab_focus()
        entry.select_region(0, -1)

        self._popover = popover
        self._entry = entry
        self._tree = tree
        self._store = store
        self.set_results([], hint="Type to search symbols")

    def set_results(
        self, symbols: list[dict[str, Any]], *, hint: str | None = None
    ) -> None:
        if self._store is None:
            return
        self._model.set_results(symbols)
        self._store.clear()
        if not symbols:
            if hint:
                self._store.append([f"  {hint}"])  # type: ignore[no-untyped-call]
            return
        for sym in symbols:
            self._store.append([_row_label(sym)])  # type: ignore[no-untyped-call]
        self._sync_selection()

    def dismiss(self) -> None:
        if self._popover is not None:
            self._popover.popdown()

    # --- internals ---

    def _sync_selection(self) -> None:
        if self._tree is None:
            return
        idx = self._model.selected_index
        sel = self._tree.get_selection()
        if idx is None:
            sel.unselect_all()
            return
        path = Gtk.TreePath.new_from_indices([idx])
        sel.select_path(path)  # type: ignore[no-untyped-call]
        self._tree.scroll_to_cell(path, None, False, 0.0, 0.0)  # type: ignore[no-untyped-call]

    def _on_entry_changed(self, entry: Gtk.Entry) -> None:
        if self._on_query is not None:
            self._on_query(entry.get_text())

    def _on_entry_key(self, _entry: Gtk.Entry, event: Any) -> bool:
        kv = event.keyval
        if kv == Gdk.KEY_Escape:
            self._cancel_and_close()
            return True
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._activate_selected()
            return True
        if kv == Gdk.KEY_Down:
            self._model.move_down()
            self._sync_selection()
            return True
        if kv == Gdk.KEY_Up:
            self._model.move_up()
            self._sync_selection()
            return True
        if kv == Gdk.KEY_Page_Down:
            self._model.page_down(10)
            self._sync_selection()
            return True
        if kv == Gdk.KEY_Page_Up:
            self._model.page_up(10)
            self._sync_selection()
            return True
        return False

    def _on_row_activated(
        self, _tree: Gtk.TreeView, path: Gtk.TreePath, _col: Gtk.TreeViewColumn
    ) -> None:
        indices = path.get_indices()
        if indices:
            self._model.select_index(indices[0])
            self._activate_selected()

    def _activate_selected(self) -> None:
        sym = self._model.selected()
        if sym is None:
            return
        cb = self._on_activate
        self._on_query = self._on_activate = self._on_cancel = None
        if self._popover is not None:
            self._popover.popdown()
        if cb is not None:
            cb(sym)

    def _cancel_and_close(self) -> None:
        cb = self._on_cancel
        self._on_query = self._on_activate = self._on_cancel = None
        if self._popover is not None:
            self._popover.popdown()
        if cb is not None:
            cb()

    def _on_closed(self, popover: Gtk.Popover) -> None:
        # Ignore a `closed` emitted by a popover we've already replaced
        # (re-entrant show(): the old popover's deferred `closed` must
        # not null the new popover's refs or fire the new cancel).
        if popover is not self._popover:
            return
        cb = self._on_cancel
        self._on_query = self._on_activate = self._on_cancel = None
        self._popover = None
        self._entry = None
        self._tree = None
        self._store = None
        if cb is not None:
            cb()
