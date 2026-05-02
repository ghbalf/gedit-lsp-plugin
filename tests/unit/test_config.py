"""Tests for the Config loader and merge policy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gedit_lsp.config import Config, ConfigError


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj))


def test_no_user_file_uses_defaults_only(tmp_path: Path) -> None:
    cfg = Config(user_path=tmp_path / "missing.json")
    cfg.load()
    assert cfg.server_for("python")["command"] == ["pylsp"]


def test_user_override_replaces_server_command(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"servers": {"python": {"command": ["pyright-langserver", "--stdio"]}}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.server_for("python")["command"] == ["pyright-langserver", "--stdio"]


def test_user_override_does_not_affect_other_languages(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"servers": {"python": {"command": ["pyright-langserver"]}}})
    cfg = Config(user_path=user)
    cfg.load()
    # Rust still uses default
    assert cfg.server_for("rust")["command"] == ["rust-analyzer"]


def test_unknown_language_returns_none(tmp_path: Path) -> None:
    cfg = Config(user_path=tmp_path / "missing.json")
    cfg.load()
    assert cfg.server_for("brainfuck") is None


def test_user_can_add_new_language(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"servers": {"haskell": {"command": ["haskell-language-server-wrapper", "--lsp"]}}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.server_for("haskell")["command"] == [
        "haskell-language-server-wrapper", "--lsp"
    ]


def test_malformed_json_raises_with_path(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    user.write_text("{not valid json")
    cfg = Config(user_path=user)
    with pytest.raises(ConfigError) as exc:
        cfg.load()
    assert str(user) in str(exc.value)


def test_root_markers_per_language_override_default(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"rootMarkers": {"python": ["only-pyproject.toml"]}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.root_markers_for("python") == ["only-pyproject.toml"]
    # Other languages still use the default merged list
    assert ".git" in cfg.root_markers_for("rust")


def test_tunables_user_override_replaces_value(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(user, {"tunables": {"changeDebounceMs": 500}})
    cfg = Config(user_path=user)
    cfg.load()
    assert cfg.tunable("changeDebounceMs") == 500
    # Untouched tunable retains default
    assert cfg.tunable("serverIdleTimeoutSeconds") == 300


def test_capability_overrides_deep_merged(tmp_path: Path) -> None:
    """serverCapabilityOverrides is per-key replacement at every depth."""
    user = tmp_path / "lsp-plugin.json"
    write_json(
        user,
        {"tunables": {"serverCapabilityOverrides": {"python": {"hoverProvider": False}}}},
    )
    cfg = Config(user_path=user)
    cfg.load()
    overrides = cfg.tunable("serverCapabilityOverrides")
    assert overrides["python"]["hoverProvider"] is False


def test_initialization_options_user_override(tmp_path: Path) -> None:
    user = tmp_path / "lsp-plugin.json"
    write_json(
        user,
        {"initializationOptions": {"python": {"plugins": {"pycodestyle": {"enabled": False}}}}},
    )
    cfg = Config(user_path=user)
    cfg.load()
    init_opts = cfg.initialization_options_for("python")
    assert init_opts["plugins"]["pycodestyle"]["enabled"] is False


def test_initialization_options_none_for_missing_language(tmp_path: Path) -> None:
    cfg = Config(user_path=tmp_path / "missing.json")
    cfg.load()
    assert cfg.initialization_options_for("python") is None
