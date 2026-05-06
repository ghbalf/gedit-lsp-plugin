# Goal C: Completion Details Popover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the highlighted completion proposal's `detail` + `documentation` in a floating `Gtk.Popover` next to the editor, replacing the function gap left by libgedit-gtksourceview's broken `CompletionInfo` Details pane.

**Architecture:** A per-view `CompletionDocsController` hooks `GtkSource.Completion`'s `show` / `hide` / `move-cursor` / `move-page` signals. It tracks the highlighted proposal's index and reads the proposal data from the active `LspCompletionProvider` (which now caches its `do_populate` result). On state changes it shows / updates / hides a single `Gtk.Popover` anchored to the view, positioned at the cursor with `Gtk.PositionType.RIGHT` so it sits beside the completion popup. The popover is non-modal so the completion popup keeps focus.

**Tech Stack:** Python 3.12, PyGObject (Gtk 3, GtkSource 300), pytest, ruff, mypy, gedit 46.

**Phasing:** Single PR. Four phases ordered for incremental review (provider plumbing → pure helpers → popover + controller → docs).

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `src/gedit_lsp/features/completion.py` | modify | `LspCompletionProvider` caches its `last_proposals` and exposes a `set_populate_callback(cb)` hook so the docs controller can react. |
| `src/gedit_lsp/features/completion_docs.py` | create | Pure helpers (index navigation, proposal formatter) + `CompletionDocsController` (per-view orchestrator). Returns a disposer per the listener-disposer pattern (see `96d4f11`). |
| `src/gedit_lsp/plugin.py` | modify | Construct `CompletionDocsController` per attached view (in `_attach_document` after the `CompletionController`). Dispose on tab-removed and on plugin deactivate. |
| `src/gedit_lsp/defaults.py` | modify | Add `showCompletionDocsPopover: bool` (default `True`). |
| `tests/unit/test_completion_docs_navigation.py` | create | Tests for the index-navigation helper (clamp, step kinds, page math). |
| `tests/unit/test_completion_docs_format.py` | create | Tests for the proposal-formatting helper. |
| `tests/unit/test_completion.py` | modify | Add a test that `LspCompletionProvider.set_populate_callback` fires on populate (uses a stub `_send_request`). |
| `docs/configure.md` | modify | Add `showCompletionDocsPopover` row to the tunables table. |
| `docs/example-config.json` | modify | Set `showCompletionDocsPopover: true`. |
| `docs/example-config.md` | modify | One-line walkthrough mention. |
| `CHANGELOG.md` | modify | Unreleased entry. |

---

# Phase 0 — Provider plumbing

## Task 1: Cache `last_proposals` + expose populate callback (TDD)

**Files:**
- Modify: `src/gedit_lsp/features/completion.py`
- Modify or create: `tests/unit/test_completion.py` (a new file is fine if none exists)

- [ ] **Step 1: Write the failing test**

Goal: confirm a callback registered via `set_populate_callback` fires with the right proposal list when `do_populate`'s response handler runs.

Approach: `LspCompletionProvider.do_populate` calls `self._server._send_request(...)` and stores the `on_response` closure; we don't have a real server in unit tests. Instead, drive the closure path by mocking `_send_request`:

```python
from unittest.mock import MagicMock

from gedit_lsp.features.completion import LspCompletionProvider, LspProposal


def test_populate_callback_fires_with_proposals() -> None:
    server = MagicMock()
    server.capability.return_value = {"triggerCharacters": ["."]}

    captured: list[list[LspProposal]] = []

    # We can't call do_populate without a GTK context; assert the wiring
    # via the closure path. Bypass do_populate by invoking the response
    # handler shape directly: build a provider, register a callback,
    # simulate the on_response we'd otherwise be passed.
    provider = LspCompletionProvider.__new__(LspCompletionProvider)
    provider._server = server
    provider._inflight_id = 7
    provider._last_was_incomplete = False
    provider._last_proposals = []
    provider._on_populated = None
    provider.set_populate_callback(captured.append)

    msg = {"result": [{"label": "foo"}, {"label": "bar"}]}
    # Re-create the closure body from do_populate by calling the new
    # public method we'll add: provider._handle_completion_response(msg, my_id=7)
    provider._handle_completion_response(msg, request_id=7)

    assert len(captured) == 1
    assert [p.label for p in captured[0]] == ["foo", "bar"]
    assert [p.label for p in provider._last_proposals] == ["foo", "bar"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_completion.py -v 2>&1 | tail -10`
