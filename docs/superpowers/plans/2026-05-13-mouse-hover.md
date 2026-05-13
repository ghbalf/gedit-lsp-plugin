# Mouse-Hover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pointer-dwell triggering for `textDocument/hover` — long-lived per-`Gedit.Document` `MouseHoverController` that watches `motion-notify-event`, debounces with a configurable dwell timer, tracks an in-flight request token, and renders responses through the existing hover popover.

**Architecture:** New `MouseHoverController` (per-doc, mirrors `SignatureHelpController` lifecycle). Reuses `textDocument/hover` request shape and the existing `render_hover_contents` plain-text renderer. `HoverController._show_popover` is extracted to a module-level `build_hover_popover` helper so keyboard hover and mouse-hover render identically. Two new tunables (`mouseHover`, `mouseHoverDwellMs`). Anchored to server-returned `range`, falling back to word-bounds at the pointer iter.

**Tech Stack:** Python 3.11+, PyGObject (Gtk 3, GtkSource 300, Gedit 3.0), pytest, ruff, mypy. Test seams: `MagicMock()` for `Gtk.TextView` and `Gtk.Popover`; real `GtkSource.Buffer` is allowed in unit tests per project memory `project_unit_tests_avoid_gtk_widgets`.

---

## File structure

**Create:**
- `src/gedit_lsp/features/mouse_hover.py` — `MouseHoverController` + private helpers (`_iters_from_lsp_range`, `_word_bounds_at`)
- `tests/unit/test_mouse_hover_helpers.py` — pure-helper tests
- `tests/unit/test_mouse_hover_controller.py` — controller invariant tests
- `tests/integration/test_mouse_hover_e2e.py` — pylsp-backed e2e

**Modify:**
- `src/gedit_lsp/features/hover.py` — extract `build_hover_popover` to module scope; `HoverController._show_popover` calls it
- `src/gedit_lsp/defaults.py` — add `mouseHover` and `mouseHoverDwellMs` tunables
- `src/gedit_lsp/plugin.py` — add `_mouse_hover_ctrls` registry; construct in `_attach_document`; dispose in `_on_tab_removed` and `do_deactivate`
- `docs/configure.md` — document the two tunables under the hover section
- `docs/protocol-coverage.md` — note pointer-dwell trigger on the existing `textDocument/hover` row
- `docs/manual-smoke-test.md` — append the mouse-hover smoke checklist

---

## Per-task verification gates

Per memory `feedback_per_task_lint_typecheck_gates`, **every task** ends with these three gates before commit:

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All three must pass cleanly. Per memory `feedback_run_full_test_tree_pre_push`, run the full `tests/` tree (not just `tests/unit/`).

Per memory `project_venv_python_invocation`, use `.venv/bin/python` for all tool invocations (bare `python` lacks dev tools).

---

## Branch

All tasks land on feature branch `feat/mouse-hover` (per project memory `feedback_pr_flow_main_protected`: PR flow required, direct push to main is blocked). Create the branch as the first action of Task 1 if it doesn't yet exist:

```bash
git checkout -b feat/mouse-hover
```

---

## Task 1: Extract `build_hover_popover` from `HoverController`

**Rationale:** `HoverController._show_popover` currently owns popover construction. Mouse-hover needs the same rendering. Extract to a module-level function so both trigger paths render identically and future popover-styling changes don't drift. Behavior-preserving refactor.

