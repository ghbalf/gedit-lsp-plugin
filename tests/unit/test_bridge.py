"""Tests for DocumentBridge — per-buffer document sync logic.

The bridge depends on a `LanguageServer` (we use a fake) and on a clock
(we use a manual clock so debouncing is deterministic).
"""
from __future__ import annotations

from typing import Any

from gedit_lsp.bridge import DocumentBridge


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
