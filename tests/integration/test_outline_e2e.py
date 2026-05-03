"""End-to-end outline test."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import gi

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.features.outline import build_tree, detect_response_format
from gedit_lsp.registry import ServerRegistry


def test_outline_returns_class_with_two_methods(
    pylsp_available: None,
    tmp_path: Path,
    registry: ServerRegistry,
    main_loop: GLib.MainLoop,
) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        "class Greeter:\n    def hello(self):\n        return 'hi'\n\n    def goodbye(self):\n        return 'bye'\n"
    )
    (tmp_path / ".git").mkdir()

    server = registry.get_or_spawn("python", tmp_path)
    assert server is not None
    server.attach_buffer(src.as_uri())

    buf = GtkSource.Buffer()
    buf.set_text(src.read_text())
    bridge = DocumentBridge(
        uri=src.as_uri(), language_id="python", text=src.read_text(),
        server=server, clock=GLibClock(), debounce_ms=150,
    )
    bridge.attach()

    def _short_quit() -> bool:
        main_loop.quit()
        return False

    GLib.timeout_add_seconds(2, _short_quit)
    main_loop.run()  # type: ignore[no-untyped-call]

    response: dict[str, Any] | None = None

    def on_resp(msg: dict[str, Any]) -> None:
        nonlocal response
        response = msg
        main_loop.quit()

    def _timeout_quit() -> bool:
        main_loop.quit()
        return False

    server._send_request(
        "textDocument/documentSymbol",
        {"textDocument": {"uri": src.as_uri()}},
        on_resp,
    )
    GLib.timeout_add_seconds(10, _timeout_quit)
    main_loop.run()  # type: ignore[no-untyped-call]

    assert response is not None
    items = response.get("result") or []
    fmt = detect_response_format(items)
    tree = build_tree(items, fmt)
    assert any(node.name == "Greeter" for node in tree)
    greeter = next(n for n in tree if n.name == "Greeter")
    assert {c.name for c in greeter.children} == {"hello", "goodbye"}
