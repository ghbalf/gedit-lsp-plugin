# textDocument/codeAction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `textDocument/codeAction` (with `codeAction/resolve` and `workspace/executeCommand`) to the gedit LSP plugin — a diagnostic-driven gutter lightbulb + Alt+Return picker that applies server-provided quick-fixes, refactors, and source actions across one or more files.

**Architecture:** Three-unit split — `CodeActionController` (window-scoped orchestration) + `LightbulbGutter` (view-scoped visual indicator) + `CodeActionPopover` (picker UI), plus a pure `code_action.py` helpers module. Reuses `workspace_edit.apply_workspace_edit` (introduced for rename) and a refactored shared load-helper pair (lifted from rename into `navigation.py`).

**Tech Stack:** Python 3.11, PyGObject (Gtk 3, GtkSource 300, Gedit 3.0), pytest, ruff, mypy. Test seams: mocked `LanguageServer`, injected `popover_factory` / `load_uri` / `buffer_for_uri`.

---

## File structure

**Create:**
- `src/gedit_lsp/code_action.py` — pure helpers (`NormalizedAction`, `normalize_action`, `group_by_kind`, `needs_resolve`, `extract_diag_context`)
- `src/gedit_lsp/features/code_action.py` — `CodeActionController`
- `src/gedit_lsp/ui/lightbulb_gutter.py` — `LightbulbGutter`
- `src/gedit_lsp/ui/code_action_popover.py` — `CodeActionPopoverModel` + `CodeActionPopover` widget
- `tests/unit/test_code_action_helpers.py`
- `tests/unit/test_code_action_controller.py`
- `tests/unit/test_lightbulb_gutter.py`
- `tests/unit/test_code_action_popover_model.py`
- `tests/integration/test_code_action_e2e.py`

**Modify:**
- `src/gedit_lsp/navigation.py` — add `default_load_uri`, `default_buffer_for_uri` (lifted from rename)
- `src/gedit_lsp/features/rename.py` — import shared load helpers from `navigation.py` instead of defining locally
- `src/gedit_lsp/defaults.py` — add `code-action` keybinding, append `codeAction` to `enabledFeatures`
- `src/gedit_lsp/ui/popup_menu.py` — add `("Show Code Actions", "lsp-code-action")` to `MENU_ITEMS`
- `src/gedit_lsp/plugin.py` — wire action, accel, controller, per-tab gutter lifecycle, popup menu
- `docs/configure.md` — keybindings table row
- `docs/protocol-coverage.md` — three new method rows (codeAction, resolve, executeCommand)
- `docs/roadmap.md` — note codeAction shipped on PR merge (deferred to merge-time, not in this PR)

---

## Per-task verification gates

Per memory `feedback_per_task_lint_typecheck_gates`, **every task** ends with these three gates before commit:

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All three must pass cleanly. Per memory `feedback_run_full_test_tree_pre_push`, the `tests/` tree (not just `tests/unit/`) runs, because integration tests carry typed factories that catch signature drift unit tests miss.

---

## Task 1: Refactor — Lift shared load helpers from rename into navigation.py

**Rationale:** `_default_load_uri` and `_default_buffer_for_uri` in `features/rename.py:34-85` are about to be needed verbatim by `CodeActionController`. Lift them to `navigation.py` (which already owns the `Gedit.commands_load_location` wrapper `navigate_to_uri`) so both features import them. Single-PR cleanup, no behavioral change.

**Files:**
- Modify: `src/gedit_lsp/navigation.py` (append two functions)
- Modify: `src/gedit_lsp/features/rename.py:34-85` (delete the two local helpers), `src/gedit_lsp/features/rename.py:88-102` (replace defaults with new imports)
- Test: `tests/unit/test_rename_controller.py` (no test changes — same behavior, same signatures)

---

- [ ] **Step 1.1: Append the two helpers to navigation.py**

Add at the bottom of `src/gedit_lsp/navigation.py`:

```python
from pathlib import Path


def default_load_uri(
    window: Any,
    uri: str,
    on_loaded: Callable[[bool], None],
) -> None:
    """Open `uri` in `window` and call on_loaded(success) when ready.

    Uses Gedit.commands_load_location (1-indexed line/column; we pass
    1, 0 since callers don't care about cursor placement on the new
    tab) and listens for the document's `loaded` signal.

    Replaceable in unit tests via constructor injection.

    Pre-flight check: a malformed WorkspaceEdit (e.g. pylsp's
    rope_rename returns URIs rooted at "/" instead of the project
    root) would otherwise spawn a ghost error tab. Skip the load and
    report failure if the URI's path doesn't exist on disk.
    """
    gi.require_version("Gedit", "3.0")
    from gi.repository import Gedit  # type: ignore[attr-defined]

    gfile = Gio.File.new_for_uri(uri)
    path = gfile.get_path()
    if path is None or not Path(path).is_file():
        on_loaded(False)
        return
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


def default_buffer_for_uri(window: Any, uri: str) -> Any:
    """Walk window.get_documents() for the matching URI. Replaceable
    in unit tests via constructor injection.
    """
    for doc in window.get_documents():
        gfile = doc.get_file().get_location()
        if gfile is not None and gfile.get_uri() == uri:
            return doc
    return None
```

- [ ] **Step 1.2: Update rename.py to import shared helpers**

In `src/gedit_lsp/features/rename.py`:

1. Delete lines 34-85 (the two `_default_*` function definitions).
2. Delete `from pathlib import Path` at line 18 (if no other usage remains — check first).
3. Add to imports:

```python
from gedit_lsp.navigation import default_load_uri, default_buffer_for_uri
```

4. Update the `RenameController.__init__` defaults from `_default_load_uri` / `_default_buffer_for_uri` to `default_load_uri` / `default_buffer_for_uri`.

Final constructor signature should read:

```python
def __init__(
    self,
    *,
    window: Gedit.Window,
    popover_factory: Callable[[Any], RenamePopover] | None = None,
    load_uri: Callable[
        [Any, str, Callable[[bool], None]], None
    ] = default_load_uri,
    buffer_for_uri: Callable[[Any, str], Any] = default_buffer_for_uri,
) -> None:
```

- [ ] **Step 1.3: Run the rename tests to verify no behavior change**

```bash
.venv/bin/python -m pytest tests/unit/test_rename_controller.py -v
```

Expected: all tests pass (same coverage, same behavior, only the import path changed).

- [ ] **Step 1.4: Run all three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All three must pass. `mypy` is especially important — the function signatures moved across modules.

- [ ] **Step 1.5: Commit**

```bash
git add src/gedit_lsp/navigation.py src/gedit_lsp/features/rename.py
git commit -m "$(cat <<'EOF'
refactor(navigation): lift load helpers from rename for reuse

Move default_load_uri and default_buffer_for_uri from features/rename.py
into navigation.py, which already owns the Gedit.commands_load_location
wrapper. textDocument/codeAction needs them next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pure helpers — `code_action.py`

**Rationale:** Build the GTK-free helpers first. No GTK, no LSP — pure data normalization with full TDD coverage. Foundation for the controller and popover model.

**Files:**
- Create: `src/gedit_lsp/code_action.py`
- Create: `tests/unit/test_code_action_helpers.py`

---

- [ ] **Step 2.1: Write the failing test for `normalize_action` with `Command` shape**

Create `tests/unit/test_code_action_helpers.py`:

```python
"""Tests for the pure codeAction helpers."""
from __future__ import annotations

from gedit_lsp.code_action import (
    extract_diag_context,
    group_by_kind,
    needs_resolve,
    normalize_action,
)


def test_normalize_command_shape() -> None:
    # Legacy LSP `Command` shape: title + command name + arguments
    raw = {
        "title": "Apply suggestion",
        "command": "ruff.applySuggestion",
        "arguments": [{"uri": "file:///a.py"}],
    }
    result = normalize_action(raw)
    assert result is not None
    assert result["title"] == "Apply suggestion"
    assert result["kind"] == ""
    assert result["edit"] is None
    assert result["command"] == {
        "title": "Apply suggestion",
        "command": "ruff.applySuggestion",
        "arguments": [{"uri": "file:///a.py"}],
    }
    assert result["data"] is None
    assert result["is_preferred"] is False
    assert result["disabled_reason"] is None
```

- [ ] **Step 2.2: Run test, expect ImportError**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py::test_normalize_command_shape -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gedit_lsp.code_action'`.

- [ ] **Step 2.3: Create the module skeleton with `NormalizedAction` and minimal `normalize_action`**

Create `src/gedit_lsp/code_action.py`:

```python
"""Pure helpers for `textDocument/codeAction` responses.

GTK-free; importable from both controller and popover model so neither
needs polymorphic Command/CodeAction dispatch. The LSP spec lets a
codeAction response be a mixed array of `Command` and `CodeAction`
shapes; `normalize_action` coerces both into one TypedDict.
"""
from __future__ import annotations

from typing import Any, TypedDict


class NormalizedAction(TypedDict):
    title: str
    kind: str
    edit: dict[str, Any] | None
    command: dict[str, Any] | None
    data: Any
    is_preferred: bool
    disabled_reason: str | None


def normalize_action(item: Any) -> NormalizedAction | None:
    """Coerce a raw codeAction response item into a NormalizedAction,
    or return None if it's malformed (no title, or neither edit nor
    command nor data — the LSP signal that the server expects resolve).

    Accepts both the legacy `Command` shape (`{title, command,
    arguments}`) and the modern `CodeAction` shape (`{title, kind,
    edit, command, data, isPreferred, disabled}`).
    """
    if not isinstance(item, dict):
        return None
    title = item.get("title")
    if not isinstance(title, str):
        return None

    # Command shape: has a `command` field that is a *string* (the
    # command name). In CodeAction shape, `command` is a *dict*
    # (`{title, command, arguments}`) — distinguish by type.
    if isinstance(item.get("command"), str):
        return NormalizedAction(
            title=title,
            kind="",
            edit=None,
            command={
                "title": title,
                "command": item["command"],
                "arguments": item.get("arguments", []),
            },
            data=None,
            is_preferred=False,
            disabled_reason=None,
        )

    # CodeAction shape.
    cmd = item.get("command")
    if cmd is not None and not isinstance(cmd, dict):
        cmd = None

    disabled = item.get("disabled")
    disabled_reason: str | None = None
    if isinstance(disabled, dict) and isinstance(disabled.get("reason"), str):
        disabled_reason = disabled["reason"]

    edit = item.get("edit")
    if edit is not None and not isinstance(edit, dict):
        edit = None

    data = item.get("data")

    # An action with no edit, no command, and no data is unactionable
    # (per spec, server must provide at least one of these to be
    # meaningful). Treat as malformed.
    if edit is None and cmd is None and data is None:
        return None

    return NormalizedAction(
        title=title,
        kind=str(item.get("kind", "")),
        edit=edit,
        command=cmd,
        data=data,
        is_preferred=bool(item.get("isPreferred", False)),
        disabled_reason=disabled_reason,
    )
```

- [ ] **Step 2.4: Run test, expect PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py::test_normalize_command_shape -v
```

Expected: PASS.

- [ ] **Step 2.5: Add tests for the remaining `normalize_action` cases**

Append to `tests/unit/test_code_action_helpers.py`:

```python
def test_normalize_code_action_full() -> None:
    raw = {
        "title": "Extract method",
        "kind": "refactor.extract",
        "edit": {"documentChanges": []},
        "isPreferred": True,
    }
    result = normalize_action(raw)
    assert result is not None
    assert result["title"] == "Extract method"
    assert result["kind"] == "refactor.extract"
    assert result["edit"] == {"documentChanges": []}
    assert result["command"] is None
    assert result["is_preferred"] is True
    assert result["disabled_reason"] is None


def test_normalize_code_action_with_command_dict() -> None:
    raw = {
        "title": "Organize imports",
        "kind": "source.organizeImports",
        "command": {
            "title": "Organize imports",
            "command": "pylsp.organizeImports",
            "arguments": [],
        },
    }
    result = normalize_action(raw)
    assert result is not None
    assert result["edit"] is None
    assert result["command"] == {
        "title": "Organize imports",
        "command": "pylsp.organizeImports",
        "arguments": [],
    }


