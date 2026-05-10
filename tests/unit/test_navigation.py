"""Regression tests for `gedit_lsp.navigation.navigate_to_uri`.

The original bug was a missing `Gedit.Window.create_tab_from_location`
method that the codebase had been calling for cross-file navigation in
`diagnostics_panel`, `definition`, and the show-server-logs path. The
right gedit API is the top-level `Gedit.commands_load_location`.
`navigate_to_uri` is the shared helper that handles three branches:

    1. URI matches the active document → place cursor in-buffer.
    2. URI matches another open tab    → `set_active_tab` + place cursor.
    3. URI is not yet open             → `Gedit.commands_load_location`.

These tests drive the helper with fakes for `Gedit.Window` and inject a
fake `load_location`, so they run outside the gedit runtime (no `Gedit`
typelib needed). View construction is also avoided to stay headless-CI
safe (see PR #14 postmortem).
"""
from __future__ import annotations

from typing import Any

from gedit_lsp.navigation import navigate_to_uri


class _FakeBuffer:
    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.placed_iter: str | None = None

    def get_file(self) -> Any:
        return _FakeFile(self.uri)

    def get_iter_at_line(self, line: int) -> str:
        return f"iter@line={line}"

    def place_cursor(self, it: Any) -> None:
        self.placed_iter = it

    @property
    def placed_at_line(self) -> int | None:
        """Convenience for tests using the default `to_iter`: extract the
        line number from the recorded `iter@line=N` string."""
        if self.placed_iter is None or "=" not in str(self.placed_iter):
            return None
        return int(str(self.placed_iter).split("=")[1])


class _FakeFile:
    def __init__(self, uri: str) -> None:
        self._uri = uri

    def get_location(self) -> Any:
        return _FakeLocation(self._uri)


class _FakeLocation:
    def __init__(self, uri: str) -> None:
        self._uri = uri

    def get_uri(self) -> str:
        return self._uri


class _FakeView:
    def __init__(self, buf: _FakeBuffer) -> None:
        self._buffer = buf
        self.scrolled_to: str | None = None

    def get_buffer(self) -> _FakeBuffer:
        return self._buffer

    def scroll_to_iter(
        self, it: str, _within: float, _use_align: bool,
        _xalign: float, _yalign: float,
    ) -> None:
        self.scrolled_to = it


class _FakeTab:
    def __init__(self, view: _FakeView) -> None:
        self._view = view

    def get_view(self) -> _FakeView:
        return self._view


class _FakeWindow:
    def __init__(
        self,
        active_uri: str | None = None,
        tabs_by_uri: dict[str, _FakeTab] | None = None,
    ) -> None:
        self._tabs_by_uri = tabs_by_uri or {}
        if active_uri is not None and active_uri in self._tabs_by_uri:
            self._active_view = self._tabs_by_uri[active_uri].get_view()
        else:
            self._active_view = None  # type: ignore[assignment]
        self.set_active_called_with: _FakeTab | None = None
        self.load_location_called_with: tuple[str, int] | None = None

    def get_active_view(self) -> _FakeView | None:
        return self._active_view

    def get_tab_from_location(self, gfile: Any) -> _FakeTab | None:
        return self._tabs_by_uri.get(gfile.get_uri())

    def set_active_tab(self, tab: _FakeTab) -> None:
        self.set_active_called_with = tab
        self._active_view = tab.get_view()


def _fake_load_location(
    window: _FakeWindow, gfile: Any, _enc: Any, line: int, col: int
) -> None:
    window.load_location_called_with = (gfile.get_uri(), line, col)


def _fake_file_for_uri(uri: str) -> Any:
    return _FakeLocation(uri)


# --- branch 1: active doc fast path ---------------------------------


def test_navigates_in_active_doc_when_uri_matches() -> None:
    buf = _FakeBuffer("file:///x.py")
    view = _FakeView(buf)
    win = _FakeWindow(
        active_uri="file:///x.py",
        tabs_by_uri={"file:///x.py": _FakeTab(view)},
    )
    navigate_to_uri(
        win, "file:///x.py", line=7, column=0,
        load_location=_fake_load_location,
        file_for_uri=_fake_file_for_uri,
    )
    # Cursor placed at line 7 in the active buffer.
    assert buf.placed_at_line == 7
    assert view.scrolled_to == "iter@line=7"
    # No tab switch, no tab open.
    assert win.set_active_called_with is None
    assert win.load_location_called_with is None


# --- branch 2: existing tab, not active --------------------------------


def test_switches_to_existing_tab_when_uri_open_elsewhere() -> None:
    other_buf = _FakeBuffer("file:///x.py")
    other_view = _FakeView(other_buf)
    other_tab = _FakeTab(other_view)
    active_buf = _FakeBuffer("file:///y.py")
    active_view = _FakeView(active_buf)
    win = _FakeWindow(
        active_uri="file:///y.py",
        tabs_by_uri={
            "file:///x.py": other_tab,
            "file:///y.py": _FakeTab(active_view),
        },
    )
    navigate_to_uri(
        win, "file:///x.py", line=3, column=0,
        load_location=_fake_load_location,
        file_for_uri=_fake_file_for_uri,
    )
    # Switched to the other tab.
    assert win.set_active_called_with is other_tab
    # Cursor placed in that tab's buffer.
    assert other_buf.placed_at_line == 3
    # Active doc untouched.
    assert active_buf.placed_at_line is None
    # No new-tab call.
    assert win.load_location_called_with is None


