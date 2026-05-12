"""CodeActionController: textDocument/codeAction orchestration.

Window-scoped controller. trigger() is the entry point — invoked from
the Alt+Return keybind, the lightbulb-click callback, or the popup-
menu entry. Mirrors RenameController in shape: capability-gate,
edit-flush, request, response dispatch via popover, commit applies
the edit (and/or executes the command, with codeAction/resolve when
needed).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gedit_lsp.code_action import (
    NormalizedAction,
    extract_diag_context,
    needs_resolve,
    normalize_action,
)
from gedit_lsp.navigation import default_buffer_for_uri, default_load_uri
from gedit_lsp.utf16 import text_iter_to_utf16
from gedit_lsp.workspace_edit import apply_workspace_edit

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]

    from gedit_lsp.server import LanguageServer
    from gedit_lsp.ui.code_action_popover import (  # type: ignore[attr-defined]
        CodeActionPopover,
    )


logger = logging.getLogger("gedit_lsp.code_action")


class CodeActionController:
    def __init__(
        self,
        *,
        window: Gedit.Window,
        popover_factory: Callable[[Any], CodeActionPopover] | None = None,
        load_uri: Callable[
            [Any, str, Callable[[bool], None]], None
        ] = default_load_uri,
        buffer_for_uri: Callable[[Any, str], Any] = default_buffer_for_uri,
    ) -> None:
        self._window = window
        self._popover_factory = popover_factory
        self._load_uri = load_uri
        self._buffer_for_uri = buffer_for_uri

    def trigger(
        self,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None],
        diagnostics_for_uri: Callable[[str], list[dict[str, Any]]],
        cursor_line: int | None = None,
    ) -> None:
        statusbar = self._window.get_statusbar()
        if not server.capability("codeActionProvider"):
            logger.info("code-action: server does not support codeActionProvider")
            statusbar.push(0, "LSP: server does not support code actions")
            return

        view = self._window.get_active_view()
        if view is None:
            logger.info("code-action: no active view")
            return

        buf = view.get_buffer()
        if cursor_line is not None:
            buf.place_cursor(buf.get_iter_at_line(cursor_line))
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line, char = text_iter_to_utf16(cursor)

        # Edit-flush invariant: server must see latest text before
        # answering "what can I do here?". See memory:
        # project_edit_triggered_flush_invariant.
        flush_pending_change()

        diags_at = extract_diag_context(diagnostics_for_uri(uri), line, char)
        params = {
            "textDocument": {"uri": uri},
            "range": {
                "start": {"line": line, "character": char},
                "end":   {"line": line, "character": char},
            },
            "context": {
                "diagnostics": diags_at,
                "triggerKind": 1,  # Invoked (manual)
            },
        }

        def on_response(msg: dict[str, Any]) -> None:
            self._dispatch_response(msg, server, view)

        logger.info("code-action: send line=%d char=%d", line, char)
        server._send_request("textDocument/codeAction", params, on_response)

    def _dispatch_response(
        self, msg: dict[str, Any], server: LanguageServer, view: Any,
    ) -> None:
        statusbar = self._window.get_statusbar()
        if msg.get("error"):
            logger.info("code-action: server error %r", msg.get("error"))
            statusbar.push(0, "LSP: code action request failed")
            return
        result = msg.get("result")
        if result is None or result == []:
            statusbar.push(0, "LSP: no code actions")
            return
        if not isinstance(result, list):
            statusbar.push(0, "LSP: no code actions")
            return
        actions: list[NormalizedAction] = []
        for item in result:
            normalized = normalize_action(item)
            if normalized is not None:
                actions.append(normalized)
        if not actions:
            statusbar.push(0, "LSP: no code actions")
            return

        factory = self._popover_factory
        if factory is None:
            from gedit_lsp.ui.code_action_popover import (  # type: ignore[attr-defined]
                CodeActionPopover,
            )
            factory = CodeActionPopover
        popover = factory(view)
        popover.show(
            actions=actions,
            on_commit=lambda action: self._commit(action, server),
            on_cancel=lambda: None,
        )

    def _commit(
        self, action: NormalizedAction, server: LanguageServer,
    ) -> None:
        if needs_resolve(action):
            def on_resolved(msg: dict[str, Any]) -> None:
                statusbar = self._window.get_statusbar()
                if msg.get("error"):
                    logger.info("code-action: resolve error %r", msg.get("error"))
                    statusbar.push(0, "LSP: could not resolve action")
                    return
                resolved_raw = msg.get("result") or {}
                resolved = normalize_action(resolved_raw)
                if resolved is None:
                    logger.info(
                        "code-action: resolve returned malformed result %r",
                        resolved_raw,
                    )
                    statusbar.push(0, "LSP: could not resolve action")
                    return
                self._execute(resolved, server)

            # Pass the original action (with data) for the server to
            # complete. Use the raw shape; LSP expects the same fields
            # we received from textDocument/codeAction.
            raw = {
                "title": action["title"],
                "kind": action["kind"],
                "data": action["data"],
            }
            server._send_request("codeAction/resolve", raw, on_resolved)
            return
        self._execute(action, server)

    def _execute(
        self, action: NormalizedAction, server: LanguageServer,
    ) -> None:
        statusbar = self._window.get_statusbar()
        has_edit = action["edit"] is not None
        has_command = action["command"] is not None

        applied: list[str] = []
        failed: list[str] = []

        if has_edit:
            try:
                applied, failed = apply_workspace_edit(
                    action["edit"],
                    buffer_for_uri=lambda u: self._buffer_for_uri(self._window, u),
                )
            except RuntimeError as exc:
                logger.info("code-action: window closed mid-apply (%r)", exc)
                return

        if has_command:
            cmd = action["command"]
            # Per spec it's a request; in practice servers return null.
            # Fire with a no-op callback for spec correctness.
            server._send_request(
                "workspace/executeCommand", cmd, lambda _msg: None,
            )

        if applied or has_command or failed:
            if failed:
                statusbar.push(
                    0,
                    f"LSP: applied {len(applied)} file(s); "
                    f"{len(failed)} failed (see log)",
                )
            else:
                statusbar.push(0, f"LSP: applied {action['title']}")
        else:
            statusbar.push(0, "LSP: nothing to apply")
