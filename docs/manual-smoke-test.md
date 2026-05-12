# Manual smoke-test checklist

Required to pass 100% before cutting a release. Tester reads each line,
performs the action, ticks the box.

## Setup

- [ ] On Ubuntu 24.04 + gedit 46.x.
- [ ] Plugin installed via `make install`.
- [ ] gedit restarted; plugin shows in Preferences → Plugins.
- [ ] Plugin enabled.
- [ ] `~/.config/gedit/lsp-plugin.json` does not exist (test the default path).
- [ ] `pylsp` is on `$PATH`.

## Diagnostics

- [ ] Open `/tmp/test.py` containing `import nonexistent_xyz`. Within 5 s,
      a red squiggle appears under the import target.
- [ ] *LSP Diagnostics* bottom panel lists the same error.
- [ ] Edit the file to fix the import. Within 5 s, the squiggle disappears.

## Hover

- [ ] Open a Python file using `os.path.join`. Place cursor on `join`.
      Press **Ctrl+K** → popover appears with `os.path.join` documentation.
- [ ] Press **Esc** → popover closes.
- [ ] Move cursor → if popover was still open, it closes.

## Definition

- [ ] Open `tests/fixtures/projects/python_definition/main.py`. Cursor
      on the call to `helper(42)` in `main`. Press **F12** → cursor
      jumps to the `def helper(x):` line.
- [ ] Press **Shift+F12** → cursor returns to the `helper(42)` call.
- [ ] Right-click in the buffer → an **LSP** submenu lists the same three
      actions; clicking each invokes it.
- [ ] Open a new untitled buffer (Ctrl+N), type `int main(){return 0;}`,
      Save As `demo.c`. Within ~1s the statusbar should show the LSP state
      indicator and right-click should expose the LSP submenu — proves the
      plugin attaches on Save-As, not only on file-open.
