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
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.navigation import navigate_to_uri
from gedit_lsp.utf16 import utf16_to_text_iter

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


class WorkspaceSymbolController:
    """Window-scoped driver for the workspace/symbol live quick-pick.

    GTK-free. Owns the debounce timer id, an integer request token
    (stale-response guard), and the in-flight request id. `schedule`
    and `cancel` are injection seams (default GLib) so the debounce /
    cancel / token logic is unit-testable without a main loop.
    """

    def __init__(
        self,
        *,
        window: Any,
        quickpick: Any,
        config: Any,
        schedule: Callable[[int, Callable[[], Any]], int] = GLib.timeout_add,
        cancel: Callable[[int], Any] = GLib.source_remove,
    ) -> None:
        self._window = window
        self._quickpick = quickpick
        self._config = config
        self._schedule = schedule
        self._cancel = cancel
        self._server: Any = None
        self._token: int = 0
        self._timer_id: int | None = None
        self._inflight_id: int | None = None

    def trigger(
        self,
        server: Any,
        view: Any,
        flush_pending_change: Callable[[], None],
    ) -> None:
        if "workspaceSymbol" not in self._config.tunable("enabledFeatures"):
            logger.info("workspace-symbol: disabled via enabledFeatures")
            return
        statusbar = self._window.get_statusbar()
        if not server.capability("workspaceSymbolProvider"):
            logger.info("workspace-symbol: server lacks workspaceSymbolProvider")
            statusbar.push(
                0, "LSP: server does not support workspace symbol search"
            )
            return
        flush_pending_change()
        # Invalidate any previous quick-pick session still in flight.
        # Note: _token is intentionally NOT reset here — it increases
        # monotonically for the controller's lifetime so a stale
        # response from a prior session (LSP $/cancelRequest is only
        # advisory, so it may still arrive) can never collide with a
        # new session's token.
        if self._timer_id is not None:
            self._cancel(self._timer_id)
        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
        self._server = server
        self._timer_id = None
        self._inflight_id = None
        seed = seed_query(view.get_buffer())
        self._quickpick.show(
            seed=seed,
            on_query=self._on_query,
            on_activate=self._on_activate,
            on_cancel=self._on_cancel,
        )
        if seed:
            self._on_query(seed)

    def _on_query(self, text: str) -> None:
        if self._timer_id is not None:
            self._cancel(self._timer_id)
            self._timer_id = None
        debounce = self._config.tunable("workspaceSymbolDebounceMs")
        self._timer_id = self._schedule(debounce, lambda: self._fire(text))

    def _fire(self, text: str) -> bool:
        self._timer_id = None
        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
            self._inflight_id = None
        self._token += 1
        my = self._token
        if text == "":
            self._quickpick.set_results([], hint="Type to search symbols")
            return False
        self._inflight_id = self._server._send_request(
            "workspace/symbol",
            {"query": text},
            lambda msg: self._on_response(my, msg),
        )
        return False  # one-shot timer

    def _on_response(self, token: int, msg: dict[str, Any]) -> None:
        if token != self._token:
            logger.debug("workspace-symbol: stale response token %d", token)
            return
        self._inflight_id = None
        if msg.get("error"):
            logger.info("workspace-symbol: error %r", msg.get("error"))
            self._window.get_statusbar().push(
                0, "LSP: workspace symbol request failed"
            )
            return
        symbols = parse_symbol_results(msg.get("result"))
        if not symbols:
            self._quickpick.set_results([], hint="No symbols match")
        else:
            self._quickpick.set_results(symbols)

    def _on_activate(self, symbol: dict[str, Any]) -> None:
        loc = symbol.get("location") or {}
        uri = loc.get("uri")
        if not isinstance(uri, str):
            return
        rng = loc.get("range")
        if rng:
            self._navigate(uri, rng)
            return
        cap = self._server.capability("workspaceSymbolProvider")
        if isinstance(cap, dict) and cap.get("resolveProvider"):
            def _cb(msg: dict[str, Any]) -> None:
                if msg.get("error"):
                    self._navigate(uri, None)
                    return
                rloc = (msg.get("result") or {}).get("location") or {}
                rrng = rloc.get("range")
                if rrng and isinstance(rloc.get("uri"), str):
                    self._navigate(rloc["uri"], rrng)
                else:
                    self._navigate(uri, None)

            self._server._send_request("workspaceSymbol/resolve", symbol, _cb)
        else:
            self._navigate(uri, None)

    def _navigate(self, uri: str, rng: dict[str, Any] | None) -> None:
        if rng:
            line = rng["start"]["line"]
            char = rng["start"]["character"]
        else:
            line, char = 0, 0
        navigate_to_uri(
            self._window, uri, line, char,
            to_iter=lambda buf: utf16_to_text_iter(buf, line, char),
        )

    def _on_cancel(self) -> None:
        if self._timer_id is not None:
            self._cancel(self._timer_id)
            self._timer_id = None
        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
            self._inflight_id = None
        self._token += 1
