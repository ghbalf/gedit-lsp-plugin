# Troubleshooting

## Decision tree

### Plugin doesn't appear in Edit → Preferences → Plugins

- Check `~/.local/share/gedit/plugins/` contains both `gedit_lsp/` and `gedit-lsp.plugin`.
- Check the manifest's `Loader=python3` line is present (`cat ~/.local/share/gedit/plugins/gedit-lsp.plugin`).
- Check the log: `tail ~/.local/state/gedit-lsp/plugin.log` — Python import errors land here.
- Are you running gedit from Flatpak? It can't run host binaries; use the distro package.

### Plugin loads but no diagnostics appear

1. Check the language server is installed: `which pylsp` (or whichever).
2. Check `~/.local/state/gedit-lsp/plugin.log` for "spawn failed" messages.
3. Enable the traffic log: edit `~/.config/gedit/lsp-plugin.json`:
   ```json
   { "tunables": { "logLspTraffic": true } }
   ```
   Restart gedit, reopen the file. `~/.local/state/gedit-lsp/lsp-traffic.log` should now show:
   - `>>> ... initialize`
   - `<<< ... result for initialize`
   - `>>> ... textDocument/didOpen`
   - `<<< ... textDocument/publishDiagnostics`
4. If `publishDiagnostics` never arrives, the issue is server-side. Run the server manually to see its stderr:
   ```bash
   pylsp --check-parent-process < /dev/null
   ```

### Statusbar shows "⚠ exited" or "✗ disabled"

The server crashed N times in a row and the circuit breaker tripped.
Click the statusbar label → **Restart**, or check `plugin.log` for the
exit reason.

### Hover popover never appears

- Cursor must be on a symbol the server recognizes.
- Some servers (e.g. clangd) need a `compile_commands.json` for hover to work.
- Check the traffic log for `<<<` response to `textDocument/hover`.

### Diagnostics line numbers are wrong

This indicates a UTF-16 conversion bug — the highest-risk module in the
plugin. Please file a bug report with:
- The exact file content (or a minimal reproduction)
- The exact diagnostic that's misplaced
- The plugin and traffic logs

### "skipped (large file)" in statusbar

The buffer is over `maxFileSizeBytes` (default 5 MB). Increase it in your
config:
```json
{ "tunables": { "maxFileSizeBytes": 20000000 } }
```

### "skipped (path excluded)" in statusbar

The buffer's path matches a `disabledForPaths` glob (default excludes
`.venv`, `node_modules`, etc.). Edit the list in your config.
