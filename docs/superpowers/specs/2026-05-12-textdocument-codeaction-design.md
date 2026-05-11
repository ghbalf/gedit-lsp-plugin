# `textDocument/codeAction` (+ `codeAction/resolve`, `workspace/executeCommand`) — Design

**Status:** approved (pending user spec review)
**Target release:** v0.4.0 (bundled)
**Issue/PR:** TBD (feature branch `feat/code-action`)
**Author:** Alfred Mickautsch (with Claude)
**Date:** 2026-05-12

## Goal

Add `textDocument/codeAction` to the gedit LSP plugin. Surface
server-provided "what can I do here?" actions — quick-fixes, refactors,
source-level operations like "organize imports" — at the cursor position.
A diagnostic-driven lightbulb in the source gutter signals lines with
likely actions; a popover lets the user pick one and commits it via the
LSP-spec apply path (`edit` and/or `command`).

## Non-goals

- **Probe-driven lightbulb.** A model where every cursor settle fires a
  background `codeAction` request to decide whether to show the bulb.
  Rejected for cost: every cursor move = one LSP round-trip; needs
  debounce + cancellation + idle handling. The diagnostic-driven model
  covers ~95% of practical use (quickfix-for-diag) and pure refactors
  remain reachable via the keybinding.
- **Action caching by line.** "Already fetched actions for line N,
  reuse on next click" — invalidation rules are subtle (diagnostics
  change, edits change, scope changes) and a single round-trip is cheap.
- **Auto-apply when N=1.** Other editors split here; we always show the
  popover. The user clicked an "action available" affordance — letting
  them confirm *what* they're applying is worth one extra keystroke,
  particularly when the action is a server-side command whose semantics
  aren't visible from the call site.
- **Per-kind keybindings.** No dedicated "organizeImports" or "fixAll"
  keybinding. Each action's title in the popover suffices for v1.
  Adding extra actions later is cheap if usage justifies it.
- **Conflict detection between concurrent applies.** The popover
  dismisses on commit, making back-to-back overlapping applies hard to
  trigger in practice. Acceptable v1 behavior.
- **Request cancellation on cursor-move.** A `$/cancelRequest` for a
  superseded codeAction request would reduce wasted server work in the
  multi-press case, but the practical cost is low. Documented as
  follow-up.

## UX

### Surface

Two affordances, three trigger paths.

**Lightbulb gutter icon.** A small `dialog-information-symbolic` (or
custom-mapped lightbulb) painted in `GtkSourceView`'s left gutter, on
every line that currently has at least one diagnostic. The bulb is
purely *informational* — it says "actions *probably* available here."
Clicking the bulb fires the request.

**Popover at cursor.** A `Gtk.Popover` anchored to the cursor's
line/column, containing a `Gtk.ListBox` of returned action titles. Each
row shows `[kind badge] title` (e.g. `[quickfix] Remove unused import`).
Disabled actions render greyed-out with a tooltip surfacing the
server-supplied `disabled.reason`. Keyboard nav: ↑/↓ moves selection,
Enter commits, Escape cancels. Single-row case is still shown but
pre-focused for one-Enter commit.

Same UI vocabulary as rename's popover (popover anchored to cursor) and
references' bottom panel (kind-grouped list). No modal dialog.

### Trigger

- **Action:** `win.lsp-code-action`
- **Default accelerator:** `<Alt>Return`
  - IntelliJ-style "act on this thing" gesture. Single chord,
    layout-neutral on German keyboard, not in `docs/configure.md`'s
    explicit conflict list (which calls out `<Primary>period`,
    `<Alt>Left/Right`, `<Alt>Up/Down` as taken).
  - Lightbulb click is a co-equal trigger; popup-menu entry "Show Code
    Actions" is the third.

## Architecture

