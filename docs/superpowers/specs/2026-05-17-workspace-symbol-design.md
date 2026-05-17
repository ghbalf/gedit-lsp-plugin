# `workspace/symbol` — Design

**Status:** approved (pending user spec review)
**Target release:** v0.4.0 (bundled)
**Issue/PR:** TBD (feature branch `feat/workspace-symbol`)
**Author:** Alfred Mickautsch (with Claude)
**Date:** 2026-05-17

## Goal

A live quick-pick that searches **every symbol in the project** via
`workspace/symbol`, filtered server-side as the user types, and jumps
to the chosen symbol. Includes `workspaceSymbol/resolve` so servers
that return location-only results still navigate accurately.

## Non-goals

- File-local symbol picker — the existing **outline** feature already
  covers `textDocument/documentSymbol`. This is project-wide search.
- Client-side fuzzy ranking / filtering. LSP delegates filtering to
  the server; the client sends the query string and renders results in
  server order.
- Tree grouping by file/kind; the result list is flat (same decision
  references made).
- Query history across gedit restarts. The query is seeded from the
  identifier/selection under the cursor; "remember last query" was
  considered and explicitly not chosen.
- Pagination / streaming partial results
  (`workspace/symbol` partial-result protocol is out of scope).
- Retrofitting `references` / `rename` / `codeAction` to honor their
  `enabledFeatures` checkboxes (see Configuration → Toggle semantics).

## UX

### Surface

A **quick-pick popover** anchored at the cursor: a `Gtk.Entry` over a
`Gtk.TreeView` in a `Gtk.ScrolledWindow`, inside a `Gtk.Popover`
(`modal=True`, position `BOTTOM`). Anchoring is `CodeActionPopover`'s
pattern verbatim (`view.get_iter_location(cursor)` →
`buffer_to_window_coords(WIDGET, …)` → `set_pointing_to`).

A popover (not a bottom panel) is correct here because the interaction
is *type-and-watch*: focus lives in the entry, results refresh live,
and the user commits or dismisses immediately. The references
bottom-panel rationale (persist for click-through across focus loss)
does not apply — a symbol search is a single transient act.

The popover footguns recorded from PR #18/#19 were *motion/crossing*
event-driven (mouse-hover). A typed quick-pick uses no view motion
events and runs `modal=True` safely: keyboard goes to the embedded
entry, click-outside dismisses. The popover risk here is therefore
materially lower than mouse-hover's. `Gtk.Dialog` is the documented
fallback if live smoke reveals an entry-inside-popover focus problem.

### Trigger

- **Action:** `win.lsp-workspace-symbol`
- **Default accelerator:** `Shift+F3` — layout-neutral F-key chord
  (German-keyboard friendly, no AltGr), same family as references
  `Shift+F4` / code-action `Shift+F2`. Plain `F3` is "find next" in
  many apps, but gedit uses `Ctrl+G`, so `Shift+F3` is expected free.
  **Verified live during smoke** (every accel in this project is —
  references went `Ctrl+Shift+F12` → `Shift+F4` after smoke caught
  silent interception by gedit/GtkSourceView).
- **Right-click popup-menu entry:** `"Search Symbols…"` in the
  existing LSP submenu (`ui/popup_menu.py` `MENU_ITEMS`).

The activate handler resolves active view → doc → bridge → server
exactly like `_on_references_activate` (log + return if not bridged).

### On open

1. **Toggle gate:** `"workspaceSymbol" in config.tunable("enabledFeatures")`
   — if absent, the action no-ops (the prefs checkbox is functionally
   real; see Configuration).
2. **Capability gate:** `server.capability("workspaceSymbolProvider")`
   falsy → statusbar
   `"LSP: server does not support workspace symbol search"`, no popover.
   (Capability is `None` until `initialize`; acceptable for a
   user-triggered action since the server is normally `READY` by the
   time the user presses the accel — this is *not* the attach-time
   gate that bit mouse-hover.)
3. `flush_pending_change()` once — edit-flush invariant, so the
   server's view of any open buffers is current.
4. Seed the entry: `seed_query(buf)` — the current selection if
   non-empty, else the identifier under the cursor, else `""`. Text
   fully selected (`select_region(0, -1)`) so the first keystroke
   replaces it but Enter immediately searches the seed.
