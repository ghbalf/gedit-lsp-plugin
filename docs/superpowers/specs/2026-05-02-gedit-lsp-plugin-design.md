# gedit LSP Plugin — Design Specification

| | |
|---|---|
| **Date** | 2026-05-02 |
| **Author** | Alfred Mickautsch |
| **Status** | Draft (awaiting written-spec review) |
| **Target version** | v0.1.0-alpha |
| **Implementation language** | Python 3.10+ |
| **Host application** | gedit ≥ 46 (libpeas-1.0, GtkSourceView-4) |
| **License (plugin source)** | MIT |

## 1. Summary

A gedit plugin that adds a Language Server Protocol (LSP) client, providing
read-only intelligence features — diagnostics, hover, go-to-definition, and a
document outline — for any language whose server the user configures. Ships
with built-in defaults for Python, C/C++, Rust, Go, TypeScript/JavaScript, and
Bash. All settings are user-configurable via a single JSON file and a small
preferences dialog.

## 2. Goals & Non-Goals

### Goals

- Diagnostics, hover (Ctrl+K), go-to-definition (Ctrl+.) with cursor history,
  and a document-outline side panel — usable for daily work.
- Multi-language, multi-project support: one server process per
  `(language, project root)` pair, shared across buffers and gedit windows.
- Zero-configuration for common languages whose server binaries are on `$PATH`.
- Single JSON config file as the authoritative source for every tunable
  value; no GSettings, no schema-compilation step.
- Robust document-sync invariant: the server's view of every open document
  must match the buffer's view at every moment any feature dispatches a
  request.
- All user-visible strings translatable via `gettext`.
- Detailed end-user documentation: install, configure, uninstall,
  troubleshoot.
- A reproducible alpha release on GitHub with a tarball artifact.

### Non-Goals (deferred to v0.2.0+)

- Editing-side intelligence: completion, signature help, code actions,
  rename, formatting, references, workspace symbols.
- Incremental document sync (`TextDocumentSyncKind.Incremental`).
- Mouse-hover trigger (only Ctrl+K invokes hover in v1).
- Per-project config files in the project tree (security: only the user's
  config is read).
- File-watcher notifications (`workspace/didChangeWatchedFiles`).
- Server-reported indexing progress (`$/progress`).
- Sandboxed/Flatpak gedit support.

## 3. Architecture

The plugin is a Python module loaded by libpeas-1.0, decomposed into seven
units with narrow responsibilities. All inter-component communication is via
Python objects and GObject signals — no shared mutable state outside the
`ServerRegistry` singleton.

```
┌──────────────────────────────────────────────────────────────────┐
│  GeditLspPlugin (libpeas entry point — WindowActivatable)        │
│   • activate/deactivate per gedit window                         │
│   • wires components together; owns the ServerRegistry singleton │
└──────────────────────────────────────────────────────────────────┘
            │
   ┌────────┴────────────────────────────────────────┐
   │                                                 │
   ▼                                                 ▼
┌───────────────────────┐                  ┌─────────────────────────┐
│  Config               │                  │  ServerRegistry         │
│ • loads built-in      │                  │ • dict[(lang, root)] →  │
│   defaults table      │                  │   LanguageServer        │
│ • merges user JSON    │                  │ • idle-kill timer       │
│   (~/.config/...)     │                  │ • spawn / shutdown      │
│ • watches file for    │                  │   lifecycle             │
│   changes (GFileMon)  │                  └────────┬────────────────┘
└───────────────────────┘                           │
                                                    ▼
                              ┌─────────────────────────────────────┐
                              │  LanguageServer                     │
                              │ • owns one GSubprocess              │
                              │ • RpcClient (JSON-RPC framing)      │
                              │ • emits ::diagnostics, ::ready,     │
                              │   ::exited via GObject signals      │
                              └────────┬────────────────────────────┘
                                       │
                                       ▼
                              ┌─────────────────────────────────────┐
                              │  RpcClient                          │
                              │ • Content-Length framing on stdin/  │
                              │   stdout via Gio.DataInputStream    │
                              │ • request → Future-like callback    │
                              │ • notification dispatch             │
                              └─────────────────────────────────────┘

   ┌───────────────────────┐    ┌────────────────────────┐
   │  DocumentBridge       │    │  ProjectRootResolver   │
   │ (1 per GeditDocument) │    │ • walk g_file_get_     │
   │ • didOpen on attach   │    │   parent() looking for │
   │ • didChange on buffer │    │   .git, pyproject.toml,│
   │   modify (debounced)  │    │   Cargo.toml, …        │
   │ • didSave / didClose  │    │ • fallback: file's dir │
   │ • routes responses to │    └────────────────────────┘
   │   FeatureControllers  │
   └───────────┬───────────┘
               │
               ▼
   ┌─────────────────────────────────────────────────────┐
   │  FeatureControllers (one per feature, per buffer)   │
   │  • DiagnosticsController (renders squiggles + marks)│
   │  • HoverController       (action + popover)         │
   │  • DefinitionController  (action + tab open/jump)   │
   │  • OutlineController     (side panel TreeView)      │
   └─────────────────────────────────────────────────────┘
```

### 3.1 Plugin entry point

`GeditLspPlugin` implements `Gedit.WindowActivatable`, instantiated once per
gedit window. The `ServerRegistry` is a process-global singleton — buffers
opened in any window route to the same server pool.

### 3.2 Why GObject signals (not Python callbacks)

