"""Tests for the log setup."""
from __future__ import annotations

from pathlib import Path

from gedit_lsp.log import setup_logging


def test_creates_state_dir_and_plugin_log(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    setup_logging(state_dir, level="info", traffic_enabled=False, max_bytes=1024, keep=2)
    assert (state_dir / "plugin.log").exists()


def test_traffic_log_only_when_enabled(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    setup_logging(state_dir, level="info", traffic_enabled=False, max_bytes=1024, keep=2)
    assert not (state_dir / "lsp-traffic.log").exists()
    setup_logging(state_dir, level="info", traffic_enabled=True, max_bytes=1024, keep=2)
    assert (state_dir / "lsp-traffic.log").exists()


def test_plugin_log_records_have_levels(tmp_path: Path) -> None:
    import logging
    state_dir = tmp_path / "state"
    setup_logging(state_dir, level="debug", traffic_enabled=False, max_bytes=1024, keep=2)
    logging.getLogger("gedit_lsp").info("hello")
    logging.shutdown()
    text = (state_dir / "plugin.log").read_text()
    assert "INFO" in text
    assert "hello" in text
