"""Tests for matched_trigger_suffix — finds the longest trigger char/string
ending the text before the cursor."""
from __future__ import annotations

from gedit_lsp.features.completion import matched_trigger_suffix


def test_no_trigger_chars() -> None:
    assert matched_trigger_suffix("foo.", []) is None


def test_single_char_trigger_match() -> None:
    assert matched_trigger_suffix("foo.", [".", "->"]) == "."


def test_no_match_returns_none() -> None:
    assert matched_trigger_suffix("foo", [".", "->"]) is None


def test_multichar_trigger_match() -> None:
    assert matched_trigger_suffix("foo->", [".", "->"]) == "->"


def test_longest_match_wins() -> None:
    """If both `>` and `->` were triggers, `->` wins for `foo->`."""
    assert matched_trigger_suffix("foo->", [">", "->"]) == "->"
    # And reverse order in the trigger list shouldn't change the result.
    assert matched_trigger_suffix("foo->", ["->", ">"]) == "->"
