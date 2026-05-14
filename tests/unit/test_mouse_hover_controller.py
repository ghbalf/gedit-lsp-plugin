"""Unit tests for MouseHoverController — construction, dispose, signal wiring."""
from __future__ import annotations

from typing import Any
from unittest.mock import ANY, MagicMock, call

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gdk, Gtk, GtkSource

from gedit_lsp.features.mouse_hover import MouseHoverController, should_attach_mouse_hover


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
    # Real GdkEventMotion always carries `window` — the sub-window the
    # pointer is over. _on_motion must consult it for correct coord
    # translation. Tests get a sentinel that the view mock can identify.
    event.window = "text-subwindow-sentinel"
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
    # Motion events arrive sub-window-relative; default the stub to TEXT,
    # which is the only sub-window we care about for hover.
    view.get_window_type.return_value = Gtk.TextWindowType.TEXT
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


def test_motion_translates_coords_using_event_subwindow_type(monkeypatch: Any) -> None:
    """Regression: pointer coords are sub-window-relative, not widget-relative.

    Motion events from GtkTextView carry `event.window` set to the sub-window
    the pointer is over (TEXT for the text area, LEFT for the line-number
    gutter, etc.). Coordinate translation must consult that window's type via
    `view.get_window_type(event.window)`. Passing a hardcoded WIDGET shifts
    the iter left by the gutter width, dropping the popover for short
    identifiers like `add`/`reset` whose visual position lands in the
    preceding `def` when the gutter offset is double-subtracted.
    """
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: 42,
    )
    event = _motion_event()

    ctrl._on_motion(view, event)

    view.get_window_type.assert_called_once_with(event.window)
    args, _kw = view.window_to_buffer_coords.call_args
    assert args[0] == Gtk.TextWindowType.TEXT


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
    view.get_window_type.return_value = Gtk.TextWindowType.TEXT
    add_calls: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (add_calls.append(1), 0)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert add_calls == []


def test_continuous_whitespace_motion_does_not_reset_pending_grace_timer(
    monkeypatch: Any,
) -> None:
    """Regression for smoke #2: the grace timer is a *deadline*, not a debounce.

    The user reported "popover takes ~150 seconds" when they kept wiggling
    the pointer over whitespace. Previously, each motion event called
    `_cancel_grace_timer()` then re-scheduled, so the 150ms deadline never
    arrived as long as motion continued. The grace timer must fire 150ms
    after the FIRST motion that left the anchor — subsequent motion-while-
    still-in-whitespace must leave the existing timer alone.
    """
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()  # any non-None
    _stub_iter_at_location(view, over_text=False)
    timer_ids = iter([42, 43, 44])
    removed: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: next(timer_ids),
    )
    monkeypatch.setattr(
        "gi.repository.GLib.source_remove",
        lambda src: removed.append(src),
    )

    ctrl._on_motion(view, _motion_event(x=10))
    first_id = ctrl._grace_timer_id

    ctrl._on_motion(view, _motion_event(x=11))
    ctrl._on_motion(view, _motion_event(x=12))

    assert ctrl._grace_timer_id == first_id, (
        "grace timer was re-armed on subsequent motion; deadline never arrives"
    )
    assert first_id not in removed, (
        "grace timer was canceled mid-flight"
    )


def test_motion_back_into_anchor_range_cancels_pending_grace_dismiss(
    monkeypatch: Any,
) -> None:
    """If the user re-enters the anchored word after a brief detour through
    whitespace, the pending grace dismiss must be canceled — otherwise the
    popover dies in mid-hover."""
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    buf = GtkSource.Buffer()
    buf.set_text("    def add(self):\n")
    anchor_start = buf.get_iter_at_line_offset(0, 8)
    anchor_end = buf.get_iter_at_line_offset(0, 11)
    inside = buf.get_iter_at_line_offset(0, 9)  # 'd' of 'add'
    ctrl._anchor_range = (anchor_start, anchor_end)
    ctrl._popover = MagicMock()
    ctrl._grace_timer_id = 77  # simulate a pending grace from prior whitespace
    view.get_iter_at_location.return_value = (True, inside)
    view.window_to_buffer_coords.return_value = (1, 1)
    view.get_window_type.return_value = Gtk.TextWindowType.TEXT
    removed: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.source_remove",
        lambda src: removed.append(src),
    )

    ctrl._on_motion(view, _motion_event())

    assert 77 in removed
    assert ctrl._grace_timer_id is None


