"""JSON-RPC framing and async transport for LSP.

Frame format (mandated by the LSP spec):

    Content-Length: <N>\r\n
    [other headers]\r\n
    \r\n
    <N bytes of UTF-8 JSON body>

Headers other than `Content-Length` are ignored. Line endings must be CRLF;
LF-only is rejected as malformed.

This module exposes:
    - encode_frame(body) -> bytes
    - FrameDecoder().feed(chunk) -> list[bytes]
    - MalformedFrameError
    - RpcClient — async JSON-RPC 2.0 client over a Gio.Subprocess
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from gedit_lsp.log import write_traffic


class MalformedFrameError(Exception):
    """The byte stream is not a valid JSON-RPC LSP frame."""


def encode_frame(body: bytes) -> bytes:
    """Wrap a raw JSON body in the `Content-Length` framed envelope."""
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class FrameDecoder:
    """Stateful decoder that turns a byte stream into discrete JSON bodies.

    Feed any sized chunk; receive a list (possibly empty) of complete bodies.
    Partial frames are buffered internally until enough bytes arrive.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._expected_length: int | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer.extend(chunk)
        out: list[bytes] = []
        while True:
            if self._expected_length is None:
                # Looking for the header block.
                sep = self._buffer.find(b"\r\n\r\n")
                if sep < 0:
                    if b"\n\n" in self._buffer and b"\r\n\r\n" not in self._buffer:
                        # LF-only sequences are illegal in LSP framing.
                        raise MalformedFrameError("LF-only line endings in headers")
                    return out
                header_block = bytes(self._buffer[:sep])
                del self._buffer[: sep + 4]
                self._expected_length = self._parse_content_length(header_block)
            if self._expected_length is not None:
                if len(self._buffer) < self._expected_length:
                    return out
                body = bytes(self._buffer[: self._expected_length])
                del self._buffer[: self._expected_length]
                self._expected_length = None
                out.append(body)

    @staticmethod
    def _parse_content_length(header_block: bytes) -> int:
        for raw_line in header_block.split(b"\r\n"):
            if not raw_line:
                continue
            try:
                name, _, value = raw_line.partition(b":")
            except ValueError as exc:
                raise MalformedFrameError(f"bad header line: {raw_line!r}") from exc
            if name.strip().lower() == b"content-length":
                try:
                    return int(value.strip())
                except ValueError as exc:
                    raise MalformedFrameError(
                        f"non-integer Content-Length: {value!r}"
                    ) from exc
        raise MalformedFrameError("missing Content-Length header")