5. If the seed is non-empty, fire one **immediate** query (no debounce
   wait) so results are present instantly.

### Live query loop

- Entry `changed` → controller schedules a debounced query
  (`workspaceSymbolDebounceMs`, default 150).
- On debounce fire: if a request is in flight,
  `server.cancel_request(prev_id)`; bump an integer request token;
  send `workspace/symbol {"query": <entry text>}`; store the id.
- **Empty query** sends no request (pylsp returns nothing; the LSP
  spec permits servers to return the *entire* index, which can be
  huge). The list shows a dim, unselectable **"Type to search
  symbols"** row and any prior results are cleared.
- `on_response`:
  - `msg["error"]` → statusbar one-liner, popover left up.
  - response token ≠ current token → **dropped** (a newer query
    superseded it; prevents flicker during fast typing).
  - `null` / `[]` → `quickpick.set_results([], hint="No symbols match")`.
  - else → `quickpick.set_results(parse_symbol_results(msg.result))`
    (model repopulated, rows re-rendered, first row selected).

The **hint** (`"Type to search symbols"` / `"No symbols match"`) is a
widget-level placeholder rendered when the result list is empty — it
is **not** a `QuickPickModel` entry. The model only ever holds real
symbols, so `selected()` is `None` and `Enter` is a no-op while a hint
is showing. The controller knows whether the query was empty vs
non-empty-but-unmatched and passes the correct `hint` string.

### Result rows

Per symbol:

- **Primary:** `name`.
- **Secondary (dim):** `kind-label · containerName · basename:line`
  (1-based line). `containerName` omitted when absent.
- `SymbolKind` int (1–26) → short label via `symbol_kind_label`
  (e.g. 5→`class`, 6→`method`, 12→`function`, 13→`variable`,
  14→`constant`); unknown → `symbol`.
- Rendered as `Gtk.CellRendererText` **text** (column `text=0`,
  never `markup=`), so server-provided strings are injection-safe —
  a symbol named `<b>x</b>` must not render as markup.
- **Row → symbol retrieval (implemented design — supersedes the
  earlier `_gedit_lsp_symbol`-stash sketch):** the widget does *not*
  stash the dict on each row. Instead `WorkspaceSymbolQuickPick`
  wraps a `QuickPickModel` and `set_results` populates the
  `Gtk.ListStore` and the model from the *same* `symbols` list in the
  *same order*; activation reads the symbol via
  `model.selected()` (keyboard) or
  `model.select_index(path.get_indices()[0])` → `model.selected()`
  (mouse). This is the chosen design because it keeps the symbol
  objects in the already-unit-tested pure model rather than smuggled
  through GTK row attributes, mirroring how `CodeActionPopoverModel`
  owns selection state. **Invariant (by construction):** the
  `Gtk.ListStore` row index and `QuickPickModel._symbols` index must
  stay 1:1 — `set_results` is the single writer of both and writes
  them together; the empty/hint case appends a *non-symbol*
  placeholder row while the model is empty, and activation is safe
  there only because `model.selected()` returns `None` first (the
  model, not the store, is the source of truth for activation). Any
  future change that adds non-symbol rows (e.g. a "…more" footer) or
  filters one side must preserve this 1:1 mapping or route activation
  through the model exclusively.

