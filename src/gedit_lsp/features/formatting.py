"""LSP `textDocument/formatting` and `textDocument/rangeFormatting`.

Pure helpers + a per-buffer `FormattingController`. Edit-application is
right-to-left because LSP `TextEdit[]` positions all reference the
*pre-edit* document, so applying earlier edits first would shift later
edits' coordinates. Sorting by start position descending and applying
in that order is the canonical safe sequence (and what VS Code does).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import gi

logger = logging.getLogger("gedit_lsp.formatting")

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource

from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter

if TYPE_CHECKING:
    from gedit_lsp.server import LanguageServer


def is_formatting_supported(capability: Any) -> bool:
    """Return True if `documentFormattingProvider` is advertised.

    LSP allows the value to be a bool or a `DocumentFormattingOptions`
    object (e.g. `{"workDoneProgress": true}`); both indicate support.
    """
    return capability is not None and capability is not False


def is_range_formatting_supported(capability: Any) -> bool:
    """Mirror of `is_formatting_supported` for the range variant."""
    return capability is not None and capability is not False


def build_formatting_params(
    *, uri: str, tab_size: int, insert_spaces: bool
) -> dict[str, Any]:
    return {
        "textDocument": {"uri": uri},
        "options": {"tabSize": tab_size, "insertSpaces": insert_spaces},
    }


def build_range_formatting_params(
    *,
    uri: str,
    start_line: int,
    start_char: int,
    end_line: int,
    end_char: int,
    tab_size: int,
    insert_spaces: bool,
) -> dict[str, Any]:
    return {
        "textDocument": {"uri": uri},
        "range": {
            "start": {"line": start_line, "character": start_char},
            "end":   {"line": end_line,   "character": end_char},
        },
        "options": {"tabSize": tab_size, "insertSpaces": insert_spaces},
    }


def apply_text_edits(
    buffer: GtkSource.Buffer, edits: list[dict[str, Any]]
) -> None:
    """Apply an LSP `TextEdit[]` to `buffer`, right-to-left.

    Sorts edits by start position descending so applying an edit doesn't
    invalidate the coordinates of subsequent (earlier-positioned) edits.
    Wrapped in `begin_user_action`/`end_user_action` so the whole format
    is one undoable step.
    """
    if not edits:
        return

    def _sort_key(edit: dict[str, Any]) -> tuple[int, int]:
        start = edit["range"]["start"]
        return (start["line"], start["character"])

    sorted_edits = sorted(edits, key=_sort_key, reverse=True)

    buffer.begin_user_action()
    try:
        for edit in sorted_edits:
            r = edit["range"]
            start_iter = utf16_to_text_iter(
                buffer, r["start"]["line"], r["start"]["character"]
            )
            end_iter = utf16_to_text_iter(
                buffer, r["end"]["line"], r["end"]["character"]
            )
            buffer.delete(start_iter, end_iter)
            new_text = edit.get("newText", "")
            if new_text:
                # `start_iter` is updated in place by `delete`; insert there.
                # PyGObject's TextBuffer.insert is dynamically dispatched and
                # untyped in the stubs, so mypy flags it; the runtime call is
                # exactly Gtk.TextBuffer::insert(iter, text, len).
                buffer.insert(start_iter, new_text, len(new_text.encode("utf-8")))  # type: ignore[no-untyped-call]
    finally:
        buffer.end_user_action()


class FormattingController:
    """Per-buffer handler for the `lsp-format` action.

    `trigger()` decides between range and full-document formatting based
    on whether the buffer has a selection, flushes any debounced
    didChange (so the server formats the up-to-date text), fires the
    request, and applies the resulting `TextEdit[]` on response.
    """

    def __init__(
        self,
        *,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None] = lambda: None,
    ) -> None:
        self._view = view
        self._buffer = buffer
        self._server = server
        self._uri = uri
        self._flush_pending_change = flush_pending_change
        self._inflight_id: int | None = None

    def trigger(self) -> None:
        # Format the latest text the user sees, not the server's stale snapshot.
        self._flush_pending_change()
        logger.info("format: triggered uri=%s", self._uri)

        # Tab/indent prefs come from the view; the server uses these to
        # pick spaces vs tabs and the indent step.
        tab_size, insert_spaces = self._formatting_options()

        bounds = self._selection_bounds()
        if bounds is None:
            cap = self._server.capability("documentFormattingProvider")
            if not is_formatting_supported(cap):
                logger.info("formatting: server does not support documentFormatting")
                return
            params = build_formatting_params(
                uri=self._uri, tab_size=tab_size, insert_spaces=insert_spaces,
            )
            method = "textDocument/formatting"
        else:
            cap = self._server.capability("documentRangeFormattingProvider")
            if not is_range_formatting_supported(cap):
                # Fall back to whole-document formatting if the server
                # advertises only documentFormattingProvider.
                doc_cap = self._server.capability("documentFormattingProvider")
                if not is_formatting_supported(doc_cap):
                    logger.info("formatting: server supports neither full nor range formatting")
                    return
                params = build_formatting_params(
                    uri=self._uri, tab_size=tab_size, insert_spaces=insert_spaces,
                )
                method = "textDocument/formatting"
            else:
                (s_line, s_char), (e_line, e_char) = bounds
                params = build_range_formatting_params(
                    uri=self._uri,
                    start_line=s_line, start_char=s_char,
                    end_line=e_line,   end_char=e_char,
                    tab_size=tab_size, insert_spaces=insert_spaces,
                )
                method = "textDocument/rangeFormatting"

        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
            self._inflight_id = None

        my_id: list[int | None] = [None]

        def on_response(msg: dict[str, Any]) -> None:
            # Drop stale responses (e.g. user fired again before this returned).
            if self._inflight_id is None or self._inflight_id != my_id[0]:
                return
            self._inflight_id = None
            if msg.get("error"):
                logger.info("formatting error: %r", msg.get("error"))
                return
            result = msg.get("result")
            if result is None or result == []:
                # pylsp returns null when no formatter plugin is loaded —
                # most common cause of "format does nothing". Make it
                # visible in the log so the user can diagnose without
                # comparing traffic-log JSON.
                logger.info(
                    "format: server returned no edits — likely no formatter "
                    "plugin enabled (e.g. install python3-autopep8 / "
                    "python-lsp-black for pylsp)"
                )
                return
            if not isinstance(result, list):
                logger.info("format: unexpected result shape %r", type(result))
                return
            logger.info("format: applying %d edit(s)", len(result))
            apply_text_edits(self._buffer, result)

        new_id = self._server._send_request(method, params, on_response)
        self._inflight_id = new_id if new_id != -1 else None
        my_id[0] = self._inflight_id

    def _formatting_options(self) -> tuple[int, bool]:
        # These methods exist on GtkSource.View but not the bare Gtk.TextView
        # type used in our annotations. hasattr-guard both so a misconfigured
        # plugin embed (e.g. a plain TextView) falls back to sane defaults.
        view = self._view
        tab_size = 4
        insert_spaces = True
        if hasattr(view, "get_tab_width"):
            tab_size = int(view.get_tab_width())
        if hasattr(view, "get_insert_spaces_instead_of_tabs"):
            insert_spaces = bool(view.get_insert_spaces_instead_of_tabs())
        return tab_size, insert_spaces

    def _selection_bounds(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        bounds = self._buffer.get_selection_bounds()
        if not bounds:
            return None
        start, end = bounds
        s_line, s_char = text_iter_to_utf16(start)
        e_line, e_char = text_iter_to_utf16(end)
        if (s_line, s_char) == (e_line, e_char):
            return None
        return (s_line, s_char), (e_line, e_char)