**Files:**
- Modify: `src/gedit_lsp/features/hover.py` (extract function; `_show_popover` becomes a one-line caller)
- Test: `tests/unit/test_hover_controller.py` (add one test that exercises the new helper's signature with a fake view)

---

- [ ] **Step 1.1: Add a failing test for the new helper**

Append to `tests/unit/test_hover_controller.py`:

```python
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource

from gedit_lsp.features.hover import build_hover_popover


def test_build_hover_popover_returns_popover_pointing_at_iter() -> None:
    view = MagicMock(spec=Gtk.TextView)
    # iter_location returns a Gdk.Rectangle; we use a MagicMock with the
    # fields the helper reads (x, y, height).
    rect = MagicMock()
    rect.x = 10
    rect.y = 20
    rect.height = 14
    view.get_iter_location.return_value = rect
    view.buffer_to_window_coords.return_value = (10, 34)

    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    anchor = buf.get_iter_at_line_offset(0, 6)  # 'w' in "world"

    popover = build_hover_popover(view, anchor, "type: str")

    assert isinstance(popover, Gtk.Popover)
    view.get_iter_location.assert_called_once_with(anchor)
```

- [ ] **Step 1.2: Run the test — expect ImportError**

```bash
.venv/bin/python -m pytest tests/unit/test_hover_controller.py::test_build_hover_popover_returns_popover_pointing_at_iter -v
```

Expected: FAIL with `ImportError: cannot import name 'build_hover_popover'`.

- [ ] **Step 1.3: Extract the helper**

In `src/gedit_lsp/features/hover.py`, between the `render_hover_contents` function (ending at line 43) and the `HoverController` class (starting at line 46), insert:

```python
def build_hover_popover(
    view: Gtk.TextView, anchor_iter: Gtk.TextIter, text: str
) -> Gtk.Popover:
    """Build a popover anchored at `anchor_iter` showing `text`.

    Used by both Ctrl+K (HoverController) and pointer-dwell
    (MouseHoverController) so the rendered surface stays identical.
    """
    rect = view.get_iter_location(anchor_iter)
    bx, by = view.buffer_to_window_coords(
        Gtk.TextWindowType.WIDGET, rect.x, rect.y + rect.height
    )
    rect.x = bx
    rect.y = by
    rect.width = 1
    rect.height = 1

    popover = Gtk.Popover.new(view)  # type: ignore[call-arg]
    popover.set_pointing_to(rect)
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_min_content_height(120)
    scrolled.set_min_content_width(400)
    inner_buf = GtkSource.Buffer()
    inner_buf.set_text(text)
    inner_view = GtkSource.View.new_with_buffer(inner_buf)
    inner_view.set_editable(False)
    inner_view.set_cursor_visible(False)
    inner_view.set_wrap_mode(Gtk.WrapMode.WORD)
    inner_view.set_monospace(True)
    scrolled.add(inner_view)  # type: ignore[attr-defined]
    popover.add(scrolled)  # type: ignore[attr-defined]
    popover.show_all()  # type: ignore[attr-defined]
    return popover
```

Then replace `HoverController._show_popover` (lines 90–117 of `hover.py`) with:

```python
    def _show_popover(self, anchor_iter: Gtk.TextIter, text: str) -> None:
        if self._popover is not None:
            self._popover.popdown()
        self._popover = build_hover_popover(self._view, anchor_iter, text)
        self._popover.popup()
```

- [ ] **Step 1.4: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

All three must pass.

- [ ] **Step 1.5: Commit**

```bash
git checkout -b feat/mouse-hover  # if not already on branch
git add src/gedit_lsp/features/hover.py tests/unit/test_hover_controller.py
git commit -m "refactor(hover): extract build_hover_popover for reuse by mouse-hover"
```

---

## Task 2: Add `mouseHover` and `mouseHoverDwellMs` tunables

**Files:**
- Modify: `src/gedit_lsp/defaults.py` (add two keys to `DEFAULT_TUNABLES`)
- Test: `tests/unit/test_config.py` (one test asserting the new defaults)

---

- [ ] **Step 2.1: Write a failing test**

Append to `tests/unit/test_config.py`:

```python
def test_mouse_hover_defaults_present() -> None:
    from gedit_lsp.defaults import DEFAULT_TUNABLES
    assert DEFAULT_TUNABLES["mouseHover"] is True
    assert DEFAULT_TUNABLES["mouseHoverDwellMs"] == 300
```

- [ ] **Step 2.2: Run — expect KeyError**

```bash
.venv/bin/python -m pytest tests/unit/test_config.py::test_mouse_hover_defaults_present -v
```

Expected: FAIL with `KeyError: 'mouseHover'`.

- [ ] **Step 2.3: Add the defaults**

In `src/gedit_lsp/defaults.py`, locate the `DEFAULT_TUNABLES` dict containing `"hoverSpinnerThresholdMs": 300`. Add the two new keys directly under it:

```python
    "hoverSpinnerThresholdMs": 300,
    "mouseHover":              True,
    "mouseHoverDwellMs":       300,
```

- [ ] **Step 2.4: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 2.5: Commit**

```bash
git add src/gedit_lsp/defaults.py tests/unit/test_config.py
git commit -m "feat(mouse-hover): add mouseHover and mouseHoverDwellMs tunables"
```

---

## Task 3: Pure helpers — `_iters_from_lsp_range`, `_word_bounds_at`

**Rationale:** These convert raw input (LSP range, buffer iter) into `(start, end)` `Gtk.TextIter` pairs used for popover anchoring. They are pure and testable with a real `GtkSource.Buffer` (no widgets).

**Files:**
- Create: `src/gedit_lsp/features/mouse_hover.py` (helpers only at this point)
- Create: `tests/unit/test_mouse_hover_helpers.py`

---

- [ ] **Step 3.1: Write failing tests for both helpers**

Create `tests/unit/test_mouse_hover_helpers.py`:

```python
"""Unit tests for mouse_hover pure helpers."""
from __future__ import annotations

import gi

gi.require_version("GtkSource", "300")
from gi.repository import GtkSource

from gedit_lsp.features.mouse_hover import _iters_from_lsp_range, _word_bounds_at


def _buffer_with(text: str) -> GtkSource.Buffer:
    buf = GtkSource.Buffer()
    buf.set_text(text)
    return buf


def test_iters_from_lsp_range_single_line() -> None:
    buf = _buffer_with("hello world\n")
    rng = {
        "start": {"line": 0, "character": 6},
        "end":   {"line": 0, "character": 11},
    }
    start, end = _iters_from_lsp_range(buf, rng)
    assert start.get_line() == 0 and start.get_line_offset() == 6
    assert end.get_line() == 0 and end.get_line_offset() == 11
    assert buf.get_text(start, end, False) == "world"


def test_iters_from_lsp_range_multi_byte_utf8() -> None:
    # "α" is one codepoint, one UTF-16 unit, two UTF-8 bytes.
    buf = _buffer_with("αβγ\n")
    rng = {
        "start": {"line": 0, "character": 1},
        "end":   {"line": 0, "character": 2},
    }
    start, end = _iters_from_lsp_range(buf, rng)
    assert buf.get_text(start, end, False) == "β"


def test_word_bounds_at_mid_word() -> None:
    buf = _buffer_with("hello world\n")
    cursor = buf.get_iter_at_line_offset(0, 8)  # inside "world"
    start, end = _word_bounds_at(cursor)
    assert buf.get_text(start, end, False) == "world"


def test_word_bounds_at_on_whitespace_returns_single_char_range() -> None:
    buf = _buffer_with("hello world\n")
    cursor = buf.get_iter_at_line_offset(0, 5)  # the space
    start, end = _word_bounds_at(cursor)
    # Falls back: one-character range starting at the iter.
    assert end.get_offset() - start.get_offset() == 1


def test_word_bounds_at_start_of_buffer() -> None:
    buf = _buffer_with("hello\n")
    cursor = buf.get_iter_at_line_offset(0, 0)
    start, end = _word_bounds_at(cursor)
    assert buf.get_text(start, end, False) == "hello"
```

- [ ] **Step 3.2: Run — expect ModuleNotFoundError**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_helpers.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gedit_lsp.features.mouse_hover'`.

- [ ] **Step 3.3: Create the module with the two helpers**

Create `src/gedit_lsp/features/mouse_hover.py`:

```python
"""MouseHoverController — pointer-dwell triggering for textDocument/hover.

Long-lived per-Gedit.Document object. Watches motion-notify-event,
debounces dwell with a configurable timer, tracks an in-flight request
token to drop stale responses, and renders results through the shared
`build_hover_popover` helper.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import gi

logger = logging.getLogger("gedit_lsp.mouse_hover")

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource

from gedit_lsp.utf16 import utf16_to_text_iter

if TYPE_CHECKING:
    from gedit_lsp.server import LanguageServer


def _iters_from_lsp_range(
    buffer: GtkSource.Buffer, lsp_range: dict[str, Any]
) -> tuple[Gtk.TextIter, Gtk.TextIter]:
    """Convert an LSP `Range` (UTF-16) to a `(start, end)` iter pair."""
    s = lsp_range["start"]
    e = lsp_range["end"]
    start = utf16_to_text_iter(buffer, s["line"], s["character"])
    end = utf16_to_text_iter(buffer, e["line"], e["character"])
    return start, end


def _word_bounds_at(
    cursor: Gtk.TextIter,
) -> tuple[Gtk.TextIter, Gtk.TextIter]:
    """Return the word range surrounding `cursor`.

    If `cursor` is not on a word character, returns a one-character
    range starting at `cursor` (so the popover still anchors somewhere
    reasonable).
    """
    start = cursor.copy()
    end = cursor.copy()
    if start.inside_word() or start.ends_word():
        if not start.starts_word():
            start.backward_word_start()
        if not end.ends_word():
            end.forward_word_end()
        return start, end
    # Fallback: one-character range.
    if not end.is_end():
        end.forward_char()
    return start, end
```

- [ ] **Step 3.4: Run — expect tests pass**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_helpers.py -v
```

Expected: 5 passed.

- [ ] **Step 3.5: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 3.6: Commit**

```bash
git add src/gedit_lsp/features/mouse_hover.py tests/unit/test_mouse_hover_helpers.py
git commit -m "feat(mouse-hover): _iters_from_lsp_range and _word_bounds_at helpers"
```

---

## Task 4: `MouseHoverController` skeleton — construction, signal attachment, dispose

**Rationale:** Establish the lifecycle shape before adding behavior. After this task the controller can be constructed and disposed cleanly with no functional motion handling yet (the `_on_motion` method is a no-op stub).

**Files:**
- Modify: `src/gedit_lsp/features/mouse_hover.py` (add class)
- Create: `tests/unit/test_mouse_hover_controller.py`

---

- [ ] **Step 4.1: Write failing tests for construction + dispose**

Create `tests/unit/test_mouse_hover_controller.py`:

```python
"""Unit tests for MouseHoverController — construction, dispose, signal wiring."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource

from gedit_lsp.features.mouse_hover import MouseHoverController


class FakeServer:
    """Minimal LanguageServer stand-in for controller tests."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict, Any]] = []

    def capability(self, key: str) -> Any:
        return True if key == "hoverProvider" else None

    def _send_request(self, method: str, params: dict, cb: Any) -> int:
        self.requests.append((method, params, cb))
        return len(self.requests)


def _make_view() -> Any:
    view = MagicMock(spec=Gtk.TextView)
    # Return integer handler IDs so tests can verify disconnect calls.
    counter = iter(range(1000, 2000))
    view.connect.side_effect = lambda *_a, **_kw: next(counter)
    return view


def _make_ctrl(
    *, view: Any = None, buf: GtkSource.Buffer | None = None,
    server: FakeServer | None = None, dwell_ms: int = 300,
) -> MouseHoverController:
    return MouseHoverController(
        view=view or _make_view(),
        buffer=buf or GtkSource.Buffer(),
        server=server or FakeServer(),
        uri="file:///a.py",
        dwell_ms=dwell_ms,
        spinner_threshold_ms=300,
    )


def test_construction_connects_motion_and_dismissal_signals() -> None:
    view = _make_view()
    _make_ctrl(view=view)
    connected = [call.args[0] for call in view.connect.call_args_list]
    assert "motion-notify-event" in connected
    assert "leave-notify-event" in connected
    assert "focus-out-event" in connected
    assert "key-press-event" in connected
    assert "button-press-event" in connected


def test_dispose_disconnects_all_signals() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl.dispose()
    # One disconnect per connect call.
    assert view.disconnect.call_count == view.connect.call_count


def test_dispose_is_idempotent() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl.dispose()
    # Second dispose must not raise and must not double-disconnect.
    pre = view.disconnect.call_count
    ctrl.dispose()
    assert view.disconnect.call_count == pre


def test_dispose_increments_request_token() -> None:
    ctrl = _make_ctrl()
    tok_before = ctrl._request_token
    ctrl.dispose()
    assert ctrl._request_token == tok_before + 1
```

- [ ] **Step 4.2: Run — expect ImportError on `MouseHoverController`**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: FAIL with `ImportError: cannot import name 'MouseHoverController'`.

- [ ] **Step 4.3: Add the controller skeleton**

Append to `src/gedit_lsp/features/mouse_hover.py`:

```python
import contextlib


class MouseHoverController:
    def __init__(
        self,
        *,
        view: Gtk.TextView,
        buffer: GtkSource.Buffer,
        server: "LanguageServer",
        uri: str,
        dwell_ms: int,
        spinner_threshold_ms: int,
    ) -> None:
        self._view = view
        self._buffer = buffer
        self._server = server
        self._uri = uri
        self._dwell_ms = dwell_ms
        self._spinner_threshold_ms = spinner_threshold_ms

        self._timer_id: int | None = None
        self._grace_timer_id: int | None = None
        self._request_token: int = 0
        self._popover: Gtk.Popover | None = None
        self._anchor_range: tuple[Gtk.TextIter, Gtk.TextIter] | None = None
        self._pointer_in_popover: bool = False
        self._disposed: bool = False
        self._view_handler_ids: list[int] = []

        self._view_handler_ids.append(
            view.connect("motion-notify-event", self._on_motion),
        )
        self._view_handler_ids.append(
            view.connect("leave-notify-event", self._on_view_leave),
        )
        self._view_handler_ids.append(
            view.connect("focus-out-event", self._on_focus_out),
        )
        self._view_handler_ids.append(
            view.connect("key-press-event", self._on_key_press),
        )
        self._view_handler_ids.append(
            view.connect("button-press-event", self._on_button_press),
        )
        logger.info("mouse-hover controller wired uri=%s dwell_ms=%d", uri, dwell_ms)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._cancel_timer()
        self._cancel_grace_timer()
        self._request_token += 1
        for hid in self._view_handler_ids:
            with contextlib.suppress(TypeError, RuntimeError):
                self._view.disconnect(hid)
        self._view_handler_ids.clear()
        self._dismiss_popover()
        self._anchor_range = None
        self._pointer_in_popover = False

    # --- helpers ---

    def _cancel_timer(self) -> None:
        if self._timer_id is not None:
            from gi.repository import GLib
            with contextlib.suppress(Exception):
                GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _cancel_grace_timer(self) -> None:
        if self._grace_timer_id is not None:
            from gi.repository import GLib
            with contextlib.suppress(Exception):
                GLib.source_remove(self._grace_timer_id)
            self._grace_timer_id = None

    def _dismiss_popover(self) -> None:
        if self._popover is not None:
            with contextlib.suppress(Exception):
                self._popover.popdown()
            self._popover = None

    # --- signal handlers (stubs; behavior added in later tasks) ---

    def _on_motion(self, _view: Any, _event: Any) -> bool:
        return False

    def _on_view_leave(self, _view: Any, _event: Any) -> bool:
        return False

    def _on_focus_out(self, _view: Any, _event: Any) -> bool:
        return False

    def _on_key_press(self, _view: Any, _event: Any) -> bool:
        return False

    def _on_button_press(self, _view: Any, _event: Any) -> bool:
        return False
```

- [ ] **Step 4.4: Run — expect tests pass**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: 4 passed.

- [ ] **Step 4.5: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 4.6: Commit**

```bash
git add src/gedit_lsp/features/mouse_hover.py tests/unit/test_mouse_hover_controller.py
git commit -m "feat(mouse-hover): MouseHoverController skeleton with signal wiring + dispose"
```

---

## Task 5: Motion handler — schedule, cancel, token, drag-suppress, anchor-range gate, over_text gate

**Files:**
- Modify: `src/gedit_lsp/features/mouse_hover.py` (`_on_motion` and supporting state)
- Modify: `tests/unit/test_mouse_hover_controller.py` (motion invariants)

---

- [ ] **Step 5.1: Write failing tests — six invariants**

Append to `tests/unit/test_mouse_hover_controller.py`:

```python
from unittest.mock import patch


def _motion_event(x: float = 5.0, y: float = 5.0, state: int = 0) -> Any:
    event = MagicMock()
    event.x = x
    event.y = y
    event.state = state
    return event


def _stub_iter_at_location(
    view: Any, *, over_text: bool, line: int = 0, char: int = 0,
) -> Gtk.TextIter:
    """Make view.get_iter_at_location return a real iter from a real buffer."""
    buf = GtkSource.Buffer()
    buf.set_text("hello world\nsecond line\n")
    iter_ = buf.get_iter_at_line_offset(line, char)
    view.get_iter_at_location.return_value = (over_text, iter_)
    view.window_to_buffer_coords.return_value = (1, 1)
    return iter_


def test_motion_over_text_schedules_a_timer(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    add_calls: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, cb, *args, **kw: (add_calls.append((ms, cb)), 42)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert len(add_calls) == 1
    assert add_calls[0][0] == 300  # dwell_ms
    assert ctrl._timer_id == 42


def test_second_motion_cancels_first_timer(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    ids = iter([42, 43])
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: next(ids),
    )
    removed: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.source_remove",
        lambda src: removed.append(src),
    )

    ctrl._on_motion(view, _motion_event())
    ctrl._on_motion(view, _motion_event(x=6))

    assert removed == [42]
    assert ctrl._timer_id == 43


def test_motion_over_whitespace_does_not_schedule(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=False)
    add_calls: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (add_calls.append(1), 0)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert add_calls == []
    assert ctrl._timer_id is None


def test_motion_with_button_pressed_does_not_schedule(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    add_calls: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (add_calls.append(1), 0)[1],
    )

    from gi.repository import Gdk
    btn_mask = Gdk.ModifierType.BUTTON1_MASK

    ctrl._on_motion(view, _motion_event(state=btn_mask))

    assert add_calls == []


def test_motion_inside_existing_anchor_range_skips_reschedule(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    start = buf.get_iter_at_line_offset(0, 6)
    end = buf.get_iter_at_line_offset(0, 11)
    inside = buf.get_iter_at_line_offset(0, 8)
    ctrl._anchor_range = (start, end)
    ctrl._popover = MagicMock()  # any non-None
    view.get_iter_at_location.return_value = (True, inside)
    view.window_to_buffer_coords.return_value = (1, 1)
    add_calls: list[int] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda *_a, **_kw: (add_calls.append(1), 0)[1],
    )

    ctrl._on_motion(view, _motion_event())

    assert add_calls == []


def test_motion_increments_request_token(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    _stub_iter_at_location(view, over_text=True)
    monkeypatch.setattr("gi.repository.GLib.timeout_add", lambda *_a, **_kw: 1)
    tok_before = ctrl._request_token

    ctrl._on_motion(view, _motion_event())

    assert ctrl._request_token == tok_before + 1
```

- [ ] **Step 5.2: Run — expect failures**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: 6 new tests FAIL (motion is still a stub).

- [ ] **Step 5.3: Implement `_on_motion`**

In `src/gedit_lsp/features/mouse_hover.py`, replace the stub `_on_motion` with:

```python
    def _on_motion(self, view: Any, event: Any) -> bool:
        from gi.repository import Gdk, GLib

        # Drag-suppress: any mouse button held → not dwell.
        any_button_mask = (
            Gdk.ModifierType.BUTTON1_MASK
            | Gdk.ModifierType.BUTTON2_MASK
            | Gdk.ModifierType.BUTTON3_MASK
        )
        if event.state & any_button_mask:
            return False

        self._cancel_timer()
        self._request_token += 1
        captured_token = self._request_token

        bx, by = view.window_to_buffer_coords(
            Gtk.TextWindowType.WIDGET, int(event.x), int(event.y)
        )
        over_text, buffer_iter = view.get_iter_at_location(bx, by)

        if not over_text:
            return False

        # If popover is up and pointer is still inside the anchored range,
        # leave it alone — stable hover, no re-fire.
        if self._popover is not None and self._anchor_range is not None:
            start, end = self._anchor_range
            if start.get_offset() <= buffer_iter.get_offset() < end.get_offset():
                return False

        self._timer_id = GLib.timeout_add(
            self._dwell_ms, self._on_dwell, captured_token, buffer_iter,
        )
        return False
```

Also add a stub `_on_dwell` (real impl in Task 6):

```python
    def _on_dwell(
        self, _captured_token: int, _buffer_iter: Gtk.TextIter,
    ) -> bool:
        return False  # one-shot
```

- [ ] **Step 5.4: Run — expect tests pass**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: all motion tests pass.

- [ ] **Step 5.5: Mutation-pin one critical invariant (project memory `feedback_mutation_test_invariants`)**

Verify the anchor-range gate actually fires by temporarily breaking it:

```bash
# Break the guard, watch the test fail:
sed -i 's|if start.get_offset() <= buffer_iter.get_offset() < end.get_offset():|if False:|' src/gedit_lsp/features/mouse_hover.py
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py::test_motion_inside_existing_anchor_range_skips_reschedule -v
# Expected: FAIL
# Restore:
git checkout src/gedit_lsp/features/mouse_hover.py
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py::test_motion_inside_existing_anchor_range_skips_reschedule -v
# Expected: PASS
```

- [ ] **Step 5.6: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 5.7: Commit**

```bash
git add src/gedit_lsp/features/mouse_hover.py tests/unit/test_mouse_hover_controller.py
git commit -m "feat(mouse-hover): motion handler with debounce, token, gates, drag-suppress"
```

---

## Task 6: Dwell → request → response → popover

**Files:**
- Modify: `src/gedit_lsp/features/mouse_hover.py` (`_on_dwell`, `_on_response`)
- Modify: `tests/unit/test_mouse_hover_controller.py`

---

- [ ] **Step 6.1: Write failing tests**

Append to `tests/unit/test_mouse_hover_controller.py`:

```python
def test_dwell_sends_hover_request_with_position() -> None:
    view = _make_view()
    server = FakeServer()
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    ctrl = _make_ctrl(view=view, server=server, buf=buf)
    anchor = buf.get_iter_at_line_offset(0, 6)

    ctrl._on_dwell(ctrl._request_token, anchor)

    assert len(server.requests) == 1
    method, params, _cb = server.requests[0]
    assert method == "textDocument/hover"
    assert params["textDocument"]["uri"] == "file:///a.py"
    assert params["position"] == {"line": 0, "character": 6}


def test_stale_token_dwell_drops_request() -> None:
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    buf = GtkSource.Buffer()
    buf.set_text("hello\n")
    anchor = buf.get_iter_at_line_offset(0, 0)

    stale = ctrl._request_token
    ctrl._request_token += 1  # simulate cancel

    ctrl._on_dwell(stale, anchor)

    assert server.requests == []


def test_response_with_token_match_builds_popover(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    ctrl = _make_ctrl(view=view, server=server, buf=buf)
    anchor = buf.get_iter_at_line_offset(0, 6)
    built: list[tuple[Any, Any, str]] = []
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda v, it, txt: (built.append((v, it, txt)), MagicMock())[1],
    )

    ctrl._on_response(
        ctrl._request_token, anchor,
        {"result": {"contents": "type: str",
                    "range": {"start": {"line": 0, "character": 6},
                              "end":   {"line": 0, "character": 11}}}},
    )

    assert len(built) == 1
    assert built[0][2] == "type: str"
    assert ctrl._popover is not None
    assert ctrl._anchor_range is not None


def test_response_stale_token_does_not_build_popover(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    built: list[int] = []
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda *_a, **_kw: (built.append(1), MagicMock())[1],
    )
    buf = GtkSource.Buffer()
    buf.set_text("hello\n")
    anchor = buf.get_iter_at_line_offset(0, 0)
    stale = ctrl._request_token
    ctrl._request_token += 1

    ctrl._on_response(
        stale, anchor,
        {"result": {"contents": "x"}},
    )

    assert built == []
    assert ctrl._popover is None


def test_response_empty_contents_does_not_build_popover(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    built: list[int] = []
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda *_a, **_kw: (built.append(1), MagicMock())[1],
    )
    buf = GtkSource.Buffer()
    buf.set_text("hello\n")
    anchor = buf.get_iter_at_line_offset(0, 0)

    ctrl._on_response(
        ctrl._request_token, anchor,
        {"result": {"contents": "   \n  "}},
    )

    assert built == []


def test_response_error_does_not_build_popover(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    ctrl = _make_ctrl(view=view, server=server)
    built: list[int] = []
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda *_a, **_kw: (built.append(1), MagicMock())[1],
    )
    buf = GtkSource.Buffer()
    buf.set_text("hello\n")
    anchor = buf.get_iter_at_line_offset(0, 0)

    ctrl._on_response(
        ctrl._request_token, anchor,
        {"error": {"code": -32603, "message": "boom"}},
    )

    assert built == []


def test_response_without_server_range_falls_back_to_word_bounds(monkeypatch: Any) -> None:
    view = _make_view()
    server = FakeServer()
    buf = GtkSource.Buffer()
    buf.set_text("hello world\n")
    ctrl = _make_ctrl(view=view, server=server, buf=buf)
    anchor = buf.get_iter_at_line_offset(0, 8)  # inside "world"
    monkeypatch.setattr(
        "gedit_lsp.features.mouse_hover.build_hover_popover",
        lambda *_a, **_kw: MagicMock(),
    )

    ctrl._on_response(
        ctrl._request_token, anchor,
        {"result": {"contents": "type: str"}},  # no range
    )

    assert ctrl._anchor_range is not None
    start, end = ctrl._anchor_range
    assert buf.get_text(start, end, False) == "world"
```

- [ ] **Step 6.2: Run — expect failures**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: the seven new tests FAIL.

- [ ] **Step 6.3: Promote two imports to module scope**

In `src/gedit_lsp/features/mouse_hover.py`, locate the existing import block (under `from gedit_lsp.utf16 import utf16_to_text_iter`) and replace/append it so the module's import section reads:

```python
from gedit_lsp.features.hover import build_hover_popover, render_hover_contents
from gedit_lsp.utf16 import text_iter_to_utf16, utf16_to_text_iter
```

Module-scope (not function-scope) imports are required because the controller tests in Step 6.1 and the e2e test in Task 9 rely on patching `gedit_lsp.features.mouse_hover.build_hover_popover` — that only works if the name is bound on the module.

- [ ] **Step 6.4: Implement `_on_dwell` and `_on_response`**

Replace the stub `_on_dwell` in `src/gedit_lsp/features/mouse_hover.py` and add `_on_response`:

```python
    def _on_dwell(
        self, captured_token: int, buffer_iter: Gtk.TextIter,
    ) -> bool:
        # If our token moved on (motion canceled us), drop silently.
        if captured_token != self._request_token:
            return False
        self._timer_id = None

        line, char = text_iter_to_utf16(buffer_iter)
        logger.info(
            "mouse-hover dwell: uri=%s pos=%d:%d token=%d",
            self._uri, line, char, captured_token,
        )

        self._server._send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": self._uri},
                "position": {"line": line, "character": char},
            },
            lambda msg: self._on_response(captured_token, buffer_iter, msg),
        )
        return False

    def _on_response(
        self,
        captured_token: int,
        anchor_iter: Gtk.TextIter,
        msg: dict[str, Any],
    ) -> None:
        if captured_token != self._request_token:
            logger.debug("mouse-hover response: stale token %d", captured_token)
            return
        if msg.get("error"):
            logger.info("mouse-hover response: error=%r", msg.get("error"))
            return
        result = msg.get("result")
        if result is None:
            return

        text = render_hover_contents(result.get("contents"))
        if not text.strip():
            return

        server_range = result.get("range")
        if server_range:
            start_iter, end_iter = _iters_from_lsp_range(
                self._buffer, server_range,
            )
        else:
            start_iter, end_iter = _word_bounds_at(anchor_iter)

        # Pop any previous popover before replacing.
        self._dismiss_popover()
        self._anchor_range = (start_iter, end_iter)
        self._popover = build_hover_popover(self._view, start_iter, text)
        self._popover.popup()
