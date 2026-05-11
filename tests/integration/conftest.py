"""Integration-test fixtures.

Fixtures construct real LanguageServer instances driving real pylsp
subprocesses. Each test gets a tmp directory it can populate; pylsp is
rooted there.
"""
from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import gi
import pytest

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.config import Config
from gedit_lsp.registry import ServerRegistry
from gedit_lsp.rpc import RpcClient


@pytest.fixture
def pylsp_available() -> None:
    if shutil.which("pylsp") is None:
        pytest.skip("pylsp not on PATH; install python3-pylsp or python-lsp-server")


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config(user_path=tmp_path / "missing.json")
    c.load()
    return c


@pytest.fixture
def registry(cfg: Config) -> ServerRegistry:
    def factory(
        command: list[str],
        log_prefix: str,
        on_exit: Callable[[int], None],
        on_stderr_line: Callable[[str], None] | None = None,
        cwd: str | None = None,
    ) -> RpcClient:
        return RpcClient(
            command=command,
            log_prefix=log_prefix,
            on_exit=on_exit,
            on_stderr_line=on_stderr_line,
            cwd=cwd,
        )

    return ServerRegistry(config=cfg, transport_factory=factory)


@pytest.fixture
def main_loop() -> Iterator[GLib.MainLoop]:
    """Provide a runnable MainLoop the test owns."""
    loop = GLib.MainLoop()
    yield loop


def run_until(
    loop: GLib.MainLoop,
    predicate: Callable[[], Any],
    timeout_s: float = 10.0,
) -> None:
    """Pump the GLib loop until predicate() returns truthy or timeout."""
    expired = [False]

    def _check() -> bool:
        if predicate():
            loop.quit()
            return False
        return True

    def _on_timeout() -> bool:
        loop.quit()
        expired[0] = True
        return False

    GLib.idle_add(_check)
    GLib.timeout_add(50, _check)
    GLib.timeout_add_seconds(int(timeout_s), _on_timeout)
    loop.run()  # type: ignore[no-untyped-call]
    if expired[0]:
        raise TimeoutError("integration test timed out")
