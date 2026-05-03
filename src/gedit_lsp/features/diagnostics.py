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
# When two diagnostics overlap (e.g. pyflakes Error + pycodestyle Warning on
# the same line), GTK uses tag priority to decide which underline-rgba wins.
# Higher number = higher priority. We want the most-severe diagnostic's color
# to be the visible one.
_SEVERITY_PRIORITY = {"hint": 0, "info": 1, "warning": 2, "error": 3}


def _subtract_intervals(
    s: int, e: int, occupied: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return the sub-intervals of [s, e) not covered by `occupied`.

    `occupied` must be sorted, disjoint, half-open intervals.
    """
    result: list[tuple[int, int]] = []
    cur = s
    for os, oe in occupied:
        if oe <= cur:
            continue
        if os >= e:
            break
        if cur < os:
            result.append((cur, os))
        cur = max(cur, oe)
        if cur >= e:
            return result
    if cur < e:
        result.append((cur, e))
    return result


def _union_intervals(
    intervals: list[tuple[int, int]], s: int, e: int,
) -> list[tuple[int, int]]:
    """Insert [s, e) into the sorted, disjoint `intervals`, merging overlaps.

    Returns the resulting sorted, disjoint interval list.
    """
    out: list[tuple[int, int]] = []
    placed = False
    for os, oe in intervals:
        if oe < s:
            out.append((os, oe))
        elif e < os:
            if not placed:
                out.append((s, e))
                placed = True
            out.append((os, oe))
        else:
            s = min(s, os)
            e = max(e, oe)
    if not placed:
        out.append((s, e))
    return out


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
        # Create in priority-ascending order so error is created last and
        # gets the highest tag-priority slot — its underline-rgba wins on
        # ranges that have multiple severities tagged.
        ordered = sorted(
            self._severity_underlines.items(),
            key=lambda kv: _SEVERITY_PRIORITY.get(kv[0], 0),
        )
        for sev, style in ordered:
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
        # Sort by severity ASC (Error=1 first). Apply each diagnostic only
        # to the sub-ranges not already claimed by a higher-severity
        # diagnostic. This guarantees any char is covered by exactly one
        # lsp-diag-* tag, so the visible color matches the most-severe
        # finding regardless of how GTK/Pango resolve overlapping
        # underline-rgba in the AttrList.
        by_severity = sorted(diagnostics, key=lambda d: d.get("severity", 1))
        occupied: list[tuple[int, int]] = []
        for d in by_severity:
            sev = _SEVERITY_TO_KEY.get(d.get("severity", 1), "error")
            tag = self._buffer.get_tag_table().lookup(f"lsp-diag-{sev}")
            if tag is None:
                continue
            r = d["range"]
            s_iter = utf16_to_text_iter(self._buffer, r["start"]["line"], r["start"]["character"])
            e_iter = utf16_to_text_iter(self._buffer, r["end"]["line"], r["end"]["character"])
            s_iter, e_iter = self._widen_for_visibility(s_iter, e_iter)
            s = s_iter.get_offset()
            e = e_iter.get_offset()
            if e <= s:
                continue
            for fs, fe in _subtract_intervals(s, e, occupied):
                si = self._buffer.get_iter_at_offset(fs)
                ei = self._buffer.get_iter_at_offset(fe)
                self._buffer.apply_tag(tag, si, ei)
            occupied = _union_intervals(occupied, s, e)

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
