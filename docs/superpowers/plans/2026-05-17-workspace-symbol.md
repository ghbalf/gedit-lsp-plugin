# workspace/symbol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live, server-filtered project-wide symbol quick-pick (`workspace/symbol` + `workspaceSymbol/resolve`) reachable via `Shift+F3`.

**Architecture:** Three-part split mirroring the shipped codeAction feature — pure helpers + a GTK-free `WorkspaceSymbolController` in `features/workspace_symbol.py`, a pure `QuickPickModel` + the `Gtk.Popover` widget `WorkspaceSymbolQuickPick` in `ui/workspace_symbol_quickpick.py`. The controller owns debounce/in-flight-cancel/stale-token logic and is unit-tested against a mock quick-pick with injected timer seams (the `MouseHoverController` pattern). The widget is smoke-only (headless widget construction is forbidden — it SIGTRAPs CI).

**Tech Stack:** Python 3.12, PyGObject (GTK 3 / GtkSource 300 / GLib 2.0), pytest, ruff, mypy. Run all tooling via `.venv/bin/python` (bare `python` lacks the dev tools in this project).

**Spec:** `docs/superpowers/specs/2026-05-17-workspace-symbol-design.md`

**Branch:** `feat/workspace-symbol` (already created; the design spec is committed there as `1fc4264`).

**Per-task gate (every task, before its commit):**

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```

All three must be clean. `tests/` (not just `tests/unit/`) — integration factories catch signature drift unit tests miss.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/gedit_lsp/features/workspace_symbol.py` | Pure helpers (`parse_symbol_results`, `symbol_kind_label`, `seed_query`) + `WorkspaceSymbolController` (GTK-free) | Create (Tasks 1, 3) |
| `src/gedit_lsp/ui/workspace_symbol_quickpick.py` | `QuickPickModel` (pure) + `WorkspaceSymbolQuickPick` (`Gtk.Popover`, smoke-only) | Create (Tasks 2, 4) |
| `src/gedit_lsp/plugin.py` | Construct controller+quickpick, action map, activate handler, dispose | Modify (Task 5) |
| `src/gedit_lsp/ui/popup_menu.py` | Right-click "Search Symbols…" entry | Modify (Task 5) |
| `src/gedit_lsp/defaults.py` | Keybinding, `enabledFeatures`, `workspaceSymbolDebounceMs` | Modify (Task 6) |
| `docs/configure.md`, `docs/protocol-coverage.md`, `docs/manual-smoke-test.md` | Doc-gate + smoke checklist | Modify (Task 6) |
| `tests/unit/test_workspace_symbol_helpers.py` | Helper tests | Create (Task 1) |
| `tests/unit/test_quickpick_model.py` | Model tests | Create (Task 2) |
| `tests/unit/test_workspace_symbol_controller.py` | Controller tests + mutation invariants | Create (Task 3) |
| `tests/integration/test_workspace_symbol_e2e.py` | pylsp end-to-end on the existing multi-file fixture | Create (Task 6) |

---

## Task 1: Pure helpers

**Files:**
- Create: `src/gedit_lsp/features/workspace_symbol.py`
- Test: `tests/unit/test_workspace_symbol_helpers.py`

`seed_query` operates on a real `Gtk.TextBuffer` (model layer — explicitly allowed in headless unit tests; only `View`/`Window`/`Popover` SIGTRAP). `parse_symbol_results` returns the **original validated item dicts unchanged** (not rebuilt) so server-specific fields like `data` survive for `workspaceSymbol/resolve`; rendering code reads `kind`/`containerName` defensively with `.get(...)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_workspace_symbol_helpers.py`:

```python
"""Unit tests for workspace/symbol pure helpers.

seed_query uses a real Gtk.TextBuffer — a model object, allowed in
headless unit tests (only View/Window/Popover SIGTRAP without DISPLAY).
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from gedit_lsp.features.workspace_symbol import (
    parse_symbol_results,
    seed_query,
    symbol_kind_label,
)


def _buf(text: str, offset: int) -> Gtk.TextBuffer:
    b = Gtk.TextBuffer()
    b.set_text(text)
    b.place_cursor(b.get_iter_at_offset(offset))
    return b


# --- parse_symbol_results --------------------------------------------


def test_parse_symbolinformation() -> None:
    result = [
        {"name": "compute_total", "kind": 12,
         "location": {"uri": "file:///lib.py",
                      "range": {"start": {"line": 10, "character": 4},
                                "end": {"line": 10, "character": 17}}}},
    ]
    out = parse_symbol_results(result)
    assert len(out) == 1
    assert out[0]["name"] == "compute_total"
    assert out[0]["location"]["range"]["start"]["line"] == 10


def test_parse_workspacesymbol_with_range() -> None:
    result = [{"name": "C", "kind": 5,
               "location": {"uri": "file:///a.py",
                            "range": {"start": {"line": 1, "character": 0},
                                      "end": {"line": 1, "character": 1}}}}]
    assert parse_symbol_results(result)[0]["name"] == "C"


def test_parse_workspacesymbol_without_range_kept() -> None:
    result = [{"name": "C", "kind": 5,
               "location": {"uri": "file:///a.py"},
               "data": {"server": "token"}}]
    out = parse_symbol_results(result)
    assert len(out) == 1
    assert "range" not in out[0]["location"]
    assert out[0]["data"] == {"server": "token"}  # preserved for resolve


def test_parse_null_and_empty() -> None:
    assert parse_symbol_results(None) == []
    assert parse_symbol_results([]) == []


def test_parse_non_list_and_malformed() -> None:
    assert parse_symbol_results({"name": "x"}) == []
    assert parse_symbol_results("garbage") == []
    # items missing name / location / location.uri are dropped
    assert parse_symbol_results([
        {"kind": 5, "location": {"uri": "file:///a"}},      # no name
        {"name": "ok", "location": {}},                      # no uri
        {"name": "ok2"},                                     # no location
        {"name": "good", "location": {"uri": "file:///g"}},  # kept
    ]) == [{"name": "good", "location": {"uri": "file:///g"}}]


# --- symbol_kind_label -----------------------------------------------


def test_symbol_kind_label_known() -> None:
    assert symbol_kind_label(5) == "class"
    assert symbol_kind_label(6) == "method"
    assert symbol_kind_label(12) == "function"
    assert symbol_kind_label(13) == "variable"
    assert symbol_kind_label(14) == "constant"


def test_symbol_kind_label_unknown() -> None:
    assert symbol_kind_label(0) == "symbol"
    assert symbol_kind_label(99) == "symbol"
    assert symbol_kind_label(-1) == "symbol"


# --- seed_query ------------------------------------------------------


def test_seed_query_identifier() -> None:
    # cursor inside "compute_total"
    assert seed_query(_buf("x = compute_total(items)", 8)) == "compute_total"


def test_seed_query_boundaries() -> None:
    text = "foo_bar = 1"
    assert seed_query(_buf(text, 0)) == "foo_bar"   # at start
    assert seed_query(_buf(text, 7)) == "foo_bar"   # just past last ident char


def test_seed_query_whitespace() -> None:
    assert seed_query(_buf("a  +  b", 3)) == ""      # cursor on spaces/'+'


def test_seed_query_selection_precedence() -> None:
    b = Gtk.TextBuffer()
    b.set_text("alpha beta gamma")
    b.select_range(b.get_iter_at_offset(6), b.get_iter_at_offset(10))  # "beta"
    assert seed_query(b) == "beta"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_workspace_symbol_helpers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gedit_lsp.features.workspace_symbol'`.

