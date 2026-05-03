# Roadmap

## v0.1.0-beta (post-alpha polish)

- Surface server stderr via a menu action (currently log-only).
- Evaluation/screenshot script (`tests/eval/screenshots.py`) for README + visual regression.
- Codify v1.0.0 readiness criteria.

## v0.2.0 — Editing intelligence

- `textDocument/completion` (+ `completionItem/resolve`) wired to
  `GtkSourceCompletionProvider`.
- `textDocument/signatureHelp`.
- Snippet support behind a per-language opt-in.

## v0.3.0 — Sync & infrastructure improvements

- Incremental document sync (`TextDocumentSyncKind.Incremental`).
- Mouse-hover trigger.
- `$/progress` server-reported indexing.
- `workspace/didChangeWatchedFiles`.

## v0.4.0 — Editing operations

- `textDocument/rename` + `prepareRename`.
- `textDocument/codeAction`.
- `textDocument/formatting`, `rangeFormatting`.
- `textDocument/references`.
- `workspace/symbol`.

## v1.0.0 — Stable

Criteria:

- Scope C (completion) shipped.
- ≥ 6 months on stable releases without regression-class bugs reported.
- At least one translation other than English shipped.

Beyond v1: Flatpak gedit support (requires sandbox handshake), system
install, GPG-signed releases.
