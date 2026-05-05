"""LSP completion feature — request shapes, response conversion, GtkSource provider.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GtkSource bindings (CompletionProvider class + Controller) are added in
later tasks.
"""
from __future__ import annotations

import dataclasses
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


@dataclasses.dataclass(frozen=True)
class LspProposal:
    """Display-ready, GTK-free representation of a single completion proposal.

    `raw_item` retains the original LSP CompletionItem dict so we can pass
    it back to `completionItem/resolve` later.
    """
    label: str
    insert_text: str
    detail: str | None
    kind: int | None        # LSP CompletionItemKind enum value
    documentation: str
    sort_text: str
    filter_text: str
    raw_item: dict[str, Any]


def _stringify_documentation(doc: Any) -> str:
    """Mirror render_hover_contents shape — strings, MarkupContent dicts, None."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        return str(doc.get("value", ""))
    return ""


def lsp_item_to_proposal(item: dict[str, Any]) -> LspProposal:
    label = str(item.get("label", ""))
    return LspProposal(
        label=label,
        insert_text=str(item.get("insertText") or label),
        detail=item.get("detail"),
        kind=item.get("kind"),
        documentation=_stringify_documentation(item.get("documentation")),
        sort_text=str(item.get("sortText") or label),
        filter_text=str(item.get("filterText") or label),
        raw_item=item,
    )


def extract_completion_items(response: Any) -> list[LspProposal]:
    """Normalise both LSP response shapes (`CompletionItem[]` and
    `CompletionList`) and return a list of LspProposal."""
    if response is None:
        return []
    if isinstance(response, list):
        return [lsp_item_to_proposal(it) for it in response]
    if isinstance(response, dict):
        items = response.get("items") or []
        return [lsp_item_to_proposal(it) for it in items]
    return []


def response_is_incomplete(response: Any) -> bool:
    if isinstance(response, dict):
        return bool(response.get("isIncomplete", False))
    return False
