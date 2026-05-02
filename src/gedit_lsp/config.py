"""Config loader and accessors.

Loads ~/.config/gedit/lsp-plugin.json and merges it with the built-in
defaults. The merge policy is intentionally simple:

    servers          — full replacement at language-key level (no per-key merge)
    rootMarkers      — full replacement at language-key level
    initializationOptions — full replacement at language-key level
    tunables         — per-key replacement (top level only)
    serverCapabilityOverrides — preserved verbatim; deep-merge into the
                       server's claimed capabilities is performed by the
                       LanguageServer at initialize time.

Reload-on-change wiring (Gio.FileMonitor) is added in Task M2.4.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from gedit_lsp.defaults import BUILTIN_SERVERS, DEFAULT_ROOT_MARKERS, DEFAULT_TUNABLES


class ConfigError(Exception):
    """Could not load the user config file."""


class Config:
    def __init__(self, user_path: Path) -> None:
        self._user_path = user_path
        self._servers: dict[str, dict[str, Any]] = {}
        self._root_markers: dict[str, list[str]] = {}
        self._initialization_options: dict[str, Any] = {}
        self._tunables: dict[str, Any] = {}

    def load(self) -> None:
        self._servers = copy.deepcopy(BUILTIN_SERVERS)
        self._root_markers = {}
        self._initialization_options = {}
        self._tunables = copy.deepcopy(DEFAULT_TUNABLES)

        if not self._user_path.exists():
            return

        try:
            user = json.loads(self._user_path.read_text())
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"failed to parse {self._user_path}: {exc.msg} at line {exc.lineno}"
            ) from exc

        for lang, entry in (user.get("servers") or {}).items():
            self._servers[lang] = entry  # full replacement

        for lang, markers in (user.get("rootMarkers") or {}).items():
            self._root_markers[lang] = list(markers)

        for lang, opts in (user.get("initializationOptions") or {}).items():
            self._initialization_options[lang] = opts

        for k, v in (user.get("tunables") or {}).items():
            self._tunables[k] = v

    def server_for(self, language_id: str) -> dict[str, Any] | None:
        return self._servers.get(language_id)

    def root_markers_for(self, language_id: str) -> list[str]:
        return self._root_markers.get(language_id, list(DEFAULT_ROOT_MARKERS))

    def initialization_options_for(self, language_id: str) -> Any:
        return self._initialization_options.get(language_id)

    def tunable(self, key: str) -> Any:
        return self._tunables[key]