`WindowActivatable` plugins can be deactivated mid-session (user toggles the
plugin off, closes the window). GObject signal connections are tracked by
gedit and torn down cleanly on deactivate; bare Python callbacks aren't, and
the resulting reference leaks become "why does gedit crash on quit" later.

### 3.3 Why GLib async (not asyncio or threads)

`GtkTextBuffer` is not thread-safe, and gedit's GLib main loop is the single
source of truth for UI events. GLib async I/O (`Gio.DataInputStream`,
`Gio.OutputStream.write_bytes_async`) runs on the main loop concurrently
without parallelism, which is the correct concurrency model for this plugin.

## 4. Configuration

### 4.1 Single JSON config file

All settings live in one file:

```
$XDG_CONFIG_HOME/gedit/lsp-plugin.json
(default: ~/.config/gedit/lsp-plugin.json)
```

The plugin watches it via `Gio.FileMonitor` and reloads on change. Reload
affects new server spawns only; running servers are not restarted
mid-session.

### 4.2 Built-in defaults table

Hardcoded in `defaults.py`. Keys are `GtkSourceLanguage` IDs.

```python
BUILTIN_SERVERS = {
    "python":     {"command": ["pylsp"]},
    "c":          {"command": ["clangd", "--background-index"]},
    "cpp":        {"command": ["clangd", "--background-index"]},
    "rust":       {"command": ["rust-analyzer"]},
    "go":         {"command": ["gopls"]},
    "typescript": {"command": ["typescript-language-server", "--stdio"]},
    "js":         {"command": ["typescript-language-server", "--stdio"]},
    "sh":         {"command": ["bash-language-server", "start"]},
}
```

On startup the plugin checks each command's existence with `shutil.which()`
and silently disables entries whose binary is missing.

### 4.3 User overrides

User entries fully replace built-in entries for the same language ID — no
per-key merging. Missing keys fall through to defaults.

```json
{
  "servers": {
    "python":  { "command": ["pyright-langserver", "--stdio"] },
    "haskell": { "command": ["haskell-language-server-wrapper", "--lsp"] }
  },
  "rootMarkers": {
    "python": ["pyproject.toml", "setup.py", "requirements.txt", ".git"],
    "c":      ["compile_commands.json", "Makefile", ".git"]
  },
  "initializationOptions": {
    "python": { "pylsp": { "plugins": { "pycodestyle": { "enabled": false } } } }
  },
  "tunables": { /* see Appendix A */ }
}
```

### 4.4 Project-root resolution

Compiled-in default marker list (overridable per-language via
`rootMarkers`):

```
.git, .hg, .svn,                       # VCS roots (any language)
pyproject.toml, setup.py, Pipfile,     # Python
Cargo.toml,                            # Rust
go.mod,                                # Go
package.json,                          # JS/TS
compile_commands.json, CMakeLists.txt, # C/C++
Makefile                               # generic
```

Walk algorithm: start at `g_file_get_parent(buffer.location)`, check each
marker, ascend, stop at `$HOME` or filesystem root. If nothing found, root =
the buffer's parent directory. Symlinks are resolved before keying so the
same physical file always resolves to the same `(lang, root)` pair.

### 4.5 Tunables surfaced in the preferences dialog

The preferences dialog (Preferences → Plugins → LSP → Configure) exposes a
small subset for non-JSON users:

- *Idle timeout* (slider 1–60 minutes)
- *Show statusbar indicator* (toggle)
- *Log LSP traffic* (toggle)
- *Maximum file size* (number)
- *Enabled features* (checkbox group: diagnostics, hover, definition,
  outline)

Plus two action buttons: *Edit user config…* (opens `lsp-plugin.json` in
gedit) and *Reveal in Files…* (opens the parent dir in the file manager).

The full set of tunables is in **Appendix A**; everything beyond the dialog
is JSON-only.

## 5. Server Lifecycle

```
                     ┌──────────────────────────┐
                     │       NOT_RUNNING        │
                     └─────────────┬────────────┘
                                   │ first DocumentBridge
                                   │ for (lang, root) attaches
                                   ▼
                     ┌──────────────────────────┐
                     │       STARTING           │  ← spawn GSubprocess,
                     │ (initialize in flight)   │     send "initialize"
                     └─────────────┬────────────┘
                                   │ initialize response
                                   ▼
                     ┌──────────────────────────┐
                     │         READY            │ ← serve documents
                     │  (N≥1 active buffers)    │
                     └────┬─────────────────────┘
              last buffer │             ▲
                  detaches│             │ new buffer attaches
                          ▼             │
                     ┌──────────────────┴───────┐
                     │         IDLE             │ ← idle timer running,
                     │   (server still alive,   │   server kept warm
                     │   no active buffers)     │
                     └─────────────┬────────────┘
                                   │ timer fires
                                   ▼
                     ┌──────────────────────────┐
                     │        STOPPING          │ ← send "shutdown",
                     │                          │   then "exit"
                     └─────────────┬────────────┘
                                   ▼
                            NOT_RUNNING
```

### 5.1 Idle policy

When the last buffer for a `(language, root)` pair detaches, the server
moves to IDLE and a timer is started for `serverIdleTimeoutSeconds` seconds
(default 300). If the timer expires, send `shutdown` then `exit`. If a new
buffer attaches before the timer fires, the timer is cancelled and the
server returns to READY.

### 5.2 Crash recovery

