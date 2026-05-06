"""LSP completion feature — request shapes, response conversion, GtkSource provider.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GtkSource bindings (CompletionProvider class + Controller) are added in
later tasks.
"""
from __future__ import annotations

import contextlib
import dataclasses
import enum
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gedit_lsp.server import LanguageServer


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
    """Mirror render_hover_contents shape — strings, MarkupContent dicts,
    list-of-the-above (rare for completion but seen on misbehaving servers),
    None."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        return str(doc.get("value", ""))
    if isinstance(doc, list):
        return "\n\n".join(_stringify_documentation(c) for c in doc).strip()
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


def matched_trigger_suffix(text_before_cursor: str, trigger_chars: list[str]) -> str | None:
    """Return the longest entry from `trigger_chars` that ends `text_before_cursor`, or None.

    Handles both single-char (e.g. `.`) and multi-char (e.g. `->`) triggers.
    Empty trigger entries in the list are ignored. Length comparison is by
    Python `len()` (codepoints), which is fine for ASCII triggers.
    """
    best: str | None = None
    for t in trigger_chars:
        if t and text_before_cursor.endswith(t) and (best is None or len(t) > len(best)):
            best = t
    return best


import logging  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import GObject, Gtk, GtkSource  # noqa: E402

from gedit_lsp.utf16 import text_iter_to_utf16  # noqa: E402

logger = logging.getLogger("gedit_lsp.completion")


class _LspCompletionProposal(GObject.Object, GtkSource.CompletionProposal):
    """A single proposal exposed to GtkSource."""

    def __init__(self, lsp: LspProposal) -> None:
        GObject.Object.__init__(self)
        self.lsp = lsp

    def do_get_label(self) -> str:
        return self.lsp.label

    def do_get_text(self) -> str:
        return self.lsp.insert_text

    def do_get_info(self) -> str:
        # Used by the info popup; we render plain text (markdown is
        # stringified upstream).
        return self.lsp.documentation


class LspCompletionProvider(GObject.Object, GtkSource.CompletionProvider):
    """GtkSource.CompletionProvider that fires LSP completion requests.

    One instance per (buffer, server). The provider is registered with the
    view's CompletionContext and disposed on tab-removed / plugin
    deactivate (see `CompletionController.dispose` in plugin wiring).
    """

    def __init__(
        self,
        *,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: LanguageServer,
        uri: str,
    ) -> None:
        GObject.Object.__init__(self)
        self._view = view
        self._buffer = buffer
        self._server = server
        self._uri = uri
        self._last_was_incomplete = False
        self._inflight_id: int | None = None
        self._last_proposals: list[LspProposal] = []
        self._on_populated: Callable[[list[LspProposal]], None] | None = None

    def set_populate_callback(
        self, cb: Callable[[list[LspProposal]], None] | None,
    ) -> None:
        """Register (or unregister with None) a callback fired whenever
        `do_populate` receives a non-error response. Receives the parsed
        proposal list (may be empty)."""
        self._on_populated = cb

    def _handle_completion_response(
        self, msg: dict[str, Any], request_id: int,
    ) -> list[LspProposal]:
        """Process a completion response. Returns the parsed proposal list.

        Centralised so unit tests can drive the response path without
        constructing a GTK CompletionContext.

        Contract (pinned by tests):
          - id-mismatch: early-return []. Do NOT fire the callback or
            touch `_last_proposals` / `_last_was_incomplete` — a
            superseded request must not perturb in-flight state.
          - error: early-return []. Do NOT fire the callback. Leave
            `_last_was_incomplete` untouched so a prior incomplete
            state survives an error blip.
          - success (including `result=None`): update both
            `_last_was_incomplete` and `_last_proposals`, then fire
            the callback with the parsed list (possibly empty, so
            subscribers can clear UI).
        """
        if self._inflight_id is None or self._inflight_id != request_id:
            return []
        if msg.get("error"):
            logger.info("completion error: %r", msg.get("error"))
            return []
        result = msg.get("result")
        self._last_was_incomplete = response_is_incomplete(result)
        proposals = extract_completion_items(result)
        self._last_proposals = proposals
        if self._on_populated is not None:
            self._on_populated(proposals)
        return proposals

    def do_get_name(self) -> str:
        return "LSP"

    def do_get_priority(self) -> int:
        return 100  # higher than the default word provider (~10)

    def do_get_activation(self) -> GtkSource.CompletionActivation:
        # USER_REQUESTED so Ctrl+Space invokes us; INTERACTIVE so trigger
        # characters auto-fire as the user types.
        return GtkSource.CompletionActivation.USER_REQUESTED | GtkSource.CompletionActivation.INTERACTIVE  # type: ignore[return-value]

    def do_match(self, _context: GtkSource.CompletionContext) -> bool:
        cap = self._server.capability("completionProvider")
        return is_completion_supported(cap)

    def do_populate(self, context: GtkSource.CompletionContext) -> None:
        cap = self._server.capability("completionProvider")
        trigger_chars = trigger_characters_from(cap)

        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        line, char = text_iter_to_utf16(cursor)

        # Look back up to max-trigger-length chars to find a multi-char
        # trigger like `->` or `::`. Single-char triggers fall out of the
        # same suffix-match.
        matched = self._matched_trigger_at(cursor, trigger_chars)

        kind, trig_char = classify_trigger(
            typed_char=matched,
            trigger_chars=trigger_chars,
            list_is_incomplete=self._last_was_incomplete,
        )

        params = build_completion_params(
            uri=self._uri,
            line=line,
            character=char,
            trigger_kind=kind,
            trigger_character=trig_char,
        )

        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
            self._inflight_id = None

        # Mutable holder so the closure can match against the id we receive
        # back from _send_request — the id doesn't exist until after the call,
        # but the closure is captured before. This pattern is safe because
        # responses always arrive *after* _send_request returns (async via
        # GLib main loop).
        my_id: list[int | None] = [None]

        def on_response(msg: dict[str, Any]) -> None:
            # Discard if we've moved past this request — a superseded
            # request's response must NOT mutate state or push proposals
            # to a stale context. Match the prior id-mismatch behavior
            # (early return, no add_proposals call) before delegating.
            request_id = my_id[0]
            if request_id is None:
                return
            if self._inflight_id is None or self._inflight_id != request_id:
                return
            # Delegate response parsing + state mutation + callback firing
            # to the extracted helper. The GTK-side concern — pushing
            # into the context — stays here.
            proposals = self._handle_completion_response(msg, request_id=request_id)
            if msg.get("error"):
                # Match prior behavior: clear stale proposals from the
                # context on error.
                context.add_proposals(self, [], True)  # type: ignore[attr-defined]
                return
            gtk_proposals = [_LspCompletionProposal(p) for p in proposals]
            context.add_proposals(self, gtk_proposals, True)  # type: ignore[attr-defined]

        new_id = self._server._send_request(
            "textDocument/completion", params, on_response
        )
        # _send_request returns -1 if the transport is None (server still
        # starting / crashed). Store None in that case so we don't try to
        # cancel a nonsense id later.
        self._inflight_id = new_id if new_id != -1 else None
        my_id[0] = self._inflight_id

    def do_activate_proposal(
        self,
        _proposal: GtkSource.CompletionProposal,
        _iter: Gtk.TextIter,
    ) -> bool:
        # Returning False signals "use GtkSource's default activation",
        # which inserts proposal.get_text() at the iter. Snippet support
        # is a separate plan (out of scope for v0.2.0).
        return False

    def _matched_trigger_at(
        self, cursor: Gtk.TextIter, trigger_chars: list[str]
    ) -> str | None:
        non_empty = [t for t in trigger_chars if t]
        if not non_empty:
            return None
        max_len = max(len(t) for t in non_empty)
        start = cursor.copy()
        start.backward_chars(max_len)
        text_before = start.get_text(cursor)
        return matched_trigger_suffix(text_before, non_empty)


class CompletionController:
    """Per-buffer wrapper that registers/unregisters the LspCompletionProvider.

    Lifecycle: constructed when `_attach_document` runs; `dispose()` called
    from `plugin.py` on tab-removed or `do_deactivate`. Mirrors the disposer
    pattern used elsewhere in the plugin.
    """

    def __init__(
        self,
        *,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: LanguageServer,
        uri: str,
    ) -> None:
        self._view = view
        self._provider = LspCompletionProvider(
            view=view, buffer=buffer, server=server, uri=uri
        )
        completion = view.get_completion()  # type: ignore[attr-defined]
        if completion is not None:
            completion.add_provider(self._provider)

    @property
    def provider(self) -> LspCompletionProvider:
        return self._provider

    def dispose(self) -> None:
        completion = self._view.get_completion()  # type: ignore[attr-defined]
        if completion is not None:
            with contextlib.suppress(Exception):
                completion.remove_provider(self._provider)
