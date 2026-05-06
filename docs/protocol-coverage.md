# LSP Protocol Coverage

| Method | v0.1.0-alpha |
|---|---|
| `initialize` / `initialized` / `shutdown` / `exit` | ✓ |
| `textDocument/didOpen` / `didChange` (Full) / `didSave` / `didClose` | ✓ |
| `textDocument/publishDiagnostics` | ✓ |
| `textDocument/hover` | ✓ |
| `textDocument/definition` | ✓ |
| `textDocument/documentSymbol` | ✓ |
| `textDocument/completion` (proposals; Details pane via popup's Alt+D toggle) | ✓ |
| `completionItem/resolve` (rich-docs enrichment) | 🚧 |
| `textDocument/signatureHelp` (popover above cursor; active param bolded) | ✓ |
