"""Unit tests for ReferencesController.

The controller is window-scoped and stateless beyond a panel reference.
trigger() is the entire surface: capture cursor, flush, send, dispatch.

Tests cover:
  - 0/1/N dispatch (none -> statusbar, single -> navigate, many -> panel)
  - flush_pending_change called BEFORE _send_request (edit-flush invariant)
  - capability gate: server without `referencesProvider` -> no request
  - request payload shape: textDocument.uri, position, includeDeclaration

No real GTK widgets — view, buffer, statusbar, window are all fakes/mocks.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from gedit_lsp.features.references import ReferencesController


class _FakeStatusbar:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def push(self, ctx: int, msg: str) -> None:
        self.messages.append((ctx, msg))


class _FakeBuffer:
    """Sufficient subset of Gtk.TextBuffer to drive text_iter_to_utf16.

    text_iter_to_utf16 calls iter.get_buffer().get_iter_at_line(line)
    then buffer.get_text(line_start, iter, False), so iters need to know
    their owning buffer.
    """

    def __init__(self, line: int, char: int, line_text: str = "x" * 100) -> None:
        self._line_text = line_text
        self._cursor_iter = _FakeIter(self, line, char)

    def get_iter_at_mark(self, _mark: Any) -> "_FakeIter":
        return self._cursor_iter

    def get_insert(self) -> Any:
        return object()

    def get_iter_at_line(self, line: int) -> "_FakeIter":
        return _FakeIter(self, line, 0)

    def get_text(
        self, start: "_FakeIter", end: "_FakeIter", _hidden: bool
    ) -> str:
        return self._line_text[start.get_line_offset():end.get_line_offset()]


class _FakeIter:
    """Stand-in for Gtk.TextIter, sufficient for text_iter_to_utf16.

    Default `_line_text="x" * 100` keeps `get_text(line_start, iter)`
    returning a string at least as long as the iter's line offset, so a
    cursor at (line=7, char=3) round-trips through text_iter_to_utf16 to
    (7, 3) without forcing each test to spell out a line of source code.
    """

    def __init__(self, buf: _FakeBuffer, line: int, line_offset: int) -> None:
        self._buf = buf
        self._line = line
        self._line_offset = line_offset

    def get_buffer(self) -> _FakeBuffer:
        return self._buf

    def get_line(self) -> int:
        return self._line

    def get_line_offset(self) -> int:
        return self._line_offset


class _FakeView:
    def __init__(self, buf: _FakeBuffer) -> None:
        self._buf = buf

    def get_buffer(self) -> _FakeBuffer:
        return self._buf


class _FakeWindow:
    def __init__(self, view: _FakeView, statusbar: _FakeStatusbar) -> None:
        self._view = view
        self._statusbar = statusbar

    def get_active_view(self) -> _FakeView:
        return self._view

    def get_statusbar(self) -> _FakeStatusbar:
        return self._statusbar


class _FakeServer:
    def __init__(
        self, *, has_references: bool = True,
    ) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self._has_references = has_references

    def capability(self, key: str) -> Any:
        if key == "referencesProvider":
            return self._has_references
        return None

    def _send_request(
        self, method: str, params: dict[str, Any], _cb: Any
    ) -> int:
        self.requests.append((method, params))
        return len(self.requests)


def _build(
    *,
    server: _FakeServer | None = None,
    cursor: tuple[int, int] = (0, 0),
) -> tuple[ReferencesController, _FakeServer, _FakeStatusbar, MagicMock]:
    server = server or _FakeServer()
    statusbar = _FakeStatusbar()
    view = _FakeView(_FakeBuffer(cursor[0], cursor[1]))
    window = _FakeWindow(view, statusbar)
    panel = MagicMock()
    ctrl = ReferencesController(window=window, panel=panel)
    return ctrl, server, statusbar, panel


def _trigger(
    ctrl: ReferencesController,
    server: _FakeServer,
    *,
    flush: Any = None,
) -> None:
    flush = flush or (lambda: None)
    ctrl.trigger(server, "file:///x.py", flush)


# --- 0/1/N dispatch ---------------------------------------------------


def test_none_result_pushes_statusbar_message() -> None:
    ctrl, server, statusbar, panel = _build()
    captured: list[Any] = []

    def fake_send(method: str, params: dict[str, Any], cb: Any) -> int:
        captured.append(cb)
        server.requests.append((method, params))
        return 1

    server._send_request = fake_send  # type: ignore[method-assign]
    _trigger(ctrl, server)
    captured[0]({"result": None})  # server replies "no references"
    assert any("no references" in m.lower() for _ctx, m in statusbar.messages)
    panel.set_results.assert_not_called()


def test_single_result_navigates_directly(monkeypatch: Any) -> None:
    nav_calls: list[tuple[Any, ...]] = []

    def fake_navigate(*args: Any, **kwargs: Any) -> None:
        nav_calls.append((args, kwargs))

    monkeypatch.setattr(
        "gedit_lsp.features.references.navigate_to_uri", fake_navigate
    )

    ctrl, server, _statusbar, panel = _build()
    captured: list[Any] = []
    server._send_request = lambda m, p, cb: (  # type: ignore[method-assign]
        captured.append(cb), server.requests.append((m, p)), 1
    )[-1]

    _trigger(ctrl, server)
    captured[0]({
        "result": [
            {"uri": "file:///a.py",
             "range": {"start": {"line": 4, "character": 2},
                       "end":   {"line": 4, "character": 5}}},
        ]
    })

    assert len(nav_calls) == 1
    args, kwargs = nav_calls[0]
    # Expect navigate_to_uri(window, uri, line, char_utf16, to_iter=...)
    assert args[1] == "file:///a.py"
    assert args[2] == 4
    assert args[3] == 2
    panel.set_results.assert_not_called()


def test_many_results_populate_panel(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "gedit_lsp.features.references.navigate_to_uri",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not navigate on multi-result")
        ),
    )

    ctrl, server, _statusbar, panel = _build()
    captured: list[Any] = []
    server._send_request = lambda m, p, cb: (  # type: ignore[method-assign]
        captured.append(cb), server.requests.append((m, p)), 1
    )[-1]

    _trigger(ctrl, server)
    locs = [
        {"uri": "file:///a.py",
         "range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 1}}},
        {"uri": "file:///b.py",
         "range": {"start": {"line": 1, "character": 0},
                   "end":   {"line": 1, "character": 1}}},
    ]
    captured[0]({"result": locs})

    panel.set_results.assert_called_once_with(locs)
    panel.reveal.assert_called_once()


# --- flush invariant --------------------------------------------------


def test_flush_called_before_send_request() -> None:
    ctrl, server, _statusbar, _panel = _build()
    log: list[str] = []

    def flush() -> None:
        log.append(f"flush@{len(server.requests)}")

    _trigger(ctrl, server, flush=flush)

    # At the moment flush ran, no requests had been sent.
    assert log == ["flush@0"]
    assert len(server.requests) == 1


# --- capability gate --------------------------------------------------


def test_capability_gate_blocks_when_unsupported() -> None:
    server = _FakeServer(has_references=False)
    ctrl, server, statusbar, panel = _build(server=server)
    _trigger(ctrl, server)
    assert server.requests == []
    panel.set_results.assert_not_called()
    assert any(
        "does not support references" in m.lower()
        for _ctx, m in statusbar.messages
    )


# --- payload shape ----------------------------------------------------


def test_request_payload_shape() -> None:
    ctrl, server, _statusbar, _panel = _build(cursor=(7, 3))
    _trigger(ctrl, server)
    assert len(server.requests) == 1
    method, params = server.requests[0]
    assert method == "textDocument/references"
    assert params["textDocument"] == {"uri": "file:///x.py"}
    assert params["position"] == {"line": 7, "character": 3}
    assert params["context"] == {"includeDeclaration": True}
