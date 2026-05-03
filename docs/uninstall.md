# Uninstalling the gedit LSP plugin

## Files installed

| Path | Created when |
|---|---|
| `~/.local/share/gedit/plugins/gedit_lsp/` | `make install` |
| `~/.local/share/gedit/plugins/gedit-lsp.plugin` | `make install` |
| `~/.local/share/gedit/plugins/locale/<lang>/LC_MESSAGES/gedit-lsp.mo` | `make mo` |
| `~/.local/state/gedit-lsp/plugin.log[.1..N]` | first plugin run |
| `~/.local/state/gedit-lsp/lsp-traffic.log[.1..N]` | only if `logLspTraffic: true` |
| `~/.config/gedit/lsp-plugin.json` | only if you created it |

## Quick uninstall (Makefile target)

```bash
cd /path/to/gedit-lsp-plugin   # or extracted release tarball
make uninstall
```

`make uninstall` removes:

- the plugin source dir
- the manifest
- the entire log directory (`~/.local/state/gedit-lsp/`)

It does **not** touch your user config (`~/.config/gedit/lsp-plugin.json`)
because that's your data.

## Manual uninstall

```bash
rm -rf ~/.local/share/gedit/plugins/gedit_lsp
rm -f ~/.local/share/gedit/plugins/gedit-lsp.plugin
rm -rf ~/.local/state/gedit-lsp
# Optional — only if you want to wipe your settings too:
rm -f ~/.config/gedit/lsp-plugin.json
```

## Verify clean uninstall

```bash
ls ~/.local/share/gedit/plugins/      # should not contain gedit_lsp
ls ~/.local/state/                    # should not contain gedit-lsp
```

Restart gedit; the plugin should no longer appear in **Edit → Preferences
→ Plugins**.