- [ ] **Step 3: Write the helpers**

Create `src/gedit_lsp/features/workspace_symbol.py`:

```python
"""workspace/symbol: pure helpers + WorkspaceSymbolController.

This module is GTK-free. `seed_query` touches a Gtk.TextBuffer, which
is a model object (no widget realization), so it is unit-testable
headless — unlike View/Window/Popover, which SIGTRAP without DISPLAY.

`parse_symbol_results` returns the server's original item dicts after
validation (it does not rebuild them) so server-specific fields such
as `data` survive for `workspaceSymbol/resolve`. Consumers read
`kind`/`containerName` defensively via `.get(...)`.
"""
from __future__ import annotations

import logging
import string
from typing import Any

logger = logging.getLogger("gedit_lsp.workspace_symbol")

_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_")

# LSP SymbolKind (1–26) → short display label.
_KIND_LABELS: dict[int, str] = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
    6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
    11: "interface", 12: "function", 13: "variable", 14: "constant",
    15: "string", 16: "number", 17: "boolean", 18: "array", 19: "object",
    20: "key", 21: "null", 22: "enum-member", 23: "struct", 24: "event",
    25: "operator", 26: "type-parameter",
}


def symbol_kind_label(kind: int) -> str:
    """LSP SymbolKind int → short label; unknown/out-of-range → 'symbol'."""
    return _KIND_LABELS.get(kind, "symbol")


def parse_symbol_results(result: Any) -> list[dict[str, Any]]:
    """Validate a workspace/symbol response into a flat list of items.

    Accepts SymbolInformation[] and WorkspaceSymbol[] (the latter may
    carry a `location` with only `uri` and no `range`). Drops anything
    not a dict, lacking a string `name`, or lacking a `location` dict
    with a `uri`. `null` / non-list / garbage → `[]`.
    """
    if not isinstance(result, list):
        return []
    out: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("name"), str):
            continue
        loc = item.get("location")
        if not isinstance(loc, dict) or "uri" not in loc:
            continue
        out.append(item)
    return out


def seed_query(buf: Any) -> str:
    """Initial quick-pick query for a Gtk.TextBuffer.

    Precedence: a non-empty selection wins; else the identifier run
    ([A-Za-z0-9_]) around the insert mark; else "". All seed
    precedence lives here so the controller stays trivial.
    """
    if buf.get_has_selection():
        bounds = buf.get_selection_bounds()
        if bounds:
            start, end = bounds
            return str(buf.get_text(start, end, False))

    cursor = buf.get_iter_at_mark(buf.get_insert())
    line_start = buf.get_iter_at_line(cursor.get_line())
    line_end = line_start.copy()
    if not line_end.ends_line():
        line_end.forward_to_line_end()
    line_text = str(buf.get_text(line_start, line_end, False))

    col = cursor.get_line_offset()
    if col > len(line_text):
        col = len(line_text)
    s = col
    while s > 0 and line_text[s - 1] in _IDENT_CHARS:
        s -= 1
    e = col
    while e < len(line_text) and line_text[e] in _IDENT_CHARS:
        e += 1
    return line_text[s:e]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_workspace_symbol_helpers.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Run the per-task gate**

Run:
```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/gedit_lsp/features/workspace_symbol.py tests/unit/test_workspace_symbol_helpers.py
git commit -m "feat(workspace-symbol): pure helpers (parse/kind-label/seed-query)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: QuickPickModel

**Files:**
- Create: `src/gedit_lsp/ui/workspace_symbol_quickpick.py`
- Test: `tests/unit/test_quickpick_model.py`

Pure selection-state model, GTK-free, direct analogue of `CodeActionPopoverModel`. Holds only real symbols (never a hint placeholder).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_quickpick_model.py`:

```python
"""Unit tests for QuickPickModel — pure selection state, GTK-free."""
from __future__ import annotations

from gedit_lsp.ui.workspace_symbol_quickpick import QuickPickModel


def _syms(n: int) -> list[dict]:
    return [{"name": f"s{i}", "location": {"uri": f"file:///{i}"}} for i in range(n)]


def test_set_results_selects_first() -> None:
    m = QuickPickModel()
    m.set_results(_syms(3))
    assert m.selected()["name"] == "s0"
    assert m.results == _syms(3)


def test_set_results_empty_selects_none() -> None:
    m = QuickPickModel()
    m.set_results([])
    assert m.selected() is None


def test_move_down_up_wraps() -> None:
    m = QuickPickModel()
    m.set_results(_syms(3))
    m.move_down(); assert m.selected()["name"] == "s1"
    m.move_down(); m.move_down()
    assert m.selected()["name"] == "s0"        # wrapped forward
    m.move_up()
    assert m.selected()["name"] == "s2"        # wrapped backward


def test_page_moves_clamp() -> None:
    m = QuickPickModel()
    m.set_results(_syms(5))
    m.page_down(10)
    assert m.selected()["name"] == "s4"        # clamped to last
    m.page_up(10)
    assert m.selected()["name"] == "s0"        # clamped to first


def test_reset_reclamps_selection() -> None:
    m = QuickPickModel()
    m.set_results(_syms(5))
    m.page_down(10)                            # selected -> index 4
    m.set_results(_syms(2))                    # shorter list
    assert m.selected()["name"] == "s0"        # re-selected to first


def test_moves_noop_when_empty() -> None:
    m = QuickPickModel()
    m.set_results([])
    m.move_down(); m.move_up(); m.page_down(3); m.page_up(3)
    assert m.selected() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_quickpick_model.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gedit_lsp.ui.workspace_symbol_quickpick'`.

- [ ] **Step 3: Write QuickPickModel**

Create `src/gedit_lsp/ui/workspace_symbol_quickpick.py`:

```python
"""workspace/symbol quick-pick: pure QuickPickModel + Gtk.Popover widget.

QuickPickModel is GTK-free and fully unit-tested. WorkspaceSymbolQuickPick
(added in Task 4) is the Gtk.Popover and is smoke-only — widget
construction in headless unit tests SIGTRAPs CI (the mouse-hover lesson).
"""
from __future__ import annotations

from typing import Any


class QuickPickModel:
    """Selection state over a flat symbol list.

    `set_results` re-selects index 0 (or None when empty). Movement
    wraps for line moves and clamps for page moves. No hint/placeholder
    rows ever enter the model — the widget renders hints separately.
    """

    def __init__(self) -> None:
        self._symbols: list[dict[str, Any]] = []
        self._selected: int | None = None

    def set_results(self, symbols: list[dict[str, Any]]) -> None:
        self._symbols = list(symbols)
        self._selected = 0 if self._symbols else None

    @property
    def results(self) -> list[dict[str, Any]]:
        return self._symbols

    def selected(self) -> dict[str, Any] | None:
        if self._selected is None:
            return None
        return self._symbols[self._selected]

    @property
    def selected_index(self) -> int | None:
        return self._selected

    def move_down(self) -> None:
        if self._selected is None:
            return
        self._selected = (self._selected + 1) % len(self._symbols)

    def move_up(self) -> None:
        if self._selected is None:
            return
        self._selected = (self._selected - 1) % len(self._symbols)

    def page_down(self, n: int) -> None:
        if self._selected is None:
            return
        self._selected = min(self._selected + n, len(self._symbols) - 1)

    def page_up(self, n: int) -> None:
        if self._selected is None:
            return
        self._selected = max(self._selected - n, 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_quickpick_model.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the per-task gate**

Run:
```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/gedit_lsp/ui/workspace_symbol_quickpick.py tests/unit/test_quickpick_model.py
git commit -m "feat(workspace-symbol): pure QuickPickModel selection state

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: WorkspaceSymbolController

