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


# ---------------------------------------------------------------------------
# Motion handler invariants (Task 5)
# ---------------------------------------------------------------------------


def _motion_event(x: float = 5.0, y: float = 5.0, state: int = 0) -> Any:
    event = MagicMock()
    event.x = x
    event.y = y
    event.state = state
    return event


def _stub_iter_at_location(
    view: Any, *, over_text: bool, line: int = 0, char: int = 0,
) -> Gtk.TextIter:
    """Make view.get_iter_at_location return a real iter from a real buffer."""
    buf = GtkSource.Buffer()
    buf.set_text("hello world\nsecond line\n")
    iter_ = buf.get_iter_at_line_offset(line, char)
    view.get_iter_at_location.return_value = (over_text, iter_)
    view.window_to_buffer_coords.return_value = (1, 1)
    return iter_


def test_motion_over_text_schedules_a_timer(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    add_calls: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, cb, *args, **kw: (add_calls.append((ms, cb)), 42)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert len(add_calls) == 1
    assert add_calls[0][0] == 300  # dwell_ms
    assert ctrl._timer_id == 42


def test_second_motion_cancels_first_timer(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    ids = iter([42, 43])
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: next(ids),
    )
    removed: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.source_remove",
        lambda src: removed.append(src),
    )

    ctrl._on_motion(view, _motion_event())
    ctrl._on_motion(view, _motion_event(x=6))

    assert removed == [42]
    assert ctrl._timer_id == 43


def test_motion_over_whitespace_does_not_schedule(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=False)
    add_calls: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (add_calls.append(1), 0)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert add_calls == []
    assert ctrl._timer_id is None


def test_motion_with_button_pressed_does_not_schedule(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    add_calls: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (add_calls.append(1), 0)[1],
    )

    from gi.repository import Gdk
    btn_mask = Gdk.ModifierType.BUTTON1_MASK

    ctrl._on_motion(view, _motion_event(state=btn_mask))

    assert add_calls == []


def test_motion_inside_existing_anchor_range_skips_reschedule(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    start = buf.get_iter_at_line_offset(0, 6)
    end = buf.get_iter_at_line_offset(0, 11)
    inside = buf.get_iter_at_line_offset(0, 8)
    ctrl._anchor_range = (start, end)
    ctrl._popover = MagicMock()  # any non-None
    view.get_iter_at_location.return_value = (True, inside)
    view.window_to_buffer_coords.return_value = (1, 1)
    add_calls: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (add_calls.append(1), 0)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert add_calls == []


def test_motion_increments_request_token(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    monkeypatch.setattr("gi.repository.GLib.timeout_add", lambda *_a, **_kw: 1)
    tok_before = ctrl._request_token

    ctrl._on_motion(view, _motion_event())

    assert ctrl._request_token == tok_before + 1
