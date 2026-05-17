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

`textDocument/didChange` is auto-selected per server: if the server's
`textDocumentSync.change` advertises `Incremental` (2), the plugin sends
each insert/delete as a `TextDocumentContentChangeEvent` with a `range`;
otherwise it falls back to `Full`. Servers that omit `textDocumentSync`
entirely default to `Full` (matches VS Code's behavior — many older
servers expect didChange even when they forget to advertise sync).
