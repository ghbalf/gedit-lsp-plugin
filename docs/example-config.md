# Walkthrough: `example-config.json`

A companion to [`example-config.json`](example-config.json), which exercises
every configurable parameter the plugin currently understands. Copy the JSON
file to `~/.config/gedit/lsp-plugin.json`, then trim the bits you don't want.

For the full reference of each key (types, defaults), see
[`configure.md`](configure.md). This page only narrates the example.

## `servers`

```json
"servers": {
  "python":  { "command": ["pylsp"] },
  "rust":    { "command": ["rust-analyzer"] },
  "haskell": { "command": ["haskell-language-server-wrapper", "--lsp"] }
}
```

A user `servers` entry **fully replaces** the built-in entry for the same
language. Add an entry only for languages whose built-in command you want to
change, or for languages the plugin doesn't ship a default for (here:
`haskell`). Languages you don't mention keep their built-in command.

Only `command` is read from a server entry. Putting `rootMarkers` or
`initializationOptions` *inside* a server entry will be silently ignored —
those are separate top-level keys (see below).

## `rootMarkers`

```json
"rootMarkers": {
  "python":  ["pyproject.toml", "setup.py", ".git"],
  "rust":    ["Cargo.toml", ".git"],
  "haskell": ["stack.yaml", "cabal.project", ".git"]
}
```

Per-language override of the upward project-root walk. A language that has
no entry here uses the global default list (`.git`, `pyproject.toml`,
`Cargo.toml`, `package.json`, etc. — see `defaults.py`). There is no global
override; if you want to change root detection for *all* languages, list
each language explicitly.

## `initializationOptions`

```json
"initializationOptions": {
  "python": {
    "pylsp": {
      "plugins": {
        "pylsp_mypy":      { "enabled": true, "live_mode": true },
        "pycodestyle":     { "enabled": false },
        "pyflakes":        { "enabled": true },
        "rope_completion": { "enabled": true }
      }
    }
  }
}
```

Forwarded verbatim to the server's `initialize` request, and (for pylsp)
also pushed via `workspace/didChangeConfiguration` after initialize. The
latter is required for some pylsp plugins (`pylsp_mypy`, `pylsp-rope`) to
activate; the plugin handles this transparently.

