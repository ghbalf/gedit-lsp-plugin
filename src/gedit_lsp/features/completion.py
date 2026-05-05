"""LSP completion feature — request shapes, response conversion, GtkSource provider.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GtkSource bindings (CompletionProvider class + Controller) are added in
later tasks.
"""
from __future__ import annotations

import enum
from typing import Any


class CompletionTriggerKind(enum.IntEnum):
    """Subset of LSP CompletionTriggerKind we use."""
    Invoked = 1
    TriggerCharacter = 2
    TriggerForIncompleteCompletions = 3


def build_completion_params(
    *,
    uri: str,
    line: int,
    character: int,
    trigger_kind: CompletionTriggerKind,
    trigger_character: str | None,
) -> dict[str, Any]:
    """Build the params dict for a `textDocument/completion` request.

    `trigger_character` is included only when `trigger_kind` is
    `TriggerCharacter`; per LSP spec, omit it otherwise.
    """
    context: dict[str, Any] = {"triggerKind": int(trigger_kind)}
    if trigger_kind is CompletionTriggerKind.TriggerCharacter and trigger_character:
        context["triggerCharacter"] = trigger_character
    return {
        "textDocument": {"uri": uri},
        "position": {"line": line, "character": character},
        "context": context,
    }


def is_completion_supported(capability: dict[str, Any] | None) -> bool:
    """Return True if the server's `completionProvider` capability is present
    and has any concrete configuration. We treat `None` and `{}` as "not
    supported" — a server that returns an empty completionProvider gives us
    no trigger characters and no resolveProvider hint, so there's nothing
    to wire up.
    """
    return bool(capability)


def trigger_characters_from(capability: dict[str, Any] | None) -> list[str]:
    if not capability:
        return []
    return list(capability.get("triggerCharacters", []) or [])


def resolve_provider_from(capability: dict[str, Any] | None) -> bool:
    if not capability:
        return False
    return bool(capability.get("resolveProvider", False))


def classify_trigger(
    *,
    typed_char: str | None,
    trigger_chars: list[str],
    list_is_incomplete: bool,
) -> tuple[CompletionTriggerKind, str | None]:
    """Map (typed_char, server trigger chars, prior isIncomplete) to an LSP
    CompletionContext shape.

    Returns (kind, character_to_send).

    The caller is responsible for matching multi-character triggers (e.g.
    `->`); if it determined a multi-char suffix matched, it passes that
    suffix as `typed_char`. We only check for membership in `trigger_chars`.
    """
    if list_is_incomplete:
        return (CompletionTriggerKind.TriggerForIncompleteCompletions, None)
    if typed_char is not None and typed_char in trigger_chars:
        return (CompletionTriggerKind.TriggerCharacter, typed_char)
    return (CompletionTriggerKind.Invoked, None)
