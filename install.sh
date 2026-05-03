#!/usr/bin/env bash
set -euxo pipefail

# Idempotent install of the gedit LSP plugin into ~/.local/share/gedit/plugins/
# Re-running is safe; existing files are overwritten.

PLUGIN_DIR="${HOME}/.local/share/gedit/plugins"
SRC="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "${PLUGIN_DIR}"
cp -r "${SRC}/src/gedit_lsp" "${PLUGIN_DIR}/"
cp "${SRC}/data/gedit-lsp.plugin" "${PLUGIN_DIR}/"

echo
echo "Installed gedit LSP plugin to ${PLUGIN_DIR}"
echo "Restart gedit and enable the plugin in Edit → Preferences → Plugins."
