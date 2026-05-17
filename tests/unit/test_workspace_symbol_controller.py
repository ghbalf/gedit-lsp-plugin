"""Unit tests for WorkspaceSymbolController.

No GTK widgets: server, quick-pick, window, statusbar are fakes/mocks.
The schedule/cancel seams default to GLib but tests inject synchronous
or manual stand-ins.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from gedit_lsp.features.workspace_symbol import WorkspaceSymbolController


class _FakeStatusbar:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def push(self, ctx: int, msg: str) -> None:
        self.messages.append((ctx, msg))


class _FakeWindow:
    def __init__(self, view: Any, statusbar: _FakeStatusbar) -> None:
        self._view = view
        self._statusbar = statusbar

    def get_active_view(self) -> Any:
        return self._view

    def get_statusbar(self) -> _FakeStatusbar:
        return self._statusbar


class _FakeView:
    def __init__(self, buf: Any) -> None:
        self._buf = buf

    def get_buffer(self) -> Any:
        return self._buf


class _FakeServer:
    def __init__(self, *, cap: Any = True) -> None:
        self._cap = cap
        self.requests: list[tuple[str, dict[str, Any], Any]] = []
        self.cancelled: list[int] = []
        self._next_id = 0

    def capability(self, key: str) -> Any:
        return self._cap if key == "workspaceSymbolProvider" else None

    def _send_request(self, method: str, params: dict[str, Any], cb: Any) -> int:
        self._next_id += 1
        self.requests.append((method, params, cb))
        return self._next_id

    def cancel_request(self, request_id: int) -> None:
        self.cancelled.append(request_id)


class _FakeConfig:
    def __init__(self, *, enabled: bool = True, debounce: int = 150) -> None:
        self._enabled = enabled
        self._debounce = debounce

    def tunable(self, key: str) -> Any:
        if key == "enabledFeatures":
            return ["workspaceSymbol"] if self._enabled else ["hover"]
        if key == "workspaceSymbolDebounceMs":
            return self._debounce
        raise KeyError(key)


def _buf(text: str = "compute_total", offset: int = 4) -> Gtk.TextBuffer:
    b = Gtk.TextBuffer()
    b.set_text(text)
    b.place_cursor(b.get_iter_at_offset(offset))
    return b


def _build(
    *,
    server: _FakeServer | None = None,
    config: _FakeConfig | None = None,
    buf_text: str = "",
    immediate: bool = True,
) -> tuple[WorkspaceSymbolController, _FakeServer, Any, _FakeStatusbar, list]:
    server = server or _FakeServer()
    config = config or _FakeConfig()
    statusbar = _FakeStatusbar()
    view = _FakeView(_buf(buf_text, 0) if buf_text else _empty_buf())
    window = _FakeWindow(view, statusbar)
    quickpick = MagicMock()
    scheduled: list = []
    if immediate:
        def schedule(_ms: int, fn: Any) -> int:
            fn()
            return 1
    else:
        def schedule(_ms: int, fn: Any) -> int:
            scheduled.append(fn)
            return len(scheduled)
    ctrl = WorkspaceSymbolController(
        window=window, quickpick=quickpick, config=config,
        schedule=schedule, cancel=lambda _i: None,
    )
    return ctrl, server, quickpick, statusbar, scheduled


def _empty_buf() -> Gtk.TextBuffer:
    b = Gtk.TextBuffer()
    b.set_text("")
    return b


# --- gates -----------------------------------------------------------


def test_capability_gate() -> None:
    ctrl, server, quickpick, statusbar, _ = _build(server=_FakeServer(cap=False))
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    assert server.requests == []
    quickpick.show.assert_not_called()
    assert any("does not support" in m.lower() for _c, m in statusbar.messages)


def test_disabled_feature_noop() -> None:
    ctrl, server, quickpick, _sb, _ = _build(config=_FakeConfig(enabled=False))
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    assert server.requests == []
    quickpick.show.assert_not_called()


# --- flush invariant -------------------------------------------------


def test_flush_before_first_query() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    log: list[str] = []
    view = _FakeView(_buf("compute_total", 4))  # seed -> immediate query
    ctrl.trigger(server, view, lambda: log.append(f"flush@{len(server.requests)}"))
    assert log == ["flush@0"]
    assert server.requests and server.requests[0][0] == "workspace/symbol"


# --- debounce / token ------------------------------------------------


def test_debounce_schedules_then_fires_once() -> None:
    ctrl, server, quickpick, _sb, scheduled = _build(immediate=False)
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("comp")
    assert len(scheduled) == 1            # scheduled, not yet fired
    assert server.requests == []
    scheduled[0]()                        # debounce fires
    assert len(server.requests) == 1
    assert server.requests[0][1] == {"query": "comp"}


def test_inflight_keystroke_cancels() -> None:
    ctrl, server, quickpick, _sb, _ = _build()  # immediate schedule
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("a")          # sends req id 1
    ctrl._on_query("ab")         # should cancel id 1, send id 2
    assert server.cancelled == [1]
    assert [p for _m, p, _c in server.requests] == [{"query": "a"}, {"query": "ab"}]


def test_stale_response_ignored() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("a")          # req 1, cb1
    cb1 = server.requests[0][2]
    ctrl._on_query("ab")         # req 2 (token bumped)
    cb1({"result": [{"name": "stale",
                     "location": {"uri": "file:///x", "range":
                                  {"start": {"line": 0, "character": 0},
                                   "end": {"line": 0, "character": 0}}}}]})
    # cb1 is stale: set_results must NOT be called for it.
    quickpick.set_results.assert_not_called()


def test_empty_query_sends_nothing() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("")
    assert server.requests == []
    quickpick.set_results.assert_called_with([], hint="Type to search symbols")


def test_nonempty_payload_shape() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("Calc")
    assert server.requests[0][0] == "workspace/symbol"
    assert server.requests[0][1] == {"query": "Calc"}


def test_no_match_hint() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("zzz")
    server.requests[0][2]({"result": []})
    quickpick.set_results.assert_called_with([], hint="No symbols match")


def test_results_populate_quickpick() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("c")
    syms = [{"name": "compute_total", "kind": 12,
             "location": {"uri": "file:///lib.py",
                          "range": {"start": {"line": 9, "character": 4},
                                    "end": {"line": 9, "character": 17}}}}]
    server.requests[0][2]({"result": syms})
    quickpick.set_results.assert_called_with(syms)


# --- activation ------------------------------------------------------


def test_activate_with_range_navigates(monkeypatch: Any) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "gedit_lsp.features.workspace_symbol.navigate_to_uri",
        lambda *a, **k: calls.append((a, k)),
    )
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_activate({"name": "f", "location":
                       {"uri": "file:///a.py",
                        "range": {"start": {"line": 7, "character": 3},
                                  "end": {"line": 7, "character": 4}}}})
    assert calls and calls[0][0][1] == "file:///a.py"
    assert calls[0][0][2] == 7 and calls[0][0][3] == 3
    assert server.requests == []  # no resolve when range present


def test_activate_resolve_then_navigate(monkeypatch: Any) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "gedit_lsp.features.workspace_symbol.navigate_to_uri",
        lambda *a, **k: calls.append((a, k)),
    )
    server = _FakeServer(cap={"resolveProvider": True})
    ctrl, server, quickpick, _sb, _ = _build(server=server)  # _build returns the same server instance
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    sym = {"name": "f", "location": {"uri": "file:///a.py"}}
    ctrl._on_activate(sym)
    assert server.requests[0][0] == "workspaceSymbol/resolve"
    assert server.requests[0][1] == sym
    server.requests[0][2]({"result": {"name": "f", "location":
                          {"uri": "file:///a.py",
                           "range": {"start": {"line": 2, "character": 1},
                                     "end": {"line": 2, "character": 2}}}}})
    assert calls and calls[0][0][2] == 2 and calls[0][0][3] == 1


def test_activate_no_resolve_falls_back(monkeypatch: Any) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "gedit_lsp.features.workspace_symbol.navigate_to_uri",
        lambda *a, **k: calls.append((a, k)),
    )
    ctrl, server, quickpick, _sb, _ = _build(server=_FakeServer(cap=True))
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_activate({"name": "f", "location": {"uri": "file:///a.py"}})
    assert calls and calls[0][0][1] == "file:///a.py"
    assert calls[0][0][2] == 0 and calls[0][0][3] == 0
    assert server.requests == []


def test_activate_resolve_error_falls_back(monkeypatch: Any) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "gedit_lsp.features.workspace_symbol.navigate_to_uri",
        lambda *a, **k: calls.append((a, k)),
    )
    server = _FakeServer(cap={"resolveProvider": True})
    ctrl, server, quickpick, _sb, _ = _build(server=server)  # _build returns the same server instance
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_activate({"name": "f", "location": {"uri": "file:///a.py"}})
    server.requests[0][2]({"error": {"code": -32603, "message": "boom"}})
    assert calls and calls[0][0][2] == 0 and calls[0][0][3] == 0


def test_cancel_drops_inflight() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("a")               # req id 1 in flight
    ctrl._on_cancel()
    assert server.cancelled == [1]
    # a late response for the cancelled request is token-guarded
    server.requests[0][2]({"result": [{"name": "x",
                          "location": {"uri": "file:///x"}}]})
    quickpick.set_results.assert_not_called()


def test_retrigger_does_not_accept_previous_session_response() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("a")          # session-1: req id 1, captured token
    cb1 = server.requests[0][2]
    # Re-trigger WITHOUT going through _on_cancel (user hits Shift+F3 again)
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("a")          # session-2: new req, new token
    # Session-1's late response must be rejected as stale even though
    # the query text is identical and it's the same controller.
    cb1({"result": [{"name": "ghost",
                     "location": {"uri": "file:///x", "range":
                                  {"start": {"line": 0, "character": 0},
                                   "end": {"line": 0, "character": 0}}}}]})
    quickpick.set_results.assert_not_called()
    # The old in-flight request must have been cancelled on re-trigger.
    assert 1 in server.cancelled
