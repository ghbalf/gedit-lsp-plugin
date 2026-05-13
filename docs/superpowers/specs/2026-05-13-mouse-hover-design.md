# `textDocument/hover` via pointer dwell ("mouse-hover") — Design

**Status:** approved (pending user spec review)
**Target release:** v0.4.0 (bundled)
**Issue/PR:** TBD (feature branch `feat/mouse-hover`)
**Author:** Alfred Mickautsch (with Claude)
**Date:** 2026-05-13

## Goal

Extend the existing keyboard-triggered hover (Ctrl+K) so that dwelling
the mouse pointer over a token also surfaces the server's
`textDocument/hover` response. The request/response/render pipeline is
already in place; this design adds the *trigger* layer — a per-view
controller that watches `motion-notify-event`, debounces dwell with a
configurable timer, tracks an in-flight request token, and reuses the
existing popover renderer.

## Non-goals

- **Replacing keyboard hover.** Ctrl+K stays as-is. Mouse-hover is
  additive.
- **Markdown rendering.** Still plain-text. The existing
  `render_hover_contents` helper handles `MarkupContent`,
  `MarkedString`, lists, and strings — we reuse it verbatim.
- **Probe-driven dwell across whitespace.** Hover only fires when
  `view.get_iter_at_location` reports `over_text=True`. No requests
  for blank space, end-of-line virtual area, or below-last-line.
- **Hover-while-selecting / hover-while-dragging.** A held mouse
  button suppresses hover (mouse motion during a drag is not dwell).
  Implemented implicitly: `button-press-event` dismisses any open
  popover and clears state until `button-release-event`.
- **Sticky popover.** Auto-dismisses on pointer leaving the anchored
  range, on any key, on any click. Stays only while the pointer is
  inside the popover itself (grace window of ~150 ms during transit).
- **Diagnostic-message-only mode.** When the pointer is over a
  diagnostic-underlined range, we still request `textDocument/hover`
  exactly as for any other range and trust the server to merge useful
  info. We do not splice in messages from `_diag_panel` — that would
  couple mouse-hover to diagnostics internals and risks duplication
  with servers that already mention the diagnostic.
- **Per-server enable/disable.** A single global boolean tunable is
  enough for v1. Per-server config can be added later if a real need
  surfaces.

## User-visible behavior

- Dwell pointer over a token for `mouseHoverDwellMs` milliseconds
  (default 300) → popover appears anchored to the token (or to the
  server-returned `range` if richer), containing the same content
  Ctrl+K would have shown at the same position.
- Move pointer to whitespace or to a different token → popover
  dismisses (or re-fires for the new token after another dwell).
- Move pointer *into* the popover itself → popover stays. Useful for
  long contents where the user wants to scroll. (150 ms transit
  grace tolerates the pointer briefly leaving the view before
  reaching the popover.)
- Press any key, click anywhere, focus leaves the view → popover
  dismisses immediately.
- Set `"mouseHover": false` in config → feature off (no event
  handlers attached at all).
- Adjust `"mouseHoverDwellMs"` → dwell threshold changes accordingly.

## Architecture

### New module: `src/gedit_lsp/features/mouse_hover.py`

Exports `MouseHoverController`, a long-lived per-`Gedit.Document`
object instantiated in `plugin._attach_document` and disposed in
`plugin._on_tab_removed` and `plugin.do_deactivate`. Mirrors the
lifecycle and registry shape of `SignatureHelpController`.

State:

| Field                  | Type                                   | Purpose                                                                                                                                        |
| ---                    | ---                                    | ---                                                                                                                                            |
| `_timer_id`            | `int \| None`                          | Pending `GLib.timeout_add` source ID for dwell debounce.                                                                                       |
| `_request_token`       | `int`                                  | Monotonic counter; incremented on every cancel/dismiss/dispose. Closures capture the current value and drop responses where token has moved on. |
| `_popover`             | `Gtk.Popover \| None`                  | The currently-shown popover (one at a time).                                                                                                   |
| `_anchor_range`        | `tuple[TextIter, TextIter] \| None`    | Buffer range the popover is anchored to. Pointer staying inside the range suppresses re-fire; pointer leaving it triggers dismiss.             |
| `_pointer_in_popover`  | `bool`                                 | Pointer-tracking flag set/cleared by popover-side `enter-notify` / `leave-notify` handlers; gates the ~150 ms transit grace.                   |
| `_grace_timer_id`      | `int \| None`                          | Pending grace-period timer used to defer dismissal while pointer is crossing between view and popover.                                         |
| `_signal_handlers`     | `list[tuple[GObject, int]]`            | All signal handlers attached during construction, for clean disconnect in `dispose()`.                                                         |

### Shared helper extracted from `features/hover.py`

A module-level function

```python
def build_hover_popover(view: Gtk.TextView, anchor_iter: Gtk.TextIter,
                        text: str) -> Gtk.Popover
```

is moved out of `HoverController._show_popover`. Both the existing
keyboard `HoverController` and the new `MouseHoverController` call
it. No behavior change for Ctrl+K — only deduplication so future
popover-styling changes don't drift between the two trigger paths.

### Plugin wiring (`plugin.py`)

```python
# Constructor — new registry alongside the existing four:
self._mouse_hover_ctrls: dict[Gedit.Document, MouseHoverController] = {}

# In _attach_document, after `server` is up and capabilities are known:
if (self._config.tunable("mouseHover")
        and server.capabilities.get("hoverProvider")):
    view = next(v for v in self.window.get_views()
                  if v.get_buffer() is doc)
    ctrl = MouseHoverController(
        view=view, buffer=doc, server=server, uri=bridge.uri,
        dwell_ms=self._config.tunable("mouseHoverDwellMs"),
        spinner_threshold_ms=self._config.tunable(
            "hoverSpinnerThresholdMs"),
    )
    self._mouse_hover_ctrls[doc] = ctrl

# In _on_tab_removed:
ctrl = self._mouse_hover_ctrls.pop(doc, None)
if ctrl is not None:
    ctrl.dispose()

# In do_deactivate (matches the pattern for _sighelp_ctrls etc.):
for ctrl in self._mouse_hover_ctrls.values():
    ctrl.dispose()
self._mouse_hover_ctrls.clear()
```

### New tunables (`defaults.py`)

```python
"mouseHover":         True,
"mouseHoverDwellMs":  300,
```

Documented in `docs/configure.md` under the existing hover section.
No change to `hoverSpinnerThresholdMs` (reused for both paths).

## Data flow

### Motion → schedule

```
motion-notify-event(event):
    if event.state & button-pressed: return    # dragging, not dwelling
    cancel _timer_id; _timer_id = None
    _request_token += 1                        # invalidate any in-flight
    bx, by = view.window_to_buffer_coords(WIDGET, event.x, event.y)
    over_text, buffer_iter = view.get_iter_at_location(bx, by)

    if not over_text:
        if _popover and pointer outside _anchor_range and not _pointer_in_popover:
            _grace_timer_id = GLib.timeout_add(150, _dismiss_if_still_outside)
        return

    if _popover and buffer_iter inside _anchor_range:
        return                                  # stable; no re-fire

    captured = _request_token
    _timer_id = GLib.timeout_add(
        dwell_ms, _on_dwell, captured, buffer_iter)
```

### Dwell → request

```
_on_dwell(captured_token, buffer_iter):
    if captured_token != _request_token: return False
    _timer_id = None
    line, char = text_iter_to_utf16(buffer_iter)
    server._send_request("textDocument/hover",
        {"textDocument": {"uri": _uri},
         "position": {"line": line, "character": char}},
        lambda msg: _on_response(captured_token, buffer_iter, msg))
    return False                                # one-shot
```

### Response → popover