```
plugin.py  (wires action lsp-code-action, accel <Alt>Return,
            popup-menu entry, attaches gutter per view,
            owns CodeActionController per window)
   │
   ├──→ CodeActionController       (window-scoped, one per Gedit.Window)
   ├──→ LightbulbGutter            (view-scoped, one per GtkSourceView)
   └──→ CodeActionPopover          (per-invocation, short-lived)

CodeActionController uses:
   - code_action.py                (pure helpers, no GTK)
       normalize_action, group_by_kind, needs_resolve,
       extract_diag_context
   - workspace_edit.py             (existing; reused from rename)
       apply_workspace_edit
   - shared load helpers           (lifted from rename — see below)

LightbulbGutter uses:
   - server.add_diagnostics_listener (returns disposer; per memory
     project_latent_diag_listener_cleanup.md)
```

Dependencies are one-directional: plugin → controller / gutter /
popover; gutter → controller (via `on_activate` callback); controller →
pure helpers + workspace_edit + server. No cycles.

**Per-view vs per-window scope.** `LightbulbGutter` is per-view: each
`GtkSourceView` has its own gutter renderer object, attached at
`tab-added`. `CodeActionController` is per-window, matching the
references / rename precedent — the popover and the network layer are
shared across the tabs of a single window.

### Shared load helpers — refactor

`features/rename.py` currently owns `_default_load_uri` and
`_default_buffer_for_uri` (file-existence pre-flight, GFile load via
`Gedit.commands_load_location`, `loaded`-signal awaiting). codeAction
needs identical behavior. The two helpers will be lifted to
`features/_load.py` (or appended to `navigation.py` — pick at
implementation time based on what reads cleaner) and the rename module
will import them. **Targeted improvement only**, no broader refactor.

## Components

### `src/gedit_lsp/code_action.py` (pure helpers, ~80 LOC)

GTK-free; importable by both controller and popover.

```python
class NormalizedAction(TypedDict):
    title: str
    kind: str                       # "" if server omitted
    edit: dict | None
    command: dict | None            # {title, command, arguments}
    data: Any | None                # opaque resolve token
    is_preferred: bool
    disabled_reason: str | None     # populated if server set `disabled`


def normalize_action(item: Any) -> NormalizedAction | None: ...
def group_by_kind(
    actions: list[NormalizedAction],
) -> list[tuple[str, list[NormalizedAction]]]: ...
def needs_resolve(action: NormalizedAction) -> bool: ...
def extract_diag_context(
    diagnostics: list[dict], cursor_line: int, cursor_char: int,
) -> list[dict]: ...
```

`normalize_action` coerces both `Command` (LSP legacy: `title` +
`command` + `arguments`) and `CodeAction` (modern) shapes into one
structure. The controller never needs polymorphic dispatch.

`group_by_kind` orders groups: `quickfix → refactor.* → source.* →
unknown`. Server-supplied order is preserved within each group.

`needs_resolve` is `True` iff the action has neither `edit` nor
`command` (the LSP signal that the server expects a `codeAction/resolve`
round-trip before execution).

`extract_diag_context` filters the buffer's current diagnostics to
those whose range overlaps the cursor position. The result populates
the codeAction request's `context.diagnostics` field, which the spec
requires for quickfix actions to know which diagnostic they target.

### `src/gedit_lsp/features/code_action.py` (~250 LOC)

```python
class CodeActionController:
    def __init__(
        self, *,
        window: Gedit.Window,
        popover_factory: Callable[[Any], CodeActionPopover] | None = None,
        load_uri: Callable[
            [Any, str, Callable[[bool], None]], None
        ] = _default_load_uri,
        buffer_for_uri: Callable[[Any, str], Any] = _default_buffer_for_uri,
    ) -> None: ...

    def trigger(
        self,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None],
        diagnostics_for_uri: Callable[[str], list[dict]],
        cursor_line: int | None = None,   # for lightbulb-click path
    ) -> None: ...
```

State: none beyond constructor injectables. Each `trigger()` is
self-contained.

