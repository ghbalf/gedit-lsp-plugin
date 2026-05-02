"""Project-root resolution.

Walks upward from a buffer's file looking for any of the configured marker
files. Stops at the user's home directory or the filesystem root and
falls back to the file's own parent directory if no marker is found.

Symlinks are resolved before walking so the same physical file always
maps to the same root, regardless of which symlink path the user opened.
"""
from __future__ import annotations

from pathlib import Path


class ProjectRootResolver:
    def __init__(self, markers: list[str]) -> None:
        self._markers = list(markers)

    def resolve(self, file_path: Path) -> Path:
        path = file_path.resolve()
        current = path.parent if path.is_file() else path
        home = Path.home().resolve()
        fs_root = Path(path.anchor).resolve()
        while True:
            for marker in self._markers:
                if (current / marker).exists():
                    return current
            if current in (home, fs_root):
                return path.parent
            parent = current.parent
            if parent == current:
                return path.parent
            current = parent
