"""Pure $/progress work-done state machine.

GTK-free and transport-free so it can be unit-tested in isolation. The
`LanguageServer` owns one `ProgressTracker`, feeds it the `params` of each
`$/progress` notification via `handle()`, and renders the active work for
the statusbar via `active_fragment()`.

LSP work-done progress is a three-phase lifecycle keyed by a token:
`begin` (carries the required `title`), zero or more `report`s (update
`message` / `percentage`, title is sticky), and `end` (clears the token).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ProgressToken = str | int


@dataclass
class ProgressEntry:
    title: str
    message: str | None = None
    percentage: int | None = None


def _coerce_percentage(value: object) -> int | None:
    """LSP percentage is a uint 0-100; tolerate float, reject non-numerics."""
    if isinstance(value, bool):  # bool is an int subclass — exclude explicitly
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def format_progress_fragment(entry: ProgressEntry) -> str:
    """Render a short statusbar fragment: title + percentage, else + message."""
    if entry.percentage is not None:
        suffix = f" {entry.percentage}%"
    elif entry.message:
        suffix = f" {entry.message}"
    else:
        suffix = ""
    return f"{entry.title}{suffix}".strip()


class ProgressTracker:
    """Tracks active work-done progress tokens; renders the newest one."""

    def __init__(self) -> None:
        self._entries: dict[ProgressToken, ProgressEntry] = {}
        self._order: list[ProgressToken] = []  # least→most recently updated

    def handle(self, params: dict[str, Any]) -> bool:
        """Apply one `$/progress` notification's params.

        Returns True iff the active state changed (caller fires listeners).
        """
        token = params.get("token")
        value = params.get("value")
        if token is None or not isinstance(value, dict):
            return False
        kind = value.get("kind")
        if kind == "begin":
            self._entries[token] = ProgressEntry(
                title=value.get("title") or "",
                message=value.get("message"),
                percentage=_coerce_percentage(value.get("percentage")),
            )
            self._touch(token)
            return True
        if kind == "report":
            entry = self._entries.get(token)
            if entry is None:
                return False
            if "message" in value:
                entry.message = value.get("message")
            if "percentage" in value:
                entry.percentage = _coerce_percentage(value.get("percentage"))
            self._touch(token)
            return True
        if kind == "end":
            if token in self._entries:
                del self._entries[token]
                self._order.remove(token)
                return True
            return False
        return False

    def active_fragment(self) -> str | None:
        if not self._order:
            return None
        return format_progress_fragment(self._entries[self._order[-1]])

    def _touch(self, token: ProgressToken) -> None:
        if token in self._order:
            self._order.remove(token)
        self._order.append(token)
