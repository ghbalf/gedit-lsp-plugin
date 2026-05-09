# textDocument/references Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `textDocument/references` to the gedit-lsp-plugin: trigger via Ctrl+Shift+F12 / right-click "Find References" → bottom-panel "LSP References" tab → click row to jump.

**Architecture:** A new `ReferencesController` (window-scoped, mirrors `DefinitionController`) sends the LSP request after a flush of pending didChange, classifies the response as 0/1/N via the existing `classify_locations()` helper (relocated from `features/definition.py` to `navigation.py` so both features share it), and dispatches: 0 → status-bar; 1 → direct `navigate_to_uri`; N → `ReferencesPanel.set_results(...)` and reveal the bottom-panel tab. `ReferencesPanel` is a near-clone of `DiagnosticsPanel`: `Gtk.TreeView` over a `Gtk.ListStore` with hidden URI/UTF-16 columns and `row-activated` → `navigate_to_uri`. Preview text per row comes from open buffers when available, falling back to a synchronous file read.

**Tech Stack:** Python 3.10+, PyGObject (Gtk 3 / GtkSource 300 / Gedit 3.0 typelibs at runtime), pytest for unit tests, `make test` for the test runner (which strips `PYTHONPATH` to dodge the system-wide leak documented in project memory).

**Branch:** `feat/references` (already created from `main`; spec committed at `ff115e4`).

---

## File structure

| File | Verb | Responsibility |
|---|---|---|
| `src/gedit_lsp/navigation.py` | modify | Add `classify_locations()` (moved from `features/definition.py`). |
| `src/gedit_lsp/features/definition.py` | modify | Remove local `classify_locations`, import from `navigation`. |
| `src/gedit_lsp/ui/references_panel.py` | create | `ReferencesPanel` + `_basename_for_uri` + `fetch_preview_line` (pure helper for testability). |
| `src/gedit_lsp/features/references.py` | create | `ReferencesController` (window-scoped). |
| `src/gedit_lsp/ui/popup_menu.py` | modify | Add `"Find References"` entry to `MENU_ITEMS`. |
| `src/gedit_lsp/plugin.py` | modify | Construct panel + controller; register `lsp-references` action + accel + handler; teardown is a no-op (panel persists — same as `DiagnosticsPanel`). |
| `src/gedit_lsp/defaults.py` | modify | Add `"references"` to `enabledFeatures`; add `"references": ["<Primary><Shift>F12"]` to `DEFAULT_KEYBINDINGS`. |
| `docs/configure.md` | modify | Add a row to the keybindings table. |
| `docs/protocol-coverage.md` | modify | Mark `textDocument/references` ✓. |
| `tests/unit/test_navigation.py` | modify | Add `classify_locations` test cases (relocated). |
| `tests/unit/test_definition_controller.py` | modify | Drop the four `classify_*` tests now living in `test_navigation.py`; keep CursorHistory tests. |
| `tests/unit/test_references_panel.py` | create | Panel unit tests using the `__new__` bypass pattern from `test_diagnostics_panel.py`. |
| `tests/unit/test_references_controller.py` | create | Controller unit tests; flush-before-send invariant; capability gate; payload shape; 0/1/N dispatch. |
| `tests/unit/test_popup_menu.py` | modify | Add a test ensuring `"Find References"` is in `MENU_ITEMS` mapped to `lsp-references`. |

---

## Conventions to follow throughout

