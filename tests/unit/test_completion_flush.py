"""Regression test: do_populate must flush the bridge before firing the
LSP request.

If the debounced didChange hasn't been sent, pylsp/clangd answer the
completion against their pre-trigger snapshot (e.g. `os` with no `.`)
and return prefix matches against the wrong text. This is the same race
signatureHelp solves the same way; see
`project_edit_triggered_flush_invariant` in memory.

The test drives a real `LspCompletionProvider` against a real
`GtkSource.Buffer` and asserts the call order: flush THEN send.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import GtkSource

from gedit_lsp.features.completion import LspCompletionProvider


class _FakeServer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def capability(self, key: str) -> Any:
        if key == "completionProvider":
            return {"resolveProvider": False, "triggerCharacters": ["."]}
        return None

    def _send_request(
        self, method: str, params: dict[str, Any], _cb: Any
    ) -> int:
        self.requests.append((method, params))
        return len(self.requests)

    def cancel_request(self, _request_id: int) -> None:
        return None


def test_do_populate_flushes_pending_change_before_sending_request() -> None:
    """When do_populate fires, flush_pending_change must run BEFORE the
    server sees `_send_request`. Otherwise the server answers against a
    stale snapshot and returns prefix matches for the pre-trigger text."""
    server = _FakeServer()
    buf = GtkSource.Buffer()
    buf.set_text("os.")
    # Cursor is at end-of-buffer after set_text.
    view = GtkSource.View.new_with_buffer(buf)

    call_log: list[str] = []

    def flush() -> None:
        # Capture how many requests had been sent at the moment of flush.
        call_log.append(f"flush@{len(server.requests)}")

    provider = LspCompletionProvider(
        view=view,
        buffer=buf,
        server=server,
        uri="file:///x.py",
        flush_pending_change=flush,
    )

    provider.do_populate(MagicMock())

    # Flush must have happened, and at the moment it ran, no requests had
    # been sent yet — i.e. flush is strictly before send.
    assert call_log == ["flush@0"]
    assert len(server.requests) == 1
    assert server.requests[0][0] == "textDocument/completion"
