# LSP Protocol Coverage

| Method | Status |
|---|---|
| `initialize` / `initialized` / `shutdown` / `exit` | ✓ |
| `textDocument/didOpen` / `didChange` (Full **and** Incremental) / `didSave` / `didClose` | ✓ |
| `textDocument/publishDiagnostics` | ✓ |
| `textDocument/hover` | ✓ |
| `textDocument/definition` | ✓ |
| `textDocument/documentSymbol` | ✓ |
| `textDocument/completion` (proposals; Details pane via popup's Alt+D toggle) | ✓ |
| `completionItem/resolve` (rich-docs enrichment) | ✓ |
| `textDocument/signatureHelp` (popover above cursor; active param bolded) | ✓ |
| `textDocument/formatting` (Ctrl+Shift+I; whole document) | ✓ |
| `textDocument/rangeFormatting` (Ctrl+Shift+I with selection) | ✓ |

`textDocument/didChange` is auto-selected per server: if the server's
`textDocumentSync.change` advertises `Incremental` (2), the plugin sends
each insert/delete as a `TextDocumentContentChangeEvent` with a `range`;
otherwise it falls back to `Full`. Servers that omit `textDocumentSync`
entirely default to `Full` (matches VS Code's behavior — many older
servers expect didChange even when they forget to advertise sync).
