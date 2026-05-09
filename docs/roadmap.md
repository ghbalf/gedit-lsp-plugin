# Roadmap

## Shipped

- **v0.1.0-alpha.2 (2026-05-04):** Surface server stderr via a menu action
  ("Show Server Logs…").
- **v0.2.0 (2026-05-06):** `textDocument/completion` wired to
  `GtkSourceCompletionProvider`.
- **v0.3.0 (2026-05-06):** Completion Details pane (revealed via the
  popup's `Alt+D` toggle) with `completionItem/resolve` enrichment.

## v0.1.0-beta (post-alpha polish)

- Evaluation/screenshot script (`tests/eval/screenshots.py`) for README + visual regression.
- Codify v1.0.0 readiness criteria.

## v0.2.0 — Editing intelligence (in progress)

- `textDocument/signatureHelp` — popover above the cursor on `(` / `,` with
  the active parameter bolded; Escape and empty server response dismiss.
- Snippet support behind a per-language opt-in.

## v0.4.0 — Sync, infrastructure, and editing operations

Sync & infrastructure (deferred from the original v0.3.0 plan so they
aren't lost):

- Incremental document sync (`TextDocumentSyncKind.Incremental`).
- Mouse-hover trigger.
- `$/progress` server-reported indexing.
- `workspace/didChangeWatchedFiles`.

Editing operations:

- `textDocument/rename` + `prepareRename`.
- `textDocument/codeAction`.
- `textDocument/formatting`, `rangeFormatting`.
- `textDocument/references`.
- `workspace/symbol`.

Testing infrastructure (housekeeping; benefits multiple features
above):

- Multi-file integration test fixture. Current integration fixtures
  are single-file; references / rename / `workspace/symbol` need
  cross-file fixtures to exercise their core value. Build once, reuse
  across feature PRs.

## v1.0.0 — Stable

Criteria:

- Scope C (completion) shipped.
- ≥ 6 months on stable releases without regression-class bugs reported.
- At least one translation other than English shipped.

Beyond v1: Flatpak gedit support (requires sandbox handshake), system
install, GPG-signed releases.