No themed icon decoration (matches the references "plain text, no
icon decoration" non-goal — avoids icon-name portability questions).

### Keyboard / mouse

Focus stays in the entry throughout. The entry's `key-press-event`
intercepts and returns `True` for:

- `Down` / `Up` → `model.move_down/up()` + re-highlight + scroll the
  selected row into view.
- `Page_Down` / `Page_Up` → `model.page_down/up(n)`.
- `Return` → activate the selected symbol.
- `Escape` → dismiss (cancel).

Mouse: `TreeView::row-activated` → activate that row.

Activation and dismissal use the **callback-clear-before-popdown**
discipline (`self._on_* = None` *before* `popdown()`), so the
`closed` signal's auto-cancel no-ops after a commit. Direct copy of
`RenamePopover` / `CodeActionPopover`.

### Activation / navigation

From the chosen symbol's `location`:

| Condition | Behavior |
|---|---|
| `location.range` present | `navigate_to_uri(window, uri, line, char_utf16, to_iter=utf16→iter)` — the references path; handles active/other-tab/closed branches. |
| no `range`, `workspaceSymbolProvider.resolveProvider` true | `workspaceSymbol/resolve` with the raw symbol → navigate to the resolved `location.range.start`. |
| no `range`, no resolve support (or resolve errors/times out) | `navigate_to_uri(window, uri, 0, 0)` — documented fallback. |

Resolve is fire-and-forget with the same stale-token guard; the
popover is already down by the time it returns.

## Architecture

### File layout

```
src/gedit_lsp/
  features/workspace_symbol.py        NEW  WorkspaceSymbolController + pure helpers
  ui/workspace_symbol_quickpick.py    NEW  QuickPickModel (pure) + WorkspaceSymbolQuickPick (widget)
  plugin.py                           EDIT construct, action map, handler, dispose
  ui/popup_menu.py                    EDIT + "Search Symbols…" MENU_ITEMS entry
  defaults.py                         EDIT keybinding + enabledFeatures + workspaceSymbolDebounceMs
docs/
  configure.md                        EDIT keybinding row + behavior paragraph   ┐ doc-gate
  protocol-coverage.md                EDIT workspace/symbol ✓, workspaceSymbol/resolve ✓ ┘
  roadmap.md                          (untouched until release — references precedent)
```

Mirrors the codeAction decomposition: pure helpers + controller in
`features/`, pure model + widget in `ui/`.

### Components

**Pure helpers** (`features/workspace_symbol.py`, GTK-free,
unit-tested):

- `parse_symbol_results(result: Any) -> list[dict[str, Any]]`
  Normalizes `SymbolInformation[]` / `WorkspaceSymbol[]` / `null` /
  `[]` / non-list into a flat list of symbol dicts, each retaining
  `name`, `kind`, `containerName`, `location`. A `WorkspaceSymbol`
  whose `location` has only `uri` (no `range`) is kept as-is — the
  resolve decision is made at activation time, not here.
- `symbol_kind_label(kind: int) -> str` — `SymbolKind` 1–26 → short
  label; unknown / out-of-range → `"symbol"`.
- `seed_query(buf: Any) -> str` — the initial query string: the
  buffer's current selection if non-empty, else the identifier run
  around the insert mark, else `""` (whitespace/punctuation). All
  seed precedence lives here, in the pure layer — the controller just
  calls `seed_query(view.get_buffer())`. Operates on a
  `Gtk.TextBuffer` (model layer — headless-testable per the
  unit-test-avoid-widgets invariant, like the existing utf16 tests).

**`WorkspaceSymbolController`** (`features/workspace_symbol.py`,
window-scoped, GTK-free, unit-tested):

```python
class WorkspaceSymbolController:
    def __init__(
        self,
        *,
        window: Gedit.Window,
        quickpick: QuickPick,            # narrow show/set_results/dismiss iface
        config: Config,
        schedule: Callable[[int, Callable[[], bool]], int] = GLib.timeout_add,
        cancel:   Callable[[int], None]                     = GLib.source_remove,
    ) -> None: ...

    def trigger(
        self,
        server: LanguageServer,
        view: Any,
        flush_pending_change: Callable[[], None],
    ) -> None:
        # enabledFeatures gate; capability gate; flush_pending_change()
        # seed = seed_query(view.get_buffer())
        # quickpick.show(seed=…, on_query=_on_query,
        #                 on_activate=_on_activate, on_cancel=_on_cancel)
        # if seed: _on_query(seed)            # immediate, no debounce

    def _on_query(self, text: str) -> None: ...    # debounce → _fire
    def _fire(self, text: str) -> None: ...        # cancel in-flight, token++, send/clear
    def _on_response(self, token: int, msg: dict) -> None: ...  # stale guard; parse; set_results
    def _on_activate(self, symbol: dict) -> None: ...  # range → navigate; else resolve-or-line-0
    def _on_cancel(self) -> None: ...              # cancel in-flight; drop timer
```

Owns the debounce timer id, the request token, and the in-flight
request id. The `schedule` / `cancel` injection seams are the
`MouseHoverController` pattern, making debounce/cancel/token logic
unit-testable without a GLib main loop. The controller has no GTK
widgets and talks to the quick-pick through a narrow interface, so it
is tested against a mock quick-pick exactly as `ReferencesController`
is tested against a mock panel.

`flush_pending_change()` is called once in `trigger()` (not per
keystroke): the user types in the popover entry, not the document, so
the buffer is stable for the duration of the search.

**`QuickPickModel`** (`ui/workspace_symbol_quickpick.py`, pure,
unit-tested):

```python
class QuickPickModel:
    def set_results(self, symbols: list[dict]) -> None: ...
    def selected(self) -> dict | None: ...
    def move_up(self) -> None: ...
    def move_down(self) -> None: ...
    def page_up(self, n: int) -> None: ...
    def page_down(self, n: int) -> None: ...
    @property
    def results(self) -> list[dict]: ...
```

Direct analogue of `CodeActionPopoverModel`: selection index with
wrap-around, re-clamped on every `set_results`.

**`WorkspaceSymbolQuickPick`** (`ui/workspace_symbol_quickpick.py`,
the `Gtk.Popover`, **smoke-only**):

```python
class WorkspaceSymbolQuickPick:
    def show(self, *, seed: str,
             on_query:    Callable[[str], None],
             on_activate: Callable[[dict], None],
             on_cancel:   Callable[[], None]) -> None: ...
    def set_results(self, symbols: list[dict],
                    *, hint: str | None = None) -> None: ...
    def dismiss(self) -> None: ...
```

`set_results` repopulates the wrapped `QuickPickModel` and re-renders
rows. When `symbols` is empty, `hint` (if given) is shown as a dim,
unselectable placeholder label — never a model row. `QuickPickModel`
itself takes only `list[dict]` of real symbols (no `hint` param); the
placeholder is purely a widget concern.

Owns popover/entry/treeview, key routing, and the
callback-clear-before-popdown discipline. Wraps a `QuickPickModel`
for selection state. **No unit tests** — widget construction in
headless unit tests is explicitly forbidden (the mouse-hover CI
SIGTRAP lesson: helpers whose body spins widgets must not be
unit-constructed). Exercised by manual smoke + the integration test.

### Data flow

```
Shift+F3 / popup "Search Symbols…"
 → win.lsp-workspace-symbol → plugin._on_workspace_symbol_activate
     (resolve view→doc→bridge→server; enabledFeatures gate)
 → WorkspaceSymbolController.trigger(server, view, flush_pending_change)
     → capability("workspaceSymbolProvider") gate
     → flush_pending_change()                    [edit-flush invariant]
     → seed = seed_query(buf)
     → quickpick.show(seed, on_query, on_activate, on_cancel)
     → if seed: on_query(seed)                   [immediate, no debounce]

entry "changed" → on_query(text)
 → cancel pending debounce; schedule(debounceMs, _fire)
 → _fire: if in-flight: server.cancel_request(prev_id)
          token += 1; my = token
          text == "" → quickpick.set_results([], hint="Type to search symbols")
                       return
          prev_id = server._send_request("workspace/symbol",
                                          {"query": text}, cb)

cb(msg) → msg.error → statusbar; return
          my != token → return                   [stale guard]
          syms = parse_symbol_results(msg.result)
          syms == [] → quickpick.set_results([], hint="No symbols match")
          else       → quickpick.set_results(syms)

Enter / row-activated → on_activate(symbol)
 → loc = symbol["location"]
   loc.range            → navigate_to_uri(uri, range.start…)
   resolveProvider true → workspaceSymbol/resolve → navigate(resolved range)
   else                 → navigate_to_uri(uri, 0, 0)   [fallback]
 (popover already popped down via callback-clear-before-popdown)
```

## Edge cases

| Case | Behavior |
|---|---|
| Server doesn't advertise `workspaceSymbolProvider` | Statusbar `"LSP: server does not support workspace symbol search"`; no popover. |
| `"workspaceSymbol"` not in `enabledFeatures` | Action no-ops (checkbox is functional). |
| Doc not bridged (no server) | Log line + return — mirrors `_on_references_activate`. |
| Empty query | No request; widget placeholder "Type to search symbols"; prior results cleared; `Enter` no-ops (model empty). |
| Non-empty query, `null` / `[]` result | Widget placeholder "No symbols match"; `Enter` no-ops. |
| Stale response (token mismatch) | Dropped; no flicker during fast typing. |
| New keystroke while a request is in flight | `server.cancel_request(prev_id)` + token bump; a late response is token-guarded even if the cancel no-ops server-side. |
| `WorkspaceSymbol` without range, `resolveProvider` true | `workspaceSymbol/resolve` → navigate resolved range; resolve error/timeout → line 0. |
| `WorkspaceSymbol` without range, no resolve support | Navigate `(uri, 0, 0)`. |
| Target symbol in a closed file | `navigate_to_uri` branch-3 opens it (proven path). |
| Popover dismissed mid-flight (Escape / click-out) | `on_cancel`; in-flight request cancelled; any late query/resolve response token-guarded and harmless. |
| Server string contains markup characters | Rendered as `Gtk.Label` text, never `set_markup`. |
| Repeated triggers while popover open | Defensive teardown of the prior popover before showing the new one (RenamePopover precedent). |
| Very large result set | O(N) render like references; no display cap in v0.4.0 (risk noted below; servers usually cap `workspace/symbol`; add a cap later under YAGNI). |
| Request times out | `RpcClient.requestTimeoutMs` governs it; `on_response` simply never fires — acceptable, same as references. |
| Plugin deactivated while popover open | Dispose: dismiss popover, remove action, drop controller. Window-scoped like the references panel. |

## Configuration

### `defaults.py`

```python
DEFAULT_KEYBINDINGS = {
    ...
    "workspace-symbol": ["<Shift>F3"],
}

DEFAULT_TUNABLES = {
    ...
    "workspaceSymbolDebounceMs": 150,
    "enabledFeatures": [
        "diagnostics", "hover", "definition", "outline",
        "completion", "signatureHelp", "formatting", "references",
        "rename", "codeAction", "mouseHover",
        "workspaceSymbol",   # NEW
    ],
}
```

Adding `"workspaceSymbol"` to `enabledFeatures` auto-flows into
`ui/prefs.py`'s `FEATURE_CHECKBOX_NAMES` (mechanically derived from
`DEFAULT_TUNABLES["enabledFeatures"]`); `tests/unit/test_prefs.py`'s
sync assertion enforces that the checkbox exists. Satisfies the
"every feature toggleable via both `enabledFeatures` and the prefs
UI" invariant.