The optional `cursor_line` parameter handles the lightbulb-click path
where the cursor must be repositioned to the activated line before
sending the request — so the server's "what can I do here?" answer is
keyed to the line the user actually clicked, not wherever the cursor
happened to be.

### `src/gedit_lsp/ui/lightbulb_gutter.py` (~120 LOC)

```python
class LightbulbGutter:
    """One per GtkSourceView. Subscribes to a single language server's
    diagnostics listener; maintains the set of lit line numbers for
    its uri; renders the icon at those lines."""

    def __init__(
        self, *,
        view: GtkSource.View,
        server: LanguageServer,
        uri: str,
        on_activate: Callable[[int], None],   # line number (0-indexed)
    ) -> None: ...

    def dispose(self) -> None: ...
```

A `GtkSourceGutterRenderer` subclass overriding `do_draw`. Iterates
visible lines, paints `dialog-information-symbolic` for any line in
`_lit_lines`. Click on the icon → `on_activate(line)`. Set is recomputed
on every `publishDiagnostics` for the matching URI (distinct
`range.start.line` values across the published diagnostics).

`dispose()`:
1. Calls the disposer returned by `add_diagnostics_listener`
2. Removes the renderer from the gutter

Idempotent — `dispose()` may be called more than once (per the existing
listener-disposer contract: see memory
`project_latent_diag_listener_cleanup.md`).

Gutter renderer priority: numeric value determined at implementation
time; conventionally a small positive integer to position the bulb to
the right of the line-number column (closer to the text). Will be
verified empirically with `./install.sh` against a live gedit.

### `src/gedit_lsp/ui/code_action_popover.py` (~150 LOC)

```python
class CodeActionPopover:
    def __init__(self, view: GtkSource.View) -> None: ...

    def show(
        self, *,
        actions: list[NormalizedAction],
        on_commit: Callable[[NormalizedAction], None],
        on_cancel: Callable[[], None],
    ) -> None: ...
```

`Gtk.Popover` anchored to the cursor's line/column (same anchoring math
as `RenamePopover`). Contents: `Gtk.ListBox` of action rows. Each row
renders `[kind badge] title`. Disabled actions are insensitive with a
tooltip carrying `disabled_reason`. Keyboard: ↑/↓ move selection, Enter
commits the selected action, Escape and focus-out both cancel.

For unit-testability, the row-selection + commit-payload computation
is extracted into a pure `CodeActionPopoverModel` class; the widget
glue is exercised only via the integration test.

### `plugin.py` deltas (~50 LOC)

- Register action `lsp-code-action` on the window
- Set accel `<Alt>Return` on the application via app's accel map
- Instantiate `CodeActionController` and store on the per-window
  controllers dict
- On `tab-added`: instantiate `LightbulbGutter` for the new view, store
  in per-tab dict keyed by `Gedit.Tab`
- On `tab-removed`: pop the gutter and call `.dispose()`
- On `deactivate`: iterate per-tab dict, dispose each
- Inject `popup_menu.MENU_ITEMS` with `("Show Code Actions",
  "lsp-code-action")`

## Data flow

### Lightbulb lifecycle

```
tab-added (plugin.py)
  └─> LightbulbGutter(view, server, uri, on_activate=lambda line:
                       controller.trigger(server, uri, flush, diags_for, cursor_line=line))
      ├─> server.add_diagnostics_listener(self._on_diag) → disposer stored
      └─> view.get_gutter(Gtk.TextWindowType.LEFT).insert(self, priority=N)
          # N: small positive int, places bulb right of line numbers;
          # exact value verified empirically at implementation time

publishDiagnostics for uri
  └─> _on_diag(params):
      ├─> if params["uri"] != self._uri: ignore
      ├─> self._lit_lines = {d["range"]["start"]["line"] for d in params["diagnostics"]}
      └─> view.queue_draw()

GtkSourceView paints
  └─> do_draw(cr, bg, cell, start_iter, end_iter):
      └─> if start_iter.get_line() in self._lit_lines: paint icon

User clicks
  └─> button-press → on_activate(line)
      └─> controller.trigger(..., cursor_line=line)

tab-removed (plugin.py)
  └─> dispose():
      ├─> self._disposer()       # remove diagnostics listener
      └─> gutter.remove(self)
```