**Files:**
- Modify: `src/gedit_lsp/features/workspace_symbol.py` (append the controller)
- Test: `tests/unit/test_workspace_symbol_controller.py`

Window-scoped, GTK-free. Owns the debounce timer, request token, in-flight id. `schedule`/`cancel` are injection seams (default `GLib.timeout_add`/`GLib.source_remove`) so debounce/cancel/token logic is unit-testable without a GLib main loop. Talks to the quick-pick through the narrow `show`/`set_results`/`dismiss` interface — tested against a mock.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_workspace_symbol_controller.py`:

```python
"""Unit tests for WorkspaceSymbolController.

No GTK widgets: server, quick-pick, window, statusbar are fakes/mocks.
The schedule/cancel seams default to GLib but tests inject synchronous
or manual stand-ins.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from gedit_lsp.features.workspace_symbol import WorkspaceSymbolController


class _FakeStatusbar:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def push(self, ctx: int, msg: str) -> None:
        self.messages.append((ctx, msg))


class _FakeWindow:
    def __init__(self, view: Any, statusbar: _FakeStatusbar) -> None:
        self._view = view
        self._statusbar = statusbar

    def get_active_view(self) -> Any:
        return self._view

    def get_statusbar(self) -> _FakeStatusbar:
        return self._statusbar


class _FakeView:
    def __init__(self, buf: Any) -> None:
        self._buf = buf

    def get_buffer(self) -> Any:
        return self._buf


class _FakeServer:
    def __init__(self, *, cap: Any = True) -> None:
        self._cap = cap
        self.requests: list[tuple[str, dict[str, Any], Any]] = []
        self.cancelled: list[int] = []
        self._next_id = 0

    def capability(self, key: str) -> Any:
        return self._cap if key == "workspaceSymbolProvider" else None

    def _send_request(self, method: str, params: dict[str, Any], cb: Any) -> int:
        self._next_id += 1
        self.requests.append((method, params, cb))
        return self._next_id

    def cancel_request(self, request_id: int) -> None:
        self.cancelled.append(request_id)


class _FakeConfig:
    def __init__(self, *, enabled: bool = True, debounce: int = 150) -> None:
        self._enabled = enabled
        self._debounce = debounce

    def tunable(self, key: str) -> Any:
        if key == "enabledFeatures":
            return ["workspaceSymbol"] if self._enabled else ["hover"]
        if key == "workspaceSymbolDebounceMs":
            return self._debounce
        raise KeyError(key)


def _buf(text: str = "compute_total", offset: int = 4) -> Gtk.TextBuffer:
    b = Gtk.TextBuffer()
    b.set_text(text)
    b.place_cursor(b.get_iter_at_offset(offset))
    return b


def _build(
    *,
    server: _FakeServer | None = None,
    config: _FakeConfig | None = None,
    buf_text: str = "",
    immediate: bool = True,
) -> tuple[WorkspaceSymbolController, _FakeServer, Any, _FakeStatusbar, list]:
    server = server or _FakeServer()
    config = config or _FakeConfig()
    statusbar = _FakeStatusbar()
    view = _FakeView(_buf(buf_text, 0) if buf_text else _empty_buf())
    window = _FakeWindow(view, statusbar)
    quickpick = MagicMock()
    scheduled: list = []
    if immediate:
        def schedule(_ms: int, fn: Any) -> int:
            fn()
            return 1
    else:
        def schedule(_ms: int, fn: Any) -> int:
            scheduled.append(fn)
            return len(scheduled)
    ctrl = WorkspaceSymbolController(
        window=window, quickpick=quickpick, config=config,
        schedule=schedule, cancel=lambda _i: None,
    )
    return ctrl, server, quickpick, statusbar, scheduled


def _empty_buf() -> Gtk.TextBuffer:
    b = Gtk.TextBuffer()
    b.set_text("")
    return b


# --- gates -----------------------------------------------------------


def test_capability_gate() -> None:
    ctrl, server, quickpick, statusbar, _ = _build(server=_FakeServer(cap=False))
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    assert server.requests == []
    quickpick.show.assert_not_called()
    assert any("does not support" in m.lower() for _c, m in statusbar.messages)


def test_disabled_feature_noop() -> None:
    ctrl, server, quickpick, _sb, _ = _build(config=_FakeConfig(enabled=False))
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    assert server.requests == []
    quickpick.show.assert_not_called()


# --- flush invariant -------------------------------------------------


def test_flush_before_first_query() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    log: list[str] = []
    view = _FakeView(_buf("compute_total", 4))  # seed -> immediate query
    ctrl.trigger(server, view, lambda: log.append(f"flush@{len(server.requests)}"))
    assert log == ["flush@0"]
    assert server.requests and server.requests[0][0] == "workspace/symbol"


# --- debounce / token ------------------------------------------------


def test_debounce_schedules_then_fires_once() -> None:
    ctrl, server, quickpick, _sb, scheduled = _build(immediate=False)
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("comp")
    assert len(scheduled) == 1            # scheduled, not yet fired
    assert server.requests == []
    scheduled[0]()                        # debounce fires
    assert len(server.requests) == 1
    assert server.requests[0][1] == {"query": "comp"}


def test_inflight_keystroke_cancels() -> None:
    ctrl, server, quickpick, _sb, _ = _build()  # immediate schedule
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("a")          # sends req id 1
    ctrl._on_query("ab")         # should cancel id 1, send id 2
    assert server.cancelled == [1]
    assert [p for _m, p, _c in server.requests] == [{"query": "a"}, {"query": "ab"}]


def test_stale_response_ignored() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("a")          # req 1, cb1
    cb1 = server.requests[0][2]
    ctrl._on_query("ab")         # req 2 (token bumped)
    cb1({"result": [{"name": "stale",
                     "location": {"uri": "file:///x", "range":
                                  {"start": {"line": 0, "character": 0},
                                   "end": {"line": 0, "character": 0}}}}]})
    # cb1 is stale: set_results must NOT be called for it.
    quickpick.set_results.assert_not_called()


def test_empty_query_sends_nothing() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("")
    assert server.requests == []
    quickpick.set_results.assert_called_with([], hint="Type to search symbols")


def test_nonempty_payload_shape() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("Calc")
    assert server.requests[0][0] == "workspace/symbol"
    assert server.requests[0][1] == {"query": "Calc"}


def test_no_match_hint() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("zzz")
    server.requests[0][2]({"result": []})
    quickpick.set_results.assert_called_with([], hint="No symbols match")


def test_results_populate_quickpick() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("c")
    syms = [{"name": "compute_total", "kind": 12,
             "location": {"uri": "file:///lib.py",
                          "range": {"start": {"line": 9, "character": 4},
                                    "end": {"line": 9, "character": 17}}}}]
    server.requests[0][2]({"result": syms})
    quickpick.set_results.assert_called_with(syms)


# --- activation ------------------------------------------------------


def test_activate_with_range_navigates(monkeypatch: Any) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "gedit_lsp.features.workspace_symbol.navigate_to_uri",
        lambda *a, **k: calls.append((a, k)),
    )
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_activate({"name": "f", "location":
                       {"uri": "file:///a.py",
                        "range": {"start": {"line": 7, "character": 3},
                                  "end": {"line": 7, "character": 4}}}})
    assert calls and calls[0][0][1] == "file:///a.py"
    assert calls[0][0][2] == 7 and calls[0][0][3] == 3
    assert server.requests == []  # no resolve when range present


def test_activate_resolve_then_navigate(monkeypatch: Any) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "gedit_lsp.features.workspace_symbol.navigate_to_uri",
        lambda *a, **k: calls.append((a, k)),
    )
    server = _FakeServer(cap={"resolveProvider": True})
    ctrl, server, quickpick, _sb, _ = _build(server=server)
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    sym = {"name": "f", "location": {"uri": "file:///a.py"}}
    ctrl._on_activate(sym)
    assert server.requests[0][0] == "workspaceSymbol/resolve"
    assert server.requests[0][1] == sym
    server.requests[0][2]({"result": {"name": "f", "location":
                          {"uri": "file:///a.py",
                           "range": {"start": {"line": 2, "character": 1},
                                     "end": {"line": 2, "character": 2}}}}})
    assert calls and calls[0][0][2] == 2 and calls[0][0][3] == 1


def test_activate_no_resolve_falls_back(monkeypatch: Any) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "gedit_lsp.features.workspace_symbol.navigate_to_uri",
        lambda *a, **k: calls.append((a, k)),
    )
    ctrl, server, quickpick, _sb, _ = _build(server=_FakeServer(cap=True))
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_activate({"name": "f", "location": {"uri": "file:///a.py"}})
    assert calls and calls[0][0][1] == "file:///a.py"
    assert calls[0][0][2] == 0 and calls[0][0][3] == 0
    assert server.requests == []


def test_activate_resolve_error_falls_back(monkeypatch: Any) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        "gedit_lsp.features.workspace_symbol.navigate_to_uri",
        lambda *a, **k: calls.append((a, k)),
    )
    server = _FakeServer(cap={"resolveProvider": True})
    ctrl, server, quickpick, _sb, _ = _build(server=server)
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_activate({"name": "f", "location": {"uri": "file:///a.py"}})
    server.requests[0][2]({"error": {"code": -32603, "message": "boom"}})
    assert calls and calls[0][0][2] == 0 and calls[0][0][3] == 0


def test_cancel_drops_inflight() -> None:
    ctrl, server, quickpick, _sb, _ = _build()
    ctrl.trigger(server, _FakeView(_empty_buf()), lambda: None)
    ctrl._on_query("a")               # req id 1 in flight
    ctrl._on_cancel()
    assert server.cancelled == [1]
    # a late response for the cancelled request is token-guarded
    server.requests[0][2]({"result": [{"name": "x",
                          "location": {"uri": "file:///x"}}]})
    quickpick.set_results.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_workspace_symbol_controller.py -q`
Expected: FAIL — `ImportError: cannot import name 'WorkspaceSymbolController'`.

- [ ] **Step 3: Append the controller to `features/workspace_symbol.py`**

Add these imports to the top of `src/gedit_lsp/features/workspace_symbol.py` (after the existing `import string`):

```python
from collections.abc import Callable

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gedit_lsp.navigation import navigate_to_uri
from gedit_lsp.utf16 import utf16_to_text_iter
```

Append the controller class to the end of the file:

```python
class WorkspaceSymbolController:
    """Window-scoped driver for the workspace/symbol live quick-pick.

    GTK-free. Owns the debounce timer id, an integer request token
    (stale-response guard), and the in-flight request id. `schedule`
    and `cancel` are injection seams (default GLib) so the debounce /
    cancel / token logic is unit-testable without a main loop.
    """

    def __init__(
        self,
        *,
        window: Any,
        quickpick: Any,
        config: Any,
        schedule: Callable[[int, Callable[[], Any]], int] = GLib.timeout_add,
        cancel: Callable[[int], None] = GLib.source_remove,
    ) -> None:
        self._window = window
        self._quickpick = quickpick
        self._config = config
        self._schedule = schedule
        self._cancel = cancel
        self._server: Any = None
        self._token: int = 0
        self._timer_id: int | None = None
        self._inflight_id: int | None = None

    def trigger(
        self,
        server: Any,
        view: Any,
        flush_pending_change: Callable[[], None],
    ) -> None:
        if "workspaceSymbol" not in self._config.tunable("enabledFeatures"):
            logger.info("workspace-symbol: disabled via enabledFeatures")
            return
        statusbar = self._window.get_statusbar()
        if not server.capability("workspaceSymbolProvider"):
            logger.info("workspace-symbol: server lacks workspaceSymbolProvider")
            statusbar.push(
                0, "LSP: server does not support workspace symbol search"
            )
            return
        flush_pending_change()
        self._server = server
        self._token = 0
        self._timer_id = None
        self._inflight_id = None
        seed = seed_query(view.get_buffer())
        self._quickpick.show(
            seed=seed,
            on_query=self._on_query,
            on_activate=self._on_activate,
            on_cancel=self._on_cancel,
        )
        if seed:
            self._on_query(seed)

    def _on_query(self, text: str) -> None:
        if self._timer_id is not None:
            self._cancel(self._timer_id)
            self._timer_id = None
        debounce = self._config.tunable("workspaceSymbolDebounceMs")
        self._timer_id = self._schedule(debounce, lambda: self._fire(text))

    def _fire(self, text: str) -> bool:
        self._timer_id = None
        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
            self._inflight_id = None
        self._token += 1
        my = self._token
        if text == "":
            self._quickpick.set_results([], hint="Type to search symbols")
            return False
        self._inflight_id = self._server._send_request(
            "workspace/symbol",
            {"query": text},
            lambda msg: self._on_response(my, msg),
        )
        return False  # one-shot timer

    def _on_response(self, token: int, msg: dict[str, Any]) -> None:
        if token != self._token:
            logger.debug("workspace-symbol: stale response token %d", token)
            return
        self._inflight_id = None
        if msg.get("error"):
            logger.info("workspace-symbol: error %r", msg.get("error"))
            self._window.get_statusbar().push(
                0, "LSP: workspace symbol request failed"
            )
            return
        symbols = parse_symbol_results(msg.get("result"))
        if not symbols:
            self._quickpick.set_results([], hint="No symbols match")
        else:
            self._quickpick.set_results(symbols)

    def _on_activate(self, symbol: dict[str, Any]) -> None:
        loc = symbol.get("location") or {}
        uri = loc.get("uri")
        if not isinstance(uri, str):
            return
        rng = loc.get("range")
        if rng:
            self._navigate(uri, rng)
            return
        cap = self._server.capability("workspaceSymbolProvider")
        if isinstance(cap, dict) and cap.get("resolveProvider"):
            def _cb(msg: dict[str, Any]) -> None:
                if msg.get("error"):
                    self._navigate(uri, None)
                    return
                rloc = (msg.get("result") or {}).get("location") or {}
                rrng = rloc.get("range")
                if rrng and isinstance(rloc.get("uri"), str):
                    self._navigate(rloc["uri"], rrng)
                else:
                    self._navigate(uri, None)

            self._server._send_request("workspaceSymbol/resolve", symbol, _cb)
        else:
            self._navigate(uri, None)

    def _navigate(self, uri: str, rng: dict[str, Any] | None) -> None:
        if rng:
            line = rng["start"]["line"]
            char = rng["start"]["character"]
        else:
            line, char = 0, 0
        navigate_to_uri(
            self._window, uri, line, char,
            to_iter=lambda buf: utf16_to_text_iter(buf, line, char),
        )

    def _on_cancel(self) -> None:
        if self._timer_id is not None:
            self._cancel(self._timer_id)
            self._timer_id = None
        if self._inflight_id is not None:
            self._server.cancel_request(self._inflight_id)
            self._inflight_id = None
        self._token += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_workspace_symbol_controller.py -q`
Expected: PASS (15 tests).

- [ ] **Step 5: Mutation-test invariants (sed-break, watch fail, restore — ~5s)**

Run each, confirm the named test FAILS, then `git checkout -- src/gedit_lsp/features/workspace_symbol.py` to restore:

```bash
# 1. Break the stale-token guard (always accept the response):
sed -i 's/        if token != self._token:/        if False:/' src/gedit_lsp/features/workspace_symbol.py
.venv/bin/python -m pytest tests/unit/test_workspace_symbol_controller.py::test_stale_response_ignored -q   # must FAIL
git checkout -- src/gedit_lsp/features/workspace_symbol.py

# 2. Break the flush call (no-op the flush):
sed -i 's/        flush_pending_change()/        pass  # flush_pending_change()/' src/gedit_lsp/features/workspace_symbol.py
.venv/bin/python -m pytest tests/unit/test_workspace_symbol_controller.py::test_flush_before_first_query -q  # must FAIL
git checkout -- src/gedit_lsp/features/workspace_symbol.py

# 3. Break the capability gate (always proceed):
sed -i 's/        if not server.capability("workspaceSymbolProvider"):/        if False:/' src/gedit_lsp/features/workspace_symbol.py
.venv/bin/python -m pytest tests/unit/test_workspace_symbol_controller.py::test_capability_gate -q           # must FAIL
git checkout -- src/gedit_lsp/features/workspace_symbol.py
```

Expected: each targeted test FAILS while broken; restored cleanly after.

- [ ] **Step 6: Run the per-task gate**

Run:
```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add src/gedit_lsp/features/workspace_symbol.py tests/unit/test_workspace_symbol_controller.py
git commit -m "feat(workspace-symbol): WorkspaceSymbolController (debounce/token/resolve)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: WorkspaceSymbolQuickPick widget (smoke-only)

**Files:**
- Modify: `src/gedit_lsp/ui/workspace_symbol_quickpick.py` (append the widget)

**No unit test.** Per the project invariant, headless construction of `Gtk.Popover`/`Gtk.TreeView` SIGTRAPs CI; this widget is exercised by manual smoke (Task 6) and the integration test path. Logic-bearing parts already live in `QuickPickModel` (Task 2, tested) and the controller (Task 3, tested). This task is a thin renderer + key router.

- [ ] **Step 1: Append the widget class**

Add to the top of `src/gedit_lsp/ui/workspace_symbol_quickpick.py` (after `from typing import Any`):

```python
from collections.abc import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

from gedit_lsp.features.workspace_symbol import symbol_kind_label
```

Append to the end of the file:

```python
def _row_label(symbol: dict[str, Any]) -> str:
    """Single-line display string for a symbol row.

    Plain text only — never markup. A symbol literally named
    `<b>x</b>` must render verbatim, not as bold.
    """
    name = symbol.get("name", "")
    kind = symbol_kind_label(symbol.get("kind", 0))
    container = symbol.get("containerName") or ""
    loc = symbol.get("location") or {}
    uri = loc.get("uri", "")
    base = uri.rsplit("/", 1)[1] if "/" in uri else uri
    rng = loc.get("range") or {}
    line = rng.get("start", {}).get("line")
    where = base if line is None else f"{base}:{line + 1}"
    tail = " · ".join(p for p in (kind, container, where) if p)
    return f"{name}    {tail}" if tail else name


class WorkspaceSymbolQuickPick:
    """Cursor-anchored Gtk.Popover: a Gtk.Entry over a results TreeView.

    Smoke-only. Wraps a QuickPickModel for selection state. Focus stays
    in the entry; arrow/page/Enter/Escape are intercepted on the entry
    and routed to the model. Uses the callback-clear-before-popdown
    discipline so the `closed` signal's auto-cancel no-ops after an
    activation.
    """

    def __init__(self, window: Any) -> None:
        self._window = window
        self._popover: Gtk.Popover | None = None
        self._entry: Gtk.Entry | None = None
        self._tree: Gtk.TreeView | None = None
        self._store: Gtk.ListStore | None = None
        self._model = QuickPickModel()
        self._on_query: Callable[[str], None] | None = None
        self._on_activate: Callable[[dict[str, Any]], None] | None = None
        self._on_cancel: Callable[[], None] | None = None

    def show(
        self,
        *,
        seed: str,
        on_query: Callable[[str], None],
        on_activate: Callable[[dict[str, Any]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        if self._popover is not None:  # defensive: tear down a stale one
            self._on_query = self._on_activate = self._on_cancel = None
            self._popover.popdown()

        self._on_query = on_query
        self._on_activate = on_activate
        self._on_cancel = on_cancel
        self._model = QuickPickModel()

        view = self._window.get_active_view()
        popover = Gtk.Popover.new(view)  # type: ignore[call-arg]
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.set_modal(True)  # type: ignore[attr-defined]

        buf = view.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        rect = view.get_iter_location(cursor)
        rect.x, rect.y = view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y,
        )
        popover.set_pointing_to(rect)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_size_request(520, 320)

        entry = Gtk.Entry()
        entry.set_text(seed)
        entry.select_region(0, -1)
        entry.set_placeholder_text("Search project symbols…")
        entry.connect("changed", self._on_entry_changed)
        entry.connect("key-press-event", self._on_entry_key)
        box.pack_start(entry, False, False, 0)  # type: ignore[attr-defined]

        store = Gtk.ListStore(str)  # type: ignore[call-arg]
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(False)
        tree.append_column(
            Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0)  # type: ignore[call-arg,arg-type]
        )
        tree.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(tree)  # type: ignore[attr-defined]
        box.pack_start(scrolled, True, True, 0)  # type: ignore[attr-defined]

        popover.add(box)  # type: ignore[attr-defined]
        popover.connect("closed", self._on_closed)
        popover.show_all()  # type: ignore[attr-defined]
        popover.popup()
        entry.grab_focus()
        entry.select_region(0, -1)

        self._popover = popover
        self._entry = entry
        self._tree = tree
        self._store = store
        self.set_results([], hint="Type to search symbols")

    def set_results(
        self, symbols: list[dict[str, Any]], *, hint: str | None = None
    ) -> None:
        if self._store is None:
            return
        self._model.set_results(symbols)
        self._store.clear()
        if not symbols:
            if hint:
                self._store.append([f"  {hint}"])  # type: ignore[no-untyped-call]
            return
        for sym in symbols:
            self._store.append([_row_label(sym)])  # type: ignore[no-untyped-call]
        self._sync_selection()

    def dismiss(self) -> None:
        if self._popover is not None:
            self._popover.popdown()

    # --- internals ---

    def _sync_selection(self) -> None:
        if self._tree is None:
            return
        idx = self._model.selected_index
        sel = self._tree.get_selection()
        if idx is None:
            sel.unselect_all()
            return
        path = Gtk.TreePath.new_from_indices([idx])  # type: ignore[arg-type]
        sel.select_path(path)
        self._tree.scroll_to_cell(path, None, False, 0.0, 0.0)

    def _on_entry_changed(self, entry: Gtk.Entry) -> None:
        if self._on_query is not None:
            self._on_query(entry.get_text())

    def _on_entry_key(self, _entry: Gtk.Entry, event: Any) -> bool:
        kv = event.keyval
        if kv == Gdk.KEY_Escape:
            self._cancel_and_close()
            return True
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._activate_selected()
            return True
        if kv == Gdk.KEY_Down:
            self._model.move_down(); self._sync_selection(); return True
        if kv == Gdk.KEY_Up:
            self._model.move_up(); self._sync_selection(); return True
        if kv == Gdk.KEY_Page_Down:
            self._model.page_down(10); self._sync_selection(); return True
        if kv == Gdk.KEY_Page_Up:
            self._model.page_up(10); self._sync_selection(); return True
        return False

    def _on_row_activated(
        self, _tree: Gtk.TreeView, path: Gtk.TreePath, _col: Gtk.TreeViewColumn
    ) -> None:
        indices = path.get_indices()
        if indices and 0 <= indices[0] < len(self._model.results):
            self._model.set_results(self._model.results)  # keep list
            # select the clicked row, then activate it
            for _ in range(indices[0]):
                self._model.move_down()
            self._activate_selected()

    def _activate_selected(self) -> None:
        sym = self._model.selected()
        if sym is None:
            return
        cb = self._on_activate
        self._on_query = self._on_activate = self._on_cancel = None
        if self._popover is not None:
            self._popover.popdown()
        if cb is not None:
            cb(sym)

    def _cancel_and_close(self) -> None:
        cb = self._on_cancel
        self._on_query = self._on_activate = self._on_cancel = None
        if self._popover is not None:
            self._popover.popdown()
        if cb is not None:
            cb()

    def _on_closed(self, _popover: Gtk.Popover) -> None:
        cb = self._on_cancel
        self._on_query = self._on_activate = self._on_cancel = None
        self._popover = None
        self._entry = None
        self._tree = None
        self._store = None
        if cb is not None:
            cb()
```

- [ ] **Step 2: Verify no headless import/collection regression**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — same count as Task 3 plus nothing new (the widget has no tests; importing the module must not SIGTRAP — class bodies don't construct widgets, only `show()` does).

- [ ] **Step 3: Run the per-task gate**

Run:
```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```
Expected: all clean.

- [ ] **Step 4: Commit**

```bash
git add src/gedit_lsp/ui/workspace_symbol_quickpick.py
git commit -m "feat(workspace-symbol): WorkspaceSymbolQuickPick popover widget

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire into plugin.py + popup menu

**Files:**
- Modify: `src/gedit_lsp/plugin.py` (imports, construction, action map, activate handler, dispose)
- Modify: `src/gedit_lsp/ui/popup_menu.py` (`MENU_ITEMS`)

No new unit test — wiring is exercised by the integration test (Task 6) and manual smoke. There is no `defaults.py` key yet, so the action's accels resolve to `[]` until Task 6; that is fine and intentional (Task 6 is a single atomic doc+defaults+integration commit; until then `Shift+F3` simply isn't bound but the right-click entry and the controller work).

- [ ] **Step 1: Add imports**

In `src/gedit_lsp/plugin.py`, next to `from gedit_lsp.features.references import ReferencesController` (line ~51) add:

```python
from gedit_lsp.features.workspace_symbol import WorkspaceSymbolController
```

Next to `from gedit_lsp.ui.references_panel import ReferencesPanel` (line ~63) add:

```python
from gedit_lsp.ui.workspace_symbol_quickpick import WorkspaceSymbolQuickPick
```

- [ ] **Step 2: Construct controller + quick-pick**

In `src/gedit_lsp/plugin.py`, immediately after these lines (~177-178):

```python
        self._rename_ctrl = RenameController(window=win)
        self._code_action_ctrl = CodeActionController(window=win)
```

add:

```python
        self._workspace_symbol_quickpick = WorkspaceSymbolQuickPick(win)
        self._workspace_symbol_ctrl = WorkspaceSymbolController(
            window=win,
            quickpick=self._workspace_symbol_quickpick,
            config=self._config,
        )
```

- [ ] **Step 3: Add to the action map**

In the action-map list (around line 191), after:

```python
            ("lsp-code-action", "code-action", self._on_code_action_activate),
```

add:

```python
            ("lsp-workspace-symbol", "workspace-symbol", self._on_workspace_symbol_activate),
```

- [ ] **Step 4: Add the activate handler**

In `src/gedit_lsp/plugin.py`, immediately after the `_on_references_activate` method (it ends at line ~686 with the `self._references_ctrl.trigger(...)` call), add:

```python
    def _on_workspace_symbol_activate(
        self, _action: Gio.SimpleAction, _param: GObject.Object | None
    ) -> None:
        logger.info("workspace-symbol action invoked")
        view = self.window.get_active_view()
        if view is None:
            logger.info("workspace-symbol: no active view")
            return
        doc = view.get_buffer()
        bridge = self._bridges.get(doc)
        server = self._servers.get(doc)
        if bridge is None or server is None:
            logger.info(
                "workspace-symbol: doc not bridged (bridge=%s server=%s)",
                bridge, server,
            )
            return
        logger.info(
            "workspace-symbol: triggering, server.state=%s", server.state
        )
        self._workspace_symbol_ctrl.trigger(
            server, view, bridge.flush_pending_change,
        )
```

- [ ] **Step 5: Dispose defensively in `do_deactivate`**

In `do_deactivate`, immediately after these lines (~234-235):

```python
        # FormattingController has no GTK resources to dispose; clear the map.
        self._formatting_ctrls.clear()
```

add:

```python
        # Window-scoped, like the references panel; just make sure no
        # quick-pick popover is left up across deactivation.
        self._workspace_symbol_quickpick.dismiss()
```

- [ ] **Step 6: Add the right-click menu entry**

In `src/gedit_lsp/ui/popup_menu.py`, in the `MENU_ITEMS` list, after:

```python
    ("Show Code Actions", "lsp-code-action"),
```

add:

```python
    ("Search Symbols…",   "lsp-workspace-symbol"),
```

- [ ] **Step 7: Run the per-task gate**

Run:
```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```
Expected: all clean. (Existing `test_prefs.py` still passes — `enabledFeatures` is unchanged until Task 6, and nothing references the not-yet-added keybinding.)

- [ ] **Step 8: Commit**

```bash
git add src/gedit_lsp/plugin.py src/gedit_lsp/ui/popup_menu.py
git commit -m "feat(workspace-symbol): wire controller, action, popup menu, dispose

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Defaults, docs (doc-gate), integration test

**Files:**
- Modify: `src/gedit_lsp/defaults.py`
- Modify: `docs/configure.md`, `docs/protocol-coverage.md`, `docs/manual-smoke-test.md`
- Create: `tests/integration/test_workspace_symbol_e2e.py`

This is the single commit that satisfies the doc-gate (`docs/` changed alongside `features/`), turns on the feature by default, makes the prefs checkbox appear (via the mechanically-derived `FEATURE_CHECKBOX_NAMES` + `test_prefs.py` sync assertion), binds `Shift+F3`, and adds end-to-end coverage on the existing multi-file fixture.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_workspace_symbol_e2e.py`:

```python
"""End-to-end workspace/symbol against real pylsp on a multi-file project.

