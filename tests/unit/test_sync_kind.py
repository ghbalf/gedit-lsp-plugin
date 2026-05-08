"""Tests for textDocumentSync capability parsing.

The server reports textDocumentSync in one of three shapes:
- An integer TextDocumentSyncKind (0=None, 1=Full, 2=Incremental) — legacy short form.
- A TextDocumentSyncOptions object {"change": int, ...} — long form (3.17 preferred).
- Missing/None — many older servers omit it.

Per LSP spec, missing defaults to None, but real clients (VS Code, neovim)
default to Full because servers in the wild expect didChange even when they
forget to advertise sync. We match that.
"""
from __future__ import annotations

from gedit_lsp.bridge import SyncKind, parse_sync_kind


def test_int_full() -> None:
    assert parse_sync_kind(1) is SyncKind.FULL


def test_int_incremental() -> None:
    assert parse_sync_kind(2) is SyncKind.INCREMENTAL


def test_int_none() -> None:
    assert parse_sync_kind(0) is SyncKind.NONE


def test_options_change_incremental() -> None:
    assert parse_sync_kind({"change": 2, "openClose": True}) is SyncKind.INCREMENTAL


def test_options_change_full() -> None:
    assert parse_sync_kind({"change": 1}) is SyncKind.FULL


def test_options_change_none() -> None:
    assert parse_sync_kind({"change": 0}) is SyncKind.NONE


def test_options_missing_change_field_defaults_to_none() -> None:
    """Per spec: TextDocumentSyncOptions.change is optional with default None."""
    assert parse_sync_kind({"openClose": True}) is SyncKind.NONE


def test_capability_absent_defaults_to_full() -> None:
    """Many servers omit textDocumentSync but still expect didChange. Match VS Code's pragmatic default."""
    assert parse_sync_kind(None) is SyncKind.FULL


def test_unknown_int_defaults_to_full() -> None:
    """Defensive: an out-of-range int falls back to Full rather than crashing."""
    assert parse_sync_kind(99) is SyncKind.FULL


def test_unexpected_shape_defaults_to_full() -> None:
    """A string or list at this key is malformed; degrade safely."""
    assert parse_sync_kind("incremental") is SyncKind.FULL
    assert parse_sync_kind([2]) is SyncKind.FULL
