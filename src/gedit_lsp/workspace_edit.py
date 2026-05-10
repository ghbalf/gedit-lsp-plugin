"""Pure helpers for applying LSP WorkspaceEdit responses + tokenising
the word under the cursor.

`apply_workspace_edit` is the canonical entry point for textDocument/rename
(and, in v0.4.0+, textDocument/codeAction). It walks the WorkspaceEdit
shape — preferring `documentChanges` (the spec-preferred shape, carries
versionId) over the older `changes` map — and delegates each file's
TextEdit[] to the existing `features.formatting.apply_text_edits` helper
(right-to-left sort + one begin/end_user_action per file).

`derive_placeholder` is the prepareRename fallback: when the server
doesn't advertise prepareProvider, or when prepareRename returns
{defaultBehavior: true}, the controller asks us for the identifier
spanning the cursor. The regex is broad enough for most LSP-supported
languages (Python, C, Rust, Go, JS); the server's prepareRename is the
authoritative source whenever it's available.

This module is GTK-widget-free apart from typed buffer parameters that
the caller already holds, so it's safe in headless CI.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gedit_lsp.features.formatting import apply_text_edits

if TYPE_CHECKING:
    from gi.repository import Gtk, GtkSource


logger = logging.getLogger("gedit_lsp.workspace_edit")

# Identifier-shaped token for the prepareRename fallback. Broad enough
# for Python / C / Rust / Go / JS — the server's prepareRename is the
# authoritative source when available.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def derive_placeholder(
    buffer: GtkSource.Buffer,
    cursor_line: int,
    cursor_char_utf16: int,
) -> str:
    """Return the identifier-shaped token spanning (line, char), or "".

    Reads the buffer line at `cursor_line` and finds the regex match
    whose span contains `cursor_char_utf16`. If no match contains the
    cursor, returns "" — caller falls back to popover with empty entry.
    """
    line_count = buffer.get_line_count()
    if cursor_line < 0 or cursor_line >= line_count:
        return ""
    start: Gtk.TextIter = buffer.get_iter_at_line(cursor_line)  # type: ignore[assignment]
    if cursor_line + 1 < line_count:
        end: Gtk.TextIter = buffer.get_iter_at_line(cursor_line + 1)  # type: ignore[assignment]
    else:
        end = buffer.get_end_iter()
    line_text = buffer.get_text(start, end, False)
    if line_text.endswith("\n"):
        line_text = line_text[:-1]
    for m in _IDENT_RE.finditer(line_text):
        if m.start() <= cursor_char_utf16 < m.end():
            return m.group(0)
    return ""


def apply_workspace_edit(
    edit: Any,
    *,
    buffer_for_uri: Callable[[str], GtkSource.Buffer | None],
) -> tuple[list[str], list[str]]:
    """Apply a WorkspaceEdit. Returns (applied_uris, failed_uris).

    Prefers `documentChanges` over the older `changes` map. Per-file
    failures don't abort the whole apply: a missing buffer or an
    apply_text_edits exception moves that URI into `failed_uris` and
    the loop continues.

    The caller is responsible for ensuring `buffer_for_uri` returns an
    open buffer for every URI in the WorkspaceEdit. That typically
    means opening any closed files via Gedit.commands_load_location
    and waiting for their `loaded` signal before calling this helper.
    """
    if not isinstance(edit, dict):
        return ([], [])

    applied: list[str] = []
    failed: list[str] = []

    document_changes = edit.get("documentChanges")
    if isinstance(document_changes, list) and document_changes:
        for entry in document_changes:
            if not isinstance(entry, dict):
                continue
            text_doc = entry.get("textDocument")
            if not isinstance(text_doc, dict):
                continue
            uri = text_doc.get("uri")
            edits = entry.get("edits")
            if not isinstance(uri, str) or not isinstance(edits, list):
                continue
            _apply_one(uri, edits, buffer_for_uri, applied, failed)
        return (applied, failed)

    changes = edit.get("changes")
    if isinstance(changes, dict):
        for uri, edits in changes.items():
            if not isinstance(uri, str) or not isinstance(edits, list):
                continue
            _apply_one(uri, edits, buffer_for_uri, applied, failed)
        return (applied, failed)

    return (applied, failed)


def _apply_one(
    uri: str,
    edits: list[dict[str, Any]],
    buffer_for_uri: Callable[[str], GtkSource.Buffer | None],
    applied: list[str],
    failed: list[str],
) -> None:
    buf = buffer_for_uri(uri)
    if buf is None:
        logger.info("workspace_edit: no buffer for %s — skipped", uri)
        failed.append(uri)
        return
    try:
        apply_text_edits(buf, edits)
    except Exception as exc:  # noqa: BLE001  — we want all per-file failures isolated
        logger.info("workspace_edit: apply_text_edits raised for %s: %r", uri, exc)
        failed.append(uri)
        return
    applied.append(uri)
