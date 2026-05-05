"""Tests for classify_trigger — maps a typed character + state to LSP trigger."""
from __future__ import annotations

from gedit_lsp.features.completion import (
    CompletionTriggerKind,
    classify_trigger,
)


def test_classify_user_invoked_no_char() -> None:
    kind, char = classify_trigger(typed_char=None, trigger_chars=[".", "->"], list_is_incomplete=False)
    assert kind is CompletionTriggerKind.Invoked
    assert char is None


def test_classify_typed_known_trigger_char() -> None:
    kind, char = classify_trigger(typed_char=".", trigger_chars=[".", "->"], list_is_incomplete=False)
    assert kind is CompletionTriggerKind.TriggerCharacter
    assert char == "."


def test_classify_typed_unknown_char() -> None:
    # User typed a regular letter — not a trigger character, but maybe we are
    # filtering an existing list. Treat as Invoked (regular re-fetch).
    kind, char = classify_trigger(typed_char="x", trigger_chars=[".", "->"], list_is_incomplete=False)
    assert kind is CompletionTriggerKind.Invoked
    assert char is None


def test_classify_incomplete_continuation() -> None:
    # The previous response had isIncomplete=true; the user keeps typing,
    # we re-request to extend the list.
    kind, char = classify_trigger(typed_char="x", trigger_chars=[".", "->"], list_is_incomplete=True)
    assert kind is CompletionTriggerKind.TriggerForIncompleteCompletions
    assert char is None


def test_classify_multichar_trigger() -> None:
    # `->` is a 2-char trigger. The classifier sees the latest typed
    # character (`>`), but matching a multichar trigger requires looking at
    # context. For v1 we match a multichar trigger only when the typed_char
    # equals one of the listed strings exactly — i.e. we don't reconstruct
    # buffer suffixes here.
    kind, _ = classify_trigger(typed_char=">", trigger_chars=[".", "->"], list_is_incomplete=False)
    # `>` alone isn't in trigger_chars, so this is Invoked.
    assert kind is CompletionTriggerKind.Invoked

    # If the caller passes the actual matched suffix (`->`), we honour it.
    kind, char = classify_trigger(typed_char="->", trigger_chars=[".", "->"], list_is_incomplete=False)
    assert kind is CompletionTriggerKind.TriggerCharacter
    assert char == "->"