If `GSubprocess` exits while in READY or IDLE, mark NOT_RUNNING and notify
all attached `DocumentBridge`s. Auto-restart on next buffer attach with
exponential backoff (`restartBackoffSchedule`, default
`[1, 2, 4, 8, 16, 30]` seconds). After `restartMaxAttempts` consecutive
failures (default 5), give up for that `(lang, root)` until either the user
edits the config or invokes the *Restart* action from the statusbar.

### 5.3 Crash-loop circuit breaker UI

Once the backoff is exhausted, a `Gtk.InfoBar` is added to every
`Gedit.Tab` whose buffer is bound to the failed `(lang, root)` pair, via
`Gedit.Tab.set_info_bar()`. Message: *"LSP for {lang} ({root}) has failed
{restartMaxAttempts} times. [Restart] [Open log] [Disable for session]"*.
The info-bar is removed on a successful restart or when the user
dismisses it. Without it, "diagnostics stopped working" becomes
impossible to triage from the user's side.

### 5.4 Save-As across roots

When a buffer's `GFile` location changes, recompute `(lang, root)`. If
different from current, treat as `didClose` on the old server +
`didOpen` on the new server. This is the only buffer-rerouting edge case.

## 6. UI Integration

Each LSP feature has one `FeatureController` per buffer. Controllers attach
when a `DocumentBridge` is created and detach when the buffer is closed.

### 6.1 Diagnostics

**Squiggle in buffer text.** One `Gtk.TextTag` per severity in the buffer's
tag table: `lsp-diag-error`, `lsp-diag-warning`, `lsp-diag-info`,
`lsp-diag-hint`. Each tag sets `underline = Pango.Underline.ERROR_LINE`
(or `SINGLE` for hints) plus an `underline-rgba` colour from the current
GtkSourceView style scheme. On `publishDiagnostics`:

1. Remove all `lsp-diag-*` tags from the buffer.
2. For each diagnostic, convert `Range` (LSP UTF-16) → `Gtk.TextIter` via
   the converter (Section 7.4).
3. Apply the tag for that severity.

**Gutter marks.** One `GtkSourceMark` per diagnostic, severity-distinct
icon (`severityIcons` config: defaults `dialog-error-symbolic` etc.).
Tooltip on the gutter shows the diagnostic message.

**Bottom panel — "LSP Diagnostics".** Registered via
`Gedit.Window.get_bottom_panel().add_titled()`, contains a `Gtk.TreeView`
with columns *Severity / Line / Message / Source*. Lists diagnostics across
all open buffers in the window. Double-click → focus the buffer's tab and
move cursor to the diagnostic's start position.

### 6.2 Hover

App action `win.lsp-hover` bound to **Ctrl+K**. On invoke:

1. Read cursor position; send `textDocument/hover`.
2. Show a `Gtk.Popover` after `hoverSpinnerThresholdMs` (default 300)
   with a small spinner if the response hasn't arrived.
3. Render: `Gtk.Popover` anchored at the cursor's screen rect
   (`gtk_text_view_get_iter_location` + `buffer_to_window_coords`), inner
   widget is a read-only `GtkSourceView` showing the markdown content as
   plain text, with triple-backtick code blocks given a monospace tag.
4. Closes on Escape, focus loss, or cursor move.

Mouse-hover trigger is out of scope for v1; deferred to v0.2.

### 6.3 Go to Definition

App action `win.lsp-goto-definition` bound to **Ctrl+.** (period). On
invoke: send `textDocument/definition`, expect 0/1/N `Location`s.

- **0** → status-bar message *"No definition found"*.
- **1** → if same file, move cursor; if different file,
  `Gedit.Window.create_tab_from_location()` and on the tab's `loaded`
  signal, scroll to the line.
- **N** → small `Gtk.Popover` listing each location (path:line:col +
  one-line preview, fetched lazily); selecting a row opens it.

**Cursor history.** Per-window stack (max `gotoHistoryMaxEntries` = 50)
of `(file, line, column)` tuples pushed on every Go-to-Definition. App
action `win.lsp-go-back` bound to **Alt+Left** pops it.

### 6.4 Outline (Document Symbols)

Side panel **"LSP Outline"** registered on
`Gedit.Window.get_side_panel()`. Tree view of `DocumentSymbol` hierarchy
returned by `textDocument/documentSymbol`. Refreshed:

- Once on initial document open after `outlineInitialDelayMs` (default
  1000).
- On `didSave`.
- On a `outlineRefreshDebounceMs` (default 2000) post-edit debounce.

Click a row → move cursor to the symbol's `selectionRange.start`. Cursor
tracks the buffer; the closest enclosing symbol is highlighted in the
tree on cursor move.

Falls back to `SymbolInformation[]` (older flat protocol) if the server
replies in that form (detected by the presence of a `location` key on
each item).

### 6.5 Statusbar indicator

`Gtk.Label` appended to gedit's statusbar showing the current buffer's
LSP state:

- `"LSP: pylsp ⚡"` (READY)
- `"LSP: pylsp …"` (STARTING — pulsing dot)
- `"LSP: pylsp ⚠ exited"` (crashed; backoff in progress)
- `"LSP: pylsp ✗ disabled"` (crash-loop circuit breaker tripped)
- `"LSP: skipped (large file)"` (over `maxFileSizeBytes` — Section 6.7)
- `"LSP: skipped (path excluded)"` (matched `disabledForPaths` — Section 6.8)
- `"LSP: disabled for buffer"` (per-buffer disable — Section 6.6)
- *(blank)* — no server configured for this language