def test_response_sets_popover_modal_false(monkeypatch: Any) -> None:
    """Regression for smoke #2 round 2: Gtk.Popover.new(parent) defaults to
    modal=True, which installs a pointer grab on popup. While that grab is
    active the view's motion-notify-event does not fire when the pointer
    moves outside the popover into view whitespace — every dismiss path in
    this controller is motion-driven, so the popover stays up indefinitely
    (only click-outside dismisses, because clicks break the grab). Disable
    modal on the mouse-hover popover specifically; the keyboard Ctrl+K
    popover still needs modal=True because its only dismissal mechanism is
    the modal-grab "click outside / Escape" behavior.
    """
    view = _make_view()
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    iter_ = buf.get_iter_at_line_offset(0, 0)
    ctrl = _make_ctrl(view=view, buf=buf)
    built_popover = MagicMock()
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda _v, _it, _t: built_popover,
    )
    monkeypatch.setattr(
        "gi.repository.GLib.source_remove",
        lambda _src: None,
    )
    ctrl._request_token = 1

    ctrl._on_response(1, iter_, {"result": {"contents": "hello"}})

    built_popover.set_modal.assert_called_once_with(False)


def test_response_cancels_pending_grace_timer_before_showing_new_popover(
    monkeypatch: Any,
) -> None:
    """When a fresh hover response builds a new popover, any grace timer
    armed by motion through the prior anchor's whitespace must be canceled
    — otherwise the new popover dies the moment the stale deadline fires.
    """
    view = _make_view()
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    iter_ = buf.get_iter_at_line_offset(0, 0)
    ctrl = _make_ctrl(view=view, buf=buf)
    ctrl._grace_timer_id = 88  # stale grace from prior motion
    removed: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.source_remove",
        lambda src: removed.append(src),
    )
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda _v, _it, _t: MagicMock(),
    )
    ctrl._request_token = 1

    ctrl._on_response(1, iter_, {"result": {"contents": "hello"}})

    assert 88 in removed
    assert ctrl._grace_timer_id is None
    """Regression for smoke #2: pointer leaving the anchored word — even
    onto a space character between tokens — must dismiss the popover.

    Previously, only past-EOL motion (where get_iter_at_location reports
    over_text=False) scheduled the grace dismiss. Motion onto an
    intertoken space lands on a real character so over_text=True, the
    only effect was scheduling a new dwell whose server response (null
    hover for whitespace) silently dropped — the existing popover stayed
    up indefinitely while the pointer hovered on whitespace.
    """
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    buf = GtkSource.Buffer()
    # "    def add(self, value: float) -> float:" — col 7 is the space
    # between `def` and `add`; the popover was anchored on `add` (8..11).
    buf.set_text("    def add(self, value: float) -> float:\n")
    anchor_start = buf.get_iter_at_line_offset(0, 8)
    anchor_end = buf.get_iter_at_line_offset(0, 11)
    space_iter = buf.get_iter_at_line_offset(0, 7)  # space char — over_text=True
    ctrl._anchor_range = (anchor_start, anchor_end)
    ctrl._popover = MagicMock()
    view.get_iter_at_location.return_value = (True, space_iter)
    view.window_to_buffer_coords.return_value = (1, 1)
    view.get_window_type.return_value = Gtk.TextWindowType.TEXT

    timer_calls: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, cb, *_a, **_kw: (timer_calls.append((ms, cb)), len(timer_calls))[1],
    )

    ctrl._on_motion(view, _motion_event())

    grace_calls = [c for c in timer_calls if c[0] == 150]
    assert len(grace_calls) == 1, f"expected 1 grace timer, got {timer_calls}"
    assert ctrl._grace_timer_id is not None


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


def test_popover_leave_with_inferior_detail_does_not_schedule_grace_dismiss(
    monkeypatch: Any,
) -> None:
    """Regression: GTK fires leave-notify-event on the popover with
    detail=INFERIOR as the pointer crosses into a child widget (e.g. the
    inner ScrolledWindow). That's not the pointer leaving the popover —
    it's still inside, just over a child. Treating INFERIOR as a real
    leave makes the popover dismiss the instant the user reaches the
    scrollable content area.
    """
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    pop = MagicMock()
    captured: dict[str, Any] = {}
    pop.connect.side_effect = lambda sig, cb: (captured.__setitem__(sig, cb), 1)[1]
    ctrl._popover = pop
    ctrl._pointer_in_popover = True
    ctrl._attach_popover_pointer_tracking(pop)

    scheduled: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, _cb, *_a, **_kw: (scheduled.append(ms), 0)[1],
    )

    inferior_leave = MagicMock()
    inferior_leave.detail = Gdk.NotifyType.INFERIOR
    captured["leave-notify-event"](pop, inferior_leave)

    assert scheduled == []
    assert ctrl._pointer_in_popover is True  # still considered inside


