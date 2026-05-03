"""End-to-end test: pylsp connects, and DiagnosticsController wires up correctly.

The test verifies:
1. A real pylsp subprocess can be spawned and initialises successfully.
2. add_diagnostics_listener delivers published diagnostics to a registered callback.
3. DiagnosticsController.apply_diagnostics() can be called with real LSP payloads.

If pyflakes is importable, the test also opens a broken file and waits for a
non-empty diagnostics notification; otherwise it opens a clean file and asserts
that the empty-diagnostics notification still arrives and is forwarded.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import gi

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.features.diagnostics import DiagnosticsController
from gedit_lsp.rpc import RpcClient
from gedit_lsp.server import LanguageServer


def _has_pyflakes() -> bool:
    try:
        importlib.import_module("pyflakes")
        return True
    except ModuleNotFoundError:
        return False


def test_diagnostics_listener_receives_notifications(
    pylsp_available: None,
    project_dir: Path,
    main_loop: GLib.MainLoop,
) -> None:
    """Verify add_diagnostics_listener is invoked when pylsp publishes diagnostics."""
    src_text = (
        "import nonexistent_module_xyz_42\nprint('ok')\n"
        if _has_pyflakes()
        else "x = 1\n"
    )

    src = project_dir / "target.py"
    src.write_text(src_text)

    exit_codes: list[int] = []

    def on_exit(code: int) -> None:
        exit_codes.append(code)

    def transport_factory(
        command: list[str],
        log_prefix: str,
        on_subprocess_exit: Any,
    ) -> RpcClient:
        return RpcClient(
            command=command,
            log_prefix=log_prefix,
            on_exit=on_exit,
        )

    server = LanguageServer(
        language_id="python",
        root_path=str(project_dir),
        command=["pylsp"],
        initialization_options=None,
        transport_factory=transport_factory,
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
    )

    buf = GtkSource.Buffer()
    buf.set_text(src_text)
    ctrl = DiagnosticsController(
        buffer=buf, severity_underlines={"error": "error", "warning": "error"}
    )

    received: list[dict[str, Any]] = []

    def on_diag(params: dict[str, Any]) -> None:
        if params.get("uri") != src.as_uri():
            return
        received.append(params)
        ctrl.apply_diagnostics(params.get("diagnostics", []))

    server.add_diagnostics_listener(on_diag)
    server.attach_buffer(src.as_uri())

    bridge = DocumentBridge(
        uri=src.as_uri(),
        language_id="python",
        text=src_text,
        server=server,
        clock=GLibClock(),
        debounce_ms=150,
    )
    bridge.attach()

    def _check() -> bool:
        if received:
            main_loop.quit()
            return False
        return True

    def _on_timeout() -> bool:
        main_loop.quit()
        return False

    GLib.timeout_add(50, _check)
    GLib.timeout_add_seconds(15, _on_timeout)
    main_loop.run()  # type: ignore[no-untyped-call]

    assert received, "no diagnostics notification arrived within 15 s"
    last = received[-1]
    diags = last.get("diagnostics", [])

    if _has_pyflakes():
        assert len(diags) > 0, "expected pyflakes to report diagnostics"
        assert any(
            "nonexistent_module_xyz_42" in d.get("message", "")
            or d.get("severity") == 1
            for d in diags
        )
    else:
        # Without a linter, pylsp sends an empty-diagnostics notification;
        # the controller must handle it without crashing.
        assert isinstance(diags, list)