Click → small popover with **Restart** and **Open log…** buttons.

Hidden if `showStatusbarIndicator` is `false`.

### 6.6 Per-buffer disable

Menu item **LSP → Disable for this buffer** toggles a buffer-local flag,
sends `didClose` to the server, removes squiggles/marks. Survives the
buffer's lifetime; lost on buffer close (no per-path persistence).

### 6.7 File-size cap

If `g_file_query_info` reports a size larger than `maxFileSizeBytes`
(default 5 242 880), the plugin does not attach a `DocumentBridge`.
Statusbar shows the *"skipped (large file)"* state. Reason: pylsp,
clangd, and other servers degrade or hang on multi-MB files.

### 6.8 Persistent ignore-list

A `disabledForPaths` config key (list of glob patterns, default
`["**/.venv/**", "**/node_modules/**", "**/.tox/**", "**/dist/**", "**/build/**"]`)
matched against the buffer's absolute path. Matching buffers are skipped
(same UI state as the file-size cap).

### 6.9 Preferences dialog

Triggered from gedit's Preferences → Plugins → LSP → Configure.
Implementation reads/writes the same JSON config file (no GSettings).
Layout:

- Group *General*: idle timeout slider, statusbar toggle, traffic-log
  toggle, max-file-size number, enabled-features checkbox group.
- Group *Config file*: file path label, *Edit in gedit*, *Reveal in
  Files*.
- Footer: *"Advanced settings — see ~/.config/gedit/lsp-plugin.json"*.

## 7. Document Sync, JSON-RPC, and the UTF-16 Hazard

This section is where 80% of LSP-client bugs hide. The invariant: **the
server's view of every open document must match the buffer's view,
character-for-character, at every moment any feature dispatches a
request.**

### 7.1 JSON-RPC transport

`RpcClient` owns one `Gio.Subprocess`
(`STDIN_PIPE | STDOUT_PIPE | STDERR_PIPE`, no shell). Reads stdout via
`Gio.DataInputStream`. Frame format: LSP `Content-Length: N\r\n\r\n`
header + N bytes of UTF-8 JSON. Read loop:

```
read_line_async()                → parse "Content-Length: N"
read_line_async() until empty    → consume remaining headers
read_bytes_async(N)              → one full JSON message
dispatch + recurse
```

Stderr is piped to the LSP traffic log (when enabled) or `/dev/null` (when
not).

Outgoing messages are serialized with
`json.dumps(..., ensure_ascii=False).encode("utf-8")`, prefixed with the
header, written via `Gio.OutputStream.write_bytes_async`. Writes are FIFO-
serialized — never multiple in-flight `write_bytes_async` on the same
stream, since GIO doesn't guarantee ordering across overlapping writes.

Pending requests live in `dict[int, RequestSlot]` keyed by JSON-RPC `id`,
where `RequestSlot` holds (1) a callback, (2) a timeout source
(`requestTimeoutMs` default 10000, cancelled on response), and (3) a
cancellable for buffer-dependent requests.

### 7.2 Cancellation

A request is cancellable if its result depends on the buffer staying
still: `hover`, `definition`, `documentSymbol`. When the buffer changes,
the controller calls `RpcClient.cancel(request_id)`, which sends
`$/cancelRequest` and removes the slot. Late responses for cancelled
requests are silently dropped. Cancellation is local; the server-side
effect is advisory.

### 7.3 Document sync events

| Event in gedit | Wire message |
|---|---|
| `Gedit.Tab.loaded` first time | `textDocument/didOpen` (full text, version=1) |
| `GtkTextBuffer.changed` | (debounced `changeDebounceMs` ms) `textDocument/didChange` (full text, version+=1) |
| `Gedit.Document.saved` | `textDocument/didSave` *if server requested it via the `save: true` capability* |
| Buffer closed / Save-As across roots | `textDocument/didClose` |

We use **`TextDocumentSyncKind.Full`** (re-send the whole buffer on every
change), not Incremental.

**Why Full.** Incremental requires sending `Range` deltas, which means
translating every `GtkTextBuffer` `insert-text` / `delete-range` signal
pair into LSP positions. Those signals fire mid-edit and don't always
pair up cleanly (paste-over-selection emits delete-then-insert; line-break
emits a single insert with `\n`). Getting Incremental wrong corrupts the
server's view permanently — the only symptom is "diagnostics line
numbers are off" much later. Full is 5× the bandwidth (negligible for
files under 100 KB which is gedit's wheelhouse), zero invariant risk.
Revisit Incremental in v0.3+ once an integration test harness is mature.

The `changeDebounceMs` default (150) keeps `didChange` traffic to one
message per typing burst rather than one per keystroke. The version
counter increments per message sent (not per keystroke), so the server
sees a strictly monotonic version.

### 7.4 The UTF-16 hazard

LSP positions are `(line, character)` pairs where `character` is the
**UTF-16 code-unit offset within the line**, not a byte offset and not a
codepoint offset. `GtkTextBuffer` works in UTF-8 internally and exposes
line/byte and line/character (codepoint) APIs but never UTF-16. Conversion
is necessary on every boundary.

Example: line `"héllo 🐍 world"`, position of `'w'`:

