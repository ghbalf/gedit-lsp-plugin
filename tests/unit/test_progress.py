"""Unit tests for the pure $/progress state machine."""
from __future__ import annotations

from typing import Any

from gedit_lsp.progress import ProgressEntry, ProgressTracker, format_progress_fragment


_UNSET: Any = object()


def _begin(
    token: str | int,
    title: str,
    message: Any = _UNSET,
    percentage: Any = _UNSET,
) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": "begin", "title": title}
    if message is not _UNSET:
        value["message"] = message
    if percentage is not _UNSET:
        value["percentage"] = percentage
    return {"token": token, "value": value}


def _report(
    token: str | int,
    message: Any = _UNSET,
    percentage: Any = _UNSET,
) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": "report"}
    if message is not _UNSET:
        value["message"] = message
    if percentage is not _UNSET:
        value["percentage"] = percentage
    return {"token": token, "value": value}


def _end(token: str | int, message: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": "end"}
    if message is not None:
        value["message"] = message
    return {"token": token, "value": value}


def test_no_progress_fragment_is_none() -> None:
    assert ProgressTracker().active_fragment() is None


def test_begin_then_fragment_shows_title() -> None:
    t = ProgressTracker()
    assert t.handle(_begin("tok1", "Indexing")) is True
    assert t.active_fragment() == "Indexing"


def test_report_percentage_appended() -> None:
    t = ProgressTracker()
    t.handle(_begin("tok1", "Indexing"))
    assert t.handle(_report("tok1", percentage=45)) is True
    assert t.active_fragment() == "Indexing 45%"


def test_report_keeps_title_when_only_message_changes() -> None:
    t = ProgressTracker()
    t.handle(_begin("tok1", "Indexing"))
    t.handle(_report("tok1", message="3/57"))
    assert t.active_fragment() == "Indexing 3/57"


def test_percentage_preferred_over_message() -> None:
    t = ProgressTracker()
    t.handle(_begin("tok1", "Indexing", message="3/57", percentage=10))
    assert t.active_fragment() == "Indexing 10%"


def test_end_clears_entry() -> None:
    t = ProgressTracker()
    t.handle(_begin("tok1", "Indexing"))
    assert t.handle(_end("tok1")) is True
    assert t.active_fragment() is None


def test_report_for_unknown_token_ignored() -> None:
    t = ProgressTracker()
    assert t.handle(_report("ghost", percentage=50)) is False
    assert t.active_fragment() is None


def test_end_for_unknown_token_ignored() -> None:
    t = ProgressTracker()
    assert t.handle(_end("ghost")) is False


def test_malformed_params_ignored() -> None:
    t = ProgressTracker()
    assert t.handle({}) is False
    assert t.handle({"token": "x", "value": "not-a-dict"}) is False
    assert t.handle({"value": {"kind": "begin", "title": "X"}}) is False
    assert t.active_fragment() is None


def test_most_recently_updated_token_is_shown() -> None:
    t = ProgressTracker()
    t.handle(_begin("a", "Indexing"))
    t.handle(_begin("b", "Building"))
    assert t.active_fragment() == "Building"          # b is newest
    t.handle(_report("a", percentage=20))             # a re-promoted
    assert t.active_fragment() == "Indexing 20%"
    t.handle(_end("a"))                               # falls back to b
    assert t.active_fragment() == "Building"


def test_empty_title_with_percentage() -> None:
    assert format_progress_fragment(ProgressEntry(title="", percentage=5)) == "5%"


def test_non_integer_percentage_coerced_or_dropped() -> None:
    t = ProgressTracker()
    t.handle(_begin("tok1", "Indexing", percentage="not-a-number"))
    assert t.active_fragment() == "Indexing"          # bad pct dropped
    t.handle(_report("tok1", percentage=12.0))        # float → int
    assert t.active_fragment() == "Indexing 12%"


def test_report_null_percentage_clears_prior() -> None:
    t = ProgressTracker()
    t.handle(_begin("tok1", "Indexing", percentage=50))
    assert t.active_fragment() == "Indexing 50%"
    t.handle(_report("tok1", percentage=None))  # explicit null clears it
    assert t.active_fragment() == "Indexing"