### Request lifecycle (manual, click, or popup-menu)

```
trigger(server, uri, flush, diags_for, cursor_line=None):

  # 1. Capability gate
  if not server.capability("codeActionProvider"):
      statusbar.push("LSP: server does not support code actions"); return

  # 2. Cursor capture + edit-flush invariant
  view = window.get_active_view()
  buf  = view.get_buffer()
  if cursor_line is not None:
      buf.place_cursor(buf.get_iter_at_line(cursor_line))
  cursor = buf.get_iter_at_mark(buf.get_insert())
  line, char = text_iter_to_utf16(cursor)
  flush()    # required, per memory project_edit_triggered_flush_invariant

  # 3. Context assembly
  diags_at = extract_diag_context(diags_for(uri), line, char)
  params = {
    "textDocument": {"uri": uri},
    "range": {
      "start": {"line": line, "character": char},
      "end":   {"line": line, "character": char},
    },
    "context": {
      "diagnostics": diags_at,
      "triggerKind": 1,   # Invoked (manual)
    }
  }

  # 4. Send + dispatch
  server._send_request("textDocument/codeAction", params, on_response)

on_response(msg):
  if msg.error:          statusbar.push("LSP: code action request failed"); return
  result = msg.get("result")
  if result is None or result == []:
      statusbar.push("LSP: no code actions"); return
  actions = [a for a in (normalize_action(x) for x in result) if a is not None]
  if not actions:
      statusbar.push("LSP: no code actions"); return
  popover.show(actions=actions, on_commit=_commit, on_cancel=_noop)

_commit(action):
  if needs_resolve(action):
      server._send_request("codeAction/resolve", action, _on_resolved); return
  _execute(action)

_on_resolved(msg):
  if msg.error:    statusbar.push("LSP: could not resolve action"); return
  resolved = normalize_action(msg.get("result") or action) or action
  _execute(resolved)

_execute(action):
  has_edit    = action.get("edit") is not None
  has_command = action.get("command") is not None
  if has_edit:
      _apply_with_load(action["edit"], next=lambda applied, failed:
                       _after(applied, failed, has_command, action))
  else:
      _after([], [], has_command, action)

_after(applied, failed, has_command, action):
  if has_command:
      server._send_request("workspace/executeCommand", action["command"],
                           lambda _msg: None)  # fire-and-forget
  if applied or has_command:
      statusbar.push(f"LSP: applied {action['title']}")
  else:
      statusbar.push("LSP: nothing to apply")
```

**Edit-before-command ordering** is invariant. For actions carrying
both, the edit is the client-side portion and the command is the
server-side bookkeeping (e.g. follow-up formatting). Edit first
preserves the cursor/scroll positions across any server-fired didChange
follow-ups.

**`workspace/executeCommand` shape.** Per LSP spec it is a request; in
practice pylsp / clangd / gopls return `null`. We send it via
`_send_request` for spec correctness but ignore the response.

**Cross-file edits** reuse the rename load-settle pattern verbatim:
collect URIs in the edit, identify ones not currently open, fire
`load_uri` for each, count down a `remaining` closure, fire the apply
once all loads have signalled.

## Error handling

