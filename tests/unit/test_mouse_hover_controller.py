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


def test_motion_with_button_pressed_cancels_pending_timer(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._timer_id = 99  # simulate pending dwell from pre-drag motion
    removed: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.source_remove",
        lambda src: removed.append(src),
    )

    from gi.repository import Gdk
    btn_mask = Gdk.ModifierType.BUTTON1_MASK

    ctrl._on_motion(view, _motion_event(state=btn_mask))

    assert removed == [99]
    assert ctrl._timer_id is None


# ---------------------------------------------------------------------------
# Dwell + response (Task 6)
# ---------------------------------------------------------------------------


def test_dwell_sends_hover_request_with_position(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    ctrl = _make_ctrl(view=view, server=server, buf=buf)
    # When _on_dwell re-translates, return our chosen iter:
    anchor = buf.get_iter_at_line_offset(0, 6)
    view.get_iter_at_location.return_value = (True, anchor)

    ctrl._on_dwell(ctrl._request_token, 100, 50)

    assert len(server.requests) == 1
    method, params, _cb = server.requests[0]
    assert method == "textDocument/hover"
    assert params["textDocument"]["uri"] == "file:///a.py"
    assert params["position"] == {"line": 0, "character": 6}


def test_stale_token_dwell_drops_request() -> None:
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    stale = ctrl._request_token
    ctrl._request_token += 1  # simulate cancel/dispose racing

    ctrl._on_dwell(stale, 100, 50)

    assert server.requests == []


def test_dwell_over_whitespace_does_not_send_request() -> None:
    """Even if motion scheduled this dwell, buffer state may have changed."""
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    view.get_iter_at_location.return_value = (False, MagicMock())

    ctrl._on_dwell(ctrl._request_token, 100, 50)

    assert server.requests == []


def test_response_with_token_match_builds_popover(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    ctrl = _make_ctrl(view=view, server=server, buf=buf)
    anchor = buf.get_iter_at_line_offset(0, 6)
    built: list[tuple[Any, Any, str]] = []
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda v, it, txt: (built.append((v, it, txt)), MagicMock())[1],
    )

    ctrl._on_response(
        ctrl._request_token, anchor,
        {"result": {"contents": "type: str",
                    "range": {"start": {"line": 0, "character": 6},
                              "end":   {"line": 0, "character": 11}}}},
    )

    assert len(built) == 1
    assert built[0][2] == "type: str"
    assert ctrl._popover is not None
    assert ctrl._anchor_range is not None


def test_response_stale_token_does_not_build_popover(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    built: list[int] = []
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda *_a, **_kw: (built.append(1), MagicMock())[1],
    )
    buf = GtkSource.Buffer()
    buf.set_text("hello\n")
    anchor = buf.get_iter_at_line_offset(0, 0)
    stale = ctrl._request_token
    ctrl._request_token += 1

    ctrl._on_response(
        stale, anchor,
        {"result": {"contents": "x"}},
    )

    assert built == []
    assert ctrl._popover is None


def test_response_empty_contents_does_not_build_popover(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    built: list[int] = []
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda *_a, **_kw: (built.append(1), MagicMock())[1],
    )
    buf = GtkSource.Buffer()
    buf.set_text("hello\n")
    anchor = buf.get_iter_at_line_offset(0, 0)

    ctrl._on_response(
        ctrl._request_token, anchor,
        {"result": {"contents": "   \n  "}},
    )

    assert built == []


def test_response_error_does_not_build_popover(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    built: list[int] = []
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda *_a, **_kw: (built.append(1), MagicMock())[1],
    )
    buf = GtkSource.Buffer()
    buf.set_text("hello\n")
    anchor = buf.get_iter_at_line_offset(0, 0)

    ctrl._on_response(
        ctrl._request_token, anchor,
        {"error": {"code": -32603, "message": "boom"}},
    )

    assert built == []


def test_response_without_server_range_falls_back_to_word_bounds(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    ctrl = _make_ctrl(view=view, server=server, buf=buf)
    anchor = buf.get_iter_at_line_offset(0, 8)  # inside "world"
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda *_a, **_kw: MagicMock(),
    )

    ctrl._on_response(
        ctrl._request_token, anchor,
        {"result": {"contents": "type: str"}},  # no range
    )

    assert ctrl._anchor_range is not None
    start, end = ctrl._anchor_range
    assert buf.get_text(start, end, False) == "world"


# ---------------------------------------------------------------------------
# Dismissal handlers (Task 7)
# ---------------------------------------------------------------------------


def test_key_press_dismisses_popover() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()
    ctrl._anchor_range = (MagicMock(), MagicMock())

    ctrl._on_key_press(view, MagicMock())

    assert ctrl._popover is None
    assert ctrl._anchor_range is None


def test_button_press_dismisses_popover() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    pop = MagicMock()
    ctrl._popover = pop
    ctrl._anchor_range = (MagicMock(), MagicMock())

    ctrl._on_button_press(view, MagicMock())

    pop.popdown.assert_called_once()
    assert ctrl._popover is None


def test_focus_out_dismisses_popover() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()

    ctrl._on_focus_out(view, MagicMock())

    assert ctrl._popover is None


def test_view_leave_with_pointer_in_popover_does_not_dismiss(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    pop = MagicMock()
    ctrl._popover = pop
    ctrl._pointer_in_popover = True
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add", lambda *_a, **_kw: 99,
    )

    ctrl._on_view_leave(view, MagicMock())

    pop.popdown.assert_not_called()
    assert ctrl._popover is pop


def test_view_leave_without_pointer_in_popover_schedules_grace_dismiss(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()
    scheduled: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, cb, *a, **kw: (scheduled.append((ms, cb)), 77)[1],
    )

    ctrl._on_view_leave(view, MagicMock())

    assert len(scheduled) == 1
    assert scheduled[0][0] == 150  # grace_ms
    assert ctrl._grace_timer_id == 77


def test_popover_leave_schedules_grace_dismiss(monkeypatch: Any) -> None:
    """Pointer leaving the popover (without view leave-notify) must arm dismiss."""
    view = _make_view()
    ctrl = _make_ctrl(view=view)

    # Construct a fake popover; capture its connect() callbacks so we can fire
    # the leave-notify handler directly.
    pop = MagicMock()
    captured_handlers: dict[str, Any] = {}

    def fake_connect(signal: str, cb: Any) -> int:
        captured_handlers[signal] = cb
        return len(captured_handlers)

    pop.connect.side_effect = fake_connect

    ctrl._popover = pop
    ctrl._pointer_in_popover = True
    ctrl._attach_popover_pointer_tracking(pop)

    scheduled: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, cb, *a, **kw: (scheduled.append((ms, cb)), 88)[1],
    )

    # Fire the popover-side leave-notify-event callback directly.
    captured_handlers["leave-notify-event"](pop, MagicMock())

    assert ctrl._pointer_in_popover is False
    assert len(scheduled) == 1
    assert scheduled[0][0] == 150
    assert ctrl._grace_timer_id == 88
