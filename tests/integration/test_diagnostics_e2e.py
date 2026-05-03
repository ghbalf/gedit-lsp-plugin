"""End-to-end test: pylsp publishes diagnostics for a broken Python file."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import gi

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.features.diagnostics import DiagnosticsController
from gedit_lsp.registry import ServerRegistry


def test_diagnostics_arrive_for_broken_import(
    pylsp_available: None,
    project_dir: Path,
    registry: ServerRegistry,
    main_loop: GLib.MainLoop,
) -> None:
    src = project_dir / "broken.py"
    src.write_text("import nonexistent_module_xyz_42\nprint('ok')\n")

    server = registry.get_or_spawn("python", project_dir)
    assert server is not None

    buf = GtkSource.Buffer()
    buf.set_text(src.read_text())
    ctrl = DiagnosticsController(
        buffer=buf, severity_underlines={"error": "error", "warning": "error"}
    )

    received: list[list[dict[str, Any]]] = []

    def on_diag(msg: dict[str, Any]) -> None:
        if msg["params"]["uri"] != src.as_uri():
            return
        received.append(msg["params"]["diagnostics"])
        ctrl.apply_diagnostics(msg["params"]["diagnostics"])

    # Patch server's diagnostics handler before attach so the on_notification
    # registration in _spawn_and_initialize picks up the lambda.
    server._on_diagnostics = on_diag  # type: ignore[method-assign]

    server.attach_buffer(src.as_uri())
    bridge = DocumentBridge(
        uri=src.as_uri(),
        language_id="python",
        text=src.read_text(),
        server=server,
        clock=GLibClock(),
        debounce_ms=150,
    )
    bridge.attach()

    def predicate() -> bool:
        return len(received) > 0 and len(received[-1]) > 0

    def _check() -> bool:
        if predicate():
            main_loop.quit()
            return False
        return True

    def _on_timeout() -> bool:
        main_loop.quit()
        return False

    GLib.timeout_add(50, _check)
    GLib.timeout_add_seconds(15, _on_timeout)
    main_loop.run()  # type: ignore[no-untyped-call]
    assert received, "no diagnostics arrived within 15 s"
    assert any(
        "nonexistent_module_xyz_42" in d.get("message", "")
        or d.get("severity") == 1
        for d in received[-1]
    )