### Toggle semantics (decision)

`_on_workspace_symbol_activate` gates on
`"workspaceSymbol" in config.tunable("enabledFeatures")`, so unchecking
the prefs box **actually disables** the feature.

This intentionally improves on the existing `references` / `rename` /
`codeAction` precedent, whose actions fire unconditionally regardless
of their checkbox (those entries exist only for the prefs-sync
invariant and are functionally inert). Retrofitting those three is
**out of scope** for this feature (an unrelated change, per the
"don't refactor pre-existing code unless asked" rule) and is recorded
here as a known follow-up. User confirmed (2026-05-17): make the
workspace-symbol checkbox functional; do not retrofit the other three.

### `docs/configure.md`

Add a keybindings-table row and a short behavior paragraph:

| Action | Default | Config key |
|---|---|---|
| Search Symbols | `<Shift>F3` | `workspace-symbol` |

### `docs/protocol-coverage.md`

Add:

| Method | Status |
|---|---|
| `workspace/symbol` (Shift+F3; live quick-pick, server-side filtered) | ✓ |
| `workspaceSymbol/resolve` (sent on activation when the chosen symbol has no `location.range` and the server advertises `resolveProvider`) | ✓ |

## Testing

All unit tests run headless (no `DISPLAY`). Project rule: **no
`GtkSource.View` / `Gtk.Window` / `Gtk.Popover` instantiation in unit
tests** — `Gtk.TextBuffer` (model) is allowed.