| Failure | Behavior |
|---|---|
| No `codeActionProvider` capability | Statusbar "LSP: server does not support code actions"; bulb never appears |
| Request returns `error` | Statusbar "LSP: code action request failed"; log full error |
| Result is `null` or `[]` | Statusbar "LSP: no code actions"; no popover |
| Every item malformed (normalize returns None) | Treated as no-actions path |
| All actions have `disabled` | Popover with greyed rows; tooltip shows `disabled.reason` |
| `codeAction/resolve` returns error | Statusbar "LSP: could not resolve action"; popover dismissed |
| `apply_workspace_edit` returns non-empty `failed` | Statusbar "LSP: applied N file(s); M failed (see log)" |
| `workspace/executeCommand` returns error | Logged; statusbar reflects only the edit portion if successful |
| Window closed mid-async (resolve or load in flight) | Catch `RuntimeError` on `get_statusbar()`; log; silent no-op |
| Server crashes during request | Existing circuit-breaker in `server.py` handles it; pending callback dropped |
| Diagnostics after gutter dispose | Cannot occur — disposer removed listener |

### Edge cases

- **Cursor moved between request and response.** Anchor the popover to
  request-send time, not response time — captured in a closure. If the
  view is gone by response time, the window-closed guard catches it.
- **Multiple in-flight requests** from rapid trigger-firing. Each gets
  its own callback closure; the second popover dismisses the first via
  GTK's natural anchor takeover. No explicit cancellation. Follow-up:
  `$/cancelRequest` for superseded codeActions if needed.
- **`Command` shape without `arguments` field.** `normalize_action`
  defaults to `[]`.
- **Action with no `edit`, no `command`, no `data`.** Indistinguishable
  from a server bug; filtered out by `normalize_action` returning None.
- **Resolved action introduces new `disabled` field.** Treated as
  resolve error → statusbar + dismiss.
- **Bulb on line with no real actions.** Diagnostic-driven means the
  bulb is heuristic; the server may return `[]` on activation. User
  gets "no code actions" statusbar message. Acceptable trade-off; the
  rejected alternative (probe-driven) was too expensive.

## Testing strategy

### Unit tests

**`tests/unit/test_code_action_helpers.py`** — pure functions, no GTK.

- `normalize_action`: Command shape; CodeAction shape; mixed-array
  element; missing-title → None; missing-command → None; `disabled`
  field surfaces as `disabled_reason`
- `group_by_kind`: `quickfix → refactor.* → source.* → unknown`;
  unknown kinds bucketed last; server-supplied order preserved within
  each group
- `needs_resolve`: edit-only → False; command-only → False; both →
  False; neither → True; neither-but-data → True
- `extract_diag_context`: cursor exactly on `range.start`; multi-line
  range overlap; range fully before cursor → excluded; range fully
  after → excluded

**`tests/unit/test_code_action_controller.py`** — mocked
`LanguageServer`, `flush`, `diagnostics_for_uri`, `popover_factory`,
`window`. Real helpers under test.

- No capability → statusbar, no request
- Server error response → statusbar, no popover
- Empty result → statusbar, no popover
- Single action with `edit` → popover shown, commit applies edit
- Single action with `command` → no edit applied, `executeCommand` sent
- Single action with both → edit first, command second (assert call
  order on the mocked server)
- Action with neither → `codeAction/resolve` sent first
- Resolve error → statusbar, no apply
- Disabled actions filtered before the popover (where applicable)
- All actions disabled → popover still shows
- Multi-file edit → `load_uri` for closed URIs, apply fires only after
  all loads settle
- Window-closed during apply → no crash (mock `get_statusbar` to raise)
- `context.diagnostics` populated correctly from `extract_diag_context`
- `flush_pending_change()` called before request send

**`tests/unit/test_lightbulb_gutter.py`** — `GtkSource.Buffer` (model
only — fine in CI per memory `project_unit_tests_avoid_gtk_widgets`)
+ `MagicMock()` for `view`.

- Listener registered on construct; disposer captured
- Diagnostics for `uri` populate `_lit_lines` with distinct
  `range.start.line` values
- Diagnostics for *different* uri are ignored
- Empty diagnostics → empty `_lit_lines`
- `dispose()` calls disposer AND removes renderer
- Double-`dispose()` is safe
- `on_activate` fired with correct line on click