pylsp returns SymbolInformation with full locations. Uses the existing
python_rename fixture (lib.py defines `compute_total` and `Calculator`).
Skips cleanly if pylsp is unavailable; xfails (not silent-pass) if pylsp
is present but never advertises workspaceSymbolProvider.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import gi
import pytest

gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "300")
from gi.repository import GLib, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.rpc import RpcClient
from gedit_lsp.server import LanguageServer

FIXTURE_ROOT = (
    Path(__file__).parent.parent / "fixtures" / "projects" / "python_rename"
)


def _run_until(loop: GLib.MainLoop, predicate: Any, timeout_s: float = 12.0) -> bool:
    state = {"hit": False}

    def _check() -> bool:
        if predicate():
            state["hit"] = True
            loop.quit()
            return False
        return True

    def _on_timeout() -> bool:
        loop.quit()
        return False

    GLib.timeout_add(50, _check)
    GLib.timeout_add_seconds(int(timeout_s), _on_timeout)
    loop.run()  # type: ignore[no-untyped-call]
    return state["hit"]


def _send_request_sync(
    server: LanguageServer,
    loop: GLib.MainLoop,
    method: str,
    params: dict[str, Any],
    timeout_s: float = 10.0,
) -> dict[str, Any] | None:
    holder: dict[str, dict[str, Any]] = {}
    server._send_request(method, params, lambda msg: holder.__setitem__("msg", msg))
    _run_until(loop, lambda: "msg" in holder, timeout_s=timeout_s)
    return holder.get("msg")


