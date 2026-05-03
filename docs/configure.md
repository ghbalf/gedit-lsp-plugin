# Configuring the gedit LSP plugin

The plugin reads a single JSON config file:

```
~/.config/gedit/lsp-plugin.json
```

Missing keys fall through to built-in defaults.

## Top-level structure

```json
{
  "servers": {            "<lang-id>": { "command": ["..."] } },
  "rootMarkers": {        "<lang-id>": ["...", "..."] },
  "initializationOptions": { "<lang-id>": { } },
  "tunables": { /* see below */ }
}
```

`<lang-id>` matches the GtkSourceView language ID (`python`, `c`, `cpp`,
`rust`, `go`, `typescript`, `js`, `sh`, `haskell`, …).

## `servers` — replace built-in command for a language

User entries fully replace the built-in entry for the same language.

```json
{ "servers": { "python": { "command": ["pyright-langserver", "--stdio"] } } }
```

To add a new language not in the built-ins:

```json
{ "servers": { "haskell": { "command": ["haskell-language-server-wrapper", "--lsp"] } } }
```

## `rootMarkers` — override the project-root walk

```json
{ "rootMarkers": { "python": ["pyproject.toml", ".git"] } }
```

Order in the list does not matter — the first marker found while walking
upward wins.

## `initializationOptions` — server-specific init parameters

Forwarded verbatim to the server's `initialize` request.

```json
{ "initializationOptions": {
    "python": { "pylsp": { "plugins": { "pycodestyle": { "enabled": false } } } }
  } }
```

## `tunables` — runtime knobs

Per-key replacement; missing keys keep their default.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `serverIdleTimeoutSeconds` | int | 300 | Seconds of buffer-detached idleness before the server is shut down |
| `changeDebounceMs` | int | 150 | Debounce window for `textDocument/didChange` |
| `outlineRefreshDebounceMs` | int | 2000 | Debounce window for outline refresh after edits |
| `outlineInitialDelayMs` | int | 1000 | Delay before first outline request after document open |
| `hoverSpinnerThresholdMs` | int | 300 | Show spinner if hover hasn't returned by this time |
| `requestTimeoutMs` | int | 10000 | Per-request timeout |
| `gotoHistoryMaxEntries` | int | 50 | Max entries in the cursor history (Alt+Left) |
| `restartBackoffSchedule` | int[] | `[1,2,4,8,16,30]` | Backoff delays (seconds) on consecutive crashes |
| `restartMaxAttempts` | int | 5 | After this many crashes, the circuit breaker trips |
| `logLevel` | str | `"info"` | One of `debug`, `info`, `warning`, `error` |
| `logRotationMaxBytes` | int | 5_242_880 | Max bytes per log file before rotation |
| `logRotationKeepFiles` | int | 3 | Number of historical log files retained |
| `logLspTraffic` | bool | `false` | Whether to write all wire messages to a separate traffic log |
| `maxFileSizeBytes` | int | 5_242_880 | Buffers larger than this are skipped |
| `showStatusbarIndicator` | bool | `true` | Show the LSP state indicator in the statusbar |
| `enabledFeatures` | str[] | `["diagnostics","hover","definition","outline"]` | Which features run |
| `severityIcons` | obj | (see defaults) | Per-severity gutter icon names |
| `severityUnderlineStyle` | obj | (see defaults) | Per-severity Pango underline style: `error`, `single`, `none` |
| `disabledForPaths` | str[] | (see defaults) | Glob patterns; matching buffers are skipped |
| `serverCapabilityOverrides` | obj | `{}` | Deep-merged on top of server's `initialize` response capabilities |

## Recipes

### Switch Python from pylsp to pyright

```json
{
  "servers": { "python": { "command": ["pyright-langserver", "--stdio"] } }
}
```

### Disable diagnostics globally, keep hover and definition

```json
{ "tunables": { "enabledFeatures": ["hover", "definition", "outline"] } }
```

### Disable hover for Python only (server-side)

```json
{
  "tunables": {
    "serverCapabilityOverrides": {
      "python": { "hoverProvider": false }
    }
  }
}
```

### Add additional ignore globs

```json
{
  "tunables": {
    "disabledForPaths": [
      "**/.venv/**", "**/node_modules/**", "**/vendor/**", "**/generated/**"
    ]
  }
}
```

### Enable the LSP traffic log temporarily for bug reports

```json
{ "tunables": { "logLspTraffic": true } }
```

The log appears at `~/.local/state/gedit-lsp/lsp-traffic.log`. Disable it
after debugging — the file rotates but grows fast under heavy use.
