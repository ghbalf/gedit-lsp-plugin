# `textDocument/rename` + `prepareRename` — Design

**Status:** approved (pending user spec review)
**Target release:** v0.4.0 (bundled)
**Issue/PR:** TBD (feature branch `feat/rename`)
**Author:** Alfred Mickautsch (with Claude)
**Date:** 2026-05-10

## Goal

Add `textDocument/rename` (and the optional `prepareRename` companion)
to the gedit LSP plugin. From a symbol under the cursor, prompt for a
new name, ask the language server for a `WorkspaceEdit`, and apply
that edit across every affected file — including files not currently
open in any tab.

## Non-goals

- A "preview before commit" panel listing every per-file edit. We
  apply immediately. The user's safety valve is the per-file undo
  stack and the standard "save? discard?" dialog gedit shows on close.
- Cross-buffer undo. gedit doesn't offer it. Each affected file gets
  one undoable step (one `begin_user_action` block); a multi-file
  rename takes one undo press *per file* to reverse. Documented.
- In-place inline editing of the symbol in the buffer (the VS Code
  F2 UX). Significantly more GTK plumbing — cursor capture, key event
  interception, out-of-band undo. Rejected as ~3-4× the implementation
  cost without the corresponding ROI for a desktop editor.
- Pre-validating that every URI is loadable before applying any edits
  ("two-phase apply"). Best-effort instead: independent per-file
  success/failure with a statusbar summary. Matches VS Code.
- Auto-saving the modified buffers. Tabs are left dirty for the user
  to review and save (or discard).
- A blast-radius cap (`maxRenameFiles` confirm dialog). Not added in
  v0.4.0; can revisit if real usage shows runaway renames.
- `textDocument/codeAction`. It also returns `WorkspaceEdit`s and will
  reuse this feature's `apply_workspace_edit` helper, but it's a
  separate v0.4.0 item.

## UX

### Surface

A `Gtk.Popover` anchored to the active view at the cursor position,
containing a single `Gtk.Entry`. Pre-fills with `prepareRename`'s
placeholder (or the word under the cursor as fallback). All text
pre-selected so the user can immediately overtype. Enter commits;
Escape and focus-out both cancel.

The popover is the same UI vocabulary already used by signatureHelp
(popover above cursor) and definition (popover for many-results) — no
modal dialog is introduced. Modal dialogs were rejected for breaking
the editing flow and being inconsistent with the rest of the plugin.

### Trigger

- **Action:** `win.lsp-rename`
- **Default accelerator:** `F2`
  - Layout-neutral, single-key, no chord. The GNOME convention for
    "rename this thing" (Files, Nautilus). VS Code precedent.
  - Verified unbound in gedit-46, GtkSourceView, the snippets plugin,
    and the schemas. The filebrowser plugin's F2 only fires when the
    file-browser side panel has focus, not in the editor view.
  - The binding-owner check follows the [feedback_check_binding_owners]
    memory: PR #16's `Ctrl+Shift+F12` was silently consumed by
    something inside gedit-46; cross-checking up front avoids the
    same trap.
- **Right-click popup-menu entry:** `"Rename Symbol"` in the existing
  LSP submenu (`src/gedit_lsp/ui/popup_menu.py:23`).

### Flow

1. User presses F2 on a symbol.
2. Plugin checks `server.capability("renameProvider")`. If absent,
   statusbar `"LSP: server does not support rename"`; bail.
3. Read cursor `(line, char_utf16)`. Call `flush_pending_change()`
   (the [edit-flush invariant]).
4. If `renameProvider.prepareProvider` is truthy, send
   `textDocument/prepareRename` and dispatch on the response shape:
   - `null` → statusbar `"LSP: cannot rename symbol here"`. Done.
   - `Range` → read `buffer.get_text(range)` for the placeholder.
   - `{range, placeholder}` → use `placeholder` directly.
   - `{defaultBehavior: true}` → tokenize word-under-cursor.
   - error → log, fall through to word-under-cursor placeholder.
5. If `prepareProvider` is falsy, skip step 4; derive the placeholder
   by regex on the buffer line at cursor (`\b[A-Za-z_][A-Za-z0-9_]*\b`).
6. Show the popover. Pre-select the placeholder.
7. On Entry::activate (Enter):
   - Empty new name → no-op (popover stays open).
   - New name == placeholder → send the request anyway; server will
     return `null` or empty WorkspaceEdit; statusbar `"LSP: no changes"`.
   - Otherwise: send `textDocument/rename` with `{textDocument, position, newName}`.
8. On Escape / focus-out: close popover, no request fired.

### WorkspaceEdit application

Given the response is a `WorkspaceEdit`:

1. Collect the URIs from `documentChanges` (preferred) or `changes`
   (fallback shape).
