"""Tests for server-capabilities tracking and override application."""
from __future__ import annotations

from gedit_lsp.server import _merge_capabilities


def test_merge_capabilities_no_overrides_returns_server_caps() -> None:
    server_caps = {"hoverProvider": True, "completionProvider": {"triggerCharacters": ["."]}}
    assert _merge_capabilities(server_caps, {}) == server_caps


def test_merge_capabilities_overrides_top_level_bool() -> None:
    server_caps = {"hoverProvider": True}
    overrides  = {"hoverProvider": False}
    assert _merge_capabilities(server_caps, overrides) == {"hoverProvider": False}


def test_merge_capabilities_deep_merges_nested_dicts() -> None:
    server_caps = {
        "completionProvider": {"triggerCharacters": [".", "->"], "resolveProvider": True}
    }
    overrides = {
        "completionProvider": {"triggerCharacters": ["."]}  # narrow only
    }
    merged = _merge_capabilities(server_caps, overrides)
    assert merged == {
        "completionProvider": {"triggerCharacters": ["."], "resolveProvider": True}
    }


def test_merge_capabilities_override_adds_missing_capability() -> None:
    server_caps = {}
    overrides = {"hoverProvider": True}
    assert _merge_capabilities(server_caps, overrides) == {"hoverProvider": True}


def test_merge_capabilities_lists_are_replaced_not_concatenated() -> None:
    server_caps = {"completionProvider": {"triggerCharacters": [".", "->", "::"]}}
    overrides  = {"completionProvider": {"triggerCharacters": ["."]}}
    merged = _merge_capabilities(server_caps, overrides)
    assert merged["completionProvider"]["triggerCharacters"] == ["."]