def test_workspace_symbol_finds_cross_file_symbol(
    pylsp_available: None,
    tmp_path: Path,
    main_loop: GLib.MainLoop,
) -> None:
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE_ROOT, ws)
    lib = ws / "lib.py"
    text = lib.read_text()
    uri = lib.as_uri()

    def transport_factory(
        command: list[str],
        log_prefix: str,
        on_exit: Any,
        on_stderr_line: Any = None,
        cwd: str | None = None,
    ) -> RpcClient:
        return RpcClient(
            command=command,
            log_prefix=log_prefix,
            on_exit=on_exit,
            on_stderr_line=on_stderr_line,
            cwd=cwd,
        )

    server = LanguageServer(
        language_id="python",
        root_path=str(ws),
        command=["pylsp"],
        initialization_options=None,
        transport_factory=transport_factory,
        backoff_schedule=[1, 2, 4],
        max_restart_attempts=3,
    )
    server.attach_buffer(uri)

    buf = GtkSource.Buffer()
    buf.set_text(text)
    bridge = DocumentBridge(
        uri=uri,
        language_id="python",
        text=text,
        server=server,
        clock=GLibClock(),
        debounce_ms=150,
    )
    bridge.attach()

    ready = _run_until(
        main_loop,
        lambda: server.capability("workspaceSymbolProvider") is not None,
        timeout_s=12.0,
    )
    if not ready or not server.capability("workspaceSymbolProvider"):
        pytest.xfail(
            "pylsp did not advertise workspaceSymbolProvider within 12s "
            f"(capability={server.capability('workspaceSymbolProvider')!r})"
        )

    response = _send_request_sync(
        server, main_loop, "workspace/symbol", {"query": "compute_total"},
        timeout_s=10.0,
    )
    assert response is not None, "no workspace/symbol response"
    result = response.get("result") or []
    assert isinstance(result, list) and result, (
        f"expected workspace/symbol hits, got {response!r}"
    )
    names = [r.get("name") for r in result if isinstance(r, dict)]
    assert "compute_total" in names, f"compute_total not in {names!r}"
    hit = next(r for r in result if r.get("name") == "compute_total")
    assert hit["location"]["uri"].endswith("lib.py"), hit["location"]["uri"]