### `tests/unit/test_workspace_symbol_helpers.py`

| Test | Asserts |
|---|---|
| `test_parse_symbolinformation` | `SymbolInformation[]` → flat dicts with name/kind/containerName/location |
| `test_parse_workspacesymbol_with_range` | newer shape carrying a full `location.range` kept intact |
| `test_parse_workspacesymbol_without_range` | `location` with only `uri` kept as-is (no synthetic range) |
| `test_parse_null_and_empty` | `null` → `[]`; `[]` → `[]` |
| `test_parse_non_list` | non-list / garbage → `[]` (defensive) |
| `test_symbol_kind_label_known` | representative kinds map to expected labels |
| `test_symbol_kind_label_unknown` | 0 / 99 / negative → `"symbol"` |
| `test_seed_query_identifier` | no selection, cursor inside an identifier → that identifier |
| `test_seed_query_boundaries` | cursor at start/end of identifier still returns it |
| `test_seed_query_whitespace` | no selection, cursor on whitespace/punctuation → `""` |
| `test_seed_query_selection_precedence` | a non-empty selection wins over the word under the caret |

### `tests/unit/test_quickpick_model.py`

| Test | Asserts |
|---|---|
| `test_set_results_selects_first` | non-empty results → `selected()` is element 0 |
| `test_set_results_empty` | empty → `selected()` is `None` |
| `test_move_down_up_wraps` | wrap-around in both directions |
| `test_page_moves_clamp` | page moves clamp at ends, never index-error |
| `test_reset_reclamps_selection` | shorter second `set_results` re-clamps the index |