| Encoding | Offset |
|---|---|
| UTF-8 byte | 12 |
| Codepoint (Python `str`, `Gtk.TextIter`) | 9 |
| **UTF-16 code-unit (LSP `character`)** | **10** |

Isolated in `utf16.py`:

```python
def utf16_to_text_iter(buffer, line: int, char_utf16: int) -> Gtk.TextIter:
    """LSP (line, character) → Gtk.TextIter."""
    line_iter = buffer.get_iter_at_line(line)
    line_text = buffer.get_text(line_iter, _line_end(line_iter), False)
    units = 0
    cp_offset = 0
    for ch in line_text:
        if units >= char_utf16:
            break
        units += 1 if ord(ch) < 0x10000 else 2
        cp_offset += 1
    return buffer.get_iter_at_line_offset(line, cp_offset)


def text_iter_to_utf16(it: Gtk.TextIter) -> tuple[int, int]:
    """Gtk.TextIter → LSP (line, character)."""
    line = it.get_line()
    line_start = it.get_buffer().get_iter_at_line(line)
    line_text = it.get_buffer().get_text(line_start, it, False)
    units = sum(1 if ord(ch) < 0x10000 else 2 for ch in line_text)
    return line, units
```

Every controller goes through these two functions — never anything else.
This is the single highest-risk function in the plugin and is exercised
with property-based tests (Section 11.1).

### 7.5 `initialize` capabilities advertised

```json
{
  "textDocument": {
    "synchronization": { "didSave": true, "willSave": false, "willSaveWaitUntil": false },
    "publishDiagnostics": { "relatedInformation": false, "versionSupport": true },
    "hover":            { "contentFormat": ["markdown", "plaintext"] },
    "definition":       { "linkSupport": false },
    "documentSymbol":   { "hierarchicalDocumentSymbolSupport": true }
  },
  "general":  { "positionEncodings": ["utf-16"] },
  "workspace": { "workspaceFolders": false, "configuration": false }
}
```

`positionEncodings: ["utf-16"]` is declared explicitly to prevent any
future server from choosing UTF-8 and breaking the converter.

### 7.6 Deliberately not implemented

- `workspace/configuration` pull. Static `initializationOptions` only.
- `workspace/didChangeWatchedFiles`. Would require a project-tree
  `Gio.FileMonitor`. v0.2.
- `window/showMessage`, `window/logMessage`. Routed to the log file
  only; no toast popups.
- `$/progress`. v0.2.
- Snippet support in any feature.

## 8. Logging

Two streams:

| Stream | Path | Always on? | Rotated? |
|---|---|---|---|
| Plugin diagnostic log | `$XDG_STATE_HOME/gedit-lsp/plugin.log` | yes (`logLevel`-gated, default `info`) | yes |
| LSP traffic log | `$XDG_STATE_HOME/gedit-lsp/lsp-traffic.log` | only if `logLspTraffic: true` | yes |

(`$XDG_STATE_HOME` defaults to `~/.local/state/`.)

Rotation: `logRotationMaxBytes` (default 5 242 880) per file,
`logRotationKeepFiles` (default 3) historical copies kept. Implemented
with `logging.handlers.RotatingFileHandler` for the plugin log; a small
custom rotator for the traffic log (which is line-streamed, not
record-formatted).

**Plugin-log format.** Standard Python `logging` records:

```
2026-05-02 14:23:01.234 INFO  registry: spawning server for ('python', '/home/alf/proj') → pylsp
```

**Traffic-log format.** One line per JSON-RPC message, with direction
arrow, monotonic millisecond timestamp, and the message itself
(compact JSON, no pretty-printing — line size matters more than
readability):

```
>>> 0001234.567 {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
<<< 0001234.612 {"jsonrpc":"2.0","id":1,"result":{...}}
>>> 0001234.620 {"jsonrpc":"2.0","method":"textDocument/didOpen","params":{...}}
```

`>>>` = client → server, `<<<` = server → client. Each language server
gets its own line prefix `[<lang>:<root-basename>]` so multi-server logs
remain readable.

Plugin-log header on every startup: plugin version, gedit version, libpeas
version, Python version, OS string. Required for triaging bug reports.

## 9. Internationalization

`gettext` infrastructure from day one. Every user-visible string wrapped
in `_()`. v0.1.0-alpha ships English only, with the infrastructure in
place so translations can be added without code changes.

Layout:

```
po/
├── gedit-lsp.pot          (template, regenerated from sources)
├── LINGUAS                (list of supported locales)
└── <locale>.po            (one per translation, none in v0.1.0-alpha)
```

`Makefile` targets: `make pot` (regenerate template), `make mo` (compile
all .po files to installed .mo files).

## 10. Security & Privacy

- **One config file is read.** Only `$XDG_CONFIG_HOME/gedit/lsp-plugin.json`.
  The plugin **does not** read per-project config files (e.g. a
  hypothetical `.gedit-lsp.json`). Rationale: a malicious project could
  otherwise execute arbitrary commands by dropping such a file.
- **No telemetry, no network calls** by the plugin itself. The plugin
  only spawns user-configured language servers; what those servers do is
  the server's contract with the user.
- **Servers run with the user's privileges**, no sandboxing. The user is
  responsible for trusting the servers they configure.
- **License obligations** stop at the source/runtime boundary. The
  plugin source is MIT (Section 16). When loaded into gedit at runtime,
  the resulting combined work is governed by GPL-2.0-or-later, which is
  gedit's licence. The plugin source may be reused under MIT terms in
  any project, including non-GPL projects.

