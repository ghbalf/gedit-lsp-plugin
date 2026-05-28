# LSP Protocol Coverage

| Method | Status |
|---|---|
| `initialize` / `initialized` / `shutdown` / `exit` | ✓ |
| `textDocument/didOpen` / `didChange` (Full **and** Incremental) / `didSave` / `didClose` | ✓ |
| `textDocument/publishDiagnostics` | ✓ |
| `textDocument/hover` (Ctrl+K **and** pointer-dwell over a token) | ✓ |
| `textDocument/definition` | ✓ |
| `textDocument/documentSymbol` | ✓ |
| `textDocument/completion` (proposals; Details pane via popup's Alt+D toggle) | ✓ |
| `completionItem/resolve` (rich-docs enrichment) | ✓ |
| `textDocument/signatureHelp` (popover above cursor; active param bolded) | ✓ |
| `textDocument/formatting` (Ctrl+Shift+I; whole document) | ✓ |
| `textDocument/rangeFormatting` (Ctrl+Shift+I with selection) | ✓ |
| `textDocument/references` (Shift+F4; many → "LSP References" bottom panel) | ✓ |
| `textDocument/rename` (F2; popover at cursor; multi-file apply, closed files opened as tabs) | ✓ |
| `textDocument/prepareRename` (gates rename when server advertises it) | ✓ |
| `textDocument/codeAction` (Shift+F2; lightbulb in gutter on diagnostic lines; popover picker; edit + command apply) | ✓ |
| `codeAction/resolve` (sent on commit when the chosen action has neither `edit` nor `command`) | ✓ |
| `workspace/executeCommand` (sent for actions carrying a `command`) | ✓ |
| `workspace/symbol` (Shift+F3; live quick-pick, server-side filtered, debounced) | ✓ |
| `workspaceSymbol/resolve` (sent on activation when the chosen symbol has no `location.range` and the server advertises `resolveProvider`) | ✓ |
| `$/progress` (work-done; server-initiated, shown in statusbar) | ✓ |
| `window/workDoneProgress/create` (server→client; acked `null`) | ✓ |

`textDocument/didChange` is auto-selected per server: if the server's
`textDocumentSync.change` advertises `Incremental` (2), the plugin sends
each insert/delete as a `TextDocumentContentChangeEvent` with a `range`;
otherwise it falls back to `Full`. Servers that omit `textDocumentSync`
entirely default to `Full` (matches VS Code's behavior — many older
servers expect didChange even when they forget to advertise sync).

`workspace/symbol` support is **server- and version-dependent**. The
plugin gates on the server's advertised `workspaceSymbolProvider`; when
it is absent, `Shift+F3` shows `LSP: server does not support workspace
symbol search` and no quick-pick (correct, by design). Notably the
common Debian/Ubuntu `python3-pylsp` (python-lsp-server, verified
1.10.0) does **not** implement `workspace/symbol`, so on the default
Python setup this feature is inert — use a server that advertises the
capability (e.g. `clangd`, verified 18.1.3 = supported) or a
newer/alternative Python language server that implements it. This is a
server limitation, not a plugin limitation; `textDocument/documentSymbol`
(the file-local *outline*) is unaffected and works on pylsp.

`$/progress` covers **server-initiated** work-done progress (e.g. clangd
indexing). The plugin advertises `window.workDoneProgress` in `initialize`,
acks the server's `window/workDoneProgress/create` request, and shows the
active token's title/percentage in the statusbar, appended to the server
state (`LSP: clangd ⚡ · indexing… 45%`). Progress on the plugin's own
requests (a client-supplied `workDoneToken`) and cancellation are not
implemented. Like `workspace/symbol`, emission is server-dependent: a
server that never sends `$/progress` simply shows the plain state glyph.
