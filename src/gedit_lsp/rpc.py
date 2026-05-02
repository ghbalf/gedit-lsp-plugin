"""JSON-RPC framing for LSP.

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

The async transport (`RpcClient`) layers on top of these in a later task.
"""
from __future__ import annotations


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