Expected: FAIL — `set_populate_callback` and `_handle_completion_response` don't exist.

- [ ] **Step 3: Implement the cache + callback + extracted handler**

In `src/gedit_lsp/features/completion.py`:

a. Add to `LspCompletionProvider.__init__`:
```python
from collections.abc import Callable  # add to top imports if missing
# ...
self._last_proposals: list[LspProposal] = []
self._on_populated: Callable[[list[LspProposal]], None] | None = None
```

b. Add the public setter:
```python
def set_populate_callback(
    self, cb: Callable[[list[LspProposal]], None] | None,
) -> None:
    """Register (or unregister with None) a callback fired whenever
    `do_populate` receives a non-error response. Receives the parsed
    proposal list (may be empty)."""
    self._on_populated = cb
```

c. Extract the response-handling body of `do_populate.on_response` into a method:
```python
def _handle_completion_response(
    self, msg: dict[str, Any], request_id: int,
) -> list[LspProposal]:
    """Process a completion response. Returns the parsed proposal list.

    Centralised so unit tests can drive the response path without
    constructing a GTK CompletionContext.
    """
    if self._inflight_id is None or self._inflight_id != request_id:
        return []
    if msg.get("error"):
        logger.info("completion error: %r", msg.get("error"))
        return []
    result = msg.get("result")
    self._last_was_incomplete = response_is_incomplete(result)
    proposals = extract_completion_items(result)
    self._last_proposals = proposals
    if self._on_populated is not None:
        self._on_populated(proposals)
    return proposals
```

d. Update the existing `on_response` closure inside `do_populate` to use it:
```python
def on_response(msg: dict[str, Any]) -> None:
    proposals = self._handle_completion_response(msg, request_id=my_id[0])
    # The error case already returned []; only push to context if no error.
    if msg.get("error"):
        context.add_proposals(self, [], True)  # type: ignore[attr-defined]
        return
    gtk_proposals = [_LspCompletionProposal(p) for p in proposals]
    context.add_proposals(self, gtk_proposals, True)  # type: ignore[attr-defined]
```

