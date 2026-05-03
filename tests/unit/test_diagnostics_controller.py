"""Unit tests for DiagnosticsController.

Tests construct a Gtk.TextBuffer manually, build the controller, then
call `apply_diagnostics` with synthetic LSP `Diagnostic` dicts.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
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


def test_severity_colors_applied_to_tag_underline_rgba() -> None:
    """severity_colors should set underline-rgba on each created tag."""
    buf = _buffer("hello\n")
    DiagnosticsController(
        buffer=buf,
        severity_underlines={"error": "error", "warning": "error"},
        severity_colors={"error": "#e01b24", "warning": "#e5a50a"},
    )
    table = buf.get_tag_table()
    err = table.lookup("lsp-diag-error")
    warn = table.lookup("lsp-diag-warning")
    assert err is not None and warn is not None
    assert err.get_property("underline-rgba-set") is True
    assert warn.get_property("underline-rgba-set") is True
    err_rgba = err.get_property("underline-rgba")
    warn_rgba = warn.get_property("underline-rgba")
    # Two distinct severities must get distinct colors.
    assert (err_rgba.red, err_rgba.green, err_rgba.blue) != (
        warn_rgba.red, warn_rgba.green, warn_rgba.blue,
    )


def test_zero_width_range_is_widened_for_visibility() -> None:
    """pycodestyle W292 'no newline at end of file' reports a zero-width
    range at EOF — we must widen it so a squiggle is visible.
    """
    buf = _buffer("hello\nworld\n")
    ctrl = DiagnosticsController(buffer=buf, severity_underlines={"warning": "error"})
    ctrl.apply_diagnostics(
        [
            {
                "range": {
                    "start": {"line": 0, "character": 2},
                    "end":   {"line": 0, "character": 2},
                },
                "severity": 2,
                "message": "fake-W292",
            }
        ]
    )
    tag = buf.get_tag_table().lookup("lsp-diag-warning")
    assert tag is not None
    it = buf.get_start_iter()
    assert it.forward_to_tag_toggle(tag), "no tagged range present — widening failed"
    end_it = it.copy()
    end_it.forward_to_tag_toggle(tag)
    # Range must span at least one character.
    assert end_it.get_offset() - it.get_offset() >= 1


def test_zero_width_range_at_eof_widens_backward() -> None:
    """If the zero-width range is at the very end of the buffer, forward
    nudge fails — must fall back to widening backward."""
    buf = _buffer("ab")
    end_offset = buf.get_end_iter().get_offset()
    ctrl = DiagnosticsController(buffer=buf, severity_underlines={"warning": "error"})
    ctrl.apply_diagnostics(
        [
            {
                "range": {
                    "start": {"line": 0, "character": end_offset},
                    "end":   {"line": 0, "character": end_offset},
                },
                "severity": 2,
                "message": "at-eof",
            }
        ]
    )
    tag = buf.get_tag_table().lookup("lsp-diag-warning")
    assert tag is not None
    it = buf.get_start_iter()
    assert it.forward_to_tag_toggle(tag)
    end_it = it.copy()
    end_it.forward_to_tag_toggle(tag)
    assert end_it.get_offset() - it.get_offset() >= 1


def test_severity_colors_omitted_leaves_underline_rgba_unset() -> None:
    """When no colors are supplied, tags should not flip underline-rgba-set."""
    buf = _buffer("hello\n")
    DiagnosticsController(
        buffer=buf,
        severity_underlines={"error": "error"},
    )
    tag = buf.get_tag_table().lookup("lsp-diag-error")
    assert tag is not None
    assert tag.get_property("underline-rgba-set") is False


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
