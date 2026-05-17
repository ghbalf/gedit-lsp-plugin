"""End-to-end workspace/symbol against real pylsp on a multi-file project.

pylsp returns SymbolInformation with full locations. Uses the existing
python_rename fixture (lib.py defines `compute_total` and `Calculator`).
Skips cleanly if pylsp is unavailable; xfails (not silent-pass) if pylsp
is present but never advertises workspaceSymbolProvider.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import gi
import pytest

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "300")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.rpc import RpcClient
from gedit_lsp.server import LanguageServer

FIXTURE_ROOT = (
    Path(__file__).parent.parent / "fixtures" / "projects" / "python_rename"
)


def _run_until(loop: GLib.MainLoop, predicate: Any, timeout_s: float = 12.0) -> bool:
    state = {"hit": False}

    def _check() -> bool:
        if predicate():
            state["hit"] = True
            loop.quit()
            return False
        return True

    def _on_timeout() -> bool:
        loop.quit()
        return False

    GLib.timeout_add(50, _check)
    GLib.timeout_add_seconds(int(timeout_s), _on_timeout)
    loop.run()  # type: ignore[no-untyped-call]
    return state["hit"]


def _send_request_sync(
    server: LanguageServer,
    loop: GLib.MainLoop,
    method: str,
    params: dict[str, Any],
    timeout_s: float = 10.0,
) -> dict[str, Any] | None:
    holder: dict[str, dict[str, Any]] = {}

    def on_resp(msg: dict[str, Any]) -> None:
        holder["msg"] = msg

    server._send_request(method, params, on_resp)
    _run_until(loop, lambda: "msg" in holder, timeout_s=timeout_s)
    return holder.get("msg")


def test_workspace_symbol_finds_cross_file_symbol(
    pylsp_available: None,
    tmp_path: Path,
    main_loop: GLib.MainLoop,
) -> None:
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE_ROOT, ws)
    lib = ws / "lib.py"
    text = lib.read_text()
    uri = lib.as_uri()

    def transport_factory(
        command: list[str],
        log_prefix: str,
        on_exit: Any,
        on_stderr_line: Any = None,
        cwd: str | None = None,
    ) -> RpcClient:
        return RpcClient(
            command=command,
            log_prefix=log_prefix,
            on_exit=on_exit,
            on_stderr_line=on_stderr_line,
            cwd=cwd,
        )

    server = LanguageServer(
        language_id="python",
        root_path=str(ws),
        command=["pylsp"],
        initialization_options=None,
        transport_factory=transport_factory,
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
    )
    server.attach_buffer(uri)

    buf = GtkSource.Buffer()
    buf.set_text(text)
    bridge = DocumentBridge(
        uri=uri,
        language_id="python",
        text=text,
        server=server,
        clock=GLibClock(),
        debounce_ms=150,
    )
    bridge.attach()

    ready = _run_until(
        main_loop,
        lambda: server.capability("workspaceSymbolProvider") is not None,
        timeout_s=12.0,
    )
    if not ready or not server.capability("workspaceSymbolProvider"):
        pytest.xfail(
            "pylsp did not advertise workspaceSymbolProvider within 12s "
            f"(capability={server.capability('workspaceSymbolProvider')!r})"
        )

    response = _send_request_sync(
        server, main_loop, "workspace/symbol", {"query": "compute_total"},
        timeout_s=10.0,
    )
    assert response is not None, "no workspace/symbol response"
    result = response.get("result") or []
    assert isinstance(result, list) and result, (
        f"expected workspace/symbol hits, got {response!r}"
    )
    names = [r.get("name") for r in result if isinstance(r, dict)]
    assert "compute_total" in names, f"compute_total not in {names!r}"
    hit = next(r for r in result if r.get("name") == "compute_total")
    assert hit["location"]["uri"].endswith("lib.py"), hit["location"]["uri"]
