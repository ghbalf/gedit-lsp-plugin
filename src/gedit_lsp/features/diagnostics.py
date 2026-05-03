"""DiagnosticsController — render LSP diagnostics into a GtkSource buffer.

For each `publishDiagnostics` notification:
    1. Remove all `lsp-diag-*` tags from the buffer.
    2. For each diagnostic, convert UTF-16 range → Gtk.TextIter via utf16.py.
    3. Apply the severity-keyed tag.

Gutter marks and the bottom panel are added in M9.
"""
from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gtk, GtkSource, Pango

from gedit_lsp.utf16 import utf16_to_text_iter

_SEVERITY_TO_KEY = {1: "error", 2: "warning", 3: "info", 4: "hint"}
_UNDERLINE = {
    "error": Pango.Underline.ERROR,
    "single": Pango.Underline.SINGLE,
    "none": Pango.Underline.NONE,
}


class DiagnosticsController:
    def __init__(
        self,
        buffer: GtkSource.Buffer,
        severity_underlines: dict[str, str],
        severity_colors: dict[str, str] | None = None,
    ) -> None:
        self._buffer = buffer
        self._severity_underlines = severity_underlines
        self._severity_colors = severity_colors or {}
        self._ensure_tags()

    def _ensure_tags(self) -> None:
        table = self._buffer.get_tag_table()
        for sev, style in self._severity_underlines.items():
            name = f"lsp-diag-{sev}"
            if table.lookup(name) is None:
                self._buffer.create_tag(name)
                tag: Gtk.TextTag | None = table.lookup(name)
                if tag is not None:
                    tag.set_property("underline", _UNDERLINE.get(style, Pango.Underline.ERROR))
                    color = self._severity_colors.get(sev)
                    if color:
                        rgba = Gdk.RGBA()
                        if rgba.parse(color):
                            tag.set_property("underline-rgba-set", True)
                            tag.set_property("underline-rgba", rgba)

    def apply_diagnostics(self, diagnostics: list[dict[str, Any]]) -> None:
        self._clear_all_tags()
        for d in diagnostics:
            sev = _SEVERITY_TO_KEY.get(d.get("severity", 1), "error")
            tag = self._buffer.get_tag_table().lookup(f"lsp-diag-{sev}")
            if tag is None:
                continue
            r = d["range"]
            start = utf16_to_text_iter(self._buffer, r["start"]["line"], r["start"]["character"])
            end = utf16_to_text_iter(self._buffer, r["end"]["line"], r["end"]["character"])
            start, end = self._widen_for_visibility(start, end)
            self._buffer.apply_tag(tag, start, end)

    def _widen_for_visibility(
        self, start: Gtk.TextIter, end: Gtk.TextIter,
    ) -> tuple[Gtk.TextIter, Gtk.TextIter]:
        """Ensure the tagged range covers at least one character.

        LSP servers sometimes report zero-width ranges (e.g. pycodestyle
        W292 'no newline at end of file' anchors at EOF). Without
        widening, those produce no visible underline. We try forward
        first, fall back to backward.
        """
        if not start.equal(end):
            return start, end
        nudged = end.copy()
        if nudged.forward_char():
            return start, nudged
        nudged = start.copy()
        if nudged.backward_char():
            return nudged, end
        return start, end

    def _clear_all_tags(self) -> None:
        table = self._buffer.get_tag_table()
        start = self._buffer.get_start_iter()
        end = self._buffer.get_end_iter()
        for sev in self._severity_underlines:
            tag = table.lookup(f"lsp-diag-{sev}")
            if tag is not None:
                self._buffer.remove_tag(tag, start, end)
