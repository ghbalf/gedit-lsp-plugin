"""workspace/symbol: pure helpers + WorkspaceSymbolController.

This module is GTK-free. `seed_query` touches a Gtk.TextBuffer, which
is a model object (no widget realization), so it is unit-testable
headless — unlike View/Window/Popover, which SIGTRAP without DISPLAY.

`parse_symbol_results` returns the server's original item dicts after
validation (it does not rebuild them) so server-specific fields such
as `data` survive for `workspaceSymbol/resolve`. Consumers read
`kind`/`containerName` defensively via `.get(...)`.
"""
from __future__ import annotations

import logging
import string
from typing import Any

logger = logging.getLogger("gedit_lsp.workspace_symbol")

_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_")

# LSP SymbolKind (1–26) → short display label.
_KIND_LABELS: dict[int, str] = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
    6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
    11: "interface", 12: "function", 13: "variable", 14: "constant",
    15: "string", 16: "number", 17: "boolean", 18: "array", 19: "object",
    20: "key", 21: "null", 22: "enum-member", 23: "struct", 24: "event",
    25: "operator", 26: "type-parameter",
}


def symbol_kind_label(kind: int) -> str:
    """LSP SymbolKind int → short label; unknown/out-of-range → 'symbol'."""
    return _KIND_LABELS.get(kind, "symbol")


def parse_symbol_results(result: Any) -> list[dict[str, Any]]:
    """Validate a workspace/symbol response into a flat list of items.

    Accepts SymbolInformation[] and WorkspaceSymbol[] (the latter may
    carry a `location` with only `uri` and no `range`). Drops anything
    not a dict, lacking a string `name`, or lacking a `location` dict
    with a `uri`. `null` / non-list / garbage → `[]`.
    """
    if not isinstance(result, list):
        return []
    out: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("name"), str):
            continue
        loc = item.get("location")
        if not isinstance(loc, dict) or not isinstance(loc.get("uri"), str):
            continue
        out.append(item)
    return out


def seed_query(buf: Any) -> str:
    """Initial quick-pick query for a Gtk.TextBuffer.

    Precedence: a non-empty selection wins; else the identifier run
    ([A-Za-z0-9_]) around the insert mark; else "". All seed
    precedence lives here so the controller stays trivial.
    """
    if buf.get_has_selection():
        bounds = buf.get_selection_bounds()
        if bounds:
            start, end = bounds
            return str(buf.get_text(start, end, False))

    cursor = buf.get_iter_at_mark(buf.get_insert())
    line_start = buf.get_iter_at_line(cursor.get_line())
    line_end = line_start.copy()
    if not line_end.ends_line():
        line_end.forward_to_line_end()
    line_text = str(buf.get_text(line_start, line_end, False))

    col = cursor.get_line_offset()
    if col > len(line_text):
        col = len(line_text)
    s = col
    while s > 0 and line_text[s - 1] in _IDENT_CHARS:
        s -= 1
    e = col
    while e < len(line_text) and line_text[e] in _IDENT_CHARS:
        e += 1
    return line_text[s:e]
