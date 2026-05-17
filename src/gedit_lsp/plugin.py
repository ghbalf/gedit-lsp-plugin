"""GeditLspPlugin — libpeas entry point, Gedit.WindowActivatable.

Lifecycle:
    do_activate()    — wire signals on Gedit.Window, attach DocumentBridges
                       to currently-open documents, set up logging.
    do_deactivate()  — disconnect signals, detach all bridges, shut down
                       all servers via the registry.
    do_update_state() — reserved (used for menu-action sensitivity in
                       feature milestones).
"""
from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

logger = logging.getLogger("gedit_lsp.plugin")

import gi

gi.require_version("Gedit", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
gi.require_version("PeasGtk", "1.0")
from gi.repository import (  # type: ignore[attr-defined]
    Gedit,
    Gio,
    GLib,
    GObject,
    Gtk,
    PeasGtk,
)

from gedit_lsp.bridge import DocumentBridge, GLibClock, SyncKind, parse_sync_kind
from gedit_lsp.config import Config
from gedit_lsp.features.code_action import CodeActionController
from gedit_lsp.features.completion import CompletionController
from gedit_lsp.features.definition import CursorHistory, DefinitionController
from gedit_lsp.features.diagnostics import DiagnosticsController
from gedit_lsp.features.formatting import FormattingController
from gedit_lsp.features.hover import HoverController
from gedit_lsp.features.mouse_hover import (
    MouseHoverController,
    should_attach_mouse_hover,
)
from gedit_lsp.features.outline import OutlineController
from gedit_lsp.features.references import ReferencesController
from gedit_lsp.features.rename import RenameController
from gedit_lsp.features.signature_help import SignatureHelpController
from gedit_lsp.features.workspace_symbol import WorkspaceSymbolController
from gedit_lsp.log import setup_logging
from gedit_lsp.registry import ServerRegistry
from gedit_lsp.root import ProjectRootResolver
from gedit_lsp.rpc import RpcClient
from gedit_lsp.server import LanguageServer, ServerState
from gedit_lsp.ui import popup_menu, server_logs
from gedit_lsp.ui.crash_notify import CrashNotifier
from gedit_lsp.ui.diagnostics_panel import DiagnosticsPanel
from gedit_lsp.ui.lightbulb_gutter import LightbulbGutter
from gedit_lsp.ui.references_panel import ReferencesPanel
from gedit_lsp.ui.statusbar import StatusbarIndicator
from gedit_lsp.ui.workspace_symbol_quickpick import WorkspaceSymbolQuickPick
from gedit_lsp.utf16 import text_iter_to_utf16


def _config_path() -> Path:
    base = Path(
        os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    )
    return base / "gedit" / "lsp-plugin.json"


def _state_dir() -> Path:
    base = Path(
        os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    )
    return base / "gedit-lsp"


# Module-global singletons (one per gedit process)
_config: Config | None = None
_registry: ServerRegistry | None = None


def _ensure_globals() -> tuple[Config, ServerRegistry]:
    global _config, _registry
    if _config is None:
        _config = Config(user_path=_config_path())
        _config.load()
        setup_logging(
            state_dir=_state_dir(),
            level=_config.tunable("logLevel"),
            traffic_enabled=_config.tunable("logLspTraffic"),
            max_bytes=_config.tunable("logRotationMaxBytes"),
            keep=_config.tunable("logRotationKeepFiles"),
        )

        def factory(
            command: list[str],
            log_prefix: str,
            on_exit: Any,
            on_stderr_line: Callable[[str], None] | None = None,
            cwd: str | None = None,
        ) -> RpcClient:
            return RpcClient(
                command=command,
                log_prefix=log_prefix,
                on_exit=on_exit,
                on_stderr_line=on_stderr_line,
                cwd=cwd,
            )

        _registry = ServerRegistry(config=_config, transport_factory=factory)
    assert _config is not None and _registry is not None
    return _config, _registry


class GeditLspPlugin(
    GObject.Object,
    Gedit.WindowActivatable,  # type: ignore[misc]
    PeasGtk.Configurable,  # type: ignore[misc]
):
    __gtype_name__ = "GeditLspPlugin"

    window = GObject.Property(type=Gedit.Window)

    def do_create_configure_widget(self) -> Gtk.Widget:
        from gedit_lsp.ui.prefs import build_preferences_widget
        return build_preferences_widget(_config_path())

    def do_activate(self) -> None:
        cfg, registry = _ensure_globals()
        self._config = cfg
        self._registry = registry
        self._clock = GLibClock()
        self._bridges: dict[Gedit.Document, DocumentBridge] = {}
        self._servers: dict[Gedit.Document, LanguageServer] = {}
        self._diagnostics_ctrls: dict[Gedit.Document, DiagnosticsController] = {}
        self._listener_disposers: dict[Gedit.Document, list[Callable[[], None]]] = {}
        self._completion_ctrls: dict[Gedit.Document, CompletionController] = {}
        self._sighelp_ctrls: dict[Gedit.Document, SignatureHelpController] = {}
        self._formatting_ctrls: dict[Gedit.Document, FormattingController] = {}
        self._mouse_hover_ctrls: dict[Gedit.Document, MouseHoverController] = {}
        self._lightbulb_gutters: dict[Gedit.Tab, LightbulbGutter] = {}
        self._handlers: list[tuple[GObject.Object, int]] = []
        self._actions: list[Gio.SimpleAction] = []
        self._popup_handlers: dict[Any, int] = {}

        win = self.window
        logger.info("plugin activated for window=%s", win)
        for doc in win.get_documents():
            self._attach_document(doc)
        for view in win.get_views():
            self._attach_popup_menu(view)
        self._handlers.append((win, win.connect("tab-added", self._on_tab_added)))
        self._handlers.append((win, win.connect("tab-removed", self._on_tab_removed)))

        self._history = CursorHistory(
            max_entries=cfg.tunable("gotoHistoryMaxEntries")
        )
        self._definition_ctrl = DefinitionController(window=win, history=self._history)
        self._outline_ctrl = OutlineController(
            window=win,
            refresh_debounce_ms=cfg.tunable("outlineRefreshDebounceMs"),
            initial_delay_ms=cfg.tunable("outlineInitialDelayMs"),
        )
        self._statusbar = StatusbarIndicator(win)
        if not cfg.tunable("showStatusbarIndicator"):
            self._statusbar.hide()
        self._diag_panel = DiagnosticsPanel(win)
        self._references_panel = ReferencesPanel(win)
        self._references_ctrl = ReferencesController(
            window=win, panel=self._references_panel,
        )
        self._rename_ctrl = RenameController(window=win)
        self._code_action_ctrl = CodeActionController(window=win)
        self._workspace_symbol_quickpick = WorkspaceSymbolQuickPick(win)
        self._workspace_symbol_ctrl = WorkspaceSymbolController(
            window=win,
            quickpick=self._workspace_symbol_quickpick,
            config=self._config,
        )
        self._crash_notifier = CrashNotifier(win)
        self._handlers.append(
            (win, win.connect("active-tab-changed", lambda *_: self._refresh_statusbar()))
        )

        app = win.get_application() or Gio.Application.get_default()
        for name, config_key, handler in [
            ("lsp-hover", "hover", self._on_hover_activate),
            ("lsp-goto-definition", "goto-definition", self._on_definition_activate),
            ("lsp-go-back", "go-back", self._on_go_back_activate),
            ("lsp-references", "references", self._on_references_activate),
            ("lsp-rename", "rename", self._on_rename_activate),
            ("lsp-code-action", "code-action", self._on_code_action_activate),
            ("lsp-workspace-symbol", "workspace-symbol", self._on_workspace_symbol_activate),
            ("lsp-show-server-logs", "show-server-logs", self._on_show_server_logs_activate),
            ("lsp-format", "format", self._on_format_activate),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            win.add_action(action)
            self._actions.append(action)
            accels = self._config.keybindings_for(config_key)
            if app is not None:
                app.set_accels_for_action(f"win.{name}", accels)  # type: ignore[union-attr]
                logger.info("registered action win.%s accels=%s", name, accels)
            else:
                logger.warning("no application; accels %s for win.%s NOT bound", accels, name)

    def do_deactivate(self) -> None:
        for action in self._actions:
            self.window.remove_action(action.get_name())
        self._actions.clear()
        for view, hid in list(self._popup_handlers.items()):
            with contextlib.suppress(TypeError, RuntimeError):
                view.disconnect(hid)
        self._popup_handlers.clear()
        for gutter in self._lightbulb_gutters.values():
            gutter.dispose()
        self._lightbulb_gutters.clear()
        for obj, hid in self._handlers:
            obj.disconnect(hid)
        self._handlers.clear()
        for bridge in list(self._bridges.values()):
            bridge.detach()
        self._bridges.clear()
        self._servers.clear()
        self._diagnostics_ctrls.clear()
        for ctrl in self._completion_ctrls.values():
            ctrl.dispose()
        self._completion_ctrls.clear()
        for sig_ctrl in self._sighelp_ctrls.values():
            sig_ctrl.dispose()
        self._sighelp_ctrls.clear()
        for mh_ctrl in self._mouse_hover_ctrls.values():
            mh_ctrl.dispose()
        self._mouse_hover_ctrls.clear()
        # FormattingController has no GTK resources to dispose; clear the map.
        self._formatting_ctrls.clear()
        # Window-scoped, like the references panel; just make sure no
        # quick-pick popover is left up across deactivation.
        self._workspace_symbol_quickpick.dismiss()
        for disposers in self._listener_disposers.values():
            for dispose in disposers:
                dispose()
        self._listener_disposers.clear()

    def do_update_state(self) -> None:
        pass

    def _on_tab_added(self, _win: Gedit.Window, tab: Gedit.Tab) -> None:
        doc = tab.get_document()
        self._attach_popup_menu(tab.get_view())
        # Document may not be loaded yet; defer to `loaded` for file-open path,
        # `saved` for the Save-As path (new buffer → file appears), and
        # `notify::language` for the case where gedit infers/changes language
        # after the path is already set. _attach_document is idempotent.
        for sig, cb in (
            ("loaded",           lambda d: self._attach_document(d)),
            ("saved",            lambda d: self._attach_document(d)),
            ("notify::language", lambda d, _p: self._attach_document(d)),
        ):
            self._handlers.append((doc, doc.connect(sig, cb)))

    def _on_tab_removed(self, _win: Gedit.Window, tab: Gedit.Tab) -> None:
        view = tab.get_view()
        hid = self._popup_handlers.pop(view, None)
        if hid is not None:
            with contextlib.suppress(TypeError, RuntimeError):
                view.disconnect(hid)
        gutter = self._lightbulb_gutters.pop(tab, None)
        if gutter is not None:
            gutter.dispose()
        doc = tab.get_document()
        bridge = self._bridges.pop(doc, None)
        if bridge is not None:
            self._diag_panel.clear_for_uri(bridge.uri)
            self._revert_pylsp_view_if_dirty(doc, bridge)
            bridge.detach()
        self._servers.pop(doc, None)
        self._diagnostics_ctrls.pop(doc, None)
        for dispose in self._listener_disposers.pop(doc, []):
            dispose()
        ctrl = self._completion_ctrls.pop(doc, None)
        if ctrl is not None:
            ctrl.dispose()
        sig_ctrl = self._sighelp_ctrls.pop(doc, None)
        if sig_ctrl is not None:
            sig_ctrl.dispose()
        mh_ctrl = self._mouse_hover_ctrls.pop(doc, None)
        if mh_ctrl is not None:
            mh_ctrl.dispose()
        self._formatting_ctrls.pop(doc, None)

    def _revert_pylsp_view_if_dirty(
        self, doc: Gedit.Document, bridge: DocumentBridge
    ) -> None:
        """If `doc` is being closed with unsaved edits, push pylsp's view of
        the file back to the on-disk content before the impending didClose,
        then trigger a documentSymbol request so the server actually
        re-parses (otherwise its parser cache stays pinned at the in-memory
        edits and project-wide queries — notably rename — miss references
        in this file). See `project_pylsp_jedi_rename_caveats`.
        """
        if not doc.get_modified():
            return
        server = self._servers.get(doc)
        if server is None:
            return
        path = Gio.File.new_for_uri(bridge.uri).get_path()
        if path is None:
            return
        try:
            disk_text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.info("revert-on-close: cannot read %s: %r", bridge.uri, exc)
            return
        if disk_text == bridge._text:
            return
        bridge.revert_to_disk(disk_text)
        # Fire-and-forget documentSymbol — its only purpose is to make
        # pylsp call jedi_script() on the now-disk-content version, which
        # is what evicts the stale entry from parso's parser cache.
        server._send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": bridge.uri}},
            lambda _resp: None,
        )

    def _attach_popup_menu(self, view: Any) -> None:
        if view is None or view in self._popup_handlers:
            return
        self._popup_handlers[view] = popup_menu.attach(view, self)

    def _attach_document(self, doc: Gedit.Document) -> None:
        if doc in self._bridges:
            return
        gfile = doc.get_file().get_location()
        if gfile is None:
            logger.info("skip attach: untitled buffer")
            return
        path = Path(gfile.get_path())
        lang = doc.get_language()
        if lang is None:
            logger.info("skip attach: no language for %s", path)
            return
        lang_id = lang.get_id()
        if self._config.server_for(lang_id) is None:
            logger.info("skip attach: no server config for lang_id=%r (%s)", lang_id, path)
            return

        # File-size cap
        size_limit = self._config.tunable("maxFileSizeBytes")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > size_limit:
            self._statusbar.set_state("LSP: skipped (large file)")
            return

        # Ignore-list (glob match against absolute path)
        path_abs = str(path.resolve())
        for pattern in self._config.tunable("disabledForPaths"):
            if fnmatch(path_abs, pattern):
                self._statusbar.set_state("LSP: skipped (path excluded)")
                return
        markers = self._config.root_markers_for(lang_id)
        resolver = ProjectRootResolver(markers=markers)
        root = resolver.resolve(path)
        server = self._registry.get_or_spawn(lang_id, root)
        if server is None:
            return
        # Trigger a buffer attach so server transitions to STARTING/READY
        uri = gfile.get_uri()
        server.attach_buffer(uri)
        text = doc.get_text(doc.get_start_iter(), doc.get_end_iter(), False)
        sync_kind = parse_sync_kind(server.capability("textDocumentSync"))
        bridge = DocumentBridge(
            uri=uri,
            language_id=lang_id,
            text=text,
            server=server,
            clock=self._clock,
            debounce_ms=self._config.tunable("changeDebounceMs"),
            sync_kind=sync_kind,
        )
        bridge.attach()
        self._bridges[doc] = bridge
        self._servers[doc] = server
        logger.info("attached %s lang=%s root=%s", path, lang_id, root)
        disposers: list[Callable[[], None]] = []
        disposers.append(
            server.add_state_listener(lambda _s: self._refresh_statusbar())
        )

        captured_server = server
        captured_bridge = bridge
        captured_doc = doc

        def _state_listener(new_state: ServerState) -> None:
            self._on_server_state(
                captured_server, captured_bridge, captured_doc, new_state
            )

        disposers.append(server.add_state_listener(_state_listener))
        self._refresh_statusbar()

        ctrl = DiagnosticsController(
            buffer=doc,
            severity_underlines=self._config.tunable("severityUnderlineStyle"),
            severity_colors=self._config.tunable("severityUnderlineColor"),
        )
        self._diagnostics_ctrls[doc] = ctrl

        def _on_diag(params: dict[str, Any]) -> None:
            if params.get("uri") != uri:
                return
            diagnostics = params.get("diagnostics", [])
            ctrl.apply_diagnostics(diagnostics)
            self._diag_panel.update_for_uri(uri, diagnostics)

        disposers.append(server.add_diagnostics_listener(_on_diag))
        self._listener_disposers[doc] = disposers

        # Wire LSP completion if enabled in config.
        if "completion" in self._config.tunable("enabledFeatures"):
            view = next(
                (v for v in self.window.get_views() if v.get_buffer() is doc),
                None,
            )
            if view is not None:
                self._completion_ctrls[doc] = CompletionController(
                    view=view, buffer=doc, server=server, uri=uri,
                    flush_pending_change=bridge.flush_pending_change,
                )
                logger.info("attached LSP completion provider for %s", path)
            else:
                logger.info("skip completion attach: no view for doc")

        # Wire LSP signatureHelp if enabled in config.
        if "signatureHelp" in self._config.tunable("enabledFeatures"):
            view = next(
                (v for v in self.window.get_views() if v.get_buffer() is doc),
                None,
            )
            if view is not None:
                self._sighelp_ctrls[doc] = SignatureHelpController(
                    view=view, buffer=doc, server=server, uri=uri,
                    flush_pending_change=bridge.flush_pending_change,
                )
                logger.info("attached LSP signatureHelp controller for %s", path)
            else:
                logger.info("skip signatureHelp attach: no view for doc")

        # Wire mouse-hover controller if the tunable is on and server supports it.
        if should_attach_mouse_hover(
            tunable_enabled="mouseHover" in self._config.tunable("enabledFeatures"),
        ):
            view = next(
                (v for v in self.window.get_views() if v.get_buffer() is doc),
                None,
            )
            if view is not None:
                self._mouse_hover_ctrls[doc] = MouseHoverController(
                    view=view,
                    buffer=doc,
                    server=server,
                    uri=bridge.uri,
                    dwell_ms=self._config.tunable("mouseHoverDwellMs"),
                    spinner_threshold_ms=self._config.tunable(
                        "hoverSpinnerThresholdMs",
                    ),
                )
            else:
                logger.info("skip mouse-hover attach: no view for doc")

        # Wire LSP formatting if enabled in config.
        if "formatting" in self._config.tunable("enabledFeatures"):
            view = next(
                (v for v in self.window.get_views() if v.get_buffer() is doc),
                None,
            )
            if view is not None:
                self._formatting_ctrls[doc] = FormattingController(
                    view=view, buffer=doc, server=server, uri=uri,
                    flush_pending_change=bridge.flush_pending_change,
                )
                logger.info("attached LSP formatting controller for %s", path)
            else:
                logger.info("skip formatting attach: no view for doc")

        def _request_outline() -> bool:
            def _on_outline(msg: dict[str, Any]) -> None:
                items = msg.get("result") or []
                self._outline_ctrl.populate(items)

            server._send_request(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": uri}},
                _on_outline,
            )
            return False  # one-shot

        GLib.timeout_add(self._config.tunable("outlineInitialDelayMs"), _request_outline)

        # Incremental sync: capture pre-edit (line, char_utf16) from the
        # default-priority insert-text/delete-range handlers (these fire
        # *before* GTK applies the edit, so the iters are pre-edit), then
        # refresh the bridge's full-text mirror in the coalesced `changed`
        # signal that fires after each edit. Bridge falls back to Full-sync
        # if sync_kind != INCREMENTAL.
        self._handlers.append(
            (doc, doc.connect("insert-text", self._on_buffer_insert_text))
        )
        self._handlers.append(
            (doc, doc.connect("delete-range", self._on_buffer_delete_range))
        )
        self._handlers.append(
            (doc, doc.connect_after("changed", self._on_doc_changed))
        )
        self._handlers.append(
            (doc, doc.connect("saved", lambda d: self._on_doc_saved(d)))
        )

        # Attach a LightbulbGutter for this view, if not already attached
        # for its tab. (Idempotent: _attach_document may be re-entered via
        # `loaded`/`saved`/`notify::language`.)
        self._attach_lightbulb_gutter(doc, bridge, server, uri)

    def _attach_lightbulb_gutter(
        self,
        doc: Gedit.Document,
        bridge: DocumentBridge,
        server: LanguageServer,
        uri: str,
    ) -> None:
        gfile = doc.get_file().get_location()
        if gfile is None:
            return
        tab = self.window.get_tab_from_location(gfile)
        if tab is None:
            logger.info("lightbulb: no tab for doc; skipping gutter attach")
            return
        if tab in self._lightbulb_gutters:
            return
        view = tab.get_view()
        if view is None:
            return

        def on_activate(line: int) -> None:
            self._code_action_ctrl.trigger(
                server,
                uri,
                bridge.flush_pending_change,
                diagnostics_for_uri=bridge.latest_diagnostics_for,
                cursor_line=line,
            )

        self._lightbulb_gutters[tab] = LightbulbGutter(
            view=view, server=server, uri=uri, on_activate=on_activate,
        )

    def _on_buffer_insert_text(
        self,
        buf: Gtk.TextBuffer,
        location: Gtk.TextIter,
        text: str,
        _length: int,
    ) -> None:
        bridge = self._bridges.get(buf)
        if bridge is None or bridge.sync_kind is not SyncKind.INCREMENTAL:
            return
        line, char = text_iter_to_utf16(location)
        bridge.on_change_event(
            {
                "range": {
                    "start": {"line": line, "character": char},
                    "end":   {"line": line, "character": char},
                },
                "text": text,
            }
        )

    def _on_buffer_delete_range(
        self,
        buf: Gtk.TextBuffer,
        start: Gtk.TextIter,
        end: Gtk.TextIter,
    ) -> None:
        bridge = self._bridges.get(buf)
        if bridge is None or bridge.sync_kind is not SyncKind.INCREMENTAL:
            return
        s_line, s_char = text_iter_to_utf16(start)
        e_line, e_char = text_iter_to_utf16(end)
        bridge.on_change_event(
            {
                "range": {
                    "start": {"line": s_line, "character": s_char},
                    "end":   {"line": e_line, "character": e_char},
                },
                "text": "",
            }
        )

    def _on_doc_changed(self, doc: Gedit.Document) -> None:
        bridge = self._bridges.get(doc)
        if bridge is None:
            return
        text = doc.get_text(doc.get_start_iter(), doc.get_end_iter(), False)
        if bridge.sync_kind is SyncKind.INCREMENTAL:
            bridge.refresh_text(text)
        else:
            bridge.on_changed(text)

    def _on_doc_saved(self, doc: Gedit.Document) -> None:
        bridge = self._bridges.get(doc)
        if bridge is not None:
            bridge.on_saved()

    def _on_hover_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("hover action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("hover: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "hover: doc not bridged (bridge=%s server=%s); attached docs=%d",
                bridge, server, len(self._bridges),
            )
            return
        logger.info("hover: sending request, server.state=%s", server.state)
        ctrl = HoverController(
            view=view,
            buffer=doc,
            server=server,
            uri=bridge.uri,
            spinner_threshold_ms=self._config.tunable("hoverSpinnerThresholdMs"),
        )
        ctrl.trigger()

    def _on_definition_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("definition action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("definition: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "definition: doc not bridged (bridge=%s server=%s)", bridge, server
            )
            return
        logger.info("definition: triggering, server.state=%s", server.state)
        self._definition_ctrl.trigger(server, bridge.uri)

    def _on_go_back_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("go-back action invoked")
        self._definition_ctrl.go_back()

    def _on_references_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("references action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("references: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "references: doc not bridged (bridge=%s server=%s)",
                bridge, server,
            )
            return
        logger.info("references: triggering, server.state=%s", server.state)
        self._references_ctrl.trigger(
            server, bridge.uri, bridge.flush_pending_change,
        )

    def _on_workspace_symbol_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("workspace-symbol action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("workspace-symbol: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "workspace-symbol: doc not bridged (bridge=%s server=%s)",
                bridge, server,
            )
            return
        logger.info(
            "workspace-symbol: triggering, server.state=%s", server.state
        )
        self._workspace_symbol_ctrl.trigger(
            server, view, bridge.flush_pending_change,
        )

    def _on_rename_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("rename action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("rename: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "rename: doc not bridged (bridge=%s server=%s)",
                bridge, server,
            )
            return
        logger.info("rename: triggering, server.state=%s", server.state)
        self._rename_ctrl.trigger(
            server, bridge.uri, bridge.flush_pending_change,
        )

    def _on_code_action_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("code-action action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("code-action: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "code-action: doc not bridged (bridge=%s server=%s)",
                bridge, server,
            )
            return
        logger.info("code-action: triggering, server.state=%s", server.state)
        self._code_action_ctrl.trigger(
            server,
            bridge.uri,
            bridge.flush_pending_change,
            diagnostics_for_uri=bridge.latest_diagnostics_for,
        )

    def _on_format_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        view = self.window.get_active_view()
        if view is None:
            return
        doc = view.get_buffer()
        ctrl = self._formatting_ctrls.get(doc)
        if ctrl is None:
            logger.info("format: no controller for active doc")
            return
        ctrl.trigger()

    def _on_show_server_logs_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        view = self.window.get_active_view()
        doc = view.get_buffer() if view is not None else None
        server = self._servers.get(doc) if doc is not None else None
        if server is None:
            dialog = Gtk.MessageDialog(
                transient_for=self.window,
                modal=False,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.CLOSE,
                text="No language server is attached to the current document.",
            )
            dialog.connect("response", lambda d, _r: d.destroy())
            dialog.show_all()  # type: ignore[attr-defined]
            return
        server_logs.show(self.window, server)

    def _on_server_state(
        self,
        server: LanguageServer,
        bridge: DocumentBridge,
        doc: Gedit.Document,
        new_state: ServerState,
    ) -> None:
        if new_state == ServerState.READY:
            bridge.sync_kind = parse_sync_kind(server.capability("textDocumentSync"))
        if new_state != ServerState.CIRCUIT_OPEN:
            return
        gfile = doc.get_file().get_location()
        if gfile is None:
            return
        tab = self.window.get_tab_from_location(gfile)
        if tab is None:
            return
        max_attempts = self._config.tunable("restartMaxAttempts")
        msg = (
            f"LSP for {server.language_id} ({server.root_path}) "
            f"failed {max_attempts} times."
        )

        def _on_restart() -> None:
            server.reset_circuit_breaker()
            server.attach_buffer(bridge.uri)

        self._crash_notifier.show_for_tab(
            tab,
            msg,
            on_restart=_on_restart,
            on_open_log=self._open_log,
            on_disable=lambda: None,
        )

    def _open_log(self) -> None:
        log_path = Path.home() / ".local/state/gedit-lsp/plugin.log"
        gfile = Gio.File.new_for_path(str(log_path))
        # commands_load_location is the right top-level API; the previous
        # `Window.create_tab_from_location` doesn't exist in the gedit-46
        # typelib (silently no-op'd).
        Gedit.commands_load_location(self.window, gfile, None, 1, 0)

    def _refresh_statusbar(self) -> None:
        view = self.window.get_active_view()
        if view is None:
            self._statusbar.set_state("")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            self._statusbar.set_state("")
            return
        cmd = server.command[0] if server.command else "?"
        states = {
            ServerState.NOT_RUNNING:  f"LSP: {cmd} ⏵",
            ServerState.STARTING:     f"LSP: {cmd} …",
            ServerState.READY:        f"LSP: {cmd} ⚡",
            ServerState.IDLE:         f"LSP: {cmd} ⚡",
            ServerState.STOPPING:     f"LSP: {cmd} ⏹",
            ServerState.CIRCUIT_OPEN: f"LSP: {cmd} ✗ disabled",
        }
        self._statusbar.set_state(states.get(server.state, ""))
