"""Tests for ServerRegistry — the (lang, root) → LanguageServer map."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gedit_lsp.config import Config
from gedit_lsp.registry import ServerRegistry


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config(user_path=tmp_path / "missing.json")
    c.load()
    return c


def test_same_lang_same_root_returns_same_server(cfg: Config) -> None:
    reg = ServerRegistry(config=cfg, transport_factory=MagicMock())
    s1 = reg.get_or_spawn("python", Path("/tmp/proj"))
    s2 = reg.get_or_spawn("python", Path("/tmp/proj"))
    assert s1 is s2


def test_same_lang_different_root_returns_different_server(cfg: Config) -> None:
    reg = ServerRegistry(config=cfg, transport_factory=MagicMock())
    s1 = reg.get_or_spawn("python", Path("/tmp/projA"))
    s2 = reg.get_or_spawn("python", Path("/tmp/projB"))
    assert s1 is not s2


def test_different_lang_same_root_returns_different_server(cfg: Config) -> None:
    reg = ServerRegistry(config=cfg, transport_factory=MagicMock())
    s1 = reg.get_or_spawn("python", Path("/tmp/proj"))
    s2 = reg.get_or_spawn("c", Path("/tmp/proj"))
    assert s1 is not s2


def test_no_server_configured_returns_none(cfg: Config) -> None:
    reg = ServerRegistry(config=cfg, transport_factory=MagicMock())
    assert reg.get_or_spawn("brainfuck", Path("/tmp/proj")) is None