```
_on_response(captured_token, anchor_iter, msg):
    if captured_token != _request_token: return        # stale
    if msg.get("error") or msg.get("result") is None:
        return
    text = render_hover_contents(msg["result"].get("contents"))
    if not text.strip(): return

    server_range = msg["result"].get("range")
    if server_range:
        start_iter, end_iter = _iters_from_lsp_range(_buffer, server_range)
    else:
        start_iter, end_iter = _word_bounds_at(anchor_iter)

    _anchor_range = (start_iter, end_iter)
    _popover = build_hover_popover(_view, start_iter, text)
    _attach_popover_pointer_tracking(_popover)
    _popover.popup()
```

### Dismissal events

All of these clear `_popover`, increment `_request_token`, remove
`_timer_id`, and `popdown()` the popover:

- `leave-notify-event` on the view (with grace timer if pointer might
  be transiting into the popover)
- `focus-out-event` on the view
- `key-press-event` on the view (any key)
- `button-press-event` on the view (any click)
- Popover's own `closed` signal (e.g. clicked outside in modal-off mode)

### Helpers

- `_iters_from_lsp_range(buffer, lsp_range)` — UTF-16 → `(start, end)`
  `Gtk.TextIter` pair. Thin wrapper over the existing `utf16` helpers;
  unit-testable.
- `_word_bounds_at(iter)` — uses `iter.starts_word()` /
  `iter.ends_word()` / `forward_word_end` / `backward_word_start`,
  returns the surrounding word range. Falls back to a one-character
  range if the iter isn't on a word character.

## Error handling

| Condition                                  | Behavior                                                                              |
| ---                                        | ---                                                                                   |
| `msg["error"]` set                         | Log at `INFO`; return without popover (parity with keyboard hover).                   |
| `msg["result"] is None`                    | No-op.                                                                                |
| Empty `contents` after rendering           | No-op.                                                                                |
| Server state ≠ `Running`                   | `server._send_request` no-ops; token cycles on next motion. No special-case.          |
| `view.get_iter_at_location` `over_text=False` | Treated as "off any token" — see flow above.                                          |
| View destroyed mid-request                 | Token guard catches stale response; `dispose()` removes signal handlers.              |
| Dynamic capability re-registration         | Worst case = wasted requests rejected by the server; `on_response` already handles it. |

No new logging channel. `logger = logging.getLogger("gedit_lsp.mouse_hover")` at `INFO` for state-transition events; per-motion traces gated behind `logger.debug`.

## Disposal

`MouseHoverController.dispose()` is idempotent and tears down in this order:

1. `if _timer_id: GLib.source_remove(_timer_id); _timer_id = None`
2. `if _grace_timer_id: GLib.source_remove(_grace_timer_id); _grace_timer_id = None`
3. `_request_token += 1` (drops any in-flight reply when it arrives)
4. For each `(obj, handler_id)` in `_signal_handlers`:
   `obj.disconnect(handler_id)` inside
   `contextlib.suppress(TypeError, RuntimeError)` — project convention.
5. If `_popover is not None`: `_popover.popdown(); _popover = None`
6. `_anchor_range = None`; `_pointer_in_popover = False`

Called from `_on_tab_removed` and from `do_deactivate`.

## Testing strategy

### Unit tests — `tests/unit/test_mouse_hover.py`

Per `project_unit_tests_avoid_gtk_widgets`: `MagicMock()` for the
view, real `GtkSource.Buffer` for the buffer.

| # | Invariant                                                                  | Mutation pin                                                            |
| - | ---                                                                        | ---                                                                     |
| 1 | Motion schedules a timer; second motion cancels the first.                 | Break `source_remove` in motion handler → expect two outstanding IDs.   |
| 2 | Pointer inside `_anchor_range` after popover shown does NOT re-fire.       | Break the `iter inside _anchor_range` guard → expect second request.    |
| 3 | `_request_token` mismatch drops a late response (no popover built).        | Break the token check in `_on_response` → expect builder called.        |
| 4 | `dispose()` removes timer, disconnects signals, increments token.          | Break `source_remove` in dispose → expect timer still scheduled.        |
| 5 | Missing `hoverProvider` capability → controller never constructed.         | Inline assert at call site; covered in plugin-wiring test.              |
| 6 | `over_text=False` motion does NOT schedule a timer.                        | Break the early return → expect timer scheduled.                        |
| 7 | Empty `contents` after rendering does NOT show popover.                    | Break the empty-string guard → expect builder called.                   |
| 8 | Button held during motion (drag) suppresses scheduling.                    | Break the button-state check → expect timer scheduled during drag.      |

