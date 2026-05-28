"""LanguageServer — one (lang, root) pair, one subprocess, one state machine.

This module is transport-agnostic. The constructor takes a `transport_factory`
callable which is invoked to construct the actual I/O layer. In production this
is the GLib-async `RpcClient` (Milestone 3); in tests it is a synchronous
fake.
"""
from __future__ import annotations

import contextlib
import copy
import enum
import itertools
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.progress import ProgressTracker
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
    on_stderr_line: Callable[[str], None] | None = None,
    cwd: str | None = None,
    on_request: Callable[[dict[str, Any]], None] | None = None,
) -> RpcClient:
    return RpcClient(
        command=command,
        log_prefix=log_prefix,
        on_exit=on_exit,
        on_stderr_line=on_stderr_line,
        cwd=cwd,
        on_request=on_request,
    )


def _merge_capabilities(server: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge `overrides` on top of `server` capabilities, returning a fresh dict.

    Dicts are recursively merged; non-dict values (bools, lists, scalars) are
    replaced wholesale. Lists are *replaced*, not concatenated — overriding
    `triggerCharacters: ["."]` narrows the set rather than appending. The
    returned dict shares no references with either input; callers may mutate
    it freely.
    """
    out: dict[str, Any] = copy.deepcopy(server)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_capabilities(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


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
        stderr_buffer_max_lines: int = 1000,
        server_capability_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.language_id = language_id
        self.root_path = root_path
        self.command = command
        self.initialization_options = initialization_options
        self._transport_factory = transport_factory
        self._backoff_schedule = backoff_schedule
        self._max_restart_attempts = max_restart_attempts
        self._idle_timeout_seconds = idle_timeout_seconds
        self._capability_overrides: dict[str, Any] = copy.deepcopy(server_capability_overrides or {})
        self._capabilities: dict[str, Any] | None = None  # set on initialize response

        self._state: ServerState = ServerState.NOT_RUNNING
        self._transport: Transport | None = None
        self._attached_uris: set[str] = set()
        self._req_ids = itertools.count(1)
        self._failed_starts = 0
        self._idle_source_id: int | None = None
        self._diagnostics_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._state_listeners: list[Callable[[ServerState], None]] = []
        self._progress = ProgressTracker()
        self._progress_listeners: list[Callable[[], None]] = []
        self._stderr_buffer: deque[str] = deque(maxlen=stderr_buffer_max_lines)

    @property
    def state(self) -> ServerState:
        return self._state

    @state.setter
    def state(self, value: ServerState) -> None:
        self._state = value
        for cb in self._state_listeners:
            cb(value)

    def add_state_listener(
        self, callback: Callable[[ServerState], None]
    ) -> Callable[[], None]:
        """Register a state listener. Returns a disposer; call it to remove
        the listener. Calling the disposer more than once is a no-op."""
        self._state_listeners.append(callback)

        def _dispose() -> None:
            with contextlib.suppress(ValueError):
                self._state_listeners.remove(callback)

        return _dispose

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

    def add_diagnostics_listener(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Register a diagnostics listener. Returns a disposer; call it to
        remove the listener. Calling the disposer more than once is a
        no-op. Important for closures that capture per-document state
        (TextBuffer, panel rows) — without disposal they leak past tab
        close and may fire for a buffer that's already gone."""
        self._diagnostics_listeners.append(callback)

        def _dispose() -> None:
            with contextlib.suppress(ValueError):
                self._diagnostics_listeners.remove(callback)

        return _dispose

    def add_progress_listener(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a progress listener fired whenever active progress
        changes. Returns a disposer; call it to remove the listener
        (calling more than once is a no-op). Same cleanup discipline as
        the diagnostics/state listeners — dispose on tab-removed/deactivate
        so closures don't outlive their buffer."""
        self._progress_listeners.append(callback)

        def _dispose() -> None:
            with contextlib.suppress(ValueError):
                self._progress_listeners.remove(callback)

        return _dispose

    def active_progress_fragment(self) -> str | None:
        """The statusbar fragment for the newest active work-done token,
        or None when no progress is in flight."""
        return self._progress.active_fragment()

    def _on_progress(self, msg: dict[str, Any]) -> None:
        if self._progress.handle(msg.get("params", {})):
            for cb in self._progress_listeners:
                cb()

    def send_notification(self, method: str, params: Any) -> None:
        if self._transport is None:
            return
        self._transport.send(
            {"jsonrpc": "2.0", "method": method, "params": params}
        )

    def _send_response(self, request_id: Any, result: Any) -> None:
        if self._transport is None:
            return
        self._transport.send(
            {"jsonrpc": "2.0", "id": request_id, "result": result}
        )

    def _send_error_response(
        self, request_id: Any, code: int, message: str
    ) -> None:
        if self._transport is None:
            return
        self._transport.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    def _on_server_request(self, msg: dict[str, Any]) -> None:
        """Handle a server→client request. We only invite
        `window/workDoneProgress/create` (via the advertised
        `window.workDoneProgress` capability); ack it with `null`. Any other
        request gets a JSON-RPC `method not found` error so a spec-strict
        server doesn't stall waiting for a response."""
        request_id = msg.get("id")
        if request_id is None:
            return
        if msg.get("method") == "window/workDoneProgress/create":
            self._send_response(request_id, None)
        else:
            # We don't implement dynamic capability registration
            # (client/registerCapability) or workspace/configuration, so any
            # other server->client request gets a spec-correct MethodNotFound
            # rather than a faked success (which would make the server believe
            # a capability is active that we never honor). Our minimal
            # advertised capabilities mean a well-behaved server won't send
            # these; proper dynamic-registration handling will arrive with
            # workspace/didChangeWatchedFiles (a later v0.4.0 item).
            self._send_error_response(
                request_id, -32601, f"method not found: {msg.get('method')}"
            )

    def _send_request(
        self,
        method: str,
        params: Any,
        callback: Callable[[dict[str, Any]], None],
    ) -> int:
        """Send a request, register the callback, return the request id."""
        if self._transport is None:
            return -1
        req_id = next(self._req_ids)
        self._transport.on_response(req_id, callback)
        self._transport.send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        return req_id

    def recent_stderr(self) -> list[str]:
        """Return a snapshot of buffered stderr lines (oldest first)."""
        return list(self._stderr_buffer)

    def capability(self, key: str) -> Any:
        """Return the merged-with-overrides capability value for `key`, or None.

        Returns None before the initialize response arrives. After it arrives,
        returns a deep copy of the server's reported value (with
        `serverCapabilityOverrides` merged on top), so callers may inspect or
        mutate the result without affecting future calls.
        """
        if self._capabilities is None:
            return None
        return copy.deepcopy(self._capabilities.get(key))

    def _apply_initialize_capabilities(self, server_caps: dict[str, Any]) -> None:
        self._capabilities = _merge_capabilities(server_caps, self._capability_overrides)

    def cancel_request(self, request_id: int) -> None:
        if self._transport is None:
            return
        self._transport.send(
            {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": request_id}}
        )

    # --- internal ---

    def _spawn_and_initialize(self) -> None:
        self._progress = ProgressTracker()
        self.state = ServerState.STARTING
        log_prefix = f"[{self.language_id}:{Path(self.root_path).name}]"
        self._transport = self._transport_factory(
            self.command,
            log_prefix,
            self._handle_subprocess_exit,
            on_stderr_line=self._stderr_buffer.append,
            cwd=self.root_path,
            on_request=self._on_server_request,
        )
        self._transport.start()
        req_id = next(self._req_ids)
        self._transport.on_response(req_id, self._on_initialize_response)
        self._transport.on_notification(
            "textDocument/publishDiagnostics", self._on_diagnostics
        )
        self._transport.on_notification("$/progress", self._on_progress)
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
        result = msg.get("result") or {}
        self._apply_initialize_capabilities(result.get("capabilities") or {})
        # Send `initialized` notification per LSP spec.
        assert self._transport is not None
        self._transport.send(
            {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        )
        # Some servers (notably pylsp + pylsp-mypy) ignore plugin settings
        # provided in `initializationOptions` and only consult them after a
        # `workspace/didChangeConfiguration` notification. Push the same
        # payload through both paths so plugin-style settings activate.
        if self.initialization_options:
            self._transport.send(
                {
                    "jsonrpc": "2.0",
                    "method": "workspace/didChangeConfiguration",
                    "params": {"settings": self.initialization_options},
                }
            )
        self._failed_starts = 0
        self.state = ServerState.READY

    def _on_diagnostics(self, msg: dict[str, Any]) -> None:
        params = msg.get("params", {})
        for cb in self._diagnostics_listeners:
            cb(params)

    def _handle_failed_start(self) -> None:
        self._failed_starts += 1
        self.state = ServerState.NOT_RUNNING

    def _handle_subprocess_exit(self, exit_code: int) -> None:
        """Production callback wired into RpcClient.on_exit."""
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
