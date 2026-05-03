"""End-to-end go-to-definition test against pylsp."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import gi

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "4")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.registry import ServerRegistry


def test_definition_jumps_to_helper(
    pylsp_available: None,
    tmp_path: Path,
    registry: ServerRegistry,
    main_loop: GLib.MainLoop,
) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "def helper(x):\n    return x + 1\n\n\ndef main():\n    return helper(42)\n"
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

    # Cursor on `helper` at line 5, char 11 (after "    return ")
    response: dict[str, Any] | None = None

    def on_resp(msg: dict[str, Any]) -> None:
        nonlocal response
        response = msg
        main_loop.quit()

    def _timeout_quit() -> bool:
        main_loop.quit()
        return False

    server._send_request(
        "textDocument/definition",
        {
            "textDocument": {"uri": src.as_uri()},
            "position": {"line": 5, "character": 11},
        },
        on_resp,
    )
    GLib.timeout_add_seconds(10, _timeout_quit)
    main_loop.run()  # type: ignore[no-untyped-call]

    assert response is not None
    res = response.get("result")
    assert res, f"no definition: {response}"
    # Could be Location or list[Location]
    loc = res[0] if isinstance(res, list) else res
    assert loc["range"]["start"]["line"] == 0  # helper is defined on line 0