def test_normalize_code_action_disabled() -> None:
    raw = {
        "title": "Inline variable",
        "kind": "refactor.inline",
        "data": {"id": "x"},
        "disabled": {"reason": "Selection contains side effects"},
    }
    result = normalize_action(raw)
    assert result is not None
    assert result["disabled_reason"] == "Selection contains side effects"


def test_normalize_missing_title_returns_none() -> None:
    assert normalize_action({"command": "do.thing"}) is None
    assert normalize_action({"title": None}) is None


def test_normalize_no_edit_no_command_no_data_returns_none() -> None:
    # Action with only a title and kind — nothing to execute.
    raw = {"title": "Nope", "kind": "refactor"}
    assert normalize_action(raw) is None


def test_normalize_resolve_needed_action_keeps_data() -> None:
    # Server sends a stub with just title/kind/data — resolve will
    # populate the rest. We keep the data field so resolve can use it.
    raw = {"title": "Stub", "kind": "quickfix", "data": {"id": "fix-1"}}
    result = normalize_action(raw)
    assert result is not None
    assert result["data"] == {"id": "fix-1"}


def test_normalize_non_dict_returns_none() -> None:
    assert normalize_action("not a dict") is None
    assert normalize_action(None) is None
    assert normalize_action(42) is None
```

- [ ] **Step 2.6: Run tests, all PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py -v
```

Expected: all 7 normalize tests pass.

- [ ] **Step 2.7: Write failing tests for `group_by_kind`**

Append to `tests/unit/test_code_action_helpers.py`:

```python
def _action(title: str, kind: str) -> dict:
    """Return a minimal NormalizedAction-shape dict for grouping tests."""
    return {
        "title": title,
        "kind": kind,
        "edit": {},
        "command": None,
        "data": None,
        "is_preferred": False,
        "disabled_reason": None,
    }


def test_group_by_kind_orders_quickfix_refactor_source() -> None:
    actions = [
        _action("organize", "source.organizeImports"),
        _action("extract", "refactor.extract"),
        _action("fix", "quickfix"),
    ]
    result = group_by_kind(actions)
    # Expected order: quickfix → refactor.* → source.* → unknown
    assert [g for g, _ in result] == ["quickfix", "refactor", "source"]


def test_group_by_kind_preserves_within_group_order() -> None:
    actions = [
        _action("fix-a", "quickfix"),
        _action("fix-b", "quickfix"),
        _action("fix-c", "quickfix"),
    ]
    result = group_by_kind(actions)
    assert len(result) == 1
    titles = [a["title"] for a in result[0][1]]
    assert titles == ["fix-a", "fix-b", "fix-c"]


def test_group_by_kind_unknown_bucketed_last() -> None:
    actions = [
        _action("???", "vendor.custom"),
        _action("fix", "quickfix"),
        _action("", ""),
    ]
    result = group_by_kind(actions)
    group_names = [g for g, _ in result]
    assert group_names[0] == "quickfix"
    assert "unknown" in group_names
    assert group_names[-1] == "unknown"
```

- [ ] **Step 2.8: Run tests, expect FAIL**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py -v
```

Expected: 3 new tests fail with `ImportError: cannot import name 'group_by_kind'`.

- [ ] **Step 2.9: Implement `group_by_kind`**

Append to `src/gedit_lsp/code_action.py`:

```python
_KIND_ORDER = ("quickfix", "refactor", "source")


def group_by_kind(
    actions: list[NormalizedAction],
) -> list[tuple[str, list[NormalizedAction]]]:
    """Group actions by top-level CodeActionKind prefix.

    Groups: `quickfix` → `refactor.*` → `source.*` → `unknown` (any
    other or empty kind). Server-supplied order is preserved within
    each group.
    """
    buckets: dict[str, list[NormalizedAction]] = {
        name: [] for name in _KIND_ORDER
    }
    buckets["unknown"] = []
    for action in actions:
        kind = action["kind"]
        # Top-level prefix: "refactor.extract" → "refactor"
        top = kind.split(".", 1)[0] if kind else ""
        if top in buckets and top != "unknown":
            buckets[top].append(action)
        else:
            buckets["unknown"].append(action)
    return [(name, buckets[name]) for name in (*_KIND_ORDER, "unknown") if buckets[name]]
```

- [ ] **Step 2.10: Run tests, all PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 2.11: Write failing tests for `needs_resolve`**

Append:

```python
def test_needs_resolve_with_edit_returns_false() -> None:
    a = _action("a", "quickfix")
    a["edit"] = {"changes": {}}
    assert needs_resolve(a) is False  # type: ignore[arg-type]


def test_needs_resolve_with_command_returns_false() -> None:
    a = _action("a", "quickfix")
    a["edit"] = None
    a["command"] = {"command": "x", "title": "x", "arguments": []}
    assert needs_resolve(a) is False  # type: ignore[arg-type]


def test_needs_resolve_with_neither_returns_true() -> None:
    a = _action("a", "quickfix")
    a["edit"] = None
    a["command"] = None
    a["data"] = {"id": 1}
    assert needs_resolve(a) is True  # type: ignore[arg-type]
```

- [ ] **Step 2.12: Run, expect FAIL**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py -v
```

Expected: 3 new failures with `ImportError`.

- [ ] **Step 2.13: Implement `needs_resolve`**

Append to `src/gedit_lsp/code_action.py`:

```python
def needs_resolve(action: NormalizedAction) -> bool:
    """True if the action has neither `edit` nor `command` — server
    expects a codeAction/resolve round-trip before execution.

    `data` alone doesn't make the action executable, but its presence
    (or absence) is irrelevant to whether resolve is needed: the LSP
    spec keys resolve-required on missing edit AND missing command,
    not on the data field.
    """
    return action["edit"] is None and action["command"] is None
```

- [ ] **Step 2.14: Run, all PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py -v
```

Expected: 13 tests pass.

- [ ] **Step 2.15: Write failing tests for `extract_diag_context`**

Append:

```python
def test_extract_diag_context_cursor_inside_range() -> None:
    diagnostics = [
        {
            "range": {
                "start": {"line": 5, "character": 4},
                "end":   {"line": 5, "character": 10},
            },
            "message": "unused import",
        },
    ]
    # Cursor at (5, 7) — inside the range
    assert extract_diag_context(diagnostics, 5, 7) == diagnostics


def test_extract_diag_context_cursor_on_start_boundary() -> None:
    diagnostics = [
        {"range": {"start": {"line": 0, "character": 0},
                   "end":   {"line": 0, "character": 4}}},
    ]
    # Cursor exactly on start — included (per LSP overlap semantics)
    assert extract_diag_context(diagnostics, 0, 0) == diagnostics


def test_extract_diag_context_range_fully_before_cursor() -> None:
    diagnostics = [
        {"range": {"start": {"line": 2, "character": 0},
                   "end":   {"line": 2, "character": 5}}},
    ]
    # Cursor at (2, 10) — after the range end
    assert extract_diag_context(diagnostics, 2, 10) == []


def test_extract_diag_context_range_fully_after_cursor() -> None:
    diagnostics = [
        {"range": {"start": {"line": 5, "character": 0},
                   "end":   {"line": 5, "character": 4}}},
    ]
    # Cursor at (4, 99) — before the range start
    assert extract_diag_context(diagnostics, 4, 99) == []


def test_extract_diag_context_multiline_range() -> None:
    diagnostics = [
        {"range": {"start": {"line": 5, "character": 10},
                   "end":   {"line": 7, "character": 2}}},
    ]
    # Cursor on line 6 — inside multi-line range
    assert extract_diag_context(diagnostics, 6, 0) == diagnostics


def test_extract_diag_context_filters_mixed() -> None:
    diagnostics = [
        {"range": {"start": {"line": 1, "character": 0},
                   "end":   {"line": 1, "character": 4}}, "id": "before"},
        {"range": {"start": {"line": 5, "character": 0},
                   "end":   {"line": 5, "character": 10}}, "id": "match"},
        {"range": {"start": {"line": 9, "character": 0},
                   "end":   {"line": 9, "character": 4}}, "id": "after"},
    ]
    # Cursor at (5, 5)
    result = extract_diag_context(diagnostics, 5, 5)
    assert len(result) == 1
    assert result[0]["id"] == "match"


def test_extract_diag_context_empty_input() -> None:
    assert extract_diag_context([], 0, 0) == []
```

- [ ] **Step 2.16: Run, expect FAIL**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py -v
```

Expected: 7 new failures with `ImportError`.

- [ ] **Step 2.17: Implement `extract_diag_context`**

Append to `src/gedit_lsp/code_action.py`:

```python
def extract_diag_context(
    diagnostics: list[dict[str, Any]],
    cursor_line: int,
    cursor_char: int,
) -> list[dict[str, Any]]:
    """Filter diagnostics whose range contains the cursor position.

    Used to populate `codeAction` request's `context.diagnostics`. A
    diagnostic at position D covers the cursor iff:
        (D.start ≤ cursor) AND (cursor ≤ D.end)
    where positions compare lexicographically by (line, character).

    Boundary semantics: the cursor on `start` is *included* (matches
    LSP server behavior for "diagnostics at this point"); the cursor
    on `end` is also included (zero-width selections still cover).
    """
    cursor = (cursor_line, cursor_char)
    result: list[dict[str, Any]] = []
    for diag in diagnostics:
        rng = diag.get("range")
        if not isinstance(rng, dict):
            continue
        start = rng.get("start")
        end = rng.get("end")
        if not isinstance(start, dict) or not isinstance(end, dict):
            continue
        start_pos = (start.get("line", 0), start.get("character", 0))
        end_pos = (end.get("line", 0), end.get("character", 0))
        if start_pos <= cursor <= end_pos:
            result.append(diag)
    return result
```

- [ ] **Step 2.18: Run all helper tests, all PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_helpers.py -v
```

Expected: 20 tests pass.

- [ ] **Step 2.19: Run three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All three must pass.

- [ ] **Step 2.20: Commit**

```bash
git add src/gedit_lsp/code_action.py tests/unit/test_code_action_helpers.py
git commit -m "$(cat <<'EOF'
feat(code-action): pure helpers — normalize, group, resolve-detect, diag-context

GTK-free coercion helpers for `textDocument/codeAction` responses:
- normalize_action: Command + CodeAction shapes → one TypedDict
- group_by_kind: quickfix → refactor.* → source.* → unknown ordering
- needs_resolve: True iff neither edit nor command (per LSP spec)
- extract_diag_context: filter diagnostics overlapping cursor position

20 unit tests covering shape variants, missing fields, malformed input,
and boundary-position overlap semantics. Foundation for the controller
and popover model in the next tasks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `CodeActionPopoverModel`

**Rationale:** Extract the pure logic of the picker (action list, selection index, commit payload) from the popover widget. Lets us TDD-test the picker behavior without `Gtk.Popover` instantiation, which the headless-CI memory `project_unit_tests_avoid_gtk_widgets` forbids.

**Files:**
- Create: `src/gedit_lsp/ui/code_action_popover.py` (model class only in this task; widget added in Task 6)
- Create: `tests/unit/test_code_action_popover_model.py`

---

- [ ] **Step 3.1: Write the failing tests**

Create `tests/unit/test_code_action_popover_model.py`:

```python
"""Tests for the pure model class behind CodeActionPopover."""
from __future__ import annotations

from gedit_lsp.code_action import NormalizedAction
from gedit_lsp.ui.code_action_popover import CodeActionPopoverModel


def _action(title: str, kind: str = "quickfix", disabled: bool = False) -> NormalizedAction:
    return NormalizedAction(
        title=title,
        kind=kind,
        edit={"changes": {}},
        command=None,
        data=None,
        is_preferred=False,
        disabled_reason="reason" if disabled else None,
    )


def test_model_initial_selection_is_first_enabled() -> None:
    a = _action("first", disabled=True)
    b = _action("second")
    c = _action("third")
    m = CodeActionPopoverModel([a, b, c])
    # Disabled rows are unselectable — first selectable is index 1
    assert m.selected_index == 1
    assert m.selected_action()["title"] == "second"


def test_model_all_disabled_no_selection() -> None:
    a = _action("a", disabled=True)
    b = _action("b", disabled=True)
    m = CodeActionPopoverModel([a, b])
    assert m.selected_index is None
    assert m.selected_action() is None


def test_model_move_down_skips_disabled() -> None:
    a = _action("a")
    b = _action("b", disabled=True)
    c = _action("c")
    m = CodeActionPopoverModel([a, b, c])
    assert m.selected_index == 0
    m.move_down()
    assert m.selected_index == 2  # skipped b


def test_model_move_down_wraps_to_first_enabled() -> None:
    a = _action("a")
    b = _action("b")
    m = CodeActionPopoverModel([a, b])
    assert m.selected_index == 0
    m.move_down()
    assert m.selected_index == 1
    m.move_down()
    assert m.selected_index == 0  # wrap


def test_model_move_up_skips_disabled_and_wraps() -> None:
    a = _action("a")
    b = _action("b", disabled=True)
    c = _action("c")
    m = CodeActionPopoverModel([a, b, c])
    # Start at 0, move_up wraps to 2 (skip b)
    m.move_up()
    assert m.selected_index == 2


def test_model_empty_actions_no_selection() -> None:
    m = CodeActionPopoverModel([])
    assert m.selected_index is None
    assert m.selected_action() is None
    # Movement on empty list is a no-op
    m.move_down()
    m.move_up()
    assert m.selected_index is None


def test_model_grouped_rows_preserves_order() -> None:
    # The model accepts a flat list but groups for display via
    # group_by_kind. Verify the grouped output for rendering.
    a = _action("ext", kind="refactor.extract")
    b = _action("fix", kind="quickfix")
    m = CodeActionPopoverModel([a, b])
    groups = m.grouped_rows()
    # quickfix → refactor ordering
    assert [g for g, _ in groups] == ["quickfix", "refactor"]
```

- [ ] **Step 3.2: Run, expect FAIL**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_popover_model.py -v
```

Expected: all fail with `ModuleNotFoundError: No module named 'gedit_lsp.ui.code_action_popover'`.

- [ ] **Step 3.3: Create the model**

Create `src/gedit_lsp/ui/code_action_popover.py`:

```python
"""CodeActionPopover — picker widget + its pure model.

The model class is GTK-free and fully unit-tested. The widget class
(added later) wraps the model and adds anchoring, ListBox rendering,
and key handling.
"""
from __future__ import annotations

from gedit_lsp.code_action import NormalizedAction, group_by_kind


class CodeActionPopoverModel:
    """Pure-Python state for the codeAction picker.

    Tracks the action list, current selection index, and provides
    group_by_kind output for rendering. Disabled actions are visible
    in the list but unselectable — movement skips them.
    """

    def __init__(self, actions: list[NormalizedAction]) -> None:
        self._actions: list[NormalizedAction] = actions
        self._selected: int | None = self._first_enabled_index()

    def _first_enabled_index(self) -> int | None:
        for i, a in enumerate(self._actions):
            if a["disabled_reason"] is None:
                return i
        return None

    @property
    def selected_index(self) -> int | None:
        return self._selected

    def selected_action(self) -> NormalizedAction | None:
        if self._selected is None:
            return None
        return self._actions[self._selected]

    def move_down(self) -> None:
        if not self._actions or self._selected is None:
            return
        n = len(self._actions)
        i = self._selected
        for _ in range(n):
            i = (i + 1) % n
            if self._actions[i]["disabled_reason"] is None:
                self._selected = i
                return

    def move_up(self) -> None:
        if not self._actions or self._selected is None:
            return
        n = len(self._actions)
        i = self._selected
        for _ in range(n):
            i = (i - 1) % n
            if self._actions[i]["disabled_reason"] is None:
                self._selected = i
                return

    def grouped_rows(self) -> list[tuple[str, list[NormalizedAction]]]:
        """Return actions grouped by kind, in display order."""
        return group_by_kind(self._actions)
```

- [ ] **Step 3.4: Run, all PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_popover_model.py -v
```

Expected: 7 tests pass.

- [ ] **Step 3.5: Run three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All three pass.

- [ ] **Step 3.6: Commit**

```bash
git add src/gedit_lsp/ui/code_action_popover.py tests/unit/test_code_action_popover_model.py
git commit -m "$(cat <<'EOF'
feat(code-action): CodeActionPopoverModel — selection + group state

Pure-Python model behind the picker popover. Skip-disabled-rows
movement, wrap-around navigation, group_by_kind rendering output.
GTK-free for headless-CI unit testing per the project_unit_tests_-
avoid_gtk_widgets memory note. Widget glue (Gtk.Popover + ListBox)
added in a later task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `LightbulbGutter`

**Rationale:** Build the visual indicator next. It subscribes to a server's diagnostics listener, maintains the set of "lit lines" for one URI, and exposes a `dispose()` for the disposer pattern (memory `project_latent_diag_listener_cleanup`).

The renderer's `do_draw` requires a real GtkSourceView's gutter machinery to test end-to-end, so the unit test exercises the *state* (lit_lines computation, listener wiring, disposal) via mocks. The draw behavior is exercised in the integration test (Task 9) where a real view is available.

**Files:**
- Create: `src/gedit_lsp/ui/lightbulb_gutter.py`
- Create: `tests/unit/test_lightbulb_gutter.py`

---

- [ ] **Step 4.1: Write the failing tests**

Create `tests/unit/test_lightbulb_gutter.py`:

```python
"""Tests for LightbulbGutter — diagnostic-driven gutter indicator."""
from __future__ import annotations

from unittest.mock import MagicMock

from gedit_lsp.ui.lightbulb_gutter import LightbulbGutter


def _make_server() -> MagicMock:
    """Create a mock LanguageServer with diagnostic-listener tracking."""
    server = MagicMock()
    listeners: list = []

    def add_listener(cb):  # type: ignore[no-untyped-def]
        listeners.append(cb)
        def dispose() -> None:
            if cb in listeners:
                listeners.remove(cb)
        return dispose

    server.add_diagnostics_listener.side_effect = add_listener
    server._test_listeners = listeners
    return server


def test_listener_registered_on_construct() -> None:
    server = _make_server()
    activations: list[int] = []
    gutter = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=activations.append,
    )
    assert len(server._test_listeners) == 1
    # Avoid teardown warning
    gutter.dispose()


def test_diagnostics_populate_lit_lines() -> None:
    server = _make_server()
    gutter = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    # Simulate publishDiagnostics
    server._test_listeners[0]({
        "uri": "file:///a.py",
        "diagnostics": [
            {"range": {"start": {"line": 3, "character": 0}, "end": {"line": 3, "character": 4}}},
            {"range": {"start": {"line": 7, "character": 0}, "end": {"line": 7, "character": 4}}},
            {"range": {"start": {"line": 3, "character": 5}, "end": {"line": 3, "character": 9}}},
        ],
    })
    assert gutter.lit_lines() == {3, 7}
    gutter.dispose()


def test_diagnostics_for_other_uri_ignored() -> None:
    server = _make_server()
    gutter = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    server._test_listeners[0]({
        "uri": "file:///OTHER.py",
        "diagnostics": [
            {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 4}}},
        ],
    })
    assert gutter.lit_lines() == set()
    gutter.dispose()


def test_empty_diagnostics_clears_lit_lines() -> None:
    server = _make_server()
    gutter = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    # First, lit lines
    server._test_listeners[0]({
        "uri": "file:///a.py",
        "diagnostics": [
            {"range": {"start": {"line": 3, "character": 0}, "end": {"line": 3, "character": 4}}},
        ],
    })
    assert gutter.lit_lines() == {3}
    # Then, server reports empty
    server._test_listeners[0]({"uri": "file:///a.py", "diagnostics": []})
    assert gutter.lit_lines() == set()
    gutter.dispose()


def test_dispose_removes_listener_and_renderer() -> None:
    server = _make_server()
    view = MagicMock()
    gutter_obj = MagicMock()
    view.get_gutter.return_value = gutter_obj
    g = LightbulbGutter(
        view=view, server=server, uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    assert len(server._test_listeners) == 1
    g.dispose()
    assert len(server._test_listeners) == 0
    gutter_obj.remove.assert_called_once()


def test_double_dispose_is_safe() -> None:
    server = _make_server()
    view = MagicMock()
    view.get_gutter.return_value = MagicMock()
    g = LightbulbGutter(
        view=view, server=server, uri="file:///a.py",
        on_activate=lambda _line: None,
    )
    g.dispose()
    g.dispose()  # must not raise


def test_activate_line_calls_callback() -> None:
    server = _make_server()
    activations: list[int] = []
    g = LightbulbGutter(
        view=MagicMock(),
        server=server,
        uri="file:///a.py",
        on_activate=activations.append,
    )
    g._fire_activate_for_test(line=5)
    assert activations == [5]
    g.dispose()
```

- [ ] **Step 4.2: Run, expect FAIL with ImportError**

```bash
.venv/bin/python -m pytest tests/unit/test_lightbulb_gutter.py -v
```

Expected: all fail with `ModuleNotFoundError`.

- [ ] **Step 4.3: Implement `LightbulbGutter`**

Create `src/gedit_lsp/ui/lightbulb_gutter.py`:

```python
"""LightbulbGutter — diagnostic-driven gutter indicator.

One per GtkSourceView. Subscribes to one server's diagnostics
listener, maintains the set of "lit" line numbers for its URI, and
renders a lightbulb icon in the gutter on those lines. Click on the
icon fires the `on_activate(line)` callback (typically the
CodeActionController's trigger entry point).

Disposal contract: call `dispose()` from the plugin's `tab-removed`
handler. Idempotent — see memory project_latent_diag_listener_cleanup.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gdk, GdkPixbuf, Gtk, GtkSource

logger = logging.getLogger("gedit_lsp.lightbulb")

# Priority offset for the gutter renderer. Positive places the bulb
# to the right of the line-number column (closer to the text). Final
# value verified empirically with ./install.sh — adjust if it lands
# in the wrong column.
_GUTTER_PRIORITY = 20

_ICON_NAME = "dialog-information-symbolic"
_ICON_SIZE_PX = 12


class _LightbulbRenderer(GtkSource.GutterRendererPixbuf):  # type: ignore[misc]
    """GtkSourceGutterRendererPixbuf subclass painting an icon on lit lines.

    Kept private and minimal — the renderer asks `_owner` for the current
    lit set via a callable, so the renderer doesn't hold state of its own.
    """

    def __init__(self, lit_lines_getter: Callable[[], set[int]]) -> None:
        super().__init__()
        self._lit_lines_getter = lit_lines_getter
        # Pre-render the pixbuf once
        icon_theme = Gtk.IconTheme.get_default()
        try:
            pixbuf = icon_theme.load_icon(
                _ICON_NAME, _ICON_SIZE_PX,
                Gtk.IconLookupFlags.USE_BUILTIN,
            )
        except Exception:  # noqa: BLE001 — theme misconfigured
            pixbuf = None
        self._pixbuf: GdkPixbuf.Pixbuf | None = pixbuf
        self.set_size(_ICON_SIZE_PX)

    def do_draw(
        self,
        cr: Any,
        background_area: Any,
        cell_area: Any,
        start: Gtk.TextIter,
        end: Gtk.TextIter,
        state: Any,
    ) -> None:
        line = start.get_line()
        if line not in self._lit_lines_getter():
            return
        if self._pixbuf is None:
            return
        # Render centered in cell
        x = cell_area.x + (cell_area.width - _ICON_SIZE_PX) // 2
        y = cell_area.y + (cell_area.height - _ICON_SIZE_PX) // 2
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, x, y)
        cr.paint()


class LightbulbGutter:
    """One per GtkSourceView. Maintains lit-line state and renderer
    attachment for one URI's diagnostics."""

    def __init__(
        self,
        *,
        view: Any,
        server: Any,
        uri: str,
        on_activate: Callable[[int], None],
    ) -> None:
        self._view = view
        self._uri = uri
        self._on_activate = on_activate
        self._lit_lines: set[int] = set()
        self._disposed = False

        self._renderer = _LightbulbRenderer(lambda: self._lit_lines)
        self._gutter = view.get_gutter(Gtk.TextWindowType.LEFT)
        self._gutter.insert(self._renderer, _GUTTER_PRIORITY)

        # Click handler on the renderer
        self._click_handler_id = self._renderer.connect(
            "activate", self._on_renderer_activated,
        )

        self._listener_disposer = server.add_diagnostics_listener(
            self._on_diagnostics,
        )

    def lit_lines(self) -> set[int]:
        """Return a copy of the current lit-line set (for tests)."""
        return set(self._lit_lines)

    def dispose(self) -> None:
        """Detach listener, remove renderer. Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        try:
            self._listener_disposer()
        except Exception:  # noqa: BLE001 — disposer should be safe; log if not
            logger.info("lightbulb: listener disposer raised")
        try:
            self._gutter.remove(self._renderer)
        except Exception:  # noqa: BLE001 — view may already be torn down
            logger.info("lightbulb: gutter renderer remove raised")

    def _on_diagnostics(self, params: dict[str, Any]) -> None:
        if params.get("uri") != self._uri:
            return
        new_lines: set[int] = set()
        for d in params.get("diagnostics", []):
            rng = d.get("range")
            if not isinstance(rng, dict):
                continue
            start = rng.get("start")
            if isinstance(start, dict) and isinstance(start.get("line"), int):
                new_lines.add(start["line"])
        self._lit_lines = new_lines
        try:
            self._view.queue_draw()
        except Exception:  # noqa: BLE001 — view torn down
            pass

    def _on_renderer_activated(
        self, _renderer: Any, it: Gtk.TextIter, _area: Any, _event: Any,
    ) -> None:
        line = it.get_line()
        self._on_activate(line)

    # --- test seam ---
    def _fire_activate_for_test(self, *, line: int) -> None:
        self._on_activate(line)
```

- [ ] **Step 4.4: Run lightbulb tests, expect PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_lightbulb_gutter.py -v
```

Expected: 7 tests pass.

- [ ] **Step 4.5: Three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All pass.

- [ ] **Step 4.6: Commit**

```bash
git add src/gedit_lsp/ui/lightbulb_gutter.py tests/unit/test_lightbulb_gutter.py
git commit -m "$(cat <<'EOF'
feat(code-action): LightbulbGutter — diagnostic-driven gutter indicator

GtkSourceGutterRendererPixbuf subclass painting dialog-information-
symbolic on lines with diagnostics. One instance per GtkSourceView,
subscribes to one server's diagnostics listener for one URI, maintains
the lit-line set, fires on_activate(line) on icon click.

dispose() detaches listener (via the disposer returned by add_-
diagnostics_listener) and removes the renderer. Idempotent — second
call is a no-op, per the listener-cleanup memory.

7 unit tests cover state computation, URI filtering, disposal, and
the activate-callback contract. Renderer paint behavior is exercised
in the integration test (Task 9) with a real view.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `CodeActionController` — basic dispatch (capability gate, request, response routing)

**Rationale:** Build the controller incrementally. This first slice handles capability gating, edit-flush invariant, context assembly, request send, and response → popover dispatch. Resolve, executeCommand, multi-file load, and window-closed guard are added in subsequent sub-tasks (5b/5c/5d).

**Files:**
- Create: `src/gedit_lsp/features/code_action.py`
- Create: `tests/unit/test_code_action_controller.py`

---

- [ ] **Step 5a.1: Write the failing test for capability gate**

Create `tests/unit/test_code_action_controller.py`:

```python
"""Tests for CodeActionController."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from gedit_lsp.features.code_action import CodeActionController


class FakeServer:
    """Minimal fake of LanguageServer for controller tests."""

    def __init__(self, capability: Any = True) -> None:
        self._capability = capability
        self.requests: list[tuple[str, dict, Any]] = []  # (method, params, cb)
        self.notifications: list[tuple[str, dict]] = []

    def capability(self, key: str) -> Any:
        return self._capability if key == "codeActionProvider" else None

    def _send_request(self, method: str, params: dict, cb: Any) -> int:
        self.requests.append((method, params, cb))
        return len(self.requests)

    def send_notification(self, method: str, params: dict) -> None:
        self.notifications.append((method, params))


def _make_window(*, statusbar: Any = None, view: Any = None) -> Any:
    win = MagicMock()
    win.get_statusbar.return_value = statusbar or MagicMock()
    win.get_active_view.return_value = view
    return win


def _make_view_at_cursor(line: int = 0, char: int = 0) -> Any:
    """Return a MagicMock view whose buffer's insert iter is at (line, char)."""
    view = MagicMock()
    buf = MagicMock()
    insert_iter = MagicMock()
    insert_iter.get_line.return_value = line
    insert_iter.get_line_offset.return_value = char  # UTF-8; UTF-16 via patch
    buf.get_iter_at_mark.return_value = insert_iter
    buf.get_insert.return_value = MagicMock()
    view.get_buffer.return_value = buf
    return view


def test_no_capability_means_statusbar_message_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=None)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    controller = CodeActionController(window=window)
    flush = MagicMock()
    diags = MagicMock(return_value=[])

    controller.trigger(server, "file:///a.py", flush, diags)

    assert server.requests == []
    statusbar.push.assert_called_once()
    msg = statusbar.push.call_args[0][1]
    assert "code action" in msg.lower()
    flush.assert_not_called()