- **Run tests with** `env -u PYTHONPATH python -m pytest tests/unit -x` (or `make test`) — the `env -u` is essential, see project memory `bashrc PYTHONPATH leak`.
- **No GTK widgets in unit tests** that need a `DISPLAY`: use `Gtk.ListStore`/`GtkSource.Buffer` (model objects) or `MagicMock()` for view-typed parameters. Constructing `Gtk.Window` / `Gtk.Popover` / `GtkSource.View` SIGTRAPs in headless CI.
- **`__new__` bypass for panels:** `panel = ReferencesPanel.__new__(ReferencesPanel)` lets you build a store and exercise the row-manipulation methods without the real `__init__` (which needs a `Gedit.Window` and a bottom panel). See `tests/unit/test_diagnostics_panel.py` for the pattern.
- **Edit-flush invariant:** any feature that triggers an LSP request from an edit-position MUST call `flush_pending_change()` BEFORE `_send_request(...)`. Test by capturing `len(server.requests)` inside the flush callable and asserting `flush@0` (i.e. flush ran when zero requests had been sent yet).
- **Commits:** one commit per task with the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer (the user's CLAUDE.md commit policy). HEREDOC the commit body. Do NOT push to origin during this plan — local commits only; PR opens at the end.

---

### Task 1: Move `classify_locations` to `navigation.py`

**Files:**
- Modify: `src/gedit_lsp/navigation.py` (append `classify_locations`)
- Modify: `src/gedit_lsp/features/definition.py:33-44` (remove local def, add import)
- Modify: `tests/unit/test_navigation.py` (append four `test_classify_*` cases)
- Modify: `tests/unit/test_definition_controller.py:1-58` (drop four `test_classify_*` cases, drop the import; keep `CursorHistory` tests)

This is a behavior-preserving relocation. The TDD shape is: write the new tests first against the new import path, watch them ImportError, do the move, watch them pass.

- [ ] **Step 1.1: Append the four classify tests to `tests/unit/test_navigation.py`**

Append at end of file:

```python


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
```

- [ ] **Step 1.2: Run the new tests to verify they fail**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_navigation.py -k classify -v`

Expected: 4 tests fail with `ImportError: cannot import name 'classify_locations' from 'gedit_lsp.navigation'`.

- [ ] **Step 1.3: Move `classify_locations` to `navigation.py`**

Append to `src/gedit_lsp/navigation.py`:

```python


def classify_locations(result: Any) -> tuple[str, list[dict[str, Any]]]:
    """Classify an LSP `Location | Location[] | null` response.

    Returns one of:
      - `("none",   [])`  — null result or empty array
      - `("single", [loc])` — single object or single-element array
      - `("many",   locs)` — multi-element array

    Used by both `textDocument/definition` and `textDocument/references`,
    which share the `Location[]` shape.
    """
    if result is None:
        return ("none", [])
    if isinstance(result, dict):
        return ("single", [result])
    if isinstance(result, list):
        if not result:
            return ("none", [])
        if len(result) == 1:
            return ("single", result)
        return ("many", result)
    return ("none", [])
```

- [ ] **Step 1.4: Update `features/definition.py`**

In `src/gedit_lsp/features/definition.py`:

1. Replace the existing `classify_locations` definition (lines 33-44) and its preceding blank line with nothing (delete those 13 lines).
2. Add to the imports near the top, after the existing `from gedit_lsp.navigation import navigate_to_uri` line:

```python
from gedit_lsp.navigation import classify_locations, navigate_to_uri
```

(Replace the existing single-import line, do not add a duplicate.)

The body that calls `classify_locations(...)` at the existing location (`on_response`) is unchanged — it now resolves through the import.

- [ ] **Step 1.5: Drop the four classify tests + import from `test_definition_controller.py`**

In `tests/unit/test_definition_controller.py`:

1. Change the import block:

```python
from gedit_lsp.features.definition import (
    CursorHistory,
    classify_locations,
)
```

to:

```python
from gedit_lsp.features.definition import CursorHistory
```

2. Delete the four functions `test_classify_no_locations`, `test_classify_single_location`, `test_classify_array_with_one`, `test_classify_array_with_many` (and the blank lines between them). The `CursorHistory` tests at the bottom stay.

- [ ] **Step 1.6: Run all unit tests**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass. Quickly grep for stragglers:

Run: `grep -rn 'from gedit_lsp.features.definition import.*classify_locations' src tests`

Expected: no output. Any hit means a missed reference; update it.

- [ ] **Step 1.7: Commit**

```bash
git add src/gedit_lsp/navigation.py \
        src/gedit_lsp/features/definition.py \
        tests/unit/test_navigation.py \
        tests/unit/test_definition_controller.py
git commit -m "$(cat <<'EOF'
refactor(navigation): move classify_locations to shared module

textDocument/references and textDocument/definition both consume
Location | Location[] | null responses. Hoisting classify_locations
out of features/definition.py and into navigation.py (which already
hosts navigate_to_uri) lets both feature controllers depend on the
shared helper without features/definition becoming a coupling point.

Behaviour-preserving: same function body, same tests (relocated to
test_navigation.py).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `ReferencesPanel` + unit tests

**Files:**
- Create: `src/gedit_lsp/ui/references_panel.py`
- Create: `tests/unit/test_references_panel.py`

The panel mirrors `DiagnosticsPanel` line-for-line. Two pure helpers — `_basename_for_uri` and `fetch_preview_line` — are extracted at module level so they can be unit-tested without instantiating the panel.

**Column layout** (exposed as integer constants on the class):

| Index | Type | Visible | Meaning |
|---|---|---|---|
| 0 | str | yes | File basename |
| 1 | int | yes | Line number (1-based, for display) |
| 2 | str | yes | Source preview (single line, truncated) |
| 3 | str | no  | Full URI (used by `_on_row_activated`) |
| 4 | int | no  | UTF-16 character offset (used by `_on_row_activated`) |

- [ ] **Step 2.1: Write `tests/unit/test_references_panel.py`**

```python
"""Unit tests for ReferencesPanel + its pure preview/uri helpers.

Constructor is bypassed via __new__ because real construction needs a
Gedit.Window and the corresponding bottom panel, which are unavailable
in unit tests. The row-manipulation methods only touch `self._store`,
so we exercise them on a freshly-built ListStore. The pure helpers
(`_basename_for_uri`, `fetch_preview_line`) are tested directly at
module level, no panel needed.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # type: ignore[attr-defined]

from gedit_lsp.ui.references_panel import (
    ReferencesPanel,
    _basename_for_uri,
    fetch_preview_line,
)


def _panel_with_rows(rows: list[list[Any]]) -> ReferencesPanel:
    panel = ReferencesPanel.__new__(ReferencesPanel)
    panel._window = MagicMock()
    panel._store = Gtk.ListStore(str, int, str, str, int)  # type: ignore[call-arg]
    for r in rows:
        panel._store.append(r)
    return panel


# --- _basename_for_uri ------------------------------------------------


def test_basename_for_uri_extracts_final_path_segment() -> None:
    assert _basename_for_uri("file:///home/u/a.py") == "a.py"
    assert _basename_for_uri("file:///x/y/z/__init__.py") == "__init__.py"


def test_basename_for_uri_falls_back_to_full_uri_on_no_separator() -> None:
    # Defensive: malformed URIs without a `/` still produce a non-empty label.
    assert _basename_for_uri("untitled") == "untitled"


# --- fetch_preview_line: open-buffer fast path -----------------------


class _FakeBuffer:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def get_iter_at_line(self, line: int) -> str:
        return f"@{line}"

    def get_iter_at_line_offset(self, line: int, _offset: int) -> str:
        return f"@{line}+0"

    def get_line_count(self) -> int:
        return len(self._lines)

    def get_text(self, start: str, _end: str, _include_hidden: bool) -> str:
        # `start` is `@N`, return that line's text.
        n = int(str(start).lstrip("@"))
        if 0 <= n < len(self._lines):
            return self._lines[n]
        return ""

    def get_end_iter(self) -> str:
        return f"@{len(self._lines)}"

    def get_file(self) -> Any:
        class _F:
            def get_location(_self) -> Any:
                class _L:
                    def get_uri(__self) -> str:
                        return "file:///open.py"
                return _L()
        return _F()


class _FakeWindow:
    def __init__(self, docs: list[Any]) -> None:
        self._docs = docs

    def get_documents(self) -> list[Any]:
        return self._docs


def test_preview_from_open_buffer_uses_buffer_text() -> None:
    buf = _FakeBuffer(["line zero", "line one  ", "    line two with leading ws"])
    window = _FakeWindow([buf])
    assert fetch_preview_line("file:///open.py", 0, window) == "line zero"
    assert fetch_preview_line("file:///open.py", 1, window) == "line one  "
    # lstrip applies — verify
    assert fetch_preview_line("file:///open.py", 2, window) == "line two with leading ws"


def test_preview_from_open_buffer_returns_empty_on_out_of_range() -> None:
    buf = _FakeBuffer(["only line"])
    window = _FakeWindow([buf])
    assert fetch_preview_line("file:///open.py", 99, window) == ""


# --- fetch_preview_line: disk fallback -------------------------------


def test_preview_from_disk_when_no_open_buffer(tmp_path: Any) -> None:
    f = tmp_path / "a.py"
    f.write_text("zero\n  one\ntwo\n", encoding="utf-8")
    window = _FakeWindow([])  # no open buffers
    uri = f"file://{f}"
    assert fetch_preview_line(uri, 0, window) == "zero"
    assert fetch_preview_line(uri, 1, window) == "one"  # lstrip
    assert fetch_preview_line(uri, 2, window) == "two"


def test_preview_from_disk_returns_empty_on_out_of_range(tmp_path: Any) -> None:
    f = tmp_path / "a.py"
    f.write_text("zero\n", encoding="utf-8")
    window = _FakeWindow([])
    assert fetch_preview_line(f"file://{f}", 99, window) == ""


def test_preview_from_disk_returns_empty_on_unreadable_file(tmp_path: Any) -> None:
    window = _FakeWindow([])
    # File doesn't exist — Path.read_text raises FileNotFoundError.
    assert fetch_preview_line(
        f"file://{tmp_path}/never-created.py", 0, window
    ) == ""


def test_preview_truncates_long_lines() -> None:
    long = "x" * 200
    buf = _FakeBuffer([long])
    window = _FakeWindow([buf])
    out = fetch_preview_line("file:///open.py", 0, window)
    assert len(out) <= 121  # 120 chars + ellipsis
    assert out.endswith("…")


# --- panel: store mutation --------------------------------------------


def test_set_results_empty_clears_store() -> None:
    panel = _panel_with_rows([
        ["a.py", 1, "preview", "file:///a.py", 0],
    ])
    panel.set_results([])
    assert list(panel._store) == []


def test_set_results_populates_in_order() -> None:
    panel = _panel_with_rows([])
    panel._window = _FakeWindow([])  # disk-fallback path; will return ""
    panel.set_results([
        {"uri": "file:///a.py",
         "range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 3}}},
        {"uri": "file:///b.py",
         "range": {"start": {"line": 9, "character": 4},
                   "end":   {"line": 9, "character": 7}}},
    ])
    rows = list(panel._store)
    assert len(rows) == 2
    assert rows[0][0] == "a.py"
    assert rows[0][1] == 1   # 1-based display
    assert rows[0][3] == "file:///a.py"
    assert rows[0][4] == 0
    assert rows[1][0] == "b.py"
    assert rows[1][1] == 10
    assert rows[1][3] == "file:///b.py"
    assert rows[1][4] == 4


def test_set_results_clears_prior_results() -> None:
    panel = _panel_with_rows([
        ["old.py", 1, "stale", "file:///old.py", 0],
    ])
    panel._window = _FakeWindow([])
    panel.set_results([
        {"uri": "file:///new.py",
         "range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 0}}},
    ])
    rows = list(panel._store)
    assert len(rows) == 1
    assert rows[0][3] == "file:///new.py"


def test_clear_empties_store() -> None:
    panel = _panel_with_rows([
        ["a.py", 1, "preview", "file:///a.py", 0],
        ["b.py", 2, "preview", "file:///b.py", 0],
    ])
    panel.clear()
    assert list(panel._store) == []
```

- [ ] **Step 2.2: Run the new tests to verify they fail**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_references_panel.py -v`

Expected: collection error or `ModuleNotFoundError: No module named 'gedit_lsp.ui.references_panel'`.

- [ ] **Step 2.3: Implement `src/gedit_lsp/ui/references_panel.py`**

```python
"""Bottom-panel "LSP References" tab: list of textDocument/references hits.

Mirrors `DiagnosticsPanel` (TreeView over a ListStore with hidden URI
and UTF-16 character columns), but populated on-demand via
`set_results(...)` rather than continuously updated like diagnostics.

Two pure helpers (`_basename_for_uri`, `fetch_preview_line`) are
exposed at module level so unit tests can exercise them without
instantiating the panel — which needs a real `Gedit.Window` and a
real bottom panel.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # type: ignore[attr-defined]

from gedit_lsp.navigation import navigate_to_uri
from gedit_lsp.utf16 import utf16_to_text_iter

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]


logger = logging.getLogger("gedit_lsp.references_panel")

# Truncate preview text to keep rows compact in narrow bottom panels.
_PREVIEW_MAX_CHARS = 120


def _basename_for_uri(uri: str) -> str:
    """Return the final path segment of a `file://` URI for display.

    Falls back to the full URI if no `/` is present (defensive — shouldn't
    happen with well-formed LSP `Location.uri` values, but guards us
    against crashes if a server returns something exotic).
    """
    if "/" not in uri:
        return uri
    return uri.rsplit("/", 1)[1]


def fetch_preview_line(uri: str, line: int, window: Any) -> str:
    """Best-effort source preview for `(uri, line)`.

    Strategy:
      1. If a `Gedit.Document` matching `uri` is currently open in
         `window`, read the line from the buffer (respects unsaved
         edits, no disk I/O).
      2. Else, read the file from disk synchronously.
      3. On any error (binary file, permission denied, line out of
         range, decode failure surviving `errors="replace"`), return
         `""`. The caller renders the row regardless.

    Result is `lstrip()`'d and truncated to `_PREVIEW_MAX_CHARS` with
    a trailing `…`.
    """
    text = _line_from_open_buffer(uri, line, window)
    if text is None:
        text = _line_from_disk(uri, line)
    return _format_preview(text)


def _line_from_open_buffer(uri: str, line: int, window: Any) -> str | None:
    try:
        docs = window.get_documents()
    except Exception:
        return None
    for doc in docs:
        try:
            doc_uri = doc.get_file().get_location().get_uri()
        except Exception:
            continue
        if doc_uri != uri:
            continue
        try:
            if line < 0 or line >= doc.get_line_count():
                return ""
            start = doc.get_iter_at_line(line)
            # End of line N is the start of line N+1 (or end-of-buffer).
            if line + 1 < doc.get_line_count():
                end = doc.get_iter_at_line(line + 1)
            else:
                end = doc.get_end_iter()
            return doc.get_text(start, end, False).rstrip("\n")
        except Exception:
            return ""
    return None


def _line_from_disk(uri: str, line: int) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return ""
    path = Path(unquote(parsed.path))
    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return ""
    return lines[line]


def _format_preview(text: str) -> str:
    out = text.lstrip()
    if len(out) > _PREVIEW_MAX_CHARS:
        out = out[:_PREVIEW_MAX_CHARS] + "…"
    return out


class ReferencesPanel:
    """Bottom-panel "LSP References" tab.

    Single-source: the controller calls `set_results()` once per
    `textDocument/references` response. Repeated calls replace the
    previous content. The panel persists across plugin
    deactivation/reactivation — same convention as `DiagnosticsPanel`.
    """

    COL_FILE = 0
    COL_LINE = 1
    COL_PREVIEW = 2
    COL_URI = 3
    COL_CHAR = 4

    def __init__(self, window: Gedit.Window) -> None:
        self._window = window
        self._store = Gtk.ListStore(str, int, str, str, int)  # type: ignore[call-arg]
        self._view = Gtk.TreeView(model=self._store)
        for i, title in enumerate(["File", "Line", "Preview"]):
            col = Gtk.TreeViewColumn(  # type: ignore[call-arg, arg-type]
                title, Gtk.CellRendererText(), text=i,
            )
            self._view.append_column(col)
        self._view.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self._view)  # type: ignore[attr-defined]
        scrolled.show_all()  # type: ignore[attr-defined]
        panel = window.get_bottom_panel()
        panel.add_titled(scrolled, "lsp-references", "LSP References")
        self._scrolled = scrolled

    def set_results(self, locations: list[dict[str, Any]]) -> None:
        """Replace the panel contents with rows for `locations`.

        Each location dict is the LSP `Location` shape: `{"uri": ...,
        "range": {"start": {"line": int, "character": int}, ...}}`.
        Preview text is fetched per-row via `fetch_preview_line`.
        """
        self.clear()
        for loc in locations:
            uri = loc["uri"]
            line = loc["range"]["start"]["line"]
            char = loc["range"]["start"]["character"]
            self._store.append([  # type: ignore[no-untyped-call]
                _basename_for_uri(uri),
                line + 1,                                # 1-based for display
                fetch_preview_line(uri, line, self._window),
                uri,
                char,
            ])

    def clear(self) -> None:
        self._store.clear()  # type: ignore[no-untyped-call]

    def reveal(self) -> None:
        """Make the bottom panel visible and select this tab."""
        panel = self._window.get_bottom_panel()
        try:
            panel.set_visible(True)
        except Exception:
            pass
        try:
            panel.set_visible_child_name("lsp-references")
        except Exception:
            # Older libgedit-tepl may use a different selection API; the
            # tab is still added and reachable manually.
            pass

    def _on_row_activated(
        self,
        _view: Gtk.TreeView,
        path: Gtk.TreePath,
        _column: Gtk.TreeViewColumn,
    ) -> None:
        it = self._store.get_iter(path)  # type: ignore[no-untyped-call]
        uri = self._store.get_value(it, self.COL_URI)
        line = self._store.get_value(it, self.COL_LINE) - 1  # back to 0-based
        char_utf16 = self._store.get_value(it, self.COL_CHAR)
        logger.info(
            "references-panel: navigate uri=%s line=%d char=%d",
            uri, line, char_utf16,
        )
        navigate_to_uri(
            self._window, uri, line, char_utf16,
            to_iter=lambda buf: utf16_to_text_iter(buf, line, char_utf16),
        )
```

- [ ] **Step 2.4: Run all unit tests**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass, including the new `test_references_panel.py` cases. If a `_FakeBuffer.get_text` mismatch surfaces, re-check the `start`/`end` iter contract — the production code reads with `(start, end, include_hidden=False)`; the fake honors that signature.

- [ ] **Step 2.5: Commit**

```bash
git add src/gedit_lsp/ui/references_panel.py tests/unit/test_references_panel.py
git commit -m "$(cat <<'EOF'
feat(references): bottom-panel ReferencesPanel + preview helpers

Adds the "LSP References" bottom-panel tab modelled on
DiagnosticsPanel: TreeView over a ListStore with hidden URI/UTF-16
columns, row-activated -> navigate_to_uri. set_results() replaces
prior content; preview text per row is fetched best-effort from any
matching open buffer first, then disk, returning "" on error.

The two pure helpers (_basename_for_uri, fetch_preview_line) are
module-level so unit tests can drive them without a real
Gedit.Window / bottom panel — the panel itself is exercised via the
__new__ bypass pattern from test_diagnostics_panel.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `ReferencesController` + unit tests

**Files:**
- Create: `src/gedit_lsp/features/references.py`
- Create: `tests/unit/test_references_controller.py`

The controller is window-scoped (one per gedit window, like `DefinitionController`). The panel is injected. The cursor position, server, URI, and `flush_pending_change` come in at trigger time so the controller doesn't hold per-doc state.

- [ ] **Step 3.1: Write `tests/unit/test_references_controller.py`**

```python
"""Unit tests for ReferencesController.

The controller is window-scoped and stateless beyond a panel reference.
trigger() is the entire surface: capture cursor, flush, send, dispatch.

Tests cover:
  - 0/1/N dispatch (none -> statusbar, single -> navigate, many -> panel)
  - flush_pending_change called BEFORE _send_request (edit-flush invariant)
  - capability gate: server without `referencesProvider` -> no request
  - request payload shape: textDocument.uri, position, includeDeclaration

No real GTK widgets — view, buffer, statusbar, window are all fakes/mocks.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from gedit_lsp.features.references import ReferencesController


class _FakeStatusbar:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def push(self, ctx: int, msg: str) -> None:
        self.messages.append((ctx, msg))


class _FakeBuffer:
    """Sufficient subset of Gtk.TextBuffer to drive text_iter_to_utf16.

    text_iter_to_utf16 calls iter.get_buffer().get_iter_at_line(line)
    then buffer.get_text(line_start, iter, False), so iters need to know
    their owning buffer.
    """

    def __init__(self, line: int, char: int, line_text: str = "x" * 100) -> None:
        self._line_text = line_text
        self._cursor_iter = _FakeIter(self, line, char)

    def get_iter_at_mark(self, _mark: Any) -> "_FakeIter":
        return self._cursor_iter

    def get_insert(self) -> Any:
        return object()

    def get_iter_at_line(self, line: int) -> "_FakeIter":
        return _FakeIter(self, line, 0)

    def get_text(
        self, start: "_FakeIter", end: "_FakeIter", _hidden: bool
    ) -> str:
        return self._line_text[start.get_line_offset():end.get_line_offset()]


class _FakeIter:
    """Stand-in for Gtk.TextIter, sufficient for text_iter_to_utf16.

    Default `_line_text="x" * 100` keeps `get_text(line_start, iter)`
    returning a string at least as long as the iter's line offset, so a
    cursor at (line=7, char=3) round-trips through text_iter_to_utf16 to
    (7, 3) without forcing each test to spell out a line of source code.
    """

    def __init__(self, buf: _FakeBuffer, line: int, line_offset: int) -> None:
        self._buf = buf
        self._line = line
        self._line_offset = line_offset

    def get_buffer(self) -> _FakeBuffer:
        return self._buf

    def get_line(self) -> int:
        return self._line

    def get_line_offset(self) -> int:
        return self._line_offset


class _FakeView:
    def __init__(self, buf: _FakeBuffer) -> None:
        self._buf = buf

    def get_buffer(self) -> _FakeBuffer:
        return self._buf


class _FakeWindow:
    def __init__(self, view: _FakeView, statusbar: _FakeStatusbar) -> None:
        self._view = view
        self._statusbar = statusbar

    def get_active_view(self) -> _FakeView:
        return self._view

    def get_statusbar(self) -> _FakeStatusbar:
        return self._statusbar


class _FakeServer:
    def __init__(
        self, *, has_references: bool = True,
    ) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self._has_references = has_references

    def capability(self, key: str) -> Any:
        if key == "referencesProvider":
            return self._has_references
        return None

    def _send_request(
        self, method: str, params: dict[str, Any], _cb: Any
    ) -> int:
        self.requests.append((method, params))
        return len(self.requests)


def _build(
    *,
    server: _FakeServer | None = None,
    cursor: tuple[int, int] = (0, 0),
) -> tuple[ReferencesController, _FakeServer, _FakeStatusbar, MagicMock]:
    server = server or _FakeServer()
    statusbar = _FakeStatusbar()
    view = _FakeView(_FakeBuffer(cursor[0], cursor[1]))
    window = _FakeWindow(view, statusbar)
    panel = MagicMock()
    ctrl = ReferencesController(window=window, panel=panel)
    return ctrl, server, statusbar, panel


def _trigger(
    ctrl: ReferencesController,
    server: _FakeServer,
    *,
    flush: Any = None,
) -> None:
    flush = flush or (lambda: None)
    ctrl.trigger(server, "file:///x.py", flush)


# --- 0/1/N dispatch ---------------------------------------------------


def test_none_result_pushes_statusbar_message() -> None:
    ctrl, server, statusbar, panel = _build()
    captured: list[Any] = []

    def fake_send(method: str, params: dict[str, Any], cb: Any) -> int:
        captured.append(cb)
        server.requests.append((method, params))
        return 1

    server._send_request = fake_send  # type: ignore[method-assign]
    _trigger(ctrl, server)
    captured[0]({"result": None})  # server replies "no references"
    assert any("no references" in m.lower() for _ctx, m in statusbar.messages)
    panel.set_results.assert_not_called()


def test_single_result_navigates_directly(monkeypatch: Any) -> None:
    nav_calls: list[tuple[Any, ...]] = []

    def fake_navigate(*args: Any, **kwargs: Any) -> None:
        nav_calls.append((args, kwargs))

    monkeypatch.setattr(
        "gedit_lsp.features.references.navigate_to_uri", fake_navigate
    )

    ctrl, server, _statusbar, panel = _build()
    captured: list[Any] = []
    server._send_request = lambda m, p, cb: (  # type: ignore[method-assign]
        captured.append(cb), server.requests.append((m, p)), 1
    )[-1]

    _trigger(ctrl, server)
    captured[0]({
        "result": [
            {"uri": "file:///a.py",
             "range": {"start": {"line": 4, "character": 2},
                       "end":   {"line": 4, "character": 5}}},
        ]
    })

    assert len(nav_calls) == 1
    args, kwargs = nav_calls[0]
    # Expect navigate_to_uri(window, uri, line, char_utf16, to_iter=...)
    assert args[1] == "file:///a.py"
    assert args[2] == 4
    assert args[3] == 2
    panel.set_results.assert_not_called()


def test_many_results_populate_panel(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "gedit_lsp.features.references.navigate_to_uri",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not navigate on multi-result")
        ),
    )

    ctrl, server, _statusbar, panel = _build()
    captured: list[Any] = []
    server._send_request = lambda m, p, cb: (  # type: ignore[method-assign]
        captured.append(cb), server.requests.append((m, p)), 1
    )[-1]

    _trigger(ctrl, server)
    locs = [
        {"uri": "file:///a.py",
         "range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 1}}},
        {"uri": "file:///b.py",
         "range": {"start": {"line": 1, "character": 0},
                   "end":   {"line": 1, "character": 1}}},
    ]
    captured[0]({"result": locs})

    panel.set_results.assert_called_once_with(locs)
    panel.reveal.assert_called_once()


# --- flush invariant --------------------------------------------------


def test_flush_called_before_send_request() -> None:
    ctrl, server, _statusbar, _panel = _build()
    log: list[str] = []

    def flush() -> None:
        log.append(f"flush@{len(server.requests)}")

    _trigger(ctrl, server, flush=flush)

    # At the moment flush ran, no requests had been sent.
    assert log == ["flush@0"]
    assert len(server.requests) == 1


# --- capability gate --------------------------------------------------


def test_capability_gate_blocks_when_unsupported() -> None:
    server = _FakeServer(has_references=False)
    ctrl, server, statusbar, panel = _build(server=server)
    _trigger(ctrl, server)
    assert server.requests == []
    panel.set_results.assert_not_called()
    assert any(
        "does not support references" in m.lower()
        for _ctx, m in statusbar.messages
    )


# --- payload shape ----------------------------------------------------


def test_request_payload_shape() -> None:
    ctrl, server, _statusbar, _panel = _build(cursor=(7, 3))
    _trigger(ctrl, server)
    assert len(server.requests) == 1
    method, params = server.requests[0]
    assert method == "textDocument/references"
    assert params["textDocument"] == {"uri": "file:///x.py"}
    assert params["position"] == {"line": 7, "character": 3}
    assert params["context"] == {"includeDeclaration": True}
```

- [ ] **Step 3.2: Run the new tests to verify they fail**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_references_controller.py -v`

Expected: collection error or `ModuleNotFoundError: No module named 'gedit_lsp.features.references'`.

- [ ] **Step 3.3: Implement `src/gedit_lsp/features/references.py`**

```python
"""ReferencesController: textDocument/references request + 0/1/N dispatch.

Mirrors `DefinitionController` in shape — window-scoped, stateless
beyond the injected `ReferencesPanel`. `trigger(server, uri,
flush_pending_change)` reads the cursor, flushes any debounced
didChange (the edit-flush invariant), sends the LSP request, and
dispatches the response:

    none   -> status-bar message
    single -> direct navigate_to_uri jump (panel untouched)
    many   -> panel.set_results(locs) + panel.reveal()
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gedit_lsp.navigation import classify_locations, navigate_to_uri
from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]

    from gedit_lsp.server import LanguageServer
    from gedit_lsp.ui.references_panel import ReferencesPanel


logger = logging.getLogger("gedit_lsp.references")


class ReferencesController:
    def __init__(
        self,
        *,
        window: Gedit.Window,
        panel: ReferencesPanel,
    ) -> None:
        self._window = window
        self._panel = panel

    def trigger(
        self,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None],
    ) -> None:
        """Send `textDocument/references` for the cursor position in
        `uri`. Caller passes `flush_pending_change` (typically
        `bridge.flush_pending_change`) so this controller doesn't need
        to know about the bridge layer.
        """
        statusbar = self._window.get_statusbar()

        # Capability gate: skip the round-trip when the server has
        # already told us it can't help.
        if not server.capability("referencesProvider"):
            logger.info("references: server does not support referencesProvider")
            statusbar.push(0, "LSP: server does not support references")
            return

        view = self._window.get_active_view()
        if view is None:
            logger.info("references: no active view")
            return
        buf = view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line, char = text_iter_to_utf16(cursor)

        # Edit-flush invariant: ensure the server has the latest text.
        flush_pending_change()

        params: dict[str, Any] = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
            "context": {"includeDeclaration": True},
        }

        def on_response(msg: dict[str, Any]) -> None:
            if msg.get("error"):
                logger.info("references: server error %r", msg.get("error"))
                statusbar.push(0, "LSP: references request failed")
                return
            kind, locs = classify_locations(msg.get("result"))
            if kind == "none":
                statusbar.push(0, "LSP: no references found")
                return
            if kind == "single":
                loc = locs[0]
                tgt_line = loc["range"]["start"]["line"]
                tgt_char = loc["range"]["start"]["character"]
                navigate_to_uri(
                    self._window, loc["uri"], tgt_line, tgt_char,
                    to_iter=lambda buf: utf16_to_text_iter(
                        buf, tgt_line, tgt_char
                    ),
                )
                return
            # many
            self._panel.set_results(locs)
            self._panel.reveal()

        logger.info("references: send line=%d char=%d", line, char)
        server._send_request("textDocument/references", params, on_response)
```

- [ ] **Step 3.4: Run all unit tests**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass.

- [ ] **Step 3.5: Mutation-test the flush invariant**

Per project practice (memory: `feedback_mutation_test_invariants`), break the production line, watch the test fail, restore. Total: ~10s.

```bash
sed -i 's/flush_pending_change()/# flush_pending_change()/' src/gedit_lsp/features/references.py
env -u PYTHONPATH python -m pytest tests/unit/test_references_controller.py::test_flush_called_before_send_request -v
# Expected: FAIL with assert log == ["flush@0"]
git checkout -- src/gedit_lsp/features/references.py
env -u PYTHONPATH python -m pytest tests/unit/test_references_controller.py::test_flush_called_before_send_request -v
# Expected: PASS
```

- [ ] **Step 3.6: Mutation-test the capability gate**

```bash
# Strip the capability gate block via plain string replace (regex over
# multi-line code is too fragile for a quick mutation test).
python -c "
import pathlib
p = pathlib.Path('src/gedit_lsp/features/references.py')
src = p.read_text()
old = '''        if not server.capability(\"referencesProvider\"):
            logger.info(\"references: server does not support referencesProvider\")
            statusbar.push(0, \"LSP: server does not support references\")
            return
'''
patched = src.replace(old, '', 1)
assert patched != src, 'patch did not apply — adjust string above'
p.write_text(patched)
"
env -u PYTHONPATH python -m pytest tests/unit/test_references_controller.py::test_capability_gate_blocks_when_unsupported -v
# Expected: FAIL — server.requests is no longer empty
git checkout -- src/gedit_lsp/features/references.py
env -u PYTHONPATH python -m pytest tests/unit/test_references_controller.py::test_capability_gate_blocks_when_unsupported -v
# Expected: PASS
```

- [ ] **Step 3.7: Commit**

```bash
git add src/gedit_lsp/features/references.py tests/unit/test_references_controller.py
git commit -m "$(cat <<'EOF'
feat(references): ReferencesController with 0/1/N dispatch

Window-scoped controller mirroring DefinitionController.
trigger(server, uri, flush_pending_change) reads the cursor,
flushes any debounced didChange (edit-flush invariant), sends
textDocument/references with includeDeclaration=true, and dispatches
the response: none -> statusbar; single -> direct navigate_to_uri
jump; many -> panel.set_results + reveal.

Capability gate (`server.capability("referencesProvider")`) avoids
a wasted round-trip on servers that don't advertise the provider.

Mutation-tested: breaking the flush call fails the order-asserting
test; bypassing the capability gate fails the gate test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Plugin wiring (action, accel, popup-menu, panel/controller)

**Files:**
- Modify: `src/gedit_lsp/ui/popup_menu.py:23-29` (add `MENU_ITEMS` row)
- Modify: `tests/unit/test_popup_menu.py` (add a test for the new entry)
- Modify: `src/gedit_lsp/plugin.py` (imports, construction, action wiring, handler)

The popup-menu addition is simple and unit-testable; the `plugin.py` wiring is exercised primarily by manual smoke-testing per project convention (no plugin-lifecycle unit tests today).

- [ ] **Step 4.1: Add a popup-menu test for the new entry**

In `tests/unit/test_popup_menu.py`, append:

```python


def test_menu_items_includes_find_references() -> None:
    """The right-click LSP submenu must surface Find References mapped to
    the win.lsp-references action so users without the keyboard accel
    can still discover the feature."""
    assert ("Find References", "lsp-references") in popup_menu.MENU_ITEMS
```

- [ ] **Step 4.2: Run the new test to verify it fails**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_popup_menu.py::test_menu_items_includes_find_references -v`

Expected: FAIL with `AssertionError` — the entry isn't in `MENU_ITEMS` yet.

- [ ] **Step 4.3: Add the entry to `MENU_ITEMS`**

In `src/gedit_lsp/ui/popup_menu.py`, replace:

```python
MENU_ITEMS: list[tuple[str, str]] = [
    ("Show Hover",        "lsp-hover"),
    ("Go to Definition",  "lsp-goto-definition"),
    ("Go Back",           "lsp-go-back"),
    ("Format",            "lsp-format"),
    ("Show Server Logs…", "lsp-show-server-logs"),
]
```

with:

```python
MENU_ITEMS: list[tuple[str, str]] = [
    ("Show Hover",        "lsp-hover"),
    ("Go to Definition",  "lsp-goto-definition"),
    ("Go Back",           "lsp-go-back"),
    ("Find References",   "lsp-references"),
    ("Format",            "lsp-format"),
    ("Show Server Logs…", "lsp-show-server-logs"),
]
```

- [ ] **Step 4.4: Run popup-menu tests to verify they pass**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_popup_menu.py -v`

Expected: all pass.

- [ ] **Step 4.5: Wire `plugin.py`**

Three edits in `src/gedit_lsp/plugin.py`:

**Edit 5a — imports.** Add after the existing `from gedit_lsp.features.outline import OutlineController` line:

```python
from gedit_lsp.features.references import ReferencesController
```

And after `from gedit_lsp.ui.diagnostics_panel import DiagnosticsPanel`:

```python
from gedit_lsp.ui.references_panel import ReferencesPanel
```

**Edit 5b — construct panel + controller in `do_activate`.** Find the existing block:

```python
        self._diag_panel = DiagnosticsPanel(win)
        self._crash_notifier = CrashNotifier(win)
```

Replace with:

```python
        self._diag_panel = DiagnosticsPanel(win)
        self._references_panel = ReferencesPanel(win)
        self._references_ctrl = ReferencesController(
            window=win, panel=self._references_panel,
        )
        self._crash_notifier = CrashNotifier(win)
```

**Edit 5c — register the action.** Find the existing actions list:

```python
        for name, config_key, handler in [
            ("lsp-hover", "hover", self._on_hover_activate),
            ("lsp-goto-definition", "goto-definition", self._on_definition_activate),
            ("lsp-go-back", "go-back", self._on_go_back_activate),
            ("lsp-show-server-logs", "show-server-logs", self._on_show_server_logs_activate),
            ("lsp-format", "format", self._on_format_activate),
        ]:
```

Replace with (one new row):

```python
        for name, config_key, handler in [
            ("lsp-hover", "hover", self._on_hover_activate),
            ("lsp-goto-definition", "goto-definition", self._on_definition_activate),
            ("lsp-go-back", "go-back", self._on_go_back_activate),
            ("lsp-references", "references", self._on_references_activate),
            ("lsp-show-server-logs", "show-server-logs", self._on_show_server_logs_activate),
            ("lsp-format", "format", self._on_format_activate),
        ]:
```

**Edit 5d — add the handler.** After the existing `_on_definition_activate` and `_on_go_back_activate` methods, add:

```python
    def _on_references_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("references action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("references: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "references: doc not bridged (bridge=%s server=%s)",
                bridge, server,
            )
            return
        logger.info("references: triggering, server.state=%s", server.state)
        self._references_ctrl.trigger(
            server, bridge.uri, bridge.flush_pending_change,
        )
```

(No `do_deactivate` change is needed — `ReferencesPanel` follows the `DiagnosticsPanel` convention of persisting for the gedit window's lifetime; it has no per-tab listener disposers.)

- [ ] **Step 4.6: Run the full unit test suite**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass. Imports in `plugin.py` are exercised by `test_typelib_versions.py` indirectly; if the module fails to import, that test surfaces it.

- [ ] **Step 4.7: Lint + typecheck**

Run: `python -m ruff check src tests`
Expected: clean.

Run: `python -m mypy src`
Expected: clean (or only the same warnings the project already tolerates).

- [ ] **Step 4.8: Manual smoke test in gedit**

```bash
./install.sh
# Restart gedit (close all windows; relaunch from the activities/applications)
```

In a running gedit, with a Python file open and pylsp attached:

1. Place the cursor on a function name with multiple usages (e.g. `flush_pending_change` in `src/gedit_lsp/bridge.py`).
2. Press **Ctrl+Shift+F12**.
3. **Expected:** the bottom panel reveals the "LSP References" tab with one row per usage; clicking a row jumps to that file/line.
4. Right-click → **LSP → Find References** triggers the same.
5. With the cursor on something that has no usages (e.g. an unused local), the statusbar shows `LSP: no references found`.
6. Verify the accel registered cleanly: `tail -n 50 ~/.local/state/gedit-lsp/plugin.log | grep lsp-references`. Expected line:
   ```
   registered action win.lsp-references accels=['<Primary><Shift>F12']
   ```
   Any "no application" warning means the accel didn't bind; treat as a blocker before merging.

- [ ] **Step 4.9: Commit**

```bash
git add src/gedit_lsp/plugin.py \
        src/gedit_lsp/ui/popup_menu.py \
        tests/unit/test_popup_menu.py
git commit -m "$(cat <<'EOF'
feat(references): wire action, accel, panel, popup-menu entry

Constructs ReferencesPanel + ReferencesController in do_activate,
registers win.lsp-references with the configured accel, adds the
"Find References" entry to the right-click LSP submenu, and routes
the action to bridge.flush_pending_change + controller.trigger so
the edit-flush invariant is upheld at the call site (matches the
definition / format / signatureHelp wiring shape).

Panel persists for the window's lifetime — same convention as
DiagnosticsPanel; no extra teardown in do_deactivate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Defaults + configure docs

**Files:**
- Modify: `src/gedit_lsp/defaults.py:33-39` (DEFAULT_KEYBINDINGS), `:57-60` (enabledFeatures)
- Modify: `docs/configure.md:65-77` (keybindings table)

- [ ] **Step 5.1: Add the keybinding default**

In `src/gedit_lsp/defaults.py`, replace:

```python
DEFAULT_KEYBINDINGS: dict[str, list[str]] = {
    "hover":            ["<Primary>k"],
    "goto-definition":  ["F12"],
    "go-back":          ["<Shift>F12"],
    "show-server-logs": [],
    "format":           ["<Primary><Shift>i"],
}
```

with:

```python
DEFAULT_KEYBINDINGS: dict[str, list[str]] = {
    "hover":            ["<Primary>k"],
    "goto-definition":  ["F12"],
    "go-back":          ["<Shift>F12"],
    "references":       ["<Primary><Shift>F12"],
    "show-server-logs": [],
    "format":           ["<Primary><Shift>i"],
}
```

- [ ] **Step 5.2: Add references to the default `enabledFeatures` list**

In `src/gedit_lsp/defaults.py`, replace:

```python
    "enabledFeatures": [
        "diagnostics", "hover", "definition", "outline",
        "completion", "signatureHelp", "formatting",
    ],
```

with:

```python
    "enabledFeatures": [
        "diagnostics", "hover", "definition", "outline",
        "completion", "signatureHelp", "formatting", "references",
    ],
```

- [ ] **Step 5.3: Document the keybinding in `docs/configure.md`**

In `docs/configure.md`, locate the keybindings table (the section starting with `| Action | Default | Meaning |`). Replace the existing rows:

```markdown
| Action | Default | Meaning |
|---|---|---|
| `hover` | `<Primary>k` | Show the hover popover at the cursor |
| `goto-definition` | `F12` | Jump to the definition of the symbol at the cursor |
| `go-back` | `<Shift>F12` | Return to the previous cursor position |
| `show-server-logs` | (none) | Open a dialog showing recent stderr from the active document's language server |
| `format` | `<Primary><Shift>i` | Format the document (or the selection if any) via the server |
```

with:

```markdown
| Action | Default | Meaning |
|---|---|---|
| `hover` | `<Primary>k` | Show the hover popover at the cursor |
| `goto-definition` | `F12` | Jump to the definition of the symbol at the cursor |
| `go-back` | `<Shift>F12` | Return to the previous cursor position |
| `references` | `<Primary><Shift>F12` | List all references to the symbol at the cursor in the bottom panel |
| `show-server-logs` | (none) | Open a dialog showing recent stderr from the active document's language server |
| `format` | `<Primary><Shift>i` | Format the document (or the selection if any) via the server |
```

- [ ] **Step 5.4: Run the full unit test suite**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass. (`test_config.py` exercises defaults shape; if anything regresses there, fix and re-run.)

- [ ] **Step 5.5: Commit**

```bash
git add src/gedit_lsp/defaults.py docs/configure.md
git commit -m "$(cat <<'EOF'
feat(references): add references to defaults + document keybinding

Default accel is <Primary><Shift>F12 (Ctrl+Shift+F12) — VS Code's
"Find All References" precedent; joins the F12 family with our
goto-definition (F12) and go-back (Shift+F12). F7 / Shift+F7 were
rejected because gedit binds them to Toggle Cursor Visibility and
Check Spelling respectively.

"references" added to enabledFeatures list for completeness; matches
the discovery pattern used for "definition", "diagnostics", etc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Mark protocol-coverage and open the PR

**Files:**
- Modify: `docs/protocol-coverage.md` (add the references row to the LSP method table)

- [ ] **Step 6.1: Add the protocol-coverage row**

In `docs/protocol-coverage.md`, locate the table. Add a row immediately after the existing `textDocument/rangeFormatting` row:

```markdown
| `textDocument/references` (Ctrl+Shift+F12; many → "LSP References" bottom panel) | ✓ |
```

The full table now reads (relevant section, for orientation):

```markdown
| `textDocument/formatting` (Ctrl+Shift+I; whole document) | ✓ |
| `textDocument/rangeFormatting` (Ctrl+Shift+I with selection) | ✓ |
| `textDocument/references` (Ctrl+Shift+F12; many → "LSP References" bottom panel) | ✓ |
```

- [ ] **Step 6.2: Final full test run**

```bash
env -u PYTHONPATH python -m pytest tests/unit
python -m ruff check src tests
python -m mypy src
```

All three must pass cleanly.

- [ ] **Step 6.3: Commit the docs update**

```bash
git add docs/protocol-coverage.md
git commit -m "$(cat <<'EOF'
docs(coverage): mark textDocument/references shipped

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6.4: Push the branch and open the PR**

```bash
git push -u origin feat/references
gh pr create --title "feat(references): textDocument/references" --body "$(cat <<'EOF'
## Summary

- `textDocument/references` with Ctrl+Shift+F12 keybinding and a right-click "Find References" entry
- Bottom-panel "LSP References" tab modelled on `DiagnosticsPanel` — file / line / preview columns, click row to jump
- 0/1/N dispatch via `classify_locations()` (relocated from `features/definition.py` to `navigation.py` so references and definition share it)
- Edit-flush invariant upheld: `bridge.flush_pending_change()` runs before `_send_request`, mutation-tested in unit suite

## Spec / plan

- Spec: `docs/superpowers/specs/2026-05-09-textdocument-references-design.md`
- Plan: `docs/superpowers/plans/2026-05-09-textdocument-references.md`

## Test plan

- [ ] `make test` passes (full unit suite)
- [ ] Linked plugin in gedit, opened a Python file with pylsp attached, placed cursor on a function with several usages
- [ ] Ctrl+Shift+F12 reveals the "LSP References" bottom-panel tab populated with rows
- [ ] Clicking a row navigates to that file:line; cursor lands on the matched character offset
- [ ] Single-result symbol jumps directly without opening the panel
- [ ] Symbol with no usages shows `LSP: no references found` in the statusbar
- [ ] Right-click → LSP → Find References triggers the same flow
- [ ] `~/.local/state/gedit-lsp/plugin.log` contains a `registered action win.lsp-references accels=['<Primary><Shift>F12']` line

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After PR open, monitor CI (`gh pr checks --watch`). Address any failures with follow-up commits on the same branch.

---

## Self-review notes

(Filled in by the plan author after writing — engineer should not need to consult these.)

- **Spec coverage check:** every section of the spec maps to a task. UX → Task 4 (popup) + Task 5 (configure docs); Architecture → Tasks 2-4; Edge cases → covered in unit tests in Tasks 2-3; Configuration → Task 5; Testing → Tasks 1-3 (unit) + Task 4 (smoke); Implementation sequence → Tasks 1-6 in order.
- **Placeholder scan:** no TBD/TODO/"add appropriate error handling" remain. Every code block is concrete.
- **Type consistency:** `ReferencesController.trigger(server, uri, flush_pending_change)` matches across the controller def (Task 3), the test calls (Task 3), and the plugin handler call (Task 4). `ReferencesPanel.set_results(locations)` matches the controller's call site. Column constants (COL_*) referenced consistently in both the panel and its tests.
- **Mutation tests:** baked into Task 3 (steps 3.5, 3.6) per project practice.
