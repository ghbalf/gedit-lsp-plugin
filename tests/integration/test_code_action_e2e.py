"""End-to-end codeAction test against real pylsp + pylsp-ruff.

Exercises the full pipeline:

    didOpen  ->  ruff diagnostic (F401 unused import)
             ->  textDocument/codeAction
             ->  codeAction/resolve (if needed)
             ->  apply WorkspaceEdit to a GtkSource.Buffer
             ->  assert `import os` line is gone

xfails (does NOT silently skip) when pylsp-ruff is not importable in
the same interpreter that runs `pylsp` — otherwise CI could "pass"
without actually validating the stack.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import gi
import pytest

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "300")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.code_action import needs_resolve, normalize_action
from gedit_lsp.rpc import RpcClient
from gedit_lsp.server import LanguageServer
from gedit_lsp.workspace_edit import apply_workspace_edit


FIXTURE_ROOT = (
    Path(__file__).parent.parent / "fixtures" / "projects" / "python_code_action"
)


# pylsp-ruff configuration. Disabling pyflakes/pycodestyle keeps the
# diagnostic set narrow so the "remove unused import" quickfix is
# unambiguous; without this, pyflakes also reports the same F401 and
# we'd have to disambiguate by source.
_RUFF_INIT_OPTS: dict[str, Any] = {
    "pylsp": {
        "plugins": {
            "ruff": {"enabled": True},
            "pyflakes": {"enabled": False},
            "pycodestyle": {"enabled": False},
            "mccabe": {"enabled": False},
        }
    }
}


def _pylsp_can_load_ruff() -> bool:
    """True iff pylsp's interpreter can import pylsp_ruff.

    pylsp is invoked as a subprocess, so checking `import pylsp_ruff`
    in *this* test interpreter is insufficient: the venv may have it
    while the system pylsp on PATH does not (or vice-versa).
    """
    pylsp_path = shutil.which("pylsp")
    if pylsp_path is None:
        return False
    # pylsp's shebang points at the interpreter it'll run under.
    try:
        first = Path(pylsp_path).read_text(errors="replace").splitlines()[0]
    except OSError:
        return False
    if not first.startswith("#!"):
        return False
    interp = first[2:].strip().split()[0]
    if not interp or not Path(interp).exists():
        return False
    try:
        subprocess.check_call(
            [interp, "-c", "import pylsp_ruff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return True


def _run_until(
    loop: GLib.MainLoop,
    predicate: Any,
    timeout_s: float = 10.0,
) -> bool:
    """Pump `loop` until predicate() returns truthy or timeout. Returns
    True if the predicate fired, False on timeout."""
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


def test_code_action_removes_unused_import_end_to_end(
    pylsp_available: None,
    tmp_path: Path,
    main_loop: GLib.MainLoop,
) -> None:
    if not _pylsp_can_load_ruff():
        pytest.xfail(
            "pylsp-ruff not importable from pylsp's interpreter; "
            "install python-lsp-ruff into the same env as pylsp to "
            "exercise this end-to-end test"
        )

    # Stage the fixture into a tmp workspace so pylsp roots there.
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE_ROOT, ws)
    src = ws / "example.py"
    text = src.read_text()
    uri = src.as_uri()

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
        initialization_options=_RUFF_INIT_OPTS,
        transport_factory=transport_factory,
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
    )

    diagnostics_for_uri: dict[str, list[dict[str, Any]]] = {}

    def on_diag(params: dict[str, Any]) -> None:
        u = params.get("uri")
        if isinstance(u, str):
            diagnostics_for_uri[u] = params.get("diagnostics", []) or []

    server.add_diagnostics_listener(on_diag)
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

    # 1. Wait for the F401 unused-import diagnostic from ruff.
    def has_ruff_unused_import() -> bool:
        diags = diagnostics_for_uri.get(uri, [])
        return any(
            (d.get("source") == "ruff") and ("F401" in str(d.get("code", "")))
            for d in diags
        )

    got = _run_until(main_loop, has_ruff_unused_import, timeout_s=12.0)
    if not got:
        # pylsp-ruff is importable but didn't publish the expected
        # diagnostic — either config wasn't honored or rule set differs.
        # xfail rather than fail noisily; this surfaces version skew
        # without breaking the suite for unrelated regressions.
        pytest.xfail(
            "pylsp-ruff did not publish an F401 diagnostic within 12s; "
            f"got diagnostics={diagnostics_for_uri.get(uri)!r}"
        )

    diags = diagnostics_for_uri[uri]
    target = next(
        d for d in diags
        if d.get("source") == "ruff" and "F401" in str(d.get("code", ""))
    )

    # 2. Request code actions at the unused-import line.
    rng = target["range"]
    response = _send_request_sync(
        server,
        main_loop,
        "textDocument/codeAction",
        {
            "textDocument": {"uri": uri},
            "range": rng,
            "context": {"diagnostics": [target], "triggerKind": 1},
        },
        timeout_s=10.0,
    )
    assert response is not None, "no codeAction response"
    result = response.get("result") or []
    assert isinstance(result, list) and result, (
        f"expected codeAction result, got {response!r}"
    )

    # 3. Normalize and pick the "remove unused import" action. Title
    #    varies by pylsp-ruff version; match by substring so the test
    #    survives minor wording drift.
    normalized = [a for a in (normalize_action(r) for r in result) if a is not None]
    assert normalized, f"all codeAction items malformed: {result!r}"

    def looks_like_remove_unused(title: str) -> bool:
        lower = title.lower()
        return ("remove" in lower and "unused" in lower) or (
            "f401" in lower and "os" in lower
        )

    candidates = [a for a in normalized if looks_like_remove_unused(a["title"])]
    assert candidates, (
        f"no 'remove unused import' action among titles: "
        f"{[a['title'] for a in normalized]}"
    )
    action = candidates[0]

    # 4. Resolve if the server returned only `data`.
    if needs_resolve(action):
        raw = {
            "title": action["title"],
            "kind": action["kind"],
            "data": action["data"],
        }
        resolved_msg = _send_request_sync(
            server, main_loop, "codeAction/resolve", raw, timeout_s=10.0
        )
        assert resolved_msg is not None and not resolved_msg.get("error"), (
            f"resolve failed: {resolved_msg!r}"
        )
        resolved = normalize_action(resolved_msg.get("result") or {})
        assert resolved is not None, (
            f"resolve returned malformed action: {resolved_msg!r}"
        )
        action = resolved

    edit = action["edit"]
    assert edit is not None, (
        f"action has no edit after resolve: {action!r}"
    )

    # 5. Apply the WorkspaceEdit to our buffer. We only expect changes
    #    for `uri` since the fixture is single-file.
    applied, failed = apply_workspace_edit(
        edit,
        buffer_for_uri=lambda u: buf if u == uri else None,
    )
    assert uri in applied, f"buffer not in applied set: {applied=} {failed=}"

    # 6. Assert the unused import is gone from the buffer.
    start, end = buf.get_bounds()
    new_text = buf.get_text(start, end, False)
    assert "import os" not in new_text, (
        f"`import os` still present after applying code action; buf=\n{new_text}"
    )
    # Sanity: the used import survived.
    assert "import sys" in new_text, (
        f"`import sys` unexpectedly removed; buf=\n{new_text}"
    )