```

- [ ] **Step 2: Run it to confirm it currently passes-or-xfails meaningfully (pre-defaults change is irrelevant to this test — it drives the server directly)**

Run: `.venv/bin/python -m pytest tests/integration/test_workspace_symbol_e2e.py -q`
Expected: PASS if pylsp is installed (jedi indexes the project and returns `compute_total` from `lib.py`); `skipped` if pylsp absent; `xfail` only if pylsp never advertises the capability. Any of these three is acceptable — a hard FAIL is not.

- [ ] **Step 3: Edit `defaults.py`**

In `src/gedit_lsp/defaults.py`, in `DEFAULT_KEYBINDINGS`, after:

```python
    "format":           ["<Primary><Shift>i"],
```

add:

```python
    "workspace-symbol": ["<Shift>F3"],
```

In `DEFAULT_TUNABLES`, after:

```python
    "mouseHoverDwellMs":       300,
```

add:

```python
    "workspaceSymbolDebounceMs": 150,
```

In `DEFAULT_TUNABLES["enabledFeatures"]`, change:

```python
    "enabledFeatures": [
        "diagnostics", "hover", "definition", "outline",
        "completion", "signatureHelp", "formatting", "references",
        "rename", "codeAction", "mouseHover",
    ],
```

to:

```python
    "enabledFeatures": [
        "diagnostics", "hover", "definition", "outline",
        "completion", "signatureHelp", "formatting", "references",
        "rename", "codeAction", "mouseHover", "workspaceSymbol",
    ],
