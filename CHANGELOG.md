# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- (entries appear here as features land)

## [0.1.0-alpha] — 2026-05-03

### Added

- Initial alpha release of the gedit LSP plugin.
- Diagnostics: squiggles via `Gtk.TextTag`, gutter marks, bottom panel listing.
- Hover: Ctrl+K shows a popover with `textDocument/hover` content.
- Go-to-Definition: Ctrl+. with cursor history (Alt+Left to return).
- Document outline: side panel populated from `textDocument/documentSymbol`.
- Single JSON config file at `~/.config/gedit/lsp-plugin.json`, with hot-reload.
- Built-in defaults for Python (pylsp), C/C++ (clangd), Rust, Go, TS/JS, Bash.
- Per-(language, project root) server lifecycle with idle-kill timer.
- Crash-loop circuit breaker with info-bar UI.
- Statusbar indicator with 8 distinct states.
- File-size cap and persistent ignore-list (`disabledForPaths`).
- Two log streams (plugin + opt-in LSP traffic) with rotation.
- Internationalisation infrastructure (English-only at alpha).
- MIT-licensed source with documented MIT/GPL runtime distinction.

### Tooling

- Unit + integration test suites in CI.
- `doc-gate` CI check requiring documentation updates with feature changes.
- Tag-triggered GitHub Release workflow with SHA-256 checksums.