### `tests/unit/test_workspace_symbol_controller.py`

| Test | Asserts |
|---|---|
| `test_capability_gate` | `workspaceSymbolProvider` falsy → statusbar; `quickpick.show` NOT called |
| `test_disabled_feature_noop` | `"workspaceSymbol"` absent from `enabledFeatures` → nothing happens |
| `test_flush_before_first_query` | `flush_pending_change` invoked **before** the first `_send_request` (call-order via `mock_calls`) |
| `test_debounce_schedules_then_fires_once` | one `schedule` per keystroke; one `_send_request` per debounce fire |
| `test_inflight_keystroke_cancels` | second keystroke → `server.cancel_request(prev_id)` + token bump |
| `test_stale_response_ignored` | response with old token → `quickpick.set_results` NOT called |
| `test_empty_query_sends_nothing` | empty query → no `_send_request`; results cleared |
| `test_nonempty_payload_shape` | sent params == `{"query": text}` |
| `test_activate_with_range_navigates` | `navigate_to_uri` called with the symbol's uri/line/char |
| `test_activate_resolve_then_navigate` | no range + `resolveProvider` → `workspaceSymbol/resolve` sent, then navigate to resolved range |
| `test_activate_no_resolve_falls_back` | no range + no resolve → `navigate_to_uri(uri, 0, 0)` |
| `test_resolve_error_falls_back` | resolve returns error → `navigate_to_uri(uri, 0, 0)` |
| `test_cancel_drops_inflight` | `_on_cancel` cancels the in-flight request + clears the debounce timer |

### Mutation-test invariants

Per project practice (sed-break the production line, watch the test
fail, restore — ~5 s total):

- Break the stale-token guard (always accept) →
  `test_stale_response_ignored` must fail.
- Break the `flush_pending_change()` call →
  `test_flush_before_first_query` must fail.
- Break the capability gate (always proceed) →
  `test_capability_gate` must fail.

### Integration test

`tests/integration/test_workspace_symbol_pylsp.py` — pylsp returns
`SymbolInformation` with full locations. Reuse the existing multi-file
fixture `tests/fixtures/projects/python_rename/` (lib.py / app.py /
utils.py): drive `workspace/symbol` for a known symbol name and assert
the expected `(uri, line)` is among the results. Unlike references
(which had to defer integration for lack of a multi-file fixture),
this fixture now exists, so the integration test is **in scope** — it
also discharges the roadmap's "multi-file integration test fixture"
housekeeping item. Follows the codeAction integration test's
xfail-when-unavailable shape if pylsp is absent from the CI image.

### Manual smoke (`docs/manual-smoke-test.md`, blocking)