```

- [ ] **Step 5a.2: Run, expect FAIL with ImportError**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py -v
```

Expected: fail with `ModuleNotFoundError`.

- [ ] **Step 5a.3: Implement controller skeleton with capability gate only**

Create `src/gedit_lsp/features/code_action.py`:

```python
"""CodeActionController: textDocument/codeAction orchestration.

Window-scoped controller. trigger() is the entry point — invoked from
the Alt+Return keybind, the lightbulb-click callback, or the popup-
menu entry. Mirrors RenameController in shape: capability-gate,
edit-flush, request, response dispatch via popover, commit applies
the edit (and/or executes the command, with codeAction/resolve when
needed).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from gedit_lsp.code_action import (
    NormalizedAction,
    extract_diag_context,
    needs_resolve,
    normalize_action,
)
from gedit_lsp.navigation import default_buffer_for_uri, default_load_uri
from gedit_lsp.utf16 import text_iter_to_utf16
from gedit_lsp.workspace_edit import apply_workspace_edit

if TYPE_CHECKING:
    from gi.repository import Gedit  # type: ignore[attr-defined]

    from gedit_lsp.server import LanguageServer
    from gedit_lsp.ui.code_action_popover import CodeActionPopover


logger = logging.getLogger("gedit_lsp.code_action")


class CodeActionController:
    def __init__(
        self,
        *,
        window: Gedit.Window,
        popover_factory: Callable[[Any], CodeActionPopover] | None = None,
        load_uri: Callable[
            [Any, str, Callable[[bool], None]], None
        ] = default_load_uri,
        buffer_for_uri: Callable[[Any, str], Any] = default_buffer_for_uri,
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
        diagnostics_for_uri: Callable[[str], list[dict[str, Any]]],
        cursor_line: int | None = None,
    ) -> None:
        statusbar = self._window.get_statusbar()
        if not server.capability("codeActionProvider"):
            logger.info("code-action: server does not support codeActionProvider")
            statusbar.push(0, "LSP: server does not support code actions")
            return

        # Further steps added in 5a.4+
        raise NotImplementedError("trigger flow not yet complete")
```

- [ ] **Step 5a.4: Run capability-gate test, expect PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py::test_no_capability_means_statusbar_message_no_request -v
```

Expected: PASS.

- [ ] **Step 5a.5: Write failing tests for the full request-dispatch flow**

Append to `tests/unit/test_code_action_controller.py`:

```python
def _patch_utf16(monkeypatch: pytest.MonkeyPatch, *, line: int, char: int) -> None:
    """Patch text_iter_to_utf16 to return predictable (line, char)."""
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.text_iter_to_utf16",
        lambda _it: (line, char),
    )


def test_trigger_flushes_then_sends_request(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)

    calls: list[str] = []
    def flush() -> None:
        calls.append("flush")
        # Recording the order: flush must precede the send
        assert server.requests == [], "flush must happen before send"

    controller = CodeActionController(window=window)
    _patch_utf16(monkeypatch, line=5, char=2)

    controller.trigger(
        server, "file:///a.py", flush,
        diagnostics_for_uri=lambda _uri: [],
    )

    assert calls == ["flush"]
    assert len(server.requests) == 1
    method, params, _cb = server.requests[0]
    assert method == "textDocument/codeAction"
    assert params["textDocument"] == {"uri": "file:///a.py"}
    assert params["range"]["start"] == {"line": 5, "character": 2}
    assert params["range"]["end"] == {"line": 5, "character": 2}
    assert params["context"]["triggerKind"] == 1
    assert params["context"]["diagnostics"] == []


def test_trigger_passes_overlapping_diagnostics_in_context(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)
    controller = CodeActionController(window=window)
    _patch_utf16(monkeypatch, line=3, char=4)

    diags_at_other_line = [
        {"range": {"start": {"line": 99, "character": 0}, "end": {"line": 99, "character": 1}}, "id": "off"},
    ]
    diags_overlapping = {
        "range": {"start": {"line": 3, "character": 0}, "end": {"line": 3, "character": 10}},
        "id": "match",
    }

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [diags_overlapping, *diags_at_other_line],
    )

    _, params, _ = server.requests[0]
    assert len(params["context"]["diagnostics"]) == 1
    assert params["context"]["diagnostics"][0]["id"] == "match"


def test_trigger_no_view_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    window = _make_window(view=None)
    controller = CodeActionController(window=window)
    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    assert server.requests == []