### Pure-function tests

- `_iters_from_lsp_range` — exercise with the existing `utf16` test
  fixtures; verify start/end iters match expected offsets including
  multi-byte UTF-8 cases.
- `_word_bounds_at` — verify boundary handling at start/end of buffer,
  on whitespace, on punctuation, mid-word.

### Integration test — `tests/integration/test_mouse_hover_e2e.py`

Pylsp-backed `.py` fixture. Programmatically emit
`motion-notify-event` at known coordinates corresponding to an
identifier. Wait for dwell + response. Assert:

- A `textDocument/hover` request appears on the wire at the expected
  `position`.
- `_popover` becomes non-`None` and `_anchor_range` matches the
  identifier's range.

Reference test style: `tests/integration/test_completion_flush.py`.

### Manual smoke (`docs/manual-smoke-test.md`)

Per `feedback_manual_smoke_catches_real_bugs` — manual smoke is a
real gate. Append:

- [ ] Open a `.py` file; dwell pointer ~300 ms over an identifier →
  popover appears with the same content Ctrl+K would have shown.
- [ ] Move pointer to whitespace → popover dismisses.
- [ ] Move pointer *into* the popover → popover stays; scroll works
  if content is long.
- [ ] Press any key → popover dismisses.
- [ ] Click anywhere → popover dismisses.
- [ ] Hover an unused-import line (pyflakes diagnostic) → popover
  shows hover content; server may include diagnostic-adjacent text.
- [ ] Edit a file with `"mouseHover": false` set → no popover ever
  appears.
- [ ] Edit a file with `"mouseHoverDwellMs": 1000` → popover delayed
  ~1 s.
- [ ] Open a second file; close the first while pointer dwells over
  it → no crash, no stray popover.
- [ ] Start drag-select with the mouse → no popover during the drag.

## Quality gates per task

Per `feedback_per_task_lint_typecheck_gates`, every task in the
implementation plan runs **all three** of:

```
.venv/bin/python -m pytest tests/        # full tree, not just unit
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

before being marked complete. Pre-push runs the full `tests/`
tree, per `feedback_run_full_test_tree_pre_push`.

## File-touch summary

| File                                                  | Change                                                              |
| ---                                                   | ---                                                                 |
| `src/gedit_lsp/features/mouse_hover.py`               | New — `MouseHoverController`, signal wiring, dwell logic.           |
| `src/gedit_lsp/features/hover.py`                     | Extract `build_hover_popover` to module level; call from controller. |
| `src/gedit_lsp/plugin.py`                             | Add `_mouse_hover_ctrls` registry; construct in `_attach_document`; dispose in `_on_tab_removed` and `do_deactivate`. |
| `src/gedit_lsp/defaults.py`                           | Add `mouseHover` and `mouseHoverDwellMs` tunables.                  |
| `docs/configure.md`                                   | Document the two new tunables under the hover section.              |
| `docs/protocol-coverage.md`                           | Note pointer-dwell trigger on the existing `textDocument/hover` row. |
| `docs/manual-smoke-test.md`                           | Append the smoke checklist above.                                   |
| `tests/unit/test_mouse_hover.py`                      | New — invariant tests with mutation pins.                           |
| `tests/integration/test_mouse_hover_e2e.py`           | New — pylsp-backed e2e test.                                        |

## Open questions

None at spec-approval time. If implementation surfaces real edge
cases (e.g. popover focus-stealing on Wayland, motion events firing
during programmatic scroll), they get folded back into this spec
before merge.
