"""LSP signatureHelp — request shapes, response normalisation, GTK popover.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GTK-bound class `SignatureHelpController` is added at the bottom and wires
the helpers to a `Gtk.Popover` anchored at the cursor.
"""
from __future__ import annotations

import contextlib
import dataclasses
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gedit_lsp.server import LanguageServer


def is_signature_help_supported(capability: dict[str, Any] | None) -> bool:
    """Server's `signatureHelpProvider` is present and non-empty."""
    return bool(capability)


def signature_trigger_chars(capability: dict[str, Any] | None) -> list[str]:
    if not capability:
        return []
    return list(capability.get("triggerCharacters", []) or [])


def signature_retrigger_chars(capability: dict[str, Any] | None) -> list[str]:
    """Server-suggested chars on which to re-fire during an active session.

    Falls back to `triggerCharacters` when the server doesn't advertise a
    distinct retrigger set — most servers conflate them.
    """
    if not capability:
        return []
    chars = capability.get("retriggerCharacters")
    if chars is None:
        return signature_trigger_chars(capability)
    return list(chars or [])


def build_signature_help_params(
    *,
    uri: str,
    line: int,
    character: int,
    trigger_character: str | None,
    is_retrigger: bool,
) -> dict[str, Any]:
    """Build params for `textDocument/signatureHelp`.

    `triggerKind`: 1=Invoked, 2=TriggerCharacter, 3=ContentChange (used
    while a session is active and the user is typing args).
    `triggerCharacter` is included only with kind=2.
    """
    if trigger_character:
        kind = 2
    elif is_retrigger:
        kind = 3
    else:
        kind = 1

    context: dict[str, Any] = {"triggerKind": kind, "isRetrigger": is_retrigger}
    if trigger_character:
        context["triggerCharacter"] = trigger_character
    return {
        "textDocument": {"uri": uri},
        "position": {"line": line, "character": character},
        "context": context,
    }


@dataclasses.dataclass(frozen=True)
class SignatureSegments:
    """Three-part split of a signature label by the active parameter span."""
    prefix: str
    active: str
    suffix: str


def split_signature_by_active_param(
    signature: dict[str, Any], active_parameter: int,
) -> SignatureSegments:
    """Slice the signature label so the active parameter can be visually marked.

    Returns (prefix, active, suffix). When the active-parameter index is out
    of range OR the parameter label can't be located in the signature label,
    returns (label, "", "") — caller renders the whole signature without
    highlighting rather than crashing.

    Parameter labels arrive in two shapes per spec: a `[start, end]` offset
    pair into the signature label (preferred — handles defaults, varargs,
    etc.) or a substring to find. Substring fallback uses first match.
    """
    label = str(signature.get("label", ""))
    params = signature.get("parameters") or []
    if not (0 <= active_parameter < len(params)):
        return SignatureSegments(label, "", "")

    p = params[active_parameter]
    if not isinstance(p, dict):
        return SignatureSegments(label, "", "")
    p_label = p.get("label")
    if isinstance(p_label, list) and len(p_label) == 2:
        try:
            start, end = int(p_label[0]), int(p_label[1])
        except (TypeError, ValueError):
            return SignatureSegments(label, "", "")
        if 0 <= start <= end <= len(label):
            return SignatureSegments(label[:start], label[start:end], label[end:])
        return SignatureSegments(label, "", "")
    if isinstance(p_label, str) and p_label:
        idx = label.find(p_label)
        if idx >= 0:
            return SignatureSegments(
                label[:idx], p_label, label[idx + len(p_label):],
            )
    return SignatureSegments(label, "", "")


