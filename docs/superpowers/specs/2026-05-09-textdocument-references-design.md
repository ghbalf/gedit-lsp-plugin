# `textDocument/references` — Design

**Status:** approved (pending user spec review)
**Target release:** v0.4.0 (bundled)
**Issue/PR:** TBD (feature branch `feat/references`)
**Author:** Alfred Mickautsch (with Claude)
**Date:** 2026-05-09

## Goal

Add `textDocument/references` support to the gedit LSP plugin: from a
symbol under the cursor, ask the language server for every place that
symbol is referenced and surface the results in a way the user can
inspect comfortably (click through, jump back and forth between
results).

## Non-goals

- `textDocument/implementation` and `textDocument/typeDefinition` (same
  `Location[]` shape, but separate v0.4.0+ items).
- Workspace-wide rename driven from the references panel
  (`textDocument/rename` is its own item).
- Persistent search history, refresh button, multiple result tabs.
- Filtering / searching within results.
- Tree grouping by file/folder; the result list is flat.
- Configurable `includeDeclaration` toggle in the UI; default `true`,
  no tunable.
- Word wrap, syntax highlighting, or icon decoration in the preview
  column; preview is plain text, single-line, truncated.
- Cursor-history (Alt+Backwards-style Go Back) integration on
  single-result direct jumps. The cursor-history stack is owned by
  `DefinitionController` and is conceptually a "navigate to definition
  and back" affordance; references is a search, not a navigation, and
  clicking through panel rows isn't naturally a back-track stack. Can
  be revisited later if user demand emerges.

## UX

### Surface

