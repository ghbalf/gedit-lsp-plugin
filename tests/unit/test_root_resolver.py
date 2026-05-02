"""Tests for project-root resolution.

Walks the directory tree upward from a buffer's file looking for marker
files, falling back to the file's own parent directory if nothing is
found.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gedit_lsp.root import ProjectRootResolver


@pytest.fixture
def resolver() -> ProjectRootResolver:
    return ProjectRootResolver(markers=[".git", "pyproject.toml", "Cargo.toml"])


def test_marker_in_immediate_parent(tmp_path: Path, resolver: ProjectRootResolver) -> None:
    (tmp_path / ".git").mkdir()
    fn = tmp_path / "src" / "a.py"
    fn.parent.mkdir(parents=True)
    fn.write_text("")
    assert resolver.resolve(fn) == tmp_path


def test_no_marker_falls_back_to_file_parent(
    tmp_path: Path, resolver: ProjectRootResolver
) -> None:
    fn = tmp_path / "loose.py"
    fn.write_text("")
    assert resolver.resolve(fn) == tmp_path


def test_inner_marker_wins_over_outer(
    tmp_path: Path, resolver: ProjectRootResolver
) -> None:
    (tmp_path / ".git").mkdir()
    inner = tmp_path / "subproj"
    (inner / "pyproject.toml").parent.mkdir()
    (inner / "pyproject.toml").write_text("")
    fn = inner / "src" / "a.py"
    fn.parent.mkdir(parents=True)
    fn.write_text("")
    assert resolver.resolve(fn) == inner


def test_walk_stops_at_filesystem_root_or_home(
    tmp_path: Path, resolver: ProjectRootResolver
) -> None:
    fn = tmp_path / "deep" / "deep" / "deep" / "a.py"
    fn.parent.mkdir(parents=True)
    fn.write_text("")
    # No markers anywhere — falls back to file's parent
    assert resolver.resolve(fn) == fn.parent


def test_symlinked_dir_resolved_to_real_path(
    tmp_path: Path, resolver: ProjectRootResolver
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / ".git").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    fn = link / "a.py"
    fn.write_text("")
    assert resolver.resolve(fn) == real.resolve()


def test_first_marker_in_list_wins_at_same_level(tmp_path: Path) -> None:
    """If a directory has multiple markers, the resolver still returns that
    directory — order in the markers list doesn't change the answer for a
    single level."""
    resolver = ProjectRootResolver(markers=[".git", "pyproject.toml"])
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("")
    fn = tmp_path / "a.py"
    fn.write_text("")
    assert resolver.resolve(fn) == tmp_path