def test_response_error_statusbar_no_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    popover = MagicMock()
    controller = CodeActionController(
        window=window, popover_factory=lambda _v: popover,
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, cb = server.requests[0]
    cb({"error": {"code": -32603, "message": "bad"}})

    popover.show.assert_not_called()
    pushed = [c.args[1] for c in statusbar.push.call_args_list]
    assert any("failed" in m.lower() for m in pushed)


def test_response_null_statusbar_no_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    popover = MagicMock()
    controller = CodeActionController(
        window=window, popover_factory=lambda _v: popover,
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, cb = server.requests[0]
    cb({"result": None})

    popover.show.assert_not_called()
    pushed = [c.args[1] for c in statusbar.push.call_args_list]
    assert any("no code actions" in m.lower() for m in pushed)


def test_response_empty_list_statusbar_no_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    popover = MagicMock()
    controller = CodeActionController(
        window=window, popover_factory=lambda _v: popover,
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, cb = server.requests[0]
    cb({"result": []})

    popover.show.assert_not_called()
    pushed = [c.args[1] for c in statusbar.push.call_args_list]
    assert any("no code actions" in m.lower() for m in pushed)


def test_response_with_actions_shows_popover(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)
    popover = MagicMock()
    controller = CodeActionController(
        window=window, popover_factory=lambda _v: popover,
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, cb = server.requests[0]
    cb({"result": [
        {"title": "Fix import", "kind": "quickfix", "edit": {"changes": {}}},
    ]})

    popover.show.assert_called_once()
    actions = popover.show.call_args.kwargs["actions"]
    assert len(actions) == 1
    assert actions[0]["title"] == "Fix import"


def test_lightbulb_cursor_line_repositions_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor(line=0, char=0)
    buf = view.get_buffer.return_value
    line_iter = MagicMock()
    buf.get_iter_at_line.return_value = line_iter
    window = _make_window(view=view)
    controller = CodeActionController(window=window)
    _patch_utf16(monkeypatch, line=8, char=0)

    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
        cursor_line=8,
    )

    buf.get_iter_at_line.assert_called_once_with(8)
    buf.place_cursor.assert_called_once_with(line_iter)
```

- [ ] **Step 5a.6: Run, expect FAIL (most cases hit NotImplementedError)**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py -v
```

Expected: most fail with `NotImplementedError`.

- [ ] **Step 5a.7: Replace the `NotImplementedError` with the full trigger flow up to popover dispatch**

In `src/gedit_lsp/features/code_action.py`, replace the body of `trigger()`:

```python
    def trigger(
        self,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None],
        diagnostics_for_uri: Callable[[str], list[dict[str, Any]]],
        cursor_line: int | None = None,
    ) -> None:
        statusbar = self._window.get_statusbar()
        if not server.capability("codeActionProvider"):
            logger.info("code-action: server does not support codeActionProvider")
            statusbar.push(0, "LSP: server does not support code actions")
            return

        view = self._window.get_active_view()
        if view is None:
            logger.info("code-action: no active view")
            return

        buf = view.get_buffer()
        if cursor_line is not None:
            buf.place_cursor(buf.get_iter_at_line(cursor_line))
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line, char = text_iter_to_utf16(cursor)

        # Edit-flush invariant: server must see latest text before
        # answering "what can I do here?". See memory:
        # project_edit_triggered_flush_invariant.
        flush_pending_change()

        diags_at = extract_diag_context(diagnostics_for_uri(uri), line, char)
        params = {
            "textDocument": {"uri": uri},
            "range": {
                "start": {"line": line, "character": char},
                "end":   {"line": line, "character": char},
            },
            "context": {
                "diagnostics": diags_at,
                "triggerKind": 1,  # Invoked (manual)
            },
        }

        def on_response(msg: dict[str, Any]) -> None:
            self._dispatch_response(msg, server, view)

        logger.info("code-action: send line=%d char=%d", line, char)
        server._send_request("textDocument/codeAction", params, on_response)

    def _dispatch_response(
        self, msg: dict[str, Any], server: LanguageServer, view: Any,
    ) -> None:
        statusbar = self._window.get_statusbar()
        if msg.get("error"):
            logger.info("code-action: server error %r", msg.get("error"))
            statusbar.push(0, "LSP: code action request failed")
            return
        result = msg.get("result")
        if result is None or result == []:
            statusbar.push(0, "LSP: no code actions")
            return
        if not isinstance(result, list):
            statusbar.push(0, "LSP: no code actions")
            return
        actions: list[NormalizedAction] = []
        for item in result:
            normalized = normalize_action(item)
            if normalized is not None:
                actions.append(normalized)
        if not actions:
            statusbar.push(0, "LSP: no code actions")
            return

        factory = self._popover_factory
        if factory is None:
            from gedit_lsp.ui.code_action_popover import CodeActionPopover
            factory = CodeActionPopover
        popover = factory(view)
        popover.show(
            actions=actions,
            on_commit=lambda action: self._commit(action, server),
            on_cancel=lambda: None,
        )

    def _commit(
        self, action: NormalizedAction, server: LanguageServer,
    ) -> None:
        # Resolve / execute logic added in Task 5b/5c.
        raise NotImplementedError("commit flow added in next sub-task")
```

- [ ] **Step 5a.8: Run all controller tests so far, expect PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5a.9: Three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All three pass.

- [ ] **Step 5a.10: Commit**

```bash
git add src/gedit_lsp/features/code_action.py tests/unit/test_code_action_controller.py
git commit -m "$(cat <<'EOF'
feat(code-action): controller dispatch — capability, flush, request, popover

CodeActionController trigger flow: capability gate, optional cursor
repositioning (lightbulb-click path), edit-flush invariant, context
assembly with overlapping-diagnostic filter, request send, response
dispatch into popover or status-bar message.

8 unit tests cover the dispatch surface. Resolve and execute paths
follow in the next sub-task — commit flow currently raises
NotImplementedError.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5b: `CodeActionController` — commit flow (resolve, execute, single-file edit)

**Rationale:** Now wire the popover's commit callback. For actions that need resolve, fire `codeAction/resolve` first. Then apply the edit (single-file case, no closed-file load yet) and/or send `workspace/executeCommand`.

**Files:**
- Modify: `src/gedit_lsp/features/code_action.py` (replace `_commit` body, add `_execute`)
- Modify: `tests/unit/test_code_action_controller.py` (append commit-flow tests)

---

- [ ] **Step 5b.1: Append failing tests for the commit flow**

Append to `tests/unit/test_code_action_controller.py`:

```python
def _commit_via_popover(controller: Any, server: FakeServer, action_dict: dict[str, Any]) -> None:
    """Drive the controller through trigger() and pull the commit
    callback off the popover.show() call."""
    popover = MagicMock()
    controller._popover_factory = lambda _v: popover
    # Trigger
    controller.trigger(
        server, "file:///a.py", lambda: None,
        diagnostics_for_uri=lambda _uri: [],
    )
    _, _, response_cb = server.requests[0]
    response_cb({"result": [action_dict]})
    # Pull the on_commit
    commit_cb = popover.show.call_args.kwargs["on_commit"]
    action = popover.show.call_args.kwargs["actions"][0]
    commit_cb(action)


def test_commit_edit_only_applies_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)
    applied_edits: list[Any] = []
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (applied_edits.append(edit), ([], []))[1],
    )
    _patch_utf16(monkeypatch, line=0, char=0)
    controller = CodeActionController(window=window)

    edit = {"changes": {"file:///a.py": []}}
    _commit_via_popover(controller, server, {
        "title": "Apply", "kind": "quickfix", "edit": edit,
    })

    assert applied_edits == [edit]
    # No executeCommand should be sent
    assert all(m != "workspace/executeCommand" for m, _, _ in server.requests)


def test_commit_command_only_sends_execute_command(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.apply_workspace_edit",
        lambda *_a, **_k: ([], []),
    )
    _patch_utf16(monkeypatch, line=0, char=0)
    controller = CodeActionController(window=window)

    cmd = {"title": "Run", "command": "do.thing", "arguments": []}
    _commit_via_popover(controller, server, {
        "title": "Run", "kind": "quickfix", "command": cmd,
    })

    exec_calls = [(m, p) for m, p, _ in server.requests if m == "workspace/executeCommand"]
    assert len(exec_calls) == 1
    _, params = exec_calls[0]
    assert params == cmd


def test_commit_edit_and_command_edits_first_then_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)
    order: list[str] = []
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.apply_workspace_edit",
        lambda *_a, **_k: (order.append("edit"), ([], []))[1],
    )
    # Patch _send_request to record method order
    orig_send = server._send_request
    def tracked_send(method: str, params: dict, cb: Any) -> int:
        if method == "workspace/executeCommand":
            order.append("command")
        return orig_send(method, params, cb)
    server._send_request = tracked_send  # type: ignore[method-assign]

    _patch_utf16(monkeypatch, line=0, char=0)
    controller = CodeActionController(window=window)

    edit = {"changes": {"file:///a.py": []}}
    cmd = {"title": "After", "command": "do.thing", "arguments": []}
    _commit_via_popover(controller, server, {
        "title": "Combo", "kind": "quickfix", "edit": edit, "command": cmd,
    })

    assert order == ["edit", "command"]


def test_commit_needs_resolve_fires_resolve_then_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)
    applied: list[Any] = []
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (applied.append(edit), ([], []))[1],
    )
    _patch_utf16(monkeypatch, line=0, char=0)
    controller = CodeActionController(window=window)

    # Action with only `data` — needs_resolve True
    _commit_via_popover(controller, server, {
        "title": "Stub", "kind": "quickfix", "data": {"id": "fix-1"},
    })

    # First the request, then resolve. Find resolve.
    resolve_calls = [(p, cb) for m, p, cb in server.requests if m == "codeAction/resolve"]
    assert len(resolve_calls) == 1
    resolve_params, resolve_cb = resolve_calls[0]
    # Resolve must carry the original action's data
    assert resolve_params["data"] == {"id": "fix-1"}

    # Server responds with the populated action
    resolve_cb({"result": {
        "title": "Stub", "kind": "quickfix",
        "edit": {"changes": {"file:///a.py": []}},
    }})

    # Now the edit must have been applied
    assert len(applied) == 1


def test_commit_resolve_error_statusbar_no_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    statusbar = MagicMock()
    view = _make_view_at_cursor()
    window = _make_window(statusbar=statusbar, view=view)
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.apply_workspace_edit",
        lambda *_a, **_k: ([], []),
    )
    _patch_utf16(monkeypatch, line=0, char=0)
    controller = CodeActionController(window=window)

    _commit_via_popover(controller, server, {
        "title": "Stub", "kind": "quickfix", "data": {"id": "x"},
    })
    resolve_cb = next(
        cb for m, _, cb in server.requests if m == "codeAction/resolve"
    )
    resolve_cb({"error": {"code": -32603, "message": "fail"}})

    pushed = [c.args[1] for c in statusbar.push.call_args_list]
    assert any("could not resolve" in m.lower() for m in pushed)
```

- [ ] **Step 5b.2: Run, expect 5 new failures with `NotImplementedError`**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py -v
```

- [ ] **Step 5b.3: Replace `_commit` body and add `_execute`**

In `src/gedit_lsp/features/code_action.py`, replace `_commit` and add helpers:

```python
    def _commit(
        self, action: NormalizedAction, server: LanguageServer,
    ) -> None:
        if needs_resolve(action):
            def on_resolved(msg: dict[str, Any]) -> None:
                statusbar = self._window.get_statusbar()
                if msg.get("error"):
                    logger.info("code-action: resolve error %r", msg.get("error"))
                    statusbar.push(0, "LSP: could not resolve action")
                    return
                resolved_raw = msg.get("result") or {}
                resolved = normalize_action(resolved_raw)
                if resolved is None:
                    statusbar.push(0, "LSP: could not resolve action")
                    return
                self._execute(resolved, server)

            # Pass the original action (with data) for the server to
            # complete. Use the raw shape; LSP expects the same fields
            # we received from textDocument/codeAction.
            raw = {
                "title": action["title"],
                "kind": action["kind"],
                "data": action["data"],
            }
            server._send_request("codeAction/resolve", raw, on_resolved)
            return
        self._execute(action, server)

    def _execute(
        self, action: NormalizedAction, server: LanguageServer,
    ) -> None:
        statusbar = self._window.get_statusbar()
        has_edit = action["edit"] is not None
        has_command = action["command"] is not None

        applied: list[str] = []
        failed: list[str] = []

        if has_edit:
            try:
                applied, failed = apply_workspace_edit(
                    action["edit"],
                    buffer_for_uri=lambda u: self._buffer_for_uri(self._window, u),
                )
            except RuntimeError as exc:
                logger.info("code-action: window closed mid-apply (%r)", exc)
                return

        if has_command:
            cmd = action["command"]
            # Per spec it's a request; in practice servers return null.
            # Fire with a no-op callback for spec correctness.
            server._send_request(
                "workspace/executeCommand", cmd, lambda _msg: None,
            )

        if applied or has_command:
            statusbar.push(0, f"LSP: applied {action['title']}")
        elif failed:
            statusbar.push(0,
                f"LSP: applied {len(applied)} file(s); {len(failed)} failed (see log)")
        else:
            statusbar.push(0, "LSP: nothing to apply")
```

- [ ] **Step 5b.4: Run all controller tests, expect PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py -v
```

Expected: 13 tests pass.

- [ ] **Step 5b.5: Three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All pass.

- [ ] **Step 5b.6: Commit**

```bash
git add src/gedit_lsp/features/code_action.py tests/unit/test_code_action_controller.py
git commit -m "$(cat <<'EOF'
feat(code-action): controller commit flow — resolve, execute, edit-first ordering

_commit and _execute round out the single-file apply path:
- needs_resolve actions fire codeAction/resolve before executing
- edit + command actions apply edit first, then send executeCommand
- resolve errors surface as 'could not resolve action' statusbar msg
- spec-correct shape for executeCommand (request with no-op callback)

5 new unit tests cover edit-only, command-only, edit+command ordering,
needs-resolve round-trip, and resolve-error handling.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5c: `CodeActionController` — cross-file load-settle

**Rationale:** When a `WorkspaceEdit` touches files not currently open, load them via `Gedit.commands_load_location` and wait for all to settle before applying. Identical pattern to rename's `_begin_apply` / `_on_one_loaded`.

**Files:**
- Modify: `src/gedit_lsp/features/code_action.py` (extract apply into `_apply_with_load`)
- Modify: `tests/unit/test_code_action_controller.py` (append multi-file tests)

---

- [ ] **Step 5c.1: Append failing tests for multi-file load-settle**

Append to `tests/unit/test_code_action_controller.py`:

