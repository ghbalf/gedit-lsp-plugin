# Installing the gedit LSP plugin

## Requirements

- gedit ≥ 46
- libpeas-1.0
- libgedit-gtksourceview (a GTK3-compatible GtkSourceView fork that gedit
  links against; exposes the GObject namespace `GtkSource-300`)
- Python ≥ 3.10
- GObject introspection bindings: `python3-gi`, `gir1.2-gtk-3.0`,
  `gir1.2-gtksource-300`

### Per-distro install commands

**Debian / Ubuntu (24.04+):**

```bash
sudo apt install gedit python3-gi gir1.2-gtk-3.0 gir1.2-gtksource-300
```

**Fedora (39+):**

```bash
sudo dnf install gedit python3-gobject gtksourceview4
```

**Arch / Manjaro:**

```bash
sudo pacman -S gedit python-gobject gtksourceview4
```

**openSUSE Tumbleweed:**

```bash
sudo zypper install gedit python3-gobject typelib-1_0-GtkSource-4
```

### Flatpak gedit caveat

The Flatpak build of gedit runs in a sandbox that cannot spawn host
binaries like `pylsp` or `clangd`. **The plugin will not function under
Flatpak gedit.** Install the distro-package version of gedit instead.

## Install the plugin

### From a release tarball (recommended for users)

```bash
curl -LO https://github.com/<your-account>/gedit-lsp-plugin/releases/download/v0.1.0-alpha/gedit-lsp-plugin-0.1.0a0.tar.gz
curl -LO https://github.com/<your-account>/gedit-lsp-plugin/releases/download/v0.1.0-alpha/gedit-lsp-plugin-0.1.0a0.tar.gz.sha256
sha256sum -c gedit-lsp-plugin-0.1.0a0.tar.gz.sha256
tar xzf gedit-lsp-plugin-0.1.0a0.tar.gz
cd gedit-lsp-plugin-0.1.0a0
make install
```

### From source (recommended for developers)

```bash
git clone https://github.com/<your-account>/gedit-lsp-plugin
cd gedit-lsp-plugin
make install
```

Both paths copy:

- `src/gedit_lsp/` → `~/.local/share/gedit/plugins/gedit_lsp/`
- `data/gedit-lsp.plugin` → `~/.local/share/gedit/plugins/gedit-lsp.plugin`

## Install language servers

Install the servers for the languages you use. Examples:

| Language | Server | Install command |
|---|---|---|
| Python | pylsp | `sudo apt install python3-pylsp python3-pyflakes python3-pycodestyle` or `pip install --user 'python-lsp-server[all]'` — the apt `python3-pylsp` package does **not** pull the analyzers (pyflakes/pycodestyle) as dependencies; without them pylsp connects but publishes no diagnostics |
| C / C++ | clangd | `sudo apt install clangd` |
| Rust | rust-analyzer | `rustup component add rust-analyzer` |
| Go | gopls | `go install golang.org/x/tools/gopls@latest` |
| TypeScript / JavaScript | typescript-language-server | `npm install -g typescript typescript-language-server` |
| Bash | bash-language-server | `npm install -g bash-language-server` |

The plugin auto-detects whichever servers are on `$PATH` at startup.

## Enable the plugin

1. Restart gedit.
2. **Edit → Preferences → Plugins**.
3. Tick **LSP**.

## Verify it works

```bash
echo "import nonexistent_module_xyz" > /tmp/test.py
gedit /tmp/test.py
```

Within a few seconds, a red squiggle should appear under
`nonexistent_module_xyz` and the row should appear in the *LSP
Diagnostics* bottom panel.

If it doesn't work, see `docs/troubleshooting.md`.
