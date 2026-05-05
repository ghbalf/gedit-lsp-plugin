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
