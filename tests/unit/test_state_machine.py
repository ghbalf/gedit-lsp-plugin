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
