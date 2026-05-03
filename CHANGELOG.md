# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- (entries appear here as features land)

## [0.1.0-alpha.1] — 2026-05-03

### Fixed

- Plugin now activates on Ubuntu 24.04 + gedit 46. Three runtime API
  mismatches had prevented libpeas from loading the module:
  - `gi.require_version("Gedit", "46")` → `"3.0"` and
    `("GtkSource", "4")` → `"300"`. GObject-Introspection namespace
    versions are an ABI version, not the package version, and gedit 46
    on Ubuntu links the `libgedit-gtksourceview` fork (namespace
    `GtkSource-300`).
  - The side panel returned by `Gedit.Window.get_side_panel()` is a
    `TeplPanel` (interface from `libgedit-tepl`), not the
    `Gtk.Stack`-style `Gedit.Panel` that the bottom panel exposes.
    `OutlineController` now calls `Tepl.Panel.add(panel, ...)`
    explicitly to dispatch the interface vfunc instead of the
    inherited `Gtk.Container.add()`.
  - The Preferences "Edit user config" button no longer crashes when
    `~/.config/gedit/lsp-plugin.json` does not yet exist; it writes
    the current config first.

### Documentation

- `docs/install.md`: list `gir1.2-gtksource-300` (Ubuntu 24.04) and
  call out `python3-pyflakes` / `python3-pycodestyle` as required for
  Python diagnostics — apt's `python3-pylsp` does not pull the
  analyzers, so without them pylsp connects but publishes empty
  diagnostics.

### Tooling

- New `tests/unit/test_typelib_versions.py` statically asserts every
  `gi.require_version()` call in `src/` matches the gedit-46 runtime
  ABI, closing the visibility gap that allowed the original bugs to
  ship.
- `make test` and `make test-integration` strip `PYTHONPATH` so a
  system-wide `PYTHONPATH=/usr/lib/python3/dist-packages` cannot
  shadow the venv's pinned `pluggy` and break `pytest` 9.x at import.
- CI workflows install `gir1.2-gtksource-300` to match the runtime
  the plugin now targets.

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