def test_popover_leave_with_nonlinear_detail_schedules_grace_dismiss(
    monkeypatch: Any,
) -> None:
    """Positive control: an actual leave (pointer crosses out of the popover
    toplevel) DOES schedule the grace dismiss."""
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    pop = MagicMock()
    captured: dict[str, Any] = {}
    pop.connect.side_effect = lambda sig, cb: (captured.__setitem__(sig, cb), 1)[1]
    ctrl._popover = pop
    ctrl._pointer_in_popover = True
    ctrl._attach_popover_pointer_tracking(pop)

    scheduled: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, _cb, *_a, **_kw: (scheduled.append(ms), 99)[1],
    )

    real_leave = MagicMock()
    real_leave.detail = Gdk.NotifyType.NONLINEAR
    captured["leave-notify-event"](pop, real_leave)

    assert scheduled == [150]
    assert ctrl._pointer_in_popover is False


def test_popover_pointer_tracking_subscribes_to_enter_leave_event_mask() -> None:
    """Regression: enter/leave handlers fire only if the widget's event mask
    includes ENTER_NOTIFY_MASK and LEAVE_NOTIFY_MASK. Gtk.Popover does NOT
    enable those by default, so the `connect` calls used to wire silent
    no-op handlers — `_pointer_in_popover` stayed False, the view-leave
    grace timer ran out, and the popover died as the pointer entered it.
    """
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    pop = MagicMock()
    connect_calls: list[str] = []
    pop.connect.side_effect = lambda sig, _cb: connect_calls.append(sig) or 1

    ctrl._attach_popover_pointer_tracking(pop)

    pop.add_events.assert_called_once()
    mask_arg = pop.add_events.call_args.args[0]
    assert mask_arg & Gdk.EventMask.ENTER_NOTIFY_MASK
    assert mask_arg & Gdk.EventMask.LEAVE_NOTIFY_MASK
    # And add_events must come before connect() so the GdkWindow's mask is
    # already correct by the time we hook the signal handlers.
    assert pop.method_calls.index(call.add_events(mask_arg)) < pop.method_calls.index(
        call.connect("enter-notify-event", ANY)
    )


# ---------------------------------------------------------------------------
# Gate-helper (Task 8)
# ---------------------------------------------------------------------------


def test_should_attach_when_tunable_on() -> None:
    assert should_attach_mouse_hover(tunable_enabled=True)


def test_should_not_attach_when_tunable_off() -> None:
    assert not should_attach_mouse_hover(tunable_enabled=False)


def test_should_attach_when_tunable_on_even_if_capabilities_not_yet_known() -> None:
    # Regression for the smoke-test bug on PR #19: server.capability(...)
    # returns None during _attach_document because the initialize response
    # has not arrived yet. The previous gate read capability at attach time
    # and silently disabled the feature on every fresh document.
    # All other features in this plugin wire on tunable alone and let the
    # request/response path no-op if the server can't actually answer.
    assert should_attach_mouse_hover(tunable_enabled=True)


# ---------------------------------------------------------------------------
# Whitespace-motion grace dismiss (spec gap fix)
# ---------------------------------------------------------------------------


def test_motion_to_whitespace_with_popover_schedules_grace_dismiss(monkeypatch: Any) -> None:
    """Moving to whitespace while a popover is showing arms the grace dismiss."""
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()
    _stub_iter_at_location(view, over_text=False)
    scheduled: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, cb, *a, **kw: (scheduled.append((ms, cb)), 55)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert len(scheduled) == 1
    assert scheduled[0][0] == 150
    assert ctrl._grace_timer_id == 55


def test_motion_to_whitespace_without_popover_does_not_schedule_grace(monkeypatch: Any) -> None:
    """No popover → no need to dismiss anything."""
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = None  # explicit
    _stub_iter_at_location(view, over_text=False)
    scheduled: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (scheduled.append(1), 0)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert scheduled == []


def test_motion_to_whitespace_with_pointer_in_popover_does_not_schedule_grace(monkeypatch: Any) -> None:
    """Pointer transiting into the popover from off-text virtual space → don't grace-dismiss."""
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()
    ctrl._pointer_in_popover = True
    _stub_iter_at_location(view, over_text=False)
    scheduled: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (scheduled.append(1), 0)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert scheduled == []