```

- [ ] **Step 6.5: Run — expect tests pass**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: all controller tests pass.

- [ ] **Step 6.6: Mutation-pin the token-stale guard**

```bash
sed -i 's|if captured_token != self._request_token:|if False:|' src/gedit_lsp/features/mouse_hover.py
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py::test_response_stale_token_does_not_build_popover -v
# Expected: FAIL
git checkout src/gedit_lsp/features/mouse_hover.py
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py::test_response_stale_token_does_not_build_popover -v
# Expected: PASS
```

Note: the `sed` command above replaces *every* occurrence of the token check (there are two — `_on_dwell` and `_on_response`). Both should be exercised by the test failure; restore with `git checkout`.

- [ ] **Step 6.7: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 6.8: Commit**

```bash
git add src/gedit_lsp/features/mouse_hover.py tests/unit/test_mouse_hover_controller.py
git commit -m "feat(mouse-hover): dwell-fire, request, response, popover with token + anchoring"
```

---

## Task 7: Dismissal events + grace timer + popover pointer tracking

**Files:**
- Modify: `src/gedit_lsp/features/mouse_hover.py` (`_on_view_leave`, `_on_focus_out`, `_on_key_press`, `_on_button_press`; pointer tracking on popover)
- Modify: `tests/unit/test_mouse_hover_controller.py`

---

- [ ] **Step 7.1: Write failing tests**

Append to `tests/unit/test_mouse_hover_controller.py`:

```python
def test_key_press_dismisses_popover() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()
    ctrl._anchor_range = (MagicMock(), MagicMock())

    ctrl._on_key_press(view, MagicMock())

    assert ctrl._popover is None
    assert ctrl._anchor_range is None