Documented in `docs/security.md` and `docs/license.md`.

## 11. Testing

### 11.1 Unit tests

Run on every commit, no gedit dependency, pure pytest. `Gtk.TextBuffer`
instances are available without a display (no `Gtk.Window` is
constructed).

| File | Pins down |
|---|---|
| `test_utf16.py` | The two converter functions. ASCII, BMP, surrogate-pair, empty strings, end-of-line, multi-line, lines with only a surrogate pair. **Property test with `hypothesis`**: round-trip `text_iter_to_utf16(utf16_to_text_iter(buf, line, char))` is identity for any (line_text, valid_unit_offset). |
| `test_config.py` | Built-in defaults load. User overrides at language-key level (no merge). Missing user file is fine. Malformed JSON falls back to defaults + warns. `Gio.FileMonitor` triggers reload. |
| `test_root_resolver.py` | Marker walk on tmp-dir fixtures. Multiple markers → first found wins. Nested projects → inner wins. No markers → file's own dir. Symlinks resolved. |
| `test_rpc_framing.py` | Encode/decode of `Content-Length` framed JSON, including UTF-8 with multi-byte content. Split-buffer decode (header arrives in two reads). Multiple messages in one read. Strict `\r\n`. |
| `test_state_machine.py` | LanguageServer state transitions. Crash from READY clears state. Backoff schedule is correct. New attach during IDLE cancels timer. |

### 11.2 Integration tests

Require `pylsp` installed. Pytest fixture `lsp_server` builds a real
`LanguageServer` against a real `pylsp` subprocess, scoped to a tmp dir.
Each test creates a fixture project, opens a buffer (a `Gtk.TextBuffer`
populated from disk — no `Gedit.Window`), drives `DocumentBridge`
directly, asserts the controller's effect on the buffer.

Tests:

- `test_diagnostics_e2e.py` — Python file with deliberate
  `import nonexistent` → one error tag spanning the right range.
- `test_hover_e2e.py` — cursor on `os.path.join` → response contains
  `"join"` in the rendered popover text.
- `test_definition_e2e.py` — cursor on a name defined three lines above
  → resulting `Location` matches expected `(line, range)`.
- `test_outline_e2e.py` — file with a class containing two methods →
  3-node hierarchical symbol tree.

### 11.3 Manual smoke test

`docs/manual-smoke-test.md` checklist. Required to pass 100% before
cutting an alpha release.

- Open Python file → squiggle on syntax error within 2 s.
- Save → squiggle updates.
- Ctrl+K on a known symbol → popover shows.
- Ctrl+. on a function call → jumps to definition. Alt+Left returns.
- Toggle plugin off → all squiggles, marks, panels disappear; gedit
  doesn't crash.
- Open second window with same file → both windows route to the same
  server (verify via `pgrep -c pylsp`).
- Edit user config to set bogus command → after backoff exhausted,
  inline crash-loop notification appears with [Restart] [Open log]
  [Disable] buttons.

### 11.4 What we don't test

End-to-end activation of `WindowActivatable.do_activate()` in a real
`Gedit.Window`. Doing so would require launching gedit, which means a
display, which means Xvfb in CI. The cost-to-value ratio is bad; manual
smoke test covers it.

## 12. Project Layout

```
gedit-lsp-plugin/
├── README.md
├── LICENSE                         (MIT)
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── pyproject.toml                  (dev deps only: pytest, ruff, mypy, hypothesis, pyfakefs)
├── Makefile                        (install / uninstall / test / pot / mo / dist)
├── install.sh                      (one-liner copy-paste install script)
├── src/
│   └── gedit_lsp/
│       ├── __init__.py             (exposes plugin class for libpeas)
│       ├── plugin.py               (GeditLspPlugin — WindowActivatable)
│       ├── config.py               (Config, defaults loader, file monitor)
│       ├── defaults.py             (BUILTIN_SERVERS, marker list)
│       ├── registry.py             (ServerRegistry, idle-kill timer)
│       ├── server.py               (LanguageServer state machine)
│       ├── rpc.py                  (RpcClient — JSON-RPC framing over GIO)
│       ├── bridge.py               (DocumentBridge — per-buffer)
│       ├── root.py                 (ProjectRootResolver)
│       ├── utf16.py                (the converter pair)
│       ├── log.py                  (rotating logger setup, two streams)
│       ├── i18n.py                 (gettext setup, _() export)
│       ├── features/
│       │   ├── diagnostics.py
│       │   ├── hover.py
│       │   ├── definition.py
│       │   └── outline.py
│       └── ui/
│           ├── statusbar.py
│           ├── diagnostics_panel.py
│           ├── crash_notify.py     (in-buffer crash-loop notification)
│           └── prefs.py
├── data/
│   └── gedit-lsp.plugin            (libpeas manifest)
├── po/
│   ├── gedit-lsp.pot
│   └── LINGUAS
├── tests/
│   ├── unit/
│   │   ├── test_utf16.py
│   │   ├── test_config.py
│   │   ├── test_root_resolver.py
│   │   ├── test_rpc_framing.py
│   │   └── test_state_machine.py
│   ├── integration/
│   │   ├── conftest.py
│   │   ├── test_diagnostics_e2e.py
│   │   ├── test_hover_e2e.py
│   │   ├── test_definition_e2e.py
│   │   └── test_outline_e2e.py
│   └── fixtures/
└── docs/
    ├── install.md
    ├── configure.md
    ├── uninstall.md
    ├── troubleshooting.md
    ├── security.md
    ├── license.md
    ├── protocol-coverage.md
    ├── architecture.md
    ├── development.md
    ├── contributing.md
    ├── manual-smoke-test.md
    ├── roadmap.md
    └── superpowers/
        └── specs/
            └── 2026-05-02-gedit-lsp-plugin-design.md
```

