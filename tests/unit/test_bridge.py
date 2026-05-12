"""Tests for DocumentBridge — per-buffer document sync logic.

The bridge depends on a `LanguageServer` (we use a fake) and on a clock
(we use a manual clock so debouncing is deterministic).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gedit_lsp.bridge import DocumentBridge, SyncKind


class FakeServer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.state = "READY"
        self._diag_listeners: list[Callable[[dict[str, Any]], None]] = []

    def send_notification(self, method: str, params: dict[str, Any]) -> None:
        self.sent.append({"method": method, "params": params})

    def add_diagnostics_listener(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        self._diag_listeners.append(callback)

        def dispose() -> None:
            if callback in self._diag_listeners:
                self._diag_listeners.remove(callback)

        return dispose

    def publish_diagnostics(self, params: dict[str, Any]) -> None:
        """Test helper: fan out to registered listeners."""
        for cb in list(self._diag_listeners):
            cb(params)


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


def test_revert_to_disk_sends_full_text_didchange_and_bumps_version() -> None:
    """The dirty-close cache workaround: a single didChange with full-text
    contentChange replacing any pending events. Mutation invariant: change
    `bridge._version += 1` to `+= 0` and the version-monotonic assertion
    breaks; remove the contentChanges payload and the shape assertion breaks.
    """
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///lib.py", language_id="python", text="renamed_content",
        server=server, clock=clock, debounce_ms=150,
        sync_kind=SyncKind.INCREMENTAL,
    )
    bridge.attach()
    initial_version = 1  # didOpen used v1
    # Stage a pending event that would otherwise fire on debounce
    bridge.on_change_event(_insert_event(0, 0, "extra"))
    server.sent.clear()

    bridge.revert_to_disk("disk_content")

    assert len(server.sent) == 1
    msg = server.sent[0]
    assert msg["method"] == "textDocument/didChange"
    assert msg["params"]["textDocument"]["version"] == initial_version + 1
    assert msg["params"]["contentChanges"] == [{"text": "disk_content"}]
    # Pending event was discarded (advancing clock must NOT fire another change)
    clock.advance(1000)
    assert len(server.sent) == 1


def test_revert_to_disk_then_detach_sends_didchange_then_didclose() -> None:
    """The full close-with-revert sequence: didChange(disk), then didClose."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///lib.py", language_id="python", text="renamed",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    server.sent.clear()
    bridge.revert_to_disk("on_disk")
    bridge.detach()
    methods = [s["method"] for s in server.sent]
    assert methods == ["textDocument/didChange", "textDocument/didClose"]


def test_latest_diagnostics_for_returns_empty_when_unseen() -> None:
    """No publishDiagnostics yet for this URI → empty list (not None)."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    assert bridge.latest_diagnostics_for("file:///x.py") == []
    assert bridge.latest_diagnostics_for("file:///never-seen.py") == []


def test_latest_diagnostics_for_records_recent_publish() -> None:
    """Bridge subscribes on attach(); the most recent publishDiagnostics for
    each URI is retained and returned by latest_diagnostics_for."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    diag = {
        "range": {"start": {"line": 0, "character": 0},
                  "end":   {"line": 0, "character": 5}},
        "severity": 1, "message": "boom",
    }
    server.publish_diagnostics({"uri": "file:///x.py", "diagnostics": [diag]})
    assert bridge.latest_diagnostics_for("file:///x.py") == [diag]


def test_latest_diagnostics_for_tracks_multiple_uris_independently() -> None:
    """Cross-file diagnostics (e.g. pylsp project-wide) populate per-URI."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///a.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    d_a = {"range": {"start": {"line": 1, "character": 0},
                     "end":   {"line": 1, "character": 1}},
           "message": "a"}
    d_b = {"range": {"start": {"line": 2, "character": 0},
                     "end":   {"line": 2, "character": 1}},
           "message": "b"}
    server.publish_diagnostics({"uri": "file:///a.py", "diagnostics": [d_a]})
    server.publish_diagnostics({"uri": "file:///b.py", "diagnostics": [d_b]})
    assert bridge.latest_diagnostics_for("file:///a.py") == [d_a]
    assert bridge.latest_diagnostics_for("file:///b.py") == [d_b]


def test_latest_diagnostics_for_replaces_on_republish() -> None:
    """publishDiagnostics is authoritative; new payload replaces the old."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    first = {"range": {"start": {"line": 0, "character": 0},
                       "end":   {"line": 0, "character": 1}},
             "message": "first"}
    second = {"range": {"start": {"line": 5, "character": 0},
                        "end":   {"line": 5, "character": 1}},
              "message": "second"}
    server.publish_diagnostics({"uri": "file:///x.py", "diagnostics": [first]})
    server.publish_diagnostics({"uri": "file:///x.py", "diagnostics": [second]})
    # Empty list also replaces (server cleared the diagnostics).
    assert bridge.latest_diagnostics_for("file:///x.py") == [second]
    server.publish_diagnostics({"uri": "file:///x.py", "diagnostics": []})
    assert bridge.latest_diagnostics_for("file:///x.py") == []


def test_diagnostics_listener_disposed_on_detach() -> None:
    """Bridge unsubscribes on detach() — no late updates after close."""
    server = FakeServer()
    clock = ManualClock()
    bridge = DocumentBridge(
        uri="file:///x.py", language_id="python", text="",
        server=server, clock=clock, debounce_ms=150,
    )
    bridge.attach()
    assert len(server._diag_listeners) == 1
    bridge.detach()
    assert server._diag_listeners == []


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