Numbered, blocking per the manual-smoke invariant (GTK-heavy +
accel + popover feature — exactly the class where unit/CI-green bugs
hide):

1. `Shift+F3` opens the quick-pick in live gedit (binding-owner
   check — confirm GtkSourceView/gedit doesn't swallow it).
2. Seed = identifier under cursor, fully selected.
3. Typing filters results live (server-side).
4. `Down`/`Up`/`PgDn`/`PgUp` move the selection while focus stays in
   the entry.
5. `Enter` navigates — symbol in an already-open file.
6. `Enter` navigates — symbol in a closed file (opens a tab).
7. `Escape` dismisses; click-outside dismisses.
8. Empty query shows the "Type to search symbols" hint.
9. A query with no matches shows the "No symbols match" hint.
10. Rapid typing produces no stale/flickering results.

The `workspaceSymbol/resolve` path cannot be exercised against pylsp
(it returns full ranges); noted as a smoke gap, covered by
`test_activate_resolve_then_navigate`.

## Implementation sequence

One PR (`feat/workspace-symbol`). **Every commit** runs the full gate:
`.venv/bin/python -m pytest tests/` + `ruff` + `mypy` (not just
`tests/unit/` — integration fixtures catch signature drift; per the
per-task-lint and full-test-tree feedback invariants).

1. **Pure helpers** — `parse_symbol_results`, `symbol_kind_label`,
   `seed_query` + `test_workspace_symbol_helpers.py`.
2. **`QuickPickModel`** + `test_quickpick_model.py`. Pure; no widget,
   no controller, no plugin wiring.
3. **`WorkspaceSymbolController`** + `test_workspace_symbol_controller.py`
   + the three mutation-test invariants. Depends on (1) and (2);
   tested against a mock quick-pick and injected `schedule`/`cancel`.
4. **`WorkspaceSymbolQuickPick`** widget (smoke-only; no unit test by
   rule). Depends on (2).
5. **Wire `plugin.py`** — construct quick-pick + controller in window
   activate, add to the action map, `_on_workspace_symbol_activate`
   (with the `enabledFeatures` gate), dispose path in `_on_tab_removed`
   / `do_deactivate`; add the `"Search Symbols…"` `MENU_ITEMS` entry
   in `ui/popup_menu.py`.
6. **`defaults.py`** — keybinding, `enabledFeatures`,
   `workspaceSymbolDebounceMs`. **`docs/configure.md`** +
   **`docs/protocol-coverage.md`** (doc-gate satisfied here).
   **Integration test** against pylsp + the existing fixture.

Each commit is independently revertible. A **final cumulative
cross-task review** runs before the PR opens (the PR #19 lesson:
per-task reviews miss spec gaps that fall *between* tasks). The PR
opens at step 6. `docs/roadmap.md` moves the entry to "Shipped" only
at v0.4.0 release time, not in this PR.

## Risks & open questions

- **Accel verification.** `Shift+F3` is expected free (gedit binds
  find-next to `Ctrl+G`), but per project history *every* accel must
  be confirmed in live gedit — GtkSourceView view-level bindings have
  silently swallowed accels before (`Ctrl+Shift+F12` for references).
  Smoke step 1 is the gate; fall back to another free F-key chord if
  it's intercepted.
- **Entry-inside-popover focus.** A `Gtk.Entry` with keyboard focus
  inside a `modal=True` `Gtk.Popover`, with arrow keys routed to a
  sibling `TreeView`, is the riskiest GTK piece. Mitigation: focus
  stays in the entry; arrows are intercepted on the entry's
  `key-press-event` and never reach the TreeView as caret/scroll.
  Documented fallback if smoke fails: a centered `Gtk.Dialog` (same
  internal layout, well-trodden focus model).
- **Huge result sets.** No display cap in v0.4.0. Servers generally
  cap `workspace/symbol`; if a profiler or smoke flags lag, add a
  client-side display cap (e.g. first 200 rows + a "…more, refine
  query" footer) — deferred under YAGNI, mirroring the references
  preview-cache deferral.
- **Empty-query semantics are server-defined.** The spec lets a
  server return its whole index for `""`. We send no request for the
  empty string, so behavior is uniform across servers regardless of
  their empty-query policy.
