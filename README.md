# gedit LSP plugin

[![Latest release](https://img.shields.io/github/v/release/ghbalf/gedit-lsp-plugin)](https://github.com/ghbalf/gedit-lsp-plugin/releases/latest)
[![CI](https://img.shields.io/github/actions/workflow/status/ghbalf/gedit-lsp-plugin/ci.yml?branch=main&label=CI)](https://github.com/ghbalf/gedit-lsp-plugin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![gedit ≥ 46](https://img.shields.io/badge/gedit-%E2%89%A546-orange)](docs/install.md)

Language Server Protocol client for gedit ≥ 46. Adds diagnostics, hover,
go-to-definition, document outline, and completion (with a Details pane
revealed via the popup's `Alt+D` toggle).

> Pre-1.0: APIs, config schema, and defaults may change between minor
> versions. The plugin is otherwise usable day-to-day.

## Quick start

1. **Install system deps** for your distro — see [`docs/install.md`](docs/install.md)
   (covers Debian/Ubuntu, Fedora, Arch, and the libgedit-gtksourceview
   `GtkSource-300` namespace requirement).
2. **Install the plugin** into `~/.local/share/gedit/plugins/`:

   ```bash
   ./install.sh   # or: make install
   ```

3. **Restart gedit**, then enable *gedit LSP* in *Preferences → Plugins*.
4. **Configure servers** (optional — sensible defaults ship for Python via pylsp).
   See [`docs/configure.md`](docs/configure.md) for the JSON schema and
   per-language recipes.

For LSP method coverage and known gaps, see [`docs/protocol-coverage.md`](docs/protocol-coverage.md).

## License

Plugin source code: MIT (see `LICENSE`).
When loaded into gedit at runtime, the combined work is governed by
GPL-2.0-or-later (gedit's licence). See `docs/license.md`.