- [ ] With the C buffer above showing diagnostics in the LSP Diagnostics
      panel, **close the tab**. The C file's rows must disappear from the
      panel. Same check on a `.py` buffer. Proves panel rows follow the
      buffer's lifetime independent of server-specific cleanup behavior
      (clangd doesn't send empty publishDiagnostics on close; pylsp does).

## Outline

- [ ] Open `tests/fixtures/projects/python_outline/sample.py`. Within
      2 s, the *LSP Outline* side panel shows `Greeter > hello, goodbye`.
- [ ] Click `goodbye` in the panel → cursor jumps to the method.

## Rename

Fixture: `tests/fixtures/projects/python_rename/` (lib.py + app.py +
utils.py + pyproject.toml). Open **only `app.py`** before each test —
lib.py and utils.py should be closed so the multi-file load path is
exercised.

> **pylsp + jedi caveat:** jedi's rename is permissive — it accepts
> any identifier the cursor sits on, including stdlib builtins
> (`print`, etc.). Refusal is *server-side* and only `pylsp-rope`
> would gate that, but rope_rename is broken on pylsp 1.10 (see the
> `project_pylsp_jedi_rename_caveats` memory).
>
> Cross-file rename works for closed files: jedi walks the project
> filesystem rooted via `pyproject.toml`. The plugin's
> `_revert_pylsp_view_if_dirty` (added 2026-05-11) handles the
> previously-broken case where closing a dirty tab pinned parso's
> parser cache at the rename content — repeat-rename now works
> regardless of whether you saved the auto-opened tabs first.
>
> Between scenarios: `git restore tests/fixtures/projects/python_rename/`
> on disk; in each open tab File → Revert (or close without saving —
> the workaround keeps pylsp's view consistent with disk either way).

- [ ] Open `tests/fixtures/projects/python_rename/app.py`. Cursor on
      `compute_total` (the import on line 27 *or* either call site).
      Press **F2** → popover anchored at the cursor, pre-filled with
      `compute_total`, text already selected.
- [ ] Type `compute_grand_total`, press **Enter**. Within ~1 s:
      lib.py and utils.py auto-open as new tabs marked dirty; all
      occurrences of `compute_total` are renamed across all three
      files; statusbar shows `LSP: renamed 3 file(s)`.
- [ ] **Discard** in-place: `git restore tests/fixtures/projects/python_rename/`,
      then either File → Revert in every open tab, OR close lib.py +
      utils.py without saving and Ctrl+Z app.py. Both paths must yield
      a successful 3-file rename on the next F2 — the
      `_revert_pylsp_view_if_dirty` workaround keeps pylsp's parso
      cache aligned with disk on close.
- [ ] Cursor on `Calculator` (the class import or instantiation in
      `stateful_demo`). Press **F2** → popover with `Calculator`
      selected. Type `Adder`, Enter → app.py + lib.py renamed;
      statusbar `LSP: renamed 2 file(s)`. Discard as above.
- [ ] Cursor on `print` (a stdlib builtin). Press **F2** → popover
      appears pre-filled with `print` (jedi accepts builtins). Press
      **Escape** to dismiss without committing. *Caveat:* if you do
      commit a new name here, pylsp will rename the in-file references
      only — it has no idea `print` is a builtin. With `pylsp-rope`
      installed instead of jedi, this would be refused server-side
      with `LSP: cannot rename symbol here`.
- [ ] Cursor inside a string literal or whitespace (no identifier).
      Press **F2** → statusbar shows `LSP: cannot rename symbol here`
      and no popover appears (pylsp's prepareRename returned null;
      controller honours the refusal). Verify `plugin.log` contains
      `rename: prepareRename returned null — refused`.
- [ ] Press **F2** on `compute_total`, then **Escape**. Popover
      dismisses, no rename request fired. (No `LSP: renamed …` line
      appears in the statusbar.)
- [ ] Press **F2** on `compute_total`, then click outside the popover
      (in the editor buffer). Popover dismisses cleanly; no rename
      request.
- [ ] **Discoverability:** right-click anywhere in the buffer → LSP
      submenu shows **Rename Symbol** between **Find References** and
      **Format**. Clicking it triggers the same flow as F2.
- [ ] Verify `~/.local/state/gedit-lsp/plugin.log` contains
      `registered action win.lsp-rename accels=['F2']` after activation
      and a `rename action invoked` line per F2 press.

## Code actions

After `./install.sh` and restarting gedit, open
`tests/fixtures/projects/python_code_action/example.py` (or any
Python file with an unused import) and verify:

- [ ] **Lightbulb in gutter** — a lightbulb icon appears in the left
      gutter on lines that have a diagnostic (e.g. the unused
      `import os` line).
- [ ] **Popup-menu entry** — right-clicking the buffer shows "Show
      Code Actions" in the LSP submenu.
- [ ] **Keybinding** — pressing `Alt+Return` on a diagnostic line
      opens the picker popover.
- [ ] **Picker contents** — the popover shows at least one action
      (for the unused-import case, "Remove unused import" or similar
      from `pylsp-ruff`).
- [ ] **Apply** — selecting an action and pressing Enter applies the
      edit (the import line is removed from the buffer).
- [ ] **Statusbar** — after apply, the statusbar shows "LSP: applied
      <title>".
- [ ] **Bulb clears after fix** — once the diagnostic is resolved by
      the apply, the lightbulb disappears from that line.
- [ ] **Window-closed mid-popover** — closing the tab while the
      popover is up does not crash gedit.
- [ ] **Capability gate** — opening a file type whose server doesn't
      advertise `codeActionProvider` shows no lightbulbs and the
      keybind reports "server does not support code actions" in the
      statusbar.

## Multi-window / multi-buffer

- [ ] Open the same file in two gedit windows. Check
      `pgrep -c pylsp` shows **1** (single shared process).
- [ ] Close the first window. Check `pgrep -c pylsp` still shows **1**
      (other window keeps it alive).
- [ ] Close all gedit windows. Check `pgrep -c pylsp` shows **0** within
      `serverIdleTimeoutSeconds` + a few seconds.

## Crash-loop circuit breaker

- [ ] Edit config to set `"servers": {"python": {"command": ["nonexistent_binary_xyz"]}}`.
- [ ] Restart gedit, open a Python file. After backoff exhausted, an
      info-bar appears on the tab with [Restart] [Open log] [Disable].
- [ ] Click **Open log** → opens `~/.local/state/gedit-lsp/plugin.log` in a new tab.

## Statusbar states

- [ ] Active tab is a Python file with running pylsp → `LSP: pylsp ⚡`.
- [ ] Active tab has no language server configured → blank.
- [ ] Open a 6 MB+ file → `LSP: skipped (large file)`.
- [ ] Open a file under `~/x/.venv/lib/...` → `LSP: skipped (path excluded)`.

## Toggling

- [ ] Toggle plugin off (Preferences → Plugins). All squiggles, marks,
      panels disappear. gedit doesn't crash.
- [ ] Toggle on → state restored.

## Final

- [ ] All boxes ticked.
- [ ] No errors in `~/.local/state/gedit-lsp/plugin.log`.