```

- [ ] **Step 4: Edit `docs/configure.md`**

In the keybindings table, after the `format` row:

```
| `format` | `<Primary><Shift>i` | Format the document (or the selection if any) via the server |
```

add:

```
| `workspace-symbol` | `<Shift>F3` | Open a live quick-pick that searches every symbol in the project (server-side filtered as you type) and jumps to the chosen one |
```

- [ ] **Step 5: Edit `docs/protocol-coverage.md`**

After the `workspace/executeCommand` row:

```
| `workspace/executeCommand` (sent for actions carrying a `command`) | ✓ |
```

add:

```
| `workspace/symbol` (Shift+F3; live quick-pick, server-side filtered, debounced) | ✓ |
| `workspaceSymbol/resolve` (sent on activation when the chosen symbol has no `location.range` and the server advertises `resolveProvider`) | ✓ |
```

- [ ] **Step 6: Edit `docs/manual-smoke-test.md`**

Immediately before the `## Final` section, add:

```markdown
## workspace/symbol (`feat/workspace-symbol`)

- [ ] Put the cursor inside an identifier; press `Shift+F3` → quick-pick opens, entry pre-filled with that identifier (fully selected), results already listed.
- [ ] Confirm `Shift+F3` is not swallowed by gedit/GtkSourceView (binding-owner check). If it is, fall back to another free F-key chord and update `defaults.py` + `docs/configure.md`.
- [ ] Type to refine → results update live (server-side filtered), no lag/flicker on fast typing.
- [ ] `Down`/`Up`/`PageDown`/`PageUp` move the selection while the text caret stays in the entry.
- [ ] `Enter` on a symbol in an already-open file → jumps there.
- [ ] `Enter` on a symbol in a closed file → opens it in a new tab at the symbol.
- [ ] Click a row with the mouse → same navigation.
- [ ] `Escape` dismisses; clicking outside the popover dismisses.
- [ ] Clear the entry → "Type to search symbols" placeholder; `Enter` does nothing.
- [ ] Type a nonsense query → "No symbols match" placeholder.
- [ ] Remove `"workspaceSymbol"` from `enabledFeatures` in your config → `Shift+F3` does nothing (checkbox is functional).
- [ ] In Preferences the "workspaceSymbol" checkbox is present and unticking it disables the feature.
```

