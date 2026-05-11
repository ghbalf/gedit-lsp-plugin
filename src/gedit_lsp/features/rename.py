"""RenameController: textDocument/rename + prepareRename orchestration.

Window-scoped, mirrors ReferencesController in shape. trigger() is the
entire surface: capture cursor, flush, optional prepareRename, show
popover, on commit fire rename, then load any closed files and apply
the WorkspaceEdit via the workspace_edit helper.

Async load-settle is the only non-trivial new state — handled inline
via a remaining-counter closure rather than a dedicated helper class
(it's <20 lines of code and only used in one place). load_uri and
buffer_for_uri are module-level test seams, replaceable per-instance
through constructor parameters.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter
from gedit_lsp.workspace_edit import apply_workspace_edit, derive_placeholder

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]

    from gedit_lsp.server import LanguageServer
    from gedit_lsp.ui.rename_popover import RenamePopover


logger = logging.getLogger("gedit_lsp.rename")


def _default_load_uri(
    window: Any, uri: str, on_loaded: Callable[[bool], None]
) -> None:
    """Open `uri` in `window` and call on_loaded(success) when ready.

    Uses Gedit.commands_load_location (1-indexed line/column; we pass
    1, 0 since rename doesn't care about cursor placement on the new
    tab) and listens for the document's `loaded` signal.

    Replaceable in unit tests via RenameController(load_uri=...).

    Pre-flight check: a malformed WorkspaceEdit (e.g. pylsp's
    rope_rename returns URIs rooted at "/" instead of the project
    root) would otherwise spawn a ghost error tab. Skip the load and
    report failure if the URI's path doesn't exist on disk.
    """
    import gi

    gi.require_version("Gedit", "3.0")
    from gi.repository import Gedit, Gio  # type: ignore[attr-defined]

    gfile = Gio.File.new_for_uri(uri)
    path = gfile.get_path()
    if path is None or not Path(path).is_file():
        logger.info("rename: refusing to load non-existent uri %s", uri)
        on_loaded(False)
        return
    Gedit.commands_load_location(window, gfile, None, 1, 0)
    tab = window.get_tab_from_location(gfile)
    if tab is None:
        on_loaded(False)
        return
    doc = tab.get_document()
    handler_id: list[int] = []

    def _on_loaded(_doc: Any) -> None:
        if handler_id:
            doc.disconnect(handler_id[0])
        on_loaded(True)

    handler_id.append(doc.connect("loaded", _on_loaded))


def _default_buffer_for_uri(window: Any, uri: str) -> Any:
    """Walk window.get_documents() for the matching URI. Replaceable
    in unit tests via RenameController(buffer_for_uri=...).
    """
    for doc in window.get_documents():
        gfile = doc.get_file().get_location()
        if gfile is not None and gfile.get_uri() == uri:
            return doc
    return None


class RenameController:
    def __init__(
        self,
        *,
        window: Gedit.Window,
        popover_factory: Callable[[Any], RenamePopover] | None = None,
        load_uri: Callable[
            [Any, str, Callable[[bool], None]], None
        ] = _default_load_uri,
        buffer_for_uri: Callable[[Any, str], Any] = _default_buffer_for_uri,
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
    ) -> None:
        statusbar = self._window.get_statusbar()
        rename_cap = server.capability("renameProvider")
        if not rename_cap:
            logger.info("rename: server does not support renameProvider")
            statusbar.push(0, "LSP: server does not support rename")
            return

        view = self._window.get_active_view()
        if view is None:
            return
        buf = view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line, char = text_iter_to_utf16(cursor)

        flush_pending_change()  # edit-flush invariant

        prepare_supported = (
            isinstance(rename_cap, dict)
            and bool(rename_cap.get("prepareProvider"))
        )
        if prepare_supported:
            self._send_prepare(server, uri, line, char, view, buf)
        else:
            placeholder = derive_placeholder(buf, line, char)
            self._show_popover(server, uri, line, char, view, placeholder)

    def _send_prepare(
        self,
        server: LanguageServer,
        uri: str,
        line: int,
        char: int,
        view: Any,
        buf: Any,
    ) -> None:
        statusbar = self._window.get_statusbar()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
        }

        def on_prepare(msg: dict[str, Any]) -> None:
            if msg.get("error"):
                logger.info(
                    "rename: prepareRename error %r — fallback", msg.get("error"),
                )
                placeholder = derive_placeholder(buf, line, char)
                self._show_popover(server, uri, line, char, view, placeholder)
                return
            result = msg.get("result")
            if result is None:
                logger.info("rename: prepareRename returned null — refused")
                statusbar.push(0, "LSP: cannot rename symbol here")
                return
            placeholder = self._placeholder_from_prepare(result, buf, line, char)
            self._show_popover(server, uri, line, char, view, placeholder)

        server._send_request("textDocument/prepareRename", params, on_prepare)

    @staticmethod
    def _placeholder_from_prepare(
        result: Any, buf: Any, line: int, char: int
    ) -> str:
        # Shape: {range, placeholder}
        if isinstance(result, dict) and isinstance(result.get("placeholder"), str):
            return str(result["placeholder"])
        # Shape: {defaultBehavior: true}
        if isinstance(result, dict) and result.get("defaultBehavior") is True:
            return derive_placeholder(buf, line, char)
        # Shape: a Range (start/end dicts present, no placeholder/defaultBehavior)
        if (
            isinstance(result, dict)
            and isinstance(result.get("start"), dict)
            and isinstance(result.get("end"), dict)
        ):
            try:
                start = utf16_to_text_iter(
                    buf, result["start"]["line"], result["start"]["character"],
                )
                end = utf16_to_text_iter(
                    buf, result["end"]["line"], result["end"]["character"],
                )
                return str(buf.get_text(start, end, False))
            except Exception:  # noqa: BLE001
                return derive_placeholder(buf, line, char)
        return derive_placeholder(buf, line, char)

    def _show_popover(
        self,
        server: LanguageServer,
        uri: str,
        line: int,
        char: int,
        view: Any,
        placeholder: str,
    ) -> None:
        factory = self._popover_factory
        if factory is None:
            from gedit_lsp.ui.rename_popover import RenamePopover
            factory = RenamePopover
        popover = factory(view)

        def on_commit(new_name: str) -> None:
            if not new_name:
                return  # empty submission — popover already dismissed
            self._send_rename(server, uri, line, char, new_name)

        def on_cancel() -> None:
            return

        popover.show(
            placeholder=placeholder,
            on_commit=on_commit,
            on_cancel=on_cancel,
        )

    def _send_rename(
        self,
        server: LanguageServer,
        uri: str,
        line: int,
        char: int,
        new_name: str,
    ) -> None:
        statusbar = self._window.get_statusbar()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
            "newName": new_name,
        }

        def on_response(msg: dict[str, Any]) -> None:
            if msg.get("error"):
                logger.info("rename: server error %r", msg.get("error"))
                statusbar.push(0, "LSP: rename failed (see log)")
                return
            edit = msg.get("result")
            if edit is None or edit == {}:
                statusbar.push(0, "LSP: no changes")
                return
            self._begin_apply(edit)

        server._send_request("textDocument/rename", params, on_response)

    def _begin_apply(self, edit: dict[str, Any]) -> None:
        uris = self._collect_uris(edit)
        if not uris:
            self._window.get_statusbar().push(0, "LSP: no changes")
            return

        to_load = [
            u for u in uris
            if self._buffer_for_uri(self._window, u) is None
        ]

        if not to_load:
            self._do_apply(edit)
            return

        remaining = [len(to_load)]

        def _on_one_loaded(_uri: str, _success: bool) -> None:
            # Success doesn't matter here: if the load failed, the URI
            # will resolve to None in buffer_for_uri at apply time and
            # apply_workspace_edit will mark it as failed. Either way
            # we just count down to know when to fire the apply.
            remaining[0] -= 1
            if remaining[0] == 0:
                self._do_apply(edit)

        def _make_cb(u: str) -> Callable[[bool], None]:
            def _cb(ok: bool) -> None:
                _on_one_loaded(u, ok)
            return _cb

        for uri in to_load:
            self._load_uri(self._window, uri, _make_cb(uri))

    @staticmethod
    def _collect_uris(edit: Any) -> list[str]:
        uris: list[str] = []
        if not isinstance(edit, dict):
            return uris
        document_changes = edit.get("documentChanges")
        if isinstance(document_changes, list):
            for entry in document_changes:
                if isinstance(entry, dict):
                    td = entry.get("textDocument")
                    if isinstance(td, dict) and isinstance(td.get("uri"), str):
                        uris.append(td["uri"])
            return uris
        changes = edit.get("changes")
        if isinstance(changes, dict):
            for uri in changes:
                if isinstance(uri, str):
                    uris.append(uri)
        return uris

    def _do_apply(self, edit: dict[str, Any]) -> None:
        # Window-closed guard: if the user closed the gedit window while
        # a load was in flight, get_statusbar() (or any later GTK call)
        # raises RuntimeError on the destroyed wrapper. Per spec, the
        # callback should no-op silently in that case rather than
        # crashing the plugin.
        try:
            applied, failed = apply_workspace_edit(
                edit,
                buffer_for_uri=lambda u: self._buffer_for_uri(self._window, u),
            )
            statusbar = self._window.get_statusbar()
        except RuntimeError as exc:
            logger.info("rename: window closed mid-apply, skipping (%r)", exc)
            return
        n = len(applied)
        m = len(failed)
        if m == 0:
            statusbar.push(0, f"LSP: renamed {n} file(s)")
        else:
            statusbar.push(0, f"LSP: renamed {n} file(s); {m} failed (see log)")
