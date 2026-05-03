"""Tests for LanguageServer state transitions.

The tests here use a fake transport that records outgoing messages and lets
the test push fake responses synchronously. Real subprocess and async I/O
are exercised by integration tests later.
"""
from __future__ import annotations

from typing import Any

import pytest

from gedit_lsp.server import (
    LanguageServer,
    ServerState,
)


class FakeTransport:
    """In-memory transport for state-machine tests."""

    def __init__(self) -> None:
        self.outgoing: list[dict[str, Any]] = []
        self.started = False
        self.killed = False
        self._on_response: dict[int, Any] = {}
        self._on_notification: dict[str, Any] = {}

    def start(self) -> None:
        self.started = True

    def kill(self) -> None:
        self.killed = True

    def send(self, msg: dict[str, Any]) -> None:
        self.outgoing.append(msg)

    def on_response(self, request_id: int, callback: Any) -> None:
        self._on_response[request_id] = callback

    def on_notification(self, method: str, callback: Any) -> None:
        self._on_notification[method] = callback

    def fake_response(self, request_id: int, result: Any = None, error: Any = None) -> None:
        cb = self._on_response.pop(request_id)
        cb({"id": request_id, "result": result, "error": error})

    def fake_notification(self, method: str, params: Any) -> None:
        cb = self._on_notification.get(method)
        if cb:
            cb({"method": method, "params": params})

    def fake_exit(self, code: int = 0) -> None:
        pass  # set by the test via callback wiring


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def server(transport: FakeTransport) -> LanguageServer:
    return LanguageServer(
        language_id="python",
        root_path="/tmp/proj",
        command=["pylsp"],
        initialization_options=None,
        transport_factory=lambda *a, **kw: transport,
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
    )


def test_initial_state_is_not_running(server: LanguageServer) -> None:
    assert server.state == ServerState.NOT_RUNNING