class RpcClient:
    """Async JSON-RPC 2.0 client over a GIO subprocess.

    Reads via `Gio.DataInputStream.read_line_async` for headers,
    `Gio.InputStream.read_bytes_async` for bodies. Writes are FIFO-
    serialized through a single `write_bytes_async` chain.
    """

    def __init__(
        self,
        command: list[str],
        log_prefix: str,
        on_request: Callable[[dict[str, Any]], None] | None = None,
        on_notification_default: Callable[[dict[str, Any]], None] | None = None,
        on_exit: Callable[[int], None] | None = None,
        on_stderr_line: Callable[[str], None] | None = None,
    ) -> None:
        self._command = command
        self._log_prefix = log_prefix
        self._on_request = on_request
        self._on_notification_default = on_notification_default
        self._on_exit = on_exit
        self._on_stderr_line = on_stderr_line

        self._proc: Gio.Subprocess | None = None
        self._stdout: Gio.DataInputStream | None = None
        self._stderr: Gio.DataInputStream | None = None
        self._stdin: Gio.OutputStream | None = None
        self._decoder = FrameDecoder()
        self._response_callbacks: dict[int, Callable[[dict[str, Any]], None]] = {}
        self._notification_callbacks: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._write_queue: list[bytes] = []
        self._writing = False

    def start(self) -> None:
        flags = (
            Gio.SubprocessFlags.STDIN_PIPE
            | Gio.SubprocessFlags.STDOUT_PIPE
            | Gio.SubprocessFlags.STDERR_PIPE
        )
        self._proc = Gio.Subprocess.new(self._command, flags)
        self._stdin = self._proc.get_stdin_pipe()
        stdout_pipe = self._proc.get_stdout_pipe()
        assert stdout_pipe is not None  # STDOUT_PIPE flag was set
        self._stdout = Gio.DataInputStream.new(stdout_pipe)
        self._stdout.set_newline_type(Gio.DataStreamNewlineType.CR_LF)
        stderr_pipe = self._proc.get_stderr_pipe()
        assert stderr_pipe is not None  # STDERR_PIPE flag was set
        self._stderr = Gio.DataInputStream.new(stderr_pipe)
        self._proc.wait_check_async(None, self._on_subprocess_exit)
        self._read_header_line()
        self._read_stderr_line()

    def kill(self) -> None:
        if self._proc is not None:
            self._proc.force_exit()

    def send(self, msg: dict[str, Any]) -> None:
        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        write_traffic(">>>", self._log_prefix, time.monotonic() * 1000.0, body)
        framed = encode_frame(body)
        self._write_queue.append(framed)
        self._pump_writes()

    def on_response(
        self, request_id: int, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        self._response_callbacks[request_id] = callback

    def on_notification(
        self, method: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        self._notification_callbacks[method] = callback

    # --- internals ---

    def _pump_writes(self) -> None:
        if self._writing or not self._write_queue or self._stdin is None:
            return
        self._writing = True
        chunk = self._write_queue.pop(0)
        self._stdin.write_bytes_async(
            GLib.Bytes.new(chunk), GLib.PRIORITY_DEFAULT, None, self._on_write_done
        )

    def _on_write_done(self, source: Any, res: Any) -> None:
        try:
            source.write_bytes_finish(res)
        except GLib.Error as exc:
            logging.getLogger("gedit_lsp").warning("write failed: %s", exc.message)
        self._writing = False
        self._pump_writes()

    def _read_header_line(self) -> None:
        assert self._stdout is not None
        self._stdout.read_line_async(
            GLib.PRIORITY_DEFAULT, None, self._on_header_line
        )

    def _on_header_line(self, source: Any, res: Any) -> None:
        try:
            line, _length = source.read_line_finish_utf8(res)
        except GLib.Error:
            return
        if line is None:
            return
        chunk = (line + "\r\n").encode("ascii")
        msgs = self._decoder.feed(chunk)
        if msgs:
            for body in msgs:
                self._dispatch(body)
        # Read body if header block completed
        if self._decoder._expected_length is not None:  # noqa: SLF001
            remaining = self._decoder._expected_length - len(self._decoder._buffer)  # noqa: SLF001
            self._read_body(remaining)
        else:
            self._read_header_line()

    def _read_body(self, remaining: int) -> None:
        assert self._stdout is not None
        self._stdout.read_bytes_async(
            remaining, GLib.PRIORITY_DEFAULT, None, self._on_body
        )

    def _on_body(self, source: Any, res: Any) -> None:
        try:
            chunk = source.read_bytes_finish(res).get_data() or b""
        except GLib.Error:
            return
        msgs = self._decoder.feed(chunk)
        for body in msgs:
            self._dispatch(body)
        self._read_header_line()

    def _dispatch(self, body: bytes) -> None:
        write_traffic("<<<", self._log_prefix, time.monotonic() * 1000.0, body)
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            logging.getLogger("gedit_lsp").warning("malformed JSON from server")
            return
        if "id" in msg and "method" not in msg:
            cb = self._response_callbacks.pop(msg["id"], None)
            if cb is not None:
                cb(msg)
        elif "method" in msg and "id" not in msg:
            cb_n = self._notification_callbacks.get(msg["method"])
            if cb_n is not None:
                cb_n(msg)
            elif self._on_notification_default is not None:
                self._on_notification_default(msg)
        elif "method" in msg and "id" in msg:
            if self._on_request is not None:
                self._on_request(msg)

    def _read_stderr_line(self) -> None:
        if self._stderr is None:
            return
        self._stderr.read_line_async(
            GLib.PRIORITY_DEFAULT, None, self._on_stderr_line_read
        )

    def _on_stderr_line_read(self, source: Any, res: Any) -> None:
        try:
            line, _length = source.read_line_finish_utf8(res)
        except GLib.Error:
            return
        if line is None:
            return  # EOF; subprocess exit handler will fire
        if self._on_stderr_line is not None:
            self._on_stderr_line(line)
        self._read_stderr_line()

    def _on_subprocess_exit(self, source: Any, res: Any) -> None:
        code = 0
        try:
            if self._proc is not None:
                self._proc.wait_check_finish(res)
        except GLib.Error as exc:
            code = exc.code or 1
        if self._on_exit is not None:
            self._on_exit(code)
