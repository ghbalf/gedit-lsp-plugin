"""Tests for server-capabilities tracking and override application."""
from __future__ import annotations

from typing import Any

from gedit_lsp.server import LanguageServer, _merge_capabilities


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


def test_merge_capabilities_dict_replaces_non_dict() -> None:
    """When override has a dict but server has a non-dict at the same key,
    the override replaces wholesale (no merge attempt)."""
    server_caps = {"hoverProvider": True}
    overrides = {"hoverProvider": {"workDoneProgress": True}}
    merged = _merge_capabilities(server_caps, overrides)
    assert merged == {"hoverProvider": {"workDoneProgress": True}}


def test_merge_capabilities_result_is_independent_of_inputs() -> None:
    """Mutating the result must not affect either input — the function
    returns a structure with no shared references."""
    server_caps = {"completionProvider": {"triggerCharacters": ["."]}}
    overrides: dict[str, Any] = {}
    merged = _merge_capabilities(server_caps, overrides)
    # Mutate the result; inputs must be untouched.
    merged["completionProvider"]["triggerCharacters"].append("->")
    assert server_caps == {"completionProvider": {"triggerCharacters": ["."]}}


def _make_server(capability_overrides: dict[str, Any] | None = None) -> LanguageServer:
    return LanguageServer(
        language_id="python",
        command=["pylsp"],
        root_path="/tmp",
        initialization_options=None,
        transport_factory=lambda *a, **kw: None,  # type: ignore[arg-type]
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
        idle_timeout_seconds=300,
        stderr_buffer_max_lines=100,
        server_capability_overrides=capability_overrides or {},
    )


def test_capability_returns_none_before_initialize() -> None:
    server = _make_server()
    assert server.capability("hoverProvider") is None


def test_capability_returns_value_after_initialize_response() -> None:
    server = _make_server()
    server._apply_initialize_capabilities(
        {"hoverProvider": True, "completionProvider": {"triggerCharacters": ["."]}}
    )
    assert server.capability("hoverProvider") is True
    assert server.capability("completionProvider") == {"triggerCharacters": ["."]}


def test_capability_applies_overrides_after_initialize() -> None:
    server = _make_server({"hoverProvider": False})
    server._apply_initialize_capabilities({"hoverProvider": True})
    assert server.capability("hoverProvider") is False


def test_capability_unknown_key_returns_none() -> None:
    server = _make_server()
    server._apply_initialize_capabilities({"hoverProvider": True})
    assert server.capability("nonexistentProvider") is None