(Note: `request_id=my_id[0]` is the same id-match logic the closure had inline; we just thread it through.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && make test 2>&1 | tail -3`
Expected: 165 passed (164 prior + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/gedit_lsp/features/completion.py tests/unit/test_completion.py
git commit -m "feat(completion): cache last_proposals; expose populate callback"
```

---

# Phase 1 — Pure helpers

## Task 2: Index navigation helper (TDD)

**Files:**
- Create: `tests/unit/test_completion_docs_navigation.py`
- Create: `src/gedit_lsp/features/completion_docs.py`

The `move-cursor` signal fires `(completion, scroll_step, num)`. `scroll_step` is a `Gtk.ScrollStep` enum; `num` is signed. We map this plus `move-page` events into index updates, clamped to the proposal-list bounds.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_completion_docs_navigation.py`:

```python
"""Tests for the index-navigation helper used by the completion docs popover."""
from __future__ import annotations

from gedit_lsp.features.completion_docs import (
    NavStep,
    advance_index,
)


def test_advance_index_step_down() -> None:
    assert advance_index(0, NavStep.STEP, 1, list_len=5, page_size=3) == 1
    assert advance_index(2, NavStep.STEP, 2, list_len=5, page_size=3) == 4


def test_advance_index_step_up() -> None:
    assert advance_index(2, NavStep.STEP, -1, list_len=5, page_size=3) == 1
    assert advance_index(0, NavStep.STEP, -1, list_len=5, page_size=3) == 0  # clamp


def test_advance_index_clamps_at_top_and_bottom() -> None:
    assert advance_index(4, NavStep.STEP, 5, list_len=5, page_size=3) == 4  # clamp
    assert advance_index(0, NavStep.STEP, -10, list_len=5, page_size=3) == 0


def test_advance_index_page_uses_page_size() -> None:
    assert advance_index(0, NavStep.PAGE, 1, list_len=20, page_size=5) == 5
    assert advance_index(15, NavStep.PAGE, -2, list_len=20, page_size=5) == 5


def test_advance_index_empty_list_returns_minus_one() -> None:
    assert advance_index(0, NavStep.STEP, 1, list_len=0, page_size=3) == -1


def test_advance_index_ends_jumps_to_extremes() -> None:
    assert advance_index(2, NavStep.ENDS, 1, list_len=5, page_size=3) == 4
    assert advance_index(2, NavStep.ENDS, -1, list_len=5, page_size=3) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_completion_docs_navigation.py -v 2>&1 | tail -5`
Expected: ImportError (module doesn't exist).

- [ ] **Step 3: Implement `advance_index`**

Create `src/gedit_lsp/features/completion_docs.py`:

```python
"""Completion docs popover — pure helpers + GTK-bound controller.

Pure helpers (unit-testable, no GTK dependency) live at module level. The
GTK class (`CompletionDocsController`) is added in a later task.
"""
from __future__ import annotations

import enum


class NavStep(enum.Enum):
    """Subset of Gtk.ScrollStep we care about for completion navigation."""
    STEP = "step"   # one row at a time (Up/Down)
    PAGE = "page"   # one page at a time (PageUp/PageDown)
    ENDS = "ends"   # jump to top/bottom (Home/End equivalent)


def advance_index(
    current: int,
    step: NavStep,
    num: int,
    *,
    list_len: int,
    page_size: int,
) -> int:
    """Compute the new highlight index after a navigation event.

    `num` is signed: negative = up/back, positive = down/forward.
    Returns -1 when the list is empty. Otherwise clamps to [0, list_len-1].
    """
    if list_len <= 0:
        return -1
    if step is NavStep.ENDS:
        return list_len - 1 if num > 0 else 0
    delta = num * (page_size if step is NavStep.PAGE else 1)
    new_index = current + delta
    if new_index < 0:
        return 0
    if new_index >= list_len:
        return list_len - 1
    return new_index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_completion_docs_navigation.py -v 2>&1 | tail -10`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/gedit_lsp/features/completion_docs.py tests/unit/test_completion_docs_navigation.py
git commit -m "feat(completion-docs): index navigation helper"
```

---

## Task 3: Proposal formatter (TDD)

**Files:**
- Create: `tests/unit/test_completion_docs_format.py`
- Modify: `src/gedit_lsp/features/completion_docs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_completion_docs_format.py`:

```python
"""Tests for the proposal-text formatter used by the completion docs popover."""
from __future__ import annotations

from gedit_lsp.features.completion import LspProposal
from gedit_lsp.features.completion_docs import format_proposal_text


def _make(label: str, *, detail: str | None = None, doc: str = "") -> LspProposal:
    return LspProposal(
        label=label, insert_text=label, detail=detail, kind=None,
        documentation=doc, sort_text=label, filter_text=label, raw_item={},
    )


def test_format_with_detail_and_doc() -> None:
    p = _make("foo", detail="(method) foo() -> int", doc="Foo the bar.")
    assert format_proposal_text(p) == "(method) foo() -> int\n\nFoo the bar."


def test_format_doc_only() -> None:
    p = _make("foo", doc="Just docs.")
    assert format_proposal_text(p) == "Just docs."


def test_format_detail_only() -> None:
    p = _make("foo", detail="(class)")
    assert format_proposal_text(p) == "(class)"


def test_format_empty_returns_blank_placeholder() -> None:
    p = _make("foo")
    # A single space rather than "" so the popover doesn't collapse to
    # zero height (matches the v0.2.0 attempt's approach).
    assert format_proposal_text(p) == " "
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_completion_docs_format.py -v 2>&1 | tail -5`
Expected: ImportError.

- [ ] **Step 3: Implement `format_proposal_text`**

Append to `src/gedit_lsp/features/completion_docs.py`:

```python
from gedit_lsp.features.completion import LspProposal  # noqa: E402  (after enum)


def format_proposal_text(proposal: LspProposal) -> str:
    """Format detail + documentation for the docs popover.

    Detail (e.g. function signature) on the first line, documentation
    below. Markdown is stringified upstream — no rich rendering for v1.
    Returns " " (single space) when both fields are empty so the popover
    doesn't collapse to a zero-height row.
    """
    parts: list[str] = []
    if proposal.detail:
        parts.append(proposal.detail)
    if proposal.documentation:
        parts.append(proposal.documentation)
    return "\n\n".join(parts) or " "
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_completion_docs_format.py -v 2>&1 | tail -5`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/gedit_lsp/features/completion_docs.py tests/unit/test_completion_docs_format.py
git commit -m "feat(completion-docs): proposal text formatter"
```

---

# Phase 2 — Popover + controller

## Task 4: `CompletionDocsController` class (manual smoke verifies)

**Files:**
- Modify: `src/gedit_lsp/features/completion_docs.py`

This task wires the GTK side. The pure helpers from Tasks 2-3 are imported. No new unit tests — the class touches GTK objects (Popover, View, Completion) and is best validated with manual smoke. The implementer should self-review carefully.

- [ ] **Step 1: Append the GTK-bound controller**

Append to `src/gedit_lsp/features/completion_docs.py` (after the pure helpers):

```python
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "300")
from gi.repository import Gtk, GtkSource  # noqa: E402

