"""End-to-end hover test against pylsp."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import gi

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "300")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.features.hover import render_hover_contents
from gedit_lsp.registry import ServerRegistry


def test_hover_returns_join_for_os_path_join(
    pylsp_available: None,
    tmp_path: Path,
    registry: ServerRegistry,
    main_loop: GLib.MainLoop,
) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "import os\nresult = os.path.join(\"a\", \"b\")\nprint(result)\n"
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

    # Wait briefly for pylsp initialize/initialized handshake to complete
    def _short_quit() -> bool:
        main_loop.quit()
        return False

    GLib.timeout_add_seconds(2, _short_quit)
    main_loop.run()  # type: ignore[no-untyped-call]

    # Cursor on the `j` in `join` (line 1, character offset)
    line_text = src.read_text().splitlines()[1]
    char = line_text.find("join")
    response: dict[str, Any] | None = None

    def on_resp(msg: dict[str, Any]) -> None:
        nonlocal response
        response = msg
        main_loop.quit()

    def _timeout_quit() -> bool:
        main_loop.quit()
        return False

    server._send_request(
        "textDocument/hover",
        {
            "textDocument": {"uri": src.as_uri()},
            "position": {"line": 1, "character": char},
        },
        on_resp,
    )
    GLib.timeout_add_seconds(10, _timeout_quit)
    main_loop.run()  # type: ignore[no-untyped-call]

    assert response is not None and response.get("result") is not None
    contents = response["result"].get("contents")
    rendered = render_hover_contents(contents)
    assert "join" in rendered.lower()