def test_button_press_dismisses_popover() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    pop = MagicMock()
    ctrl._popover = pop
    ctrl._anchor_range = (MagicMock(), MagicMock())

    ctrl._on_button_press(view, MagicMock())

    pop.popdown.assert_called_once()
    assert ctrl._popover is None


def test_focus_out_dismisses_popover() -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()

    ctrl._on_focus_out(view, MagicMock())

    assert ctrl._popover is None


def test_view_leave_with_pointer_in_popover_does_not_dismiss(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    pop = MagicMock()
    ctrl._popover = pop
    ctrl._pointer_in_popover = True
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add", lambda *_a, **_kw: 99,
    )

    ctrl._on_view_leave(view, MagicMock())

    pop.popdown.assert_not_called()
    assert ctrl._popover is pop


def test_view_leave_without_pointer_in_popover_schedules_grace_dismiss(monkeypatch: Any) -> None:
    view = _make_view()
    ctrl = _make_ctrl(view=view)
    ctrl._popover = MagicMock()
    scheduled: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        "gi.repository.GLib.timeout_add",
        lambda ms, cb, *a, **kw: (scheduled.append((ms, cb)), 77)[1],
    )

    ctrl._on_view_leave(view, MagicMock())

    assert len(scheduled) == 1
    assert scheduled[0][0] == 150  # grace_ms
    assert ctrl._grace_timer_id == 77
