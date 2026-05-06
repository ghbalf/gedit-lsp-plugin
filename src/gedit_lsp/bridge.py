"""DocumentBridge — one per gedit buffer.

Owns the version counter, the debounce timer, and the wire-message
formatting for the four `textDocument/*` notifications. Holds a reference
to its `LanguageServer` (passed in at construction) and a `Clock`
abstraction so unit tests can drive time deterministically.
"""
from __future__ import annotations

from typing import Any, Protocol


class Server(Protocol):
    def send_notification(self, method: str, params: dict[str, Any]) -> None: ...


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
    ) -> None:
        self.uri = uri
        self.language_id = language_id
        self._text = text
        self._server = server
        self._clock = clock
        self._debounce_ms = debounce_ms
        self._version = 0
        self._pending_handle: Any = None

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

    def on_changed(self, new_text: str) -> None:
        self._text = new_text
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
        self._pending_handle = self._clock.schedule_after_ms(
            self._debounce_ms, self._flush_change
        )

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

    def detach(self) -> None:
        if self._pending_handle is not None:
            self._clock.cancel(self._pending_handle)
            self._pending_handle = None
        self._server.send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": self.uri}},
        )

    def _flush_change(self) -> None:
        self._pending_handle = None
        self._version += 1
        self._server.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": self.uri, "version": self._version},
                "contentChanges": [{"text": self._text}],
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
