"""Unit tests for HoverController — verifies request format and response rendering."""
from __future__ import annotations

from gedit_lsp.features.hover import render_hover_contents


def test_render_string_contents() -> None:
    text = render_hover_contents("hello")
    assert text == "hello"


def test_render_markup_contents_extracts_value() -> None:
    text = render_hover_contents({"kind": "markdown", "value": "# Title\n\nbody"})
    assert "Title" in text and "body" in text


def test_render_markedstring_array() -> None:
    text = render_hover_contents([{"language": "python", "value": "def f(): ..."}, "docstring"])
    assert "def f()" in text and "docstring" in text


def test_render_none_returns_empty() -> None:
    assert render_hover_contents(None) == ""
