"""Tests for DocumentBridge — per-buffer document sync logic.

The bridge depends on a `LanguageServer` (we use a fake) and on a clock
(we use a manual clock so debouncing is deterministic).
"""
from __future__ import annotations

from typing import Any

from gedit_lsp.bridge import DocumentBridge, SyncKind


class FakeServer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.state = "READY"

    def send_notification(self, method: str, params: dict[str, Any]) -> None:
        self.sent.append({"method": method, "params": params})


class ManualClock:
    def __init__(self) -> None:
        self.now_ms = 0
        self.scheduled: list[tuple[int, Any]] = []

    def schedule_after_ms(self, delay_ms: int, callback: Any) -> Any:
        self.scheduled.append((self.now_ms + delay_ms, callback))
        return len(self.scheduled) - 1

    def cancel(self, handle: Any) -> None:
        self.scheduled = [s for i, s in enumerate(self.scheduled) if i != handle]

    def advance(self, ms: int) -> None:
        self.now_ms += ms
        due = [(t, cb) for (t, cb) in self.scheduled if t <= self.now_ms]
        self.scheduled = [(t, cb) for (t, cb) in self.scheduled if t > self.now_ms]
        for _, cb in due:
            cb()


def test_did_open_sent_on_attach() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py",
        language_id="python",
        text="print(1)",
        server=server,
        clock=clock,
        debounce_ms=150,
    )
    bridge.attach()
    assert server.sent[-1]["method"] == "textDocument/didOpen"
    p = server.sent[-1]["params"]
    assert p["textDocument"]["uri"] == "file:///x.py"
    assert p["textDocument"]["text"] == "print(1)"
    assert p["textDocument"]["version"] == 1


def test_did_change_debounced() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py",
        language_id="python",
        text="print(1)",
        server=server,
        clock=clock,
        debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_changed("print(2)")
    bridge.on_changed("print(3)")
    bridge.on_changed("print(4)")
    # No didChange yet — still inside debounce window
    assert server.sent == []
    clock.advance(150)
    # One didChange sent with the latest text
    assert len(server.sent) == 1
    assert server.sent[0]["method"] == "textDocument/didChange"
    assert server.sent[0]["params"]["contentChanges"][0]["text"] == "print(4)"


def test_did_change_version_monotonic() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    for new in ["b", "c", "d"]:
        bridge.on_changed(new)
        clock.advance(150)
    versions = [s["params"]["textDocument"]["version"] for s in server.sent]
    assert versions == [2, 3, 4]


def test_did_save_sent_immediately() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_saved()
    assert server.sent[0]["method"] == "textDocument/didSave"


def test_did_close_sent_on_detach() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.detach()
    assert server.sent[0]["method"] == "textDocument/didClose"


def test_pending_change_flushed_on_save() -> None:
    """Saving while a debounced change is pending must flush the change first."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_changed("ab")
    bridge.on_saved()
    methods = [s["method"] for s in server.sent]
    assert methods == ["textDocument/didChange", "textDocument/didSave"]


# --- Incremental sync (TextDocumentSyncKind.Incremental) -----------------

def _insert_event(line: int, ch: int, text: str) -> dict[str, Any]:
    return {
        "range": {"start": {"line": line, "character": ch},
                  "end":   {"line": line, "character": ch}},
        "text": text,
    }


def test_incremental_sends_event_list_not_full_text() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="ab",
        server=server, clock=clock, debounce_ms=150,
        sync_kind=SyncKind.INCREMENTAL,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_change_event(_insert_event(0, 2, "c"))
    bridge.refresh_text("abc")
    clock.advance(150)
    assert len(server.sent) == 1
    p = server.sent[0]["params"]
    assert p["contentChanges"] == [_insert_event(0, 2, "c")]
    assert p["textDocument"]["version"] == 2


def test_incremental_coalesces_events_within_debounce() -> None:
    """Multiple events inside the debounce window batch into one didChange,
    preserving event order — the server applies them sequentially."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
        sync_kind=SyncKind.INCREMENTAL,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_change_event(_insert_event(0, 0, "a"))
    bridge.on_change_event(_insert_event(0, 1, "b"))
    bridge.on_change_event(_insert_event(0, 2, "c"))
    bridge.refresh_text("abc")
    clock.advance(150)
    assert len(server.sent) == 1
    changes = server.sent[0]["params"]["contentChanges"]
    assert [c["text"] for c in changes] == ["a", "b", "c"]


def test_incremental_clears_buffer_after_flush() -> None:
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
        sync_kind=SyncKind.INCREMENTAL,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_change_event(_insert_event(0, 0, "a"))
    clock.advance(150)
    bridge.on_change_event(_insert_event(0, 1, "b"))
    clock.advance(150)
    assert len(server.sent) == 2
    assert server.sent[0]["params"]["contentChanges"] == [_insert_event(0, 0, "a")]
    assert server.sent[1]["params"]["contentChanges"] == [_insert_event(0, 1, "b")]


def test_incremental_flush_pending_change_sends_synchronously() -> None:
    """Edit-triggered features (signatureHelp on `(`) must see the events
    flushed before they fire their request."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
        sync_kind=SyncKind.INCREMENTAL,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_change_event(_insert_event(0, 0, "("))
    bridge.flush_pending_change()
    assert len(server.sent) == 1
    assert server.sent[0]["method"] == "textDocument/didChange"
    assert server.sent[0]["params"]["contentChanges"] == [_insert_event(0, 0, "(")]


def test_incremental_falls_back_to_full_text_when_no_events() -> None:
    """Defensive: if a client uses on_changed (full text) on an Incremental
    bridge — e.g. legacy code paths or the future Full-sync fallback —
    the bridge must still send something the server can apply, not crash.
    Sends a full-text content change, since that's what's available."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="a",
        server=server, clock=clock, debounce_ms=150,
        sync_kind=SyncKind.INCREMENTAL,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_changed("ab")
    clock.advance(150)
    assert len(server.sent) == 1
    assert server.sent[0]["params"]["contentChanges"] == [{"text": "ab"}]


def test_none_sync_kind_skips_didchange() -> None:
    """A server that advertises textDocumentSync.change == None still gets
    didOpen/didSave/didClose (governed by openClose), but didChange is suppressed."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
        sync_kind=SyncKind.NONE,
    )
    bridge.attach()
    server.sent.clear()
    bridge.on_change_event(_insert_event(0, 0, "x"))
    clock.advance(150)
    bridge.on_changed("xy")
    clock.advance(150)
    assert [s["method"] for s in server.sent] == []