`gedit-lsp.plugin` (libpeas-1.0):

```ini
[Plugin]
Module=gedit_lsp
Loader=python3
IAge=3
Name=LSP
Description=Language Server Protocol client for gedit
Authors=Alfred Mickautsch <alfred@mickautsch.de>
Copyright=Copyright © 2026 Alfred Mickautsch (MIT-licensed source; combined work GPL-2.0+)
Website=
Version=0.1.0
```

## 13. Build / Install

User-local install only in v0.1.0-alpha. System install (root) is not
shipped — distros that want it can package the plugin themselves.

`Makefile` top-level targets:

```
make install            → copy src/gedit_lsp/ + data/gedit-lsp.plugin
                          to ~/.local/share/gedit/plugins/
make uninstall          → rm -rf the above and the log directory
make test               → pytest tests/unit
make test-integration   → pytest tests/integration  (requires pylsp on PATH)
make pot                → regenerate po/gedit-lsp.pot
make mo                 → compile po/*.po → installed .mo
make dist               → tarball into dist/gedit-lsp-plugin-<version>.tar.gz
```

`pyproject.toml` is **not** used to install the plugin (libpeas does not
go through pip); it declares dev dependencies only.

## 14. Continuous Integration

Single GitHub Actions workflow `ci.yml` on push and pull-request:

- **lint** — ruff + mypy.
- **unit** — pytest tests/unit on Python 3.10, 3.11, 3.12.
- **integration** — pytest tests/integration after
  `apt-get install python3-pylsp` (Ubuntu only).
- **doc-gate** — fails if any file under `src/gedit_lsp/features/` was
  modified but `docs/configure.md` and `docs/protocol-coverage.md` were
  not. Enforces the doc-PR-with-feature-PR rule.

No coverage gate. Coverage on UI shell code is meaningless. The high-risk
modules (`utf16.py`, `rpc.py`, `root.py`) are watched manually and should
be ≥95%.

## 15. Documentation Deliverables

Required for v0.1.0-alpha:

| File | Audience | Content |
|---|---|---|
| `README.md` | first-time visitor | Elevator pitch, screenshot, install one-liner, links |
| `docs/install.md` | end user | Dependencies (gedit ≥46, libpeas-1.0, GtkSourceView-4, Python ≥3.10, GIR bindings), per-distro install commands (Debian/Ubuntu apt, Fedora dnf, Arch pacman, openSUSE zypper), Flatpak gedit caveats (does not work in Flatpak gedit — sandbox blocks server spawn), language-server install hints, copy-paste installation transcript with `set -ex`, post-install verification checklist |
| `docs/configure.md` | end user | Full config schema, every key documented (type/default/example), recipe section for common needs (switch Python from pylsp to pyright; disable a server; per-project override) |
| `docs/uninstall.md` | end user | Exact list of files installed (with paths), exact `rm` commands, log directory removal, config removal, clean-uninstall verification |
| `docs/troubleshooting.md` | end user | Decision tree by symptom (no squiggles, stuck STARTING, hover empty, line numbers wrong); how to enable LSP traffic log; how to read it |
| `docs/security.md` | user / contributor | Section 10 content as a permanent doc |
| `docs/license.md` | user / contributor | The MIT-source / GPL-runtime distinction |
| `docs/protocol-coverage.md` | curious user | LSP request/notification matrix: implemented / planned / out-of-scope (Appendix B) |
| `docs/architecture.md` | contributor | High-level architecture (mirrors Section 3, but kept in sync as design evolves) |
| `docs/development.md` | contributor | Run gedit against source tree without installing (`GEDIT_PLUGINS_PATH`), debugging, log inspection |
| `docs/contributing.md` | contributor | PR guidelines, code style (ruff config), test requirements, doc-update requirement |
| `docs/manual-smoke-test.md` | release manager | Section 11.3 checklist |
| `docs/roadmap.md` | curious user | v0.2/v0.3 plans, definition of v1.0.0 readiness |
| Inline docstrings | reader of source | Module-level on each module, function-level on every public function |

**Doc-PR rule.** No feature PR merges without its corresponding doc updates.
Enforced by the `doc-gate` CI check.

## 16. License