```

- [ ] **Step 7.2: Run — expect failures**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: five new tests FAIL.

- [ ] **Step 7.3: Implement dismissal handlers**

In `src/gedit_lsp/features/mouse_hover.py`, replace the four stub handlers (`_on_view_leave`, `_on_focus_out`, `_on_key_press`, `_on_button_press`) with:

```python
    _GRACE_MS = 150

    def _on_view_leave(self, _view: Any, _event: Any) -> bool:
        if self._popover is None:
            return False
        if self._pointer_in_popover:
            return False
        from gi.repository import GLib
        self._cancel_grace_timer()
        self._grace_timer_id = GLib.timeout_add(
            self._GRACE_MS, self._on_grace_expired,
        )
        return False

    def _on_grace_expired(self) -> bool:
        self._grace_timer_id = None
        if not self._pointer_in_popover:
            self._dismiss_state()
        return False  # one-shot

    def _on_focus_out(self, _view: Any, _event: Any) -> bool:
        self._dismiss_state()
        return False

    def _on_key_press(self, _view: Any, _event: Any) -> bool:
        self._dismiss_state()
        return False

    def _on_button_press(self, _view: Any, _event: Any) -> bool:
        self._dismiss_state()
        return False

    def _dismiss_state(self) -> None:
        """Cancel pending work and dismiss the popover."""
        self._cancel_timer()
        self._cancel_grace_timer()
        self._request_token += 1
        self._dismiss_popover()
        self._anchor_range = None
        self._pointer_in_popover = False