2. Open any URI not currently in `window.get_documents()` via
   `Gedit.commands_load_location` (the same helper used by
   `navigation.navigate_to_uri`'s third branch — see
   [project_gedit_load_location_api]). Track loaded vs. failed.
3. `commands_load_location` is **async** — the resulting tab's
   `Gedit.Document::loaded` signal fires when the buffer is ready.
   The controller waits for *all* loads to settle (via a small
   `_PendingLoads` counter) before applying anything.
4. Once all URIs have buffers (or are known-failed), call
   `apply_workspace_edit(edit, buffer_for_uri=…)` which iterates each
   `TextDocumentEdit` and delegates to the existing
   `apply_text_edits` helper from `features/formatting.py:72`. That
   helper already sorts edits right-to-left and wraps each file in
   one `begin_user_action`/`end_user_action`, so each affected file
   ends up as a single undoable step.
5. Statusbar: `"LSP: renamed {N} file(s)"` on full success; on
   partial: `"LSP: renamed {N} file(s); {M} failed (see log)"`.

Buffers are left dirty after apply. The user reviews and saves.

## Architecture

Three new units, mirroring the references / formatting split.

| Unit | File | Responsibility |
|---|---|---|
| `RenameController` | `src/gedit_lsp/features/rename.py` | Window-scoped orchestration. Owns the trigger flow end-to-end. |
| `RenamePopover` | `src/gedit_lsp/ui/rename_popover.py` | Thin `Gtk.Popover` + `Gtk.Entry` widget. Stateless beyond the entry text and two callbacks. |
| `apply_workspace_edit` (+ `derive_placeholder`) | `src/gedit_lsp/workspace_edit.py` | Pure helpers. No GTK widgets. |

Wiring (`src/gedit_lsp/plugin.py`):

- `lsp-rename` action added to the action loop (currently lines
  172-189). Default accel `F2` from
  `defaults.DEFAULT_KEYBINDINGS["rename"]`.
- New `_on_rename_activate` handler: looks up bridge + server for the
  active doc, calls `RenameController.trigger(server, bridge.uri,
  bridge.flush_pending_change)`.
- `popup_menu.MENU_ITEMS` (currently `src/gedit_lsp/ui/popup_menu.py:23`):
  add `("Rename Symbol", "lsp-rename")`.
- `defaults.DEFAULT_TUNABLES["enabledFeatures"]`: append `"rename"`.

### Why a separate `workspace_edit.py` module

`WorkspaceEdit` is its own LSP concept, distinct from formatting's
`TextEdit[]`. Future code-action support (`textDocument/codeAction`,
also v0.4.0) returns the same shape and will reuse this helper.
Folding it into `formatting.py` would cement an unrelated concern;
keeping it standalone makes the dependency graph honest.

`derive_placeholder` lives next to `apply_workspace_edit` because
both deal with cursor-adjacent text manipulation that the controller
shouldn't carry.

### Why `RenamePopover` is a separate file

Per the [unit-tests-avoid-gtk-widgets] invariant, `Gtk.Popover` and
`Gtk.Entry` instantiation is unsafe in headless CI. Extracting the
widget keeps the controller importable and unit-testable with a
`MagicMock` factory; the popover itself gets minimal direct test
coverage and relies on manual smoke testing for visual concerns.

## Components in detail

### `RenameController`

```python
class RenameController:
    def __init__(
        self,
        *,
        window: Gedit.Window,
        popover_factory: Callable[..., RenamePopover] = RenamePopover,
    ) -> None: ...

    def trigger(
        self,
        server: LanguageServer,
        uri: str,
        flush_pending_change: Callable[[], None],
    ) -> None:
        """Mirrors ReferencesController.trigger. See spec UX flow."""
```

`popover_factory` is the test seam — production passes the real
`RenamePopover`; tests pass a `MagicMock` whose `show()` immediately
fires the on_commit callback synchronously.

