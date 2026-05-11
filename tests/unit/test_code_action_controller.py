"""Tests for CodeActionController."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from gedit_lsp.features.code_action import CodeActionController


class FakeServer:
    """Minimal fake of LanguageServer for controller tests."""

    def __init__(self, capability: Any = True) -> None:
        self._capability = capability
        self.requests: list[tuple[str, dict, Any]] = []  # (method, params, cb)
        self.notifications: list[tuple[str, dict]] = []

    def capability(self, key: str) -> Any:
        return self._capability if key == "codeActionProvider" else None

    def _send_request(self, method: str, params: dict, cb: Any) -> int:
        self.requests.append((method, params, cb))
        return len(self.requests)

    def send_notification(self, method: str, params: dict) -> None:
        self.notifications.append((method, params))


def _make_window(*, statusbar: Any = None, view: Any = None) -> Any:
    win = MagicMock()
    win.get_statusbar.return_value = statusbar or MagicMock()
    win.get_active_view.return_value = view
    return win


def _make_view_at_cursor(line: int = 0, char: int = 0) -> Any:
    """Return a MagicMock view whose buffer's insert iter is at (line, char)."""
    view = MagicMock()
    buf = MagicMock()
    insert_iter = MagicMock()
    insert_iter.get_line.return_value = line
    insert_iter.get_line_offset.return_value = char  # UTF-8; UTF-16 via patch
    buf.get_iter_at_mark.return_value = insert_iter
    buf.get_insert.return_value = MagicMock()
    view.get_buffer.return_value = buf
    return view


def test_no_capability_means_statusbar_message_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=None)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    controller = CodeActionController(window=window)
    flush = MagicMock()
    diags = MagicMock(return_value=[])

    controller.trigger(server, "file:///a.py", flush, diags)

    assert server.requests == []
    statusbar.push.assert_called_once()
    msg = statusbar.push.call_args[0][1]
    assert "code action" in msg.lower()
    flush.assert_not_called()


def _patch_utf16(monkeypatch: pytest.MonkeyPatch, *, line: int, char: int) -> None:
    """Patch text_iter_to_utf16 to return predictable (line, char)."""
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.text_iter_to_utf16",
        lambda _it: (line, char),
    )


def test_trigger_flushes_then_sends_request(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)

    calls: list[str] = []
    def flush() -> None:
        calls.append("flush")
        # Recording the order: flush must precede the send
        assert server.requests == [], "flush must happen before send"

    controller = CodeActionController(window=window)
    _patch_utf16(monkeypatch, line=5, char=2)

    controller.trigger(
        server, "file:///a.py", flush,
        diagnostics_for_uri=lambda _uri: [],
    )

    assert calls == ["flush"]
    assert len(server.requests) == 1
    method, params, _cb = server.requests[0]
    assert method == "textDocument/codeAction"
    assert params["textDocument"] == {"uri": "file:///a.py"}
    assert params["range"]["start"] == {"line": 5, "character": 2}
    assert params["range"]["end"] == {"line": 5, "character": 2}
    assert params["context"]["triggerKind"] == 1
    assert params["context"]["diagnostics"] == []


def test_trigger_passes_overlapping_diagnostics_in_context(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)
    controller = CodeActionController(window=window)
    _patch_utf16(monkeypatch, line=3, char=4)

    diags_at_other_line = [
        {"range": {"start": {"line": 99, "character": 0}, "end": {"line": 99, "character": 1}}, "id": "off"},
    ]
    diags_overlapping = {
        "range": {"start": {"line": 3, "character": 0}, "end": {"line": 3, "character": 10}},
        "id": "match",
    }

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [diags_overlapping, *diags_at_other_line],
    )

    _, params, _ = server.requests[0]
    assert len(params["context"]["diagnostics"]) == 1
    assert params["context"]["diagnostics"][0]["id"] == "match"


def test_trigger_no_view_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    window = _make_window(view=None)
    controller = CodeActionController(window=window)
    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    assert server.requests == []


def test_response_error_statusbar_no_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    popover = MagicMock()
    controller = CodeActionController(
        window=window, popover_factory=lambda _v: popover,
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, cb = server.requests[0]
    cb({"error": {"code": -32603, "message": "bad"}})

    popover.show.assert_not_called()
    pushed = [c.args[1] for c in statusbar.push.call_args_list]
    assert any("failed" in m.lower() for m in pushed)


def test_response_null_statusbar_no_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    popover = MagicMock()
    controller = CodeActionController(
        window=window, popover_factory=lambda _v: popover,
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, cb = server.requests[0]
    cb({"result": None})

    popover.show.assert_not_called()
    pushed = [c.args[1] for c in statusbar.push.call_args_list]
    assert any("no code actions" in m.lower() for m in pushed)


def test_response_empty_list_statusbar_no_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    popover = MagicMock()
    controller = CodeActionController(
        window=window, popover_factory=lambda _v: popover,
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, cb = server.requests[0]
    cb({"result": []})

    popover.show.assert_not_called()
    pushed = [c.args[1] for c in statusbar.push.call_args_list]
    assert any("no code actions" in m.lower() for m in pushed)


def test_response_with_actions_shows_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)
    popover = MagicMock()
    controller = CodeActionController(
        window=window, popover_factory=lambda _v: popover,
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, cb = server.requests[0]
    cb({"result": [
        {"title": "Fix import", "kind": "quickfix", "edit": {"changes": {}}},
    ]})

    popover.show.assert_called_once()
    actions = popover.show.call_args.kwargs["actions"]
    assert len(actions) == 1
    assert actions[0]["title"] == "Fix import"


def test_lightbulb_cursor_line_repositions_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor(line=0, char=0)
    buf = view.get_buffer.return_value
    line_iter = MagicMock()
    buf.get_iter_at_line.return_value = line_iter
    window = _make_window(view=view)
    controller = CodeActionController(window=window)
    _patch_utf16(monkeypatch, line=8, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
        cursor_line=8,
    )

    buf.get_iter_at_line.assert_called_once_with(8)
    buf.place_cursor.assert_called_once_with(line_iter)
