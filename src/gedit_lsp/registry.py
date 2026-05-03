"""Process-global ServerRegistry.

Maps `(language_id, root_path)` → `LanguageServer`. Constructs servers
lazily; once a server exists for a key, future requests reuse it.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gedit_lsp.config import Config
from gedit_lsp.server import LanguageServer, Transport


class ServerRegistry:
    def __init__(
        self,
        config: Config,
        transport_factory: Callable[..., Transport],
    ) -> None:
        self._config = config
        self._transport_factory = transport_factory
        self._servers: dict[tuple[str, str], LanguageServer] = {}

    def get_or_spawn(
        self, language_id: str, root_path: Path
    ) -> LanguageServer | None:
        entry = self._config.server_for(language_id)
        if entry is None:
            return None
        key = (language_id, str(root_path))
        if key not in self._servers:
            self._servers[key] = LanguageServer(
                language_id=language_id,
                root_path=str(root_path),
                command=entry["command"],
                initialization_options=self._config.initialization_options_for(language_id),
                transport_factory=self._transport_factory,
                backoff_schedule=self._config.tunable("restartBackoffSchedule"),
                max_restart_attempts=self._config.tunable("restartMaxAttempts"),
                idle_timeout_seconds=self._config.tunable("serverIdleTimeoutSeconds"),
            )
        return self._servers[key]

    def all_servers(self) -> list[LanguageServer]:
        return list(self._servers.values())

    def shutdown_all(self) -> None:
        for server in self._servers.values():
            server.kill_now()
        self._servers.clear()
