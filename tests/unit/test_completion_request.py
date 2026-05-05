"""Tests for the LSP completion request param builder."""
from __future__ import annotations

from gedit_lsp.features.completion import (
    CompletionTriggerKind,
    build_completion_params,
)


def test_build_completion_params_invoked() -> None:
    params = build_completion_params(
        uri="file:///tmp/x.py", line=3, character=7,
        trigger_kind=CompletionTriggerKind.Invoked,
        trigger_character=None,
    )
    assert params == {
        "textDocument": {"uri": "file:///tmp/x.py"},
        "position": {"line": 3, "character": 7},
        "context": {"triggerKind": 1},
    }


def test_build_completion_params_trigger_character() -> None:
    params = build_completion_params(
        uri="file:///x", line=0, character=5,
        trigger_kind=CompletionTriggerKind.TriggerCharacter,
        trigger_character=".",
    )
    assert params["context"] == {"triggerKind": 2, "triggerCharacter": "."}


def test_build_completion_params_for_incomplete() -> None:
    params = build_completion_params(
        uri="file:///x", line=1, character=2,
        trigger_kind=CompletionTriggerKind.TriggerForIncompleteCompletions,
        trigger_character=None,
    )
    assert params["context"] == {"triggerKind": 3}


def test_build_completion_params_trigger_character_none_omits_key() -> None:
    """When trigger_kind is TriggerCharacter but no char is given (caller bug),
    triggerCharacter is omitted rather than crashing — documents the
    silent-omission contract of the truthiness guard.
    """
    params = build_completion_params(
        uri="file:///x", line=0, character=0,
        trigger_kind=CompletionTriggerKind.TriggerCharacter,
        trigger_character=None,
    )
    assert "triggerCharacter" not in params["context"]
    assert params["context"]["triggerKind"] == 2
