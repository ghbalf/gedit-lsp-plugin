"""Unit tests for RenameController.

Three thrust areas:

  1. Capability + prepareRename branching — the controller honours
     renameProvider.prepareProvider, branches on the four protocol
     response shapes, and falls back to derive_placeholder on error.
  2. Edit-flush invariant — flush_pending_change() runs before the
     first request goes out (whether prepareRename or rename).
  3. WorkspaceEdit apply — controller collects URIs, async-loads
     closed ones via the load_uri seam, then delegates to
     apply_workspace_edit and publishes the per-file summary.

No real GTK widgets — view/buffer/window/popover are all fakes/mocks.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("GtkSource", "300")
from gi.repository import GtkSource  # type: ignore[attr-defined]

from gedit_lsp.features.rename import RenameController


class _FakeStatusbar:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def push(self, ctx: int, msg: str) -> None:
        self.messages.append((ctx, msg))


class _FakeBuffer:
    """Sufficient subset of Gtk.TextBuffer to drive text_iter_to_utf16
    and the prepareRename Range-shape placeholder reader.
    """

    def __init__(
        self,
        line: int,
        char: int,
        line_text: str = "x" * 100,
    ) -> None:
        self._line_text = line_text
        self._cursor_iter = _FakeIter(self, line, char)

    def get_iter_at_mark(self, _mark: Any) -> _FakeIter:
        return self._cursor_iter

    def get_insert(self) -> Any:
        return object()

    def get_iter_at_line(self, line: int) -> _FakeIter:
        return _FakeIter(self, line, 0)

    def get_text(
        self, start: _FakeIter, end: _FakeIter, _hidden: bool
    ) -> str:
        return self._line_text[start.get_line_offset():end.get_line_offset()]


class _FakeIter:
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
        self,
        *,
        rename_capability: Any = True,
    ) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self._rename_cap = rename_capability
        # callbacks keyed by request index
        self.callbacks: list[Any] = []

    def capability(self, key: str) -> Any:
        if key == "renameProvider":
            return self._rename_cap
        return None

    def _send_request(
        self, method: str, params: dict[str, Any], cb: Any
    ) -> int:
        self.requests.append((method, params))
        self.callbacks.append(cb)
        return len(self.requests)


class _FakePopover:
    """Synchronous popover: show() immediately fires on_commit with
    `commit_text` if set, or on_cancel otherwise.
    """
    def __init__(
        self,
        view: Any,
        *,
        commit_text: str | None = None,
    ) -> None:
        self._view = view
        self._commit_text = commit_text
        self.shown_with: dict[str, Any] | None = None

    def show(
        self,
        *,
        placeholder: str,
        on_commit: Any,
        on_cancel: Any,
    ) -> None:
        self.shown_with = {"placeholder": placeholder}
        if self._commit_text is None:
            on_cancel()
        else:
            on_commit(self._commit_text)


def _make_buffer_for_real_derive_placeholder() -> GtkSource.Buffer:
    """A real GtkSource.Buffer so derive_placeholder can read from it.

    Line 0 is "foo = bar(baz)" for derive_placeholder tests (cursor at col 7
    lands inside "bar"). Lines 1-8 are filler so cursor=(7, 3) in
    test_rename_request_payload_shape is not clamped by GTK.
    """
    b = GtkSource.Buffer()
    b.set_text(
        "foo = bar(baz)\n"
        "x\n" "x\n" "x\n" "x\n" "x\n" "x\n"
        "abcdefg\n"   # line 7: at least 3 chars so get_iter_at_line_offset(7,3) works
        "x\n",
        -1,
    )
    return b


def _build(
    *,
    server: _FakeServer | None = None,
    cursor: tuple[int, int] = (0, 7),
    popover_commit_text: str | None = "new_name",
    load_uri: Any = None,
    buffer_for_uri: Any = None,
    real_buffer: bool = False,
) -> tuple[RenameController, _FakeServer, _FakeStatusbar, list[_FakePopover]]:
    server = server or _FakeServer()
    statusbar = _FakeStatusbar()
    if real_buffer:
        buf = _make_buffer_for_real_derive_placeholder()
        # _FakeBuffer wrapping a real GtkSource.Buffer — but the real
        # buffer's iters work too, so use it directly:
        view = MagicMock()
        view.get_buffer.return_value = buf

        class _BufWindow:
            def __init__(self) -> None:
                self._sb = statusbar
            def get_active_view(self) -> Any:
                return view
            def get_statusbar(self) -> Any:
                return self._sb
        # Simulate cursor by patching get_iter_at_mark on the real buffer:
        cursor_iter = buf.get_iter_at_line_offset(cursor[0], cursor[1])
        buf.get_iter_at_mark = lambda _m: cursor_iter  # type: ignore[assignment, method-assign]
        buf.get_insert = lambda: object()  # type: ignore[assignment, method-assign]
        window = _BufWindow()
    else:
        view = _FakeView(_FakeBuffer(cursor[0], cursor[1]))
        window = _FakeWindow(view, statusbar)

    popovers: list[_FakePopover] = []

    def _factory(v: Any) -> _FakePopover:
        p = _FakePopover(v, commit_text=popover_commit_text)
        popovers.append(p)
        return p

    ctrl = RenameController(
        window=window,
        popover_factory=_factory,
        load_uri=load_uri or (lambda _w, _u, on_done: on_done(True)),
        buffer_for_uri=buffer_for_uri or (lambda _w, _u: MagicMock()),
    )
    return ctrl, server, statusbar, popovers


def _trigger(
    ctrl: RenameController,
    server: _FakeServer,
    *,
    flush: Any = None,
) -> None:
    flush = flush or (lambda: None)
    ctrl.trigger(server, "file:///x.py", flush)


# --- capability gate -------------------------------------------------


def test_capability_gate_blocks_when_unsupported() -> None:
    server = _FakeServer(rename_capability=False)
    ctrl, server, statusbar, popovers = _build(server=server)
    _trigger(ctrl, server)
    assert server.requests == []
    assert popovers == []
    assert any(
        "does not support rename" in m.lower()
        for _ctx, m in statusbar.messages
    )


def test_capability_gate_blocks_when_capability_is_none() -> None:
    server = _FakeServer(rename_capability=None)
    ctrl, server, _statusbar, popovers = _build(server=server)
    _trigger(ctrl, server)
    assert server.requests == []
    assert popovers == []


# --- prepareRename: gating + branches -------------------------------


def test_prepareRename_skipped_when_prepareProvider_falsy() -> None:
    # capability is True (boolean) — no prepareProvider → skip prepareRename
    server = _FakeServer(rename_capability=True)
    ctrl, server, _statusbar, popovers = _build(
        server=server, real_buffer=True, popover_commit_text=None,
    )
    _trigger(ctrl, server)
    # No request fired (popover commit_text was None → no rename either)
    assert server.requests == []
    # But the popover WAS shown
    assert len(popovers) == 1


def test_prepareRename_sent_when_prepareProvider_true() -> None:
    server = _FakeServer(
        rename_capability={"prepareProvider": True},
    )
    ctrl, server, _statusbar, popovers = _build(
        server=server, popover_commit_text=None,
    )
    _trigger(ctrl, server)
    assert len(server.requests) == 1
    assert server.requests[0][0] == "textDocument/prepareRename"
    # Popover not yet shown (waiting for prepare response)
    assert popovers == []


def test_prepareRename_null_pushes_cannot_rename_here_no_popover() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, statusbar, popovers = _build(server=server)
    _trigger(ctrl, server)
    server.callbacks[0]({"result": None})
    assert popovers == []
    assert any(
        "cannot rename" in m.lower() for _ctx, m in statusbar.messages
    )


def test_prepareRename_with_placeholder_used_directly() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, popovers = _build(
        server=server, popover_commit_text=None,
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "range": {"start": {"line": 0, "character": 0},
                  "end":   {"line": 0, "character": 3}},
        "placeholder": "ServerSaidThis",
    }})
    assert len(popovers) == 1
    assert popovers[0].shown_with == {"placeholder": "ServerSaidThis"}


def test_prepareRename_default_behavior_uses_derive_placeholder() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, popovers = _build(
        server=server, real_buffer=True, popover_commit_text=None,
        cursor=(0, 7),  # inside "bar"
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {"defaultBehavior": True}})
    assert len(popovers) == 1
    assert popovers[0].shown_with == {"placeholder": "bar"}


def test_prepareRename_range_reads_buffer_text_for_placeholder() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, popovers = _build(
        server=server, real_buffer=True, popover_commit_text=None,
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "start": {"line": 0, "character": 6},
        "end":   {"line": 0, "character": 9},
    }})
    assert len(popovers) == 1
    assert popovers[0].shown_with == {"placeholder": "bar"}


def test_prepareRename_error_falls_back_to_derive_placeholder() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, popovers = _build(
        server=server, real_buffer=True, popover_commit_text=None,
        cursor=(0, 7),
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"error": {"code": -32601, "message": "method not found"}})
    assert len(popovers) == 1
    assert popovers[0].shown_with == {"placeholder": "bar"}


# --- edit-flush invariant -------------------------------------------


def test_flush_called_before_prepareRename_when_prepareProvider_true() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, _popovers = _build(server=server, popover_commit_text=None)
    log: list[str] = []

    def flush() -> None:
        log.append(f"flush@{len(server.requests)}")

    _trigger(ctrl, server, flush=flush)
    assert log == ["flush@0"]
    assert len(server.requests) == 1


def test_flush_called_before_rename_when_no_prepareProvider() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, _statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
    )
    log: list[str] = []

    def flush() -> None:
        log.append(f"flush@{len(server.requests)}")

    _trigger(ctrl, server, flush=flush)
    assert log == ["flush@0"]
    # rename request was sent (no prepareRename in this path)
    assert len(server.requests) == 1
    assert server.requests[0][0] == "textDocument/rename"


# --- rename request: payload + empty/unchanged + errors -------------


def test_empty_newName_does_not_send_rename_request() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, _popovers = _build(
        server=server, popover_commit_text="",
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "range": {"start": {"line": 0, "character": 0},
                  "end":   {"line": 0, "character": 3}},
        "placeholder": "old",
    }})
    # Only the prepareRename request was sent — no rename followup.
    assert [r[0] for r in server.requests] == ["textDocument/prepareRename"]


def test_rename_request_payload_shape() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, _statusbar, _popovers = _build(
        server=server, real_buffer=True,
        cursor=(7, 3), popover_commit_text="new_name",
    )
    # Override default uri-extraction by triggering directly
    ctrl.trigger(server, "file:///x.py", lambda: None)
    assert len(server.requests) == 1
    method, params = server.requests[0]
    assert method == "textDocument/rename"
    assert params["textDocument"] == {"uri": "file:///x.py"}
    assert params["position"] == {"line": 7, "character": 3}
    assert params["newName"] == "new_name"


def test_unchanged_newName_still_sends_rename_request() -> None:
    # Spec: "New name == placeholder → send the request anyway; server
    # typically returns null/empty; statusbar 'LSP: no changes'." This
    # pins the "send anyway" behaviour against a future regression that
    # might add an `if new_name == placeholder: return` guard.
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, _popovers = _build(
        server=server, popover_commit_text="ServerSaidThis",
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "range": {"start": {"line": 0, "character": 0},
                  "end":   {"line": 0, "character": 3}},
        "placeholder": "ServerSaidThis",
    }})
    # Both prepareRename AND rename were sent — the controller does not
    # short-circuit when the user submits the same text.
    assert [r[0] for r in server.requests] == [
        "textDocument/prepareRename", "textDocument/rename",
    ]
    assert server.requests[1][1]["newName"] == "ServerSaidThis"


def test_rename_server_error_pushes_failure_message() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
    )
    _trigger(ctrl, server)
    # rename was sent — fire its callback with an error
    server.callbacks[0]({"error": {"code": 1, "message": "nope"}})
    assert any(
        "rename failed" in m.lower() for _ctx, m in statusbar.messages
    )


def test_rename_null_result_pushes_no_changes() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": None})
    assert any("no changes" in m.lower() for _ctx, m in statusbar.messages)


def test_rename_empty_documentChanges_pushes_no_changes() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {"documentChanges": []}})
    # All-URIs-collected returns []; the controller short-circuits to "no changes".
    assert any("no changes" in m.lower() for _ctx, m in statusbar.messages)


# --- WorkspaceEdit dispatch + load-settle ---------------------------


def test_all_open_files_apply_immediately(monkeypatch: Any) -> None:
    captured_apply_args: list[tuple[Any, dict[str, Any]]] = []

    def fake_apply(edit: Any, *, buffer_for_uri: Any) -> tuple[list[str], list[str]]:
        captured_apply_args.append((buffer_for_uri, edit))
        return (["file:///a.py", "file:///b.py"], [])

    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit", fake_apply,
    )

    open_buffers = {"file:///a.py": MagicMock(), "file:///b.py": MagicMock()}
    load_calls: list[str] = []

    def load_uri(_w: Any, uri: str, on_done: Any) -> None:
        load_calls.append(uri)
        on_done(True)

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=load_uri,
        buffer_for_uri=lambda _w, u: open_buffers.get(u),
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": []},
            {"textDocument": {"uri": "file:///b.py"}, "edits": []},
        ],
    }})
    # No load was needed — all URIs were already open.
    assert load_calls == []
    assert len(captured_apply_args) == 1
    assert any(
        "renamed 2 file" in m.lower() for _ctx, m in statusbar.messages
    )


def test_closed_files_are_loaded_then_apply_runs(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (
            [u for u in ["file:///a.py", "file:///b.py", "file:///c.py"]
             if buffer_for_uri(u) is not None],
            [u for u in ["file:///a.py", "file:///b.py", "file:///c.py"]
             if buffer_for_uri(u) is None],
        ),
    )

    # a.py open, b.py and c.py closed (load_uri makes them open).
    state = {"file:///a.py": MagicMock()}
    load_calls: list[str] = []

    def load_uri(_w: Any, uri: str, on_done: Any) -> None:
        load_calls.append(uri)
        state[uri] = MagicMock()  # "loaded" — buffer_for_uri now finds it
        on_done(True)

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=load_uri,
        buffer_for_uri=lambda _w, u: state.get(u),
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": []},
            {"textDocument": {"uri": "file:///b.py"}, "edits": []},
            {"textDocument": {"uri": "file:///c.py"}, "edits": []},
        ],
    }})
    assert sorted(load_calls) == ["file:///b.py", "file:///c.py"]
    assert any(
        "renamed 3 file" in m.lower() for _ctx, m in statusbar.messages
    )


def test_partial_load_failure_reports_in_summary(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (
            [u for u in ["file:///a.py", "file:///b.py", "file:///c.py"]
             if buffer_for_uri(u) is not None],
            [u for u in ["file:///a.py", "file:///b.py", "file:///c.py"]
             if buffer_for_uri(u) is None],
        ),
    )

    state = {"file:///a.py": MagicMock()}

    def load_uri(_w: Any, uri: str, on_done: Any) -> None:
        if uri == "file:///c.py":
            on_done(False)  # simulate load failure
        else:
            state[uri] = MagicMock()
            on_done(True)

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=load_uri,
        buffer_for_uri=lambda _w, u: state.get(u),
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": []},
            {"textDocument": {"uri": "file:///b.py"}, "edits": []},
            {"textDocument": {"uri": "file:///c.py"}, "edits": []},
        ],
    }})
    assert any(
        "renamed 2 file" in m.lower() and "1 failed" in m.lower()
        for _ctx, m in statusbar.messages
    )


def test_changes_map_fallback_collected_correctly(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (["file:///a.py"], []),
    )

    state = {"file:///a.py": MagicMock()}

    def load_uri(_w: Any, uri: str, on_done: Any) -> None:
        state[uri] = MagicMock()
        on_done(True)

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=load_uri,
        buffer_for_uri=lambda _w, u: state.get(u),
    )
    _trigger(ctrl, server)
    # Server returns the older `changes` map shape, no documentChanges.
    server.callbacks[0]({"result": {
        "changes": {
            "file:///a.py": [{"range": {
                "start": {"line": 0, "character": 0},
                "end":   {"line": 0, "character": 3},
            }, "newText": "X"}],
        },
    }})
    assert any(
        "renamed 1 file" in m.lower() for _ctx, m in statusbar.messages
    )


def test_window_closed_during_load_does_not_crash(monkeypatch: Any) -> None:
    # Spec: "If the controller's window is closed while loads are
    # pending, the callback no-ops." Simulate it by having the buffer
    # lookup raise RuntimeError (PyGObject's "wrapper for X has been
    # destroyed" behavior) on the apply call.
    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (_ for _ in ()).throw(
            RuntimeError("wrapper destroyed"),
        ),
    )

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=lambda _w, _u, on_done: on_done(True),
        buffer_for_uri=lambda _w, _u: MagicMock(),
    )
    _trigger(ctrl, server)
    # If the guard is missing, this raises RuntimeError unhandled and
    # the test fails. With the guard, we get a clean no-op + log line.
    server.callbacks[0]({"result": {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": []},
        ],
    }})
    # No statusbar message because the apply itself raised.
    assert not any(
        "renamed" in m.lower() for _ctx, m in statusbar.messages
    )