def test_attach_first_buffer_transitions_to_starting(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    assert server.state == ServerState.STARTING
    assert transport.started is True
    assert transport.outgoing[0]["method"] == "initialize"


def test_initialize_response_transitions_to_ready(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    init_id = transport.outgoing[0]["id"]
    transport.fake_response(init_id, result={"capabilities": {}})
    assert server.state == ServerState.READY


def test_initialize_handshake_pushes_settings_via_didChangeConfiguration(
    transport: FakeTransport,
) -> None:
    """pylsp + pylsp-mypy ignore plugin settings in initializationOptions
    until they receive workspace/didChangeConfiguration. The server must
    push the same payload through both paths after initialize succeeds."""
    init_opts = {"pylsp": {"plugins": {"pylsp_mypy": {"enabled": True}}}}
    srv = LanguageServer(
        language_id="python",
        root_path="/tmp/proj",
        command=["pylsp"],
        initialization_options=init_opts,
        transport_factory=lambda *a, **kw: transport,
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
    )
    srv.attach_buffer("file:///tmp/proj/a.py")
    init_id = transport.outgoing[0]["id"]
    transport.fake_response(init_id, result={"capabilities": {}})

    methods = [m["method"] for m in transport.outgoing if "method" in m]
    assert "initialized" in methods
    assert "workspace/didChangeConfiguration" in methods
    # didChange must come AFTER initialized.
    assert methods.index("workspace/didChangeConfiguration") > methods.index("initialized")
    # Same payload as initializationOptions.
    didchange = next(
        m for m in transport.outgoing if m.get("method") == "workspace/didChangeConfiguration"
    )
    assert didchange["params"] == {"settings": init_opts}


def test_initialize_skips_didChangeConfiguration_when_no_settings(
    server: LanguageServer, transport: FakeTransport
) -> None:
    """No initializationOptions → don't push an empty settings notification."""
    server.attach_buffer("file:///tmp/proj/a.py")
    init_id = transport.outgoing[0]["id"]
    transport.fake_response(init_id, result={"capabilities": {}})
    methods = [m["method"] for m in transport.outgoing if "method" in m]
    assert "workspace/didChangeConfiguration" not in methods


def test_last_buffer_detach_transitions_to_idle(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    transport.fake_response(transport.outgoing[0]["id"], result={"capabilities": {}})
    server.detach_buffer("file:///tmp/proj/a.py")
    assert server.state == ServerState.IDLE


def test_attach_during_idle_returns_to_ready(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    transport.fake_response(transport.outgoing[0]["id"], result={"capabilities": {}})
    server.detach_buffer("file:///tmp/proj/a.py")
    assert server.state == ServerState.IDLE
    server.attach_buffer("file:///tmp/proj/b.py")
    assert server.state == ServerState.READY


def test_idle_timer_expires_to_stopping(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    transport.fake_response(transport.outgoing[0]["id"], result={"capabilities": {}})
    server.detach_buffer("file:///tmp/proj/a.py")
    server._fire_idle_timer_for_test()  # synchronous test hook
    assert server.state == ServerState.STOPPING
    # Verify shutdown then exit were sent
    methods = [m.get("method") for m in transport.outgoing]
    assert "shutdown" in methods
    assert "exit" in methods


def test_subprocess_crash_from_ready_clears_state(
    server: LanguageServer, transport: FakeTransport
) -> None:
    server.attach_buffer("file:///tmp/proj/a.py")
    transport.fake_response(transport.outgoing[0]["id"], result={"capabilities": {}})
    server._handle_subprocess_exit_for_test(exit_code=139)
    assert server.state == ServerState.NOT_RUNNING


def test_backoff_schedule_is_advanced_on_each_failure(
    server: LanguageServer, transport: FakeTransport
) -> None:
    # Force three failed starts
    for expected_backoff in [1, 2, 4]:
        server.attach_buffer("file:///tmp/proj/a.py")
        # crash before initialize completes
        server._handle_subprocess_exit_for_test(exit_code=1)
        assert server.state == ServerState.NOT_RUNNING
        assert server.next_restart_delay == expected_backoff


def test_circuit_breaker_trips_after_max_attempts(
    server: LanguageServer, transport: FakeTransport
) -> None:
    for _ in range(3):  # max_restart_attempts=3
        server.attach_buffer("file:///tmp/proj/a.py")
        server._handle_subprocess_exit_for_test(exit_code=1)
    server.attach_buffer("file:///tmp/proj/a.py")
    # Further attempts are refused until reset_circuit_breaker() is called
    assert server.state == ServerState.CIRCUIT_OPEN


def test_reset_circuit_breaker_allows_restart(
    server: LanguageServer, transport: FakeTransport
) -> None:
    for _ in range(3):
        server.attach_buffer("file:///tmp/proj/a.py")
        server._handle_subprocess_exit_for_test(exit_code=1)
    assert server.state in (ServerState.NOT_RUNNING, ServerState.CIRCUIT_OPEN)
    server.reset_circuit_breaker()
    server.attach_buffer("file:///tmp/proj/a.py")
    assert server.state == ServerState.STARTING


def test_diagnostics_listener_disposer_removes_callback(
    server: LanguageServer,
) -> None:
    received: list[dict[str, Any]] = []
    dispose = server.add_diagnostics_listener(received.append)
    server._on_diagnostics({"params": {"uri": "file:///x", "diagnostics": []}})
    assert len(received) == 1
    dispose()
    server._on_diagnostics({"params": {"uri": "file:///x", "diagnostics": []}})
    assert len(received) == 1, "listener fired after dispose"


def test_state_listener_disposer_removes_callback(
    server: LanguageServer,
) -> None:
    received: list[ServerState] = []
    dispose = server.add_state_listener(received.append)
    server.state = ServerState.STARTING
    assert received == [ServerState.STARTING]
    dispose()
    server.state = ServerState.READY
    assert received == [ServerState.STARTING], "listener fired after dispose"


def test_listener_disposer_is_idempotent(server: LanguageServer) -> None:
    """Calling the disposer twice (e.g. once on tab-removed, then again on
    do_deactivate) must not raise."""
    dispose = server.add_diagnostics_listener(lambda _p: None)
    dispose()
    dispose()  # second call is a no-op


def test_disposing_one_listener_leaves_others_intact(
    server: LanguageServer,
) -> None:
    """Two listeners; disposing the first must not affect the second."""
    a: list[dict[str, Any]] = []
    b: list[dict[str, Any]] = []
    dispose_a = server.add_diagnostics_listener(a.append)
    server.add_diagnostics_listener(b.append)
    dispose_a()
    server._on_diagnostics({"params": {"uri": "file:///x", "diagnostics": []}})
    assert a == []
    assert len(b) == 1


def test_recent_stderr_is_empty_initially(server: LanguageServer) -> None:
    assert server.recent_stderr() == []


def test_stderr_buffer_accumulates_lines_and_drops_old(transport: FakeTransport) -> None:
    """The stderr buffer is bounded; oldest lines are dropped."""
    server = LanguageServer(
        language_id="python",
        root_path="/tmp/proj",
        command=["pylsp"],
        initialization_options=None,
        transport_factory=lambda *a, **kw: transport,
        backoff_schedule=[1],
        max_restart_attempts=1,
        stderr_buffer_max_lines=3,
    )
    for line in ("a", "b", "c", "d"):
        server._stderr_buffer.append(line)
    assert server.recent_stderr() == ["b", "c", "d"]


def test_transport_factory_receives_on_stderr_line(transport: FakeTransport) -> None:
    """LanguageServer must wire its stderr-append into the factory call."""
    captured: dict[str, Any] = {}

    def factory(*args: Any, **kwargs: Any) -> FakeTransport:
        captured["kwargs"] = kwargs
        return transport

    server = LanguageServer(
        language_id="python",
        root_path="/tmp/proj",
        command=["pylsp"],
        initialization_options=None,
        transport_factory=factory,
        backoff_schedule=[1],
        max_restart_attempts=1,
    )
    server.attach_buffer("file:///tmp/proj/a.py")
    on_stderr_line = captured["kwargs"].get("on_stderr_line")
    assert on_stderr_line is not None
    on_stderr_line("warning: something happened")
    assert "warning: something happened" in server.recent_stderr()
