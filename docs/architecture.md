# Architecture

This document describes the current architecture of the gedit LSP
plugin. For the *design rationale*, see
`docs/superpowers/specs/2026-05-02-gedit-lsp-plugin-design.md`. For new
component additions or significant changes, update both this file and
the spec; this file remains authoritative for what the code looks like
now.

## Component map

```
GeditLspPlugin (per gedit window)
    ├── Config          (process global, watches user JSON)
    ├── ServerRegistry  (process global, dict[(lang, root)] → LanguageServer)
    │       └── LanguageServer
    │               └── RpcClient → Gio.Subprocess (one per language server)
    ├── DocumentBridge  (one per Gedit.Document)
    └── FeatureControllers (one of each per Gedit.Document)
            ├── DiagnosticsController
            ├── HoverController
            ├── DefinitionController
            └── OutlineController
```

- **Config** — loads `~/.config/gedit/lsp-plugin.json` and merges with
  built-in defaults. Exposes `server_for(lang_id)`,
  `root_markers_for(lang_id)`, `initialization_options_for(lang_id)`,
  and `tunable(key)`. Reload triggers any registered observer callbacks.
- **ServerRegistry** — keyed by `(language_id, project_root_path)`,
  lazily creating one `LanguageServer` per key. Two buffers in the same
  project share a server; two projects get distinct ones.
- **LanguageServer** — owns the state machine, the per-server idle
  timer, and the diagnostics-listener fan-out. Transport-agnostic: a
  `transport_factory` callable produces an `RpcClient` (production) or a
  fake (tests).
- **RpcClient** — `Gio.Subprocess` async I/O. `Gio.DataInputStream`
  reads CR_LF-delimited header lines; `read_bytes_async` reads bodies.
  Writes are FIFO-serialized.
- **DocumentBridge** — one per `Gedit.Document`. Owns the version
  counter, the debounce timer, and the four `textDocument/*`
  notifications. Speaks to `LanguageServer.send_notification`.
- **FeatureControllers** — `DiagnosticsController`,
  `HoverController`, `DefinitionController`, `OutlineController`. Each
  handles one LSP method and renders the result. Pure modules where
  possible (UTF-16 conversion is in `utf16.py`, response classification
  is per-feature module).

## Data flow

```
gedit signals → DocumentBridge → LanguageServer → RpcClient → subprocess
                                                ← RpcClient ←
                ← FeatureControllers ←
```

## Threading model

Single-threaded GLib main loop. All async I/O via `Gio.DataInputStream` /
`Gio.OutputStream` async methods. No `asyncio`, no Python threads.