```python
def test_commit_multifile_edit_loads_closed_files_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)

    apply_calls: list[Any] = []
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (apply_calls.append(edit), ([], []))[1],
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    # buffer_for_uri: a.py is open, b.py is closed
    def buffer_for_uri(_win: Any, uri: str) -> Any:
        return MagicMock() if uri == "file:///a.py" else None

    loads: list[tuple[str, Any]] = []
    def load_uri(_win: Any, uri: str, on_loaded: Any) -> None:
        loads.append((uri, on_loaded))

    controller = CodeActionController(
        window=window,
        load_uri=load_uri,
        buffer_for_uri=buffer_for_uri,
    )

    edit = {
        "changes": {
            "file:///a.py": [],
            "file:///b.py": [],
        }
    }
    _commit_via_popover(controller, server, {
        "title": "Multi", "kind": "quickfix", "edit": edit,
    })

    # apply not yet fired — waiting on b.py load
    assert apply_calls == []
    assert len(loads) == 1
    assert loads[0][0] == "file:///b.py"

    # Simulate load completion
    loads[0][1](True)
    assert apply_calls == [edit]


def test_commit_multifile_edit_fires_apply_after_all_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    window = _make_window(view=view)

    apply_calls: list[Any] = []
    monkeypatch.setattr(
        "gedit_lsp.features.code_action.apply_workspace_edit",
        lambda edit, *, buffer_for_uri: (apply_calls.append(edit), ([], []))[1],
    )
    _patch_utf16(monkeypatch, line=0, char=0)

    def buffer_for_uri(_w: Any, _uri: str) -> Any:
        return None  # everything closed

    loads: list[tuple[str, Any]] = []
    def load_uri(_w: Any, uri: str, on_loaded: Any) -> None:
        loads.append((uri, on_loaded))

    controller = CodeActionController(
        window=window, load_uri=load_uri, buffer_for_uri=buffer_for_uri,
    )

    edit = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///a.py"}, "edits": []},
            {"textDocument": {"uri": "file:///b.py"}, "edits": []},
        ]
    }
    _commit_via_popover(controller, server, {
        "title": "Multi", "kind": "quickfix", "edit": edit,
    })

    assert len(loads) == 2
    assert apply_calls == []
    # Settle them out-of-order: b first, then a
    loads[1][1](True)
    assert apply_calls == []
    loads[0][1](True)
    assert apply_calls == [edit]


def test_window_closed_during_apply_no_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeServer(capability=True)
    view = _make_view_at_cursor()
    statusbar = MagicMock()
    statusbar.push.side_effect = RuntimeError("destroyed")
    window = _make_window(statusbar=statusbar, view=view)

    monkeypatch.setattr(
        "gedit_lsp.features.code_action.apply_workspace_edit",
        lambda *_a, **_k: ([], []),
    )
    _patch_utf16(monkeypatch, line=0, char=0)
    controller = CodeActionController(window=window)

    # Should not raise
    _commit_via_popover(controller, server, {
        "title": "Apply", "kind": "quickfix",
        "edit": {"changes": {"file:///a.py": []}},
    })
```

- [ ] **Step 5c.2: Run, expect 3 new failures**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py -v
```

- [ ] **Step 5c.3: Add cross-file load-settle to `_execute`**

In `src/gedit_lsp/features/code_action.py`, change `_execute` to wrap edit-apply in `_apply_with_load`. Replace the existing `_execute` body and add the new helpers:

```python
    def _execute(
        self, action: NormalizedAction, server: LanguageServer,
    ) -> None:
        has_edit = action["edit"] is not None
        has_command = action["command"] is not None

        if has_edit:
            def after_edit(applied: list[str], failed: list[str]) -> None:
                self._finish(applied, failed, has_command, action, server)
            self._apply_with_load(action["edit"], after_edit)
        else:
            self._finish([], [], has_command, action, server)

    def _apply_with_load(
        self,
        edit: dict[str, Any],
        on_done: Callable[[list[str], list[str]], None],
    ) -> None:
        uris = self._collect_uris(edit)
        to_load = [
            u for u in uris
            if self._buffer_for_uri(self._window, u) is None
        ]

        def do_apply() -> None:
            try:
                applied, failed = apply_workspace_edit(
                    edit,
                    buffer_for_uri=lambda u: self._buffer_for_uri(self._window, u),
                )
            except RuntimeError as exc:
                logger.info("code-action: window closed mid-apply (%r)", exc)
                return
            on_done(applied, failed)

        if not to_load:
            do_apply()
            return

        remaining = [len(to_load)]

        def on_one_loaded(_uri: str, _ok: bool) -> None:
            remaining[0] -= 1
            if remaining[0] == 0:
                do_apply()

        def make_cb(u: str) -> Callable[[bool], None]:
            def cb(ok: bool) -> None:
                on_one_loaded(u, ok)
            return cb

        for u in to_load:
            self._load_uri(self._window, u, make_cb(u))

    @staticmethod
    def _collect_uris(edit: Any) -> list[str]:
        if not isinstance(edit, dict):
            return []
        uris: list[str] = []
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

    def _finish(
        self,
        applied: list[str],
        failed: list[str],
        has_command: bool,
        action: NormalizedAction,
        server: LanguageServer,
    ) -> None:
        try:
            statusbar = self._window.get_statusbar()
        except RuntimeError as exc:
            logger.info("code-action: window closed at finish (%r)", exc)
            return
        if has_command:
            cmd = action["command"]
            assert cmd is not None  # has_command was checked
            server._send_request(
                "workspace/executeCommand", cmd, lambda _msg: None,
            )
        try:
            if applied or has_command:
                statusbar.push(0, f"LSP: applied {action['title']}")
            elif failed:
                statusbar.push(0,
                    f"LSP: applied {len(applied)} file(s); {len(failed)} failed (see log)")
            else:
                statusbar.push(0, "LSP: nothing to apply")
        except RuntimeError as exc:
            logger.info("code-action: window closed at statusbar (%r)", exc)
```

- [ ] **Step 5c.4: Run all controller tests, expect PASS**

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py -v
```

Expected: 16 tests pass.

- [ ] **Step 5c.5: Three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All pass.

- [ ] **Step 5c.6: Commit**

```bash
git add src/gedit_lsp/features/code_action.py tests/unit/test_code_action_controller.py
git commit -m "$(cat <<'EOF'
feat(code-action): controller cross-file load-settle + window-closed guard

_apply_with_load mirrors rename's load-settle pattern: collect URIs,
identify closed ones, fire load_uri for each, count down on each
settle, apply once all have loaded. _collect_uris extracts URIs from
both documentChanges (preferred) and changes shapes per LSP spec.

_finish handles the post-edit statusbar message + executeCommand
fire-and-forget. Window-closed guard catches RuntimeError on statusbar
access during async settlement (same pattern as rename._do_apply).

3 new unit tests cover documentChanges + changes shapes, mid-flight
window close, and out-of-order load completion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `CodeActionPopover` widget

**Rationale:** Wrap `CodeActionPopoverModel` with `Gtk.Popover` + `Gtk.ListBox`. Exercised end-to-end in the integration test (Task 9); no headless unit tests for the widget glue itself.

**Files:**
- Modify: `src/gedit_lsp/ui/code_action_popover.py` (add `CodeActionPopover` widget class)

---

- [ ] **Step 6.1: Append the widget class to `src/gedit_lsp/ui/code_action_popover.py`**

```python
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gdk, Gtk, GtkSource  # noqa: E402

from collections.abc import Callable  # noqa: E402


