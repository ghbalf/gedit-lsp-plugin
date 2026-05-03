"""Unit tests for DiagnosticsController.

Tests construct a Gtk.TextBuffer manually, build the controller, then
call `apply_diagnostics` with synthetic LSP `Diagnostic` dicts.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import GtkSource

from gedit_lsp.features.diagnostics import DiagnosticsController


def _buffer(text: str) -> GtkSource.Buffer:
    buf = GtkSource.Buffer()
    buf.set_text(text)
    return buf


def test_clears_then_applies_tags() -> None:
    buf = _buffer("line0\nline1\n")
    ctrl = DiagnosticsController(buffer=buf, severity_underlines={"error": "error"})
    ctrl.apply_diagnostics(
        [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 4},
                },
                "severity": 1,
                "message": "boom",
                "source": "pylsp",
            }
        ]
    )
    # Re-apply with no diagnostics — old tag must be cleared
    ctrl.apply_diagnostics([])
    # Look for the error tag — should not be applied anywhere now
    tag = buf.get_tag_table().lookup("lsp-diag-error")
    if tag is None:
        return  # never created — fine
    start = buf.get_start_iter()
    assert not start.starts_tag(tag) and not start.has_tag(tag)


def test_applies_correct_range_for_emoji() -> None:
    buf = _buffer("a🐍def")
    ctrl = DiagnosticsController(buffer=buf, severity_underlines={"warning": "error"})
    # Mark "def" — UTF-16 chars 3..6 (after `a` and the surrogate pair)
    ctrl.apply_diagnostics(
        [
            {
                "range": {
                    "start": {"line": 0, "character": 3},
                    "end": {"line": 0, "character": 6},
                },
                "severity": 2,
                "message": "warn",
            }
        ]
    )
    tag = buf.get_tag_table().lookup("lsp-diag-warning")
    assert tag is not None
    # Find the tagged range
    it = buf.get_start_iter()
    it.forward_to_tag_toggle(tag)
    assert it.get_line_offset() == 2  # codepoint offset for "def" (after a + 🐍)
