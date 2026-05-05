"""Tests for the completion capability gate and trigger-character extraction."""
from __future__ import annotations

from gedit_lsp.features.completion import (
    is_completion_supported,
    trigger_characters_from,
    resolve_provider_from,
)


def test_is_completion_supported_no_capability() -> None:
    assert is_completion_supported(None) is False
    assert is_completion_supported({}) is False


def test_is_completion_supported_present_dict() -> None:
    assert is_completion_supported({"triggerCharacters": ["."]}) is True


def test_is_completion_supported_present_empty_dict() -> None:
    # Server reports support but configures nothing — still supported.
    assert is_completion_supported({}) is False  # we treat absent capability as no support
    assert is_completion_supported({"resolveProvider": False}) is True


def test_trigger_characters_extracts_list() -> None:
    assert trigger_characters_from({"triggerCharacters": [".", "->"]}) == [".", "->"]


def test_trigger_characters_missing_returns_empty() -> None:
    assert trigger_characters_from({}) == []
    assert trigger_characters_from(None) == []


def test_resolve_provider_default_false() -> None:
    assert resolve_provider_from({}) is False
    assert resolve_provider_from(None) is False


def test_resolve_provider_explicit_true() -> None:
    assert resolve_provider_from({"resolveProvider": True}) is True
