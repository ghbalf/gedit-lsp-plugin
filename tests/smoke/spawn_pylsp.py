#!/usr/bin/env python3
"""Spawn pylsp, complete initialize, print capabilities, shut down.

Usage:
    python tests/smoke/spawn_pylsp.py

Requires:
    - pylsp on $PATH
    - python3-gi (PyGObject), GLib

Exit codes:
    0 — success (initialize completed, shutdown sent, subprocess exited)
    1 — failure
"""
from __future__ import annotations

import json
import sys
from typing import Any

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

# Make the source tree importable without installing.
sys.path.insert(0, "src")

from gedit_lsp.rpc import RpcClient


def main() -> int:
    loop = GLib.MainLoop()

    def on_exit(code: int) -> None:
        print(f"pylsp exited (code={code})")
        loop.quit()

    client = RpcClient(
        command=["pylsp"],
        log_prefix="[python:smoke]",
        on_exit=on_exit,
    )
    client.start()

    def on_init(msg: dict[str, Any]) -> None:
        if msg.get("error"):
            print("initialize failed:", msg["error"])
            sys.exit(1)
        caps = msg["result"]["capabilities"]
        print("Server capabilities:", json.dumps(caps, indent=2)[:500])
        client.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})

        def on_shutdown(_msg: dict[str, Any]) -> None:
            client.send({"jsonrpc": "2.0", "method": "exit", "params": None})

        client.on_response(2, on_shutdown)
        client.send(
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None}
        )

    client.on_response(1, on_init)
    client.send(
        {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "processId": None, "rootUri": None, "capabilities": {},
            },
        }
    )

    def on_timeout() -> bool:
        print("TIMEOUT")
        loop.quit()
        return False

    GLib.timeout_add_seconds(15, on_timeout)
    loop.run()  # type: ignore[no-untyped-call]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