def _stringify_doc(doc: Any) -> str:
    """Mirror render_hover_contents for MarkupContent / string / None."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        return str(doc.get("value", ""))
    return ""


@dataclasses.dataclass(frozen=True)
class ParsedSignatureHelp:
    """Display-ready, GTK-free signature-help payload."""
    segments: SignatureSegments
    documentation: str
    signature_count: int
    active_signature_index: int


def parse_signature_help(response: Any) -> ParsedSignatureHelp | None:
    """Extract the active signature + active parameter from an LSP response.

    Returns None when the response is null/empty or no usable signature is
    present. Per LSP 3.16+, `signature.activeParameter` overrides the
    top-level `activeParameter` when both are present.
    """
    if not isinstance(response, dict):
        return None
    signatures = response.get("signatures") or []
    if not signatures:
        return None

    try:
        active_sig = int(response.get("activeSignature") or 0)
    except (TypeError, ValueError):
        active_sig = 0
    if not (0 <= active_sig < len(signatures)):
        active_sig = 0

    sig = signatures[active_sig]
    if not isinstance(sig, dict):
        return None

    sig_active_param = sig.get("activeParameter")
    if sig_active_param is None:
        sig_active_param = response.get("activeParameter") or 0
    try:
        active_param = int(sig_active_param)
    except (TypeError, ValueError):
        active_param = 0

    segments = split_signature_by_active_param(sig, active_param)

    # Prefer parameter-level doc (more specific), fall back to signature doc.
    doc = ""
    params = sig.get("parameters") or []
    if 0 <= active_param < len(params) and isinstance(params[active_param], dict):
        doc = _stringify_doc(params[active_param].get("documentation"))
    if not doc:
        doc = _stringify_doc(sig.get("documentation"))

    return ParsedSignatureHelp(
        segments=segments,
        documentation=doc,
        signature_count=len(signatures),
        active_signature_index=active_sig,
    )


import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gdk, GLib, Gtk, GtkSource  # noqa: E402

from gedit_lsp.utf16 import text_iter_to_utf16  # noqa: E402

logger = logging.getLogger("gedit_lsp.signature_help")


class SignatureHelpController:
    """Per-buffer signature-help popover.

    Triggers on server-advertised `triggerCharacters` (typically `(` and
    `,`). While the popover is visible, subsequent insertions re-fire the
    request so the active parameter tracks what the user is typing. An
    empty/null response from the server dismisses the popover (the "user
    left the call" signal we'd otherwise have to compute ourselves).
    """

    def __init__(
        self,
        *,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None],
    ) -> None:
        self._view = view
        self._buffer = buffer
        self._server = server
        self._uri = uri
        self._flush_pending_change = flush_pending_change
        self._popover: Gtk.Popover | None = None
        self._sig_label: Gtk.Label | None = None
        self._doc_label: Gtk.Label | None = None
        self._inflight_id: int | None = None
        self._buffer_handler_ids: list[int] = []
        self._view_handler_ids: list[int] = []
        self._logged_first_insert = False

        self._buffer_handler_ids.append(
            buffer.connect_after("insert-text", self._on_insert_text),
        )
        self._buffer_handler_ids.append(
            buffer.connect_after("delete-range", self._on_delete_range),
        )
        self._view_handler_ids.append(
            view.connect("key-press-event", self._on_key_press),
        )
        logger.info(
            "signatureHelp controller wired uri=%s; cap_at_attach=%r",
            uri, server.capability("signatureHelpProvider"),
        )

    def dispose(self) -> None:
        for hid in self._buffer_handler_ids:
            with contextlib.suppress(TypeError, RuntimeError):
                self._buffer.disconnect(hid)
        self._buffer_handler_ids.clear()
        for hid in self._view_handler_ids:
            with contextlib.suppress(TypeError, RuntimeError):
                self._view.disconnect(hid)
        self._view_handler_ids.clear()
        self._popdown()

    # --- signal handlers ---

    def _on_insert_text(
        self,
        _buffer: GtkSource.Buffer,
        _location: Gtk.TextIter,
        text: str,
        _length: int,
    ) -> None:
        cap = self._server.capability("signatureHelpProvider")
        if not self._logged_first_insert:
            self._logged_first_insert = True
            logger.info(
                "signatureHelp: first insert-text fired; text=%r cap=%r",
                text, cap,
            )
        if not is_signature_help_supported(cap):
            return
        triggers = signature_trigger_chars(cap)
        retriggers = signature_retrigger_chars(cap)
        visible = self._popover is not None and self._popover.get_visible()

        is_trigger = text in triggers
        if not is_trigger and not visible:
            return  # not a trigger and no session — ignore
        if not is_trigger and text not in retriggers:
            # Visible session, non-retrigger insertion (typing arg names).
            # Still re-fire so the server can refresh the active parameter
            # if it tracks position-based.
            pass

        logger.info(
            "signatureHelp: firing request text=%r is_trigger=%s visible=%s triggers=%r",
            text, is_trigger, visible, triggers,
        )
        self._fire_request(
            trigger_char=text if is_trigger else None,
            is_retrigger=visible,
        )

    def _on_delete_range(
        self,
        _buffer: GtkSource.Buffer,
        _start: Gtk.TextIter,
        _end: Gtk.TextIter,
    ) -> None:
        # Only refresh during an active session — deletions outside a call
        # shouldn't trigger first-time invocation.
        if self._popover is None or not self._popover.get_visible():
            return
        self._fire_request(trigger_char=None, is_retrigger=True)

    def _on_key_press(self, _view: Gtk.TextView, event: Any) -> bool:
        if event.keyval == Gdk.KEY_Escape and self._popover is not None and self._popover.get_visible():
            self._popdown()
            return True  # consume Escape so it doesn't also collapse the find bar etc.
        return False

    # --- request / response ---

    def _fire_request(self, *, trigger_char: str | None, is_retrigger: bool) -> None:
        # Flush any debounced didChange so the server sees the just-typed char
        # before answering "what's at this position?". Otherwise pylsp etc.
        # consult their stale in-memory copy and return empty signatures.
        self._flush_pending_change()
        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        line, character = text_iter_to_utf16(cursor)
        params = build_signature_help_params(
            uri=self._uri,
            line=line, character=character,
            trigger_character=trigger_char,
            is_retrigger=is_retrigger,
        )

        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
            self._inflight_id = None

        my_id: list[int | None] = [None]
        anchor_offset = cursor.get_offset()

        def on_response(msg: dict[str, Any]) -> None:
            if self._inflight_id is None or self._inflight_id != my_id[0]:
                logger.info("signatureHelp: stale response dropped (id mismatch)")
                return
            self._inflight_id = None
            if msg.get("error"):
                logger.info("signatureHelp error: %r", msg.get("error"))
                return
            result = msg.get("result")
            parsed = parse_signature_help(result)
            logger.info(
                "signatureHelp response: result=%r parsed=%r", result, parsed,
            )
            if parsed is None:
                self._popdown()
                return
            anchor = self._buffer.get_iter_at_offset(anchor_offset)
            self._show(parsed, anchor)

        new_id = self._server._send_request(
            "textDocument/signatureHelp", params, on_response,
        )
        self._inflight_id = new_id if new_id != -1 else None
        my_id[0] = self._inflight_id

    # --- presentation ---

    def _ensure_popover(self) -> Gtk.Popover:
        if self._popover is None:
            popover = Gtk.Popover.new(self._view)  # type: ignore[call-arg]
            popover.set_modal(False)  # type: ignore[attr-defined]  # let user keep typing
            popover.set_position(Gtk.PositionType.TOP)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_start(8)
            box.set_margin_end(8)
            box.set_margin_top(6)
            box.set_margin_bottom(6)

            sig_label = Gtk.Label.new("")
            sig_label.set_xalign(0)
            sig_label.set_selectable(True)
            sig_label.set_use_markup(True)
            box.add(sig_label)  # type: ignore[attr-defined]

            doc_label = Gtk.Label.new("")
            doc_label.set_xalign(0)
            doc_label.set_yalign(0)
            doc_label.set_line_wrap(True)  # type: ignore[attr-defined]
            doc_label.set_selectable(True)
            doc_label.set_max_width_chars(72)
            box.add(doc_label)  # type: ignore[attr-defined]

            popover.add(box)  # type: ignore[attr-defined]
            popover.show_all()  # type: ignore[attr-defined]
            self._popover = popover
            self._sig_label = sig_label
            self._doc_label = doc_label
        return self._popover

    def _show(self, parsed: ParsedSignatureHelp, anchor: Gtk.TextIter) -> None:
        popover = self._ensure_popover()
        assert self._sig_label is not None
        assert self._doc_label is not None

        seg = parsed.segments
        markup_parts = [GLib.markup_escape_text(seg.prefix)]
        if seg.active:
            markup_parts.append(f"<b>{GLib.markup_escape_text(seg.active)}</b>")
        markup_parts.append(GLib.markup_escape_text(seg.suffix))
        self._sig_label.set_markup("".join(markup_parts))

        if parsed.documentation.strip():
            self._doc_label.set_text(parsed.documentation)
            self._doc_label.show()
        else:
            self._doc_label.hide()

        rect = self._view.get_iter_location(anchor)
        bx, by = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y,
        )
        rect.x = bx
        rect.y = max(0, by)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        popover.popup()

    def _popdown(self) -> None:
        if self._popover is not None:
            with contextlib.suppress(Exception):
                self._popover.popdown()
