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

import os
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gedit", "46")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import Gedit, Gio, GObject  # type: ignore[attr-defined]

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.config import Config
from gedit_lsp.features.definition import CursorHistory, DefinitionController
from gedit_lsp.features.diagnostics import DiagnosticsController
from gedit_lsp.features.hover import HoverController
from gedit_lsp.log import setup_logging
from gedit_lsp.registry import ServerRegistry
from gedit_lsp.root import ProjectRootResolver
from gedit_lsp.rpc import RpcClient
from gedit_lsp.server import LanguageServer


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

        def factory(command: list[str], log_prefix: str, on_exit: Any) -> RpcClient:
            return RpcClient(command=command, log_prefix=log_prefix, on_exit=on_exit)

        _registry = ServerRegistry(config=_config, transport_factory=factory)
    assert _config is not None and _registry is not None
    return _config, _registry


class GeditLspPlugin(GObject.Object, Gedit.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "GeditLspPlugin"

    window = GObject.Property(type=Gedit.Window)

    def do_activate(self) -> None:
        cfg, registry = _ensure_globals()
        self._config = cfg
        self._registry = registry
        self._clock = GLibClock()
        self._bridges: dict[Gedit.Document, DocumentBridge] = {}
        self._servers: dict[Gedit.Document, LanguageServer] = {}
        self._diagnostics_ctrls: dict[Gedit.Document, DiagnosticsController] = {}
        self._handlers: list[tuple[GObject.Object, int]] = []
        self._actions: list[Gio.SimpleAction] = []

        win = self.window
        for doc in win.get_documents():
            self._attach_document(doc)
        self._handlers.append((win, win.connect("tab-added", self._on_tab_added)))
        self._handlers.append((win, win.connect("tab-removed", self._on_tab_removed)))

        self._history = CursorHistory(
            max_entries=cfg.tunable("gotoHistoryMaxEntries")
        )
        self._definition_ctrl = DefinitionController(window=win, history=self._history)

        app = win.get_application()
        for name, accel, handler in [
            ("lsp-hover", "<Primary>k", self._on_hover_activate),
            ("lsp-goto-definition", "<Primary>period", self._on_definition_activate),
            ("lsp-go-back", "<Alt>Left", self._on_go_back_activate),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            win.add_action(action)
            self._actions.append(action)
            if app is not None:
                app.set_accels_for_action(f"win.{name}", [accel])

    def do_deactivate(self) -> None:
        for action in self._actions:
            self.window.remove_action(action.get_name())
        self._actions.clear()
        for obj, hid in self._handlers:
            obj.disconnect(hid)
        self._handlers.clear()
        for bridge in list(self._bridges.values()):
            bridge.detach()
        self._bridges.clear()
        self._servers.clear()
        self._diagnostics_ctrls.clear()

    def do_update_state(self) -> None:
        pass

    def _on_tab_added(self, _win: Gedit.Window, tab: Gedit.Tab) -> None:
        doc = tab.get_document()
        # Document may not be loaded yet; defer to `loaded` signal
        loaded_handler = doc.connect("loaded", lambda d: self._attach_document(d))
        self._handlers.append((doc, loaded_handler))

    def _on_tab_removed(self, _win: Gedit.Window, tab: Gedit.Tab) -> None:
        doc = tab.get_document()
        bridge = self._bridges.pop(doc, None)
        if bridge is not None:
            bridge.detach()
        self._servers.pop(doc, None)
        self._diagnostics_ctrls.pop(doc, None)

    def _attach_document(self, doc: Gedit.Document) -> None:
        if doc in self._bridges:
            return
        gfile = doc.get_file().get_location()
        if gfile is None:
            return  # untitled buffer
        path = Path(gfile.get_path())
        lang = doc.get_language()
        if lang is None:
            return
        lang_id = lang.get_id()
        if self._config.server_for(lang_id) is None:
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
        bridge = DocumentBridge(
            uri=uri,
            language_id=lang_id,
            text=text,
            server=server,
            clock=self._clock,
            debounce_ms=self._config.tunable("changeDebounceMs"),
        )
        bridge.attach()
        self._bridges[doc] = bridge
        self._servers[doc] = server

        ctrl = DiagnosticsController(
            buffer=doc,
            severity_underlines=self._config.tunable("severityUnderlineStyle"),
        )
        self._diagnostics_ctrls[doc] = ctrl

        def _on_diag(params: dict[str, Any]) -> None:
            if params.get("uri") != uri:
                return
            ctrl.apply_diagnostics(params.get("diagnostics", []))

        server.add_diagnostics_listener(_on_diag)

        self._handlers.append(
            (doc, doc.connect("changed", lambda d: self._on_doc_changed(d)))
        )
        self._handlers.append(
            (doc, doc.connect("saved", lambda d: self._on_doc_saved(d)))
        )

    def _on_doc_changed(self, doc: Gedit.Document) -> None:
        bridge = self._bridges.get(doc)
        if bridge is None:
            return
        text = doc.get_text(doc.get_start_iter(), doc.get_end_iter(), False)
        bridge.on_changed(text)

    def _on_doc_saved(self, doc: Gedit.Document) -> None:
        bridge = self._bridges.get(doc)
        if bridge is not None:
            bridge.on_saved()

    def _on_hover_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        view = self.window.get_active_view()
        if view is None:
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            return
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
        view = self.window.get_active_view()
        if view is None:
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            return
        self._definition_ctrl.trigger(server, bridge.uri)

    def _on_go_back_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        self._definition_ctrl.go_back()
