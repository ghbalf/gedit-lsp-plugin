"""DocumentBridge — one per gedit buffer.

Owns the version counter, the debounce timer, and the wire-message
formatting for the four `textDocument/*` notifications. Holds a reference
to its `LanguageServer` (passed in at construction) and a `Clock`
abstraction so unit tests can drive time deterministically.
"""
from __future__ import annotations

import enum
from collections.abc import Callable
from typing import Any, Protocol


class SyncKind(enum.Enum):
    NONE = 0
    FULL = 1
    INCREMENTAL = 2


def parse_sync_kind(capability: Any) -> SyncKind:
    """Normalize a server's `textDocumentSync` capability to a SyncKind.

    The capability arrives as one of:
      - integer TextDocumentSyncKind (0/1/2),
      - TextDocumentSyncOptions object with optional `change` field,
      - None / missing — many servers omit it.

    LSP 3.17 says missing → None, but in practice clients default to Full
    because real-world servers expect didChange even when they don't
    advertise sync. We match that to avoid silently-broken setups.
    Malformed/unknown shapes also degrade to Full.
    """
    if capability is None:
        return SyncKind.FULL
    if isinstance(capability, bool):
        return SyncKind.FULL
    if isinstance(capability, int):
        try:
            return SyncKind(capability)
        except ValueError:
            return SyncKind.FULL
    if isinstance(capability, dict):
        change = capability.get("change")
        if change is None:
            return SyncKind.NONE
        try:
            return SyncKind(int(change))
        except (ValueError, TypeError):
            return SyncKind.FULL
    return SyncKind.FULL


class Server(Protocol):
    def send_notification(self, method: str, params: dict[str, Any]) -> None: ...
    def add_diagnostics_listener(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]: ...


class Clock(Protocol):
    def schedule_after_ms(self, delay_ms: int, callback: Any) -> Any: ...
    def cancel(self, handle: Any) -> None: ...


class DocumentBridge:
    def __init__(
        self,
        uri: str,
        language_id: str,
        text: str,
        server: Server,
        clock: Clock,
        debounce_ms: int,
        sync_kind: SyncKind = SyncKind.FULL,
    ) -> None:
        self.uri = uri
        self.language_id = language_id
        self._text = text
        self._server = server
        self._clock = clock
        self._debounce_ms = debounce_ms
        self.sync_kind = sync_kind
        self._version = 0
        self._pending_handle: Any = None
        self._pending_events: list[dict[str, Any]] = []
        # Last-seen publishDiagnostics list, keyed by URI. The bridge
        # subscribes to the server on attach(); CodeActionController reads
        # this via latest_diagnostics_for(uri) to assemble its request's
        # `context.diagnostics`.
        self._latest_diagnostics: dict[str, list[dict[str, Any]]] = {}
        self._diagnostics_disposer: Callable[[], None] | None = None

    def attach(self) -> None:
        self._version = 1
        self._server.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": self.uri,
                    "languageId": self.language_id,
                    "version": self._version,
                    "text": self._text,
                }
            },
        )
        self._diagnostics_disposer = self._server.add_diagnostics_listener(
            self._on_diagnostics
        )

    def _on_diagnostics(self, params: dict[str, Any]) -> None:
        """Stash the most recent publishDiagnostics for any URI we see."""
        uri = params.get("uri")
        if not isinstance(uri, str):
            return
        diags = params.get("diagnostics", [])
        if not isinstance(diags, list):
            return
        self._latest_diagnostics[uri] = diags

    def latest_diagnostics_for(self, uri: str) -> list[dict[str, Any]]:
        """Return the most recent publishDiagnostics list for `uri`, or []."""
        return self._latest_diagnostics.get(uri, [])

    def on_changed(self, new_text: str) -> None:
        """Full-document change entrypoint. Used by the Full-sync path; on
        an Incremental bridge it's a fallback that emits a full-text
        contentChange (rare — only callers that don't have edit deltas)."""
        self._text = new_text
        self._schedule_flush()

    def on_change_event(self, event: dict[str, Any]) -> None:
        """Incremental change entrypoint. `event` is an LSP
        `TextDocumentContentChangeEvent` (`{range, text}`).

        The bridge's `_text` mirror is *not* updated here — that's handled
        by `refresh_text()`, called from the buffer's coalesced `changed`
        signal once GTK has applied the edit. Until refresh, `_text` lags
        by one event; that's only read on save, which fires after the
        change-signal cycle completes."""
        if self.sync_kind is SyncKind.INCREMENTAL:
            self._pending_events.append(event)
        self._schedule_flush()

    def refresh_text(self, text: str) -> None:
        """Update the full-text mirror used by didSave and the Full-sync
        fallback. Does not schedule a didChange — events drive that."""
        self._text = text

    def on_saved(self) -> None:
        self.flush_pending_change()
        self._server.send_notification(
            "textDocument/didSave",
            {"textDocument": {"uri": self.uri}, "text": self._text},
        )

    def flush_pending_change(self) -> None:
        """Send any debounce-queued didChange synchronously, now.

        Edit-triggered features (e.g. signatureHelp on `(`) call this before
        sending their request so pylsp/clangd see the new text — otherwise
        the server is consulting stale state and returns an empty result.
        """
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
            self._flush_change()

    def revert_to_disk(self, disk_text: str) -> None:
        """Push a full-text didChange replacing pending edits with `disk_text`.

        Used by the dirty-close cache-workaround path: if a buffer that was
        modified (e.g. by apply_workspace_edit during rename) is closed
        without saving, parso's parse cache for this file remains pinned
        at the in-memory rename content. The next project-wide rename
        then misses references in this file. Reverting pylsp's view to the
        on-disk content immediately before close keeps parso's cache
        aligned with disk so subsequent project searches read the right
        symbols. See `project_pylsp_jedi_rename_caveats` memory.
        """
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
            self._pending_handle = None
        self._pending_events.clear()
        self._text = disk_text
        self._version += 1
        self._server.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": self.uri, "version": self._version},
                "contentChanges": [{"text": disk_text}],
            },
        )

    def detach(self) -> None:
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
            self._pending_handle = None
        self._pending_events.clear()
        if self._diagnostics_disposer is not None:
            self._diagnostics_disposer()
            self._diagnostics_disposer = None
        self._server.send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": self.uri}},
        )

    def _schedule_flush(self) -> None:
        if self.sync_kind is SyncKind.NONE:
            return
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
        self._pending_handle = self._clock.schedule_after_ms(
            self._debounce_ms, self._flush_change
        )

    def _flush_change(self) -> None:
        self._pending_handle = None
        if self.sync_kind is SyncKind.NONE:
            return
        if self.sync_kind is SyncKind.INCREMENTAL and self._pending_events:
            content_changes = self._pending_events
            self._pending_events = []
        else:
            content_changes = [{"text": self._text}]
        self._version += 1
        self._server.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": self.uri, "version": self._version},
                "contentChanges": content_changes,
            },
        )

class GLibClock:
    """Real Clock backed by GLib.timeout_add."""

    def __init__(self) -> None:
        import gi  # local import to keep test imports light

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        self._GLib = GLib

    def schedule_after_ms(self, delay_ms: int, callback: Any) -> int:
        def _wrapper() -> bool:
            callback()
            return False

        return int(self._GLib.timeout_add(delay_ms, _wrapper))

    def cancel(self, handle: int) -> None:
        self._GLib.source_remove(handle)
