"""CodeActionPopover — picker widget + its pure model.

The model class is GTK-free and fully unit-tested. The widget class
wraps the model and adds anchoring, ListBox rendering, and key
handling.

This widget is excluded from automated tests per the unit-tests-avoid-
GTK-widgets project invariant — Gtk.Popover SIGTRAPs in headless CI.
It is exercised by the codeAction integration test (Task 9).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gdk, Gtk, GtkSource  # noqa: E402

from gedit_lsp.code_action import NormalizedAction, group_by_kind  # noqa: E402


class CodeActionPopoverModel:
    """Pure-Python state for the codeAction picker.

    Tracks the action list, current selection index, and provides
    group_by_kind output for rendering. Disabled actions are visible
    in the list but unselectable — movement skips them.
    """

    def __init__(self, actions: list[NormalizedAction]) -> None:
        self._actions: list[NormalizedAction] = actions
        self._selected: int | None = self._first_enabled_index()

    def _first_enabled_index(self) -> int | None:
        for i, a in enumerate(self._actions):
            if a["disabled_reason"] is None:
                return i
        return None

    @property
    def selected_index(self) -> int | None:
        return self._selected

    def selected_action(self) -> NormalizedAction | None:
        if self._selected is None:
            return None
        return self._actions[self._selected]

    def move_down(self) -> None:
        if not self._actions or self._selected is None:
            return
        n = len(self._actions)
        i = self._selected
        for _ in range(n):
            i = (i + 1) % n
            if self._actions[i]["disabled_reason"] is None:
                self._selected = i
                return

    def move_up(self) -> None:
        if not self._actions or self._selected is None:
            return
        n = len(self._actions)
        i = self._selected
        for _ in range(n):
            i = (i - 1) % n
            if self._actions[i]["disabled_reason"] is None:
                self._selected = i
                return

    def grouped_rows(self) -> list[tuple[str, list[NormalizedAction]]]:
        """Return actions grouped by kind, in display order."""
        return group_by_kind(self._actions)


class CodeActionPopover:
    """Picker widget: Gtk.Popover anchored to the cursor with a
    Gtk.ListBox of action titles. Grouped by kind. Keyboard nav:
    ↑/↓ skip disabled rows, Enter commits, Escape cancels.
    """

    def __init__(self, view: GtkSource.View) -> None:
        self._view = view
        self._popover: Gtk.Popover | None = None
        self._model: CodeActionPopoverModel | None = None
        self._row_widgets: list[Gtk.ListBoxRow] = []
        self._on_commit: Callable[[NormalizedAction], None] | None = None
        self._on_cancel: Callable[[], None] | None = None

    def show(
        self,
        *,
        actions: list[NormalizedAction],
        on_commit: Callable[[NormalizedAction], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self._model = CodeActionPopoverModel(actions)

        popover = Gtk.Popover.new(self._view)  # type: ignore[call-arg]
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.set_modal(True)  # type: ignore[attr-defined]

        # Anchor at the cursor
        buf = self._view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        rect = self._view.get_iter_location(cursor)
        rect.x, rect.y = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y,
        )
        popover.set_pointing_to(rect)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._row_widgets = []
        # Iterate grouped output to preserve kind ordering (quickfix →
        # refactor.* → source.*), but render each action as a single row.
        # The `[kind.subkind]` badge in _make_row already conveys grouping;
        # adding bare-Label group headers to a Gtk.ListBox would have GTK
        # auto-wrap them as selectable rows, which is the bug that prompted
        # this change.
        for _group_name, group_actions in self._model.grouped_rows():
            for action in group_actions:
                row = self._make_row(action)
                listbox.add(row)  # type: ignore[attr-defined]
                self._row_widgets.append(row)
        listbox.connect("row-activated", self._on_row_activated)
        box.add(listbox)  # type: ignore[attr-defined]
        popover.add(box)  # type: ignore[attr-defined]

        popover.connect("key-press-event", self._on_key_press)
        popover.connect("closed", self._on_popover_closed)
        popover.show_all()  # type: ignore[attr-defined]
        popover.popup()
        self._popover = popover
        # Pre-select the first enabled row in the *rendered* order
        # (which is grouped by kind, not server order — so the model's
        # `selected_index` would be misindexed).
        for row in self._row_widgets:
            row_action = getattr(row, "_gedit_lsp_action", None)
            if row_action is not None and row_action.get("disabled_reason") is None:
                listbox.select_row(row)
                row.grab_focus()
                break

    def _make_row(self, action: NormalizedAction) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        badge = Gtk.Label(label=f"[{action['kind'] or 'action'}]")
        badge.get_style_context().add_class("dim-label")
        h.pack_start(badge, False, False, 0)  # type: ignore[attr-defined]
        title = Gtk.Label(label=action["title"])
        title.set_xalign(0.0)
        h.pack_start(title, True, True, 0)  # type: ignore[attr-defined]
        row.add(h)  # type: ignore[attr-defined]
        if action["disabled_reason"]:
            row.set_sensitive(False)
            row.set_tooltip_text(action["disabled_reason"])
        # Stash the action on the row for retrieval at commit time
        row._gedit_lsp_action = action  # type: ignore[attr-defined]
        return row

    def _on_row_activated(
        self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow,
    ) -> None:
        action = getattr(row, "_gedit_lsp_action", None)
        if action is None or action.get("disabled_reason"):
            return
        # Capture and clear the callbacks before popdown so the
        # subsequent 'closed' signal doesn't re-fire on_cancel.
        commit_cb = self._on_commit
        self._on_commit = None
        self._on_cancel = None
        if self._popover is not None:
            self._popover.popdown()
        if commit_cb is not None:
            commit_cb(action)

    def _on_key_press(self, _popover: Gtk.Popover, event: Any) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            if self._popover is not None:
                self._popover.popdown()
            return True
        return False

    def _on_popover_closed(self, _popover: Gtk.Popover) -> None:
        if self._on_cancel is not None:
            self._on_cancel()
