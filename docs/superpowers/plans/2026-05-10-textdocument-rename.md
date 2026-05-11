# textDocument/rename + prepareRename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `textDocument/rename` (and the optional `prepareRename` companion) to gedit-lsp-plugin. F2 opens a `Gtk.Popover` near the cursor with the symbol pre-selected; on Enter, the server returns a `WorkspaceEdit`; the controller opens any closed files affected, then applies edits across all of them, leaving them dirty for the user to save.

**Architecture:** Three new units. `RenameController` (window-scoped, mirrors `ReferencesController`) orchestrates the trigger flow: capability check → flush pending didChange → optional `prepareRename` → `RenamePopover.show(...)` → on Enter, send `textDocument/rename` → on response, open closed files (async via `Gedit.commands_load_location`), wait for all `loaded` signals, then call `apply_workspace_edit`. `RenamePopover` is a thin `Gtk.Popover` + `Gtk.Entry` widget anchored at the cursor (excluded from automated tests, smoke-tested only). `apply_workspace_edit` + `derive_placeholder` live in a new pure module `workspace_edit.py` and reuse the existing `apply_text_edits` helper from `features/formatting.py` per file.

**Tech Stack:** Python 3.10+, PyGObject (Gtk 3 / GtkSource 300 / Gedit 3.0 typelibs at runtime), pytest for unit tests, `make test` for the test runner (which strips `PYTHONPATH` to dodge the system-wide leak documented in project memory).

**Branch:** `feat/rename` (already created from `main`; spec committed at `53c1ad6`).

---

## File structure

| File | Verb | Responsibility |
|---|---|---|
| `src/gedit_lsp/workspace_edit.py` | create | Pure helpers: `apply_workspace_edit` + `derive_placeholder`. No GTK widgets. |
| `src/gedit_lsp/ui/rename_popover.py` | create | `RenamePopover` widget. `Gtk.Popover` + `Gtk.Entry`, anchored at cursor. Excluded from automated tests. |
| `src/gedit_lsp/features/rename.py` | create | `RenameController` (window-scoped). Module-level test seams `_default_load_uri` and `_default_buffer_for_uri`. |
| `src/gedit_lsp/ui/popup_menu.py` | modify | Add `"Rename Symbol"` entry to `MENU_ITEMS`. |
| `src/gedit_lsp/plugin.py` | modify | Construct controller, register `lsp-rename` action + accel + `_on_rename_activate` handler. |
| `src/gedit_lsp/defaults.py` | modify | Add `"rename"` to `enabledFeatures`; add `"rename": ["F2"]` to `DEFAULT_KEYBINDINGS`. |
| `docs/configure.md` | modify | Add a row to the keybindings table. |
| `docs/protocol-coverage.md` | modify | Mark `textDocument/rename` ✓. |
| `docs/roadmap.md` | modify | Move `textDocument/rename + prepareRename` from v0.4.0 list into shipped section (under v0.4.0 bundle). |
| `tests/unit/test_workspace_edit.py` | create | Unit tests for `apply_workspace_edit` + `derive_placeholder`. No GTK widgets. |
| `tests/unit/test_rename_controller.py` | create | Controller unit tests; capability gate; prepareRename branches; flush-before-send invariant; empty/unchanged newName; rename error/null; WorkspaceEdit dispatch via `apply_workspace_edit`; async load-settle; best-effort partial failure. |
| `tests/unit/test_popup_menu.py` | modify | Add a test ensuring `"Rename Symbol"` is in `MENU_ITEMS` mapped to `lsp-rename`. |

---

## Conventions to follow throughout

- **Run tests with** `env -u PYTHONPATH python -m pytest tests/unit -x` (or `make test`) — the `env -u` is essential, see project memory `bashrc PYTHONPATH leak`.
- **No GTK widgets in unit tests** that need a `DISPLAY`: use `Gtk.ListStore`/`GtkSource.Buffer` (model objects) or `MagicMock()` for view-typed parameters. Constructing `Gtk.Window` / `Gtk.Popover` / `GtkSource.View` SIGTRAPs in headless CI.
- **Edit-flush invariant:** any feature that triggers an LSP request from an edit-position MUST call `flush_pending_change()` BEFORE `_send_request(...)`. Test by capturing `len(server.requests)` inside the flush callable and asserting `flush@0`.
- **Per-task verify gate:** every task's "run tests" step runs **all three** of `pytest`, `ruff check`, and `mypy` — not just pytest. PR #16 lost time accumulating 6 ruff + 6 mypy errors across tasks because the per-task verify was pytest-only. See feedback memory `Per-task verify steps must include ruff + mypy, not just pytest`.
- **Commits:** one commit per task with the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer. HEREDOC the commit body. Do NOT push to origin during this plan — local commits only; PR opens at the end.

---

### Task 1: `workspace_edit.py` module + unit tests

**Files:**
- Create: `src/gedit_lsp/workspace_edit.py`
- Create: `tests/unit/test_workspace_edit.py`

The module hosts two unrelated-but-co-located pure helpers: `apply_workspace_edit` (the LSP `WorkspaceEdit` applier — used by rename now, code-action later) and `derive_placeholder` (the prepareRename fallback — tokenizes the word under the cursor). Both are plain Python with no GTK widget dependencies, so they can be exercised directly without the `__new__` panel-bypass trick.

`apply_workspace_edit` delegates per-file to `apply_text_edits` from `features/formatting.py:72` (already in the codebase, already test-covered for the right-to-left sort + `begin/end_user_action` pattern).

- [ ] **Step 1.1: Write `tests/unit/test_workspace_edit.py`**