# --- branch 3: not yet open --------------------------------------------


def test_loads_location_when_uri_not_open() -> None:
    win = _FakeWindow(active_uri=None, tabs_by_uri={})
    navigate_to_uri(
        win, "file:///never-opened.py", line=12, column=0,
        load_location=_fake_load_location,
        file_for_uri=_fake_file_for_uri,
    )
    # commands_load_location called with line+1 (gedit is 1-indexed)
    # and column 0 (passed straight through).
    assert win.load_location_called_with == ("file:///never-opened.py", 13, 0)
    # No tab switch.
    assert win.set_active_called_with is None


# --- column passthrough + custom `to_iter` (definition.py paths) -------


def test_column_is_passed_to_load_location_for_unopened_files() -> None:
    """definition.py asks navigate_to_uri to land on a specific column.
    The fallback path forwards `column` straight to commands_load_location."""
    win = _FakeWindow(active_uri=None, tabs_by_uri={})
    navigate_to_uri(
        win, "file:///x.py", line=4, column=12,
        load_location=_fake_load_location,
        file_for_uri=_fake_file_for_uri,
    )
    assert win.load_location_called_with == ("file:///x.py", 5, 12)


def test_to_iter_callable_is_used_for_active_doc_branch() -> None:
    """definition.py uses `utf16_to_text_iter`; diagnostics_panel uses
    `get_iter_at_line`. The helper must invoke whichever the caller
    passes via `to_iter` rather than a hardcoded line-only call."""
    buf = _FakeBuffer("file:///x.py")
    view = _FakeView(buf)
    win = _FakeWindow(
        active_uri="file:///x.py",
        tabs_by_uri={"file:///x.py": _FakeTab(view)},
    )
    invocations: list[Any] = []

    def custom_to_iter(b: Any) -> str:
        invocations.append(b)
        return "iter@custom"

    navigate_to_uri(
        win, "file:///x.py", line=2, column=8,
        to_iter=custom_to_iter,
        load_location=_fake_load_location,
        file_for_uri=_fake_file_for_uri,
    )
    # Custom to_iter was invoked with the active buffer.
    assert invocations == [buf]
    # And its return value was used for both place_cursor and scroll.
    assert view.scrolled_to == "iter@custom"


def test_to_iter_callable_is_used_for_other_tab_branch() -> None:
    """Same as the active-doc test but the URI lives in a different tab."""
    target_buf = _FakeBuffer("file:///x.py")
    target_view = _FakeView(target_buf)
    target_tab = _FakeTab(target_view)
    active_view = _FakeView(_FakeBuffer("file:///y.py"))
    win = _FakeWindow(
        active_uri="file:///y.py",
        tabs_by_uri={
            "file:///x.py": target_tab,
            "file:///y.py": _FakeTab(active_view),
        },
    )
    invocations: list[Any] = []

    def custom_to_iter(b: Any) -> str:
        invocations.append(b)
        return "iter@custom"

    navigate_to_uri(
        win, "file:///x.py", line=2, column=8,
        to_iter=custom_to_iter,
        load_location=_fake_load_location,
        file_for_uri=_fake_file_for_uri,
    )
    # to_iter was called with the *target* tab's buffer, not the active buffer.
    assert invocations == [target_buf]
    assert target_view.scrolled_to == "iter@custom"


# --- classify_locations -------------------------------------------------
# Relocated from test_definition_controller.py — the helper now lives in
# navigation.py because both definition and references consume it.

from gedit_lsp.navigation import classify_locations  # noqa: E402


def test_classify_no_locations() -> None:
    assert classify_locations(None) == ("none", [])
    assert classify_locations([]) == ("none", [])


def test_classify_single_location() -> None:
    loc = {
        "uri": "file:///x.py",
        "range": {
            "start": {"line": 0, "character": 0},
            "end":   {"line": 0, "character": 3},
        },
    }
    kind, locs = classify_locations(loc)
    assert kind == "single"
    assert locs == [loc]


def test_classify_array_with_one() -> None:
    loc = {
        "uri": "file:///x.py",
        "range": {
            "start": {"line": 0, "character": 0},
            "end":   {"line": 0, "character": 3},
        },
    }
    kind, _locs = classify_locations([loc])
    assert kind == "single"


def test_classify_array_with_many() -> None:
    locs = [
        {"uri": "file:///x.py",
         "range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 3}}},
        {"uri": "file:///y.py",
         "range": {"start": {"line": 5, "character": 0},
                   "end":   {"line": 5, "character": 3}}},
    ]
    kind, got = classify_locations(locs)
    assert kind == "many"
    assert got == locs