```

Note: `_GRACE_MS` is a class constant; tests assert it equals 150.

Also wire popover-side pointer tracking when the popover is created. Modify the line `self._popover = build_hover_popover(self._view, start_iter, text)` in `_on_response` so it attaches pointer-tracking signals immediately after:

```python
        self._dismiss_popover()
        self._anchor_range = (start_iter, end_iter)
        self._popover = build_hover_popover(self._view, start_iter, text)
        self._attach_popover_pointer_tracking(self._popover)
        self._popover.popup()
```

And add the helper:

```python
    def _attach_popover_pointer_tracking(self, popover: Gtk.Popover) -> None:
        def on_enter(_w: Any, _e: Any) -> bool:
            self._pointer_in_popover = True
            self._cancel_grace_timer()
            return False

        def on_leave(_w: Any, _e: Any) -> bool:
            self._pointer_in_popover = False
            return False

        with contextlib.suppress(Exception):
            popover.connect("enter-notify-event", on_enter)
            popover.connect("leave-notify-event", on_leave)
            popover.connect(
                "closed",
                lambda _p: setattr(self, "_popover", None),
            )
```

- [ ] **Step 7.4: Run — expect tests pass**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: all controller tests pass.

- [ ] **Step 7.5: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 7.6: Commit**

```bash
git add src/gedit_lsp/features/mouse_hover.py tests/unit/test_mouse_hover_controller.py
git commit -m "feat(mouse-hover): dismissal handlers, grace timer, popover pointer tracking"
```

---

## Task 8: Plugin wiring

**Rationale:** Up to now `MouseHoverController` is unreachable from the plugin. Hook it into the per-document registry, gate on capability + tunable, and dispose on tab-removed / deactivate.

**Files:**
- Modify: `src/gedit_lsp/plugin.py` (registry, attach in `_attach_document`, dispose in `_on_tab_removed` and `do_deactivate`)
- Modify: `tests/unit/test_mouse_hover_controller.py` (a small plugin-wiring assertion via direct import, since plugin.py has no widget-free unit harness — *see Step 8.1 below*)

---

- [ ] **Step 8.1: Write a small assertion test for the capability/tunable gate**

The gate logic (`config.tunable("mouseHover") and server.capability("hoverProvider")`) lives in `plugin.py`. Rather than spinning up the full plugin, extract that decision into a pure helper. Append to `src/gedit_lsp/features/mouse_hover.py`:

```python
def should_attach_mouse_hover(
    *, tunable_enabled: bool, hover_capability: Any
) -> bool:
    """Return True iff a MouseHoverController should be attached.

    Tunable on/off + server's `hoverProvider` capability (truthy = present).
    Lifted out of plugin.py so it's unit-testable without the full plugin.
    """
    return bool(tunable_enabled) and bool(hover_capability)