if TYPE_CHECKING:
    from gedit_lsp.features.completion import LspCompletionProvider

logger = logging.getLogger("gedit_lsp.completion_docs")


class CompletionDocsController:
    """Per-view controller showing a docs popover for the highlighted proposal.

    Lifecycle: constructed when `_attach_document` runs (after the existing
    `CompletionController`); `dispose()` called from `plugin.py` on
    tab-removed or `do_deactivate`. Returns its disposer so the plugin
    can store it alongside the existing listener-disposer set.
    """

    def __init__(
        self,
        *,
        view: Gtk.TextView,
        provider: LspCompletionProvider,
    ) -> None:
        self._view = view
        self._provider = provider
        self._proposals: list[LspProposal] = []
        self._index = 0
        self._popover: Gtk.Popover | None = None
        self._label: Gtk.Label | None = None
        self._handler_ids: list[int] = []
        self._completion = view.get_completion()  # type: ignore[attr-defined]
        # Hook the completion popup signals.
        if self._completion is not None:
            for sig, cb in (
                ("show",          self._on_show),
                ("hide",          self._on_hide),
                ("move-cursor",   self._on_move_cursor),
                ("move-page",     self._on_move_page),
            ):
                hid = self._completion.connect(sig, cb)
                self._handler_ids.append(hid)
        # Subscribe to populate events on our provider.
        self._provider.set_populate_callback(self._on_populated)

    def dispose(self) -> None:
        if self._completion is not None:
            for hid in self._handler_ids:
                with contextlib.suppress(Exception):
                    self._completion.disconnect(hid)
        self._handler_ids.clear()
        self._provider.set_populate_callback(None)
        if self._popover is not None:
            with contextlib.suppress(Exception):
                self._popover.popdown()
        self._popover = None
        self._label = None

    # --- callbacks ---

    def _on_populated(self, proposals: list[LspProposal]) -> None:
        self._proposals = proposals
        self._index = 0
        self._refresh()

    def _on_show(self, _completion: GtkSource.Completion) -> None:
        # The popup just opened. If our provider's proposals are stale
        # (e.g. another provider populated last), don't show — wait for
        # the next _on_populated.
        if self._proposals:
            self._refresh(show=True)

    def _on_hide(self, _completion: GtkSource.Completion) -> None:
        if self._popover is not None:
            with contextlib.suppress(Exception):
                self._popover.popdown()

    def _on_move_cursor(
        self,
        _completion: GtkSource.Completion,
        scroll_step: Gtk.ScrollStep,
        num: int,
    ) -> None:
        step = _scroll_step_to_navstep(scroll_step)
        if step is None:
            return  # unsupported step — ignore
        page_size = self._page_size()
        self._index = advance_index(
            self._index, step, num,
            list_len=len(self._proposals), page_size=page_size,
        )
        self._refresh()

    def _on_move_page(
        self,
        _completion: GtkSource.Completion,
        scroll_step: Gtk.ScrollStep,
        num: int,
    ) -> None:
        # libgedit also fires move-page for PageUp/PageDown; treat as PAGE
        # regardless of the scroll_step value.
        page_size = self._page_size()
        self._index = advance_index(
            self._index, NavStep.PAGE, num,
            list_len=len(self._proposals), page_size=page_size,
        )
        self._refresh()

    # --- helpers ---

    def _page_size(self) -> int:
        # The completion popup's proposal-page-size property (default 5
        # in libgedit) tells us how many rows fit in a "page".
        if self._completion is None:
            return 5
        try:
            return int(self._completion.get_property("proposal-page-size"))
        except (TypeError, ValueError):
            return 5

    def _refresh(self, *, show: bool = False) -> None:
        if not self._proposals or self._index < 0:
            return
        text = format_proposal_text(self._proposals[self._index])
        label = self._ensure_label()
        label.set_text(text)
        if show or (self._popover is not None and self._popover.get_visible()):
            self._show_popover()

    def _ensure_label(self) -> Gtk.Label:
        if self._label is None:
            label = Gtk.Label.new("")
            label.set_xalign(0)
            label.set_line_wrap(True)  # type: ignore[attr-defined]
            label.set_selectable(True)
            label.set_max_width_chars(60)
            self._label = label
        return self._label

    def _ensure_popover(self) -> Gtk.Popover:
        if self._popover is None:
            popover = Gtk.Popover.new(self._view)  # type: ignore[call-arg]
            popover.set_modal(False)  # don't steal focus from completion popup
            popover.set_position(Gtk.PositionType.RIGHT)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_min_content_height(120)
            scrolled.set_min_content_width(360)
            scrolled.set_max_content_height(360)
            scrolled.add(self._ensure_label())  # type: ignore[attr-defined]
            popover.add(scrolled)  # type: ignore[attr-defined]
            popover.show_all()  # type: ignore[attr-defined]
            self._popover = popover
        return self._popover

    def _show_popover(self) -> None:
        # Anchor at the cursor's screen rect so the popover sits beside
        # the completion popup (which is anchored similarly, just below).
        buf = self._view.get_buffer()
        cursor_iter = buf.get_iter_at_mark(buf.get_insert())
        rect = self._view.get_iter_location(cursor_iter)
        bx, by = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y + rect.height,
        )
        rect.x = bx
        rect.y = by
        rect.width = 1
        rect.height = 1
        popover = self._ensure_popover()
        popover.set_pointing_to(rect)
        popover.popup()  # non-modal show