A new bottom-panel tab **"LSP References"**, sibling to **"LSP
Diagnostics"**. Mirrors `DiagnosticsPanel` line-for-line; the choice
follows the dominant pattern across editors (Emacs `*xref*` buffer,
Neovim quickfix, JetBrains Find Usages tool window, VS Code "Find All
References"). A popover was rejected for references because it
dismisses on focus loss, breaking the typical "click through several
results" inspection workflow.

### Trigger

- **Action:** `win.lsp-references`
- **Default accelerator:** `Ctrl+Shift+F12`
  (VS Code's "Find All References" precedent; joins the F12 family
  with our `F12` definition and `Shift+F12` go-back; function-key
  based, layout-neutral on QWERTZ. Earlier candidates `F7` and
  `Shift+F7` were rejected — gedit binds them to Toggle Cursor
  Visibility and Check Spelling respectively. **Must still be verified
  once registered** by checking the plugin's "registered action … accel"
  log line, per the project's accel-owner-check rule.)
- **Right-click popup-menu entry:** `"Find References"` in the existing
  LSP submenu.

### Result dispatch

Reuses `classify_locations()` (currently in `features/definition.py`,
moved to `navigation.py` as part of this feature — see Step 1 below).

| Classification | Behavior |
|---|---|
| `none` | Statusbar: `"LSP: no references found"`. Panel left unchanged. |
| `single` | Direct `navigate_to_uri` jump (matches definition behavior); panel left unchanged. |
| `many` | `panel.set_results(locs)` and reveal the `lsp-references` tab in the bottom panel. |

### Panel columns

| Column | Source | Notes |
|---|---|---|
| File | basename of `Location.uri` | Tooltip on the row gives the full path |
| Line | `range.start.line + 1` | 1-based for display |
| Preview | source line text | See "Preview population" below |

A hidden URI column and a hidden UTF-16 character column carry the
data needed for `navigate_to_uri` on `row-activated`.

### Preview population

For each location:

1. **Open buffer hit:** walk `window.get_documents()` to find a
   `Gedit.Document` whose file location matches the result URI; if
   found, read the line via `buf.get_iter_at_line(line)` /
   `get_iter_at_line_offset(line+1, 0)` / `get_text(...)`. Fast,
   accurate, respects unsaved edits.
2. **Closed file:** `Path(gfile.get_path()).read_text(errors="replace")
   .splitlines()[line]`. Synchronous; per-file, not per-result, via a
   small in-method dict cache so repeated hits in the same file don't
   re-read.
3. **On any error** (binary file, permission denied, line out of
   range, decode failure surviving `errors="replace"`): preview is
   `""`. The row remains navigable.

Preview is `lstrip()`'d and truncated to 120 characters with `…` if
longer.

## Architecture

### File layout

```
src/gedit_lsp/
  features/references.py           NEW
  ui/references_panel.py           NEW
  navigation.py                    EDIT  + classify_locations
  features/definition.py           EDIT  import classify_locations from navigation
  plugin.py                        EDIT  action / accel / popup wiring / dispose
  ui/popup_menu.py                 EDIT  + "Find References" entry
  defaults.py                      EDIT  + keybinding + enabledFeatures default
docs/
  configure.md                     EDIT  document the keybinding
  protocol-coverage.md             EDIT  mark textDocument/references ✓
  roadmap.md                       EDIT  move textDocument/references to "Shipped" on release
```

### Components

**`ReferencesController`** (`features/references.py`)

```python
class ReferencesController:
    def __init__(
        self,
        window: Gedit.Window,
        panel: ReferencesPanel,
        flush_pending_change: Callable[[], None],
    ) -> None: ...

    def trigger(self, server: LanguageServer, uri: str) -> None:
        # 1. capability check: server.capability("referencesProvider")
        # 2. capture cursor (line, char_utf16) via text_iter_to_utf16
        # 3. flush_pending_change()    [edit-flush invariant]
        # 4. server._send_request(
        #        "textDocument/references",
        #        {"textDocument":{"uri":uri},
        #         "position":{"line":line,"character":char},
        #         "context":{"includeDeclaration": True}},
        #        on_response,
        #    )
        # 5. on_response: classify_locations -> none/single/many dispatch
```

Stateless beyond the panel reference. No GTK widgets owned directly —
follows `DefinitionController`'s lean shape.

**`ReferencesPanel`** (`ui/references_panel.py`)

```python
class ReferencesPanel:
    def __init__(self, window: Gedit.Window) -> None:
        # ListStore: file, line, preview, uri (hidden), char_utf16 (hidden)
        # TreeView with first three columns visible
        # row-activated -> navigate_to_uri(window, uri, line, char_utf16)
        # add_titled to bottom panel as "lsp-references" / "LSP References"

    def set_results(self, window: Gedit.Window,
                    locations: list[dict[str, Any]]) -> None:
        # clear + repopulate with previews

    def clear(self) -> None: ...

    def reveal(self) -> None:
        # set bottom panel visible + select this tab
```

**`navigation.classify_locations`**

Moved verbatim from `features/definition.py`. Same signature, same
behavior, same tests. The move is a behavior-preserving refactor.

### Data flow

```
Ctrl+Shift+F12 / popup-menu "Find References"
  → win.lsp-references action
  → plugin._on_references_activate
  → ReferencesController.trigger(server, uri)
       → server.capability("referencesProvider") check
       → bridge.flush_pending_change()        [edit-flush invariant]
       → server._send_request("textDocument/references", params, on_response)

on_response(msg):
  → classify_locations(msg.get("result"))
      → "none"   → window.get_statusbar().push(0, "LSP: no references found")
      → "single" → navigate_to_uri(window, ...)
      → "many"   → panel.set_results(window, locs); panel.reveal()
```

## Edge cases

| Case | Behavior |
|---|---|
| Server doesn't advertise `referencesProvider` | Statusbar `"LSP: server does not support references"`; no request sent. |
| Server returns `null` or `[]` | `"LSP: no references found"`; panel left untouched (any prior results remain visible until next search). |
| Single result | Direct jump; panel not opened. |
| Doc not bridged (no server attached) | Log line + return — matches `_on_definition_activate`. |
| File closed and unreadable for preview | Empty preview cell; row still navigable. |
| Result line index out of range for current file content | Empty preview cell; row still navigable. |
| Request times out | `RpcClient.requestTimeoutMs` already governs this; `on_response` simply never fires. Acceptable — same as definition. |
| Repeated searches | `set_results()` clears the store first; no row accumulation. |
| Plugin deactivated while results are visible | Panel tab persists for the gedit window's lifetime — same convention as `DiagnosticsPanel`, which `do_deactivate` does not remove. The clean rebuild on the next activation handles re-attachment idempotently. |

## Configuration

### `defaults.py`

```python
DEFAULT_KEYBINDINGS = {
    ...
    "references": ["<Primary><Shift>F12"],
}

DEFAULT_TUNABLES["enabledFeatures"] = [
    "diagnostics", "hover", "definition", "outline",
    "completion", "signatureHelp", "formatting",
    "references",   # NEW
]
```

### `docs/configure.md`

Add a row to the keybindings table:

| Action | Default | Config key |
|---|---|---|
| Find References | `<Primary><Shift>F12` | `references` |

## Testing

All unit tests run headless (no `DISPLAY`); follow the project rule of
**no GtkSource.View / Gtk.Window / Gtk.Popover instantiation in unit
tests** — use `MagicMock` for view-typed parameters.

### `tests/unit/test_references_controller.py`

| Test | Asserts |
|---|---|
| `test_none_result_shows_statusbar` | empty/null result → `statusbar.push` called; `panel.set_results` NOT called |
| `test_single_result_navigates_directly` | one-element result → `navigate_to_uri` called once with the right uri/line/char; `panel.set_results` NOT called |
| `test_many_results_populate_panel` | multi-element result → `panel.set_results(locs)` and `panel.reveal()` called; `navigate_to_uri` NOT called |
| `test_flush_called_before_request` | `flush_pending_change` is invoked **before** `server._send_request` (call-order assertion via `mock_calls`) |
| `test_capability_gate` | server with `referencesProvider=False` → statusbar capability message; no request sent |
| `test_request_payload_shape` | sent params have `textDocument.uri`, `position.{line,character}`, `context.includeDeclaration=True` |

### `tests/unit/test_references_panel.py`

| Test | Asserts |
|---|---|
| `test_set_results_empty` | empty list → store empty |
| `test_set_results_populates_in_order` | rows reflect input order; columns hold expected `file`/`line`/`preview` values |
| `test_set_results_clears_prior` | second call clears the first call's rows |
| `test_clear_empties_store` | direct `clear()` call empties the store |
| `test_row_activated_navigates` | `row-activated` calls `navigate_to_uri` with the row's hidden URI and UTF-16 char column |
| `test_preview_truncation` | line longer than 120 chars truncates to 120 + `…` |
| `test_preview_open_buffer_path` | when a matching `Gedit.Document` is open, preview comes from the buffer (not disk) |
| `test_preview_disk_fallback` | when no matching doc is open, preview comes from `Path.read_text` |
| `test_preview_unreadable_file` | unreadable / out-of-range / decode-error inputs produce empty preview, no crash |

### `tests/unit/test_classify_locations_shared.py`

Verify the function is now importable from `navigation` and that
existing tests behaviorally unchanged. Existing
`test_definition.py::test_classify_*` tests adjusted to import from
the new location.

### Mutation-test invariants

Per project practice (sed-break the production line, watch the test
fail, restore — ~5s total):

- Break `flush_pending_change()` call in `ReferencesController.trigger`
  → `test_flush_called_before_request` must fail.
- Break the capability gate (always call `_send_request`) →
  `test_capability_gate` must fail.

### Integration tests

Deferred. The current fixture set is single-file; references requires
a multi-file fixture. Acceptable to ship without — definition,
formatting, signatureHelp also have unit-only coverage. Add a
multi-file integration fixture later as a separate item if useful.

## Implementation sequence

Six commits in one PR (`feat/references`):

1. **Move `classify_locations` to `navigation.py`** + update
   `features/definition.py` import. Behavior-preserving refactor.
   Existing tests pass without modification (after import update).
2. **`ReferencesPanel`** + `tests/unit/test_references_panel.py`. UI
   module standalone — no controller, no plugin wiring.
3. **`ReferencesController`** + `tests/unit/test_references_controller.py`.
   Depends on (1) and (2).
4. **Wire into `plugin.py`** — action, accel registration, popup menu
   entry (`MENU_ITEMS`), per-doc controller attachment in
   `_attach_document` if `"references" in enabledFeatures`, dispose
   path in `_on_tab_removed` and `do_deactivate`.
5. **`defaults.py`** — add `"references"` to `enabledFeatures`, add
   `"references": ["Ctrl+Shift+F12"]` to `DEFAULT_KEYBINDINGS`. Update
   `docs/configure.md` with the new entry. Doc-gate satisfied here.
6. **`docs/protocol-coverage.md`** — mark
   `textDocument/references` ✓. **`docs/roadmap.md`** — move the entry
   from "v0.4.0 — Editing operations" to "Shipped" only on release; in
   this PR, just leave it where it is (it ships when v0.4.0 ships).

Each commit is independently revertible. The PR opens at step 6.

## Risks & open questions

- **`Ctrl+Shift+F12` accel verification.** The memory rule requires a post-registration
  log check. Done in step 4 by reading the plugin log after install.
  Fallback if a clash surfaces: `Ctrl+Shift+R` (Eclipse-ish "find
  references"; needs gedit/plugin owner check first).
- **Preview cost on huge result sets.** N=10000 references would mean
  N file reads worst-case. The per-file cache makes this O(unique
  files), and most languages return references within one project
  (small file set). If it bites, lazy-fill previews on row-render
  rather than eagerly in `set_results`. Don't preempt.
- **`includeDeclaration: True` is a default.** Some servers (pylsp)
  honor it; others ignore the field. Acceptable — server behavior is
  out of scope.