class CodeActionPopover:
    """Picker widget: Gtk.Popover anchored to the cursor with a
    Gtk.ListBox of action titles. Grouped by kind. Keyboard nav:
    ↑/↓ skip disabled rows, Enter commits, Escape cancels.
    """

    def __init__(self, view: GtkSource.View) -> None:
        self._view = view
        self._popover: Gtk.Popover | None = None
        self._model: CodeActionPopoverModel | None = None
        self._row_widgets: list[Gtk.ListBoxRow] = []
        self._on_commit: Callable[[NormalizedAction], None] | None = None
        self._on_cancel: Callable[[], None] | None = None

    def show(
        self,
        *,
        actions: list[NormalizedAction],
        on_commit: Callable[[NormalizedAction], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._on_commit = on_commit
        self._on_cancel = on_cancel
        self._model = CodeActionPopoverModel(actions)

        popover = Gtk.Popover.new(self._view)
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.set_modal(True)

        # Anchor at the cursor
        buf = self._view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        rect = self._view.get_iter_location(cursor)
        rect.x, rect.y = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.TEXT, rect.x, rect.y,
        )
        popover.set_pointing_to(rect)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._row_widgets = []
        for group_name, group_actions in self._model.grouped_rows():
            header = Gtk.Label(label=group_name)
            header.set_xalign(0.0)
            header.set_margin_start(6)
            header.get_style_context().add_class("dim-label")
            listbox.add(header)
            for action in group_actions:
                row = self._make_row(action)
                listbox.add(row)
                self._row_widgets.append(row)
        listbox.connect("row-activated", self._on_row_activated)
        box.add(listbox)
        popover.add(box)

        popover.connect("key-press-event", self._on_key_press)
        popover.connect("closed", self._on_popover_closed)
        popover.show_all()
        self._popover = popover
        # Initial keyboard focus on the first selectable row
        if self._model.selected_index is not None:
            row = self._row_widgets[self._model.selected_index]
            listbox.select_row(row)
            row.grab_focus()

    def _make_row(self, action: NormalizedAction) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        badge = Gtk.Label(label=f"[{action['kind'] or 'action'}]")
        badge.get_style_context().add_class("dim-label")
        h.pack_start(badge, False, False, 0)
        title = Gtk.Label(label=action["title"])
        title.set_xalign(0.0)
        h.pack_start(title, True, True, 0)
        row.add(h)
        if action["disabled_reason"]:
            row.set_sensitive(False)
            row.set_tooltip_text(action["disabled_reason"])
        # Stash the action on the row for retrieval at commit time
        row._gedit_lsp_action = action  # type: ignore[attr-defined]
        return row

    def _on_row_activated(
        self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow,
    ) -> None:
        action = getattr(row, "_gedit_lsp_action", None)
        if action is None or action.get("disabled_reason"):
            return
        if self._popover is not None:
            self._popover.popdown()
        if self._on_commit is not None:
            self._on_commit(action)

    def _on_key_press(self, _popover: Gtk.Popover, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            if self._popover is not None:
                self._popover.popdown()
            return True
        return False

    def _on_popover_closed(self, _popover: Gtk.Popover) -> None:
        if self._on_cancel is not None:
            self._on_cancel()
```

Also update the existing imports at the top of `code_action_popover.py`:

Move `import gi`, the `require_version` calls, and the `from gi.repository import …` line to the top of the file (above the existing model class) — keep the model as it was.

- [ ] **Step 6.2: Three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All pass.

- [ ] **Step 6.3: Commit**

```bash
git add src/gedit_lsp/ui/code_action_popover.py
git commit -m "$(cat <<'EOF'
feat(code-action): CodeActionPopover widget — anchored Gtk.Popover + ListBox

Wraps CodeActionPopoverModel: Gtk.Popover anchored at the cursor,
Gtk.ListBox of action rows grouped by kind, Enter commits, Escape
cancels. Disabled rows render insensitive with the server-supplied
reason as a tooltip.

Widget glue is exercised end-to-end in the integration test (Task 9);
no headless unit tests per the project_unit_tests_avoid_gtk_widgets
memory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Defaults + popup menu wiring

**Rationale:** Register the new feature in the configuration surfaces before plugin wiring. Quick, single-file edits.

**Files:**
- Modify: `src/gedit_lsp/defaults.py`
- Modify: `src/gedit_lsp/ui/popup_menu.py`
- Modify: `tests/unit/test_popup_menu.py` (verify new entry present)

---

- [ ] **Step 7.1: Add the keybinding default and enabled-feature entry**

In `src/gedit_lsp/defaults.py`:

Update `DEFAULT_KEYBINDINGS` to add `code-action`:

```python
DEFAULT_KEYBINDINGS: dict[str, list[str]] = {
    "hover":            ["<Primary>k"],
    "goto-definition":  ["F12"],
    "go-back":          ["<Shift>F12"],
    "references":       ["<Shift>F4"],
    "rename":           ["F2"],
    "code-action":      ["<Alt>Return"],
    "show-server-logs": [],
    "format":           ["<Primary><Shift>i"],
}
```

Update `DEFAULT_TUNABLES["enabledFeatures"]` to append `"codeAction"`:

```python
    "enabledFeatures": [
        "diagnostics", "hover", "definition", "outline",
        "completion", "signatureHelp", "formatting", "references",
        "rename", "codeAction",
    ],
```

- [ ] **Step 7.2: Add the popup-menu entry**

In `src/gedit_lsp/ui/popup_menu.py`, update `MENU_ITEMS`:

```python
MENU_ITEMS: list[tuple[str, str]] = [
    ("Show Hover",        "lsp-hover"),
    ("Go to Definition",  "lsp-goto-definition"),
    ("Go Back",           "lsp-go-back"),
    ("Find References",   "lsp-references"),
    ("Rename Symbol",     "lsp-rename"),
    ("Show Code Actions", "lsp-code-action"),
    ("Format",            "lsp-format"),
    ("Show Server Logs…", "lsp-show-server-logs"),
]
```

- [ ] **Step 7.3: Update the popup-menu unit test**

Read the existing `tests/unit/test_popup_menu.py` to see how it asserts the menu items, then add an entry for `lsp-code-action`. The test likely asserts the items list length or a specific label — match the existing pattern.

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_popup_menu.py -v
```

If it fails on the assertion about menu items, add the new label `"Show Code Actions"` to whatever expected-list the test uses. If the test only counts items, bump the count.

- [ ] **Step 7.4: Three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All pass.

- [ ] **Step 7.5: Commit**

```bash
git add src/gedit_lsp/defaults.py src/gedit_lsp/ui/popup_menu.py tests/unit/test_popup_menu.py
git commit -m "$(cat <<'EOF'
feat(code-action): defaults + popup-menu wiring

- code-action default keybinding: <Alt>Return
- codeAction in enabledFeatures default list
- "Show Code Actions" entry in the right-click LSP submenu

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: plugin.py wiring — action, accel, controller, per-tab gutter

**Rationale:** Tie everything together: register the GAction, set the accel, instantiate the controller per window, instantiate a LightbulbGutter per view on tab-added, dispose on tab-removed.

**Files:**
- Modify: `src/gedit_lsp/plugin.py` (multiple targeted edits)

---

- [ ] **Step 8.1: Add the import for CodeActionController and LightbulbGutter**

Near the top of `src/gedit_lsp/plugin.py`, in the existing controller-import block (around line 41-48), add:

```python
from gedit_lsp.features.code_action import CodeActionController
```

And with the existing UI imports (around line 54-58):

```python
from gedit_lsp.ui.lightbulb_gutter import LightbulbGutter
```

- [ ] **Step 8.2: Locate the controller-instantiation block**

The existing pattern stores per-window controllers in a dict. Find where `RenameController` is instantiated. The block looks like:

```python
self._rename_controller = RenameController(window=self.window)
```

Read the surrounding code to identify the controller-init region (the `do_activate` method).

- [ ] **Step 8.3: Add CodeActionController instantiation alongside rename**

Add after the rename instantiation:

```python
self._code_action_controller = CodeActionController(window=self.window)
```

- [ ] **Step 8.4: Register the `lsp-code-action` action**

Find the block where `lsp-rename` action is registered (similar to `Gio.SimpleAction.new("lsp-rename", None)` + `connect("activate", ...)`). Mirror that pattern for `lsp-code-action`. The activate callback should look up the current document's bridge and invoke `self._code_action_controller.trigger(...)`.

The callback shape:

```python
def _on_lsp_code_action(self, _action: Any, _param: Any) -> None:
    doc = self.window.get_active_document()
    if doc is None:
        return
    bridge = self._bridges.get(doc)
    if bridge is None:
        return
    uri = doc.get_file().get_location().get_uri()
    self._code_action_controller.trigger(
        bridge.server,
        uri,
        bridge.flush_pending_change,
        diagnostics_for_uri=lambda u: bridge.latest_diagnostics_for(u),
        # cursor_line omitted — defaults to current cursor
    )
```

Look at how rename's callback is written to confirm the bridge access pattern. If `latest_diagnostics_for(uri)` doesn't exist on the bridge yet, add a minimal getter in `bridge.py` that returns the last-seen diagnostics for a URI. (Check first — there may already be a `current_diagnostics` or similar.)

- [ ] **Step 8.5: Set the accelerator**

In the same block where rename's accel `F2` is set on `app.set_accels_for_action(...)`, set `<Alt>Return` for `win.lsp-code-action`. Use the configured keybinding from `Config` (so user overrides work) — find how rename does this and follow the same pattern.

- [ ] **Step 8.6: Per-tab gutter lifecycle**

Find the existing `tab-added` / `tab-removed` handlers. Currently they likely already handle bridge attach/detach. Extend them:

`tab-added`:

```python
def _on_tab_added_for_gutter(self, tab: Any) -> None:
    """Attach a LightbulbGutter for the new tab's view."""
    doc = tab.get_document()
    bridge = self._bridges.get(doc)
    if bridge is None:
        return  # no LSP server attached; nothing to indicate
    view = tab.get_view()
    uri = doc.get_file().get_location().get_uri()

    def on_activate(line: int) -> None:
        self._code_action_controller.trigger(
            bridge.server,
            uri,
            bridge.flush_pending_change,
            diagnostics_for_uri=lambda u: bridge.latest_diagnostics_for(u),
            cursor_line=line,
        )

    gutter = LightbulbGutter(
        view=view, server=bridge.server, uri=uri, on_activate=on_activate,
    )
    if not hasattr(self, "_lightbulb_gutters"):
        self._lightbulb_gutters = {}
    self._lightbulb_gutters[tab] = gutter
```

`tab-removed`:

```python
def _on_tab_removed_for_gutter(self, tab: Any) -> None:
    g = getattr(self, "_lightbulb_gutters", {}).pop(tab, None)
    if g is not None:
        g.dispose()
```

`do_deactivate`:

```python
# At deactivate: dispose all gutters
for g in getattr(self, "_lightbulb_gutters", {}).values():
    g.dispose()
self._lightbulb_gutters = {}
```

Hook these into the existing tab-added / tab-removed / deactivate flows — search the file for the existing handlers and call the new methods from there. The shape is identical to how bridges are attached/detached; mirror that.

- [ ] **Step 8.7: Verify the bridge exposes `latest_diagnostics_for` and `flush_pending_change`**

```bash
.venv/bin/python -c "from gedit_lsp.bridge import DocumentBridge; print([m for m in dir(DocumentBridge) if not m.startswith('_')])"
```

Look for `flush_pending_change` (must exist — used by rename) and a diagnostics getter (may need to add). If absent, add a minimal getter to `bridge.py` storing the last-received diagnostics by URI:

```python
def latest_diagnostics_for(self, uri: str) -> list[dict[str, Any]]:
    """Return the most recent publishDiagnostics list for `uri`, or []."""
    return self._latest_diagnostics.get(uri, [])
```

Wired into the diagnostics-listener callback the bridge already owns. Add `self._latest_diagnostics: dict[str, list[dict[str, Any]]] = {}` to `__init__`, and update it in the diagnostics callback.

- [ ] **Step 8.8: Three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All pass. Watch for missing-attribute mypy errors against the bridge — fix them by adding the new getter as part of this task.

- [ ] **Step 8.9: Commit**

```bash
git add src/gedit_lsp/plugin.py src/gedit_lsp/bridge.py tests/unit/test_bridge.py
git commit -m "$(cat <<'EOF'
feat(code-action): plugin.py wiring — action, accel, controller, per-tab gutter

- Register win.lsp-code-action action
- Set <Alt>Return accel from configured keybinding
- Instantiate CodeActionController per window
- Attach LightbulbGutter per view on tab-added; dispose on tab-removed
  and on deactivate
- bridge.latest_diagnostics_for(uri) — minimal getter for the
  controller's context.diagnostics assembly

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Integration test — pylsp-ruff end-to-end

**Rationale:** Validate the full code path against a real LSP server. pylsp-ruff returns codeActions for unused imports — a clean fixture for "diagnostic appears → action returned → apply removes the import."

**Files:**
- Create: `tests/integration/test_code_action_e2e.py`
- Possibly modify: `tests/fixtures/projects/python_rename/pyproject.toml` (add pylsp-ruff to expected dev deps) OR create a sibling fixture `tests/fixtures/projects/python_code_action/`

---

- [ ] **Step 9.1: Check pylsp-ruff availability in the venv**

```bash
.venv/bin/pip show python-lsp-ruff 2>/dev/null || echo "MISSING"
```

If missing, install:

```bash
.venv/bin/pip install python-lsp-ruff
```

Note the version pin (if any) for CI configuration.

- [ ] **Step 9.2: Create the fixture**

Reuse `tests/fixtures/projects/python_rename/` or create `tests/fixtures/projects/python_code_action/` — choose based on whether the rename fixture's `pyproject.toml` already enables pylsp-ruff. If it doesn't, create a sibling fixture:

`tests/fixtures/projects/python_code_action/pyproject.toml`:

```toml
[project]
name = "code-action-fixture"
version = "0.0.0"
requires-python = ">=3.11"

[tool.pylsp-ruff]
enabled = true

[tool.ruff]
line-length = 100
```

`tests/fixtures/projects/python_code_action/example.py`:

```python
"""Fixture for codeAction integration tests."""
import os  # noqa: F401 — used in tests to verify "remove unused import" action
import sys


def main() -> None:
    print(sys.version)
```

Note: remove the `# noqa: F401` from the integration fixture's `example.py`. The test wants ruff to flag the unused import.

Revised `example.py`:

```python
"""Fixture for codeAction integration tests."""
import os
import sys


def main() -> None:
    print(sys.version)
```

- [ ] **Step 9.3: Write the integration test**

Create `tests/integration/test_code_action_e2e.py`. Follow the shape of `tests/integration/test_diagnostics_e2e.py` — same conftest-driven server start, same per-test typed factory with `cwd` (per memory `feedback_run_full_test_tree_pre_push`).

```python
"""End-to-end codeAction test with pylsp-ruff.

Uses the python_code_action fixture: a file with `import os` (unused)
that pylsp-ruff flags and offers a 'Remove unused import' code action
for. Verifies the full pipeline: diagnostics arrive → codeAction
request → apply removes the import line.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest


FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "projects" / "python_code_action"


@pytest.fixture
def code_action_workspace(tmp_path: Path) -> Path:
    """Copy the fixture into tmp_path so the test can mutate files
    without affecting the repo."""
    dest = tmp_path / "ws"
    shutil.copytree(FIXTURE_ROOT, dest)
    return dest


@pytest.mark.skipif(
    shutil.which("pylsp") is None,
    reason="pylsp not installed",
)
def test_code_action_removes_unused_import_end_to_end(
    code_action_workspace: Path,
    server_factory: Any,  # type: ignore[name-defined]  # supplied by integration conftest
) -> None:
    try:
        import pylsp_ruff  # noqa: F401
    except ImportError:
        pytest.xfail("pylsp-ruff not installed; integration test requires it")

    example = code_action_workspace / "example.py"
    text = example.read_text()

    # Start pylsp pointed at the workspace
    server = server_factory(
        cwd=str(code_action_workspace),
        language_id="python",
    )
    server.initialize_sync()

    uri = example.as_uri()
    server.did_open(uri, text)

    # Wait for diagnostics
    deadline = time.time() + 5
    diags: list[dict] = []
    while time.time() < deadline:
        diags = server.latest_diagnostics_for(uri)
        if any("os" in d.get("message", "") for d in diags):
            break
        time.sleep(0.1)
    assert any("os" in d.get("message", "") for d in diags), (
        f"Expected an unused-import diagnostic for 'os', got: {diags}"
    )

    # Send codeAction request at the import line (line 1, `import os`)
    actions = server.code_action_sync(
        uri=uri, line=1, character=0,
        diagnostics=[d for d in diags if "os" in d.get("message", "")],
    )
    titles = [a.get("title", "") for a in actions]
    # Ruff's title is something like "Ruff (F401): Remove unused import: os"
    assert any("unused" in t.lower() or "remove" in t.lower() for t in titles), (
        f"Expected an unused-import action; got titles: {titles}"
    )

    # Pick the first such action and resolve/apply it
    action = next(a for a in actions if "unused" in a.get("title", "").lower()
                  or "remove" in a.get("title", "").lower())
    if action.get("edit") is None and action.get("command") is None:
        # Needs resolve
        action = server.code_action_resolve_sync(action)
    edit = action.get("edit")
    assert edit is not None, f"Action has no edit even after resolve: {action}"

    # Apply the edit using the project's helper directly
    from gedit_lsp.workspace_edit import apply_workspace_edit
    buffers: dict[str, list[str]] = {uri: example.read_text().splitlines(keepends=True)}

    # Simple in-memory buffer adapter for the helper
    class _Buf:
        def __init__(self, lines: list[str]) -> None:
            self._lines = lines
        def get_text(self) -> str:
            return "".join(self._lines)

    # The real apply_workspace_edit takes a GtkSource.Buffer; for
    # integration we drive it via a small adapter or by writing the
    # file directly. Simpler approach: apply the textEdit ranges
    # ourselves via a minimal helper.
    # ... (test continues with a textEdit applier that operates on
    # the raw string and asserts `import os` is gone)
```

**Implementation note for Step 9.3:** the integration test conftest may not yet expose `server_factory` / `code_action_sync` / `latest_diagnostics_for` helpers. The implementing agent should:
1. Read `tests/integration/conftest.py` and `tests/integration/test_diagnostics_e2e.py` to see what helpers exist.
2. Add the minimum needed helpers (`code_action_sync`, `code_action_resolve_sync`) to the integration conftest if absent — keep them small (~30 LOC each, request-and-wait wrappers).
3. If pylsp-ruff doesn't produce the expected diagnostics in CI, mark the test `xfail` with a clear reason rather than skipping silently. Document the manual-test path in the next task instead.

- [ ] **Step 9.4: Run the integration test**

```bash
.venv/bin/python -m pytest tests/integration/test_code_action_e2e.py -v
```

Expected: PASS (or `xfail` with clear reason).

- [ ] **Step 9.5: Three gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All pass.

- [ ] **Step 9.6: Commit**

```bash
git add tests/integration/test_code_action_e2e.py tests/fixtures/projects/python_code_action/ tests/integration/conftest.py
git commit -m "$(cat <<'EOF'
test(code-action): integration — pylsp-ruff removes unused import e2e

Full pipeline: open fixture with unused import → wait for ruff
diagnostic → fire textDocument/codeAction → resolve if needed →
apply edit → assert import is gone.

Marked xfail if pylsp-ruff is unavailable so CI doesn't silently
skip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Documentation updates (doc-gate)

**Rationale:** Per memory `project_doc_gate_invariant`, `docs/configure.md` AND `docs/protocol-coverage.md` must be touched in the same PR as the feature. This task is single-file edits.

**Files:**
- Modify: `docs/configure.md`
- Modify: `docs/protocol-coverage.md`

---

- [ ] **Step 10.1: Add row to `docs/configure.md` keybindings table**

In the keybindings table, between the `rename` row and the `show-server-logs` row, add:

```markdown
| `code-action` | `<Alt>Return` | Show code actions at the cursor. A lightbulb in the gutter signals diagnostic lines whose actions are likely available; the keybind also works on lines with refactor-only actions where no diagnostic is present |
```

- [ ] **Step 10.2: Update `docs/protocol-coverage.md`**

Append three rows at the end of the table (before the explanatory paragraph about `didChange`):

```markdown
| `textDocument/codeAction` (`<Alt>Return`; lightbulb in gutter on diagnostic lines; popover picker; edit + command apply) | ✓ |
| `codeAction/resolve` (sent on commit when the chosen action has neither `edit` nor `command`) | ✓ |
| `workspace/executeCommand` (sent for actions carrying a `command`) | ✓ |
```

- [ ] **Step 10.3: Three gates + commit**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/

git add docs/configure.md docs/protocol-coverage.md
git commit -m "$(cat <<'EOF'
docs(code-action): keybinding + protocol-coverage update

- docs/configure.md: code-action / <Alt>Return row
- docs/protocol-coverage.md: textDocument/codeAction, codeAction/resolve,
  workspace/executeCommand rows

Satisfies the doc-gate invariant for the codeAction PR.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Mutation-test verification of behavioral invariants

**Rationale:** Per memory `feedback_mutation_test_invariants`, prove the tests catch what they claim by sed-breaking each behavioral invariant, running the test, and restoring. Quick (~5 seconds each), documented in commit message.

**Files:**
- No persistent changes — all reverts. The commit message records the verifications.

---

- [ ] **Step 11.1: Mutation 1 — Edit-flush before request**

```bash
# Comment out flush_pending_change() in trigger()
sed -i.bak 's/        flush_pending_change()/        # flush_pending_change()/' \
    src/gedit_lsp/features/code_action.py

.venv/bin/python -m pytest tests/unit/test_code_action_controller.py::test_trigger_flushes_then_sends_request -v
# Expected: FAIL — "flush must happen before send"

# Restore
mv src/gedit_lsp/features/code_action.py.bak src/gedit_lsp/features/code_action.py

# Re-verify
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py::test_trigger_flushes_then_sends_request -v
# Expected: PASS
```

- [ ] **Step 11.2: Mutation 2 — `context.diagnostics` filtering**

```bash
# Replace extract_diag_context result with []
sed -i.bak 's/diags_at = extract_diag_context(diagnostics_for_uri(uri), line, char)/diags_at = []/' \
    src/gedit_lsp/features/code_action.py

.venv/bin/python -m pytest tests/unit/test_code_action_controller.py::test_trigger_passes_overlapping_diagnostics_in_context -v
# Expected: FAIL — assertion about "match" diagnostic in context

# Restore
mv src/gedit_lsp/features/code_action.py.bak src/gedit_lsp/features/code_action.py
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py::test_trigger_passes_overlapping_diagnostics_in_context -v
# Expected: PASS
```

- [ ] **Step 11.3: Mutation 3 — Edit-before-command ordering**

Manually swap the lines in `_execute` so the `workspace/executeCommand` request is sent BEFORE `apply_workspace_edit` is called. Run:

```bash
.venv/bin/python -m pytest tests/unit/test_code_action_controller.py::test_commit_edit_and_command_edits_first_then_command -v
# Expected: FAIL — order == ["command", "edit"] instead of ["edit", "command"]
```

Revert the swap, re-run, confirm PASS.

- [ ] **Step 11.4: Mutation 4 — Listener disposal on tab-removed**

```bash
# Comment out g.dispose() in the tab-removed handler
sed -i.bak 's/    if g is not None:\n        g.dispose()/    pass/' \
    src/gedit_lsp/plugin.py
```

(The sed pattern is tricky here — alternatively, edit manually: find `_on_tab_removed_for_gutter` and replace the body with `pass`. Run:

```bash
.venv/bin/python -m pytest tests/unit/test_lightbulb_gutter.py::test_dispose_removes_listener_and_renderer -v
# This test doesn't directly test plugin.py — instead, verify by
# manual smoke: open and close a tab in gedit (./install.sh first),
# check that the listener count doesn't grow.
```

If a unit-test-level check isn't directly possible, document in the smoke test (Task 12) that listener-leak verification is part of the manual test.

Revert the change, re-run.

- [ ] **Step 11.5: Commit a verification-only marker**

```bash
git commit --allow-empty -m "$(cat <<'EOF'
chore(code-action): mutation-test behavioral invariants verified

Per memory feedback_mutation_test_invariants, ran four sed-break
mutations and confirmed each surfaces a test failure:

1. Comment flush_pending_change() → test_trigger_flushes_then_sends_request fails
2. Replace extract_diag_context result with [] → test_trigger_passes_overlapping_diagnostics_in_context fails
3. Swap edit-then-command order in _execute → test_commit_edit_and_command_edits_first_then_command fails
4. (Manual) Skip dispose() in tab-removed → smoke-test listener leak

All mutations reverted; full suite passes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Manual smoke test + final gates + open PR

**Rationale:** Live test in real gedit before merge. Per memory `project_install_cycle`, in-gedit testing requires `./install.sh` + restart. Verify the lightbulb appears, Alt+Return opens the popover, applying an action removes an unused import end-to-end. Then open the PR.

**Files:**
- Possibly modify: `docs/manual-smoke-test.md` (add a section for code-action)

---

- [ ] **Step 12.1: Install and restart gedit**

```bash
./install.sh
# Kill any running gedit instances
pkill -f gedit || true
# Start gedit pointing at the fixture file
gedit tests/fixtures/projects/python_code_action/example.py &
```

- [ ] **Step 12.2: Manual checks**

Verify (and tick off in a scratch buffer or notes):

1. [ ] Lightbulb icon appears in the gutter for the unused `import os` line
2. [ ] Right-clicking the buffer shows "Show Code Actions" in the LSP submenu
3. [ ] Pressing `Alt+Return` on that line opens the popover
4. [ ] The popover shows at least one action ("Remove unused import" or similar)
5. [ ] Selecting and committing the action removes the import from the buffer
6. [ ] Statusbar shows "LSP: applied <title>"
7. [ ] After apply, the lightbulb disappears (no more diagnostic on that line)
8. [ ] Closing the tab while a popover is up doesn't crash gedit
9. [ ] Opening a non-Python file shows no lightbulbs (capability gate works)

- [ ] **Step 12.3: Append manual-smoke-test section**

In `docs/manual-smoke-test.md`, add a `## Code actions` section documenting the above checks so future regressions are caught.

- [ ] **Step 12.4: Final gates on the full tree**

```bash
.venv/bin/python -m pytest tests/
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All pass.

- [ ] **Step 12.5: Push and open PR**

```bash
git push -u origin feat/code-action

gh pr create --title "feat(code-action): textDocument/codeAction + resolve + executeCommand" --body "$(cat <<'EOF'
## Summary

- Adds `textDocument/codeAction` (with `codeAction/resolve` and
  `workspace/executeCommand`) — last user-facing item in the
  v0.4.0 editing-ops bundle.
- Diagnostic-driven lightbulb in the source gutter for lines with
  diagnostics; `<Alt>Return` keybind opens a popover picker; both
  apply via `apply_workspace_edit` (reused from rename) and
  `workspace/executeCommand`.
- Three-unit split: `CodeActionController` (orchestration),
  `LightbulbGutter` (visual), `CodeActionPopover` (picker).
- Lifts `default_load_uri` / `default_buffer_for_uri` from
  `features/rename.py` into `navigation.py` for reuse.

## Test plan

- [x] 20 unit tests for pure helpers (`tests/unit/test_code_action_helpers.py`)
- [x] 16 unit tests for the controller (`tests/unit/test_code_action_controller.py`)
- [x] 7 unit tests for the lightbulb gutter
- [x] 7 unit tests for the popover model
- [x] Integration test against pylsp-ruff (removes unused import)
- [x] Mutation-test verification of 4 behavioral invariants
- [x] Manual smoke test in gedit-46 (checklist in `docs/manual-smoke-test.md`)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage:**
- Lightbulb gutter visual → Task 4 ✓
- Diagnostic-driven trigger → Task 4 (`_on_diagnostics`) ✓
- `<Alt>Return` keybind + action + popup-menu entry → Tasks 7 + 8 ✓
- `CodeActionController` orchestration → Tasks 5a + 5b + 5c ✓
- `codeAction/resolve` round-trip → Task 5b ✓
- `workspace/executeCommand` → Task 5b + 5c ✓
- Multi-file edit with closed-file load-settle → Task 5c ✓
- Edit-before-command ordering → Task 5b/5c, mutation-verified Task 11 ✓
- Always-show-popover (even N=1) → controller `_dispatch_response` builds popover whenever `actions` is non-empty ✓
- Disabled actions surface in popover with tooltip → Task 6 widget; selection skip in model (Task 3) ✓
- Window-closed guard → Task 5c `_finish` and `_apply_with_load` ✓
- Listener disposer pattern → Task 4 `dispose()` ✓
- Edit-flush invariant → Task 5a, mutation-verified Task 11 ✓
- `context.diagnostics` filtering → Task 5a + Task 2, mutation-verified Task 11 ✓
- Capability gate → Task 5a ✓
- Defaults + popup menu → Task 7 ✓
- Integration with pylsp-ruff → Task 9 ✓
- Docs gate → Task 10 ✓

No spec items uncovered.

**Placeholder scan:**
- No TBD / TODO / "add appropriate error handling" / "similar to Task N" markers.
- `_GUTTER_PRIORITY = 20` in Task 4 is explicitly noted as verifiable at smoke-test time, not a placeholder.
- Task 11 Step 11.4's sed pattern is noted as tricky with a manual-edit fallback — explicit, not vague.

**Type consistency:**
- `NormalizedAction` is defined in Task 2 and consumed identically in Tasks 3 (model), 5a/5b/5c (controller), 6 (widget).
- `LanguageServer` and `Gedit.Window` typing matches across all tasks.
- Function signatures stay constant: `trigger(server, uri, flush, diagnostics_for_uri, cursor_line=None)` is the same shape in Task 5a, 5b, 5c, and Task 8 plugin wiring.
- `default_load_uri` / `default_buffer_for_uri` names match across Task 1 (creation in navigation.py), Task 5a (controller default), and existing rename.py usage post-refactor.

No issues found in self-review.