Plugin source code is licensed under the **MIT License** (full text in
`LICENSE`). When the plugin is loaded into gedit at runtime, the resulting
combined work is governed by GPL-2.0-or-later (gedit's licence). The
plugin source may be reused under MIT terms in any project, including
non-GPL projects.

This arrangement is documented prominently in `README.md` and
`docs/license.md`.

## 17. Release Process

### 17.1 Definition of "alpha-ready"

The gate for cutting `v0.1.0-alpha`:

1. All four features (diagnostics, hover, definition, outline) work
   end-to-end against `pylsp` on the integration-test fixtures.
2. The manual smoke-test checklist passes 100% on Ubuntu 24.04 + gedit 46.
3. All unit and integration tests green in CI on every supported Python.
4. `docs/install.md`, `docs/configure.md`, `docs/uninstall.md`,
   `docs/troubleshooting.md` complete.
5. `CHANGELOG.md` has a `0.1.0-alpha` entry listing every implemented
   feature.

### 17.2 Mechanics

GitHub Actions workflow `release.yml` triggered on tag `v*`:

- Runs the full test suite.
- Builds `dist/gedit-lsp-plugin-<version>.tar.gz` containing
  `src/gedit_lsp/`, `data/gedit-lsp.plugin`, `Makefile`, `install.sh`,
  `README.md`, all `docs/*`, `LICENSE`, `CHANGELOG.md`.
- Computes SHA-256 of the tarball.
- Creates a GitHub Release marked **pre-release**, body auto-extracted
  from the relevant `CHANGELOG.md` section, attaches the tarball and
  `.sha256` file.

### 17.3 Versioning

Semver from day one.

- `0.1.0-alpha` — first usable release (this design).
- `0.1.0-beta` — once external testers have reported back without
  blocker bugs.
- `0.1.0` — once stable.
- `0.2.0-alpha` adds completion (scope C) — out of scope for this spec.
- `1.0.0` — completion shipped, ≥ 6 months on stable releases without
  regression-class bugs, at least one translation other than English
  shipped. Documented in `docs/roadmap.md`.

No GPG signing in alpha. Added at `1.0.0`.

## 18. Roadmap (Out of Scope for v0.1.0-alpha)

Tracked in `docs/roadmap.md`:

- v0.1.0-beta: items deferred from alpha that were originally proposed:
  surface server stderr via menu action, evaluation/screenshot script,
  v1.0.0 readiness criteria.
- v0.2.0: scope C — completion (`textDocument/completion` via
  `GtkSourceCompletionProvider`), signature help, snippets opt-in.
- v0.3.0: incremental sync, mouse-hover trigger, `$/progress`,
  `workspace/didChangeWatchedFiles`.
- v0.4.0: rename, code actions, formatting, references, workspace
  symbols (scope D from the original brainstorming).
- Beyond: Flatpak gedit support (requires sandbox handshake), system
  install, GPG-signed releases.

---

## Appendix A — Complete Tunables Schema

Full `tunables` section of the JSON config. All have defaults baked in;
users only specify keys they want to change.

```json
{
  "tunables": {
    "serverIdleTimeoutSeconds": 300,
    "changeDebounceMs": 150,
    "outlineRefreshDebounceMs": 2000,
    "outlineInitialDelayMs": 1000,
    "hoverSpinnerThresholdMs": 300,
    "requestTimeoutMs": 10000,
    "gotoHistoryMaxEntries": 50,
    "restartBackoffSchedule": [1, 2, 4, 8, 16, 30],
    "restartMaxAttempts": 5,
    "logLevel": "info",
    "logRotationMaxBytes": 5242880,
    "logRotationKeepFiles": 3,
    "logLspTraffic": false,
    "maxFileSizeBytes": 5242880,
    "showStatusbarIndicator": true,
    "enabledFeatures": ["diagnostics", "hover", "definition", "outline"],
    "severityIcons": {
      "error":   "dialog-error-symbolic",
      "warning": "dialog-warning-symbolic",
      "info":    "dialog-information-symbolic",
      "hint":    "dialog-information-symbolic"
    },
    "severityUnderlineStyle": {
      "error":   "error",
      "warning": "error",
      "info":    "single",
      "hint":    "single"
    },
    "disabledForPaths": [
      "**/.venv/**",
      "**/node_modules/**",
      "**/.tox/**",
      "**/dist/**",
      "**/build/**"
    ],
    "serverCapabilityOverrides": {}
  }
}
```

`serverCapabilityOverrides` is an escape hatch: an object keyed by
language ID, value is a partial server-capabilities document that is
**deep-merged on top of** the capabilities the server claimed in its
`initialize` response. Per-key replacement at every depth (e.g.
`{"python": {"hoverProvider": false}}` disables hover for Python
without touching anything else the server advertised). Use only when a
server lies about its own capabilities (rare).

## Appendix B — LSP Request/Notification Coverage

| Method | v0.1.0-alpha | v0.2.0 | v0.3.0 | v0.4.0 |
|---|---|---|---|---|
| `initialize` / `initialized` / `shutdown` / `exit` | ✓ | | | |
| `textDocument/didOpen` / `didChange` (Full) / `didSave` / `didClose` | ✓ | | | |
| `textDocument/publishDiagnostics` | ✓ | | | |
| `textDocument/hover` | ✓ | | | |
| `textDocument/definition` | ✓ | | | |
| `textDocument/documentSymbol` | ✓ | | | |
| `textDocument/completion` / `resolve` | | ✓ | | |
| `textDocument/signatureHelp` | | ✓ | | |
| `textDocument/didChange` (Incremental) | | | ✓ | |
| `$/progress` | | | ✓ | |
| `workspace/didChangeWatchedFiles` | | | ✓ | |
| `textDocument/rename` / `prepareRename` | | | | ✓ |
| `textDocument/codeAction` | | | | ✓ |
| `textDocument/formatting` / `rangeFormatting` | | | | ✓ |
| `textDocument/references` | | | | ✓ |
| `workspace/symbol` | | | | ✓ |
| `$/cancelRequest` | ✓ (client → server) | | | |
| `window/showMessage` / `logMessage` | log only | | | |
| `window/showMessageRequest` | | | | (deferred, low value) |
