"""Tests for the JSON-RPC framing helpers.

The transport itself (real GIO async I/O) is exercised in integration tests.
This file pins down the pure framing helpers: encode/decode of
`Content-Length: N\r\n\r\n<body>` messages.
"""
import pytest

from gedit_lsp.rpc import (
    FrameDecoder,
    MalformedFrameError,
    encode_frame,
)


def test_encode_simple_message() -> None:
    body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
    framed = encode_frame(body)
    assert framed == b"Content-Length: 40\r\n\r\n" + body


def test_encode_utf8_multibyte_body() -> None:
    body = '{"v":"héllo"}'.encode("utf-8")
    framed = encode_frame(body)
    # Header counts BYTES, not chars
    expected_header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    assert framed == expected_header + body


def test_decode_one_message() -> None:
    body = b'{"jsonrpc":"2.0","id":1}'
    blob = b"Content-Length: 24\r\n\r\n" + body
    dec = FrameDecoder()
    msgs = dec.feed(blob)
    assert msgs == [body]


def test_decode_multiple_messages_in_one_chunk() -> None:
    b1 = b'{"a":1}'
    b2 = b'{"b":2}'
    blob = (
        b"Content-Length: 7\r\n\r\n" + b1 +
        b"Content-Length: 7\r\n\r\n" + b2
    )
    dec = FrameDecoder()
    assert dec.feed(blob) == [b1, b2]


def test_decode_split_header() -> None:
    body = b'{"a":1}'
    dec = FrameDecoder()
    assert dec.feed(b"Content-Length: ") == []
    assert dec.feed(b"7\r\n\r\n") == []
    assert dec.feed(body) == [body]


def test_decode_split_body() -> None:
    body = b'{"a":1}'
    dec = FrameDecoder()
    assert dec.feed(b"Content-Length: 7\r\n\r\n" + body[:3]) == []
    assert dec.feed(body[3:]) == [body]


def test_decode_extra_headers_are_ignored() -> None:
    body = b'{"a":1}'
    blob = b"Content-Length: 7\r\nContent-Type: application/vscode-jsonrpc; charset=utf-8\r\n\r\n" + body
    dec = FrameDecoder()
    assert dec.feed(blob) == [body]


def test_decode_rejects_lf_only_line_endings() -> None:
    blob = b"Content-Length: 7\n\n" + b'{"a":1}'
    dec = FrameDecoder()
    with pytest.raises(MalformedFrameError):
        dec.feed(blob)


def test_decode_rejects_missing_content_length() -> None:
    blob = b"Content-Type: text/plain\r\n\r\nhello"
    dec = FrameDecoder()
    with pytest.raises(MalformedFrameError):
        dec.feed(blob)


def test_decode_rejects_non_integer_content_length() -> None:
    blob = b"Content-Length: abc\r\n\r\n"
    dec = FrameDecoder()
    with pytest.raises(MalformedFrameError):
        dec.feed(blob)