The controller carries no per-rename state across triggers — each
press of F2 is a fresh request flow. In-flight cancellation is not
needed (rename is human-driven and infrequent; if the user fires F2
a second time mid-flow, the popover from the first press is still up
and they're stuck on it anyway).

### `RenamePopover`

```python
class RenamePopover:
    def __init__(self, view: Gtk.TextView) -> None: ...

    def show(
        self,
        *,
        placeholder: str,
        on_commit: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Anchor at the cursor's iter rectangle. Pre-select all text.
        Connect Entry::activate -> on_commit, Escape -> on_cancel,
        focus-out -> on_cancel.
        """

    def dismiss(self) -> None: ...
```

Anchoring uses `view.get_iter_location(cursor_iter)` to compute a
rectangle, then `popover.set_pointing_to(rect)` — the same pattern
signatureHelp uses (`features/signature_help.py`).

### `apply_workspace_edit`

```python
def apply_workspace_edit(
    edit: dict[str, Any],
    *,
    buffer_for_uri: Callable[[str], GtkSource.Buffer | None],
) -> tuple[list[str], list[str]]:
    """Apply a WorkspaceEdit. Returns (applied_uris, failed_uris).

    Prefers documentChanges; falls back to changes. Per-file errors
    don't abort the whole apply. Reuses apply_text_edits from
    features.formatting for each file's TextEdit[]. Synchronous and
    GTK-free apart from the buffer references handed in by the caller.
    """
```

Caller (the controller) is responsible for ensuring `buffer_for_uri`
returns the right buffer for each URI — that includes opening closed
files first via `commands_load_location` and waiting for `loaded`.

### `derive_placeholder`

```python
def derive_placeholder(
    buffer: GtkSource.Buffer,
    cursor_line: int,
    cursor_char_utf16: int,
) -> str:
    """Tokenize the word at (line, char) using a Python-identifier-ish
    regex. Returns "" if no identifier-shaped token spans the cursor.
    """
```

Used as the prepareRename fallback (and the no-prepareProvider path).
Regex is `\b[A-Za-z_][A-Za-z0-9_]*\b` — broad enough for most
LSP-supported languages; the server's prepareRename is the
authoritative source when available.

## Data flow

End-to-end for the common case (cursor on a symbol, server has
`prepareProvider`, rename touches 2 open files + 1 closed file):

```
F2 → plugin._on_rename_activate
   → RenameController.trigger(server, uri, flush)
       capability("renameProvider")        → True
       text_iter_to_utf16(cursor)          → (line, char)
       flush_pending_change()              ← edit-flush invariant
       server.send("textDocument/prepareRename")
   ← prepareRename response → placeholder = "old_name"
   → RenamePopover.show(placeholder="old_name", on_commit, on_cancel)
   ── user types "new_name", Enter ──
   → on_commit("new_name")
       server.send("textDocument/rename", {newName: "new_name"})
   ← rename response: WorkspaceEdit (3 files)
   → controller collects URIs
       for each closed URI:
         Gedit.commands_load_location(...)
         doc.connect("loaded", _on_load)   ← async settle
   ── all loads fire ──
   → apply_workspace_edit(edit, buffer_for_uri=window-walk)
       for each file: apply_text_edits(buf, edits)
                       (sorts right-to-left, one user_action)
   → statusbar: "LSP: renamed 3 file(s)"
```

### Timing notes

- **Async load settle** is the only non-trivial new state in the
  controller. A small `_PendingLoads` helper holds the WorkspaceEdit
  + a remaining-count + a per-URI status, decrements on each `loaded`
  signal (or a `loaded`-with-error analogue), and fires
  `apply_workspace_edit` when the count hits zero. If the controller's
  window is closed while loads are pending, the callback no-ops.
- **Edits between request-out and response-in** to open buffers can
  in theory invalidate the response's coordinates. We don't try to
  detect this — rename is a deliberate refactor gesture; users
  typically don't keep typing during it. The risk is bounded by the
  edit-flush at the start of the flow.
- **`commands_load_location` uses 1-indexed lines**; the response's
  ranges are 0-indexed. Existing `apply_text_edits` already handles
  the per-edit conversion; the load step doesn't need a position (it
  just opens the file).

## Error handling

| Failure | Behavior |
|---|---|
| Server lacks `renameProvider` | Statusbar: `"LSP: server does not support rename"`. No request, no popover. |
| `prepareRename` returns `null` | Statusbar: `"LSP: cannot rename symbol here"`. No popover. |
| `prepareRename` returns error | Log; fall through to word-under-cursor placeholder. |
| `prepareProvider` falsy on server | Skip prepareRename; regex-derive placeholder. |
| User submits empty newName | Popover stays open (no-op). |
| User submits unchanged newName | Send the request; server typically returns null/empty; statusbar `"LSP: no changes"`. |
| `textDocument/rename` returns error | Statusbar: `"LSP: rename failed (see log)"`. Log code/message. |
| `textDocument/rename` returns `null` | No-op; statusbar `"LSP: no changes"`. |
| WorkspaceEdit URI fails to load | Tracked in `failed_uris`; per-URI failure doesn't block other files; statusbar summary reflects partial. |
| `apply_text_edits` raises mid-application (corrupt server range) | Caught per-file via try/except in the controller's apply loop; URI moves to `failed_uris`. The existing helper's `try/finally` ensures `end_user_action` runs, so the partial edit remains undoable as one step. |
| Pending loads + window closed | `_PendingLoads` callback no-ops. |
| Popover open, focus-out | Treat as cancel. |

## Testing

### `tests/unit/test_rename_controller.py`