```python
"""Unit tests for the workspace_edit module.

Covers two helpers:
  * apply_workspace_edit — walks WorkspaceEdit (preferring documentChanges
    over the older `changes` map), per-file delegates to apply_text_edits.
  * derive_placeholder — regex-based identifier extraction at a cursor
    position; the prepareRename fallback for servers that don't (or won't)
    return a placeholder.

No real GTK widgets; buffers are GtkSource.Buffer model objects (safe in
headless CI per the project-memory invariant) or MagicMocks.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import GtkSource  # type: ignore[attr-defined]

from gedit_lsp.workspace_edit import (
    apply_workspace_edit,
    derive_placeholder,
)


# --- derive_placeholder ----------------------------------------------


def _buf(text: str) -> GtkSource.Buffer:
    buf = GtkSource.Buffer()
    buf.set_text(text, -1)
    return buf


def test_derive_placeholder_returns_identifier_at_cursor() -> None:
    buf = _buf("foo = bar(baz)\n")
    # cursor inside "bar"
    assert derive_placeholder(buf, 0, 7) == "bar"
    # cursor on the leading 'f' of "foo"
    assert derive_placeholder(buf, 0, 0) == "foo"
    # cursor on the closing paren — between identifiers
    assert derive_placeholder(buf, 0, 13) == ""


def test_derive_placeholder_supports_underscored_identifiers() -> None:
    buf = _buf("    _private_var = 1\n")
    assert derive_placeholder(buf, 0, 8) == "_private_var"


def test_derive_placeholder_returns_empty_on_whitespace_or_punctuation() -> None:
    buf = _buf("a = b\n")
    # cursor on the space between 'a' and '='
    assert derive_placeholder(buf, 0, 1) == ""
    # cursor on the '='
    assert derive_placeholder(buf, 0, 2) == ""


def test_derive_placeholder_returns_empty_on_out_of_range_line() -> None:
    buf = _buf("only line\n")
    assert derive_placeholder(buf, 99, 0) == ""
    assert derive_placeholder(buf, -1, 0) == ""


def test_derive_placeholder_works_on_last_line_without_newline() -> None:
    buf = _buf("first\nsecond")  # no trailing newline
    assert derive_placeholder(buf, 1, 0) == "second"


# --- apply_workspace_edit: documentChanges precedence -------------


def test_documentChanges_preferred_over_changes() -> None:
    # If both shapes are present, documentChanges wins.
    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///a.py", "version": 7},
                "edits": [{"range": {
                    "start": {"line": 0, "character": 0},
                    "end":   {"line": 0, "character": 3},
                }, "newText": "NEW"}],
            },
        ],
        "changes": {
            "file:///b.py": [{"range": {
                "start": {"line": 0, "character": 0},
                "end":   {"line": 0, "character": 3},
            }, "newText": "OTHER"}],
        },
    }
    seen: list[str] = []

    def buffer_for_uri(uri: str) -> Any:
        seen.append(uri)
        b = MagicMock()
        return b

    applied, failed = apply_workspace_edit(edit, buffer_for_uri=buffer_for_uri)
    assert applied == ["file:///a.py"]
    assert failed == []
    assert seen == ["file:///a.py"]  # changes map ignored


def test_changes_fallback_when_no_documentChanges() -> None:
    edit = {
        "changes": {
            "file:///a.py": [{"range": {
                "start": {"line": 0, "character": 0},
                "end":   {"line": 0, "character": 3},
            }, "newText": "X"}],
            "file:///b.py": [{"range": {
                "start": {"line": 1, "character": 0},
                "end":   {"line": 1, "character": 3},
            }, "newText": "Y"}],
        }
    }
    seen: list[str] = []

    def buffer_for_uri(uri: str) -> Any:
        seen.append(uri)
        return MagicMock()

    applied, failed = apply_workspace_edit(edit, buffer_for_uri=buffer_for_uri)
    assert sorted(applied) == ["file:///a.py", "file:///b.py"]
    assert failed == []
    assert sorted(seen) == ["file:///a.py", "file:///b.py"]


# --- apply_workspace_edit: per-file failure isolation -------------


def test_uri_not_found_in_lookup_goes_to_failed() -> None:
    edit = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"},
             "edits": [{"range": {
                 "start": {"line": 0, "character": 0},
                 "end":   {"line": 0, "character": 1},
             }, "newText": "X"}]},
            {"textDocument": {"uri": "file:///missing.py"},
             "edits": [{"range": {
                 "start": {"line": 0, "character": 0},
                 "end":   {"line": 0, "character": 1},
             }, "newText": "Y"}]},
        ],
    }

    def buffer_for_uri(uri: str) -> Any:
        return MagicMock() if uri == "file:///a.py" else None

    applied, failed = apply_workspace_edit(edit, buffer_for_uri=buffer_for_uri)
    assert applied == ["file:///a.py"]
    assert failed == ["file:///missing.py"]


def test_apply_text_edits_exception_routes_uri_to_failed(monkeypatch: Any) -> None:
    def fake_apply(buffer: Any, edits: Any) -> None:
        raise RuntimeError("simulated server-range corruption")

    monkeypatch.setattr(
        "gedit_lsp.workspace_edit.apply_text_edits", fake_apply,
    )

    edit = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"},
             "edits": [{"range": {
                 "start": {"line": 0, "character": 0},
                 "end":   {"line": 0, "character": 1},
             }, "newText": "X"}]},
        ],
    }
    applied, failed = apply_workspace_edit(
        edit, buffer_for_uri=lambda _u: MagicMock(),
    )
    assert applied == []
    assert failed == ["file:///a.py"]


# --- apply_workspace_edit: empty / malformed edge cases ----------


def test_empty_workspace_edit_returns_empty_lists() -> None:
    applied, failed = apply_workspace_edit(
        {}, buffer_for_uri=lambda _u: MagicMock(),
    )
    assert applied == []
    assert failed == []


def test_non_dict_edit_returns_empty_lists() -> None:
    applied, failed = apply_workspace_edit(
        None, buffer_for_uri=lambda _u: MagicMock(),  # type: ignore[arg-type]
    )
    assert applied == []
    assert failed == []


def test_documentChanges_with_malformed_entries_skipped() -> None:
    edit = {
        "documentChanges": [
            "not a dict",  # type: ignore[list-item]
            {"missing": "textDocument"},
            {"textDocument": "not a dict"},
            {"textDocument": {"uri": 42}, "edits": []},  # uri not str
            {"textDocument": {"uri": "file:///a.py"}, "edits": "not a list"},
            {"textDocument": {"uri": "file:///b.py"},
             "edits": [{"range": {
                 "start": {"line": 0, "character": 0},
                 "end":   {"line": 0, "character": 1},
             }, "newText": "X"}]},
        ],
    }
    applied, failed = apply_workspace_edit(
        edit, buffer_for_uri=lambda _u: MagicMock(),
    )
    assert applied == ["file:///b.py"]
    assert failed == []


# --- apply_workspace_edit: per-file edit isolation ---------------


def test_per_file_edits_handed_through_unchanged() -> None:
    captured: list[tuple[str, list[Any]]] = []

    def fake_apply(buffer: Any, edits: list[Any]) -> None:
        # buffer is uniquely tagged per uri so we can verify isolation.
        captured.append((buffer.tag, edits))

    import gedit_lsp.workspace_edit as we
    we.apply_text_edits = fake_apply  # type: ignore[assignment]

    a_edits = [{"range": {"start": {"line": 0, "character": 0},
                          "end":   {"line": 0, "character": 1}}, "newText": "A"}]
    b_edits = [{"range": {"start": {"line": 1, "character": 0},
                          "end":   {"line": 1, "character": 1}}, "newText": "B"}]
    edit = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": a_edits},
            {"textDocument": {"uri": "file:///b.py"}, "edits": b_edits},
        ],
    }

    def buffer_for_uri(uri: str) -> Any:
        m = MagicMock()
        m.tag = uri
        return m

    apply_workspace_edit(edit, buffer_for_uri=buffer_for_uri)
    assert ("file:///a.py", a_edits) in captured
    assert ("file:///b.py", b_edits) in captured
    # No cross-contamination
    a_call = next(c for c in captured if c[0] == "file:///a.py")
    assert a_call[1] is a_edits
```

- [ ] **Step 1.2: Run the new tests to verify they fail**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_workspace_edit.py -v`

Expected: every test fails with `ModuleNotFoundError: No module named 'gedit_lsp.workspace_edit'`.

- [ ] **Step 1.3: Implement `src/gedit_lsp/workspace_edit.py`**

```python
"""Pure helpers for applying LSP WorkspaceEdit responses + tokenising
the word under the cursor.

`apply_workspace_edit` is the canonical entry point for textDocument/rename
(and, in v0.4.0+, textDocument/codeAction). It walks the WorkspaceEdit
shape — preferring `documentChanges` (the spec-preferred shape, carries
versionId) over the older `changes` map — and delegates each file's
TextEdit[] to the existing `features.formatting.apply_text_edits` helper
(right-to-left sort + one begin/end_user_action per file).

`derive_placeholder` is the prepareRename fallback: when the server
doesn't advertise prepareProvider, or when prepareRename returns
{defaultBehavior: true}, the controller asks us for the identifier
spanning the cursor. The regex is broad enough for most LSP-supported
languages (Python, C, Rust, Go, JS); the server's prepareRename is the
authoritative source whenever it's available.

This module is GTK-widget-free apart from typed buffer parameters that
the caller already holds, so it's safe in headless CI.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gedit_lsp.features.formatting import apply_text_edits

if TYPE_CHECKING:
    from gi.repository import GtkSource  # type: ignore[attr-defined]


logger = logging.getLogger("gedit_lsp.workspace_edit")

# Identifier-shaped token for the prepareRename fallback. Broad enough
# for Python / C / Rust / Go / JS — the server's prepareRename is the
# authoritative source when available.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def derive_placeholder(
    buffer: GtkSource.Buffer,
    cursor_line: int,
    cursor_char_utf16: int,
) -> str:
    """Return the identifier-shaped token spanning (line, char), or "".

    Reads the buffer line at `cursor_line` and finds the regex match
    whose span contains `cursor_char_utf16`. If no match contains the
    cursor, returns "" — caller falls back to popover with empty entry.
    """
    line_count = buffer.get_line_count()
    if cursor_line < 0 or cursor_line >= line_count:
        return ""
    start = buffer.get_iter_at_line(cursor_line)
    if cursor_line + 1 < line_count:
        end = buffer.get_iter_at_line(cursor_line + 1)
    else:
        end = buffer.get_end_iter()
    line_text = buffer.get_text(start, end, False)
    if line_text.endswith("\n"):
        line_text = line_text[:-1]
    for m in _IDENT_RE.finditer(line_text):
        if m.start() <= cursor_char_utf16 <= m.end():
            return m.group(0)
    return ""


def apply_workspace_edit(
    edit: Any,
    *,
    buffer_for_uri: Callable[[str], "GtkSource.Buffer | None"],
) -> tuple[list[str], list[str]]:
    """Apply a WorkspaceEdit. Returns (applied_uris, failed_uris).

    Prefers `documentChanges` over the older `changes` map. Per-file
    failures don't abort the whole apply: a missing buffer or an
    apply_text_edits exception moves that URI into `failed_uris` and
    the loop continues.

    The caller is responsible for ensuring `buffer_for_uri` returns an
    open buffer for every URI in the WorkspaceEdit. That typically
    means opening any closed files via Gedit.commands_load_location
    and waiting for their `loaded` signal before calling this helper.
    """
    if not isinstance(edit, dict):
        return ([], [])

    applied: list[str] = []
    failed: list[str] = []

    document_changes = edit.get("documentChanges")
    if isinstance(document_changes, list) and document_changes:
        for entry in document_changes:
            if not isinstance(entry, dict):
                continue
            text_doc = entry.get("textDocument")
            if not isinstance(text_doc, dict):
                continue
            uri = text_doc.get("uri")
            edits = entry.get("edits")
            if not isinstance(uri, str) or not isinstance(edits, list):
                continue
            _apply_one(uri, edits, buffer_for_uri, applied, failed)
        return (applied, failed)

    changes = edit.get("changes")
    if isinstance(changes, dict):
        for uri, edits in changes.items():
            if not isinstance(uri, str) or not isinstance(edits, list):
                continue
            _apply_one(uri, edits, buffer_for_uri, applied, failed)
        return (applied, failed)

    return (applied, failed)


def _apply_one(
    uri: str,
    edits: list[dict[str, Any]],
    buffer_for_uri: Callable[[str], "GtkSource.Buffer | None"],
    applied: list[str],
    failed: list[str],
) -> None:
    buf = buffer_for_uri(uri)
    if buf is None:
        logger.info("workspace_edit: no buffer for %s — skipped", uri)
        failed.append(uri)
        return
    try:
        apply_text_edits(buf, edits)
    except Exception as exc:  # noqa: BLE001  — we want all per-file failures isolated
        logger.info("workspace_edit: apply_text_edits raised for %s: %r", uri, exc)
        failed.append(uri)
        return
    applied.append(uri)
```

- [ ] **Step 1.4: Run the tests to verify they pass**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_workspace_edit.py -v`

Expected: all pass.

- [ ] **Step 1.5: Run all unit tests to confirm no collateral damage**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass.

- [ ] **Step 1.6: Lint + typecheck**

Run:
```bash
env -u PYTHONPATH python -m ruff check src tests
env -u PYTHONPATH python -m mypy src
```

Expected: both clean.

- [ ] **Step 1.7: Commit**

```bash
git add src/gedit_lsp/workspace_edit.py tests/unit/test_workspace_edit.py
git commit -m "$(cat <<'EOF'
feat(rename): workspace_edit module — apply_workspace_edit + derive_placeholder

Pure helpers for the upcoming textDocument/rename feature (and reused
by textDocument/codeAction in a later v0.4.0 task).

apply_workspace_edit walks the WorkspaceEdit shape (preferring
documentChanges over the older `changes` map) and per-file delegates
to features.formatting.apply_text_edits — which already handles the
right-to-left sort + begin/end_user_action wrapping. Per-file failures
are isolated via try/except: missing buffers and apply exceptions move
the URI into the `failed_uris` return list without aborting the rest.

derive_placeholder is the prepareRename fallback: regex-based
identifier extraction at the cursor for clients whose servers don't
advertise prepareProvider, or that return {defaultBehavior: true}.

No GTK widgets at module load time; tests use GtkSource.Buffer (the
model object — safe in headless CI per the project-memory invariant)
and MagicMock buffers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `RenamePopover` widget

**Files:**
- Create: `src/gedit_lsp/ui/rename_popover.py`

The popover is a thin `Gtk.Popover` wrapper around a single `Gtk.Entry`. Per the spec's testing section, the widget is excluded from automated tests (the unit-tests-avoid-GTK-widgets invariant — `Gtk.Popover` SIGTRAPs in headless CI). Smoke testing covers it later in Task 4.

This task is small but kept separate so the controller (Task 3) imports a real type rather than a stub. Two non-obvious bits:

1. **Cursor anchoring.** Use `view.get_iter_location(cursor_iter)` to get a buffer-coordinate `Gdk.Rectangle`, convert via `view.buffer_to_window_coords` (so scroll position doesn't put the popover off-screen), then `popover.set_pointing_to(rect)`. Same pattern that `features/signature_help.py` uses.
2. **Cancel-on-close-by-other-means.** `Gtk.Popover` fires `closed` whenever it dismisses — including when we call `popdown()` ourselves from the Enter handler. To avoid double-firing the cancel callback after a successful commit, clear `self._on_commit` and `self._on_cancel` to `None` before calling `popdown()` from the Enter / Escape handlers. The `closed` handler then no-ops if both are None.

- [ ] **Step 2.1: Create `src/gedit_lsp/ui/rename_popover.py`**

```python
"""Gtk.Popover with a single Gtk.Entry for the rename feature's
new-name input.

