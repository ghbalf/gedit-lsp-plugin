"""Unit tests for MouseHoverController — construction, dispose, signal wiring."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource

from gedit_lsp.features.mouse_hover import MouseHoverController


class FakeServer:
    """Minimal LanguageServer stand-in for controller tests."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict, Any]] = []

    def capability(self, key: str) -> Any:
        return True if key == "hoverProvider" else None

    def _send_request(self, method: str, params: dict, cb: Any) -> int:
        self.requests.append((method, params, cb))
        return len(self.requests)


def _make_view() -> Any:
    view = MagicMock(spec=Gtk.TextView)
    # Return integer handler IDs so tests can verify disconnect calls.
    counter = iter(range(1000, 2000))
    view.connect.side_effect = lambda *_a, **_kw: next(counter)
    return view


def _make_ctrl(
    *, view: Any = None, buf: GtkSource.Buffer | None = None,
    server: FakeServer | None = None, dwell_ms: int = 300,
) -> MouseHoverController:
    return MouseHoverController(
        view=view or _make_view(),
        buffer=buf or GtkSource.Buffer(),
        server=server or FakeServer(),
        uri="file:///a.py",
        dwell_ms=dwell_ms,
        spinner_threshold_ms=300,
    )


def test_construction_connects_motion_and_dismissal_signals() -> None:
    view = _make_view()
    _make_ctrl(view=view)
    connected = [call.args[0] for call in view.connect.call_args_list]
    assert "motion-notify-event" in connected
    assert "leave-notify-event" in connected
    assert "focus-out-event" in connected
    assert "key-press-event" in connected
    assert "button-press-event" in connected


def test_dispose_disconnects_all_signals() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl.dispose()
    # One disconnect per connect call.
    assert view.disconnect.call_count == view.connect.call_count


def test_dispose_is_idempotent() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl.dispose()
    # Second dispose must not raise and must not double-disconnect.
    pre = view.disconnect.call_count
    ctrl.dispose()
    assert view.disconnect.call_count == pre


def test_dispose_increments_request_token() -> None:
    ctrl = _make_ctrl()
    tok_before = ctrl._request_token
    ctrl.dispose()
    assert ctrl._request_token == tok_before + 1
