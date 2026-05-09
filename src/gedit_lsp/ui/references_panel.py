"""Bottom-panel "LSP References" tab: list of textDocument/references hits.

Mirrors `DiagnosticsPanel` (TreeView over a ListStore with hidden URI
and UTF-16 character columns), but populated on-demand via
`set_results(...)` rather than continuously updated like diagnostics.

Two pure helpers (`_basename_for_uri`, `fetch_preview_line`) are
exposed at module level so unit tests can exercise them without
instantiating the panel — which needs a real `Gedit.Window` and a
real bottom panel.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # type: ignore[attr-defined]

from gedit_lsp.navigation import navigate_to_uri
from gedit_lsp.utf16 import utf16_to_text_iter

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]


logger = logging.getLogger("gedit_lsp.references_panel")

# Truncate preview text to keep rows compact in narrow bottom panels.
_PREVIEW_MAX_CHARS = 120


def _basename_for_uri(uri: str) -> str:
    """Return the final path segment of a `file://` URI for display.

    Falls back to the full URI if no `/` is present (defensive — shouldn't
    happen with well-formed LSP `Location.uri` values, but guards us
    against crashes if a server returns something exotic).
    """
    if "/" not in uri:
        return uri
    return uri.rsplit("/", 1)[1]


def fetch_preview_line(uri: str, line: int, window: Any) -> str:
    """Best-effort source preview for `(uri, line)`.

    Strategy:
      1. If a `Gedit.Document` matching `uri` is currently open in
         `window`, read the line from the buffer (respects unsaved
         edits, no disk I/O).
      2. Else, read the file from disk synchronously.
      3. On any error (binary file, permission denied, line out of
         range, decode failure surviving `errors="replace"`), return
         `""`. The caller renders the row regardless.

    Result is `lstrip()`'d and truncated to `_PREVIEW_MAX_CHARS` with
    a trailing `…`.
    """
    text = _line_from_open_buffer(uri, line, window)
    if text is None:
        text = _line_from_disk(uri, line)
    return _format_preview(text)


def _line_from_open_buffer(uri: str, line: int, window: Any) -> str | None:
    try:
        docs = window.get_documents()
    except Exception:
        return None
    for doc in docs:
        try:
            doc_uri = doc.get_file().get_location().get_uri()
        except Exception:
            continue
        if doc_uri != uri:
            continue
        try:
            if line < 0 or line >= doc.get_line_count():
                return ""
            start = doc.get_iter_at_line(line)
            # End of line N is the start of line N+1 (or end-of-buffer).
            if line + 1 < doc.get_line_count():
                end = doc.get_iter_at_line(line + 1)
            else:
                end = doc.get_end_iter()
            return doc.get_text(start, end, False).rstrip("\n")
        except Exception:
            return ""
    return None


def _line_from_disk(uri: str, line: int) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return ""
    path = Path(unquote(parsed.path))
    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return ""
    return lines[line]


def _format_preview(text: str) -> str:
    out = text.lstrip()
    if len(out) > _PREVIEW_MAX_CHARS:
        out = out[:_PREVIEW_MAX_CHARS] + "…"
    return out


class ReferencesPanel:
    """Bottom-panel "LSP References" tab.

    Single-source: the controller calls `set_results()` once per
    `textDocument/references` response. Repeated calls replace the
    previous content. The panel persists across plugin
    deactivation/reactivation — same convention as `DiagnosticsPanel`.
    """

    COL_FILE = 0
    COL_LINE = 1
    COL_PREVIEW = 2
    COL_URI = 3
    COL_CHAR = 4

    def __init__(self, window: Gedit.Window) -> None:
        self._window = window
        self._store = Gtk.ListStore(str, int, str, str, int)  # type: ignore[call-arg]
        self._view = Gtk.TreeView(model=self._store)
        for i, title in enumerate(["File", "Line", "Preview"]):
            col = Gtk.TreeViewColumn(  # type: ignore[call-arg, arg-type]
                title, Gtk.CellRendererText(), text=i,
            )
            self._view.append_column(col)
        self._view.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self._view)  # type: ignore[attr-defined]
        scrolled.show_all()  # type: ignore[attr-defined]
        panel = window.get_bottom_panel()
        panel.add_titled(scrolled, "lsp-references", "LSP References")
        self._scrolled = scrolled

    def set_results(self, locations: list[dict[str, Any]]) -> None:
        """Replace the panel contents with rows for `locations`.

        Each location dict is the LSP `Location` shape: `{"uri": ...,
        "range": {"start": {"line": int, "character": int}, ...}}`.
        Preview text is fetched per-row via `fetch_preview_line`.
        """
        self.clear()
        for loc in locations:
            uri = loc["uri"]
            line = loc["range"]["start"]["line"]
            char = loc["range"]["start"]["character"]
            self._store.append([  # type: ignore[no-untyped-call]
                _basename_for_uri(uri),
                line + 1,                                # 1-based for display
                fetch_preview_line(uri, line, self._window),
                uri,
                char,
            ])

    def clear(self) -> None:
        self._store.clear()  # type: ignore[no-untyped-call]

    def reveal(self) -> None:
        """Make the bottom panel visible and select this tab."""
        panel = self._window.get_bottom_panel()
        try:
            panel.set_visible(True)
        except Exception:
            pass
        try:
            panel.set_visible_child_name("lsp-references")
        except Exception:
            # Older libgedit-tepl may use a different selection API; the
            # tab is still added and reachable manually.
            pass

    def _on_row_activated(
        self,
        _view: Gtk.TreeView,
        path: Gtk.TreePath,
        _column: Gtk.TreeViewColumn,
    ) -> None:
        it = self._store.get_iter(path)  # type: ignore[no-untyped-call]
        uri = self._store.get_value(it, self.COL_URI)
        line = self._store.get_value(it, self.COL_LINE) - 1  # back to 0-based
        char_utf16 = self._store.get_value(it, self.COL_CHAR)
        logger.info(
            "references-panel: navigate uri=%s line=%d char=%d",
            uri, line, char_utf16,
        )
        navigate_to_uri(
            self._window, uri, line, char_utf16,
            to_iter=lambda buf: utf16_to_text_iter(buf, line, char_utf16),
        )