Anchored at the active view's cursor position via set_pointing_to(rect)
where the rect comes from view.get_iter_location(cursor_iter) and is
converted to widget coordinates with view.buffer_to_window_coords.
Same positioning pattern as features/signature_help's popover.

This widget is excluded from automated tests per the unit-tests-avoid-
GTK-widgets project invariant — Gtk.Popover SIGTRAPs in headless CI.
It is exercised by manual smoke testing only (see the rename PR's
test plan).

Cancellation discipline: any close path that didn't go through commit
is treated as a cancel. To avoid double-firing the cancel callback
after a successful commit, the Enter handler clears the callbacks
to None *before* calling popdown(); the `closed` handler then sees
None and no-ops.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

logger = logging.getLogger("gedit_lsp.rename_popover")


class RenamePopover:
    def __init__(self, view: Gtk.TextView) -> None:
        self._view = view
        self._popover: Gtk.Popover | None = None
        self._entry: Gtk.Entry | None = None
        self._on_commit: Callable[[str], None] | None = None
        self._on_cancel: Callable[[], None] | None = None

    def show(
        self,
        *,
        placeholder: str,
        on_commit: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._on_commit = on_commit
        self._on_cancel = on_cancel

        popover = Gtk.Popover.new(self._view)  # type: ignore[call-arg]
        entry = Gtk.Entry()
        entry.set_text(placeholder)
        entry.select_region(0, -1)
        entry.set_width_chars(max(20, len(placeholder) + 4))
        entry.connect("activate", self._on_activate)
        entry.connect("key-press-event", self._on_key_press)
        popover.add(entry)  # type: ignore[attr-defined]
        popover.connect("closed", self._on_closed)

        # Anchor at cursor.
        buf = self._view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        rect = self._view.get_iter_location(cursor)
        wx, wy = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y,
        )
        rect.x = wx
        rect.y = wy
        popover.set_pointing_to(rect)
        popover.show_all()  # type: ignore[attr-defined]
        popover.popup()
        entry.grab_focus()

        self._popover = popover
        self._entry = entry

    def dismiss(self) -> None:
        if self._popover is not None:
            self._popover.popdown()

    def _on_activate(self, entry: Gtk.Entry) -> None:
        text = entry.get_text()
        on_commit = self._on_commit
        # Clear callbacks BEFORE popdown so _on_closed's auto-cancel no-ops.
        self._on_commit = None
        self._on_cancel = None
        self.dismiss()
        if on_commit is not None:
            on_commit(text)

    def _on_key_press(self, _entry: Gtk.Entry, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            on_cancel = self._on_cancel
            # Clear before popdown — same reason as commit path.
            self._on_commit = None
            self._on_cancel = None
            self.dismiss()
            if on_cancel is not None:
                on_cancel()
            return True
        return False

    def _on_closed(self, _popover: Gtk.Popover) -> None:
        # Treat any close that didn't go through commit/escape (i.e.
        # focus-out, click-elsewhere, programmatic dismiss) as a cancel.
        on_cancel = self._on_cancel
        self._on_commit = None
        self._on_cancel = None
        self._popover = None
        self._entry = None
        if on_cancel is not None:
            on_cancel()
```

- [ ] **Step 2.2: Smoke-test the import path**

Run: `env -u PYTHONPATH python -c "from gedit_lsp.ui.rename_popover import RenamePopover; print(RenamePopover)"`

Expected: `<class 'gedit_lsp.ui.rename_popover.RenamePopover'>`. (No widget construction at import time, so this is safe in headless CI.)

- [ ] **Step 2.3: Lint + typecheck**

Run:
```bash
env -u PYTHONPATH python -m ruff check src tests
env -u PYTHONPATH python -m mypy src
```

Expected: both clean.

- [ ] **Step 2.4: Commit**

```bash
git add src/gedit_lsp/ui/rename_popover.py
git commit -m "$(cat <<'EOF'
feat(rename): RenamePopover — Gtk.Popover + Gtk.Entry for new-name input

Thin widget wrapper: anchored at the cursor via set_pointing_to, text
pre-selected so the user can immediately overtype, Enter commits,
Escape and focus-out both cancel.

Cancellation discipline: the activate / Escape handlers clear the
callbacks to None *before* calling popdown() so the `closed` signal
handler (which exists to catch focus-out) doesn't double-fire on a
successful commit.

Excluded from automated tests per the unit-tests-avoid-GTK-widgets
project invariant — Gtk.Popover SIGTRAPs in headless CI. Will be
exercised by the manual smoke test in the plugin-wiring task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `RenameController` + unit tests

**Files:**
- Create: `src/gedit_lsp/features/rename.py`
- Create: `tests/unit/test_rename_controller.py`

The controller is the orchestration layer. It mirrors `ReferencesController` in shape — window-scoped, `trigger(server, uri, flush_pending_change)` is the entire surface — but adds:

1. An optional `prepareRename` round-trip with four protocol-shape branches (null / Range / `{range, placeholder}` / `{defaultBehavior: true}`) plus an error fallback.
2. A `RenamePopover` instance per trigger, with `popover_factory` injectable for tests.
3. A `WorkspaceEdit` apply phase that opens any closed files first (async via `Gedit.commands_load_location` + the document's `loaded` signal), waits for *all* loads to settle, then calls `apply_workspace_edit`.

The async load step uses two module-level test seams:
- `_default_load_uri(window, uri, on_loaded)` — production: `commands_load_location` + connect to `loaded`. Tests pass a synchronous fake.
- `_default_buffer_for_uri(window, uri)` — production: walk `window.get_documents()`. Tests pass a dict-lookup fake.

These are module-level functions (not methods) so tests inject by passing them as constructor parameters — the same pattern `navigation.navigate_to_uri` uses for its `load_location` and `file_for_uri` seams.

The controller carries no state across triggers — each F2 press is a fresh flow. (Race: if the user presses F2 again with the popover up, the new request goes through the new popover; the old popover stays attached to its now-orphaned commit callback. We accept this — rename is a deliberate human gesture, not an autocomplete-style stream.)

- [ ] **Step 3.1: Write `tests/unit/test_rename_controller.py`**

```python
"""Unit tests for RenameController.

Three thrust areas:

  1. Capability + prepareRename branching — the controller honours
     renameProvider.prepareProvider, branches on the four protocol
     response shapes, and falls back to derive_placeholder on error.
  2. Edit-flush invariant — flush_pending_change() runs before the
     first request goes out (whether prepareRename or rename).
  3. WorkspaceEdit apply — controller collects URIs, async-loads
     closed ones via the load_uri seam, then delegates to
     apply_workspace_edit and publishes the per-file summary.

No real GTK widgets — view/buffer/window/popover are all fakes/mocks.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("GtkSource", "300")
from gi.repository import GtkSource  # type: ignore[attr-defined]

from gedit_lsp.features.rename import RenameController


class _FakeStatusbar:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def push(self, ctx: int, msg: str) -> None:
        self.messages.append((ctx, msg))


class _FakeBuffer:
    """Sufficient subset of Gtk.TextBuffer to drive text_iter_to_utf16
    and the prepareRename Range-shape placeholder reader.
    """

    def __init__(
        self,
        line: int,
        char: int,
        line_text: str = "x" * 100,
    ) -> None:
        self._line_text = line_text
        self._cursor_iter = _FakeIter(self, line, char)

    def get_iter_at_mark(self, _mark: Any) -> _FakeIter:
        return self._cursor_iter

    def get_insert(self) -> Any:
        return object()

    def get_iter_at_line(self, line: int) -> _FakeIter:
        return _FakeIter(self, line, 0)

    def get_text(
        self, start: _FakeIter, end: _FakeIter, _hidden: bool
    ) -> str:
        return self._line_text[start.get_line_offset():end.get_line_offset()]


class _FakeIter:
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
        self,
        *,
        rename_capability: Any = True,
    ) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self._rename_cap = rename_capability
        # callbacks keyed by request index
        self.callbacks: list[Any] = []

    def capability(self, key: str) -> Any:
        if key == "renameProvider":
            return self._rename_cap
        return None

    def _send_request(
        self, method: str, params: dict[str, Any], cb: Any
    ) -> int:
        self.requests.append((method, params))
        self.callbacks.append(cb)
        return len(self.requests)


class _FakePopover:
    """Synchronous popover: show() immediately fires on_commit with
    `commit_text` if set, or on_cancel otherwise.
    """
    def __init__(
        self,
        view: Any,
        *,
        commit_text: str | None = None,
    ) -> None:
        self._view = view
        self._commit_text = commit_text
        self.shown_with: dict[str, Any] | None = None

    def show(
        self,
        *,
        placeholder: str,
        on_commit: Any,
        on_cancel: Any,
    ) -> None:
        self.shown_with = {"placeholder": placeholder}
        if self._commit_text is None:
            on_cancel()
        else:
            on_commit(self._commit_text)


def _make_buffer_for_real_derive_placeholder() -> GtkSource.Buffer:
    """A real GtkSource.Buffer so derive_placeholder can read from it."""
    b = GtkSource.Buffer()
    b.set_text("foo = bar(baz)\n", -1)
    return b


def _build(
    *,
    server: _FakeServer | None = None,
    cursor: tuple[int, int] = (0, 7),
    popover_commit_text: str | None = "new_name",
    load_uri: Any = None,
    buffer_for_uri: Any = None,
    real_buffer: bool = False,
) -> tuple[RenameController, _FakeServer, _FakeStatusbar, list[_FakePopover]]:
    server = server or _FakeServer()
    statusbar = _FakeStatusbar()
    if real_buffer:
        buf = _make_buffer_for_real_derive_placeholder()
        # _FakeBuffer wrapping a real GtkSource.Buffer — but the real
        # buffer's iters work too, so use it directly:
        view = MagicMock()
        view.get_buffer.return_value = buf

        class _BufWindow:
            def __init__(self) -> None:
                self._sb = statusbar
            def get_active_view(self) -> Any:
                return view
            def get_statusbar(self) -> Any:
                return self._sb
        # Simulate cursor by patching get_iter_at_mark on the real buffer:
        cursor_iter = buf.get_iter_at_line_offset(cursor[0], cursor[1])
        buf.get_iter_at_mark = lambda _m: cursor_iter  # type: ignore[assignment, method-assign]
        buf.get_insert = lambda: object()  # type: ignore[assignment, method-assign]
        window = _BufWindow()
    else:
        view = _FakeView(_FakeBuffer(cursor[0], cursor[1]))
        window = _FakeWindow(view, statusbar)

    popovers: list[_FakePopover] = []

    def _factory(v: Any) -> _FakePopover:
        p = _FakePopover(v, commit_text=popover_commit_text)
        popovers.append(p)
        return p

    ctrl = RenameController(
        window=window,
        popover_factory=_factory,
        load_uri=load_uri or (lambda _w, _u, on_done: on_done(True)),
        buffer_for_uri=buffer_for_uri or (lambda _w, _u: MagicMock()),
    )
    return ctrl, server, statusbar, popovers


def _trigger(
    ctrl: RenameController,
    server: _FakeServer,
    *,
    flush: Any = None,
) -> None:
    flush = flush or (lambda: None)
    ctrl.trigger(server, "file:///x.py", flush)


# --- capability gate -------------------------------------------------


def test_capability_gate_blocks_when_unsupported() -> None:
    server = _FakeServer(rename_capability=False)
    ctrl, server, statusbar, popovers = _build(server=server)
    _trigger(ctrl, server)
    assert server.requests == []
    assert popovers == []
    assert any(
        "does not support rename" in m.lower()
        for _ctx, m in statusbar.messages
    )


def test_capability_gate_blocks_when_capability_is_none() -> None:
    server = _FakeServer(rename_capability=None)
    ctrl, server, _statusbar, popovers = _build(server=server)
    _trigger(ctrl, server)
    assert server.requests == []
    assert popovers == []


# --- prepareRename: gating + branches -------------------------------


def test_prepareRename_skipped_when_prepareProvider_falsy() -> None:
    # capability is True (boolean) — no prepareProvider → skip prepareRename
    server = _FakeServer(rename_capability=True)
    ctrl, server, _statusbar, popovers = _build(
        server=server, real_buffer=True, popover_commit_text=None,
    )
    _trigger(ctrl, server)
    # No request fired (popover commit_text was None → no rename either)
    assert server.requests == []
    # But the popover WAS shown
    assert len(popovers) == 1


def test_prepareRename_sent_when_prepareProvider_true() -> None:
    server = _FakeServer(
        rename_capability={"prepareProvider": True},
    )
    ctrl, server, _statusbar, popovers = _build(
        server=server, popover_commit_text=None,
    )
    _trigger(ctrl, server)
    assert len(server.requests) == 1
    assert server.requests[0][0] == "textDocument/prepareRename"
    # Popover not yet shown (waiting for prepare response)
    assert popovers == []


def test_prepareRename_null_pushes_cannot_rename_here_no_popover() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, statusbar, popovers = _build(server=server)
    _trigger(ctrl, server)
    server.callbacks[0]({"result": None})
    assert popovers == []
    assert any(
        "cannot rename" in m.lower() for _ctx, m in statusbar.messages
    )


def test_prepareRename_with_placeholder_used_directly() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, popovers = _build(
        server=server, popover_commit_text=None,
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "range": {"start": {"line": 0, "character": 0},
                  "end":   {"line": 0, "character": 3}},
        "placeholder": "ServerSaidThis",
    }})
    assert len(popovers) == 1
    assert popovers[0].shown_with == {"placeholder": "ServerSaidThis"}


def test_prepareRename_default_behavior_uses_derive_placeholder() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, popovers = _build(
        server=server, real_buffer=True, popover_commit_text=None,
        cursor=(0, 7),  # inside "bar"
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {"defaultBehavior": True}})
    assert len(popovers) == 1
    assert popovers[0].shown_with == {"placeholder": "bar"}


def test_prepareRename_range_reads_buffer_text_for_placeholder() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, popovers = _build(
        server=server, real_buffer=True, popover_commit_text=None,
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "start": {"line": 0, "character": 6},
        "end":   {"line": 0, "character": 9},
    }})
    assert len(popovers) == 1
    assert popovers[0].shown_with == {"placeholder": "bar"}


def test_prepareRename_error_falls_back_to_derive_placeholder() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, popovers = _build(
        server=server, real_buffer=True, popover_commit_text=None,
        cursor=(0, 7),
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"error": {"code": -32601, "message": "method not found"}})
    assert len(popovers) == 1
    assert popovers[0].shown_with == {"placeholder": "bar"}


# --- edit-flush invariant -------------------------------------------


def test_flush_called_before_prepareRename_when_prepareProvider_true() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, _popovers = _build(server=server, popover_commit_text=None)
    log: list[str] = []

    def flush() -> None:
        log.append(f"flush@{len(server.requests)}")

    _trigger(ctrl, server, flush=flush)
    assert log == ["flush@0"]
    assert len(server.requests) == 1


def test_flush_called_before_rename_when_no_prepareProvider() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, _statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
    )
    log: list[str] = []

    def flush() -> None:
        log.append(f"flush@{len(server.requests)}")

    _trigger(ctrl, server, flush=flush)
    assert log == ["flush@0"]
    # rename request was sent (no prepareRename in this path)
    assert len(server.requests) == 1
    assert server.requests[0][0] == "textDocument/rename"


# --- rename request: payload + empty/unchanged + errors -------------


def test_empty_newName_does_not_send_rename_request() -> None:
    server = _FakeServer(rename_capability={"prepareProvider": True})
    ctrl, server, _statusbar, _popovers = _build(
        server=server, popover_commit_text="",
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "range": {"start": {"line": 0, "character": 0},
                  "end":   {"line": 0, "character": 3}},
        "placeholder": "old",
    }})
    # Only the prepareRename request was sent — no rename followup.
    assert [r[0] for r in server.requests] == ["textDocument/prepareRename"]


def test_rename_request_payload_shape() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, _statusbar, _popovers = _build(
        server=server, real_buffer=True,
        cursor=(7, 3), popover_commit_text="new_name",
    )
    # Override default uri-extraction by triggering directly
    ctrl.trigger(server, "file:///x.py", lambda: None)
    assert len(server.requests) == 1
    method, params = server.requests[0]
    assert method == "textDocument/rename"
    assert params["textDocument"] == {"uri": "file:///x.py"}
    assert params["position"] == {"line": 7, "character": 3}
    assert params["newName"] == "new_name"


def test_rename_server_error_pushes_failure_message() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
    )
    _trigger(ctrl, server)
    # rename was sent — fire its callback with an error
    server.callbacks[0]({"error": {"code": 1, "message": "nope"}})
    assert any(
        "rename failed" in m.lower() for _ctx, m in statusbar.messages
    )


def test_rename_null_result_pushes_no_changes() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": None})
    assert any("no changes" in m.lower() for _ctx, m in statusbar.messages)


def test_rename_empty_documentChanges_pushes_no_changes() -> None:
    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {"documentChanges": []}})
    # All-URIs-collected returns []; the controller short-circuits to "no changes".
    assert any("no changes" in m.lower() for _ctx, m in statusbar.messages)


# --- WorkspaceEdit dispatch + load-settle ---------------------------


def test_all_open_files_apply_immediately(monkeypatch: Any) -> None:
    captured_apply_args: list[tuple[Any, dict[str, Any]]] = []

    def fake_apply(edit: Any, *, buffer_for_uri: Any) -> tuple[list[str], list[str]]:
        captured_apply_args.append((buffer_for_uri, edit))
        return (["file:///a.py", "file:///b.py"], [])

    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit", fake_apply,
    )

    open_buffers = {"file:///a.py": MagicMock(), "file:///b.py": MagicMock()}
    load_calls: list[str] = []

    def load_uri(_w: Any, uri: str, on_done: Any) -> None:
        load_calls.append(uri)
        on_done(True)

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=load_uri,
        buffer_for_uri=lambda _w, u: open_buffers.get(u),
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": []},
            {"textDocument": {"uri": "file:///b.py"}, "edits": []},
        ],
    }})
    # No load was needed — all URIs were already open.
    assert load_calls == []
    assert len(captured_apply_args) == 1
    assert any(
        "renamed 2 file" in m.lower() for _ctx, m in statusbar.messages
    )


def test_closed_files_are_loaded_then_apply_runs(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (
            [u for u in ["file:///a.py", "file:///b.py", "file:///c.py"]
             if buffer_for_uri(u) is not None],
            [u for u in ["file:///a.py", "file:///b.py", "file:///c.py"]
             if buffer_for_uri(u) is None],
        ),
    )

    # a.py open, b.py and c.py closed (load_uri makes them open).
    state = {"file:///a.py": MagicMock()}
    load_calls: list[str] = []

    def load_uri(_w: Any, uri: str, on_done: Any) -> None:
        load_calls.append(uri)
        state[uri] = MagicMock()  # "loaded" — buffer_for_uri now finds it
        on_done(True)

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=load_uri,
        buffer_for_uri=lambda _w, u: state.get(u),
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": []},
            {"textDocument": {"uri": "file:///b.py"}, "edits": []},
            {"textDocument": {"uri": "file:///c.py"}, "edits": []},
        ],
    }})
    assert sorted(load_calls) == ["file:///b.py", "file:///c.py"]
    assert any(
        "renamed 3 file" in m.lower() for _ctx, m in statusbar.messages
    )


def test_partial_load_failure_reports_in_summary(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (
            [u for u in ["file:///a.py", "file:///b.py", "file:///c.py"]
             if buffer_for_uri(u) is not None],
            [u for u in ["file:///a.py", "file:///b.py", "file:///c.py"]
             if buffer_for_uri(u) is None],
        ),
    )

    state = {"file:///a.py": MagicMock()}

    def load_uri(_w: Any, uri: str, on_done: Any) -> None:
        if uri == "file:///c.py":
            on_done(False)  # simulate load failure
        else:
            state[uri] = MagicMock()
            on_done(True)

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=load_uri,
        buffer_for_uri=lambda _w, u: state.get(u),
    )
    _trigger(ctrl, server)
    server.callbacks[0]({"result": {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": []},
            {"textDocument": {"uri": "file:///b.py"}, "edits": []},
            {"textDocument": {"uri": "file:///c.py"}, "edits": []},
        ],
    }})
    assert any(
        "renamed 2 file" in m.lower() and "1 failed" in m.lower()
        for _ctx, m in statusbar.messages
    )


def test_changes_map_fallback_collected_correctly(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "gedit_lsp.features.rename.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (["file:///a.py"], []),
    )

    state = {"file:///a.py": MagicMock()}

    def load_uri(_w: Any, uri: str, on_done: Any) -> None:
        state[uri] = MagicMock()
        on_done(True)

    server = _FakeServer(rename_capability=True)
    ctrl, server, statusbar, _popovers = _build(
        server=server, real_buffer=True, popover_commit_text="new",
        load_uri=load_uri,
        buffer_for_uri=lambda _w, u: state.get(u),
    )
    _trigger(ctrl, server)
    # Server returns the older `changes` map shape, no documentChanges.
    server.callbacks[0]({"result": {
        "changes": {
            "file:///a.py": [{"range": {
                "start": {"line": 0, "character": 0},
                "end":   {"line": 0, "character": 3},
            }, "newText": "X"}],
        },
    }})
    assert any(
        "renamed 1 file" in m.lower() for _ctx, m in statusbar.messages
    )
```

- [ ] **Step 3.2: Run the new tests to verify they fail**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_rename_controller.py -v`

Expected: every test fails with `ModuleNotFoundError: No module named 'gedit_lsp.features.rename'`.

- [ ] **Step 3.3: Implement `src/gedit_lsp/features/rename.py`**

```python
"""RenameController: textDocument/rename + prepareRename orchestration.

Window-scoped, mirrors ReferencesController in shape. trigger() is the
entire surface: capture cursor, flush, optional prepareRename, show
popover, on commit fire rename, then load any closed files and apply
the WorkspaceEdit via the workspace_edit helper.

Async load-settle is the only non-trivial new state — handled inline
via a remaining-counter closure rather than a dedicated helper class
(it's <20 lines of code and only used in one place). load_uri and
buffer_for_uri are module-level test seams, replaceable per-instance
through constructor parameters.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter
from gedit_lsp.workspace_edit import apply_workspace_edit, derive_placeholder

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]

    from gedit_lsp.server import LanguageServer
    from gedit_lsp.ui.rename_popover import RenamePopover


logger = logging.getLogger("gedit_lsp.rename")


def _default_load_uri(
    window: Any, uri: str, on_loaded: Callable[[bool], None]
) -> None:
    """Open `uri` in `window` and call on_loaded(success) when ready.

    Uses Gedit.commands_load_location (1-indexed line/column; we pass
    1, 0 since rename doesn't care about cursor placement on the new
    tab) and listens for the document's `loaded` signal.

    Replaceable in unit tests via RenameController(load_uri=...).
    """
    import gi

    gi.require_version("Gedit", "3.0")
    from gi.repository import Gedit, Gio  # type: ignore[attr-defined]

    gfile = Gio.File.new_for_uri(uri)
    Gedit.commands_load_location(window, gfile, None, 1, 0)
    tab = window.get_tab_from_location(gfile)
    if tab is None:
        on_loaded(False)
        return
    doc = tab.get_document()
    handler_id: list[int] = []

    def _on_loaded(_doc: Any) -> None:
        if handler_id:
            doc.disconnect(handler_id[0])
        on_loaded(True)

    handler_id.append(doc.connect("loaded", _on_loaded))


def _default_buffer_for_uri(window: Any, uri: str) -> Any:
    """Walk window.get_documents() for the matching URI. Replaceable
    in unit tests via RenameController(buffer_for_uri=...).
    """
    for doc in window.get_documents():
        gfile = doc.get_file().get_location()
        if gfile is not None and gfile.get_uri() == uri:
            return doc
    return None


class RenameController:
    def __init__(
        self,
        *,
        window: Gedit.Window,
        popover_factory: Callable[[Any], RenamePopover] | None = None,
        load_uri: Callable[
            [Any, str, Callable[[bool], None]], None
        ] = _default_load_uri,
        buffer_for_uri: Callable[[Any, str], Any] = _default_buffer_for_uri,
    ) -> None:
        self._window = window
        self._popover_factory = popover_factory
        self._load_uri = load_uri
        self._buffer_for_uri = buffer_for_uri

    def trigger(
        self,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None],
    ) -> None:
        statusbar = self._window.get_statusbar()
        rename_cap = server.capability("renameProvider")
        if not rename_cap:
            logger.info("rename: server does not support renameProvider")
            statusbar.push(0, "LSP: server does not support rename")
            return

        view = self._window.get_active_view()
        if view is None:
            return
        buf = view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line, char = text_iter_to_utf16(cursor)

        flush_pending_change()  # edit-flush invariant

        prepare_supported = (
            isinstance(rename_cap, dict)
            and bool(rename_cap.get("prepareProvider"))
        )
        if prepare_supported:
            self._send_prepare(server, uri, line, char, view, buf)
        else:
            placeholder = derive_placeholder(buf, line, char)
            self._show_popover(server, uri, line, char, view, placeholder)

    def _send_prepare(
        self,
        server: LanguageServer,
        uri: str,
        line: int,
        char: int,
        view: Any,
        buf: Any,
    ) -> None:
        statusbar = self._window.get_statusbar()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
        }

        def on_prepare(msg: dict[str, Any]) -> None:
            if msg.get("error"):
                logger.info(
                    "rename: prepareRename error %r — fallback", msg.get("error"),
                )
                placeholder = derive_placeholder(buf, line, char)
                self._show_popover(server, uri, line, char, view, placeholder)
                return
            result = msg.get("result")
            if result is None:
                statusbar.push(0, "LSP: cannot rename symbol here")
                return
            placeholder = self._placeholder_from_prepare(result, buf, line, char)
            self._show_popover(server, uri, line, char, view, placeholder)

        server._send_request("textDocument/prepareRename", params, on_prepare)

    @staticmethod
    def _placeholder_from_prepare(
        result: Any, buf: Any, line: int, char: int
    ) -> str:
        # Shape: {range, placeholder}
        if isinstance(result, dict) and isinstance(result.get("placeholder"), str):
            return result["placeholder"]
        # Shape: {defaultBehavior: true}
        if isinstance(result, dict) and result.get("defaultBehavior") is True:
            return derive_placeholder(buf, line, char)
        # Shape: a Range (start/end dicts present, no placeholder/defaultBehavior)
        if (
            isinstance(result, dict)
            and isinstance(result.get("start"), dict)
            and isinstance(result.get("end"), dict)
        ):
            try:
                start = utf16_to_text_iter(
                    buf, result["start"]["line"], result["start"]["character"],
                )
                end = utf16_to_text_iter(
                    buf, result["end"]["line"], result["end"]["character"],
                )
                return buf.get_text(start, end, False)
            except Exception:  # noqa: BLE001
                return derive_placeholder(buf, line, char)
        return derive_placeholder(buf, line, char)

    def _show_popover(
        self,
        server: LanguageServer,
        uri: str,
        line: int,
        char: int,
        view: Any,
        placeholder: str,
    ) -> None:
        factory = self._popover_factory
        if factory is None:
            from gedit_lsp.ui.rename_popover import RenamePopover
            factory = RenamePopover
        popover = factory(view)

        def on_commit(new_name: str) -> None:
            if not new_name:
                return  # empty submission — popover already dismissed
            self._send_rename(server, uri, line, char, new_name)

        def on_cancel() -> None:
            return

        popover.show(
            placeholder=placeholder,
            on_commit=on_commit,
            on_cancel=on_cancel,
        )

    def _send_rename(
        self,
        server: LanguageServer,
        uri: str,
        line: int,
        char: int,
        new_name: str,
    ) -> None:
        statusbar = self._window.get_statusbar()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
            "newName": new_name,
        }

        def on_response(msg: dict[str, Any]) -> None:
            if msg.get("error"):
                logger.info("rename: server error %r", msg.get("error"))
                statusbar.push(0, "LSP: rename failed (see log)")
                return
            edit = msg.get("result")
            if edit is None or edit == {}:
                statusbar.push(0, "LSP: no changes")
                return
            self._begin_apply(edit)

        server._send_request("textDocument/rename", params, on_response)

    def _begin_apply(self, edit: dict[str, Any]) -> None:
        uris = self._collect_uris(edit)
        if not uris:
            self._window.get_statusbar().push(0, "LSP: no changes")
            return

        to_load = [
            u for u in uris
            if self._buffer_for_uri(self._window, u) is None
        ]

        if not to_load:
            self._do_apply(edit)
            return

        remaining = [len(to_load)]

        def _on_one_loaded(_uri: str, _success: bool) -> None:
            # Success doesn't matter here: if the load failed, the URI
            # will resolve to None in buffer_for_uri at apply time and
            # apply_workspace_edit will mark it as failed. Either way
            # we just count down to know when to fire the apply.
            remaining[0] -= 1
            if remaining[0] == 0:
                self._do_apply(edit)

        for uri in to_load:
            self._load_uri(
                self._window, uri,
                lambda ok, u=uri: _on_one_loaded(u, ok),
            )

    @staticmethod
    def _collect_uris(edit: Any) -> list[str]:
        uris: list[str] = []
        if not isinstance(edit, dict):
            return uris
        document_changes = edit.get("documentChanges")
        if isinstance(document_changes, list):
            for entry in document_changes:
                if isinstance(entry, dict):
                    td = entry.get("textDocument")
                    if isinstance(td, dict) and isinstance(td.get("uri"), str):
                        uris.append(td["uri"])
            return uris
        changes = edit.get("changes")
        if isinstance(changes, dict):
            for uri in changes:
                if isinstance(uri, str):
                    uris.append(uri)
        return uris

    def _do_apply(self, edit: dict[str, Any]) -> None:
        applied, failed = apply_workspace_edit(
            edit,
            buffer_for_uri=lambda u: self._buffer_for_uri(self._window, u),
        )
        statusbar = self._window.get_statusbar()
        n = len(applied)
        m = len(failed)
        if m == 0:
            statusbar.push(0, f"LSP: renamed {n} file(s)")
        else:
            statusbar.push(0, f"LSP: renamed {n} file(s); {m} failed (see log)")
```

- [ ] **Step 3.4: Run the new tests to verify they pass**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_rename_controller.py -v`

Expected: all pass.

- [ ] **Step 3.5: Run the full unit test suite**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass.

- [ ] **Step 3.6: Mutation-test the flush invariant**

Per project memory `Mutation-test behavioural invariants`: prove the test catches what it claims to. Temporarily break `flush_pending_change()` ordering in `features/rename.py:trigger`:

```bash
sed -i.bak 's|flush_pending_change()  # edit-flush invariant|# flush_pending_change()  # edit-flush invariant|' src/gedit_lsp/features/rename.py
env -u PYTHONPATH python -m pytest tests/unit/test_rename_controller.py -k flush -v
```

Expected: `test_flush_called_before_prepareRename_when_prepareProvider_true` and `test_flush_called_before_rename_when_no_prepareProvider` both fail.

Restore:

```bash
mv src/gedit_lsp/features/rename.py.bak src/gedit_lsp/features/rename.py
env -u PYTHONPATH python -m pytest tests/unit/test_rename_controller.py -k flush -v
```

Expected: both tests pass again.

- [ ] **Step 3.7: Mutation-test the capability gate**

Temporarily flip the `if not rename_cap:` guard:

```bash
sed -i.bak 's|if not rename_cap:|if rename_cap and False:|' src/gedit_lsp/features/rename.py
env -u PYTHONPATH python -m pytest tests/unit/test_rename_controller.py -k capability -v
```

Expected: both `test_capability_gate_*` tests fail.

Restore:

```bash
mv src/gedit_lsp/features/rename.py.bak src/gedit_lsp/features/rename.py
env -u PYTHONPATH python -m pytest tests/unit/test_rename_controller.py -k capability -v
```

Expected: both pass again.

- [ ] **Step 3.8: Lint + typecheck**

Run:
```bash
env -u PYTHONPATH python -m ruff check src tests
env -u PYTHONPATH python -m mypy src
```

Expected: both clean.

- [ ] **Step 3.9: Commit**

```bash
git add src/gedit_lsp/features/rename.py tests/unit/test_rename_controller.py
git commit -m "$(cat <<'EOF'
feat(rename): RenameController with prepareRename + WorkspaceEdit apply

Window-scoped controller mirroring ReferencesController. Surface is
trigger(server, uri, flush_pending_change). Branches:

  - capability gate: server.capability("renameProvider") falsy → bail
  - if renameProvider.prepareProvider truthy → send prepareRename, branch
    on the four protocol shapes (null / Range / {range,placeholder} /
    {defaultBehavior:true}) plus an error fallback
  - otherwise → derive_placeholder regex on the buffer line at cursor
  - show popover, on Enter → send textDocument/rename
  - on response → collect URIs, async-load any closed ones via
    Gedit.commands_load_location + the document's `loaded` signal,
    then call apply_workspace_edit and publish per-file summary

load_uri and buffer_for_uri are module-level test seams, replaceable
per-instance through constructor parameters — same pattern as
navigation.navigate_to_uri's load_location/file_for_uri seams.

Mutation-tested invariants (per project memory):
  - flush_pending_change() runs before any LSP request goes out
  - capability gate blocks the request when renameProvider is falsy

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Plugin wiring (action, accel, popup-menu, controller)

**Files:**
- Modify: `src/gedit_lsp/ui/popup_menu.py:23-30` (MENU_ITEMS list)
- Modify: `src/gedit_lsp/plugin.py` (controller construction + action loop + handler)
- Modify: `tests/unit/test_popup_menu.py` (assert "Rename Symbol" → lsp-rename)

- [ ] **Step 4.1: Add a popup-menu test for the new entry**

Append to `tests/unit/test_popup_menu.py` (the existing file already imports `popup_menu` at module level, so use `popup_menu.MENU_ITEMS` — same pattern as the existing `test_menu_items_includes_find_references`):

```python


def test_menu_items_includes_rename_symbol() -> None:
    """Discoverability: right-click → LSP → Rename Symbol must surface
    the win.lsp-rename action for users without the F2 accel."""
    assert ("Rename Symbol", "lsp-rename") in popup_menu.MENU_ITEMS
```

- [ ] **Step 4.2: Run the new test to verify it fails**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_popup_menu.py -k rename_symbol -v`

Expected: fails with `assert ("Rename Symbol", "lsp-rename") in [...]`.

- [ ] **Step 4.3: Add the entry to `MENU_ITEMS`**

In `src/gedit_lsp/ui/popup_menu.py`, replace the existing `MENU_ITEMS` list:

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

with:

```python
MENU_ITEMS: list[tuple[str, str]] = [
    ("Show Hover",        "lsp-hover"),
    ("Go to Definition",  "lsp-goto-definition"),
    ("Go Back",           "lsp-go-back"),
    ("Find References",   "lsp-references"),
    ("Rename Symbol",     "lsp-rename"),
    ("Format",            "lsp-format"),
    ("Show Server Logs…", "lsp-show-server-logs"),
]
```

- [ ] **Step 4.4: Run popup-menu tests to verify they pass**

Run: `env -u PYTHONPATH python -m pytest tests/unit/test_popup_menu.py -v`

Expected: all pass.

- [ ] **Step 4.5: Wire `plugin.py`**

Three edits in `src/gedit_lsp/plugin.py`:

**(a)** Add the import alongside the other feature controllers (look near the existing `from gedit_lsp.features.references import ReferencesController` line, around `:46-47`):

```python
from gedit_lsp.features.rename import RenameController
```

**(b)** Construct the controller in `do_activate`. Find this block (currently `:162-165`):

```python
        self._references_panel = ReferencesPanel(win)
        self._references_ctrl = ReferencesController(
            window=win, panel=self._references_panel,
        )
```

Add immediately after it:

```python
        self._rename_ctrl = RenameController(window=win)
```

**(c)** Add `lsp-rename` to the action loop. Find this list (currently `:172-179`):

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

Replace with:

```python
        for name, config_key, handler in [
            ("lsp-hover", "hover", self._on_hover_activate),
            ("lsp-goto-definition", "goto-definition", self._on_definition_activate),
            ("lsp-go-back", "go-back", self._on_go_back_activate),
            ("lsp-references", "references", self._on_references_activate),
            ("lsp-rename", "rename", self._on_rename_activate),
            ("lsp-show-server-logs", "show-server-logs", self._on_show_server_logs_activate),
            ("lsp-format", "format", self._on_format_activate),
        ]:
```

**(d)** Add the `_on_rename_activate` handler. Place it immediately after the existing `_on_references_activate` handler (currently `:543-563`):

```python
    def _on_rename_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("rename action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("rename: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "rename: doc not bridged (bridge=%s server=%s)",
                bridge, server,
            )
            return
        logger.info("rename: triggering, server.state=%s", server.state)
        self._rename_ctrl.trigger(
            server, bridge.uri, bridge.flush_pending_change,
        )
```

- [ ] **Step 4.6: Run the full unit test suite**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass.

- [ ] **Step 4.7: Lint + typecheck**

Run:
```bash
env -u PYTHONPATH python -m ruff check src tests
env -u PYTHONPATH python -m mypy src
```

Expected: both clean.

- [ ] **Step 4.8: Manual smoke test in gedit**

1. Reinstall the plugin: `./install.sh` (per project memory `Source edits → ./install.sh → restart gedit`).
2. Restart gedit.
3. Open a Python file in a project with multiple files referencing the same symbol (e.g. `src/gedit_lsp/features/references.py` has `ReferencesController` referenced from `plugin.py`).
4. Place the cursor on the `ReferencesController` class name.
5. Press **F2**. Expected:
   - Popover appears anchored at the cursor with `ReferencesController` pre-selected.
   - Type `RenamedReferencesController` and press **Enter**.
   - Both `features/references.py` and `plugin.py` end up with the renamed symbol; the plugin.py tab opens automatically (it was closed) and is left dirty.
   - Statusbar shows `LSP: renamed 2 file(s)` (or however many files are touched).
6. Verify Escape and click-elsewhere both dismiss the popover without sending a request.
7. Verify right-click → LSP → **Rename Symbol** triggers the same flow.
8. Check `~/.local/state/gedit-lsp/plugin.log` contains:
   - `registered action win.lsp-rename accels=['F2']`
   - `rename action invoked`
   - `rename: triggering, server.state=READY`
9. Discard the changes (or `git restore` them) before continuing.

If F2 is silently consumed (per the binding-owner-check memory's PR #16 lesson), the action invocation log line will be absent. In that case, fall back to right-click for the smoke test and file a follow-up to investigate the consumer.

- [ ] **Step 4.9: Commit**

```bash
git add src/gedit_lsp/ui/popup_menu.py \
        src/gedit_lsp/plugin.py \
        tests/unit/test_popup_menu.py
git commit -m "$(cat <<'EOF'
feat(rename): wire action, accel, popup-menu entry, controller

Plugin wiring for textDocument/rename:
  * "Rename Symbol" entry added to the right-click LSP submenu
    (between "Find References" and "Format")
  * lsp-rename Gio.SimpleAction registered with the F2 accelerator
    (default — see defaults.py task)
  * _on_rename_activate handler dispatches to RenameController.trigger
    with the active doc's bridge.uri + bridge.flush_pending_change
  * RenameController constructed in do_activate alongside the other
    window-scoped controllers; nothing to dispose on deactivate
    (no GTK widget retention beyond the popover, which the popover
    itself drops via popdown's `closed` signal)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Defaults + configure docs

**Files:**
- Modify: `src/gedit_lsp/defaults.py:32-39` (DEFAULT_KEYBINDINGS), `:58-61` (enabledFeatures)
- Modify: `docs/configure.md:71-78` (keybindings table)

- [ ] **Step 5.1: Add the `rename` keybinding default**

In `src/gedit_lsp/defaults.py`, replace:

```python
DEFAULT_KEYBINDINGS: dict[str, list[str]] = {
    "hover":            ["<Primary>k"],
    "goto-definition":  ["F12"],
    "go-back":          ["<Shift>F12"],
    "references":       ["<Shift>F4"],
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
    "references":       ["<Shift>F4"],
    "rename":           ["F2"],
    "show-server-logs": [],
    "format":           ["<Primary><Shift>i"],
}
```

- [ ] **Step 5.2: Add `rename` to the default `enabledFeatures` list**

In `src/gedit_lsp/defaults.py`, replace:

```python
    "enabledFeatures": [
        "diagnostics", "hover", "definition", "outline",
        "completion", "signatureHelp", "formatting", "references",
    ],
```

with:

```python
    "enabledFeatures": [
        "diagnostics", "hover", "definition", "outline",
        "completion", "signatureHelp", "formatting", "references",
        "rename",
    ],
```

- [ ] **Step 5.3: Document the keybinding in `docs/configure.md`**

In `docs/configure.md`, locate the keybindings table (the section starting `| Action | Default | Meaning |` around line 71). Replace:

```markdown
| Action | Default | Meaning |
|---|---|---|
| `hover` | `<Primary>k` | Show the hover popover at the cursor |
| `goto-definition` | `F12` | Jump to the definition of the symbol at the cursor |
| `go-back` | `<Shift>F12` | Return to the previous cursor position |
| `references` | `<Shift>F4` | List all references to the symbol at the cursor in the bottom panel |
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
| `references` | `<Shift>F4` | List all references to the symbol at the cursor in the bottom panel |
| `rename` | `F2` | Rename the symbol at the cursor across every file the server's WorkspaceEdit touches (closed files are opened as tabs and left dirty for review) |
| `show-server-logs` | (none) | Open a dialog showing recent stderr from the active document's language server |
| `format` | `<Primary><Shift>i` | Format the document (or the selection if any) via the server |
```

- [ ] **Step 5.4: Run the full unit test suite**

Run: `env -u PYTHONPATH python -m pytest tests/unit -x`

Expected: all pass. (`test_config.py` may exercise defaults shape — if any regression there, fix and re-run.)

- [ ] **Step 5.5: Lint + typecheck**

Run:
```bash
env -u PYTHONPATH python -m ruff check src tests
env -u PYTHONPATH python -m mypy src
```

Expected: both clean.

- [ ] **Step 5.6: Commit**

```bash
git add src/gedit_lsp/defaults.py docs/configure.md
git commit -m "$(cat <<'EOF'
feat(rename): add rename to defaults + document keybinding

Default accel is F2 — the GNOME convention for "rename this thing"
(Files, Nautilus) and the VS Code precedent. Verified unbound in
gedit-46, GtkSourceView, the snippets plugin, and the schemas
(filebrowser plugin's F2 only fires when the file-browser side panel
has focus, not in the editor view).

"rename" added to enabledFeatures for completeness; matches the
discovery pattern used for "definition", "references", etc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Mark protocol-coverage, update roadmap, open the PR

**Files:**
- Modify: `docs/protocol-coverage.md` (add the rename row)
- Modify: `docs/roadmap.md` (move rename out of v0.4.0 in-progress)

- [ ] **Step 6.1: Add the protocol-coverage row**

In `docs/protocol-coverage.md`, locate the LSP method table. Add a row immediately after the existing `textDocument/references` row:

```markdown
| `textDocument/rename` (F2; popover at cursor; multi-file apply, closed files opened as tabs) | ✓ |
| `textDocument/prepareRename` (gates rename when server advertises it) | ✓ |
```

The full table now reads (relevant section, for orientation):

```markdown
| `textDocument/formatting` (Ctrl+Shift+I; whole document) | ✓ |
| `textDocument/rangeFormatting` (Ctrl+Shift+I with selection) | ✓ |
| `textDocument/references` (Shift+F4; many → "LSP References" bottom panel) | ✓ |
| `textDocument/rename` (F2; popover at cursor; multi-file apply, closed files opened as tabs) | ✓ |
| `textDocument/prepareRename` (gates rename when server advertises it) | ✓ |
```

- [ ] **Step 6.2: Move rename out of v0.4.0 in-progress in `docs/roadmap.md`**

In `docs/roadmap.md`, find the `## v0.4.0 — Sync, infrastructure, and editing operations` section (around line 28). Locate this bullet under "Editing operations:":

```markdown
- `textDocument/rename` + `prepareRename`.
```

Delete it. (The v0.4.0 release section will list the full bundle when v0.4.0 is tagged — this plan doesn't add it to "Shipped" yet because v0.4.0 isn't tagged.)

- [ ] **Step 6.3: Final full test run**

Run:
```bash
env -u PYTHONPATH python -m pytest tests/unit
env -u PYTHONPATH python -m ruff check src tests
env -u PYTHONPATH python -m mypy src
```

All three must pass cleanly.

- [ ] **Step 6.4: Commit the docs updates**

```bash
git add docs/protocol-coverage.md docs/roadmap.md
git commit -m "$(cat <<'EOF'
docs(coverage): mark textDocument/rename + prepareRename shipped

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6.5: Push the branch and open the PR**

```bash
git push -u origin feat/rename
gh pr create --title "feat(rename): textDocument/rename + prepareRename" --body "$(cat <<'EOF'
## Summary

- `textDocument/rename` + optional `textDocument/prepareRename` with `F2` keybinding and a right-click "Rename Symbol" entry
- `Gtk.Popover` near the cursor with a single `Gtk.Entry` for the new name; pre-selects the symbol; Enter commits, Escape and focus-out cancel
- Honors `renameProvider.prepareProvider`: branches on the four protocol response shapes (`null` / `Range` / `{range, placeholder}` / `{defaultBehavior: true}`); error falls back to `derive_placeholder`
- Multi-file `WorkspaceEdit` apply: closed files are opened via `Gedit.commands_load_location`; controller waits for all `loaded` signals via a remaining-counter closure, then delegates to `apply_workspace_edit` (new `workspace_edit.py` module) which reuses `apply_text_edits` from `formatting.py` per file
- Best-effort failure mode: per-file failures don't abort the whole apply; statusbar summary reports `renamed N file(s); M failed (see log)` on partial success
- Edit-flush invariant upheld: `bridge.flush_pending_change()` runs before `_send_request`, mutation-tested in unit suite

## Spec / plan

- Spec: `docs/superpowers/specs/2026-05-10-textdocument-rename-design.md`
- Plan: `docs/superpowers/plans/2026-05-10-textdocument-rename.md`

## Test plan

- [ ] `make test` passes (full unit suite)
- [ ] `ruff check` and `mypy` clean
- [ ] Linked plugin in gedit, opened a Python file with pylsp attached, placed cursor on a function with usages in two or more files (one open, one closed)
- [ ] F2 reveals the popover with the symbol pre-selected
- [ ] Typing a new name + Enter applies the rename across all affected files; closed files open as dirty tabs
- [ ] Statusbar shows `LSP: renamed N file(s)`
- [ ] Escape dismisses the popover without sending a request
- [ ] Click-elsewhere dismisses the popover without sending a request
- [ ] Right-click → LSP → Rename Symbol triggers the same flow
- [ ] Cursor on whitespace + F2 → popover with empty placeholder (server may still accept)
- [ ] Cursor on a symbol where pylsp can't rename (e.g. a stdlib name) → statusbar `LSP: cannot rename symbol here`, no popover
- [ ] `~/.local/state/gedit-lsp/plugin.log` contains a `registered action win.lsp-rename accels=['F2']` line

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After PR open, monitor CI (`gh pr checks --watch`). Address any failures with follow-up commits on the same branch.

---

## Summary

Six tasks; each lands a working unit + commit. Per-task verify gate is `pytest + ruff + mypy` (not just pytest, per feedback memory). All controllers + helpers are unit-tested without GTK widget instantiation, per the headless-CI invariant. The popover widget is excluded from automated tests; smoke testing in Task 4 is the gate.

Branch sequence:
1. workspace_edit module + tests
2. RenamePopover widget
3. RenameController + tests + mutation-tests
4. Plugin wiring + popup menu + smoke test
5. Defaults + configure docs
6. Protocol-coverage + roadmap + push + PR

## Spec / plan

- Spec: `docs/superpowers/specs/2026-05-10-textdocument-rename-design.md`
- Plan: this file

## Self-review notes

(Filled in by the plan author after writing — engineer should not need to consult these.)

- **Spec coverage check:** every spec section maps to a task. UX flow → Tasks 3 (controller) + 2 (popover) + 4 (action wiring); WorkspaceEdit application → Task 1 (helper) + Task 3 (controller orchestration); Architecture → Tasks 1-3; Error-handling table → Task 3 tests; Testing section → Tasks 1, 3 (unit) + Task 4 (smoke); Documentation → Task 5 (configure) + Task 6 (protocol-coverage, roadmap).
- **Placeholder scan:** no TBD/TODO/"add appropriate error handling" remain. Every code block is concrete. Hand-checked the long inline test files and controller body.
- **Type consistency check:**
  - `RenameController.__init__(*, window, popover_factory=None, load_uri=…, buffer_for_uri=…)` — same in Task 3 controller def, Task 3 test `_build()`, and Task 4 plugin wiring (which only passes `window=win` and lets the rest default).
  - `RenameController.trigger(server, uri, flush_pending_change)` — matches across controller def, test invocations, and plugin handler call.
  - `RenamePopover.show(*, placeholder, on_commit, on_cancel)` — keyword-only, matches in popover def (Task 2), controller's `_show_popover` (Task 3), and the test fake `_FakePopover.show` (Task 3).
  - `apply_workspace_edit(edit, *, buffer_for_uri)` — keyword-only buffer_for_uri, matches across helper def (Task 1), helper tests (Task 1), controller's `_do_apply` (Task 3), and controller tests (Task 3).
  - `derive_placeholder(buffer, cursor_line, cursor_char_utf16)` — positional, matches across helper def (Task 1), helper tests (Task 1), and controller's prepareRename branch handler (Task 3).
  - Module-level seams `_default_load_uri(window, uri, on_loaded)` and `_default_buffer_for_uri(window, uri)` — names and signatures match across controller def and the constructor defaults.
- **Mutation tests:** baked into Task 3 (steps 3.6, 3.7) per project practice.
- **Per-task verify gate:** every task's "run tests" step pairs `pytest` with `ruff check` AND `mypy` — not just pytest. Bakes in the [feedback_per_task_lint_typecheck_gates] memory.