```

Append to `tests/unit/test_mouse_hover_controller.py`:

```python
from gedit_lsp.features.mouse_hover import should_attach_mouse_hover


def test_should_attach_when_tunable_on_and_capability_present() -> None:
    assert should_attach_mouse_hover(tunable_enabled=True, hover_capability=True)
    assert should_attach_mouse_hover(
        tunable_enabled=True, hover_capability={"workDoneProgress": False},
    )


def test_should_not_attach_when_tunable_off() -> None:
    assert not should_attach_mouse_hover(
        tunable_enabled=False, hover_capability=True,
    )


def test_should_not_attach_when_capability_missing() -> None:
    assert not should_attach_mouse_hover(
        tunable_enabled=True, hover_capability=None,
    )
    assert not should_attach_mouse_hover(
        tunable_enabled=True, hover_capability=False,
    )
```

- [ ] **Step 8.2: Run — expect tests pass after adding the helper**

```bash
.venv/bin/python -m pytest tests/unit/test_mouse_hover_controller.py -v
```

Expected: the three new gate-helper tests pass.

- [ ] **Step 8.3: Wire the controller into `plugin.py`**

In `src/gedit_lsp/plugin.py`:

1. Add the import near the other feature imports (around line 45 where `HoverController` is imported):

   ```python
   from gedit_lsp.features.mouse_hover import (
       MouseHoverController,
       should_attach_mouse_hover,
   )
   ```

2. Add the registry to the constructor, alongside the existing controller registries (around line 140 where `_formatting_ctrls` is defined). Insert:

   ```python
           self._mouse_hover_ctrls: dict[Gedit.Document, MouseHoverController] = {}
   ```

3. In `_attach_document`, after the server is up and bridge is created (locate the section where `_sighelp_ctrls` is created — the pattern matches), append:

   ```python
           if should_attach_mouse_hover(
               tunable_enabled=self._config.tunable("mouseHover"),
               hover_capability=server.capability("hoverProvider"),
           ):
               view = next(
                   (v for v in self.window.get_views() if v.get_buffer() is doc),
                   None,
               )
               if view is not None:
                   self._mouse_hover_ctrls[doc] = MouseHoverController(
                       view=view,
                       buffer=doc,
                       server=server,
                       uri=bridge.uri,
                       dwell_ms=self._config.tunable("mouseHoverDwellMs"),
                       spinner_threshold_ms=self._config.tunable(
                           "hoverSpinnerThresholdMs",
                       ),
                   )
   ```

4. In `_on_tab_removed`, after the existing `_sighelp_ctrls` cleanup (around line 274), insert:

   ```python
           mh_ctrl = self._mouse_hover_ctrls.pop(doc, None)
           if mh_ctrl is not None:
               mh_ctrl.dispose()
   ```

5. In `do_deactivate`, alongside the other registry teardowns (around line 226), append:

   ```python
           for mh_ctrl in self._mouse_hover_ctrls.values():
               mh_ctrl.dispose()
           self._mouse_hover_ctrls.clear()
   ```

- [ ] **Step 8.4: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 8.5: Commit**

```bash
git add src/gedit_lsp/plugin.py src/gedit_lsp/features/mouse_hover.py tests/unit/test_mouse_hover_controller.py
git commit -m "feat(mouse-hover): wire MouseHoverController into plugin lifecycle"
```

---

## Task 9: Integration test — e2e against pylsp

**Files:**
- Create: `tests/integration/test_mouse_hover_e2e.py`

---

- [ ] **Step 9.1: Write the e2e test**

Create `tests/integration/test_mouse_hover_e2e.py`:

```python
"""End-to-end mouse-hover test against pylsp.

Drives a real MouseHoverController against a real pylsp by directly
calling _on_dwell (the equivalent of "timer fired") with a known anchor
iter. Verifies that:
  * the controller sends textDocument/hover with the correct position,
  * the response arrives and is rendered into a popover.

We don't synthesize a real motion-notify-event because (a) test
machines may run headless and (b) the motion → timer → dwell path is
already covered by unit tests; the e2e gate is "the actual server
round-trip with anchored response works".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import GLib, Gtk, GtkSource

from gedit_lsp.bridge import DocumentBridge, GLibClock
from gedit_lsp.features.mouse_hover import MouseHoverController
from gedit_lsp.registry import ServerRegistry


def test_mouse_hover_e2e_returns_response_and_anchors(
    pylsp_available: None,
    tmp_path: Path,
    registry: ServerRegistry,
    main_loop: GLib.MainLoop,
) -> None:
    src = tmp_path / "main.py"
    src.write_text(
        "import os\nresult = os.path.join(\"a\", \"b\")\nprint(result)\n"
    )
    (tmp_path / ".git").mkdir()

    server = registry.get_or_spawn("python", tmp_path)
    assert server is not None
    server.attach_buffer(src.as_uri())

    buf = GtkSource.Buffer()
    buf.set_text(src.read_text())
    bridge = DocumentBridge(
        uri=src.as_uri(), language_id="python", text=src.read_text(),
        server=server, clock=GLibClock(), debounce_ms=150,
    )
    bridge.attach()

    # Wait for initialize/initialized handshake.
    def _short_quit() -> bool:
        main_loop.quit()
        return False
    GLib.timeout_add_seconds(2, _short_quit)
    main_loop.run()  # type: ignore[no-untyped-call]

    # Build a controller against a fake view but the real buffer + server.
    view = MagicMock(spec=Gtk.TextView)
    # build_hover_popover is widget-dependent; stub it so we don't need a
    # display to construct the popover. We assert the controller calls it
    # with the right arguments.
    built: list[tuple[Any, Any, str]] = []
    import gedit_lsp.features.mouse_hover as mh

    original_build = mh.build_hover_popover

    def fake_build(v: Any, it: Any, txt: str) -> Any:
        built.append((v, it, txt))
        return MagicMock()

    mh.build_hover_popover = fake_build  # type: ignore[assignment]
    try:
        ctrl = MouseHoverController(
            view=view, buffer=buf, server=server, uri=src.as_uri(),
            dwell_ms=10, spinner_threshold_ms=300,
        )

        # Anchor on the `j` in `join` (line 1).
        line_text = src.read_text().splitlines()[1]
        char = line_text.find("join")
        anchor = buf.get_iter_at_line_offset(1, char)

        # Drive a dwell directly with the current token.
        ctrl._on_dwell(ctrl._request_token, anchor)

        # Pump the main loop until the popover gets built or 10s pass.
        def _timeout_quit() -> bool:
            main_loop.quit()
            return False
        GLib.timeout_add_seconds(10, _timeout_quit)

        def _ready() -> bool:
            if built:
                main_loop.quit()
                return False
            return True
        GLib.timeout_add(100, _ready)
        main_loop.run()  # type: ignore[no-untyped-call]

        assert built, "no popover built — server did not respond in time"
        _v, _it, text = built[0]
        assert "join" in text.lower()
        assert ctrl._anchor_range is not None
    finally:
        mh.build_hover_popover = original_build  # type: ignore[assignment]
```

- [ ] **Step 9.2: Run — expect pass (or skip if pylsp not installed)**

```bash
.venv/bin/python -m pytest tests/integration/test_mouse_hover_e2e.py -v
```

Expected: PASS (or `SKIPPED` if the `pylsp_available` fixture decides pylsp isn't installed — match behavior of `test_hover_e2e.py`).

- [ ] **Step 9.3: Run gates**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 9.4: Commit**

```bash
git add tests/integration/test_mouse_hover_e2e.py
git commit -m "test(mouse-hover): e2e against pylsp via direct dwell-fire"
```

---

## Task 10: Docs (doc-gate per memory `project_doc_gate_invariant`)

**Files:**
- Modify: `docs/configure.md`
- Modify: `docs/protocol-coverage.md`
- Modify: `docs/manual-smoke-test.md`

---

- [ ] **Step 10.1: Document the two new tunables in `docs/configure.md`**

Locate the section that lists hover-related tunables (search for `hoverSpinnerThresholdMs`). Add two rows / paragraphs documenting:

```markdown
### `mouseHover` (boolean, default `true`)

Enable pointer-dwell triggering for `textDocument/hover`. When `true`,
hovering the mouse over a token for `mouseHoverDwellMs` milliseconds
shows the same hover popover that Ctrl+K produces. Set to `false` to
disable the feature entirely (no motion-notify handlers attached).

### `mouseHoverDwellMs` (integer, default `300`)

Milliseconds the pointer must dwell over a token before a
`textDocument/hover` request is sent. Increase for slower-feeling
hovers; decrease for snappier (300 ms matches VS Code's default).
Only meaningful when `mouseHover` is `true`.
```

- [ ] **Step 10.2: Update `docs/protocol-coverage.md`**

Locate the existing `textDocument/hover` row. Replace its description so it documents both trigger paths:

```markdown
| `textDocument/hover` (Ctrl+K **and** pointer-dwell over a token) | ✓ |
```

- [ ] **Step 10.3: Append a mouse-hover smoke checklist to `docs/manual-smoke-test.md`**

At the bottom of `docs/manual-smoke-test.md` add:

```markdown
## Mouse-hover (`feat/mouse-hover`)

- [ ] Open a `.py` file; dwell pointer ~300 ms over an identifier → popover appears with the same content Ctrl+K would have shown.
- [ ] Move pointer to whitespace → popover dismisses.
- [ ] Move pointer *into* the popover → popover stays; scroll works if content is long.
- [ ] Press any key → popover dismisses.
- [ ] Click anywhere → popover dismisses.
- [ ] Hover an unused-import line (pyflakes diagnostic) → popover shows hover content; server may include diagnostic-adjacent text.
- [ ] Edit a file with `"mouseHover": false` set → no popover ever appears.
- [ ] Edit a file with `"mouseHoverDwellMs": 1000` → popover delayed ~1 s.
- [ ] Open a second file; close the first while pointer dwells over it → no crash, no stray popover.
- [ ] Start drag-select with the mouse → no popover during the drag.
```

- [ ] **Step 10.4: Run gates (docs don't break tests, but we run them anyway as the doc-gate convention)**

```bash
.venv/bin/python -m pytest tests/ -x
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

- [ ] **Step 10.5: Commit**

```bash
git add docs/configure.md docs/protocol-coverage.md docs/manual-smoke-test.md
git commit -m "docs(mouse-hover): configure, protocol-coverage, manual-smoke entries"
```

---

## After Task 10: open the PR

Per memory `feedback_pr_flow_main_protected` (PR flow required, direct push to main blocked). Per memory `project_ci_only_on_main` (opening the PR is itself a CI validation moment):

```bash
git push -u origin feat/mouse-hover
gh pr create --title "feat(mouse-hover): pointer-dwell triggering for textDocument/hover" --body "$(cat <<'EOF'
## Summary
- Long-lived `MouseHoverController` per `Gedit.Document` (mirrors `SignatureHelpController` lifecycle).
- Watches `motion-notify-event`, debounces dwell with configurable timer, tracks in-flight request token.
- Anchors to server-returned `range`; falls back to word-bounds at the pointer iter.
- Reuses `textDocument/hover` request shape + existing plain-text renderer.
- Two new tunables: `mouseHover` (default `true`), `mouseHoverDwellMs` (default `300`).

## Test plan
- [ ] `.venv/bin/python -m pytest tests/` passes
- [ ] `.venv/bin/python -m ruff check src/ tests/` clean
- [ ] `.venv/bin/python -m mypy src/` clean
- [ ] Manual smoke (see `docs/manual-smoke-test.md` "Mouse-hover" section) — all 10 checks pass in live gedit
- [ ] Disable via `"mouseHover": false` → no popover, no handlers attached
- [ ] Set `"mouseHoverDwellMs": 1000` → popover delayed ~1 s

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After the PR is open, run the full manual-smoke checklist in live gedit (per memory `feedback_manual_smoke_catches_real_bugs` — manual smoke is a real gate, not a formality). Address any defects on the same branch with follow-up commits before merge.