**`tests/unit/test_code_action_popover_model.py`** — pure logic of the
extracted `CodeActionPopoverModel` (row selection, commit payload).
Widget glue exercised only in integration.

### Integration test

**`tests/integration/test_code_action_e2e.py`** — extends the
`tests/fixtures/projects/python_rename/` fixture (or adds a sibling
fixture with `pylsp-ruff` enabled if rename's fixture won't carry it):

- Open file with an unused import → wait for diagnostics → assert
  gutter has a lit line for that import
- Send `textDocument/codeAction` for that range → real pylsp-ruff
  response
- Resolve if needed, apply the edit → assert the import is gone from
  the buffer
- Cross-file action (if the fixture produces one) → closed file gets
  loaded and edited

If `pylsp-ruff` isn't available in CI, the test is `xfail` with a
clear reason rather than silently skipping.

### Mutation-test invariants

Per memory `feedback_mutation_test_invariants`, explicitly mutation-test
these behavioral claims (sed-break, run test, restore):

1. **Edit-flush before request.** Comment the `flush()` call in
   `trigger()` → `test_code_action_flushes_before_request` fails.
2. **`context.diagnostics` filtering.** Replace `extract_diag_context(...)`
   with `[]` → controller test fails (asserts the right diag in the
   request).
3. **Edit-before-command ordering.** Swap order in `_execute` → test
   asserting mocked server call order fails.
4. **Listener disposal on tab-removed.** Comment the `.dispose()` call
   in `plugin.py`'s tab-removed handler → unit test catches residual
   subscription via listener-count assertion.

### CI gates per task

Per memory `feedback_per_task_lint_typecheck_gates`, every task runs:

```
.venv/bin/python -m pytest tests/         # not just tests/unit/
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/
```

Per memory `feedback_run_full_test_tree_pre_push`, the full
`tests/` tree (not just `tests/unit/`) runs before every push.

### Test seams

The controller's constructor accepts `load_uri`, `buffer_for_uri`, and
`popover_factory` as injection points — same shape as
`RenameController`. The lightbulb's `on_activate` callback is similarly
injectable. These are what make widget-free unit testing possible.

## Configuration / defaults

### `src/gedit_lsp/defaults.py`

- `DEFAULT_KEYBINDINGS`: add `"code-action": ["<Alt>Return"]`
- `DEFAULT_TUNABLES.enabledFeatures`: append `"codeAction"`

### `docs/configure.md`

- New row in the keybindings table: `code-action | <Alt>Return | Show
  code actions at the cursor (lightbulb in gutter signals lines with
  diagnostics that may have fixes)`
- No new tunables section needed for v1 (no probe debounce, no caching)

### `docs/protocol-coverage.md`

- New rows:
  - `textDocument/codeAction` (`<Alt>Return`; lightbulb in gutter on
    diagnostic lines; popover picker; edit + command apply)
  - `codeAction/resolve` (sent on commit when the chosen action has
    neither `edit` nor `command`)
  - `workspace/executeCommand` (sent for actions carrying a `command`)

## Documentation updates (doc-gate)

Per the doc-gate invariant (memory `project_doc_gate_invariant`),
`docs/configure.md` and `docs/protocol-coverage.md` will both be touched
in the same PR.

## References

- LSP spec: [textDocument/codeAction](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_codeAction)
- LSP spec: [codeAction/resolve](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#codeAction_resolve)
- LSP spec: [workspace/executeCommand](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#workspace_executeCommand)
- pylsp-ruff codeAction behavior — used for the integration test
- Existing precedent: `features/rename.py` (request + WorkspaceEdit
  apply with cross-file load-settle), `features/references.py` (0/1/N
  dispatch shape)
- `docs/superpowers/specs/2026-05-10-textdocument-rename-design.md` —
  source of the `workspace_edit.py` helper that codeAction reuses