def _scroll_step_to_navstep(s: Gtk.ScrollStep) -> NavStep | None:
    # Gtk.ScrollStep values that GtkSourceCompletion actually emits:
    # STEPS (single row), PAGES (page), ENDS (top/bottom).
    if s == Gtk.ScrollStep.STEPS:
        return NavStep.STEP
    if s == Gtk.ScrollStep.PAGES:
        return NavStep.PAGE
    if s == Gtk.ScrollStep.ENDS:
        return NavStep.ENDS
    return None
```

Add this import near the top of the same file (above the `import gi` block):

```python
import contextlib
```

And add the `LspProposal` import to the TYPE_CHECKING-or-runtime block as needed (the formatter already imports it, so verify no double-import).

- [ ] **Step 2: Run lint + typecheck + test**

Run: `source .venv/bin/activate && make lint && make typecheck && make test 2>&1 | tail -3`
Expected: clean; no new tests; existing 165 still pass.

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/features/completion_docs.py
git commit -m "feat(completion-docs): per-view popover controller"
```

---

## Task 5: Wire the controller from `plugin.py`

**Files:**
- Modify: `src/gedit_lsp/plugin.py`

- [ ] **Step 1: Add the import + per-doc storage**

Near the existing `from gedit_lsp.features.completion import CompletionController`:

```python
from gedit_lsp.features.completion_docs import CompletionDocsController
```

In `do_activate`, alongside `self._completion_ctrls`:

```python
self._docs_ctrls: dict[Gedit.Document, CompletionDocsController] = {}
```

- [ ] **Step 2: Construct the controller in `_attach_document`**

After the existing `CompletionController` creation block (find the line `self._completion_ctrls[doc] = CompletionController(...)`), add a sibling block:

```python
if self._config.tunable("showCompletionDocsPopover"):
    completion_ctrl = self._completion_ctrls.get(doc)
    view = next(
        (v for v in self.window.get_views() if v.get_buffer() is doc),
        None,
    )
    if completion_ctrl is not None and view is not None:
        self._docs_ctrls[doc] = CompletionDocsController(
            view=view, provider=completion_ctrl._provider,
        )
```

(Yes, accessing `_provider` — the `CompletionController` doesn't expose the provider publicly. Add a property `provider` on `CompletionController` first if you prefer; the simpler route is to expose it.)

Add to `CompletionController` (in `completion.py`):

```python
@property
def provider(self) -> "LspCompletionProvider":
    return self._provider
```

Then the wiring becomes `provider=completion_ctrl.provider`.

- [ ] **Step 3: Dispose in `_on_tab_removed`**

In `_on_tab_removed` near the existing `ctrl = self._completion_ctrls.pop(doc, None)` block:

```python
docs_ctrl = self._docs_ctrls.pop(doc, None)
if docs_ctrl is not None:
    docs_ctrl.dispose()
```

- [ ] **Step 4: Dispose in `do_deactivate`**

In `do_deactivate`, alongside the existing `for ctrl in self._completion_ctrls.values():` loop:

```python
for ctrl in self._docs_ctrls.values():
    ctrl.dispose()
self._docs_ctrls.clear()
```

- [ ] **Step 5: Run lint + typecheck + test**

Run: `source .venv/bin/activate && make lint && make typecheck && make test 2>&1 | tail -3`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/gedit_lsp/features/completion.py src/gedit_lsp/plugin.py
git commit -m "feat(completion-docs): wire per-view popover from plugin lifecycle"
```

---

# Phase 3 — Tunable + docs

## Task 6: Add `showCompletionDocsPopover` to defaults

**Files:**
- Modify: `src/gedit_lsp/defaults.py`

- [ ] **Step 1: Add the default**

Find the `DEFAULT_TUNABLES` dict and add (alphabetically near `showStatusbarIndicator`):

```python
"showCompletionDocsPopover": True,
```

- [ ] **Step 2: Run tests**

Run: `source .venv/bin/activate && make test 2>&1 | tail -3`
Expected: clean (no test should regress).

- [ ] **Step 3: Commit**

```bash
git add src/gedit_lsp/defaults.py
git commit -m "feat(completion-docs): add showCompletionDocsPopover default"
```

---

## Task 7: Update docs (`configure.md`, `example-config.json`, `example-config.md`)

**Files:**
- Modify: `docs/configure.md`
- Modify: `docs/example-config.json`
- Modify: `docs/example-config.md`

- [ ] **Step 1: `docs/configure.md`**

Add a row in the tunables table near `showStatusbarIndicator`:

```markdown
| `showCompletionDocsPopover` | bool | `true` | Show a side popover with detail+documentation for the highlighted completion proposal |
```

- [ ] **Step 2: `docs/example-config.json`**

Add the line in the `tunables` block (near `showStatusbarIndicator`):

```json
"showCompletionDocsPopover":  true,
```

- [ ] **Step 3: `docs/example-config.md`**

In the `### Buffer / UI guards` block (or `### Features` — whichever sits closer to the existing docs), add:

```markdown
`showCompletionDocsPopover` toggles the side-popover that mirrors the
highlighted completion proposal's `detail` + `documentation`. Workaround
for libgedit's broken built-in Details pane.
```

- [ ] **Step 4: Sanity-verify the example config still parses**

Run:
```bash
source .venv/bin/activate
PYTHONPATH=src python -c "
import json
from pathlib import Path
from gedit_lsp.config import Config
from gedit_lsp.defaults import DEFAULT_TUNABLES
data = json.loads(Path('docs/example-config.json').read_text())
cfg = Config(Path('docs/example-config.json')); cfg.load()
missing = [k for k in DEFAULT_TUNABLES if k not in data['tunables']]
assert not missing, missing
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/configure.md docs/example-config.json docs/example-config.md
git commit -m "docs: document showCompletionDocsPopover tunable"
```

---

## Task 8: CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add an Unreleased entry**

Under `## [Unreleased]` → `### Added`:

```markdown
- LSP completion docs popover. While the completion popup is open, a
  non-modal `Gtk.Popover` next to the editor displays the highlighted
  proposal's `detail` + `documentation` (parsed from the initial
  `textDocument/completion` response). Replaces the libgedit Details
  pane, which our completion provider can't populate. Toggle with the
  new `showCompletionDocsPopover` tunable. `completionItem/resolve`
  enrichment is a separate follow-up.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for completion docs popover"
```

---

# Phase 4 — PR + manual smoke

## Task 9: Push, open PR, manual smoke, merge

- [ ] **Step 1: Push**

```bash
git push -u origin feat/completion-docs
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(completion-docs): popover for highlighted proposal" --body "$(cat <<'EOF'
## Summary

Goal C from the v0.2.0 wrap-up: replace the broken libgedit Details pane with our own `Gtk.Popover` that mirrors the highlighted completion proposal's detail + documentation.

- Per-view `CompletionDocsController` hooks `GtkSource.Completion` signals (\`show\` / \`hide\` / \`move-cursor\` / \`move-page\`) and tracks the highlighted index.
- `LspCompletionProvider` now caches its last proposal list and exposes a populate-callback so the docs controller can read proposal data.
- New tunable \`showCompletionDocsPopover\` (default \`true\`).
- v1 scope: shows whatever's in the initial \`textDocument/completion\` response. \`completionItem/resolve\` enrichment is a follow-up.

## Test plan

- [x] \`make lint\` clean
- [x] \`make typecheck\` clean
- [x] \`make test\` (165 → 175 expected: +6 navigation + +4 format + +1 callback wiring)
- [x] Example config parses
- [ ] Manual: open a Python file with pylsp running. Type \`os.\` — popup shows. Popover appears next to it with detail/documentation for the first proposal.
- [ ] Manual: arrow Up/Down — popover updates with each new highlighted proposal.
- [ ] Manual: PageDown — popover updates by page-size jumps.
- [ ] Manual: Escape — popup hides; popover hides.
- [ ] Manual: open a Markdown file (no completionProvider) — no popup, no popover, no errors.
- [ ] Manual: set \`"showCompletionDocsPopover": false\` in config — restart gedit — popover never shows.
EOF
)"
```

- [ ] **Step 3: Wait for CI green**

```bash
gh pr view --json statusCheckRollup --jq '.statusCheckRollup[] | "\(.name): \(.conclusion // .status)"'
```

- [ ] **Step 4: Manual smoke (the test plan items)**

`./install.sh` from this checkout, restart gedit, walk through each manual step in the PR body. Update the checkboxes on the PR. If a step fails, fix and re-push.

- [ ] **Step 5: Merge**

```bash
gh pr merge --merge --delete-branch
git checkout main && git pull --ff-only
```

---

## Self-review

After writing the plan, verify:

1. **Spec coverage:** every requirement in the goal-C memory note (`project_goal_c_completion_details_popover.md`) has a task.
   - "Bottom panel"? Goal swapped to popover (user pick).
   - "Index navigation"? Task 2.
   - "Proposal formatter"? Task 3.
   - "Selection-change detection via signals"? Task 4 (`_on_show`/`_on_move_cursor`/`_on_move_page`).
   - "Disposer pattern"? Task 4 (`dispose()` method).
   - "Tunable to disable"? Task 6.
   - "Docs"? Task 7.
   - "CHANGELOG"? Task 8.
   - resolve enrichment is explicitly out of scope for v1 — noted in the CHANGELOG entry and PR body.
2. **Placeholder scan:** no "TBD"/"TODO" markers; every code block has full content.
3. **Type consistency:** `LspProposal`, `NavStep`, `advance_index`, `format_proposal_text`, `CompletionDocsController` referenced consistently across tasks.
