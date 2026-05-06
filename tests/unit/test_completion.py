"""Tests for `LspCompletionProvider` populate-callback wiring.

`do_populate` itself needs a real `GtkSource.CompletionContext` and view, so
we drive the response path via the extracted `_handle_completion_response`
method, which the closure inside `do_populate` delegates to.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from gedit_lsp.features.completion import LspCompletionProvider, LspProposal


def test_populate_callback_fires_with_proposals() -> None:
    server = MagicMock()
    server.capability.return_value = {"triggerCharacters": ["."]}

    captured: list[list[LspProposal]] = []

    # We can't call do_populate without a GTK context; assert the wiring
    # via the closure path. Bypass do_populate by invoking the response
    # handler shape directly: build a provider, register a callback,
    # simulate the on_response we'd otherwise be passed.
    provider = LspCompletionProvider.__new__(LspCompletionProvider)
    provider._server = server
    provider._inflight_id = 7
    provider._last_was_incomplete = False
    provider._last_proposals = []
    provider._on_populated = None
    provider.set_populate_callback(captured.append)

    msg = {"result": [{"label": "foo"}, {"label": "bar"}]}
    provider._handle_completion_response(msg, request_id=7)

    assert len(captured) == 1
    assert [p.label for p in captured[0]] == ["foo", "bar"]
    assert [p.label for p in provider._last_proposals] == ["foo", "bar"]
