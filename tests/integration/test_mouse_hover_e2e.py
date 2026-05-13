"""End-to-end mouse-hover test against pylsp.

Drives a real MouseHoverController against a real pylsp by directly
calling _on_dwell (the equivalent of "timer fired") with known window
coordinates. Verifies that:
  * the controller sends textDocument/hover with the correct position,
  * the response arrives and is rendered into a popover-build call.

We don't synthesize a real motion-notify-event because (a) test
machines may run headless and (b) the motion → timer → dwell path is
already covered by unit tests; the e2e gate is "the actual server
round-trip with anchored response works".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import GLib, Gtk, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.features.mouse_hover import MouseHoverController
from gedit_lsp.registry import ServerRegistry


def test_mouse_hover_e2e_returns_response_and_anchors(
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

    # Wait for initialize/initialized handshake.
    def _short_quit() -> bool:
        main_loop.quit()
        return False
    GLib.timeout_add_seconds(2, _short_quit)
    main_loop.run()  # type: ignore[no-untyped-call]

    # Build a controller against a fake view but the real buffer + server.
    view = MagicMock(spec=Gtk.TextView)
    # The controller's _on_dwell calls view.get_iter_at_location(bx, by) to
    # re-translate the cached coordinates. Anchor on "join" at line 1.
    line_text = src.read_text().splitlines()[1]
    char = line_text.find("join")
    anchor = buf.get_iter_at_line_offset(1, char)
    view.get_iter_at_location.return_value = (True, anchor)

    # build_hover_popover is widget-dependent; stub it so we don't need a
    # display to construct the popover. We assert the controller calls it
    # with the right arguments.
    built: list[tuple[Any, Any, str]] = []
    import gedit_lsp.features.mouse_hover as mh

    original_build = mh.build_hover_popover

    def fake_build(v: Any, it: Any, txt: str) -> Any:
        built.append((v, it, txt))
        return MagicMock()

    mh.build_hover_popover = fake_build  # type: ignore[assignment]
    try:
        ctrl = MouseHoverController(
            view=view, buffer=buf, server=server, uri=src.as_uri(),
            dwell_ms=10, spinner_threshold_ms=300,
        )

        # Drive a dwell directly with the current token and arbitrary coords
        # (view.get_iter_at_location returns our chosen iter regardless).
        ctrl._on_dwell(ctrl._request_token, 100, 50)

        # Pump the main loop until the popover gets built or 10s pass.
        def _timeout_quit() -> bool:
            main_loop.quit()
            return False
        GLib.timeout_add_seconds(10, _timeout_quit)

        def _ready() -> bool:
            if built:
                main_loop.quit()
                return False
            return True
        GLib.timeout_add(100, _ready)
        main_loop.run()  # type: ignore[no-untyped-call]

        assert built, "no popover built — server did not respond in time"
        _v, _it, text = built[0]
        assert "join" in text.lower()
        assert ctrl._anchor_range is not None
    finally:
        mh.build_hover_popover = original_build  # type: ignore[assignment]