Bulk of the coverage. All controllers use `MagicMock()` views to stay
headless-CI safe per [unit-tests-avoid-gtk-widgets].

- Capability gate (no `renameProvider` → no request fired, statusbar
  pushed).
- prepareRename branch coverage:
  - `null` → statusbar `"cannot rename here"`, no popover.
  - `Range` → placeholder read from buffer.
  - `{range, placeholder}` → placeholder used directly.
  - `{defaultBehavior: true}` → fallback to `derive_placeholder`.
  - error → log, fallback to `derive_placeholder`.
  - `prepareProvider: false` → prepareRename skipped entirely.
- Edit-flush invariant: assert `flush_pending_change()` called before
  the prepareRename / rename request goes out. Mutation-test pattern
  from PR #14/#15: `sed`-break the line, watch the test fail, restore.
  See [feedback_mutation_test_invariants].
- Empty newName → no rename request fired.
- Unchanged newName → request fired anyway; null result handled.
- `textDocument/rename` server error → statusbar message, no edits
  applied.
- WorkspaceEdit response with `documentChanges` → preferred over
  `changes`.
- WorkspaceEdit with only `changes` → fallback path used.
- Best-effort partial failure: 3 URIs, 1 fails to load, 2 apply,
  statusbar shows `"renamed 2 file(s); 1 failed"`.

### `tests/unit/test_workspace_edit.py`

Pure helper tests, no GTK. `buffer_for_uri` returns mock buffers
whose `apply_text_edits` invocations are inspected.

- `documentChanges` precedence over `changes`.
- Empty edit → empty applied / empty failed.
- URI not found in lookup → goes to failed list.
- Multi-file: each file's edits stay isolated (no cross-file
  coordinate bleed).
- `derive_placeholder` returns identifier text for cursor inside an
  identifier; `""` for cursor on whitespace / punctuation.

### `tests/unit/test_rename_popover.py`

Skipped — the `RenamePopover` widget is excluded from automated tests
per the unit-tests-avoid-GTK-widgets invariant and is exercised by
manual smoke testing only, same calculus as `ReferencesPanel`.
`derive_placeholder` (the only non-widget piece) is covered in
`test_workspace_edit.py`.

### Integration test

Deferred to the planned multi-file integration fixture (referenced
by the references roadmap entry). Not blocking the unit-test gate.

### Per-task verify gate

Every implementation task in the plan runs **`pytest + ruff + mypy`**,
not just pytest. PR #16 lost time accumulating 6 ruff + 6 mypy errors
across tasks because the per-task verify was pytest-only. See
[feedback_per_task_lint_typecheck_gates].

## Documentation

The doc-gate invariant ([project_doc_gate_invariant]) requires every
PR touching `src/gedit_lsp/features/` to update `docs/configure.md`
and/or `docs/protocol-coverage.md`. This PR will:

- Add a new row to `docs/protocol-coverage.md`:
  `textDocument/rename` (F2; popover at cursor; multi-file apply) | ✓
- Add a new row to `docs/configure.md` for the `rename` keybinding
  default.
- Update `docs/roadmap.md`: move `textDocument/rename + prepareRename`
  from the v0.4.0 in-progress list into the shipped section.

## Open questions

None — all design decisions captured during brainstorming.

## Rejected alternatives (recap)

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| Apply mode | Apply immediately, open closed tabs | Preview panel (`Apply`/`Cancel`) | Preview panel is its own substantial UI surface — out of scope for v0.4.0. Not a current user pain. |
| Apply mode | Apply immediately, open closed tabs | Edit closed files on disk via `Path.write_text` | Bypasses gedit's load path. No syntax-highlighted review. Not idiomatic. |
| Input UI | Gtk.Popover near cursor | Modal Gtk.Dialog | Breaks editing flow; inconsistent with the rest of the plugin's UI vocabulary. |
| Input UI | Gtk.Popover near cursor | In-place inline edit of the symbol | ~3-4× the implementation cost (cursor capture, key event interception, out-of-band undo). |
| prepareRename | Honor server capability | Skip entirely; pre-fill from word-under-cursor | Loses the server's "this isn't renameable" check; user finds out by error after typing. |
| prepareRename | Honor server capability | Always send regardless of capability | Spec-incorrect; some servers strictly reject unsupported requests. |
| Keybinding | F2 | Shift+F6 (JetBrains) | F2 is the GNOME convention; closer match to user expectations. |
| Keybinding | F2 | No default | Friction for most users; F2 verified safe. |
| Failure mode | Best-effort, statusbar summary | Two-phase read-then-apply | Modest complexity bump for marginal safety; matches VS Code. |
| Failure mode | Best-effort, statusbar summary | Refuse if >N files (confirm dialog) | Premature; revisit if real usage shows runaway renames. |
