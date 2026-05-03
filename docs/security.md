# Security & Privacy

## Single config file

The plugin reads exactly one config file:
`$XDG_CONFIG_HOME/gedit/lsp-plugin.json` (typically
`~/.config/gedit/lsp-plugin.json`).

It **does not** read per-project config files (e.g. a hypothetical
`.gedit-lsp.json` placed in a project directory). This is deliberate: a
malicious project could otherwise execute arbitrary commands by dropping
such a file in its tree.

If you want per-project servers, edit your global config to add the
project's specific server entry, or change the project root via
`rootMarkers` so each project gets its own server instance.

## No telemetry, no network

The plugin makes no network calls. It only spawns user-configured
language servers; what those servers do is entirely the server's
responsibility.

## Servers run with user privileges

Spawned servers run as the user, with no sandboxing. Trust your servers.

## License obligations

The plugin source is MIT (`LICENSE`). Loaded into gedit at runtime, the
combined work is governed by GPL-2.0-or-later (gedit's license). The
plugin source may be reused under MIT terms in any project, including
non-GPL projects. See `docs/license.md`.