See [`configure.md` → "Add error-severity diagnostics for unresolved Python
imports"](configure.md#add-error-severity-diagnostics-for-unresolved-python-imports-pylsp-mypy)
for installation notes on `pylsp-mypy`.

## `keybindings`

```json
"keybindings": {
  "hover":            "<Primary>i",
  "goto-definition":  ["F12", "<Primary>F12"],
  "go-back":          "<Shift>F12",
  "show-server-logs": "F11"
}
```

The four built-in actions:

| Action | What it does |
|---|---|
| `hover` | Show hover popover at cursor |
| `goto-definition` | Jump to definition |
| `go-back` | Pop the cursor history |
| `show-server-logs` | Open recent server stderr (no default chord) |

Accel value forms — all four are accepted:

```json
"hover":            "<Primary>i",                   // single string
"goto-definition":  ["F12", "<Primary>F12"],        // list (any one fires)
"go-back":          "",                             // empty string disables
"show-server-logs": null                            // null disables
```

Disabling only removes the **keyboard** binding. The action stays in the
right-click LSP submenu either way.

Avoid these chords — GtkSourceView's view-level binding set claims them
before the window's accel map gets a look in:

- `<Alt>Left` / `<Alt>Right` (GtkSourceView swaps adjacent words —
  *destructively*).
- `<Alt>Up` / `<Alt>Down` (move line up/down).
- `<Primary>period` (emoji chooser).

## `tunables`

Every key here can be omitted — missing keys keep their built-in default.
The example sets several to non-default values to make the override visible;
your real config can be much shorter.

### Lifecycle and timeouts

```json
"serverIdleTimeoutSeconds":  600,
"changeDebounceMs":          200,
"outlineRefreshDebounceMs":  2500,
"outlineInitialDelayMs":     1000,
"hoverSpinnerThresholdMs":   300,
"requestTimeoutMs":          15000,
"gotoHistoryMaxEntries":     100
```

`serverIdleTimeoutSeconds` is wall-clock idleness *after the last buffer
closes*. Set higher on slow machines so a server doesn't have to re-warm
every time you reopen the project. `requestTimeoutMs` is per request —
raise it if you work with a slow server (e.g. cold rust-analyzer on a large
crate).

### Crash recovery

```json
"restartBackoffSchedule":  [1, 2, 4, 8, 16, 30],
"restartMaxAttempts":      5
```

After a crash, the supervisor waits `schedule[i]` seconds before restart
attempt `i`. After `restartMaxAttempts` consecutive crashes the circuit
breaker trips and the server is left dead until you restart gedit (or the
config changes). Picking a longer schedule with fewer attempts is friendlier
on a flaky server; picking a shorter schedule with more attempts is right
for transient hiccups.

### Logging

```json
"logLevel":              "info",
"logRotationMaxBytes":   5242880,
"logRotationKeepFiles":  3,
"logLspTraffic":         false
```

`logLevel` is one of `debug`, `info`, `warning`, `error`. `logLspTraffic`
writes every wire message to a separate `lsp-traffic.log` — useful for bug
reports, but the file grows fast under heavy editing. Logs live under
`~/.local/state/gedit-lsp/`.

### Buffer / UI guards

```json
"maxFileSizeBytes":       5242880,
"showStatusbarIndicator": true,
"stderrBufferMaxLines":   1000
```

`maxFileSizeBytes` is a hard cutoff: buffers larger than this are skipped
entirely (no didOpen, no diagnostics). `stderrBufferMaxLines` is per server
— how many recent stderr lines the **Show Server Logs…** dialog can show.

### Features

```json
"enabledFeatures": ["diagnostics", "hover", "definition", "outline", "completion"]
```

Recognised values: `diagnostics`, `hover`, `definition`, `outline`,
`completion`. Any other string is silently ignored. Removing one disables
that feature plugin-wide; you can also disable a single feature for a
single language by overriding the server's capability — see
`serverCapabilityOverrides` below.

### Diagnostic visuals

```json
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
"severityUnderlineColor": {
  "error":   "#e01b24",
  "warning": "#e5a50a",
  "info":    "#62a0ea",
  "hint":    ""
}
```

`severityIcons` takes any icon name available in the GTK icon theme — the
`-symbolic` variants are theme-tinted and look right in both light and dark
themes.

`severityUnderlineStyle` accepts only three values: `"error"` (Pango's
wavy underline), `"single"`, or `"none"`. Anything else falls back to
`"error"`.

`severityUnderlineColor` is a CSS-style hex string. **Setting a value to
the empty string falls back to the theme's default underline color** —
useful for `hint`, where a custom grey often clashes with a dark theme.

### Path filters

```json
"disabledForPaths": [
  "**/.venv/**", "**/node_modules/**", "**/.tox/**",
  "**/dist/**",  "**/build/**",        "**/vendor/**",
  "**/generated/**"
]
```

Glob patterns matched against the absolute file path. A buffer matching any
glob is skipped: no LSP server is started for it, no didOpen is sent. Most
users only need to extend the list (e.g. with `**/vendor/**` and
`**/generated/**`).

### Server capability overrides

```json
"serverCapabilityOverrides": {
  "c":      { "completionProvider": { "triggerCharacters": [".", "->"] } },
  "cpp":    { "completionProvider": { "triggerCharacters": [".", "->", "::"] } },
  "python": { "hoverProvider": true }
}
```

Deep-merged on top of whatever the server reports back from `initialize`.
Use it to:

- **Disable a feature per language.** `{ "python": { "hoverProvider":
  false } }` turns off hover for Python only, even though pylsp claims to
  support it.
- **Cap a noisy capability.** clangd's default trigger characters include
  many that fire spuriously; the example narrows them to `.` and `->`
  (plus `::` for C++).
- **Override a server that under-reports.** Some servers omit capabilities
  they actually have; flipping the bool here makes the plugin trust them.

## What's missing from the example?

If you find a knob you can configure that isn't in `example-config.json`,
that's a docs bug — please file an issue. The example is meant to be the
canonical "everything you can change" reference.
