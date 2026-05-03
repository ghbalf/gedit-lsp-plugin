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

## Outline

- [ ] Open `tests/fixtures/projects/python_outline/sample.py`. Within
      2 s, the *LSP Outline* side panel shows `Greeter > hello, goodbye`.
- [ ] Click `goodbye` in the panel → cursor jumps to the method.

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
