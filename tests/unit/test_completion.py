"""Tests for `LspCompletionProvider` populate-callback wiring.

`do_populate` itself needs a real `GtkSource.CompletionContext` and view, so
we drive the response path via the extracted `_handle_completion_response`
method, which the closure inside `do_populate` delegates to.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from gedit_lsp.features.completion import LspCompletionProvider, LspProposal


def _make_provider() -> tuple[LspCompletionProvider, list[list[LspProposal]]]:
    """Build a bare provider with the attributes `_handle_completion_response`
    touches, plus a list to capture callback invocations.

    Bypasses `__init__` (which needs GTK objects) via `__new__` — cheap
    insurance against attribute drift since every test exercises the same
    set of fields.
    """
    server = MagicMock()
    captured: list[list[LspProposal]] = []

    provider = LspCompletionProvider.__new__(LspCompletionProvider)
    provider._server = server
    provider._inflight_id = 7
    provider._last_was_incomplete = False
    provider._last_proposals = []
    provider._on_populated = None
    provider.set_populate_callback(captured.append)
    return provider, captured


def test_populate_callback_fires_with_proposals() -> None:
    provider, captured = _make_provider()

    msg = {"result": [{"label": "foo"}, {"label": "bar"}]}
    provider._handle_completion_response(msg, request_id=7)

    assert len(captured) == 1
    assert [p.label for p in captured[0]] == ["foo", "bar"]
    assert [p.label for p in provider._last_proposals] == ["foo", "bar"]


def test_handle_response_id_mismatch_does_not_fire_callback() -> None:
    """A superseded request's response must NOT fire the callback,
    mutate _last_proposals, or flip _last_was_incomplete."""
    provider, captured = _make_provider()
    provider._last_was_incomplete = True  # pre-set so we can detect mutation

    # request_id != _inflight_id -> id-mismatch path
    msg = {"result": [{"label": "stale"}]}
    out = provider._handle_completion_response(msg, request_id=99)

    assert out == []
    assert captured == []  # callback NOT fired
    assert provider._last_proposals == []  # cache untouched
    assert provider._last_was_incomplete is True  # state preserved


def test_handle_response_error_does_not_fire_callback() -> None:
    """An error response must NOT fire the callback or mutate
    _last_was_incomplete (so a prior incomplete state survives an error
    blip — matches pre-refactor behavior)."""
    provider, captured = _make_provider()
    provider._last_was_incomplete = True

    msg = {"error": {"code": -32603, "message": "boom"}}
    out = provider._handle_completion_response(msg, request_id=7)

    assert out == []
    assert captured == []
    assert provider._last_was_incomplete is True


def test_handle_response_null_result_fires_callback_with_empty_list() -> None:
    """LSP allows result=None for 'no proposals'; we treat it as the
    empty list, fire the callback (so subscribers can clear UI), and
    clear _last_was_incomplete."""
    provider, captured = _make_provider()
    provider._last_was_incomplete = True

    msg = {"result": None}
    out = provider._handle_completion_response(msg, request_id=7)

    assert out == []
    assert captured == [[]]  # callback fired with empty list
    assert provider._last_was_incomplete is False  # response_is_incomplete(None) == False