- [ ] **Step 7: Run the full gate (defaults + prefs sync + everything)**

Run:
```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```
Expected: all clean. In particular `tests/unit/test_prefs.py` passes — `FEATURE_CHECKBOX_NAMES` is derived from `DEFAULT_TUNABLES["enabledFeatures"]`, so adding `"workspaceSymbol"` keeps the sync assertion green and the prefs checkbox appears automatically.

- [ ] **Step 8: Commit**

```bash
git add src/gedit_lsp/defaults.py docs/configure.md docs/protocol-coverage.md docs/manual-smoke-test.md tests/integration/test_workspace_symbol_e2e.py
git commit -m "feat(workspace-symbol): defaults, docs (doc-gate), pylsp e2e

Binds Shift+F3, enables workspaceSymbol by default (auto-flows into
the prefs checkbox via FEATURE_CHECKBOX_NAMES + test_prefs sync),
adds workspaceSymbolDebounceMs, documents the keybinding and protocol
coverage, adds the manual-smoke section, and adds an end-to-end test
against real pylsp on the existing multi-file python_rename fixture
(also discharges the roadmap multi-file integration-fixture item).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final cumulative review (before opening the PR)

Per the PR #19 lesson — per-task reviews miss spec gaps that fall *between* tasks. Before opening the PR:

- [ ] Re-read the spec end to end; confirm every UX/edge/config row maps to shipped behavior.
- [ ] Dispatch `superpowers:requesting-code-review` over the cumulative diff `git diff main...feat/workspace-symbol`.
- [ ] Run the full gate once more on the tip: `.venv/bin/python -m pytest tests/ -q && .venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src`.
- [ ] Perform the `docs/manual-smoke-test.md` workspace/symbol section in live gedit (blocking — this is a GTK-heavy + accel + popover feature; smoke is where this class of bug lives). Resolve the `Shift+F3` binding-owner check here; if intercepted, switch the default and amend Task 6's defaults/docs commit.
- [ ] Open the PR (`feat/workspace-symbol` → `main`). CI runs on the PR event. Do **not** touch `docs/roadmap.md` — that entry moves to "Shipped" only at v0.4.0 release time.

---

## Self-Review (plan vs spec)

**Spec coverage:**

- Goal / live quick-pick / server-side filtering → Tasks 3 (controller), 4 (widget). ✓
- Seed from selection/cursor, fully selected → `seed_query` Task 1; entry `select_region(0,-1)` Task 4. ✓
- Capability gate, enabledFeatures gate → Task 3 `trigger`; tests `test_capability_gate`, `test_disabled_feature_noop`. ✓
- Debounce + in-flight cancel + stale-token guard → Task 3; tests + mutation invariant. ✓
- Empty query hint / no-match hint as widget placeholders (not model rows) → Task 3 (`set_results([], hint=...)`), Task 4 (`set_results` renders placeholder, model holds only symbols). ✓
- SymbolInformation + WorkspaceSymbol + resolve fallback / line-0 fallback → Task 3 `_on_activate`/`_navigate`; 4 activation tests. ✓
- Original items preserved for `data`/resolve → Task 1 `parse_symbol_results` returns validated originals; `test_parse_workspacesymbol_without_range_kept`. ✓
- Navigation via `navigate_to_uri` (open/closed/active) → Task 3 `_navigate`. ✓
- Keyboard model (focus in entry; arrows/page/Enter/Esc routed; row-activated) → Task 4 `_on_entry_key`/`_on_row_activated`. ✓
- Callback-clear-before-popdown → Task 4 `_activate_selected`/`_cancel_and_close`/`_on_closed`. ✓
- Injection-safe rendering (plain `Gtk.Label`/`CellRendererText` text, never markup) → Task 4 `_row_label` + `CellRendererText`. ✓
- Shift+F3 default, debounce tunable, enabledFeatures, prefs auto-sync → Task 6. ✓
- Doc-gate (configure + protocol-coverage), smoke checklist → Task 6. ✓
- Integration test on existing multi-file fixture (discharges roadmap housekeeping) → Task 6. ✓
- Dispose (window-scoped; defensive dismiss) → Task 5 `do_deactivate`. ✓
- Final cumulative review + blocking smoke + accel verification → Final section. ✓

No gaps.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows complete code; every command shows expected output.

**Type consistency:** `WorkspaceSymbolController(window, quickpick, config, schedule, cancel)` — same signature in Task 3 definition, Task 3 tests, and Task 5 construction. `quickpick` interface `show(seed, on_query, on_activate, on_cancel)` / `set_results(symbols, *, hint=None)` / `dismiss()` — consistent between Task 3's calls, Task 3's MagicMock assertions, and Task 4's `WorkspaceSymbolQuickPick` definition. `QuickPickModel` API (`set_results`, `selected`, `selected_index`, `move_up/down`, `page_up/down`, `results`) — consistent between Task 2 definition/tests and Task 4 usage. `parse_symbol_results`/`symbol_kind_label`/`seed_query` signatures consistent across Tasks 1, 3, 4. `navigate_to_uri(window, uri, line, column, *, to_iter=...)` matches the existing `references.py` call shape.
