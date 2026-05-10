"""ReferencesController: textDocument/references request + 0/1/N dispatch.

Mirrors `DefinitionController` in shape — window-scoped, stateless
beyond the injected `ReferencesPanel`. `trigger(server, uri,
flush_pending_change)` reads the cursor, flushes any debounced
didChange (the edit-flush invariant), sends the LSP request, and
dispatches the response:

    none   -> status-bar message
    single -> direct navigate_to_uri jump (panel untouched)
    many   -> panel.set_results(locs) + panel.reveal()
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gedit_lsp.navigation import classify_locations, navigate_to_uri
from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]

    from gedit_lsp.server import LanguageServer
    from gedit_lsp.ui.references_panel import ReferencesPanel


logger = logging.getLogger("gedit_lsp.references")


class ReferencesController:
    def __init__(
        self,
        *,
        window: Gedit.Window,
        panel: ReferencesPanel,
    ) -> None:
        self._window = window
        self._panel = panel

    def trigger(
        self,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None],
    ) -> None:
        """Send `textDocument/references` for the cursor position in
        `uri`. Caller passes `flush_pending_change` (typically
        `bridge.flush_pending_change`) so this controller doesn't need
        to know about the bridge layer.
        """
        statusbar = self._window.get_statusbar()

        # Capability gate: skip the round-trip when the server has
        # already told us it can't help.
        if not server.capability("referencesProvider"):
            logger.info("references: server does not support referencesProvider")
            statusbar.push(0, "LSP: server does not support references")
            return

        view = self._window.get_active_view()
        if view is None:
            logger.info("references: no active view")
            return
        buf = view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line, char = text_iter_to_utf16(cursor)

        # Edit-flush invariant: ensure the server has the latest text.
        flush_pending_change()

        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
            "context": {"includeDeclaration": True},
        }

        def on_response(msg: dict[str, Any]) -> None:
            if msg.get("error"):
                logger.info("references: server error %r", msg.get("error"))
                statusbar.push(0, "LSP: references request failed")
                return
            kind, locs = classify_locations(msg.get("result"))
            if kind == "none":
                statusbar.push(0, "LSP: no references found")
                return
            if kind == "single":
                loc = locs[0]
                tgt_line = loc["range"]["start"]["line"]
                tgt_char = loc["range"]["start"]["character"]
                navigate_to_uri(
                    self._window, loc["uri"], tgt_line, tgt_char,
                    to_iter=lambda buf: utf16_to_text_iter(
                        buf, tgt_line, tgt_char
                    ),
                )
                return
            # many
            self._panel.set_results(locs)
            self._panel.reveal()

        logger.info("references: send line=%d char=%d", line, char)
        server._send_request("textDocument/references", params, on_response)
