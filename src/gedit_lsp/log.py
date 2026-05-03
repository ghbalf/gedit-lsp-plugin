"""Two log streams: plugin diagnostic + LSP traffic.

The plugin log uses standard Python `logging` with a `RotatingFileHandler`.
The traffic log is line-streamed (one wire message per line) and uses a
small custom rotator so we don't pay record-formatting overhead.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


_traffic_file: IO[str] | None = None
_traffic_path: Path | None = None
_traffic_max_bytes: int = 5_242_880
_traffic_keep: int = 3


def setup_logging(
    state_dir: Path,
    level: str,
    traffic_enabled: bool,
    max_bytes: int,
    keep: int,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    plugin_log = state_dir / "plugin.log"

    logger = logging.getLogger("gedit_lsp")
    logger.setLevel(_LEVELS.get(level, logging.INFO))
    # Remove any prior handlers (idempotent)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = RotatingFileHandler(
        plugin_log, maxBytes=max_bytes, backupCount=keep, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    # Force flush on every record (rotation tests rely on this)
    handler.flush()

    global _traffic_file, _traffic_path, _traffic_max_bytes, _traffic_keep
    _traffic_max_bytes = max_bytes
    _traffic_keep = keep
    if _traffic_file is not None:
        _traffic_file.close()
        _traffic_file = None
    if traffic_enabled:
        _traffic_path = state_dir / "lsp-traffic.log"
        _traffic_file = open(_traffic_path, "a", encoding="utf-8")  # noqa: SIM115


def write_traffic(direction: str, prefix: str, ts_ms: float, body: bytes) -> None:
    """Append one wire message to the traffic log.

    `direction` is `>>>` (client to server) or `<<<` (server to client).
    `prefix` is `[<lang>:<root-basename>]`.
    """
    if _traffic_file is None or _traffic_path is None:
        return
    line = f"{direction} {ts_ms:013.3f} {prefix} {body.decode('utf-8', 'replace')}\n"
    _traffic_file.write(line)
    _traffic_file.flush()
    if _traffic_path.stat().st_size >= _traffic_max_bytes:
        _rotate_traffic()


def _rotate_traffic() -> None:
    global _traffic_file
    if _traffic_path is None:
        return
    if _traffic_file is not None:
        _traffic_file.close()
    for i in range(_traffic_keep, 0, -1):
        if i == 1:
            src = _traffic_path
        else:
            src = _traffic_path.with_suffix(_traffic_path.suffix + f".{i - 1}")
        dst = _traffic_path.with_suffix(_traffic_path.suffix + f".{i}")
        if src.exists():
            src.replace(dst)
    _traffic_file = open(_traffic_path, "a", encoding="utf-8")  # noqa: SIM115
