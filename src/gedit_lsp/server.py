"""LanguageServer — one (lang, root) pair, one subprocess, one state machine.

This module is transport-agnostic. The constructor takes a `transport_factory`
callable which is invoked to construct the actual I/O layer. In production this
is the GLib-async `RpcClient` (Milestone 3); in tests it is a synchronous
fake.
"""
from __future__ import annotations

import enum
import itertools
from collections.abc import Callable
from typing import Any, Protocol

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.rpc import RpcClient


class ServerState(enum.Enum):
    NOT_RUNNING = "not_running"
    STARTING = "starting"
    READY = "ready"
    IDLE = "idle"
    STOPPING = "stopping"
    CIRCUIT_OPEN = "circuit_open"


class Transport(Protocol):
    def start(self) -> None: ...
    def kill(self) -> None: ...
    def send(self, msg: dict[str, Any]) -> None: ...
    def on_response(
        self, request_id: int, callback: Callable[[dict[str, Any]], None]
    ) -> None: ...
    def on_notification(
        self, method: str, callback: Callable[[dict[str, Any]], None]
    ) -> None: ...


def real_transport_factory(
    command: list[str],
    log_prefix: str,
    on_exit: Callable[[int], None],
) -> RpcClient:
    return RpcClient(command=command, log_prefix=log_prefix, on_exit=on_exit)


class LanguageServer:
    def __init__(
        self,
        language_id: str,
        root_path: str,
        command: list[str],
        initialization_options: Any,
        transport_factory: Callable[..., Transport],
        backoff_schedule: list[int],
        max_restart_attempts: int,
        idle_timeout_seconds: int = 300,
    ) -> None:
        self.language_id = language_id
        self.root_path = root_path
        self.command = command
        self.initialization_options = initialization_options
        self._transport_factory = transport_factory
        self._backoff_schedule = backoff_schedule
        self._max_restart_attempts = max_restart_attempts
        self._idle_timeout_seconds = idle_timeout_seconds

        self.state: ServerState = ServerState.NOT_RUNNING
        self._transport: Transport | None = None
        self._attached_uris: set[str] = set()
        self._req_ids = itertools.count(1)
        self._failed_starts = 0
        self._idle_source_id: int | None = None

    @property
    def next_restart_delay(self) -> int:
        # `_failed_starts` is the count of failures so far; the next attempt's
        # wait is schedule[failed_starts - 1], clamped into the schedule.
        idx = max(0, min(self._failed_starts - 1, len(self._backoff_schedule) - 1))
        return self._backoff_schedule[idx]

    def attach_buffer(self, uri: str) -> None:
        if self.state == ServerState.CIRCUIT_OPEN:
            return
        self._attached_uris.add(uri)
        if self.state == ServerState.NOT_RUNNING:
            if self._failed_starts >= self._max_restart_attempts:
                self.state = ServerState.CIRCUIT_OPEN
                return
            self._spawn_and_initialize()
        elif self.state == ServerState.IDLE:
            self._cancel_idle_timer()
            self.state = ServerState.READY

    def detach_buffer(self, uri: str) -> None:
        self._attached_uris.discard(uri)
        if not self._attached_uris and self.state == ServerState.READY:
            self.state = ServerState.IDLE
            self._idle_source_id = GLib.timeout_add_seconds(
                self._idle_timeout_seconds, self._on_idle_timer
            )

    def _on_idle_timer(self) -> bool:
        if self.state == ServerState.IDLE:
            self._begin_shutdown()
        self._idle_source_id = None
        return False  # don't repeat

    def _cancel_idle_timer(self) -> None:
        if self._idle_source_id is not None:
            GLib.source_remove(self._idle_source_id)
            self._idle_source_id = None

    def reset_circuit_breaker(self) -> None:
        self._failed_starts = 0
        if self.state == ServerState.CIRCUIT_OPEN:
            self.state = ServerState.NOT_RUNNING

    def send_notification(self, method: str, params: Any) -> None:
        if self._transport is None:
            return
        self._transport.send(
            {"jsonrpc": "2.0", "method": method, "params": params}
        )

    # --- internal ---

    def _spawn_and_initialize(self) -> None:
        self.state = ServerState.STARTING
        self._transport = self._transport_factory()
        self._transport.start()
        req_id = next(self._req_ids)
        self._transport.on_response(req_id, self._on_initialize_response)
        self._transport.on_notification(
            "textDocument/publishDiagnostics", self._on_diagnostics
        )
        self._transport.send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": self._initialize_params(),
            }
        )

    def _initialize_params(self) -> dict[str, Any]:
        return {
            "processId": None,
            "rootUri": f"file://{self.root_path}",
            "capabilities": {},
            "initializationOptions": self.initialization_options,
        }

    def _on_initialize_response(self, msg: dict[str, Any]) -> None:
        if msg.get("error"):
            self._handle_failed_start()
            return
        # Send `initialized` notification per LSP spec.
        assert self._transport is not None
        self._transport.send(
            {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        )
        self._failed_starts = 0
        self.state = ServerState.READY

    def _on_diagnostics(self, msg: dict[str, Any]) -> None:
        # Routed to controllers via signal in real impl; no-op in state machine
        pass

    def _handle_failed_start(self) -> None:
        self._failed_starts += 1
        self.state = ServerState.NOT_RUNNING

    # --- test hooks (named with `_for_test` to make their purpose obvious) ---

    def _fire_idle_timer_for_test(self) -> None:
        assert self.state == ServerState.IDLE
        self._begin_shutdown()

    def _handle_subprocess_exit_for_test(self, exit_code: int) -> None:
        # Whether crashed during STARTING or after READY/IDLE, treat as a
        # failed run: increment counter and return to NOT_RUNNING. The
        # circuit-open transition happens lazily on the next attach_buffer
        # when failed_starts has reached max_restart_attempts.
        self._failed_starts += 1
        self.state = ServerState.NOT_RUNNING

    def kill_now(self) -> None:
        """Immediate shutdown — used on plugin deactivate / window close."""
        if self.state in (ServerState.READY, ServerState.IDLE):
            self._begin_shutdown()
        elif self._transport is not None:
            self._transport.kill()
            self.state = ServerState.NOT_RUNNING

    def _begin_shutdown(self) -> None:
        self._cancel_idle_timer()
        self.state = ServerState.STOPPING
        assert self._transport is not None
        req_id = next(self._req_ids)
        self._transport.on_response(req_id, lambda _msg: None)
        self._transport.send(
            {"jsonrpc": "2.0", "id": req_id, "method": "shutdown", "params": None}
        )
        self._transport.send({"jsonrpc": "2.0", "method": "exit", "params": None})
        self._transport.kill()
        # State remains STOPPING; production code transitions to NOT_RUNNING
        # in the subprocess-exit handler once the child has actually exited.
