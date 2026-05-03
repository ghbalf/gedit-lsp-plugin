# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- (entries appear here as features land)

## [0.1.0-alpha.2] — 2026-05-04

### Added

- Per-severity diagnostic squiggle colors. New `severityUnderlineColor`
  tunable maps `error` / `warning` / `info` / `hint` to a CSS hex; set
  to `""` to fall back to the GTK theme's default (red wavy via
  `Pango.Underline.ERROR`). Defaults follow the GNOME palette.
- "Show Server Logs…" menu action and dialog. Right-click in the
  editor → LSP → Show Server Logs… opens a read-only TextView with the
  active document's language-server stderr (header shows state, root,
  command). Bindable via the new `show-server-logs` keybinding action
  (no default chord). Buffer size is bounded by the new
  `stderrBufferMaxLines` tunable (default 1000).
- Configurable keybindings for all LSP actions (`hover`,
  `goto-definition`, `go-back`, `show-server-logs`) plus a right-click
  "LSP" submenu for users who don't bind chords. The same submenu now
  shows the assigned accelerator next to each label.

### Fixed

- pylsp's plugin ecosystem (pylsp-mypy, pylsp-rope, …) now activates
  reliably. Plugin settings sent only through `initializationOptions`
  are *not* picked up by pylsp's per-plugin config layer; we now also
  push the same payload through `workspace/didChangeConfiguration`
  immediately after `initialized`. Without this, pylsp-mypy reported
  "Loaded plugin" but never ran mypy.
- Diagnostic squiggles are now visible on syntax errors at end of line.
  pyflakes (and others) report `invalid syntax` with end-character past
  the line's actual length; the LSP spec mandates clamping to line
  length, which produces a zero-width range at end-of-line. Widening
  forward put the tag on the trailing `\n`, which Pango can't render
  (no glyph). Now widens backward to cover the last visible character.
- Overlapping diagnostics of different severities now visibly reflect
  the most-severe finding. GTK 3.24 + Pango 1.50 on Ubuntu 24.04 does
  not resolve overlapping `underline-rgba` via tag priority despite
  what the docs say. Workaround: decompose ranges so each char is
  covered by exactly one `lsp-diag-*` tag, with severity ASC priority.
- Zero-width diagnostic ranges (e.g. pycodestyle `W292 no newline at
  end of file`) widen to one character so a squiggle is visible.
- The diagnostics panel clears rows for a buffer when its tab is
  closed, instead of waiting for the server to publish empty
  diagnostics (which most servers don't do for closed URIs).
- Documents are now bridged on Save-As and on language change, not
  only on file-open. Previously a buffer that gained a language
  identity after the path was set (or that switched type via the
  language menu) would never get an LSP attachment.
- Listener registrations on `LanguageServer` now return idempotent
  disposers; the plugin disposes its per-document listeners when the
  tab closes (and on plugin deactivate), so closures over the
  now-closed buffer no longer linger in the server's listener list.
- Server stderr is now drained from the kernel pipe. It was captured
  by the `STDERR_PIPE` flag but never read, so a sufficiently chatty
  server could have blocked on stderr writes once the pipe filled.

### Documentation

- New recipe in `docs/configure.md` for enabling pylsp-mypy as an
  Error-severity Python diagnostics source, with a caveat about how a
  project's own `pyproject.toml` mypy config (notably
  `ignore_missing_imports = true`) interacts with the auto-discovery
  behavior of pylsp-mypy.
- `docs/configure.md` documents the new `severityUnderlineColor`,
  `stderrBufferMaxLines`, and `show-server-logs` keybinding action.

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
